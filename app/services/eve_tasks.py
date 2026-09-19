# app/services/eve_tasks.py
#
# Module A — EVE Step 1: Guideline Context Classification
# Module B — EVE Steps 3+4: Checklist Generation
#
# These tasks run on the Complifyre side (RE/Admin), NOT the auditor side.
# They are run once per guideline / control activity and stored centrally.
#
# Celery queues used:
#   eve_context      — Module A tasks
#   eve_checklist    — Module B tasks

import json
import time
import logging
from datetime import datetime

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, field_validator

from app import db, client
from app.models.ai import Guidelines, ControlActivity
from app.models.eve_models import (
    GuidelineEveContext,
    ControlChecklist,
    ProjectChecklist,
    ClauseChecklistReview,
)
from app.models.project_instance_models import ProjectControlActivity

logger = get_task_logger(__name__)


# ============================================================
# Pydantic schemas — enforce structured JSON output from LLM
# ============================================================

class EveContextSchema(BaseModel):
    """EVE Step 1 output schema — must match exactly what the prompt returns."""
    regulation_type: str
    domain: str
    auditor_profile: str

    @field_validator("regulation_type")
    @classmethod
    def validate_regulation_type(cls, v):
        valid = {
            "RBI", "SEBI", "IRDAI", "NABARD", "ISO",
            "PCI_DSS", "SWIFT", "DPDP", "GDPR", "BASEL", "OTHER"
        }
        if v not in valid:
            raise ValueError(f"Invalid regulation_type: {v}. Must be one of {valid}")
        return v

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v):
        valid = {
            "INFOSEC", "DATA_PRIVACY", "CREDIT_RISK", "MARKET_RISK",
            "OPERATIONAL_RISK", "IT_GOVERNANCE", "VENDOR_RISK", "FINANCIAL_REPORTING"
        }
        if v not in valid:
            raise ValueError(f"Invalid domain: {v}. Must be one of {valid}")
        return v

    @field_validator("auditor_profile")
    @classmethod
    def validate_auditor_profile(cls, v):
        valid = {
            "INFOSEC_AUDITOR", "PRIVACY_AUDITOR", "ITGC_AUDITOR",
            "RISK_AUDITOR", "FINANCIAL_AUDITOR"
        }
        if v not in valid:
            raise ValueError(f"Invalid auditor_profile: {v}. Must be one of {valid}")
        return v


class EveChecklistSchema(BaseModel):
    """EVE Steps 3+4 output schema."""
    required_dimensions: dict
    checklist: list
    admissibility_requirements: dict
    sampling_rules: dict
    dimension_rules: dict
    scoring_rules: dict


# ============================================================
# Utility — direct OpenAI chat call (no vector store needed)
# Context classification works from guideline name alone.
# temperature=0 for maximum determinism.
# ============================================================

def _call_llm_json(prompt: str, retries: int = 2, backoff: float = 2.0) -> dict | None:
    """
    Call OpenAI with temperature=0 and expect a JSON response.
    Returns parsed dict or None on failure.
    """
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                max_tokens=16000,
                temperature=0,        # deterministic — same input = same output
                top_p=0.1,
                timeout=900,           # hard cap — data showed genuine calls up to 714s, cuts hung calls beyond that
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a compliance classification engine. "
                            "Return ONLY valid JSON. No explanation. No markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
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

    logger.error("All LLM retries exhausted — returning None")
    return None


# ============================================================
# MODULE A — Task: generate_guideline_eve_context
# EVE Step 1 — Context Classification
#
# Input:  guideline_id (int)
# Output: GuidelineEveContext row in DB
#
# Called from: RE dashboard when guideline is ready
# Queue: eve_context
# ============================================================

def _build_context_prompt(guideline_name: str) -> str:
    """Build EVE Step 1 prompt — exactly matches the excel sheet Step 1."""
    return f"""You are a compliance context classifier for BFSI regulations.

TASK:
Classify the given guideline into a structured audit context.
Return ONLY JSON. No explanation.

INPUT:
- Guideline Name: {guideline_name}
- Industry: BFSI
- Geography: India

RULES:
1. Regulation Type Mapping:
   - RBI guidelines → RBI
   - SEBI regulations → SEBI
   - IRDAI guidelines → IRDAI
   - NABARD → NABARD
   - ISO standards → ISO
   - PCI DSS → PCI_DSS
   - SWIFT CSP → SWIFT
   - DPDP Act → DPDP
   - GDPR → GDPR
   - Basel norms → BASEL
   - Otherwise → OTHER

2. Domain Mapping:
   - Cyber security, access control, IT security → INFOSEC
   - Personal data protection → DATA_PRIVACY
   - Lending, credit appraisal → CREDIT_RISK
   - Market exposure, trading → MARKET_RISK
   - Internal processes, fraud, ops → OPERATIONAL_RISK
   - IT controls, system governance → IT_GOVERNANCE
   - Third-party/vendor outsourcing → VENDOR_RISK
   - Financial statements, accounting → FINANCIAL_REPORTING

3. Auditor Profile Mapping:
   - INFOSEC → INFOSEC_AUDITOR
   - DATA_PRIVACY → PRIVACY_AUDITOR
   - IT_GOVERNANCE → ITGC_AUDITOR
   - CREDIT_RISK / MARKET_RISK / OPERATIONAL_RISK / VENDOR_RISK → RISK_AUDITOR
   - FINANCIAL_REPORTING → FINANCIAL_AUDITOR

OUTPUT FORMAT:
{{
  "regulation_type": "",
  "domain": "",
  "auditor_profile": ""
}}"""


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_guideline_eve_context(self, guideline_id: int, generated_by: int = None):
    """
    Module A — EVE Step 1: Classify a guideline into regulation type,
    domain, and auditor profile. Stores result in guideline_eve_context.

    Args:
        guideline_id:  ID from the guidelines table
        generated_by:  User ID who triggered this task (optional)

    Returns:
        dict with status, guideline_id, and context data
    """
    logger.info(f"[Module A] Starting context classification for guideline_id={guideline_id}")

    try:
        # ── 1. Load guideline ──────────────────────────────────────────
        guideline = db.session.query(Guidelines).get(guideline_id)
        if not guideline:
            logger.error(f"Guideline {guideline_id} not found")
            return {
                "status": "error",
                "message": f"Guideline {guideline_id} not found",
                "guideline_id": guideline_id,
            }

        # ── 2. Check if context already exists ────────────────────────
        existing = (
            db.session.query(GuidelineEveContext)
            .filter_by(guideline_id=guideline_id)
            .first()
        )
        if existing:
            logger.info(
                f"Context already exists for guideline_id={guideline_id} "
                f"(regulation_type={existing.regulation_type}) — skipping"
            )
            return {
                "status": "already_exists",
                "message": "Context already classified",
                "guideline_id": guideline_id,
                "regulation_type": existing.regulation_type,
                "domain": existing.domain,
                "auditor_profile": existing.auditor_profile,
            }

        # ── 3. Extract guideline name from guideline_data JSON ─────────
        guideline_name = None
        if guideline.guideline_data:
            gdata = guideline.guideline_data
            if isinstance(gdata, dict):
                guideline_name = (
    gdata.get("guideline_name")
    or gdata.get("name")
    or gdata.get("title")
    or gdata.get("guideline_title")
    or (gdata.get("DocumentDetails") or {}).get("DocumentName")
)
            elif isinstance(gdata, str):
                guideline_name = gdata[:200]

        if not guideline_name:
            logger.error(f"Cannot extract guideline name for guideline_id={guideline_id}")
            return {
                "status": "error",
                "message": "Guideline name could not be extracted from guideline_data",
                "guideline_id": guideline_id,
            }

        logger.info(f"[Module A] Guideline name: '{guideline_name}'")

        # ── 4. Build prompt and call LLM ──────────────────────────────
        prompt = _build_context_prompt(guideline_name)
        raw_output = _call_llm_json(prompt)

        if not raw_output:
            raise self.retry(
                exc=Exception("LLM returned no output"),
                countdown=60,
            )

        # ── 5. Validate output against schema ─────────────────────────
        try:
            validated = EveContextSchema(**raw_output)
        except Exception as e:
            logger.error(f"[Module A] Schema validation failed: {e} — raw: {raw_output}")
            raise self.retry(
                exc=Exception(f"Schema validation failed: {e}"),
                countdown=60,
            )

        # ── 6. Store in DB ────────────────────────────────────────────
        context_record = GuidelineEveContext(
            guideline_id=guideline_id,
            regulation_type=validated.regulation_type,
            domain=validated.domain,
            auditor_profile=validated.auditor_profile,
            raw_output_json=raw_output,
            generated_at=datetime.utcnow(),
            generated_by=generated_by,
        )
        db.session.add(context_record)
        db.session.commit()

        logger.info(
            f"[Module A] Context saved for guideline_id={guideline_id}: "
            f"regulation_type={validated.regulation_type}, "
            f"domain={validated.domain}, "
            f"auditor_profile={validated.auditor_profile}"
        )

        return {
            "status": "success",
            "guideline_id": guideline_id,
            "regulation_type": validated.regulation_type,
            "domain": validated.domain,
            "auditor_profile": validated.auditor_profile,
        }

    except self.MaxRetriesExceededError:
        logger.error(f"[Module A] Max retries exceeded for guideline_id={guideline_id}")
        return {
            "status": "error",
            "message": "Max retries exceeded",
            "guideline_id": guideline_id,
        }
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module A] DB error for guideline_id={guideline_id}: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module A] Unexpected error for guideline_id={guideline_id}: {e}")
        return {
            "status": "error",
            "message": str(e),
            "guideline_id": guideline_id,
        }


# ============================================================
# MODULE B — Task: generate_control_checklist
# EVE Steps 3+4 — Checklist Generation
#
# Input:  control_activity_id (int)
# Output: ControlChecklist row in DB
#
# Called from: RE dashboard after test procedures are ready
# Queue: eve_checklist
# ============================================================

