# app/services/eve_step678.py
#
# Module E — EVE Step 6: Aggregation + Severity Engine
# Module F — EVE Step 7: Recommendation Engine
# Module G — EVE Step 8: Clause-Level Aggregation
#
# Runs on AUDITOR side after all evidence has been evaluated (Step 5).
# Steps 6+7 run together per control activity.
# Step 8 runs after ALL control activities under a clause are done.

import json
import time
import logging
from datetime import datetime

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app import db, client
from app.models.ai import Clauses
from app.models.project_instance_models import (
    ProjectControlActivity,
    ProjectClause,
    ProjectComplianceActivity,
)
from app.models.eve_models import (
    ProjectChecklist,
    EveEvidenceResult,
    EveControlResult,
)

logger = get_task_logger(__name__)


# ─────────────────────────────────────────────────────────────
# LLM call — temperature=0 for determinism
# ─────────────────────────────────────────────────────────────

def _call_llm_json(system_msg: str, user_msg: str, retries: int = 3, backoff: float = 2.0) -> dict | None:
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                max_tokens=16000,
                temperature=0,
                top_p=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            )
            raw = response.choices[0].message.content
            if not raw:
                raise ValueError("Empty response from LLM")
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"Attempt {attempt + 1}: JSON decode error — {e}")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}: LLM call failed — {e}")

        if attempt < retries - 1:
            wait = backoff ** (attempt + 1)
            logger.info(f"Retrying in {wait:.1f}s...")
            time.sleep(wait)

    logger.error("All LLM retries exhausted")
    return None


# ─────────────────────────────────────────────────────────────
# Prompt builders — match EVE v2 Excel exactly
# ─────────────────────────────────────────────────────────────

def _build_step6_prompt(required_dimensions: dict, checklist: list, evidence_results: list) -> str:
    _chk = json.dumps(checklist, indent=2)
    return f"""You are an Audit Assurance Consolidation Engine.

TASK — STEP 6: ASSURANCE CONSOLIDATION AND CONTROL STATE SYNTHESIS

Consolidate all checklist evaluation outputs from Step 5 into a deterministic and explainable control assurance state.

This step MUST:
* consolidate evidence evaluation outcomes
* determine final checklist support states
* evaluate evidence sufficiency
* consolidate assurance metrics
* assess unresolved contradictions and inquiry outcomes
* evaluate OE reliability
* synthesize overall control support status
* prepare structured inputs for findings generation in Step 7

This step MUST NOT:
* generate findings
* generate recommendations
* generate severity ratings
* generate audit conclusions
* create narrative audit observations

Return ONLY valid JSON. No explanation. No markdown.

---

INPUT:

* Required Dimensions:
  {json.dumps(required_dimensions, indent=2)}

* Checklist:
  {_chk}

* Evidence Results:
  {json.dumps(evidence_results, indent=2)}

* Escalated Inquiries:
  {{escalated_inquiries_json}}

---

PRINCIPLE 1 — CHECKLIST-CENTRIC CONSOLIDATION:
Consume ONLY checklist validation results, evidence mappings, contradiction states, inquiry states, assurance updates, logical validation results, OE exception outputs.
Direct document interpretation is prohibited.

PRINCIPLE 2 — FINAL CHECKLIST STATE DETERMINATION:
Each checklist item must be assigned a final consolidated state:
* Supported: Assertion sufficiently validated
* Partially Supported: Incomplete or implied support
* Unsupported: Assertion not supported
* Needs Further Inquiry: Unresolved ambiguity or contradiction

PRINCIPLE 3 — MULTI-EVIDENCE CONSOLIDATION (CRITICAL RULES):
Consolidate corroborative evidence. Reconcile overlapping evidence. Preserve evidence lineage.
Disclose which evidence sources contributed to final support status.

CRITICAL — PRE-COMPUTED CONSOLIDATION:
The input data contains a "cross_evidence_consolidation" field per evidence piece.
This field has ALREADY computed the consolidated state for each checklist item across all evidence.
You MUST use these pre-computed values — do NOT re-derive consolidation from raw signals.

For each checklist item, find its entry in cross_evidence_consolidation and apply:
  consolidated_state = "SUPPORTED" AND suppress_finding = true
    → Final state = Supported. DO NOT raise a finding for this item. MANDATORY.
  consolidated_state = "PARTIALLY_SUPPORTED" AND suppress_finding = false
    → Final state = Partially Supported. Raise finding at REDUCED severity.
  consolidated_state = "UNSUPPORTED" AND suppress_finding = false
    → Final state = Unsupported. Raise finding at full severity.
  consolidated_state = "NOT_APPLICABLE"
    → Final state = Not Applicable. DO NOT raise a finding for this item. MANDATORY.
    Raise inquiry only if clarification would genuinely help; otherwise leave as-is.

EVIDENCE HIERARCHY (for reference only — consolidation already computed):
  TIER 1 — PRIMARY: Policy Documents, Board Minutes, Meeting Minutes, System Reports, Transaction Data, Audit Reports
  TIER 2 — SECONDARY: Interview responses, Walkthroughs, Observational notes

suppress_finding = true means NO FINDING for that checklist item regardless of what individual evidence pieces say.
This is NON-NEGOTIABLE — if suppress_finding is true, the item is considered evidenced.

PRINCIPLE 4 — ASSURANCE STATE CONSOLIDATION:
Maintain assurance metrics:
* Assurance Score (0.0 to 1.0): Overall confidence level
* Coverage Score (0.0 to 1.0): Checklist coverage completeness
* Evidence Quality Score (0.0 to 1.0): Reliability of supporting evidence
* Inquiry Count: Open clarification items
* Contradiction Count: Outstanding inconsistencies
* OE Reliability Score (0.0 to 1.0): Operational effectiveness consistency
* Evidence Sufficiency Score (0.0 to 1.0): Adequacy of evidence provided

PRINCIPLE 5 — ASSURANCE CALCULATION RULES:
Assurance influenced by: checklist coverage, evidence quality, corroborative support, OE exception rates, unresolved inquiries, unresolved contradictions, inadmissible evidence, logical validation failures.
Preserve explainability. Disclose assurance-impacting factors.

PRINCIPLE 6 — EVIDENCE SUFFICIENCY:
For each checklist item determine:
* Sufficient: Adequate evidence available
* Partially Sufficient: Limited or incomplete evidence
* Insufficient: Evidence inadequate
* Not Available: Evidence absent

PRINCIPLE 7 — CONTRADICTION CONSOLIDATION:
Classify contradictions as: Resolved / Pending Clarification / Unresolved / Material Unresolved
Only unresolved/material contradictions may negatively impact assurance.

PRINCIPLE 8 — INQUIRY STATE MANAGEMENT:
Track: Open / Resolved / Partially Resolved / Unresolved
Open and unresolved inquiries MUST reduce assurance confidence.

PRINCIPLE 9 — OE RELIABILITY SYNTHESIS:
Consolidate: population testing, attribute testing, analytical testing, sample testing, exception instances.
Preserve exact failed instances, failed attributes, OE exception lineage.

PRINCIPLE 10 — CONTROL SUPPORT STATUS:
Determine final control activity support state:
* Fully Supported: Adequate evidence, no material unresolved issues
* Partially Supported: Some gaps, ambiguities, or limited deficiencies
* Weakly Supported: Significant deficiencies or unresolved issues
* Unsupported: Control not adequately evidenced
* Not Tested: ALL checklist items resolved to Not Applicable -- no relevant
  evidence was submitted at all. This is NOT a compliance failure -- it means
  the control could not be evaluated. DO NOT use Unsupported for this case.

PRINCIPLE 11 — EVIDENCE INTEGRITY:
Consolidate: unsupported inference detection, traceability, audit period alignment, cross-document consistency, version alignment.

PRINCIPLE 12 — NO FINDINGS OR OBSERVATIONS:
Do NOT generate findings, observations, recommendations, risk statements, severity ratings, or audit conclusions.
This step is ONLY assurance consolidation and control state synthesis.

---

EVIDENCE WEIGHTING RULES:
Priority: STRONG > MODERATE > WEAK, PRIMARY > SUPPORTING
* WEAK evidence cannot independently support HIGH weight items
* SUPPORTING evidence cannot override PRIMARY
* INADMISSIBLE evidence must be excluded

SIGNAL RESOLUTION:
* IF STRONG CONTRADICTS + escalated inquiry → final_state = Unsupported
* IF STRONG SUPPORTS + no contradiction → proceed to support
* IF no admissible evidence → final_state = Unsupported
* IF inquiry unresolved → final_state = Needs Further Inquiry

SAMPLE TESTING:
* IF within_audit_period = NO → validity LOW
* IF exception_rate = 0 → HIGH validity → Supported
* IF exception_rate > 0 AND ≤ 10% → Partially Supported with LOW severity finding
* IF exception_rate > 10% AND ≤ 25% AND exceptions documented+escalated → Partially Supported with MEDIUM severity finding
* IF exception_rate > 10% AND ≤ 25% AND exceptions NOT documented → Unsupported with HIGH severity finding
* IF exception_rate > 25% → Unsupported with HIGH/CRITICAL severity finding

OE SEVERITY CALIBRATION RULES (CRITICAL):
* Control IS operating if: exceptions are DETECTED by the control itself AND escalated to management
* Control IS NOT operating if: exceptions are detected externally OR not escalated
* Detecting exceptions is EVIDENCE of control operation — do NOT mark as CRITICAL just because exceptions exist
* CRITICAL severity only when: exception rate > 50% OR control completely non-functional
* HIGH severity when: exception rate > 25% OR exceptions not escalated
* MEDIUM severity when: exception rate 10-25% with documented escalation
* LOW severity when: exception rate < 10% with documented escalation

---

OUTPUT FORMAT (return ONLY this JSON structure):

{{{{
  "checklist_state_matrix": [
    {{{{
      "checklist_id": "",
      "requirement": "",
      "final_state": "Supported | Partially Supported | Unsupported | Needs Further Inquiry | Not Applicable",
      "supporting_evidence": ["evidence_id_1", "evidence_id_2"],
      "confidence": "HIGH | MEDIUM | LOW",
      "assurance_impact": "POSITIVE | NEUTRAL | NEGATIVE",
      "sufficiency_status": "Sufficient | Partially Sufficient | Insufficient | Not Available",
      "basis": ""
    }}}}
  ],
  "assurance_state": {{{{
    "assurance_score": 0.0,
    "coverage_score": 0.0,
    "evidence_quality_score": 0.0,
    "oe_reliability_score": 0.0,
    "evidence_sufficiency_score": 0.0,
    "inquiry_count": 0,
    "contradiction_count": 0,
    "resolved_contradiction_count": 0,
    "unresolved_contradiction_count": 0,
    "assurance_impacting_factors": []
  }}}},
  "evidence_sufficiency_summary": [
    {{{{
      "checklist_id": "",
      "sufficiency_status": "Sufficient | Partially Sufficient | Insufficient | Not Available",
      "missing_evidence": "",
      "residual_gaps": ""
    }}}}
  ],
  "contradiction_inquiry_summary": [
    {{{{
      "item": "",
      "type": "CONTRADICTION | INQUIRY",
      "status": "Resolved | Pending Clarification | Unresolved | Material Unresolved",
      "resolution_state": "",
      "residual_risk": "HIGH | MEDIUM | LOW | NONE"
    }}}}
  ],
  "oe_exception_summary": [
    {{{{
      "instance_id": "",
      "checklist_id": "",
      "failed_attribute": "",
      "exception_severity": "CRITICAL | HIGH | MEDIUM | LOW",
      "exception_status": "Open | Remediated | Accepted"
    }}}}
  ],
  "control_support_status": {{{{
    "final_status": "Fully Supported | Partially Supported | Weakly Supported | Unsupported | Not Tested",
    "assurance_rationale": "",
    "key_gaps": [],
    "unresolved_items": []
  }}}}
}}}}

STRICT CONSTRAINTS:
* Return ONLY valid JSON
* Do NOT generate findings, observations, or recommendations
* Do NOT conclude compliance
* All assurance scores must be between 0.0 and 1.0
* final_state must use exact values: Supported / Partially Supported / Unsupported / Needs Further Inquiry / Not Applicable
* final_status must use exact values: Fully Supported / Partially Supported / Weakly Supported / Unsupported / Not Tested"""



