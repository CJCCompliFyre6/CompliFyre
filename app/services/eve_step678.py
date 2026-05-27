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
                model="gpt-4o-mini",
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
  {json.dumps(checklist, indent=2)}

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

PRINCIPLE 3 — MULTI-EVIDENCE CONSOLIDATION:
Consolidate corroborative evidence. Reconcile overlapping evidence. Preserve evidence lineage.
Disclose which evidence sources contributed to final support status.

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
* IF exception_rate > 0 AND ≤ 10% → Partially Supported
* IF exception_rate > 10% → Unsupported

---

OUTPUT FORMAT (return ONLY this JSON structure):

{{{{
  "checklist_state_matrix": [
    {{{{
      "checklist_id": "",
      "requirement": "",
      "final_state": "Supported | Partially Supported | Unsupported | Needs Further Inquiry",
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
    "final_status": "Fully Supported | Partially Supported | Weakly Supported | Unsupported",
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
* final_state must use exact values: Supported / Partially Supported / Unsupported / Needs Further Inquiry
* final_status must use exact values: Fully Supported / Partially Supported / Weakly Supported / Unsupported"""



def _build_step7_prompt(
    checklist_state_matrix: list,
    assurance_state: dict,
    evidence_sufficiency_summary: list,
    contradiction_inquiry_summary: list,
    oe_exception_summary: list,
    control_support_status: dict,
    checklist: list,
    findings: list = None,
) -> str:
    """Build EVE Step 7 prompt — V3 with 13 principles."""

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

INPUT FROM STEP 6:

* Checklist State Matrix:
  {json.dumps(checklist_state_matrix, indent=2)}

* Assurance State:
  {json.dumps(assurance_state, indent=2)}

* Evidence Sufficiency Summary:
  {json.dumps(evidence_sufficiency_summary, indent=2)}

* Contradiction / Inquiry Summary:
  {json.dumps(contradiction_inquiry_summary, indent=2)}

* OE Exception Summary:
  {json.dumps(oe_exception_summary, indent=2)}

* Control Support Status:
  {json.dumps(control_support_status, indent=2)}

* Checklist Items:
  {json.dumps(checklist, indent=2)}

---

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
      "finding_summary": "",
      "finding_type": "D | IE | OE | Evidence Integrity | Inquiry",
      "related_checklist_ids": [],
      "root_issue": "",
      "evidence_basis": "",
      "regulatory_impact": "",
      "operational_impact": "",
      "residual_risk": "",
      "severity": "Low | Medium | High | Critical",
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
    return f"""You are an Audit Clause Aggregation Engine.

TASK:
Aggregate outputs from multiple control activities into a single clause-level result.

You must:
* consolidate observations
* merge and group findings using predefined categories
* retain full traceability
* consolidate recommendations aligned to merged findings
* determine clause-level status and severity

Return ONLY valid JSON.

DO NOT:
* re-evaluate evidence
* generate new findings
* generate new recommendations from scratch
* assume missing information

---

INPUT:
{{
  "clause_id": "{clause_id}",
  "clause_text": {json.dumps(clause_text)},
  "control_outputs": {json.dumps(control_outputs, indent=2)}
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

SUB-STEP-2 — GROUP FINDINGS INTO CONTROLLED CATEGORIES
Assign each finding to EXACTLY ONE group from the 8 categories above.
Group based on ROOT CAUSE (not symptom).
Priority: Oversight > Governance > Risk > Roles > Implementation > Documentation > Evidence > Regulatory

SUB-STEP-3 — MERGE FINDINGS
Within each group:
* Merge findings that represent the SAME underlying issue
* Do NOT merge unrelated issues
* Merged Severity = MAX(severity of grouped findings)
* Each merged finding must include source_references with control_id, checklist_id, evidence_reference

SUB-STEP-4 — CONSOLIDATE RECOMMENDATIONS
* Map recommendations to merged findings using finding_id linkage
* Combine recommendations addressing same issue
* Do NOT generate new recommendations
* Merged timeline = MOST URGENT: IMMEDIATE > SHORT_TERM > MEDIUM_TERM > LONG_TERM

SUB-STEP-5 — DETERMINE CLAUSE SEVERITY
Clause Severity = MAX(severity across all merged findings)

SUB-STEP-6 — DETERMINE CLAUSE STATUS
IF any finding severity = CRITICAL → clause_status = NON_COMPLIANT
ELSE IF any finding severity = HIGH → clause_status = PARTIALLY_COMPLIANT
ELSE → clause_status = COMPLIANT

SUB-STEP-7 — GENERATE CLAUSE SUMMARY
Write a concise paragraph: what was assessed, key strengths (if any), key issues, overall conclusion.
Tone: formal, auditor-style, evidence-based, no vague language.

OUTPUT FORMAT:
{{
  "clause_id": "{clause_id}",
  "clause_text": "",
  "clause_status": "",
  "clause_severity": "",
  "summary": "",
  "observations": [],
  "findings": [
    {{
      "finding_id": "",
      "group": "",
      "issue": "",
      "impact": "",
      "severity": "",
      "source_references": [
        {{"control_id": "", "checklist_id": "", "evidence_reference": ""}}
      ]
    }}
  ],
  "recommendations": [
    {{"finding_id": "", "recommendation": "", "implementation_steps": [], "timeline": ""}}
  ]
}}

STRICT CONSTRAINTS:
* Do NOT duplicate findings
* Do NOT lose traceability
* Do NOT weaken severity
* Do NOT introduce new issues
* Observations must remain evidence-linked
* Recommendations must map 1:1 to merged findings"""


# ─────────────────────────────────────────────────────────────
# Helper — build evidence results input for Step 6
# from EveEvidenceResult rows
# ─────────────────────────────────────────────────────────────

def _build_evidence_results_for_step6(checklist_id: int) -> list:
    """
    Fetch all EveEvidenceResult rows for a project_checklist
    and format them as Step 6 input.
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
            evidence_map[eid] = {
                "evidence_id": eid,
                "evidence_type": r.evidence_type or "",
                "admissibility": r.admissibility,
                "confidence": r.confidence or "MEDIUM",
                "evidence_meta": {
                    "strength": r.evidence_strength or "MODERATE",
                    "role": r.evidence_role or "SUPPORTING",
                },
                "item_signals": [],
                "results": [],
                "sample_evaluation": {
                    "applicable": "YES" if r.sample_applicable else "NO",
                    "sample_size": r.sample_size,
                    "population_size": r.population_size,
                    "exception_rate": float(r.exception_rate) if r.exception_rate else None,
                    "within_audit_period": "YES" if r.sample_within_audit_period else "NO",
                },
            }

        evidence_map[eid]["item_signals"].append({
            "checklist_id": r.checklist_item_id,
            "signal": r.signal,
            "basis": r.signal_basis or "",
            "confidence": r.confidence or "MEDIUM",
        })
        evidence_map[eid]["results"].append({
            "checklist_id": r.checklist_item_id,
            "status": r.item_status,
            "evidence_reference": r.evidence_reference or "",
            "confidence": r.confidence or "MEDIUM",
        })

    return list(evidence_map.values())


# ─────────────────────────────────────────────────────────────
# MODULE E+F — Task: run_eve_step6_and_7
# EVE Steps 6+7 per project_control_activity
# ─────────────────────────────────────────────────────────────

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

        # ── 3. Check if Step 5 results exist ──────────────────────────
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
                oe_exception_summary=step6_output.get("oe_exception_summary", []),
                control_support_status=control_support_status,
                checklist=checklist_items,
                findings=findings,
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
        final_status, final_severity = _compute_control_status(findings)
        control_result.final_status = final_status
        control_result.final_severity = final_severity
        control_result.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(
            f"[Module E+F] Steps 6+7 complete for pca_id={project_control_activity_id}: "
            f"status={final_status}, severity={final_severity}"
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
    """
    if not findings:
        return "COMPLIANT", None

    severities = [f.get("severity", "LOW") for f in findings]
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

        # ── 3. Get all PCAs under this project clause ──────────────────
        pcas = (
            db.session.query(ProjectControlActivity)
            .join(
                ProjectComplianceActivity,
                ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id,
            )
            .filter(ProjectComplianceActivity.project_clause_id == project_clause_id)
            .all()
        )

        if not pcas:
            return {
                "status": "error",
                "message": "No control activities found under this clause",
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
            control_outputs.append({
                "control_id": cr.project_control_activity_id,
                "observations": cr.observations_json or [],
                "findings": cr.findings_json or [],
                "recommendations": cr.recommendations_json or [],
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