def _build_checklist_prompt(
    regulation_type: str,
    domain: str,
    auditor_profile: str,
    clause_text: str,
    control_activity: str,
    test_procedure: str,
    evidence_list: str,
    control_type: str = "Unknown",
    frequency: str = "Unknown",
) -> str:
    """Build EVE v3 Step 4 prompt — all 15 principles implemented."""

    return f"""You are a Control Decomposition Engine for BFSI regulatory audits.

TASK: Convert an existing control definition into a structured, deterministic, auditable atomic checklist.

IMPORTANT:
* Do NOT evaluate any evidence
* Do NOT assume any evidence content
* Do NOT generate observations, findings, or conclusions
* Only define HOW the control should be tested

Return ONLY valid JSON. No explanation. No markdown.

---

INPUT:
* Regulation Type: {regulation_type}
* Domain: {domain}
* Auditor Profile: {auditor_profile}
* Control Type: {control_type}
* Frequency: {frequency}
* Clause: {clause_text}
* Control Activity: {control_activity}
* Test Procedure: {test_procedure}
* Evidence List: {evidence_list}

---

CONTROL TYPE + FREQUENCY DIMENSION OVERRIDE RULES (CRITICAL — apply FIRST before intent classification):
These rules take absolute priority over intent-based classification:

RULE A: Control Type = Detective → ALWAYS include OPERATING dimension. Never generate only DESIGN items for Detective controls.
RULE B: Frequency = Per Transaction OR Per Instance OR Per Event → OPERATING mandatory.
RULE C: Frequency = One Time → DESIGN only, NEVER OPERATING.
RULE D: Control Type = Governance AND Frequency = One Time → DESIGN only.
RULE E: Control Type = Preventive AND Frequency = ongoing (Daily/Weekly/Monthly/Per Transaction) → DESIGN + OPERATING.

DIMENSION EXAMPLES:
  Detective + Per Transaction → DESIGN=NO, IMPLEMENTATION=NO, OPERATING=YES
  Governance + One Time → DESIGN=YES, IMPLEMENTATION=NO, OPERATING=NO
  Preventive + Monthly → DESIGN=YES, IMPLEMENTATION=YES, OPERATING=YES
  Detective + Monthly → DESIGN=NO, IMPLEMENTATION=NO, OPERATING=YES

---

STEP 3 — DETERMINE REQUIRED EFFECTIVENESS DIMENSIONS (INTENT-DRIVEN)
IMPORTANT: Before classifying intent, check the CONTROL TYPE + FREQUENCY OVERRIDE RULES above.
If Control Type = Detective OR Frequency = Per Transaction → set DESIGN=NO, IMPLEMENTATION=NO, OPERATING=YES and SKIP the rest of STEP 3.
If Frequency = One Time → set DESIGN=YES, IMPLEMENTATION=NO, OPERATING=NO and SKIP the rest of STEP 3.
Only proceed with intent classification below if no override rule applies.


Classify intent into one or more of:
* GOVERNANCE → policy/framework/documentation/approval
* CONFIGURATION → system setup/technical enforcement
* EXECUTION → ongoing process/review/monitoring/operation
* OUTCOME → required end-state (ensure, prevent, protect)

RULES:
1. GOVERNANCE-ONLY: If clause primarily requires documentation/governance with NO signals of execution, configuration or outcome → Intent = [GOVERNANCE] ONLY
2. OUTCOME DOMINANCE: If clause requires a state/result → Intent = [OUTCOME] ONLY
3. OTHERWISE: Select maximum 2 intents based on clear signals
4. CONFLICT PRIORITY: OUTCOME > EXECUTION > CONFIGURATION > GOVERNANCE

CRITICAL DIMENSION CLASSIFICATION RULES:
* EXECUTION intent ONLY when clause EXPLICITLY requires:
  - Ongoing operations over a time period (daily/monthly/quarterly/annual)
  - Regular/periodic activities with defined frequency
  - Transaction-level controls or population-based testing
  - Monitoring of ongoing operations
* NEVER classify as EXECUTION for:
  - One-time documentation activities (drafting, developing, establishing)
  - Framework development or policy creation
  - Governance structure establishment
  - Board approval activities
  - One-time training or rollout activities
* IMPLEMENTATION intent ONLY when clause requires:
  - Active rollout or deployment of a system/process
  - Training and awareness programs
  - System configuration or activation
* NEVER set OPERATING=YES for one-time or documentation-only controls

DIMENSION MAPPING (FIXED):
* GOVERNANCE: DESIGN=YES, IMPLEMENTATION=NO, OPERATING=NO
* CONFIGURATION: DESIGN=NO, IMPLEMENTATION=YES, OPERATING=YES
* EXECUTION: DESIGN=YES, IMPLEMENTATION=YES, OPERATING=YES
* OUTCOME: DESIGN=YES, IMPLEMENTATION=YES, OPERATING=YES

FINAL DIMENSIONS = UNION of selected intent mappings.

---

STEP 4 — GENERATE ATOMIC CHECKLIST (ALL 15 PRINCIPLES ENFORCED)

PRINCIPLE 1 — ATOMICITY (MANDATORY):
Each checklist item must:
* represent ONE auditable assertion only
* test a SINGLE control expectation
* be independently verifiable
* avoid narrative phrasing, broad governance language, multi-condition assertions, or subjective judgments

PRINCIPLE 2 — BINARY + TRACEABLE (MANDATORY):
Each checklist item must:
* be testable as YES / NO / PARTIAL / NEEDS_REVIEW
* rely solely on objective evidence
* be traceable to exact evidence locations
Every evaluation result MUST contain: supporting extracted evidence text + exact location + source reference.

PRINCIPLE 3 — EFFECTIVENESS DIMENSION AWARENESS (MANDATORY):
* DESIGN (D) items: ONLY test existence, documented structure, governance, formalization, defined controls. Must NOT assess execution or operational adoption.
* IMPLEMENTATION EFFECTIVENESS (IE) items: test operationalization — rollout, training, workflow activation. Must NOT conclude sustained operational effectiveness.
* OPERATING EFFECTIVENESS (OE) items: test execution over audit period — attribute testing, sample testing, population testing, exception testing, trend analysis.

PRINCIPLE 4 — ATTRIBUTE/POPULATION TESTING (OE ITEMS ONLY):
For all OE checklist items where applicable, define population_scope, instance_identifier, attribute_being_tested, pass_criteria, fail_criteria, exception_logic.

PRINCIPLE 5 — LOGICAL INTEGRITY TESTING:
Include logical validation items wherever relevant to validate chronology, cross-document consistency, audit period alignment, version alignment.
CRITICAL RULE: Detected contradictions must generate INQUIRY triggers — NOT automatic failures.

PRINCIPLE 6 — CONTEXTUAL INFERENCE:
Checklist items must reflect operational intent. Controlled contextual inference permitted only where organizational/process structure reasonably supports it.
Each item must define: whether inference is permitted, the basis, and what is prohibited.

PRINCIPLE 7 — MULTI-EVIDENCE SOURCE MAPPING:
Each checklist item must specify one or more acceptable evidence sources.

PRINCIPLE 8 — EVIDENCE STRENGTH CLASSIFICATION:
Each checklist item must define expected evidence strength:
* PRIMARY: direct evidence (policy, logs, config, datasets)
* SUPPORTING: indirect evidence (reports, screenshots, interviews)
* OBSERVATIONAL: walkthrough observation, process trace
* ANALYTICAL: trend analysis, reconciliation, recomputation

PRINCIPLE 9 — ASSURANCE CONTRIBUTION:
Each checklist item must specify assurance_weight (HIGH/MEDIUM/LOW) and materiality (HIGH/MEDIUM/LOW).

PRINCIPLE 10 — CHECKLIST FAMILY CLASSIFICATION:
Each item must be categorized into exactly one family:
GOVERNANCE | PROCESS | RISK | MONITORING | COMPLIANCE | TRAINING | LOGICAL_INTEGRITY | EVIDENCE_INTEGRITY | ASSURANCE

PRINCIPLE 11 — CONFIDENCE CLASSIFICATION:
* EXPLICIT: requirement directly stated in evidence → allows YES status
* IMPLIED: reasonably inferred → allows PARTIAL status only
* AMBIGUOUS: unclear or indirect → allows PARTIAL or NEEDS_REVIEW only

PRINCIPLE 12 — EVIDENCE-TO-CHECKLIST VALIDATION:
Checklist satisfaction must validate that evidence EXPLICITLY contains the assertion, NOT merely semantically resembles it.

PRINCIPLE 13 — EVIDENCE ADMISSIBILITY (5 STATES):
Distinguish between: NOT_PROVIDED | PROVIDED_INVALID | PROVIDED_INSUFFICIENT | CONTRADICTORY | VALID

PRINCIPLE 14 — INQUIRY-DRIVEN AUDIT REASONING:
Failures, contradictions, ambiguities may generate inquiry triggers BEFORE findings.
Where inquiry_trigger = YES, define the condition that triggers inquiry.

PRINCIPLE 15 — OBSERVATION/FINDING SEPARATION:
Evidence summaries must NOT generate findings or recommendations.
Findings emerge ONLY from: unresolved checklist failures, unresolved contradictions, failed logical validations, inadmissible evidence, unresolved inquiry results.

PRINCIPLE 16 — CROSS-DIMENSION PARAMETER DISCOVERY (Build Sequence #394):
DE, IE, and OE are not independent checks -- they are cumulative. Critically, DE-testing is a
DISCOVERY step, not just a pass/fail gate: the real policy document reveals organization-specific
implementation details (e.g. THIS bank's monitoring frequency, THIS bank's escalation forum) that
IE and OE items must then test against -- not a generic assumption.
* If a DESIGN item's own requirement text asks the auditor to establish a specific,
  organization-defined fact that a LATER (Implementation or Operating) item in this SAME checklist
  will need to check against (a frequency, a forum/committee name, a threshold, an approving
  authority, a methodology) -- tag that DESIGN item with discovers_parameter: a short,
  descriptive name for that fact, GROUNDED IN THIS SPECIFIC ACTIVITY'S OWN TEXT. Do NOT invent a
  parameter from a generic, external list -- only tag what this activity's own requirement or test
  procedure text genuinely implies needs discovering.
* If an IMPLEMENTATION or OPERATING item's own requirement can only be correctly evaluated once
  that organization-specific fact is known (e.g. "verify monthly reports exist" cannot be checked
  without first knowing THIS org's actual required frequency), tag that item with
  depends_on_parameter using the EXACT SAME parameter name as the DESIGN item that discovers it.
* Every discovers_parameter / depends_on_parameter tag MUST be accompanied by
  parameter_justification_quote: the exact, verbatim sentence or phrase from the Test Procedure or
  Control Activity input above that justifies this tag. This is verified mechanically after
  generation -- a tag whose quote cannot be found, verbatim, in the actual input text will be
  discarded, so do not paraphrase or summarize here.
* Most checklist items will have NEITHER field set (most items are standalone, self-contained
  checks) -- only tag items where a genuine, real dependency exists between two specific items in
  this checklist. Do not force every item into this pattern.
* A depends_on_parameter with no matching discovers_parameter anywhere in the same checklist will
  be treated as an error and dropped -- only reference a parameter you are also discovering
  somewhere in this same output.

---

STEP 4.1 — IDENTIFY CONTROL PATTERN

Classify into one or more of:
REVIEW_CONTROL | APPROVAL_CONTROL | RECONCILIATION_CONTROL | ACCESS_CONTROL |
TRANSACTION_CONTROL | MONITORING_CONTROL | CONFIGURATION_CONTROL | DOCUMENTATION_CONTROL

---

STEP 4.2 — ENFORCE CONTROL COMPLETENESS (CRITICAL)

If control involves review, approval, or exception handling, checklist MUST cover full lifecycle:
IDENTIFICATION → VALIDATION → APPROVAL → EXCEPTION → REMEDIATION → EVIDENCE

MANDATORY for REVIEW / ACCESS / MONITORING controls:
1. Population completeness
2. Execution of control
3. Reviewer identification
4. Approval validation
5. Exception identification
6. Exception justification documented
7. Exception remediation performed
8. Evidence of remediation / closure available

---

STEP 4.2.1 — ENUMERATED REQUIREMENTS (CRITICAL)

If the regulatory clause explicitly enumerates specific areas, products, or activities (e.g., numbered list, bulleted list), you MUST:
* Generate a SEPARATE checklist item for EACH enumerated area/product/activity
* Each item must verify whether the policy/document covers that specific area
* Use pass_condition: "Policy explicitly covers [specific area]"
* Use fail_condition: "Policy does not address [specific area]"
* Do NOT consolidate multiple enumerated areas into a single checklist item
* Mark illustrative examples (introduced by "such as", "inter alia", "including") as IMPLIED confidence
* Mark explicitly numbered/listed items as EXPLICIT confidence

EXAMPLE: If clause says "(1) Digital Lending (2) Gold Loans (3) Housing Finance" — generate CHK_001 for Digital Lending, CHK_002 for Gold Loans, CHK_003 for Housing Finance as separate items.

---

STEP 4.3 — GENERATE ATOMIC CHECKLIST

For each checklist item output EXACTLY this JSON structure:

{{{{
  "id": "CHK_###",
  "requirement": "Single atomic testable assertion only",
  "checklist_family": "GOVERNANCE | PROCESS | RISK | MONITORING | COMPLIANCE | TRAINING | LOGICAL_INTEGRITY | EVIDENCE_INTEGRITY | ASSURANCE",
  "control_pattern": "REVIEW_CONTROL | APPROVAL_CONTROL | RECONCILIATION_CONTROL | ACCESS_CONTROL | TRANSACTION_CONTROL | MONITORING_CONTROL | CONFIGURATION_CONTROL | DOCUMENTATION_CONTROL",
  "lifecycle_stage": "IDENTIFICATION | VALIDATION | APPROVAL | EXCEPTION | REMEDIATION | EVIDENCE | NA",
  "effectiveness_type": "DESIGN | IMPLEMENTATION | OPERATING",
  "discovers_parameter": "Short parameter name this DESIGN item discovers, or null (Principle 16)",
  "depends_on_parameter": "Exact parameter name this item depends on, or null (Principle 16)",
  "parameter_justification_quote": "Verbatim quote from Test Procedure/Control Activity justifying the tag above, or null",
  "dimension_test_scope": "Describe exactly what to test for this dimension — do not cross dimension boundaries",
  "weight": "HIGH | MEDIUM | LOW",
  "assurance_weight": "HIGH | MEDIUM | LOW",
  "materiality": "HIGH | MEDIUM | LOW",
  "testing_method": "DOCUMENT_REVIEW | CONTENT_VALIDATION | APPROVAL_VALIDATION | CONFIGURATION_VALIDATION | ATTRIBUTE_VERIFICATION | SAMPLE_TESTING | LOG_REVIEW | TIMELINE_VALIDATION | RECONCILIATION | PROCESS_TRACE | DIAGRAM_ANALYSIS | COMMUNICATION_VALIDATION | THIRD_PARTY_VALIDATION | EXCEPTION_ANALYSIS",
  "testing_approach": "FULL | SAMPLE | TREND | RECOMPUTE | WALKTHROUGH",
  "expected_evidence_types": ["SPECIFIC EVIDENCE TYPES THAT WOULD CONTAIN PROOF FOR THIS ITEM"],
  // CRITICAL — expected_evidence_types RULES:
  // Set this based on the REQUIREMENT TEXT of this specific checklist item — not the overall activity.
  // Examples:
  //   Requirement mentions "approval signatures" → ["Policy Documents", "Signed Agreements"]
  //   Requirement mentions "meeting minutes" or "board resolution" → ["Board Meeting Minutes", "Board Resolutions"]
  //   Requirement mentions "training records" or "attendance" → ["Training Records", "Attendance Logs"]
  //   Requirement mentions "system logs" or "audit trail" → ["System Logs", "Audit Trail Reports"]
  //   Requirement mentions "transaction data" or "loan register" → ["Transaction Data", "Loan Register", "Excel Reports"]
  //   Requirement mentions "policy document" or "framework" → ["Policy Documents", "Control Frameworks"]
  //   Requirement mentions "communication" or "notice" → ["Email Communications", "Notices", "Circulars"]
  // NEVER set all items to the same evidence type — each item should reflect its specific requirement
  // This field is used to determine if an evidence piece is RELEVANT to this checklist item
  // Wrong evidence type → NOT_APPLICABLE (no finding), Correct evidence type but missing → NOT_FOUND (finding)
  "evidence_strength_required": "PRIMARY | SUPPORTING | OBSERVATIONAL | ANALYTICAL",
  "evidence_logic": {{{{
    "minimum_required": 1,
    "acceptable_combinations": [[]]
  }}}},
  "contextual_inference": {{{{
    "permitted": "YES | NO",
    "basis": "",
    "prohibited_inferences": ""
  }}}},
  "oe_testing": {{{{
    "applicable": "YES | NO",
    "population_scope": "",
    "instance_identifier": "",
    "attribute_being_tested": "",
    "pass_criteria": "",
    "fail_criteria": "",
    "exception_logic": ""
  }}}},
  "logical_integrity_check": {{{{
    "required": "YES | NO",
    "validate": ["CHRONOLOGY | CROSS_DOC_CONSISTENCY | VERSION_ALIGNMENT | AUDIT_PERIOD_ALIGNMENT"],
    "contradiction_action": "INQUIRY"
  }}}},
  "confidence_classification": "EXPLICIT | IMPLIED | AMBIGUOUS",
  "inquiry_trigger": "YES | NO",
  "inquiry_conditions": ["CONTRADICTION_DETECTED | AMBIGUOUS_EVIDENCE | INSUFFICIENT_EVIDENCE | PERIOD_MISMATCH | APPROVAL_MISSING"],
  "admissibility_states": ["NOT_PROVIDED", "PROVIDED_INVALID", "PROVIDED_INSUFFICIENT", "CONTRADICTORY", "VALID"],
  "requirement_type": "PRIMARY | COMPENSATING | OPTIONAL",
  "allows_compensating_control": "YES | NO",
  "compensating_control_logic": "",
  "evaluation_logic": {{{{
    "check_for": "Exactly what to look for in evidence",
    "pass_condition": "Binary testable pass condition",
    "partial_condition": "Explicitly defined partial condition — NOT vague",
    "fail_condition": "Binary testable fail condition",
    "contradiction_action": "INQUIRY"

  // APPROVAL EVIDENCE RULES (CRITICAL — apply when requirement involves approval/authorization):
  // POLICY DOCUMENTS, FRAMEWORKS, SOPs, MANUALS, CIRCULARS, GUIDELINES:
  //   Document Control table with "Approved By" + approval date = SUFFICIENT evidence of approval.
  //   Do NOT require physical wet signatures. Do NOT set fail_condition as "lacks approval signatures".
  //   pass_condition: "Document shows approved authority and approval date"
  //   fail_condition: "No approval authority or approval date found anywhere in document"
  // CONTRACTS, AGREEMENTS, MoUs, LOAN DOCUMENTS, DEEDS, LEGAL INSTRUMENTS:
  //   Physical signature blocks MUST be present (detect presence only, not verify authenticity).
  //   pass_condition: "Signature blocks present with signatory names/designations"
  //   fail_condition: "Signature blocks absent or blank"
  //   partial_condition: "Some but not all required signatories present"
  }}}},
  "failure_impact": "CRITICAL | MAJOR | SIGNIFICANT | MINOR"
}}}}

---

RULES FOR ASSIGNMENT:

1. EFFECTIVENESS TYPE must align with Step 3 required_dimensions.
2. OE items: oe_testing.applicable = YES for sampling/population/transaction controls. All 6 sub-fields mandatory when YES.
3. LOGICAL_INTEGRITY items: logical_integrity_check.required = YES. contradiction_action always = INQUIRY.
4. inquiry_conditions must NOT be empty when inquiry_trigger = YES.
5. partial_condition must be explicitly defined — never vague.
6. checklist_family: assign exactly ONE per item.
7. confidence_classification: EXPLICIT where clause directly states requirement, IMPLIED where inferred, AMBIGUOUS where unclear.
8. admissibility_states: always include all 5 states as array — this is metadata for Step 5.
9. discovers_parameter / depends_on_parameter (Principle 16): leave BOTH null on most items. Only set when a genuine, real dependency exists between two specific items in THIS checklist, grounded in this activity's own text -- never invent a parameter from a generic list, and never set depends_on_parameter without a matching discovers_parameter present somewhere in this same output.

---

OUTPUT FORMAT (return ONLY this — no explanation, no markdown):

{{{{
  "required_dimensions": {{{{
    "design": "YES | NO",
    "implementation": "YES | NO",
    "operating": "YES | NO"
  }}}},
  "checklist": [...],
  "admissibility_requirements": {{{{
    "ownership_required": "YES | NO",
    "audit_period_required": "YES | NO",
    "approval_required": "YES | NO",
    "system_identification_required": "YES | NO"
  }}}},
  "sampling_rules": {{{{
    "applicable": "YES | NO",
    "method": "RANDOM | SYSTEMATIC | JUDGMENTAL",
    "minimum_sample_size": "",
    "period_constraint": "WITHIN_AUDIT_PERIOD"
  }}}},
  "dimension_rules": {{{{
    "minimum_evidence_required": {{{{
      "design": 1,
      "implementation": 1,
      "operating": 1
    }}}}
  }}}},
  "scoring_rules": {{{{
    "pass_threshold": 0.8,
    "partial_threshold": 0.6
  }}}}
}}}}

STRICT CONSTRAINTS:
* Do NOT include explanations or markdown
* Do NOT evaluate evidence
* Every OE item MUST have oe_testing defined
* Every LOGICAL_INTEGRITY item MUST have logical_integrity_check defined
* inquiry_conditions must not be empty when inquiry_trigger = YES
* partial_condition must not be empty or vague
* CRITICAL — ILLUSTRATIVE vs MANDATORY: When a regulatory clause contains phrases like "such as", "including", "for example", "e.g.", "inter alia" — treat those examples as ILLUSTRATIVE ONLY, not mandatory requirements. Generate checklist items that test whether the institution has documented ITS OWN products/processes — NOT whether specific named examples exist.
* CRITICAL — INSTITUTION-SPECIFIC SCOPE: Checklist items must NEVER mandate specific product names, service types, or process names that appear as examples in a clause. Test for COVERAGE and COMPLETENESS of the institution's actual scope — not for presence of illustrative examples.
* CRITICAL — REGULATORY INTENT: Always derive checklist items from the INTENT of the regulatory requirement. Ask "What is this regulation trying to achieve?" — not "What specific words appear in the clause?"
* Use consistent ENUM values only"""