def _build_step7_prompt(
    checklist_state_matrix: list,
    assurance_state: dict,
    evidence_sufficiency_summary: list,
    contradiction_inquiry_summary: list,
    oe_exception_summary: list,
    control_support_status: dict,
    checklist: list,
    findings: list = None,
    control_activity_name: str = "",
    control_activity_description: str = "",
    required_dimensions: dict = None,
) -> str:
    """Build EVE Step 7 prompt — V3 with 13 principles."""
    # Pre-serialize to avoid f-string brace interpretation errors
    _csm = json.dumps(checklist_state_matrix, indent=2)
    _as = json.dumps(assurance_state, indent=2)
    _ess = json.dumps(evidence_sufficiency_summary, indent=2)
    _cis = json.dumps(contradiction_inquiry_summary, indent=2)
    _oes = json.dumps(oe_exception_summary, indent=2)
    _css = json.dumps(control_support_status, indent=2)
    _chk = json.dumps(checklist, indent=2)
    _fin = json.dumps(findings or [], indent=2)
    _dims = json.dumps(required_dimensions or {}, indent=2)

    return f"""You are an Audit Observation, Finding, Risk, and Recommendation Engine.

TASK — STEP 7: STRUCTURED AUDIT ISSUE GENERATION AND RISK ARTICULATION

Generate deterministic, evidence-backed, auditable audit observations, findings, risks, severity assessments, and recommendations based solely on the consolidated assurance outputs from Step 6.

This step MUST:
* identify unresolved control deficiencies
* generate structured audit observations
* generate findings from failed or weakly supported checklist items
* evaluate impact and severity
* identify operational and regulatory risks
* generate targeted recommendations
* consolidate OE exception impacts
* maintain full traceability to checklist failures and evidence lineage

CRITICAL RULES FOR FINDINGS:
* Findings must be SPECIFIC not GENERIC — state exactly what was found to be missing, incorrect, or insufficient
* DO NOT say "documentation is incomplete" — say exactly WHAT documentation is missing or what specific element is absent
* DO NOT say "roles are unclear" — say exactly WHICH roles are undefined and in WHICH document
* Every finding must reference the specific checklist item(s) that failed and the specific evidence gap
* Findings must be written from the perspective of an experienced auditor who has read the evidence
* CRITERIA FIELD (mandatory): populate "criteria" with the actual regulatory/clause requirement being
  tested, cited by paragraph or clause reference where available -- pull this from the "requirement"
  field of the relevant checklist_state_matrix item(s). Example: "Paragraph 5 of the Master Direction
  requires the KYC policy to include Monitoring of Transactions." This is the FIRST thing an experienced
  auditor looks for in a finding -- it must never be left blank or vague.
* FINDING_SUMMARY MUST BE PROSE, NOT A TEMPLATE: write finding_summary as connected auditor prose that
  naturally weaves together the Condition (what was actually found, citing the specific source document
  and section by name) and the Cause (why the gap exists). DO NOT use a fill-in-the-blank template such
  as "X is inadequate — [root]. What was expected: [Y]. What was found: [Z]. If not remediated, [W]."
  That scaffolding pattern is explicitly PROHIBITED -- it makes distinct findings read as interchangeable
  boilerplate. Two findings with different root causes must read as genuinely different prose, not the
  same sentence structure with different words substituted in.
* DO NOT restate consequence/impact language inside finding_summary. Impact belongs ONLY in the separate
  regulatory_impact and operational_impact fields -- repeating it in finding_summary as well (e.g. "If not
  remediated, there is a risk of...") is a duplication error and is PROHIBITED.
* Cite the source document and section BY NAME inside finding_summary itself (e.g. "the KYC/AML Policy
  (D1) Section 4.2"), not only in evidence_basis or evidence_lineage.

CRITICAL RULES FOR RECOMMENDATIONS:
* Recommendations must be SPECIFIC and ACTIONABLE — not generic
* DO NOT say "identify gaps" — specify exactly what gaps were found
* DO NOT say "update records" — specify exactly which records need updating and what needs to be added
* DO NOT say "clarify roles" — specify exactly which roles are unclear and what clarity is needed
* Every implementation step must be a concrete action derived from the actual evidence gap
* The recommendation must directly address the specific deficiency noted in the related finding
* Base every recommendation on the exact evidence gaps found in the checklist state matrix

This step MUST NOT:
* directly interpret raw documents
* generate findings from unsupported inference
* generate conclusions without evidence lineage
* bypass the structured checklist evaluation framework
* generate final audit opinions or overall compliance conclusions

Return ONLY valid JSON. No explanation. No markdown.

---

CONTROL ACTIVITY CONTEXT:
* Activity Name: {control_activity_name}
* Activity Description: {control_activity_description}
* Required Effectiveness Dimensions: {_dims}

---

ACTIVITY SCOPING AND EFFECTIVENESS DIMENSION RULES (CRITICAL):
1. All findings and recommendations MUST be framed in terms of whether this specific
   control activity is designed / implemented / operating effectively — as applicable.
2. Only generate findings for dimensions where Required Effectiveness Dimensions = YES:
   - DESIGN findings only if design = YES
   - IMPLEMENTATION findings only if implementation = YES
   - OPERATING findings only if operating = YES
3. Do NOT generate a finding for a dimension just because it is applicable — only generate
   if the checklist state matrix shows actual failures or unsupported items for that dimension.
4. Multiple findings per dimension are allowed if distinct deficiencies exist.
5. Finding titles MUST be framed as:
   "The control '[activity name]' is not [designed/implemented/operating] effectively because [specific deficiency]"
6. If a checklist item failure does not map to any applicable effectiveness dimension
   for this activity, do NOT raise a standalone finding for it.
7. OE exception instances remain as factual test results and must always be reported
   under the relevant OPERATING finding regardless of framing.
8. ACTIVITY BOUNDARY RULE (CRITICAL): Before raising a finding for any checklist item,
   ask: "Does this checklist item test something that THIS specific control activity
   is responsible for?" If the checklist item tests a requirement that belongs to a
   DIFFERENT activity (e.g. periodic sampling/quarterly review when this activity operates
   at the time of a transaction/event), you MUST NOT raise a finding for it.
   The activity description is your boundary — if the checklist item requirement is
   outside that boundary, SKIP it entirely. Do not raise, do not mention.

---

INPUT FROM STEP 6:

* Checklist State Matrix:
  {_csm}

* Assurance State:
  {_as}

* Evidence Sufficiency Summary:
  {_ess}

* Contradiction / Inquiry Summary:
  {_cis}

* OE Exception Summary:
  {_oes}

* Control Support Status:
  {_css}

* Checklist Items:
  {_chk}

---

OE EXCEPTION REGISTER RULE (CRITICAL):
The "OE Exception Summary" input above contains pre-identified exception instances from evidence.
You MUST:
1. Populate "oe_exception_register" with ALL items from OE Exception Summary
2. In each finding that is about OE failures (finding_type = "OE") — populate "related_oe_exceptions" as a list of objects:
   [{{"instance_id": "AFL25009", "failed_attribute": "Gold ornament weight limit", "exception_description": "1.15 kg exceeds 1 kg limit"}}]
3. For findings NOT about OE (e.g. missing documentation, missing process steps) — set related_oe_exceptions = []
4. finding_type must be "OE" for findings about weight limit breaches, "IE" for implementation/documentation gaps
Do NOT add OE exceptions to non-OE findings.
Do NOT use string format for related_oe_exceptions — always use object format with instance_id, failed_attribute, exception_description.

PRINCIPLE 1 — FINDINGS MUST EMERGE ONLY FROM STRUCTURED FAILURES:
Findings may ONLY be generated from:
* Unsupported checklist items
* Weakly Supported control states
* Unresolved contradictions
* Unresolved inquiries
* Inadmissible evidence
* Failed logical validations
* Failed OE testing with exception instances
* Insufficient evidence states
* Evidence integrity failures

PRINCIPLE 2 — FULL TRACEABILITY IS MANDATORY:
Every observation, finding, risk, and recommendation must retain traceability to:
checklist IDs, failed assertions, evidence sources, OE exception instances, contradiction records, inquiry records, and assurance impacts.

PRINCIPLE 3 — OBSERVATION STRUCTURE:
Each observation must identify:
* the control expectation
* the issue identified
* the supporting basis
* the operational/regulatory implication
Observations must be: factual, concise, evidence-backed, non-speculative.

PRINCIPLE 4 — FINDING GENERATION RULES:
Findings must emerge from unresolved deficiencies and distinguish between:
* Design deficiencies (D)
* Implementation deficiencies (IE)
* OE deficiencies (OE)
* Evidence deficiencies (Evidence Integrity)
* Inquiry-related uncertainties (Inquiry)

PRINCIPLE 5 — FINDING CONSOLIDATION AND DEDUPLICATION:
Consolidate related checklist failures into unique findings.
Group failures where they relate to: same control objective, same governance weakness, same OE breakdown.
AVOID: repetitive findings, one-to-one checklist-to-finding duplication.

PARTIAL CHECKLIST ITEMS:
PARTIAL items must NOT automatically generate findings.
Evaluate materiality, aggregation impact, assurance reduction before deciding.

GOOD EXAMPLE: "Board governance and approval controls for the Credit Policy were not fully evidenced. (High)"
BAD EXAMPLE: Multiple separate findings for each individual board approval gap.

PRINCIPLE 6 — SEVERITY ASSESSMENT:
| Severity | Meaning |
| Low | Minor isolated issue |
| Medium | Moderate control weakness |
| High | Significant deficiency impacting assurance |
| Critical | Material regulatory/control failure |

Severity influenced by: assurance impact, regulatory significance, OE failure extent, population impact, evidence sufficiency, unresolved contradictions.

PRINCIPLE 7 — ROOT CAUSE IDENTIFICATION:
Where possible identify probable root causes:
inadequate design, incomplete implementation, weak operational execution, insufficient monitoring, poor governance, missing evidence controls, documentation gaps.
Root causes must remain evidence-supported, avoid speculative attribution.

PRINCIPLE 8 — RISK GENERATION:
Generate risks associated with unresolved deficiencies.
Risk categories: Regulatory | Operational | Financial | Governance
Risks must be: proportional, evidence-backed, logically connected to findings.

PRINCIPLE 9 — RECOMMENDATION GENERATION:
Recommendations must:
* directly address identified deficiencies
* remain implementable and proportionate to severity
* align with regulatory intent
* NOT introduce unrelated remediation
* NOT exceed scope of finding

PRINCIPLE 10 — OE EXCEPTION CONSOLIDATION:
Where OE testing applies, findings must consider:
* exact failed instances
* frequency of exceptions
* population-wide impact
* exception severity and remediation status
Preserve exact exception lineage. Avoid generalized OE conclusions.

PRINCIPLE 11 — INQUIRY AND CONTRADICTION TREATMENT:
Resolved contradictions/inquiries must NOT generate findings.
Only unresolved, material, or assurance-impacting contradictions may contribute toward findings.
Clearly distinguish unresolved ambiguity from confirmed control failure.

PRINCIPLE 12 — EVIDENCE INTEGRITY FINDINGS:
Evidence integrity failures may independently generate findings where:
* evidence traceability is broken
* audit period alignment fails
* unsupported inference materially impacts evaluation
* evidence inconsistency remains unresolved

PRINCIPLE 13 — NO FINAL AUDIT CONCLUSIONS:
This step must NOT generate:
* final audit opinions
* overall compliance conclusions
* clause-level compliance status
* executive summaries

---

OUTPUT FORMAT (return ONLY this JSON structure):

{{{{
  "observation_register": [
    {{{{
      "observation_id": "OBS-001",
      "related_checklist_ids": [],
      "observation_summary": "",
      "supporting_basis": "",
      "evidence_references": [],
      "assurance_impact": "POSITIVE | NEUTRAL | NEGATIVE"
    }}}}
  ],
  "findings_register": [
    {{{{
      "finding_id": "F-001",
      "criteria": "",
      "finding_summary": "",
      "finding_type": "D | IE | OE | Evidence Integrity | Inquiry",
      "related_checklist_ids": [],
      "root_issue": "",
      "evidence_basis": "",
      "regulatory_impact": "",
      "operational_impact": "",
      "residual_risk": "",
      "severity": "CRITICAL | HIGH | MEDIUM | LOW",
      "assurance_impact": "",
      "related_oe_exceptions": [],
      "evidence_lineage": []
    }}}}
  ],
  "risk_register": [
    {{{{
      "risk_id": "R-001",
      "related_findings": [],
      "risk_description": "",
      "risk_category": "Regulatory | Operational | Financial | Governance",
      "potential_impact": "",
      "likelihood": "Low | Medium | High",
      "residual_exposure": ""
    }}}}
  ],
  "recommendation_register": [
    {{{{
      "recommendation_id": "REC-001",
      "related_finding": "",
      "recommendation_summary": "",
      "target_control_area": "",
      "recommended_action": "",
      "implementation_steps": [],
      "owner": "",
      "timeline": "IMMEDIATE | SHORT_TERM | MEDIUM_TERM | LONG_TERM",
      "priority": "Low | Medium | High",
      "expected_outcome": ""
    }}}}
  ],
  "oe_exception_register": [
    {{{{
      "instance_id": "",
      "checklist_id": "",
      "failed_attribute": "",
      "exception_description": "",
      "population_impact": "",
      "exception_severity": "Critical | High | Medium | Low",
      "severity_contribution": ""
    }}}}
  ],
  "inquiry_contradiction_register": [
    {{{{
      "item": "",
      "type": "CONTRADICTION | INQUIRY",
      "resolution_status": "Resolved | Pending | Unresolved | Material Unresolved",
      "residual_impact": "",
      "escalation_required": "YES | NO"
    }}}}
  ]
}}}}

STRICT CONSTRAINTS:
* Return ONLY valid JSON
* Do NOT generate final audit opinions or compliance conclusions
* Findings must emerge from Step 6 structured outputs ONLY
* Every finding must have traceable checklist_ids
* Resolved contradictions/inquiries must NOT generate findings
* PARTIAL items need materiality evaluation before generating findings
* Severity must be explainable and evidence-backed
* Recommendations must be one-to-one with findings
* OE exceptions must preserve instance-level traceability"""



