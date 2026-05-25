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

def _call_llm_json(prompt: str, retries: int = 3, backoff: float = 2.0) -> dict | None:
    """
    Call OpenAI with temperature=0 and expect a JSON response.
    Returns parsed dict or None on failure.
    """
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,        # deterministic — same input = same output
                top_p=0.1,
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
* Clause: {clause_text}
* Control Activity: {control_activity}
* Test Procedure: {test_procedure}
* Evidence List: {evidence_list}

---

STEP 3 — DETERMINE REQUIRED EFFECTIVENESS DIMENSIONS (INTENT-DRIVEN)

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

STEP 4.3 — GENERATE ATOMIC CHECKLIST

For each checklist item output EXACTLY this JSON structure:

{{{{
  "id": "CHK_###",
  "requirement": "Single atomic testable assertion only",
  "checklist_family": "GOVERNANCE | PROCESS | RISK | MONITORING | COMPLIANCE | TRAINING | LOGICAL_INTEGRITY | EVIDENCE_INTEGRITY | ASSURANCE",
  "control_pattern": "REVIEW_CONTROL | APPROVAL_CONTROL | RECONCILIATION_CONTROL | ACCESS_CONTROL | TRANSACTION_CONTROL | MONITORING_CONTROL | CONFIGURATION_CONTROL | DOCUMENTATION_CONTROL",
  "lifecycle_stage": "IDENTIFICATION | VALIDATION | APPROVAL | EXCEPTION | REMEDIATION | EVIDENCE | NA",
  "effectiveness_type": "DESIGN | IMPLEMENTATION | OPERATING",
  "dimension_test_scope": "Describe exactly what to test for this dimension — do not cross dimension boundaries",
  "weight": "HIGH | MEDIUM | LOW",
  "assurance_weight": "HIGH | MEDIUM | LOW",
  "materiality": "HIGH | MEDIUM | LOW",
  "testing_method": "DOCUMENT_REVIEW | CONTENT_VALIDATION | APPROVAL_VALIDATION | CONFIGURATION_VALIDATION | ATTRIBUTE_VERIFICATION | SAMPLE_TESTING | LOG_REVIEW | TIMELINE_VALIDATION | RECONCILIATION | PROCESS_TRACE | DIAGRAM_ANALYSIS | COMMUNICATION_VALIDATION | THIRD_PARTY_VALIDATION | EXCEPTION_ANALYSIS",
  "testing_approach": "FULL | SAMPLE | TREND | RECOMPUTE | WALKTHROUGH",
  "expected_evidence_types": ["LIST ALL ACCEPTABLE TYPES"],
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
* Use consistent ENUM values only"""


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

        # ── 7. Parse dimensions ────────────────────────────────────────
        dims = validated.required_dimensions
        dimension_design = str(dims.get("design", "NO")).upper() == "YES"
        dimension_implementation = str(dims.get("implementation", "NO")).upper() == "YES"
        dimension_operating = str(dims.get("operating", "NO")).upper() == "YES"

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