import re


def _normalize_for_quote_match(text: str) -> str:
    """Collapse whitespace and lowercase, for a forgiving-but-still-genuine substring check --
    tolerates line-wrapping/spacing differences without allowing a paraphrase to pass."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _validate_parameter_tags(checklist_items: list, source_text: str) -> list:
    """
    Build Sequence #394 Step 4.4 -- deterministic, code-level safeguard for the
    discovers_parameter / depends_on_parameter tags an LLM call (Principle 16 in
    _build_checklist_prompt) may have added to individual checklist items.

    Two checks, both mechanical, never trusting the LLM's own tagging at face value:
    1. Every tag's parameter_justification_quote must be a genuine, verbatim (whitespace/case
       tolerant only) substring of the real activity + test procedure text. A tag whose quote
       cannot be found this way is dropped entirely -- this is what actually prevents the LLM
       from inventing a parameter that was never really discoverable in the source text.
    2. Every depends_on_parameter must name a parameter some item's discovers_parameter in this
       SAME checklist actually produces. An orphaned dependency (referencing a parameter nothing
       in this checklist discovers) is dropped -- the item reverts to a standalone item rather
       than carrying a dependency that can never be resolved.
    """
    normalized_source = _normalize_for_quote_match(source_text)

    # Pass 1: quote verification
    for item in checklist_items:
        if not isinstance(item, dict):
            continue
        has_tag = item.get("discovers_parameter") or item.get("depends_on_parameter")
        if not has_tag:
            continue
        quote = item.get("parameter_justification_quote")
        if not quote or _normalize_for_quote_match(quote) not in normalized_source:
            logger.warning(
                f"[Module B] Dropping parameter tag -- quote not found verbatim in source text. "
                f"discovers={item.get('discovers_parameter')!r}, depends_on={item.get('depends_on_parameter')!r}, "
                f"quote={quote!r}"
            )
            item["discovers_parameter"] = None
            item["depends_on_parameter"] = None
            item["parameter_justification_quote"] = None

    # Build Sequence #398: dependency resolution (matching depends_on_parameter against
    # discovers_parameter) is intentionally NOT done here anymore. A real bug found today:
    # this function runs per-activity, while a genuine dependency very often points to a
    # SIBLING activity's discovery under the same clause -- which doesn't exist yet at this
    # point in generation. Checking only this checklist's own items would silently, wrongly,
    # permanently drop every genuine cross-activity dependency. That resolution now happens
    # once, later, in resolve_cross_sibling_dependencies() below, after every sibling
    # activity's checklist for the clause actually exists.
    return checklist_items


def resolve_cross_sibling_dependencies(clause_id: int) -> dict:
    """
    Build Sequence #398. Runs once, after every sibling activity under a clause has its
    checklist generated -- the first point where a genuine cross-activity dependency can
    actually be checked. Mechanical, no LLM call: depends_on_parameter is already an
    explicit, plain-text name assigned by the tagging step: matching it against every
    sibling's discovers_parameter names is a string comparison, not a judgment call.

    Any depends_on_parameter that doesn't match a discovers_parameter anywhere across
    ALL sibling checklists for this clause is dropped -- same orphan-handling principle
    as the old, narrower, single-checklist check this replaces, just checked against the
    full, real set of siblings instead of an empty one.
    """
    from app.models.ai import ComplianceActivities, ControlActivity
    from app.models.eve_models import ControlChecklist

    sibling_activity_ids = [
        row.id for row in
        db.session.query(ComplianceActivities.id).filter_by(clause_id=clause_id).all()
    ]
    if not sibling_activity_ids:
        return {"clause_id": clause_id, "checklists_checked": 0, "dependencies_kept": 0, "dependencies_dropped": 0}

    controls = (
        db.session.query(ControlActivity)
        .filter(ControlActivity.compliance_activity_id.in_(sibling_activity_ids))
        .all()
    )
    control_ids = [c.id for c in controls]
    checklists = (
        db.session.query(ControlChecklist)
        .filter(ControlChecklist.control_activity_id.in_(control_ids))
        .all()
        if control_ids else []
    )

    all_discovered_names = set()
    for cl in checklists:
        for item in (cl.checklist_json or []):
            if isinstance(item, dict) and item.get("discovers_parameter"):
                all_discovered_names.add(item["discovers_parameter"])

    checklists_changed = 0
    dependencies_kept = 0
    dependencies_dropped = 0

    for cl in checklists:
        items = cl.checklist_json or []
        changed = False
        for item in items:
            if not isinstance(item, dict):
                continue
            dep = item.get("depends_on_parameter")
            if not dep:
                continue
            if dep in all_discovered_names:
                dependencies_kept += 1
            else:
                logger.warning(
                    f"[Module B] Dropping orphaned depends_on_parameter={dep!r} for "
                    f"control_activity_id={cl.control_activity_id} -- no matching "
                    f"discovers_parameter found across ANY sibling checklist for clause_id={clause_id}."
                )
                item["depends_on_parameter"] = None
                item["parameter_justification_quote"] = None
                dependencies_dropped += 1
                changed = True
        if changed:
            cl.checklist_json = items
            checklists_changed += 1

    if checklists_changed:
        db.session.commit()

    summary = {
        "clause_id": clause_id,
        "checklists_checked": len(checklists),
        "dependencies_kept": dependencies_kept,
        "dependencies_dropped": dependencies_dropped,
    }
    logger.info(f"[Module B] resolve_cross_sibling_dependencies: {summary}")
    return summary


# ---------------------------------------------------------------------------
# Build Sequence #TBD -- Part C, Step C6 (Clause-level checklist assurance review)
#
# Runs once every sibling activity's checklist under a clause exists AND
# resolve_cross_sibling_dependencies() (above) has already run against them --
# same wiring point in manual_task.py, called immediately after it.
#
# A single LLM call judges, across ALL sibling activities together (something
# no single activity's own checklist-generation call can ever see, since it
# only has its own checklist in view):
#   (a) sufficiency -- do these checklists, as a whole, let an auditor reach
#       an accurate conclusion for the clause
#   (c) genuine duplicate checklist items across DIFFERENT sibling activities
#       -- recorded as CANDIDATE pairs only. C8 (not yet built) persists
#       CONFIRMED links permanently, only after C6/C7 (regenerate-once-then-
#       flag orchestration, also not yet built) settle.
#
# Dependency resolution (b) is intentionally out of scope here -- that's
# resolve_cross_sibling_dependencies() above, mechanical, no LLM, already run
# before this.
# ---------------------------------------------------------------------------

def _build_clause_checklist_review_prompt(clause_text: str, activities_data: list) -> str:
    """Build Sequence #TBD -- C6 prompt. See module-level comment above for scope."""
    activities_block = []
    for a in activities_data:
        items_lines = []
        for item in (a["checklist_items"] or []):
            if not isinstance(item, dict):
                continue
            items_lines.append(
                f'  - {item.get("id", "?")} [{item.get("effectiveness_type", "?")}]: '
                f'{item.get("requirement", "")}'
            )
        activities_block.append(
            f'Activity (control_activity_id={a["control_activity_id"]}): {a["activity_description"]}\n'
            f'Dimensions: DESIGN={a["dimension_design"]}, IMPLEMENTATION={a["dimension_implementation"]}, OPERATING={a["dimension_operating"]}\n'
            f'Checklist items:\n' + "\n".join(items_lines)
        )
    activities_text = "\n\n".join(activities_block)

    return f"""You are a Clause-Level Checklist Assurance Reviewer for BFSI regulatory audits.

TASK: Review ALL sibling control activities generated under a single regulatory clause, together, as one unit -- not one at a time. You are given every sibling activity's full checklist for this clause.

Return ONLY valid JSON. No explanation. No markdown.

---

CLAUSE TEXT:
{clause_text}

---

SIBLING ACTIVITIES AND THEIR CHECKLISTS (all activities generated for this clause):

{activities_text}

---

TASK 1 -- SUFFICIENCY:
Judge whether these checklists, taken TOGETHER as a whole, let an auditor reach an accurate, complete conclusion about the organization's compliance with this clause. Consider:
* Does every distinct obligation in the clause text have at least one checklist item -- an actual line in a "Checklist items:" list above -- that DIRECTLY tests it?
* Are there any genuine gaps -- an obligation in the clause with no corresponding checklist item anywhere?

CRITICAL -- base this judgment ONLY on the actual checklist items listed under each activity. An activity's own name or description is NOT evidence that its obligation is covered -- an activity can be named or described in terms of an obligation (e.g. "Analyse, monitor, and report X") while its actual checklist items test something else entirely (e.g. only staff roles or training, with no item that tests analysis, monitoring, or reporting itself). If no checklist item anywhere actually tests an obligation, that obligation is a gap -- regardless of how directly relevant the activity's name or description sounds.

Do NOT flag insufficiency merely because of duplication (see Task 2) -- overlapping coverage of the same obligation is not a gap.

Set sufficiency_verdict to exactly "SUFFICIENT" or "INSUFFICIENT". If INSUFFICIENT, sufficiency_reasoning must name the specific obligation(s) in the clause text that have no checklist item testing them anywhere.

If INSUFFICIENT, ALSO populate missing_coverage: for each distinct untested obligation, output which ONE sibling activity (by its exact control_activity_id, as given above) should logically cover it, based on that activity's existing description and checklist focus. Only name a control_activity_id that is one of the sibling activities actually given above. If no single sibling activity is a clear fit for an obligation, omit that obligation from missing_coverage rather than guessing.

---

TASK 2 -- GENUINE DUPLICATION ACROSS SIBLING ACTIVITIES (strict symmetric test):
Find checklist items, in DIFFERENT sibling activities, that are genuine duplicates under this exact test:

  Item A and Item B are duplicates ONLY IF evidence that fully and accurately
  answers A would, BY ITSELF, also fully and accurately answer B -- AND,
  symmetrically, evidence that fully and accurately answers B would, by
  itself, also fully and accurately answer A. The test must hold in BOTH
  directions.

If evidence for A only partially answers B, or answers B but leaves out something B specifically requires (or vice versa), they are NOT duplicates -- B still needs its own independent investigation, even if related to A. Being in the same topic area, testing the same control, or sounding similar is NOT enough -- apply the exact evidence-sufficiency test above, in both directions, before calling a pair a duplicate.

For each genuine duplicate pair found, output BOTH items' control_activity_id and checklist item id exactly as given above, plus a short justification that explicitly confirms BOTH directions of the test hold.

Do NOT invent a duplicate pair across items within the SAME activity -- only across DIFFERENT sibling activities (control_activity_id must differ between the two sides of every pair).

---

OUTPUT FORMAT (exactly this JSON shape):
{{
  "sufficiency_verdict": "SUFFICIENT" | "INSUFFICIENT",
  "sufficiency_reasoning": "string -- required if INSUFFICIENT, empty string if SUFFICIENT",
  "missing_coverage": [
    {{
      "obligation": "string -- the specific untested obligation from the clause text",
      "control_activity_id": <int, exactly as given above -- the sibling activity that should cover it>
    }}
  ],
  "duplicate_pairs": [
    {{
      "control_activity_id_a": <int, exactly as given above>,
      "checklist_item_id_a": "<e.g. CHK_001>",
      "control_activity_id_b": <int, exactly as given above>,
      "checklist_item_id_b": "<e.g. CHK_003>",
      "justification": "string"
    }}
  ]
}}

If no genuine duplicates exist, duplicate_pairs must be an empty array []. If sufficiency_verdict is SUFFICIENT, missing_coverage must be an empty array []."""