def _build_step8_prompt(clause_id: int, clause_text: str, control_outputs: list) -> str:
    _ct = json.dumps(clause_text)
    _co = json.dumps(control_outputs, indent=2)
    return f"""You are an Audit Clause Aggregation Engine.

TASK:
Aggregate outputs from multiple control activities into a single clause-level result.

You must:
* consolidate observations
* merge and group findings using predefined categories
* retain full traceability
* consolidate recommendations aligned to merged findings
* determine clause-level status and severity
* use appropriate language based on finding_type

Return ONLY valid JSON.

DO NOT:
* re-evaluate evidence
* generate new findings
* generate new recommendations from scratch
* assume missing information
* include findings with auditor_status = "ACCEPTED" (already cleared)

---

INPUT:
{{
  "clause_id": "{clause_id}",
  "clause_text": {_ct},
  "control_outputs": {_co}
}}

---

SUB-STEP-1 — CONSOLIDATE OBSERVATIONS
* Combine all observations across controls
* Remove duplicates (semantic similarity)
* Retain evidence references
* Sequence using this order:
  1. Governance Framework & Structure
  2. Roles, Responsibilities & Accountability
  3. Oversight & Monitoring
  4. Risk Management & Control Design
  5. Implementation & Operational Effectiveness
  6. Documentation & Approval
  7. Evidence & Record Keeping
  8. Regulatory Compliance & Reporting

SUB-STEP-2 — CLASSIFY EACH FINDING BY TYPE
Before grouping, classify each incoming finding:
* NORMAL — standard audit finding — factual gap or control failure
* NEEDS_REVIEW — auditor raised as requiring review — evidence ambiguous or clarification needed
* CONTRADICTION — internal document conflict or explicit exclusion detected

Use the finding's existing type/auditor_status fields to determine classification.
If finding has no type → treat as NORMAL.

SUB-STEP-3 — GROUP FINDINGS INTO CONTROLLED CATEGORIES
Assign each finding to EXACTLY ONE group from the 8 categories above.
Group based on ROOT CAUSE (not symptom).
Priority: Oversight > Governance > Risk > Roles > Implementation > Documentation > Evidence > Regulatory

SUB-STEP-4 — MERGE FINDINGS
Within each group:
* Merge findings that represent the SAME underlying issue
* Do NOT merge findings of different types (NORMAL vs NEEDS_REVIEW vs CONTRADICTION)
* Merged Severity = MAX(severity of grouped findings)
* Each merged finding must include source_references with control_id, checklist_id, evidence_reference

SUB-STEP-5 — APPLY FINDING LANGUAGE BY TYPE

For NORMAL findings — use factual, direct language:
"The credit policy does not include a roles and responsibilities framework."
"Board approval for the credit policy is not documented."

For NEEDS_REVIEW findings — use clarification-pending language:
"Board approval date requires clarification — two conflicting approval dates found in document. [Pending auditor review]"
"Scope of the credit policy requires verification — document language is ambiguous regarding applicable products. [Pending auditor review]"
"Policy version in document body does not match filename version — document integrity requires confirmation. [Pending auditor review]"

For CONTRADICTION findings — use type-specific language:

  EXPLICIT_EXCLUSION type:
  "The credit policy explicitly excludes [topic] from its scope. Coverage gap identified."
  "Document scope section explicitly states [requirement] is not applicable to this institution."

  INTERNAL type:
  "The credit policy contains contradictory statements regarding [topic] — [Section X] states [A] while [Section Y] states [B]. Control gap not resolved."
  "Conflicting approval authorities identified — [Section X] assigns authority to [Body A] while [Section Y] assigns to [Body B]."

  DATE_INCONSISTENCY type:
  "Document date inconsistency detected — effective date [date] precedes approval date [date]. Document integrity requires verification."

SUB-STEP-6 — CONSOLIDATE RECOMMENDATIONS
* Map recommendations to merged findings using finding_id linkage
* Combine recommendations addressing same issue
* Do NOT generate new recommendations
* Merged timeline = MOST URGENT: IMMEDIATE > SHORT_TERM > MEDIUM_TERM > LONG_TERM
* For NEEDS_REVIEW findings → recommendation should be: "Obtain auditor clarification before escalating as finding."
* For CONTRADICTION findings → recommendation should address root cause resolution

SUB-STEP-6B — OE FINDING SEVERITY CALIBRATION (apply BEFORE SUB-STEP-7):
For OE exception findings — use these rules:
* exception_rate <= 10% WITH escalation → severity = LOW
* exception_rate 10-25% WITH documented escalation → severity = MEDIUM
* exception_rate 10-25% WITHOUT escalation → severity = HIGH
* exception_rate > 25% → severity = HIGH
* exception_rate > 50% OR control non-functional → severity = CRITICAL
* If exceptions DETECTED by control AND escalated to management → severity MAX = HIGH (not CRITICAL)
* CRITICAL only if: control failed to detect exceptions OR exception_rate > 50%

SUB-STEP-7 — DETERMINE CLAUSE SEVERITY
Clause Severity = MAX(severity across all NORMAL + unresolved NEEDS_REVIEW + CONTRADICTION findings)

SUB-STEP-8 — DETERMINE CLAUSE STATUS
IF any finding severity = CRITICAL → clause_status = NON_COMPLIANT
ELSE IF any finding severity = HIGH → clause_status = PARTIALLY_COMPLIANT
ELSE IF any finding severity = MEDIUM → clause_status = PARTIALLY_COMPLIANT
ELSE → clause_status = COMPLIANT


SUB-STEP-9 — GENERATE CLAUSE SUMMARY
Write a concise paragraph: what was assessed, key strengths (if any), key issues, overall conclusion.
Tone: formal, auditor-style, evidence-based, no vague language.
If NEEDS_REVIEW findings present — note: "X items require auditor clarification before final assessment."
If CONTRADICTION findings present — note: "X document contradictions identified requiring resolution."

OUTPUT FORMAT:
{{{{
  "clause_id": "{clause_id}",
  "clause_text": "",
  "clause_status": "",
  "clause_severity": "",
  "summary": "",
  "needs_review_count": 0,
  "contradiction_count": 0,
  "observations": [],
  "findings": [
    {{{{
      "finding_id": "",
      "group": "",
      "finding_type": "NORMAL | NEEDS_REVIEW | CONTRADICTION",
      "contradiction_type": "EXPLICIT_EXCLUSION | INTERNAL | DATE_INCONSISTENCY | null",
      "issue": "",
      "impact": "",
      "severity": "",
      "source_references": [
        {{{{"control_id": "", "checklist_id": "", "evidence_reference": ""}}}}
      ]
    }}}}
  ],
  "recommendations": [
    {{{{"finding_id": "", "recommendation": "", "implementation_steps": [], "timeline": ""}}}}
  ]
}}}}

STRICT CONSTRAINTS:
* Do NOT duplicate findings
* Do NOT lose traceability
* Do NOT weaken severity
* Do NOT introduce new issues
* Do NOT include findings with auditor_status = ACCEPTED
* Observations must remain evidence-linked
* Recommendations must map 1:1 to merged findings
* NEEDS_REVIEW findings must use clarification-pending language
* CONTRADICTION findings must use type-specific language"""