class EveClauseChecklistReviewSchema(BaseModel):
    """Build Sequence #TBD -- Part C, Step C6 output schema."""
    sufficiency_verdict: str
    sufficiency_reasoning: str = ""
    missing_coverage: list = []
    duplicate_pairs: list = []

    @field_validator("sufficiency_verdict")
    @classmethod
    def _verdict_must_be_valid(cls, v):
        allowed = {"SUFFICIENT", "INSUFFICIENT"}
        if v not in allowed:
            raise ValueError(f"sufficiency_verdict must be one of {allowed}, got {v!r}")
        return v


def run_clause_checklist_assurance_review(clause_id: int, iteration: int = None) -> dict:
    """
    Build Sequence #TBD -- C6. See module-level comment above for scope.

    iteration: explicit attempt number within a C7 cycle (1 = first look,
    2 = re-check after patching). Pass explicitly from the C7 orchestrator
    so iteration reflects "attempt within this C7 run", not "how many times
    this clause has ever been reviewed for any reason". Left as None for a
    bare/manual call (e.g. from the UI) with no C7 cycle context -- falls
    back to self-incrementing off this clause's existing review history.
    """
    from app.models.ai import Clauses, ComplianceActivities

    clause = db.session.query(Clauses).filter_by(id=clause_id).first()
    if not clause:
        logger.error(f"[Module B] run_clause_checklist_assurance_review: clause_id={clause_id} not found")
        return {"clause_id": clause_id, "status": "ERROR", "reason": "clause not found"}

    sibling_activity_ids = [
        row.id for row in
        db.session.query(ComplianceActivities.id).filter_by(clause_id=clause_id).all()
    ]
    if not sibling_activity_ids:
        logger.info(f"[Module B] run_clause_checklist_assurance_review: no activities for clause_id={clause_id}, skipping")
        return {"clause_id": clause_id, "status": "SKIPPED", "reason": "no activities"}

    controls = (
        db.session.query(ControlActivity)
        .filter(ControlActivity.compliance_activity_id.in_(sibling_activity_ids))
        .all()
    )
    control_ids = [c.id for c in controls]
    if not control_ids:
        logger.info(f"[Module B] run_clause_checklist_assurance_review: no control activities for clause_id={clause_id}, skipping")
        return {"clause_id": clause_id, "status": "SKIPPED", "reason": "no control activities"}

    checklists = (
        db.session.query(ControlChecklist)
        .filter(ControlChecklist.control_activity_id.in_(control_ids))
        .all()
    )
    if not checklists:
        logger.info(f"[Module B] run_clause_checklist_assurance_review: no checklists yet for clause_id={clause_id}, skipping")
        return {"clause_id": clause_id, "status": "SKIPPED", "reason": "no checklists"}

    control_by_id = {c.id: c for c in controls}
    compliance_activity_by_id = {
        a.id: a for a in
        db.session.query(ComplianceActivities).filter(ComplianceActivities.id.in_(sibling_activity_ids)).all()
    }

    activities_data = []
    for cl in checklists:
        control = control_by_id.get(cl.control_activity_id)
        activity_description = ""
        if control is not None:
            compliance_activity = compliance_activity_by_id.get(control.compliance_activity_id)
            if compliance_activity is not None:
                activity_description = compliance_activity.activity_description or ""
        activities_data.append({
            "control_activity_id": cl.control_activity_id,
            "activity_description": activity_description,
            "dimension_design": cl.dimension_design,
            "dimension_implementation": cl.dimension_implementation,
            "dimension_operating": cl.dimension_operating,
            "checklist_items": cl.checklist_json or [],
        })

    prompt = _build_clause_checklist_review_prompt(clause.clause_text or "", activities_data)
    raw_output = _call_llm_json(prompt)

    if not raw_output:
        logger.error(f"[Module B] run_clause_checklist_assurance_review: LLM returned no output for clause_id={clause_id}")
        return {"clause_id": clause_id, "status": "ERROR", "reason": "LLM returned no output"}

    try:
        validated = EveClauseChecklistReviewSchema(**raw_output)
    except Exception as e:
        logger.error(f"[Module B] run_clause_checklist_assurance_review: schema validation failed for clause_id={clause_id}: {e}")
        return {"clause_id": clause_id, "status": "ERROR", "reason": f"schema validation failed: {e}"}

    real_items_by_control = {
        a["control_activity_id"]: {item.get("id") for item in a["checklist_items"] if isinstance(item, dict)}
        for a in activities_data
    }
    valid_control_activity_ids = set(real_items_by_control.keys())
    valid_missing_coverage = []
    missing_coverage_dropped = 0
    for entry in (validated.missing_coverage or []):
        if not isinstance(entry, dict):
            missing_coverage_dropped += 1
            continue
        ca_id = entry.get("control_activity_id")
        if ca_id not in valid_control_activity_ids:
            logger.warning(
                f"[Module B] Dropping missing_coverage entry -- control_activity_id={ca_id} "
                f"is not one of the real sibling activities sent."
            )
            missing_coverage_dropped += 1
            continue
        valid_missing_coverage.append(entry)

    valid_pairs = []
    dropped_count = 0
    for pair in (validated.duplicate_pairs or []):
        if not isinstance(pair, dict):
            dropped_count += 1
            continue
        ca_a = pair.get("control_activity_id_a")
        ca_b = pair.get("control_activity_id_b")
        item_a = pair.get("checklist_item_id_a")
        item_b = pair.get("checklist_item_id_b")
        if ca_a == ca_b:
            logger.warning(
                f"[Module B] Dropping duplicate pair -- same control_activity_id on both "
                f"sides ({ca_a}), not a genuine cross-activity duplicate."
            )
            dropped_count += 1
            continue
        if ca_a not in real_items_by_control or item_a not in real_items_by_control.get(ca_a, set()):
            logger.warning(f"[Module B] Dropping duplicate pair -- side A ({ca_a}, {item_a}) doesn't match any real checklist item sent.")
            dropped_count += 1
            continue
        if ca_b not in real_items_by_control or item_b not in real_items_by_control.get(ca_b, set()):
            logger.warning(f"[Module B] Dropping duplicate pair -- side B ({ca_b}, {item_b}) doesn't match any real checklist item sent.")
            dropped_count += 1
            continue
        valid_pairs.append(pair)

    if iteration is None:
        from sqlalchemy import func as sa_func
        prior_max_iteration = (
            db.session.query(sa_func.max(ClauseChecklistReview.iteration))
            .filter_by(clause_id=clause_id)
            .scalar()
        )
        next_iteration = (prior_max_iteration or 0) + 1
    else:
        next_iteration = iteration

    review = ClauseChecklistReview(
        clause_id=clause_id,
        iteration=next_iteration,
        sufficiency_verdict=validated.sufficiency_verdict,
        sufficiency_reasoning=validated.sufficiency_reasoning,
        duplicate_pairs_json=valid_pairs,
        raw_output_json=raw_output,
        reviewed_at=datetime.utcnow(),
    )
    db.session.add(review)
    db.session.commit()

    summary = {
        "clause_id": clause_id,
        "status": "REVIEWED",
        "sufficiency_verdict": validated.sufficiency_verdict,
        "duplicate_pairs_kept": len(valid_pairs),
        "duplicate_pairs_dropped": dropped_count,
        "missing_coverage": valid_missing_coverage,
        "missing_coverage_dropped": missing_coverage_dropped,
    }
    logger.info(f"[Module B] run_clause_checklist_assurance_review: {summary}")
    return summary


# ---------------------------------------------------------------------------
# Build Sequence #TBD -- Part C, Step C7 (regenerate-once-then-flag)
#
# Targeted patch, not full regeneration: appends checklist item(s) covering a
# specific untested obligation (identified by C6's missing_coverage) to ONE
# sibling activity's existing checklist. Does not touch other items, does not
# bump ControlChecklist.version (that column tracks full C3 regenerations,
# not additive patches), does not overwrite raw_output_json (which records
# how the ORIGINAL checklist was generated).
#
# New item(s) are run through the same _validate_parameter_tags mechanical
# safeguard as any item from a normal generation pass -- never trusted at
# face value just because they came from a smaller, targeted call.
# ---------------------------------------------------------------------------

def _build_missing_coverage_patch_prompt(clause_text: str, control_activity_text: str,
                                          test_procedure_text: str, obligation_text: str,
                                          existing_checklist_items: list) -> str:
    """Build Sequence #TBD -- C7 patch prompt. Appends item(s) for one obligation."""
    existing_lines = []
    for item in (existing_checklist_items or []):
        if not isinstance(item, dict):
            continue
        existing_lines.append(
            f'  - {item.get("id", "?")} [{item.get("effectiveness_type", "?")}]: '
            f'{item.get("requirement", "")}'
        )
    existing_text = "\n".join(existing_lines) if existing_lines else "  (none)"

    return f"""You are extending an existing BFSI audit checklist for ONE control activity.

TASK: This activity's checklist does not yet test a specific obligation from its clause. Add ONE OR MORE new checklist item(s) that test it, matching the style and granularity of the EXISTING items below. Do not repeat or modify any existing item.

Return ONLY valid JSON. No explanation. No markdown.

---

CLAUSE TEXT:
{clause_text}

CONTROL ACTIVITY:
{control_activity_text}

TEST PROCEDURE:
{test_procedure_text}

---

EXISTING CHECKLIST ITEMS (for this activity -- do not duplicate or alter these):
{existing_text}

---

UNTESTED OBLIGATION TO COVER:
{obligation_text}

---

OUTPUT FORMAT (exactly this JSON shape):
{{
  "new_checklist_items": [
    {{
      "id": "<new unique id, e.g. CHK_00X, continuing the existing numbering>",
      "requirement": "string",
      "control_pattern": "string",
      "lifecycle_stage": "string",
      "effectiveness_type": "DESIGN" | "IMPLEMENTATION" | "OPERATING",
      "weight": <number>,
      "testing_method": "string",
      "testing_approach": "string",
      "expected_evidence_types": ["string"],
      "evidence_logic": "string",
      "requirement_type": "string",
      "allows_compensating_control": <bool>,
      "compensating_control_logic": "string",
      "evaluation_logic": {{"check_for": "string", "pass_condition": "string", "fail_condition": "string"}},
      "failure_impact": "string"
    }}
  ]
}}"""