# ─────────────────────────────────────────────────────────────
# Helper — build evidence results input for Step 6
# from EveEvidenceResult rows
# ─────────────────────────────────────────────────────────────

def _build_evidence_results_for_step6(checklist_id: int) -> list:
    """
    Fetch all EveEvidenceResult rows for a project_checklist
    and format them as Step 6 input.
    FIX A: Also pass checklist_evaluation data from raw_output_json
    so Step 6 LLM has verbatim extracts, locations, gaps — not just PASS/FAIL.
    """
    results = (
        db.session.query(EveEvidenceResult)
        .filter_by(project_checklist_id=checklist_id)
        .all()
    )

    # Group by evidence_artifact_id
    evidence_map = {}
    for r in results:
        eid = r.evidence_artifact_id
        if eid not in evidence_map:
            # Extract checklist_evaluation from raw_output_json
            checklist_eval_map = {}
            if r.raw_output_json and isinstance(r.raw_output_json, dict):
                for ce in r.raw_output_json.get("checklist_evaluation", []):
                    cid = ce.get("checklist_id", "")
                    if cid:
                        checklist_eval_map[cid] = ce
                # Also pull admissibility_tests for Step 6 context
                admissibility_tests = r.raw_output_json.get("admissibility_tests", [])
                oe_testing = r.raw_output_json.get("oe_testing_results", {})
                evidence_meta_raw = r.raw_output_json.get("evidence_meta", {})
            else:
                admissibility_tests = []
                oe_testing = {}
                evidence_meta_raw = {}

            evidence_map[eid] = {
                "evidence_id": eid,
                "evidence_type": r.evidence_type or "",
                "admissibility": r.admissibility,
                "admissibility_reason": r.admissibility_reason or "",
                "confidence": r.confidence or "MEDIUM",
                "evidence_meta": {
                    "strength": r.evidence_strength or "MODERATE",
                    "role": r.evidence_role or "SUPPORTING",
                    "entity_name": evidence_meta_raw.get("entity_name", ""),
                    "document_title": evidence_meta_raw.get("document_title", ""),
                    "approval_date": evidence_meta_raw.get("approval_date", ""),
                    "effective_date": evidence_meta_raw.get("effective_date", ""),
                    "review_frequency": evidence_meta_raw.get("review_frequency", ""),
                },
                "admissibility_tests": admissibility_tests,
                "item_signals": [],
                "results": [],
                "oe_testing_results": oe_testing,
                "sample_evaluation": {
                    "applicable": "YES" if r.sample_applicable else "NO",
                    "sample_size": r.sample_size,
                    "population_size": r.population_size,
                    "exception_rate": float(r.exception_rate) if r.exception_rate else None,
                    "within_audit_period": "YES" if r.sample_within_audit_period else "NO",
                },
                "_checklist_eval_map": checklist_eval_map,  # internal use below
            }

        # Get checklist_evaluation entry for this row
        ce = evidence_map[eid]["_checklist_eval_map"].get(r.checklist_item_id, {})

        evidence_map[eid]["item_signals"].append({
            "checklist_id": r.checklist_item_id,
            "signal": r.signal,
            "basis": r.signal_basis or ce.get("basis", ""),
            "confidence": r.confidence or "MEDIUM",
        })
        evidence_map[eid]["results"].append({
            "checklist_id": r.checklist_item_id,
            "status": r.item_status,
            "found": ce.get("found", ""),
            "evidence_reference": r.evidence_reference or ce.get("location", ""),
            "extract": ce.get("extract", ""),      # verbatim extract from document
            "gap": ce.get("gap", ""),              # specific gap identified
            "confidence": r.confidence or "MEDIUM",
            "confidence_classification": ce.get("confidence", ""),
        })

    # Remove internal helper key before returning
    output = []
    for ev in evidence_map.values():
        ev.pop("_checklist_eval_map", None)
        output.append(ev)

    # ── PRE-CONSOLIDATION: compute cross-evidence found state per checklist item ──
    # This tells Step 6 LLM exactly what the consolidated state is — no guessing needed
    # RULE 3A: If FOUND in ANY Tier 1 (document) evidence → mark as consolidated_found
    # RULE 3C: NOT_APPLICABLE is not NOT_FOUND
    TIER1_EVIDENCE_ROLES = {"PRIMARY", "CORROBORATIVE"}
    TIER1_EVIDENCE_TYPES = {
        "POLICY_DOCUMENT", "BOARD_MINUTES", "MEETING_MINUTES", "SIGNED_AGREEMENT",
        "SYSTEM_REPORT", "TRANSACTION_DATA", "AUDIT_REPORT", "REGISTER", "LOG",
        "FINANCIAL_STATEMENT", "CONTRACT", "CERTIFICATE", "APPROVAL_LETTER",
        "BOARD_RESOLUTION", "CIRCULAR", "NOTICE", "REGULATORY_FILING"
    }

    # Build per-checklist-item cross-evidence summary
    checklist_cross_summary = {}
    for ev in output:
        ev_type = (ev.get("evidence_type") or "").upper().replace(" ", "_")
        ev_role = (ev.get("evidence_meta", {}).get("role") or "").upper()
        is_tier1 = ev_role in TIER1_EVIDENCE_ROLES or ev_type in TIER1_EVIDENCE_TYPES

        for result in ev.get("results", []):
            chk_id = result.get("checklist_id")
            found_val = (result.get("found") or "").upper()
            if not chk_id:
                continue
            if chk_id not in checklist_cross_summary:
                checklist_cross_summary[chk_id] = {
                    "tier1_found": False,
                    "tier1_partial": False,
                    "any_found": False,
                    "all_not_applicable": True,
                    "contributing_evidence": []
                }
            summary = checklist_cross_summary[chk_id]
            if found_val == "NOT_APPLICABLE":
                continue  # skip — not a finding signal
            summary["all_not_applicable"] = False
            if found_val in ("FOUND",):
                summary["any_found"] = True
                if is_tier1:
                    summary["tier1_found"] = True
                    summary["contributing_evidence"].append({
                        "evidence_id": ev.get("evidence_id"),
                        "evidence_type": ev.get("evidence_type"),
                        "tier": "TIER1"
                    })
            elif found_val == "PARTIAL":
                if is_tier1:
                    summary["tier1_partial"] = True
                    summary["contributing_evidence"].append({
                        "evidence_id": ev.get("evidence_id"),
                        "evidence_type": ev.get("evidence_type"),
                        "tier": "TIER1_PARTIAL"
                    })

    # Compute consolidated state per checklist item
    for chk_id, summary in checklist_cross_summary.items():
        if summary["tier1_found"]:
            summary["consolidated_state"] = "SUPPORTED"
            summary["suppress_finding"] = True
            summary["reason"] = "FOUND in Tier 1 (primary document) evidence — finding suppressed per RULE 3A"
        elif summary["tier1_partial"]:
            summary["consolidated_state"] = "PARTIALLY_SUPPORTED"
            summary["suppress_finding"] = False
            summary["reason"] = "Only PARTIAL in Tier 1 evidence — finding may be raised at reduced severity"
        elif summary["any_found"]:
            summary["consolidated_state"] = "PARTIALLY_SUPPORTED"
            summary["suppress_finding"] = False
            summary["reason"] = "FOUND only in Tier 2 (secondary) evidence — documentary evidence required"
        elif summary["all_not_applicable"]:
            summary["consolidated_state"] = "NOT_APPLICABLE"
            summary["suppress_finding"] = True
            summary["reason"] = "Item not applicable to any evidence type submitted — raise inquiry"
        else:
            summary["consolidated_state"] = "UNSUPPORTED"
            summary["suppress_finding"] = False
            summary["reason"] = "NOT_FOUND in all applicable evidence — finding should be raised"

    # Attach cross-summary to output for Step 6 LLM
    for ev in output:
        ev["cross_evidence_consolidation"] = checklist_cross_summary

    # Pre-build oe_exception_summary from all evidence OE testing results
    # Step 6 LLM often fails to extract exception instances from nested JSON
    oe_exception_summary = []
    seen_instances = set()
    for ev in output:
        oe = ev.get("oe_testing_results", {})
        if not oe or not isinstance(oe, dict):
            continue
        instances = oe.get("exception_instances", [])
        if not instances:
            continue
        for inst in instances:
            if not isinstance(inst, dict):
                continue
            inst_key = inst.get("instance_id") or inst.get("loan_id") or str(inst.get("issue", ""))[:50]
            if inst_key in seen_instances:
                continue
            seen_instances.add(inst_key)
            oe_exception_summary.append({
                "instance_id": inst.get("instance_id") or inst.get("loan_id") or f"EXC-{len(oe_exception_summary)+1:03d}",
                "checklist_id": inst.get("checklist_id") or inst.get("attribute_tested", ""),
                "failed_attribute": inst.get("failed_attribute") or inst.get("attribute_tested") or inst.get("issue", ""),
                "exception_severity": inst.get("exception_severity") or inst.get("severity", "HIGH"),
                "exception_status": inst.get("status") or "Open",
                "description": inst.get("issue") or inst.get("description", ""),
                "evidence_source": ev.get("evidence_type", ""),
            })

    # Attach pre-built oe_exception_summary to first evidence for Step 6 access
    if output:
        output[0]["pre_built_oe_exception_summary"] = oe_exception_summary

    return output