def patch_checklist_for_missing_coverage(control_activity_id: int, obligation_text: str,
                                          clause_text: str) -> dict:
    """
    Build Sequence #TBD -- C7. Appends new checklist item(s) to ONE activity's
    existing ControlChecklist row, covering a specific untested obligation
    identified by C6's missing_coverage. Targeted patch, not full regeneration
    -- see module comment above.
    """
    control = db.session.query(ControlActivity).get(control_activity_id)
    if not control:
        logger.error(f"[Module B] patch_checklist_for_missing_coverage: control_activity_id={control_activity_id} not found")
        return {"control_activity_id": control_activity_id, "status": "ERROR", "reason": "control activity not found"}

    checklist_record = (
        db.session.query(ControlChecklist)
        .filter_by(control_activity_id=control_activity_id)
        .first()
    )
    if not checklist_record:
        logger.error(f"[Module B] patch_checklist_for_missing_coverage: no ControlChecklist for control_activity_id={control_activity_id}")
        return {"control_activity_id": control_activity_id, "status": "ERROR", "reason": "no existing checklist to patch"}

    control_activity_text = (
        f"{control.activity_name or ''}\n{control.activity_description or ''}"
    ).strip()

    test_procedure_text = ""
    if control.test_procedure:
        tp = control.test_procedure
        walkthrough = getattr(tp, "walkthrough", "") or ""
        sampling = getattr(tp, "sampling", "") or ""
        test_procedure_text = f"Walkthrough: {walkthrough}\nSampling: {sampling}".strip()

    existing_items = checklist_record.checklist_json or []

    prompt = _build_missing_coverage_patch_prompt(
        clause_text, control_activity_text, test_procedure_text, obligation_text, existing_items
    )
    raw_output = _call_llm_json(prompt)

    if not raw_output or not isinstance(raw_output, dict) or not raw_output.get("new_checklist_items"):
        logger.error(f"[Module B] patch_checklist_for_missing_coverage: LLM returned no usable output for control_activity_id={control_activity_id}")
        return {"control_activity_id": control_activity_id, "status": "ERROR", "reason": "LLM returned no usable output"}

    new_items = raw_output["new_checklist_items"]
    if not isinstance(new_items, list):
        logger.error(f"[Module B] patch_checklist_for_missing_coverage: new_checklist_items is not a list for control_activity_id={control_activity_id}")
        return {"control_activity_id": control_activity_id, "status": "ERROR", "reason": "new_checklist_items malformed"}

    existing_ids = {item.get("id") for item in existing_items if isinstance(item, dict)}
    deduped_new_items = []
    for item in new_items:
        if not isinstance(item, dict):
            continue
        if item.get("id") in existing_ids:
            logger.warning(
                f"[Module B] patch_checklist_for_missing_coverage: dropping new item with "
                f"id={item.get('id')!r} -- collides with an existing item id."
            )
            continue
        deduped_new_items.append(item)

    if not deduped_new_items:
        logger.warning(f"[Module B] patch_checklist_for_missing_coverage: no usable new items after dedup for control_activity_id={control_activity_id}")
        return {"control_activity_id": control_activity_id, "status": "ERROR", "reason": "no usable new items after id dedup"}

    source_text_for_quotes = f"{clause_text}\n{control_activity_text}\n{test_procedure_text}"
    deduped_new_items = _validate_parameter_tags(deduped_new_items, source_text_for_quotes)

    checklist_record.checklist_json = existing_items + deduped_new_items
    db.session.commit()

    summary = {
        "control_activity_id": control_activity_id,
        "status": "PATCHED",
        "items_added": len(deduped_new_items),
    }
    logger.info(f"[Module B] patch_checklist_for_missing_coverage: {summary}")
    return summary


# ---------------------------------------------------------------------------
# Build Sequence #TBD -- Part C, Step C7 orchestrator (regenerate-once-then-flag)
#
# Runs C6. If INSUFFICIENT, patches ONLY the specific missing_coverage gaps
# (via patch_checklist_for_missing_coverage above), re-resolves cross-sibling
# dependencies (mandatory -- a patched item may carry a new discovers_parameter
# or depends_on_parameter tag that resolve_cross_sibling_dependencies has not
# yet checked against the full sibling set), then re-runs C6 fresh as the next
# iteration. Whatever that second review says is final -- no third attempt.
# The existing SUFFICIENT/INSUFFICIENT badge in the UI covers both outcomes;
# no separate "flagged" status is introduced.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Build Sequence #TBD -- Part C, Step C8 (confirmed duplicate pair promotion)
#
# Turns C6's per-review CANDIDATE duplicate_pairs (ClauseChecklistReview.
# duplicate_pairs_json) into permanent ConfirmedDuplicatePair rows, per the
# automatic confirmation rule:
#   - a pair present in BOTH iteration=1 and iteration=2 (after a C7 patch-
#     and-recheck cycle) is confirmed -- it survived an independent re-review.
#   - a pair found on a straight-SUFFICIENT iteration=1 (no C7 cycle occurs,
#     so there's no second review to confirm against) is confirmed immediately.
#
# Every pair is normalized so control_activity_id_a < control_activity_id_b
# before insert, regardless of which side C6's output happened to list first
# -- this is what lets the unique constraint actually catch the same real
# pair being promoted twice across separate pipeline runs over the clause's
# lifetime, instead of silently duplicating it.
# ---------------------------------------------------------------------------

def _normalize_pair(pair: dict) -> tuple:
    """Returns (control_activity_id_a, checklist_item_id_a, control_activity_id_b,
    checklist_item_id_b) with side A always the smaller control_activity_id."""
    ca_a, item_a = pair["control_activity_id_a"], pair["checklist_item_id_a"]
    ca_b, item_b = pair["control_activity_id_b"], pair["checklist_item_id_b"]
    if ca_a <= ca_b:
        return (ca_a, item_a, ca_b, item_b)
    return (ca_b, item_b, ca_a, item_a)


def promote_confirmed_duplicate_pairs(clause_id: int, first_review: dict,
                                       second_review: dict = None) -> dict:
    """
    Build Sequence #TBD -- C8. See module comment above for scope.

    first_review: the C6 result dict from run_clause_checklist_assurance_review,
    used only to check status/verdict -- the actual pairs are read fresh from
    the corresponding ClauseChecklistReview row(s) by iteration, not trusted
    from the summary dict.

    second_review: the re-review result dict after a C7 patch cycle, if one
    occurred. None means no C7 cycle ran (first_review was already SUFFICIENT).
    """
    from app.models.eve_models import ClauseChecklistReview, ConfirmedDuplicatePair

    if second_review is None:
        # No C7 cycle -- first_review's pairs are confirmed immediately.
        row = (
            db.session.query(ClauseChecklistReview)
            .filter_by(clause_id=clause_id, iteration=1)
            .order_by(ClauseChecklistReview.reviewed_at.desc())
            .first()
        )
        if not row:
            return {"clause_id": clause_id, "status": "SKIPPED", "reason": "no iteration=1 row found"}
        candidate_pairs = row.duplicate_pairs_json or []
        source_review_id = row.id
    else:
        # C7 cycle ran -- only pairs present in BOTH reviews are confirmed.
        first_row = (
            db.session.query(ClauseChecklistReview)
            .filter_by(clause_id=clause_id, iteration=1)
            .order_by(ClauseChecklistReview.reviewed_at.desc())
            .first()
        )
        second_row = (
            db.session.query(ClauseChecklistReview)
            .filter_by(clause_id=clause_id, iteration=2)
            .order_by(ClauseChecklistReview.reviewed_at.desc())
            .first()
        )
        if not first_row or not second_row:
            return {"clause_id": clause_id, "status": "SKIPPED", "reason": "missing iteration row(s) for comparison"}

        first_normalized = {_normalize_pair(p) for p in (first_row.duplicate_pairs_json or [])}
        second_pairs = second_row.duplicate_pairs_json or []
        candidate_pairs = [p for p in second_pairs if _normalize_pair(p) in first_normalized]
        source_review_id = second_row.id

    promoted = []
    skipped_existing = 0

    for pair in candidate_pairs:
        ca_a, item_a, ca_b, item_b = _normalize_pair(pair)
        existing = (
            db.session.query(ConfirmedDuplicatePair)
            .filter_by(
                clause_id=clause_id,
                control_activity_id_a=ca_a,
                checklist_item_id_a=item_a,
                control_activity_id_b=ca_b,
                checklist_item_id_b=item_b,
            )
            .first()
        )
        if existing:
            skipped_existing += 1
            continue

        confirmed = ConfirmedDuplicatePair(
            clause_id=clause_id,
            control_activity_id_a=ca_a,
            checklist_item_id_a=item_a,
            control_activity_id_b=ca_b,
            checklist_item_id_b=item_b,
            justification=pair.get("justification", ""),
            source_review_id=source_review_id,
            confirmed_at=datetime.utcnow(),
        )
        db.session.add(confirmed)
        promoted.append((ca_a, item_a, ca_b, item_b))

    if promoted:
        db.session.commit()

    summary = {
        "clause_id": clause_id,
        "status": "PROMOTED",
        "pairs_promoted": len(promoted),
        "pairs_already_confirmed": skipped_existing,
    }
    logger.info(f"[Module B] promote_confirmed_duplicate_pairs: {summary}")
    return summary