# ─────────────────────────────────────────────────────────────
# MODULE E+F — Task: run_eve_step6_and_7
# EVE Steps 6+7 per project_control_activity
# ─────────────────────────────────────────────────────────────

def _filter_checklist_for_activity(checklist_state_matrix, checklist_items, activity_description, activity_name=""):
    """Remove checklist items clearly outside the scope of a transactional activity."""
    PERIODIC_KEYWORDS = [
        "random sample", "quarterly", "periodic review",
        "sample selection", "random selection", "sampling",
        "random sample of", "selected and reviewed",
    ]
    TRANSACTIONAL_KEYWORDS = [
        "at the time of", "per transaction", "each transaction",
        "loan approval", "disbursement", "per instance", "per event",
    ]
    # Check both activity_name and activity_description
    activity_lower = ((activity_name or "") + " " + (activity_description or "")).lower()
    is_transactional = any(k in activity_lower for k in TRANSACTIONAL_KEYWORDS)
    if not is_transactional:
        return checklist_state_matrix, checklist_items
    # Find checklist item IDs that are periodic in nature
    filtered_ids = set()
    for item in checklist_items:
        req = (item.get("requirement") or "").lower()
        if any(k in req for k in PERIODIC_KEYWORDS):
            filtered_ids.add(item.get("id"))
            logger.info(
                f"[Module F] Filtering out-of-scope checklist item {item.get('id')} "
                f"from Step 7 input (periodic keyword detected in transactional activity)"
            )
    if not filtered_ids:
        return checklist_state_matrix, checklist_items
    filtered_matrix = [i for i in checklist_state_matrix if i.get("checklist_id") not in filtered_ids]
    filtered_items = [i for i in checklist_items if i.get("id") not in filtered_ids]
    return filtered_matrix, filtered_items


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_eve_step6_and_7(self, project_control_activity_id: int, generated_by: int = None):
    """
    Module E+F — EVE Steps 6+7:
    - Step 6: Aggregate evidence results → checklist summary, observations, findings
    - Step 7: Generate recommendations for each finding

    Stores result in eve_control_result table.

    Args:
        project_control_activity_id: ID from project_control_activities
        generated_by: User ID who triggered this (optional)
    """
    logger.info(
        f"[Module E+F] Starting Steps 6+7 for pca_id={project_control_activity_id}"
    )

    try:
        # ── 1. Load project control activity ──────────────────────────
        pca = db.session.query(ProjectControlActivity).get(project_control_activity_id)
        if not pca:
            return {"status": "error", "message": f"ProjectControlActivity {project_control_activity_id} not found"}

        # ── 2. Load project checklist ──────────────────────────────────
        checklist = (
            db.session.query(ProjectChecklist)
            .filter_by(project_control_activity_id=project_control_activity_id)
            .first()
        )
        if not checklist:
            return {"status": "error", "message": "No ProjectChecklist found — run Module B first"}

        checklist_items = checklist.get_checklist_items()
        if not checklist_items:
            return {"status": "error", "message": "ProjectChecklist has no items"}

        # ── 3. Check if already completed — prevent duplicate runs ───
        existing_result = db.session.query(EveControlResult).filter_by(
            project_control_activity_id=project_control_activity_id
        ).first()
        if existing_result and existing_result.step7_completed:
            logger.info(f"[Module E+F] Step 6+7 already completed for pca_id={project_control_activity_id} — skipping duplicate run")
            return {"status": "skipped", "message": "Already completed", "project_control_activity_id": project_control_activity_id}

        # ── 4. Check if Step 5 results exist ──────────────────────────
        evidence_count = (
            db.session.query(EveEvidenceResult)
            .filter_by(project_checklist_id=checklist.id)
            .count()
        )
        if evidence_count == 0:
            return {
                "status": "error",
                "message": "No Step 5 results found — run Module D (Eve Step 5) first",
                "project_control_activity_id": project_control_activity_id,
            }

        # ── 4. Get or create EveControlResult ─────────────────────────
        control_result = (
            db.session.query(EveControlResult)
            .filter_by(project_control_activity_id=project_control_activity_id)
            .first()
        )
        if not control_result:
            control_result = EveControlResult(
                project_control_activity_id=project_control_activity_id,
                project_checklist_id=checklist.id,
                generated_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                generated_by=generated_by,
            )
            db.session.add(control_result)
            db.session.flush()

        # ── 5. Build Step 6 inputs ─────────────────────────────────────
        required_dimensions = {
            "design": "YES" if checklist.dimension_design else "NO",
            "implementation": "YES" if checklist.dimension_implementation else "NO",
            "operating": "YES" if checklist.dimension_operating else "NO",
        }
        evidence_results = _build_evidence_results_for_step6(checklist.id)

        # ── Fetch escalated inquiries ──────────────────────────────────
        from app.models.eve_models import EveInquiry
        escalated_inquiries = (
            db.session.query(EveInquiry)
            .filter_by(
                project_checklist_id=checklist.id,
                status="ESCALATED_TO_FINDING"
            )
            .all()
        )
        escalated_inquiries_data = []
        for inq in escalated_inquiries:
            escalated_inquiries_data.append({
                "inquiry_id": inq.id,
                "checklist_item_id": inq.checklist_item_id,
                "contradiction_type": inq.contradiction_type,
                "severity": inq.severity,
                "inquiry_question": inq.inquiry_question,
                "evidence_a_claim": inq.evidence_a_claim,
                "evidence_b_claim": inq.evidence_b_claim,
                "escalation_reason": inq.escalation_reason,
                "auditor_response": inq.auditor_response,
            })
        logger.info(
            f"[Module E] {len(escalated_inquiries_data)} escalated inquiries "
            f"found for checklist_id={checklist.id}"
        )

        # Build Step 6 prompt with escalated inquiries
        step6_prompt = _build_step6_prompt(required_dimensions, checklist_items, evidence_results)
        step6_prompt = step6_prompt.replace(
            "{{escalated_inquiries_json}}",
            json.dumps(escalated_inquiries_data, indent=2)
        )

        # ── 6. Run Step 6 ──────────────────────────────────────────────
        logger.info(f"[Module E] Running Step 6 for pca_id={project_control_activity_id}")
        step6_output = _call_llm_json(
            system_msg=(
                "You are an Audit Aggregation and Evaluation Engine. "
                "Return ONLY valid JSON. No markdown. No explanation."
            ),
            user_msg=step6_prompt,
        )

        if not step6_output:
            raise self.retry(exc=Exception("Step 6 LLM returned no output"), countdown=60)

        # V3 Step 6 outputs
        checklist_state_matrix = step6_output.get("checklist_state_matrix", [])
        assurance_state = step6_output.get("assurance_state", {})
        control_support_status = step6_output.get("control_support_status", {})

        # Backward compatibility mapping V3 → V2
        status_map = {
            "Supported": "PASS",
            "Partially Supported": "PARTIAL",
            "Unsupported": "FAIL",
            "Needs Further Inquiry": "PARTIAL",
            "Not Applicable": "NOT_APPLICABLE",
        }
        checklist_summary = []
        for item in checklist_state_matrix:
            state = item.get("final_state", "Partially Supported")
            checklist_summary.append({
                "checklist_id": item.get("checklist_id", ""),
                "requirement": item.get("requirement", ""),
                "final_status": status_map.get(state, "PARTIAL"),
                "final_state": state,
                "basis": item.get("basis", ""),
                "confidence": item.get("confidence", "MEDIUM"),
                "sufficiency_status": item.get("sufficiency_status", ""),
                "assurance_impact": item.get("assurance_impact", "NEUTRAL"),
            })

        # Store results
        control_result.checklist_summary_json = checklist_summary
        control_result.observations_json = []
        control_result.findings_json = []
        control_result.step6_completed = True
        control_result.updated_at = datetime.utcnow()
        control_result.sync_counts()
        control_result.sync_checklist_counts()

        # Update EveAssuranceState
        try:
            from app.models.eve_models import EveAssuranceState
            eve_assurance = db.session.query(EveAssuranceState).filter_by(
                project_checklist_id=checklist.id
            ).first()
            if eve_assurance and assurance_state:
                eve_assurance.assurance_score = float(assurance_state.get("assurance_score", 0.0))
                eve_assurance.coverage_score = float(assurance_state.get("coverage_score", 0.0))
                eve_assurance.evidence_quality_score = float(assurance_state.get("evidence_quality_score", 0.0))
                eve_assurance.oe_reliability_score = float(assurance_state.get("oe_reliability_score", 0.0))
                eve_assurance.inquiry_count = int(assurance_state.get("inquiry_count", 0))
                eve_assurance.contradiction_count = int(assurance_state.get("contradiction_count", 0))
                eve_assurance.last_updated_at = datetime.utcnow()
        except Exception as ae:
            logger.warning(f"[Module E] Could not update EveAssuranceState: {ae}")

        db.session.commit()
        # fix 2026-08-01 (#224/#238): deterministic override -- if ALL checklist
        # items are Not Applicable, control_support_status must never remain a
        # graded value that triggers a false finding below. Don't trust the LLM
        # alone for this, same pattern as the per-item final_state fix.
        if checklist_state_matrix and all(
            item.get("final_state") == "Not Applicable" for item in checklist_state_matrix
        ):
            control_support_status["final_status"] = "Not Tested"
            control_support_status["assurance_rationale"] = (
                "All checklist items resolved to Not Applicable -- no relevant "
                "evidence was submitted to evaluate this control. Not a compliance failure."
            )
            control_support_status["key_gaps"] = []
        logger.info(
            f"[Module E] Step 6 V3 done: {len(checklist_state_matrix)} items, "
            f"control_support={control_support_status.get('final_status', 'Unknown')}"
        )

        # Generate findings for Step 7
        findings = []
        if control_support_status.get("final_status") in ("Partially Supported", "Weakly Supported", "Unsupported"):
            for gap in control_support_status.get("key_gaps", []):
                findings.append({
                    "finding_id": f"F-{len(findings)+1:03d}",
                    "checklist_id": "",
                    "issue": gap,
                    "impact": "Control objective not fully supported",
                    "severity": "HIGH" if control_support_status.get("final_status") == "Unsupported" else "MEDIUM",
                })
        for inq in escalated_inquiries_data:
            findings.append({
                "finding_id": f"F-INQ-{inq.get('inquiry_id', '')}",
                "checklist_id": inq.get("checklist_item_id", ""),
                "issue": inq.get("escalation_reason", inq.get("inquiry_question", "")),
                "impact": "Unresolved contradiction identified during audit",
                "severity": "HIGH" if inq.get("severity") == "MATERIAL" else "MEDIUM",
            })

        # ── 7. Run Step 7 V3 (Observations + Findings + Risks + Recommendations) ──
        # Filter out-of-scope checklist items before Step 7
        checklist_state_matrix, checklist_items = _filter_checklist_for_activity(
            checklist_state_matrix, checklist_items,
            activity_description=pca.activity_description or "",
            activity_name=pca.activity_name or "",
        )
        # fix 2026-08-01 (#224/#238): structural safeguard -- a checklist item
        # correctly determined Not Applicable (per cross_evidence_consolidation)
        # must never reach Step 7's finding-generation prompt, even if the LLM
        # doesn't perfectly respect the Not Applicable final_state. Filtering
        # here makes a false finding structurally impossible, not just
        # instructed-against. Full explicit scope-statement surfacing for
        # excluded items is #235's separate scope -- not built here.
        _not_applicable_ids = {
            item.get("checklist_id") for item in checklist_state_matrix
            if item.get("final_state") == "Not Applicable"
        }
        if _not_applicable_ids:
            logger.info(
                f"[Module F] Excluding {len(_not_applicable_ids)} Not Applicable "
                f"item(s) from Step 7 finding generation: {sorted(_not_applicable_ids)}"
            )
            checklist_state_matrix = [
                i for i in checklist_state_matrix
                if i.get("checklist_id") not in _not_applicable_ids
            ]
            checklist_items = [
                i for i in checklist_items
                if i.get("id") not in _not_applicable_ids
            ]
        logger.info(f"[Module F] Running Step 7 V3 for pca_id={project_control_activity_id}")
        step7_output = _call_llm_json(
            system_msg=(
                "You are an Audit Observation, Finding, Risk, and Recommendation Engine. "
                "Return ONLY valid JSON. No markdown. No explanation."
            ),
            user_msg=_build_step7_prompt(
                checklist_state_matrix=checklist_state_matrix,
                assurance_state=assurance_state,
                evidence_sufficiency_summary=step6_output.get("evidence_sufficiency_summary", []),
                contradiction_inquiry_summary=step6_output.get("contradiction_inquiry_summary", []),
                oe_exception_summary=(
                    # Use pre-built summary if available (more reliable than LLM-generated)
                    (evidence_results[0].get("pre_built_oe_exception_summary", []) if evidence_results else [])
                    or step6_output.get("oe_exception_summary", [])
                ),
                control_support_status=control_support_status,
                checklist=checklist_items,
                findings=findings,
                control_activity_name=pca.activity_name or "",
                control_activity_description=pca.activity_description or "",
                required_dimensions=required_dimensions,
            ),
        )
        if not step7_output:
            logger.warning(f"[Module F] Step 7 returned no output for pca_id={project_control_activity_id}")
            observations = []
            findings_v3 = findings
            risks = []
            recommendations = []
            oe_exception_register = []
            inquiry_contradiction_register = []
        else:
            observations = step7_output.get("observation_register", [])
            findings_v3 = step7_output.get("findings_register", findings)
            risks = step7_output.get("risk_register", [])
            recommendations = step7_output.get("recommendation_register", [])
            oe_exception_register = step7_output.get("oe_exception_register", [])
            inquiry_contradiction_register = step7_output.get("inquiry_contradiction_register", [])

        # fix 2026-08-02 (#224/#238): hard, unconditional safeguard -- if the
        # checklist Step 7 was actually given was empty (every item filtered
        # out as Not Applicable), it has nothing legitimate to raise a finding
        # about. Discard any findings it generated anyway, rather than trust a
        # prompt instruction to prevent this -- confirmed tonight that even an
        # empty checklist + Not Tested control_support_status + empty seed
        # findings wasn't enough to stop the LLM from fabricating one.
        if not checklist_items and findings_v3:
            logger.warning(
                f"[Module F] Discarding {len(findings_v3)} finding(s) Step 7 "
                f"generated with an empty checklist for pca_id={project_control_activity_id} "
                f"-- checklist was fully Not Applicable, nothing to find."
            )
            findings_v3 = []

        # Store Step 7 V3 results
        control_result.observations_json = observations
        control_result.findings_json = findings_v3
        control_result.recommendations_json = recommendations
        if hasattr(control_result, 'risks_json'):
            control_result.risks_json = risks
        if hasattr(control_result, 'oe_exception_register_json'):
            control_result.oe_exception_register_json = oe_exception_register
        if hasattr(control_result, 'inquiry_register_json'):
            control_result.inquiry_register_json = inquiry_contradiction_register
        control_result.step7_completed = True
        control_result.updated_at = datetime.utcnow()
        db.session.commit()
        logger.info(
            f"[Module F] Step 7 V3 done: {len(observations)} obs, "
            f"{len(findings_v3)} findings, {len(risks)} risks, {len(recommendations)} recs"
        )
        # ── 8. Determine final_status and final_severity ───────────────
        # FIX B: Use findings_v3 (Step 7 LLM output) not pre-seeded findings
        # Pre-seeded findings come from Step 6 key_gaps — Step 7 may have
        # removed, merged, or changed them. Use Step 7 output for accuracy.
        final_status, final_severity = _compute_control_status(findings_v3)
        control_result.final_status = final_status
        control_result.final_severity = final_severity
        control_result.updated_at = datetime.utcnow()

        # ── Sync ProjectControlActivity legacy fields ──────────────────
        # Dashboard + reports read overall_severity_classification and
        # compliant_status from ProjectControlActivity — keep them in sync
        # with EVE final_severity / final_status so display is consistent.
        _EVE_SEV_TO_LEGACY = {
            "CRITICAL": "Critical",
            "HIGH":     "Major",
            "MEDIUM":   "Significant",
            "LOW":      "Minor",
        }
        _EVE_STATUS_TO_LEGACY = {
            "COMPLIANT":           "Compliant",
            "PARTIALLY_COMPLIANT": "Partially Compliant",
            "NON_COMPLIANT":       "Non-Compliant",
        }
        pca.overall_severity_classification = (
            _EVE_SEV_TO_LEGACY.get(final_severity, "No findings noted")
            if final_severity else "No findings noted"
        )
        pca.compliant_status = _EVE_STATUS_TO_LEGACY.get(final_status, final_status)

        db.session.commit()

        logger.info(
            f"[Module E+F] Steps 6+7 complete for pca_id={project_control_activity_id}: "
            f"status={final_status}, severity={final_severity} "
            f"→ legacy: {pca.compliant_status} / {pca.overall_severity_classification}"
        )

        return {
            "status": "success",
            "project_control_activity_id": project_control_activity_id,
            "final_status": final_status,
            "final_severity": final_severity,
            "checklist_items": len(checklist_summary),
            "observations": len(observations),
            "findings": len(findings),
            "recommendations": len(control_result.recommendations_json or []),
        }

    except self.MaxRetriesExceededError:
        return {"status": "error", "message": "Max retries exceeded", "project_control_activity_id": project_control_activity_id}
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module E+F] DB error: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module E+F] Unexpected error: {e}")
        return {"status": "error", "message": str(e), "project_control_activity_id": project_control_activity_id}


def _compute_control_status(findings: list) -> tuple[str, str | None]:
    """
    Deterministic rule — compute final_status and final_severity from findings.
    Matches EVE v2 Step 6 Sub-step 9 severity rules.
    Handles both standard (CRITICAL/HIGH/MEDIUM/LOW) and
    legacy/LLM values (SIGNIFICANT/MAJOR/MINOR).
    """
    if not findings:
        return "COMPLIANT", None

    # Normalize LLM severity values → standard values
    sev_normalize = {
        "CRITICAL":    "CRITICAL",
        "MAJOR":       "HIGH",        # LLM sometimes returns MAJOR
        "HIGH":        "HIGH",
        "SIGNIFICANT": "MEDIUM",      # LLM sometimes returns SIGNIFICANT
        "MEDIUM":      "MEDIUM",
        "MODERATE":    "MEDIUM",
        "MINOR":       "LOW",
        "LOW":         "LOW",
    }

    severities = [
        sev_normalize.get(f.get("severity", "LOW").upper(), "LOW")
        for f in findings
    ]
    severity_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    max_sev = max(severities, key=lambda s: severity_order.get(s, 0))

    if max_sev == "CRITICAL":
        return "NON_COMPLIANT", "CRITICAL"
    elif max_sev == "HIGH":
        return "PARTIALLY_COMPLIANT", "HIGH"
    elif max_sev == "MEDIUM":
        return "PARTIALLY_COMPLIANT", "MEDIUM"
    else:
        return "PARTIALLY_COMPLIANT", "LOW"