def run_clause_checklist_assurance_with_regeneration(clause_id: int) -> dict:
    """Build Sequence #TBD -- C7. See module comment above for scope."""
    first_review = run_clause_checklist_assurance_review(clause_id, iteration=1)

    if first_review.get("status") != "REVIEWED":
        # ERROR or SKIPPED from C6 itself -- nothing for C7 to do.
        return first_review

    if first_review.get("sufficiency_verdict") != "INSUFFICIENT":
        # SUFFICIENT on iteration=1 -- no regeneration needed. C8: promote
        # this review's duplicate pairs immediately, since there's no
        # second review coming to confirm against.
        promote_confirmed_duplicate_pairs(clause_id, first_review)
        return first_review

    missing_coverage = first_review.get("missing_coverage") or []
    if not missing_coverage:
        # INSUFFICIENT but nothing usable to patch (all entries dropped by the
        # mechanical safeguard) -- nothing C7 can do, first review stands as final.
        logger.warning(
            f"[Module B] run_clause_checklist_assurance_with_regeneration: clause_id={clause_id} "
            f"is INSUFFICIENT but has no usable missing_coverage entries -- cannot patch, flagging as-is."
        )
        return first_review

    clause_text = ""
    from app.models.ai import Clauses
    clause = db.session.query(Clauses).filter_by(id=clause_id).first()
    if clause:
        clause_text = clause.clause_text or ""

    patch_results = []
    for entry in missing_coverage:
        ca_id = entry.get("control_activity_id")
        obligation = entry.get("obligation", "")
        if not ca_id or not obligation:
            continue
        patch_result = patch_checklist_for_missing_coverage(ca_id, obligation, clause_text)
        patch_results.append(patch_result)

    patched_count = sum(1 for p in patch_results if p.get("status") == "PATCHED")
    if patched_count == 0:
        logger.warning(
            f"[Module B] run_clause_checklist_assurance_with_regeneration: clause_id={clause_id} "
            f"-- all patch attempts failed, flagging first review as final."
        )
        first_review["c7_patch_results"] = patch_results
        first_review["c7_status"] = "PATCH_FAILED"
        return first_review

    # Mandatory: re-resolve cross-sibling dependencies. A patched item may carry
    # a new discovers_parameter/depends_on_parameter tag that hasn't been checked
    # against the full sibling set yet.
    resolve_cross_sibling_dependencies(clause_id)

    second_review = run_clause_checklist_assurance_review(clause_id, iteration=2)

    # C8: promote duplicate pairs that survived from iteration=1 into
    # iteration=2 unchanged -- see promote_confirmed_duplicate_pairs.
    promote_confirmed_duplicate_pairs(clause_id, first_review, second_review)

    # Build Sequence #TBD -- 4.8: if the second, independent review is STILL
    # INSUFFICIENT after C7's targeted patch, stop retrying and flag the
    # clause for human review -- same flagging mechanism already used for
    # ambiguous clause classifications (Clauses.extraction_status /
    # Clauses.flag_reason), so it surfaces on the existing Clause Review
    # screen's FLAGGED filter and badge with no UI changes needed.
    if second_review.get("sufficiency_verdict") == "INSUFFICIENT":
        from app.models.ai import Clauses
        clause_row = db.session.query(Clauses).filter_by(id=clause_id).first()
        if clause_row:
            clause_row.extraction_status = "FLAGGED"
            clause_row.flag_reason = "CHECKLIST_ASSURANCE_FAILED"
            db.session.commit()
            logger.warning(
                f"[Module B] clause_id={clause_id} flagged CHECKLIST_ASSURANCE_FAILED -- "
                f"still INSUFFICIENT after C7 patch-and-recheck cycle."
            )

    second_review["c7_patch_results"] = patch_results
    second_review["c7_status"] = "REGENERATED_AND_REVIEWED"
    logger.info(
        f"[Module B] run_clause_checklist_assurance_with_regeneration: clause_id={clause_id} "
        f"final verdict after C7 = {second_review.get('sufficiency_verdict')}"
    )
    return second_review


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_control_checklist(self, control_activity_id: int, generated_by: int = None):
    """
    Module B — EVE Steps 3+4: Generate atomic checklist for a control activity.
    Stores result in control_checklist table.

    Args:
        control_activity_id:  ID from control_activities table
        generated_by:         User ID who triggered this task (optional)

    Returns:
        dict with status and checklist summary
    """
    logger.info(f"[Module B] Starting checklist generation for control_activity_id={control_activity_id}")

    try:
        # ── 1. Load control activity ───────────────────────────────────
        control = db.session.query(ControlActivity).get(control_activity_id)
        if not control:
            logger.error(f"ControlActivity {control_activity_id} not found")
            return {
                "status": "error",
                "message": f"ControlActivity {control_activity_id} not found",
                "control_activity_id": control_activity_id,
            }

        # ── 2. Check if checklist already exists ──────────────────────
        existing = (
            db.session.query(ControlChecklist)
            .filter_by(control_activity_id=control_activity_id)
            .first()
        )
        if existing:
            logger.info(
                f"Checklist already exists for control_activity_id={control_activity_id} "
                f"(version={existing.version}) — skipping"
            )
            return {
                "status": "already_exists",
                "message": "Checklist already generated",
                "control_activity_id": control_activity_id,
                "checklist_id": existing.id,
                "version": existing.version,
                "checklist_items_count": len(existing.checklist_json or []),
            }

        # ── 3. Get context from guideline_eve_context ──────────────────
        # We need regulation_type, domain, auditor_profile
        # These come from the guideline that this control's compliance_activity belongs to
        from app.models.ai import ComplianceActivities, Clauses
        from app.models.eve_models import GuidelineEveContext

        compliance_activity = control.compliance_activity
        if not compliance_activity:
            logger.error(f"No compliance_activity linked to control_activity_id={control_activity_id}")
            return {
                "status": "error",
                "message": "No compliance activity linked to this control",
                "control_activity_id": control_activity_id,
            }

        clause = None
        guideline_id = None
        if hasattr(compliance_activity, 'clause_id') and compliance_activity.clause_id:
            from app.models.ai import Clauses
            clause = db.session.query(Clauses).get(compliance_activity.clause_id)
        elif hasattr(compliance_activity, 'clause') and compliance_activity.clause:
            clause = compliance_activity.clause
        if clause:
            guideline_id = clause.guideline_id

        eve_context = None
        if guideline_id:
            eve_context = (
                db.session.query(GuidelineEveContext)
                .filter_by(guideline_id=guideline_id)
                .first()
            )

        # Use context if available, else use fallback defaults
        if eve_context:
            regulation_type = eve_context.regulation_type
            domain = eve_context.domain
            auditor_profile = eve_context.auditor_profile
            logger.info(f"[Module B] Using context: {regulation_type}/{domain}/{auditor_profile}")
        else:
            regulation_type = "OTHER"
            domain = "IT_GOVERNANCE"
            auditor_profile = "ITGC_AUDITOR"
            logger.warning(
                f"[Module B] No EVE context found for guideline_id={guideline_id} "
                f"— using fallback defaults. Run Module A first for better results."
            )

        # ── 4. Prepare inputs ──────────────────────────────────────────
        clause_text = ""
        if clause:
            clause_text = getattr(clause, "clause_text", "") or ""

        control_activity_text = (
            f"{control.activity_name or ''}\n{control.activity_description or ''}"
        ).strip()
        control_type = getattr(control, "control_type", "") or "Unknown"
        frequency = getattr(control, "frequency", "") or "Unknown"

        # Get test procedure text from linked TestSteps
        test_procedure_text = ""
        if control.test_procedure:
            tp = control.test_procedure
            walkthrough = getattr(tp, "walkthrough", "") or ""
            sampling = getattr(tp, "sampling", "") or ""
            test_procedure_text = f"Walkthrough: {walkthrough}\nSampling: {sampling}".strip()

        # Get evidence list from linked EvidenceArtifacts
        evidence_list_text = ""
        if control.evidences:
            evidence_items = []
            for i, e in enumerate(control.evidences, 1):
                item_text = f"{i}. [{e.category or 'General'}] {e.item or ''}"
                if hasattr(e, 'description') and e.description:
                    item_text += f"\n   Description: {e.description}"
                evidence_items.append(item_text)
            evidence_list_text = "\n".join(evidence_items)

        logger.info(
            f"[Module B] Inputs ready — clause: {len(clause_text)} chars, "
            f"control: {len(control_activity_text)} chars, "
            f"test_procedure: {len(test_procedure_text)} chars"
        )

        # ── 5. Build prompt and call LLM ──────────────────────────────
        prompt = _build_checklist_prompt(
            regulation_type=regulation_type,
            domain=domain,
            auditor_profile=auditor_profile,
            clause_text=clause_text or "Not available",
            control_activity=control_activity_text or "Not available",
            test_procedure=test_procedure_text or "Not available",
            evidence_list=evidence_list_text or "Not available",
            control_type=control_type,
            frequency=frequency,
        )

        raw_output = _call_llm_json(prompt)

        if not raw_output:
            raise self.retry(
                exc=Exception("LLM returned no output for checklist generation"),
                countdown=60,
            )

        # ── 6. Validate output ─────────────────────────────────────────
        try:
            validated = EveChecklistSchema(**raw_output)
        except Exception as e:
            logger.error(f"[Module B] Schema validation failed: {e}")
            raise self.retry(
                exc=Exception(f"Schema validation failed: {e}"),
                countdown=60,
            )

        # ── 7. Read dimensions (Build Sequence #397) ───────────────────
        # This used to be independently re-decided here (LLM guess + hardcoded
        # control_type/frequency override rules) -- a second, disagreeing decision
        # from the one already made at test-procedure-generation time, which is
        # provably more informed (same call that decides control_type/frequency
        # itself) and matches the corrected principle that no control type can
        # shortcut past Design/Implementation. That decision is now the single,
        # authoritative source -- read directly from the control record rather
        # than re-derived. The LLM's own required_dimensions guess in this
        # checklist-generation response is intentionally ignored.
        dimension_design = bool(control.dimension_design)
        dimension_implementation = bool(control.dimension_implementation)
        dimension_operating = bool(control.dimension_operating)
        logger.info(
            f"[Module B] Dimensions read from control_activity_id={control_activity_id}: "
            f"design={dimension_design}, implementation={dimension_implementation}, operating={dimension_operating}"
        )

        # Filter checklist items to match the decided dimensions
        if not dimension_design or not dimension_implementation or not dimension_operating:
            allowed_dims = []
            if dimension_design: allowed_dims.append("DESIGN")
            if dimension_implementation: allowed_dims.append("IMPLEMENTATION")
            if dimension_operating: allowed_dims.append("OPERATING")
            if allowed_dims and validated.checklist:
                filtered = [
                    item for item in validated.checklist
                    if item.get("effectiveness_type", "DESIGN") in allowed_dims
                ]
                if filtered:
                    validated.checklist = filtered
                    logger.info(f"[Module B] Filtered checklist to {len(filtered)} items for dims: {allowed_dims}")

        # ── 7.5. Verify parameter tags (Build Sequence #394 Step 4.4) ─────
        # Must run on the FINAL, dimension-filtered checklist -- a dependency
        # pointing to a discovery item that got filtered out above should also drop.
        # Build Sequence #394 bugfix: clause_text is a genuine, valid input source in
        # the actual prompt above ("Clause: {clause_text}") -- confirmed via a real test
        # run where every single tag was wrongly dropped because the source text checked
        # here omitted it entirely, even though the cited quotes were real text sitting
        # directly in the clause itself, not hallucinated.
        source_text_for_quotes = f"{clause_text}\n{control_activity_text}\n{test_procedure_text}"
        if validated.checklist:
            validated.checklist = _validate_parameter_tags(validated.checklist, source_text_for_quotes)

        # ── 8. Store in DB ────────────────────────────────────────────
        checklist_record = ControlChecklist(
            control_activity_id=control_activity_id,
            dimension_design=dimension_design,
            dimension_implementation=dimension_implementation,
            dimension_operating=dimension_operating,
            checklist_json=validated.checklist,
            admissibility_rules_json=validated.admissibility_requirements,
            sampling_rules_json=validated.sampling_rules,
            scoring_rules_json=validated.scoring_rules,
            version=1,
            raw_output_json=raw_output,
            generated_at=datetime.utcnow(),
            generated_by=generated_by,
        )
        db.session.add(checklist_record)
        db.session.commit()

        checklist_items_count = len(validated.checklist)
        # Auto-copy to all ProjectChecklists that reference this control
        try:
            from app.models.project_instance_models import ProjectControlActivity
            pcas = db.session.query(ProjectControlActivity).filter_by(
                original_control_id=control_activity_id
            ).all()
            for pca in pcas:
                existing_pc = db.session.query(ProjectChecklist).filter_by(
                    project_control_activity_id=pca.id
                ).first()
                if existing_pc:
                    # Update placeholder with real checklist data
                    existing_pc.source_checklist_id = checklist_record.id
                    existing_pc.checklist_json = checklist_record.checklist_json
                    existing_pc.dimension_design = checklist_record.dimension_design
                    existing_pc.dimension_implementation = checklist_record.dimension_implementation
                    existing_pc.dimension_operating = checklist_record.dimension_operating
                    existing_pc.admissibility_rules_json = checklist_record.admissibility_rules_json
                    existing_pc.sampling_rules_json = checklist_record.sampling_rules_json
                    existing_pc.scoring_rules_json = checklist_record.scoring_rules_json
                    existing_pc.status = "completed"
                else:
                    new_pc = ProjectChecklist(
                        project_control_activity_id=pca.id,
                        source_checklist_id=checklist_record.id,
                        checklist_json=checklist_record.checklist_json,
                        dimension_design=checklist_record.dimension_design,
                        dimension_implementation=checklist_record.dimension_implementation,
                        dimension_operating=checklist_record.dimension_operating,
                        admissibility_rules_json=checklist_record.admissibility_rules_json,
                        sampling_rules_json=checklist_record.sampling_rules_json,
                        scoring_rules_json=checklist_record.scoring_rules_json,
                        status="completed"
                    )
                    db.session.add(new_pc)
            db.session.commit()
            logger.info(f"[Module B] ProjectChecklists copied for {len(pcas)} project activities")
        except Exception as copy_err:
            logger.warning(f"[Module B] Could not copy to ProjectChecklists: {copy_err}")
        logger.info(
            f"[Module B] Checklist saved for control_activity_id={control_activity_id}: "
            f"{checklist_items_count} items, "
            f"dimensions: design={dimension_design}, "
            f"implementation={dimension_implementation}, "
            f"operating={dimension_operating}"
        )

        return {
            "status": "success",
            "control_activity_id": control_activity_id,
            "checklist_id": checklist_record.id,
            "checklist_items_count": checklist_items_count,
            "dimension_design": dimension_design,
            "dimension_implementation": dimension_implementation,
            "dimension_operating": dimension_operating,
        }

    except self.MaxRetriesExceededError:
        logger.error(f"[Module B] Max retries exceeded for control_activity_id={control_activity_id}")
        return {
            "status": "error",
            "message": "Max retries exceeded",
            "control_activity_id": control_activity_id,
        }
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module B] DB error for control_activity_id={control_activity_id}: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module B] Unexpected error for control_activity_id={control_activity_id}: {e}")
        return {
            "status": "error",
            "message": str(e),
            "control_activity_id": control_activity_id,
        }