# ─────────────────────────────────────────────────────────────
# MODULE G — Task: run_eve_step8_clause_rollup
# EVE Step 8 per project_clause
# ─────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_eve_step8_clause_rollup(self, project_clause_id: int, generated_by: int = None):
    """
    Module G — EVE Step 8: Aggregate all control activity results
    under a clause into a single clause-level result.

    Stores clause_rollup_json in each EveControlResult under this clause.

    Args:
        project_clause_id: ID from project_clauses table
        generated_by: User ID who triggered this (optional)
    """
    logger.info(f"[Module G] Starting Step 8 for project_clause_id={project_clause_id}")

    try:
        # ── 1. Load project clause ─────────────────────────────────────
        project_clause = db.session.query(ProjectClause).get(project_clause_id)
        if not project_clause:
            return {"status": "error", "message": f"ProjectClause {project_clause_id} not found"}

        # ── 2. Get clause text from master clauses table ───────────────
        clause_text = ""
        if project_clause.original_clause_id:
            original = db.session.query(Clauses).get(project_clause.original_clause_id)
            if original:
                clause_text = getattr(original, "clause_text", "") or ""

        # ── 3. Get all APPLICABLE PCAs under this project clause ──────
        pcas = (
            db.session.query(ProjectControlActivity)
            .join(
                ProjectComplianceActivity,
                ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id,
            )
            .filter(
                ProjectComplianceActivity.project_clause_id == project_clause_id,
                ProjectComplianceActivity.applicability == True,   # applicable only
            )
            .all()
        )

        if not pcas:
            return {
                "status": "error",
                "message": "No applicable control activities found under this clause",
                "project_clause_id": project_clause_id,
            }

        # ── 4. Check all Steps 6+7 are done ───────────────────────────
        pca_ids = [pca.id for pca in pcas]
        control_results = (
            db.session.query(EveControlResult)
            .filter(EveControlResult.project_control_activity_id.in_(pca_ids))
            .all()
        )

        completed_ids = {cr.project_control_activity_id for cr in control_results if cr.step7_completed}
        pending = [pid for pid in pca_ids if pid not in completed_ids]

        if pending:
            logger.warning(
                f"[Module G] {len(pending)} control activities still pending Steps 6+7: {pending}"
            )
            return {
                "status": "pending",
                "message": f"{len(pending)} control activities not yet completed Steps 6+7",
                "pending_pca_ids": pending,
                "project_clause_id": project_clause_id,
            }

        # ── 5. Build control_outputs for Step 8 ───────────────────────
        control_outputs = []
        for cr in control_results:
            # Filter findings — exclude ACCEPTED findings (auditor cleared them)
            raw_findings = cr.findings_json or []
            filtered_findings = []
            closed_finding_ids = set()
            accepted_count = 0

            for f in raw_findings:
                auditor_status = f.get("auditor_status") if isinstance(f, dict) else None
                if auditor_status == "ACCEPTED":
                    accepted_count += 1
                    logger.info(
                        f"[Module G] Excluding ACCEPTED finding {f.get('finding_id', '?')} "
                        f"from control_id={cr.project_control_activity_id}"
                    )
                elif auditor_status == "CLOSED":
                    closed_finding_ids.add(f.get("finding_id"))
                    logger.info(
                        f"[Module G] Excluding CLOSED finding {f.get('finding_id', '?')} "
                        f"from control_id={cr.project_control_activity_id}"
                    )
                else:
                    filtered_findings.append(f)

            if accepted_count or closed_finding_ids:
                logger.info(
                    f"[Module G] control_id={cr.project_control_activity_id}: "
                    f"excluded {accepted_count} ACCEPTED + {len(closed_finding_ids)} CLOSED findings, "
                    f"{len(filtered_findings)} remaining"
                )

            # Filter recommendations — exclude those linked to CLOSED/ACCEPTED findings
            raw_recs = cr.recommendations_json or []
            filtered_recs = []
            excluded_finding_ids = closed_finding_ids  # ACCEPTED findings also excluded above
            for f in raw_findings:
                if isinstance(f, dict) and f.get("auditor_status") == "ACCEPTED":
                    excluded_finding_ids.add(f.get("finding_id"))

            for rec in raw_recs:
                if isinstance(rec, dict):
                    rec_finding_id = rec.get("finding_id") or rec.get("related_finding_id")
                    if rec_finding_id and rec_finding_id in excluded_finding_ids:
                        logger.info(
                            f"[Module G] Excluding recommendation linked to "
                            f"{'CLOSED' if rec_finding_id in closed_finding_ids else 'ACCEPTED'} "
                            f"finding {rec_finding_id}"
                        )
                        continue
                filtered_recs.append(rec)

            control_outputs.append({
                "control_id": cr.project_control_activity_id,
                "observations": cr.observations_json or [],
                "findings": filtered_findings,
                "recommendations": filtered_recs,
            })

        if not control_outputs:
            return {"status": "error", "message": "No control results to aggregate"}

        # ── 6. Run Step 8 ──────────────────────────────────────────────
        logger.info(f"[Module G] Running Step 8 for project_clause_id={project_clause_id}")
        step8_output = _call_llm_json(
            system_msg=(
                "You are an Audit Clause Aggregation Engine. "
                "Return ONLY valid JSON. No markdown. No explanation."
            ),
            user_msg=_build_step8_prompt(
                clause_id=project_clause_id,
                clause_text=clause_text or "Not available",
                control_outputs=control_outputs,
            ),
        )

        if not step8_output:
            raise self.retry(exc=Exception("Step 8 LLM returned no output"), countdown=60)

        # ── 7. Store clause_rollup_json in ALL control results ─────────
        for cr in control_results:
            cr.clause_rollup_json = step8_output
            cr.step8_completed = True
            cr.updated_at = datetime.utcnow()

        db.session.commit()

        clause_status = step8_output.get("clause_status", "")
        clause_severity = step8_output.get("clause_severity", "")
        findings_count = len(step8_output.get("findings", []))
        recommendations_count = len(step8_output.get("recommendations", []))

        logger.info(
            f"[Module G] Step 8 complete for project_clause_id={project_clause_id}: "
            f"status={clause_status}, severity={clause_severity}, "
            f"findings={findings_count}, recommendations={recommendations_count}"
        )

        return {
            "status": "success",
            "project_clause_id": project_clause_id,
            "clause_status": clause_status,
            "clause_severity": clause_severity,
            "findings_count": findings_count,
            "recommendations_count": recommendations_count,
            "controls_aggregated": len(control_results),
        }

    except self.MaxRetriesExceededError:
        return {"status": "error", "message": "Max retries exceeded", "project_clause_id": project_clause_id}
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module G] DB error: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module G] Unexpected error: {e}")
        return {"status": "error", "message": str(e), "project_clause_id": project_clause_id}