# ============================================================
# UTILITY TASK — copy_checklist_to_project
#
# Called when a new project is created.
# Copies the master ControlChecklist into ProjectChecklist
# so the auditor has a frozen copy to work against.
# ============================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def copy_checklist_to_project(self, project_control_activity_id: int):
    """
    Copy the master ControlChecklist into ProjectChecklist for a specific
    project_control_activity. Called at project creation time.

    Args:
        project_control_activity_id: ID from project_control_activities table

    Returns:
        dict with status and project_checklist_id
    """
    logger.info(
        f"[Copy Checklist] Copying checklist for "
        f"project_control_activity_id={project_control_activity_id}"
    )

    try:
        # ── 1. Load project control activity ──────────────────────────
        pca = db.session.query(ProjectControlActivity).get(project_control_activity_id)
        if not pca:
            return {
                "status": "error",
                "message": f"ProjectControlActivity {project_control_activity_id} not found",
            }

        # ── 2. Check if project checklist already exists ───────────────
        existing = (
            db.session.query(ProjectChecklist)
            .filter_by(project_control_activity_id=project_control_activity_id)
            .first()
        )
        if existing:
            logger.info(
                f"ProjectChecklist already exists for pca_id={project_control_activity_id}"
            )
            return {
                "status": "already_exists",
                "project_checklist_id": existing.id,
            }

        # ── 3. Find master checklist via original_control_id ──────────
        master = (
            db.session.query(ControlChecklist)
            .filter_by(control_activity_id=pca.original_control_id)
            .first()
        )

        if not master:
            logger.warning(
                f"No master checklist found for original_control_id={pca.original_control_id}. "
                f"Project checklist will be created with empty checklist — "
                f"run Module B first to generate the master checklist."
            )
            # Create empty placeholder so auditor can still proceed
            project_checklist = ProjectChecklist(
                project_control_activity_id=project_control_activity_id,
                source_checklist_id=None,
                dimension_design=False,
                dimension_implementation=False,
                dimension_operating=False,
                checklist_json=[],
                admissibility_rules_json=None,
                sampling_rules_json=None,
                scoring_rules_json=None,
                source_version=None,
                status="pending",
                created_at=datetime.utcnow(),
            )
        else:
            # ── 4. Copy master into project checklist ──────────────────
            project_checklist = ProjectChecklist(
                project_control_activity_id=project_control_activity_id,
                source_checklist_id=master.id,
                dimension_design=master.dimension_design,
                dimension_implementation=master.dimension_implementation,
                dimension_operating=master.dimension_operating,
                checklist_json=master.checklist_json,          # deep copy via JSON
                admissibility_rules_json=master.admissibility_rules_json,
                sampling_rules_json=master.sampling_rules_json,
                scoring_rules_json=master.scoring_rules_json,
                source_version=master.version,
                status="pending",
                created_at=datetime.utcnow(),
            )

        db.session.add(project_checklist)
        db.session.commit()

        logger.info(
            f"[Copy Checklist] ProjectChecklist created: id={project_checklist.id}, "
            f"pca_id={project_control_activity_id}, "
            f"items={len(project_checklist.checklist_json or [])}"
        )

        return {
            "status": "success",
            "project_checklist_id": project_checklist.id,
            "project_control_activity_id": project_control_activity_id,
            "checklist_items_count": len(project_checklist.checklist_json or []),
            "source_checklist_id": master.id if master else None,
        }

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Copy Checklist] DB error: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Copy Checklist] Unexpected error: {e}")
        return {"status": "error", "message": str(e)}


@shared_task(bind=True)
def fix_pending_checklists(self):
    """Periodic task: fix any pending ProjectChecklists that were not auto-updated."""
    from app.models.eve_models import ControlChecklist, ProjectChecklist
    from app.models.project_instance_models import ProjectControlActivity
    try:
        pending = ProjectChecklist.query.filter_by(status='pending').all()
        fixed = 0
        triggered = 0
        for pc in pending:
            if not pc.checklist_json:
                pca = ProjectControlActivity.query.get(pc.project_control_activity_id)
                if pca:
                    cc = ControlChecklist.query.filter_by(control_activity_id=pca.original_control_id).first()
                    if cc and cc.checklist_json:
                        pc.checklist_json = cc.checklist_json
                        pc.dimension_design = cc.dimension_design
                        pc.dimension_implementation = cc.dimension_implementation
                        pc.dimension_operating = cc.dimension_operating
                        pc.source_checklist_id = cc.id
                        pc.status = 'completed'
                        fixed += 1
                    else:
                        generate_control_checklist.apply_async(
                            args=[pca.original_control_id],
                            queue='eve_checklist'
                        )
                        triggered += 1
        db.session.commit()
        # Also fix incomplete EveControlResults (step7_completed=False but findings exist)
        from app.models.eve_models import EveControlResult, EveEvidenceResult
        incomplete = EveControlResult.query.filter_by(step7_completed=False).all()
        step7_triggered = 0
        for cr in incomplete:
            # Check if ALL evidence has been evaluated
            from app.models.project_instance_models import ProjectEvidenceArtifact
            total_evidence = ProjectEvidenceArtifact.query.filter_by(
                project_control_activity_id=cr.project_control_activity_id
            ).count()
            evaluated_evidence = db.session.query(EveEvidenceResult.evidence_artifact_id).filter_by(
                project_checklist_id=cr.project_checklist_id
            ).distinct().count()
            if total_evidence > 0 and evaluated_evidence > 0 and evaluated_evidence >= total_evidence:
                from app.services.eve_step678 import run_eve_step6_and_7
                run_eve_step6_and_7.apply_async(
                    args=[cr.project_control_activity_id, None],
                    queue="eve_evaluate"
                )
                step7_triggered += 1
        # Also trigger Step 6+7 for activities where all evidence evaluated but EveControlResult doesn't exist yet
        from app.models.eve_models import ProjectChecklist as PC4
        from app.models.project_instance_models import ProjectEvidenceArtifact as PEA2
        all_checklists = PC4.query.filter(PC4.status.in_(['completed', 'in_progress'])).all()
        for pc in all_checklists:
            existing_cr = EveControlResult.query.filter_by(
                project_control_activity_id=pc.project_control_activity_id
            ).first()
            if existing_cr:
                continue
            total_evidence = PEA2.query.filter_by(
                project_control_activity_id=pc.project_control_activity_id
            ).count()
            if total_evidence == 0:
                continue
            evaluated_evidence = db.session.query(EveEvidenceResult.evidence_artifact_id).filter_by(
                project_checklist_id=pc.id
            ).distinct().count()
            if evaluated_evidence >= total_evidence:
                from app.services.eve_step678 import run_eve_step6_and_7
                run_eve_step6_and_7.apply_async(
                    args=[pc.project_control_activity_id, None],
                    queue="eve_evaluate"
                )
                step7_triggered += 1
        logger.info(f"[Periodic] fix_pending_checklists: fixed={fixed}, triggered={triggered}, step7_triggered={step7_triggered}")
        return {"fixed": fixed, "triggered": triggered, "step7_triggered": step7_triggered}
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Periodic] fix_pending_checklists error: {e}")
        return {"error": str(e)}
