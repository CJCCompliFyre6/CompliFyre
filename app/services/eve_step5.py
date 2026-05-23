# app/services/eve_step5.py
#
# Module D — EVE Step 5: Evidence Execution Engine
#
# Runs on the AUDITOR side after evidence is uploaded.
# For each evidence artifact, evaluates it against each
# relevant checklist item and stores results in eve_evidence_result.
#
# One task per evidence artifact — parallel execution possible.

import os
import json
import time
import logging
from datetime import datetime

import fitz  # PyMuPDF
from docx import Document as DocxDocument
from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError

from app import db, client
from app.models.project_instance_models import (
    ProjectControlActivity,
    ProjectEvidenceArtifact,
    EvidenceFile,
)
from app.models.eve_models import (
    ProjectChecklist,
    EveEvidenceResult,
)

logger = get_task_logger(__name__)

# ─────────────────────────────────────────────────────────────
# File text extraction helpers
# ─────────────────────────────────────────────────────────────

def _extract_text_from_file(file_path: str, content_type: str = None) -> str:
    """
    Extract text content from an uploaded evidence file.
    Supports PDF, DOCX, TXT. Returns extracted text or error message.
    """
    if not file_path or not os.path.exists(file_path):
        return "[File not found or path invalid]"

    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext == ".pdf" or (content_type and "pdf" in content_type):
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return text.strip() or "[No extractable text found in PDF]"

        elif ext in (".docx",) or (content_type and "wordprocessingml" in content_type):
            doc = DocxDocument(file_path)
            return (
                "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                or "[No extractable text in DOCX]"
            )

        elif ext in (".txt", ".csv", ".log"):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().strip() or "[Empty file]"

        elif ext in (".xlsx", ".xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file_path, data_only=True)
                rows = []
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        row_text = " | ".join(str(c) for c in row if c is not None)
                        if row_text.strip():
                            rows.append(row_text)
                return "\n".join(rows[:200]) or "[No extractable data in Excel]"
            except Exception as e:
                return f"[Excel extraction error: {e}]"

        else:
            return f"[Unsupported file type: {ext}]"

    except Exception as e:
        logger.error(f"File extraction error for {file_path}: {e}")
        return f"[Extraction error: {e}]"


def _get_evidence_content(artifact: ProjectEvidenceArtifact, upload_base: str) -> str:
    """
    Get full text content for an evidence artifact.
    Combines evidence_text + all uploaded file contents.
    """
    parts = []

    # Uploaded files — primary source
    files = artifact.evidence_files.all() if artifact.evidence_files else []
    for ef in files:
        file_path = os.path.join(upload_base, ef.stored_filename) if ef.stored_filename else ef.file_path
        text = _extract_text_from_file(file_path, ef.content_type)
        parts.append(f"[File: {ef.file_name}]\n{text}")

    # Use evidence_text ONLY if no files uploaded (manual text or interview response)
    if not parts and artifact.evidence_text and artifact.evidence_text.strip():
        parts.append(f"[Evidence Text]\n{artifact.evidence_text.strip()}")

    if not parts:
        return "[No evidence content available]"

    return "\n\n---\n\n".join(parts)


# ─────────────────────────────────────────────────────────────
# LLM call — temperature=0 for determinism
# ─────────────────────────────────────────────────────────────

def _call_eve_step5(prompt: str, retries: int = 3, backoff: float = 2.0) -> dict | None:
    """Call OpenAI with temperature=0 — returns parsed JSON or None."""
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,
                top_p=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an Audit Evidence Execution Engine. "
                            "Return ONLY valid JSON. No explanation. No markdown. "
                            "Do NOT generate findings or conclude compliance."
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

    logger.error("All EVE Step 5 retries exhausted")
    return None


# ─────────────────────────────────────────────────────────────
# Prompt builder — exactly matches EVE v2 Step 5 Excel sheet
# ─────────────────────────────────────────────────────────────

def _build_step5_prompt(
    auditee_name: str,
    audit_period_start: str,
    audit_period_end: str,
    required_dimensions: dict,
    checklist: list,
    evidence_id: int,
    evidence_content: str,
) -> str:
    """Build EVE Step 5 prompt — V3 with all 14 principles."""

    return f"""You are an Audit Evidence Execution Engine.

TASK:
Evaluate the provided evidence against the applicable atomic checklist items.

You must:
* validate evidence against checklist assertions
* determine checklist satisfaction status
* generate traceable evidence mappings
* maintain assurance state updates
* identify contradictions, ambiguities, inadmissibility, and inquiry triggers
* support D / IE / OE evaluation logic
* support attribute, analytical, and population testing
* identify exact exceptions during OE testing
* produce deterministic evidence evaluation outputs

You must NOT:
* generate audit findings
* generate recommendations
* generate severity ratings
* generate audit conclusions
* directly assess overall compliance

Return ONLY valid JSON. No explanation. No markdown.

---

INPUT:

* Auditee Name: {auditee_name}

* Audit Period:
  Start Date: {audit_period_start}
  End Date: {audit_period_end}

* Required Dimensions:
  {json.dumps(required_dimensions, indent=2)}

* Checklist:
  {json.dumps(checklist, indent=2)}

* Evidence:
  {{
    "evidence_id": "{evidence_id}",
    "content": {json.dumps(evidence_content[:8000])}
  }}

---

PRINCIPLE 1 — CHECKLIST-DRIVEN EVALUATION ONLY:
Evaluate evidence ONLY against the atomic checklist items provided.
Do NOT summarize documents freely, generate narrative interpretations, or evaluate outside checklist scope.

PRINCIPLE 2 — ITEM-BY-ITEM VALIDATION:
Evaluate each checklist item independently.
Determine status: YES / NO / PARTIAL / NEEDS_REVIEW
Maintain cumulative checklist state across all uploaded evidence.

PRINCIPLE 3 — EVIDENCE TRACEABILITY IS MANDATORY:
Every checklist evaluation must contain:
* evidence source
* evidence location (exact section/page/reference)
* supporting extract (exact text from evidence)
* confidence classification
* admissibility status
Results may NOT be assigned without supporting extract OR explicit inadmissibility rationale.

---

SUB-STEP-1 — CLASSIFY EVIDENCE TYPE:

Classify evidence using predefined types:
POLICY_DOCUMENT | PROCEDURE_DOCUMENT | SOP_DOCUMENT | SYSTEM_SCREENSHOT |
SYSTEM_CONFIGURATION | TRANSACTION_DATASET | SAMPLED_RECORDS | SYSTEM_LOG |
APPLICATION_LOG | SECURITY_LOG | REPORT | DASHBOARD_EXPORT |
EMAIL_COMMUNICATION | APPROVAL_EMAIL | MEETING_MINUTES | BOARD_DOCUMENT |
PROCESS_FLOW_DIAGRAM | NETWORK_DIAGRAM | ARCHITECTURE_DIAGRAM |
THIRD_PARTY_DOCUMENT | CONTRACT | SLA_DOCUMENT | CERTIFICATE |
AUDIT_REPORT | INTERVIEW_RESPONSE | EXCEPTION_RECORD | INCIDENT_RECORD

---

SUB-STEP-2 — EXTRACT METADATA:

Extract if available:
* entity_name
* document_title
* approval_authority
* approval_date
* effective_date
* document_version

---

SUB-STEP-3 — ADMISSIBILITY CHECK (PRINCIPLE 6):

Evaluate admissibility using 5 states:
* VALID: Evidence sufficiently supports assertion
* NOT_PROVIDED: Required evidence absent
* PROVIDED_INVALID: Uploaded but unacceptable (wrong entity, wrong period, corrupt)
* PROVIDED_INSUFFICIENT: Partial support only — does not meet pass condition
* CONTRADICTORY: Conflicts with requirement or other evidence

Rules:
* Ownership FAIL → PROVIDED_INVALID
* Period FAIL → PROVIDED_INVALID
* Integrity FAIL → PROVIDED_INSUFFICIENT
* UNKNOWN values → PROVIDED_INSUFFICIENT

EXPLAINABLE INADMISSIBILITY IS MANDATORY:
Where evidence is inadmissible, explicitly state:
* which evidence failed
* why it failed
* what deficiency was identified

---

SUB-STEP-4 — SET EVIDENCE META:

Assign strength:
* STRONG: logs, configs, datasets, policies, board documents
* MODERATE: reports, screenshots, emails
* WEAK: interviews, observations

Assign role:
* PRIMARY: direct evidence (policy, logs, config, datasets)
* SUPPORTING: indirect evidence (interviews, screenshots)
* OBSERVATIONAL: walkthrough, process trace
* ANALYTICAL: trend analysis, reconciliation, recomputation

---

SUB-STEP-5 — FILTER RELEVANT CHECKLIST ITEMS:

Evaluate ALL checklist items against this evidence.
Do NOT skip items based on strict evidence_type matching.
Use semantic relevance: if evidence content can support or refute a checklist assertion, evaluate it.
Examples:
* BOARD_DOCUMENT can satisfy items expecting "policy documents", "approval records", "governance documents"
* MEETING_MINUTES can satisfy items expecting "approval records", "board documents", "governance evidence"
* POLICY_DOCUMENT can satisfy items expecting "control frameworks", "governance documents"
Only skip if evidence is completely unrelated to the checklist item's requirement.

---

SUB-STEP-6 — EXTRACT CLAIMS AND CHECKPOINTS:

For each relevant checklist item extract:
* claims: structured statements from evidence
* checkpoints: atomic facts aligned to requirement

Classify claim_type:
* DOCUMENTED: explicitly written in evidence
* OBSERVED: observed during walkthrough
* ASSERTION: stated verbally/in interview

---

SUB-STEP-7 — DETECT SIGNALS AND CONTRADICTIONS (PRINCIPLE 7):

For each checklist item determine:
signal = SUPPORTS / CONTRADICTS / INSUFFICIENT

RULES:
SUPPORTS: evidence aligns with requirement, satisfies pass_condition fully or partially
INSUFFICIENT: evidence exists but incomplete, does not fully meet pass_condition
CONTRADICTS: evidence conflicts with requirement OR conflicts with another statement

CRITICAL — CONTRADICTION HANDLING:
* Detected contradictions must generate INQUIRY TRIGGERS
* Contradictions must NOT automatically generate findings or failures
* Contradiction lifecycle: identified → inquiry triggered → clarification → resolved or escalated
* Only UNRESOLVED / MATERIAL contradictions may negatively impact assurance

IMPORTANT:
* Absence of evidence is NOT contradiction
* CONTRADICTS must only be used for clear logical conflict

---

SUB-STEP-8 — LOGICAL VALIDATION (PRINCIPLE 8):

Validate logical integrity across evidence:
* CHRONOLOGY: dates in logical sequence (approval before effective date)
* AUDIT_PERIOD_ALIGNMENT: evidence falls within audit period
* VERSION_ALIGNMENT: document versions consistent across evidence
* CROSS_DOC_CONSISTENCY: same facts stated consistently across documents
* APPROVAL_SEQUENCING: approval authority and sequence correct
* DEPENDENCY_CONSISTENCY: dependent controls/processes consistent

Logical failures must generate inquiry triggers.

---

SUB-STEP-9 — APPLY TEST LOGIC (PRINCIPLE 9, 10, 11):

Use testing_method, testing_approach, evaluation_logic from checklist.

STATUS RULES:
* YES: pass_condition fully satisfied with explicit evidence extract
* PARTIAL: partially satisfied or incomplete — partial_condition met
* NO: fail_condition met
* NEEDS_REVIEW: evidence exists but requires auditor judgment

DIMENSION-SPECIFIC RULES:
* DESIGN items: test existence/documentation ONLY — do NOT assess execution
* IMPLEMENTATION items: test operationalization/rollout — do NOT conclude sustained effectiveness
* OPERATING items: test execution over audit period — use attribute/sample/population testing

ATTRIBUTE TESTING (P9):
For OE items with oe_testing.applicable = YES:
* evaluate each required attribute independently
* identify exact failed attributes
* preserve instance-level traceability

ANALYTICAL TESTING (P10):
* evaluate trends, ratios, thresholds, exception rates
* disclose calculation logic
* identify exact analytical exceptions

POPULATION/SAMPLE TESTING (P11):
* evaluate each instance independently
* preserve population completeness
* identify exact failed instances — do NOT summarize failures generically

SPECIAL RULES:
1. INTERVIEW_RESPONSE:
   * strength = WEAK
   * cannot independently pass HIGH weight items
   * at best → PARTIAL

2. PROCESS_TRACE:
   * must show full flow + execution
   * flow only → PARTIAL

3. SAMPLE TESTING:
   * evaluate: sample_size, exceptions_found, exception_rate, audit_period_coverage

---

SUB-STEP-10 — EVIDENCE REFERENCE AND CONFIDENCE:

Provide:
* exact section/clause/page reference
* supporting extract (verbatim text from evidence)

Confidence Classification (P11):
* EXPLICIT: requirement directly and clearly stated → allows YES
* IMPLIED: reasonably inferred from context → allows PARTIAL only
* AMBIGUOUS: unclear or indirect → allows PARTIAL or NEEDS_REVIEW only

---

SUB-STEP-11 — EVIDENCE INTEGRITY VALIDATION (PRINCIPLE 13):

Validate:
* evidence_traceability: can result be traced to exact evidence location?
* location_validation: is evidence location identified?
* inference_prevention: is unsupported inference avoided?
* period_alignment: does evidence fall within audit period?
* cross_doc_consistency: are facts consistent across documents?
* version_alignment: are document versions current and consistent?

Evidence integrity failures must reduce assurance confidence and generate inquiry triggers.

---

SUB-STEP-12 — ASSURANCE STATE UPDATE (PRINCIPLE 12):

Update assurance state variables:
* assurance_score_delta: positive/negative/neutral impact
* coverage_delta: how much of checklist is now covered
* evidence_quality_impact: HIGH/MEDIUM/LOW
* inquiry_triggered: YES/NO
* contradiction_detected: YES/NO

---

OUTPUT FORMAT (return ONLY this structure — no explanation, no markdown):

{{{{
  "evidence_id": "{evidence_id}",
  "evidence_type": "",
  "admissibility": "",
  "admissibility_reason": "",
  "confidence": "",
  "evidence_meta": {{{{
    "strength": "",
    "role": "",
    "entity_name": "",
    "document_title": "",
    "document_version": "",
    "approval_authority": "",
    "approval_date": "",
    "effective_date": ""
  }}}},
  "claims": [
    {{{{
      "checklist_id": "",
      "claim": "",
      "claim_type": "",
      "confidence": ""
    }}}}
  ],
  "checkpoints": [
    {{{{
      "checklist_id": "",
      "checkpoint": "",
      "evidence_location": "",
      "supporting_extract": ""
    }}}}
  ],
  "item_signals": [
    {{{{
      "checklist_id": "",
      "signal": "",
      "basis": "",
      "confidence": ""
    }}}}
  ],
  "results": [
    {{{{
      "checklist_id": "",
      "status": "",
      "confidence_classification": "",
      "evidence_reference": "",
      "supporting_extract": "",
      "admissibility_status": "",
      "admissibility_reason": "",
      "assurance_impact": ""
    }}}}
  ],
  "inquiry_triggers": [
    {{{{
      "checklist_id": "",
      "trigger_type": "CONTRADICTION_DETECTED | AMBIGUOUS_EVIDENCE | INSUFFICIENT_EVIDENCE | PERIOD_MISMATCH | LOGICAL_FAILURE | APPROVAL_MISSING",
      "severity": "MATERIAL | MINOR",
      "evidence_a_claim": "",
      "evidence_b_claim": "",
      "inquiry_question": "",
      "suggested_additional_evidence": ""
    }}}}
  ],
  "logical_validations": [
    {{{{
      "validation_type": "CHRONOLOGY | AUDIT_PERIOD_ALIGNMENT | VERSION_ALIGNMENT | CROSS_DOC_CONSISTENCY | APPROVAL_SEQUENCING",
      "checklist_id": "",
      "result": "PASS | FAIL | UNKNOWN",
      "detail": "",
      "inquiry_triggered": "YES | NO"
    }}}}
  ],
  "attribute_test_results": [
    {{{{
      "checklist_id": "",
      "instance_id": "",
      "attribute": "",
      "result": "PASS | FAIL",
      "reason": "",
      "evidence_reference": ""
    }}}}
  ],
  "exception_instances": [
    {{{{
      "instance_id": "",
      "checklist_id": "",
      "status": "FAIL",
      "failed_attribute": "",
      "exception_reason": "",
      "evidence_reference": ""
    }}}}
  ],
  "evidence_integrity": {{{{
    "traceability": "PASS | FAIL | PARTIAL",
    "location_validation": "PASS | FAIL | PARTIAL",
    "period_alignment": "PASS | FAIL | UNKNOWN",
    "cross_doc_consistency": "PASS | FAIL | UNKNOWN | NOT_APPLICABLE",
    "version_alignment": "PASS | FAIL | UNKNOWN | NOT_APPLICABLE",
    "overall_integrity": "HIGH | MEDIUM | LOW"
  }}}},
  "assurance_state_update": {{{{
    "assurance_score_delta": 0.0,
    "coverage_delta": 0.0,
    "evidence_quality_impact": "HIGH | MEDIUM | LOW",
    "inquiry_triggered": "YES | NO",
    "contradiction_detected": "YES | NO",
    "oe_reliability_impact": "POSITIVE | NEUTRAL | NEGATIVE"
  }}}},
  "sample_evaluation": {{{{
    "applicable": "YES | NO",
    "sample_size": null,
    "exceptions_found": null,
    "exception_rate": null,
    "within_audit_period": "YES | NO | PARTIAL"
  }}}}
}}}}

STRICT CONSTRAINTS:
* Do NOT generate findings, observations, or recommendations
* Do NOT conclude compliance or control effectiveness
* Do NOT evaluate non-relevant checklist items
* Do NOT assume missing information
* All outputs must be structured and explicit
* inquiry_triggers must NOT be empty when contradiction detected
* supporting_extract must be verbatim text from evidence — NOT paraphrase
* confidence_classification must follow: EXPLICIT → YES only, IMPLIED → PARTIAL only, AMBIGUOUS → PARTIAL or NEEDS_REVIEW only"""


# ─────────────────────────────────────────────────────────────
# MODULE D — Celery Task
# ─────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_eve_step5_for_evidence(
    self,
    project_evidence_artifact_id: int,
    project_checklist_id: int,
    upload_base_path: str = None,
):
    """
    Module D — EVE Step 5: Run evidence execution engine for one evidence artifact.

    For each relevant checklist item in the project checklist,
    evaluates the evidence and stores result in eve_evidence_result.

    Args:
        project_evidence_artifact_id: ID from project_evidence_artifacts
        project_checklist_id:         ID from project_checklist
        upload_base_path:             Base path for uploaded files (optional)

    Returns:
        dict with status and results summary
    """
    logger.info(
        f"[Module D] Starting EVE Step 5 for "
        f"evidence_id={project_evidence_artifact_id}, "
        f"checklist_id={project_checklist_id}"
    )

    try:
        # ── 1. Load evidence artifact ──────────────────────────────────
        artifact = db.session.query(ProjectEvidenceArtifact).get(
            project_evidence_artifact_id
        )
        if not artifact:
            return {
                "status": "error",
                "message": f"ProjectEvidenceArtifact {project_evidence_artifact_id} not found",
            }

        # ── 2. Load project checklist ──────────────────────────────────
        checklist = db.session.query(ProjectChecklist).get(project_checklist_id)
        if not checklist:
            return {
                "status": "error",
                "message": f"ProjectChecklist {project_checklist_id} not found",
            }

        checklist_items = checklist.get_checklist_items()
        if not checklist_items:
            return {
                "status": "error",
                "message": "ProjectChecklist has no checklist items — run Module B first",
                "project_checklist_id": project_checklist_id,
            }

        # ── 3. Get project context (auditee name, audit period) ────────
        pca = artifact.project_control_activity
        project = None
        auditee_name = "Unknown"
        audit_period_start = "Unknown"
        audit_period_end = "Unknown"

        if pca:
            # Navigate up: pca → project_compliance_activity → project_clause → project
            try:
                pca_obj = pca
                pcomp = getattr(pca_obj, "project_compliance_activity", None)
                pclause = getattr(pcomp, "project_clause", None) if pcomp else None
                project = getattr(pclause, "project", None) if pclause else None

                if project:
                    auditee_name = (
                        getattr(project, "organization_name", None)
                        or getattr(project, "name", None)
                        or "Unknown"
                    )
                    audit_period_start = str(
                        getattr(project, "audit_period_start", None)
                        or getattr(project, "start_date", None)
                        or "Unknown"
                    )
                    audit_period_end = str(
                        getattr(project, "audit_period_end", None)
                        or getattr(project, "end_date", None)
                        or "Unknown"
                    )
            except Exception as e:
                logger.warning(f"[Module D] Could not extract project context: {e}")

        # ── 4. Extract evidence content from files ─────────────────────
        if not upload_base_path:
            upload_base_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "../../uploads"
            )

        evidence_content = _get_evidence_content(artifact, upload_base_path)

        logger.info(
            f"[Module D] Evidence content extracted: "
            f"{len(evidence_content)} chars for artifact_id={project_evidence_artifact_id}"
        )

        # ── 5. Build required_dimensions from checklist ────────────────
        required_dimensions = {
            "design": "YES" if checklist.dimension_design else "NO",
            "implementation": "YES" if checklist.dimension_implementation else "NO",
            "operating": "YES" if checklist.dimension_operating else "NO",
        }

        # ── 6. Call EVE Step 5 LLM ────────────────────────────────────
        prompt = _build_step5_prompt(
            auditee_name=auditee_name,
            audit_period_start=audit_period_start,
            audit_period_end=audit_period_end,
            required_dimensions=required_dimensions,
            checklist=checklist_items,
            evidence_id=project_evidence_artifact_id,
            evidence_content=evidence_content,
        )

        raw_output = _call_eve_step5(prompt)

        if not raw_output:
            raise self.retry(
                exc=Exception("LLM returned no output for EVE Step 5"),
                countdown=60,
            )

        # ── 7. Parse and store results ─────────────────────────────────
        admissibility = raw_output.get("admissibility", "PARTIAL")
        admissibility_reason = raw_output.get("admissibility_reason", "")
        evidence_type = raw_output.get("evidence_type", "")
        overall_confidence = raw_output.get("confidence", "MEDIUM")

        evidence_meta = raw_output.get("evidence_meta", {})
        strength = evidence_meta.get("strength", "MODERATE")
        role = evidence_meta.get("role", "SUPPORTING")

        sample_eval = raw_output.get("sample_evaluation", {})
        sample_applicable = str(sample_eval.get("applicable", "NO")).upper() == "YES"
        sample_size = sample_eval.get("sample_size")
        exception_rate = sample_eval.get("exception_rate")
        within_audit_period = str(sample_eval.get("within_audit_period", "NO")).upper() == "YES"

        # Build lookup maps for signals and results
        signals_map = {
            s["checklist_id"]: s
            for s in raw_output.get("item_signals", [])
            if s.get("checklist_id")
        }
        results_map = {
            r["checklist_id"]: r
            for r in raw_output.get("results", [])
            if r.get("checklist_id")
        }

        # Identify which checklist items were evaluated
        evaluated_item_ids = set(signals_map.keys()) | set(results_map.keys())

        if not evaluated_item_ids:
            # Evidence not relevant to any checklist item
            logger.info(
                f"[Module D] Evidence {project_evidence_artifact_id} not relevant "
                f"to any checklist item — admissibility={admissibility}"
            )
            return {
                "status": "not_relevant",
                "message": "Evidence not relevant to any checklist item",
                "project_evidence_artifact_id": project_evidence_artifact_id,
                "admissibility": admissibility,
                "evidence_type": evidence_type,
                "items_evaluated": 0,
            }

        # Store one EveEvidenceResult per evaluated checklist item
        stored_count = 0
        skipped_count = 0

        for checklist_item_id in evaluated_item_ids:
            # Check if already exists (idempotent)
            existing = (
                db.session.query(EveEvidenceResult)
                .filter_by(
                    project_checklist_id=project_checklist_id,
                    evidence_artifact_id=project_evidence_artifact_id,
                    checklist_item_id=checklist_item_id,
                )
                .first()
            )
            if existing:
                skipped_count += 1
                continue

            signal_data = signals_map.get(checklist_item_id, {})
            result_data = results_map.get(checklist_item_id, {})

            signal = signal_data.get("signal", "INSUFFICIENT")
            signal_basis = signal_data.get("basis", "")
            item_status = result_data.get("status", "PARTIAL")
            evidence_reference = result_data.get("evidence_reference", "")
            item_confidence = result_data.get("confidence", overall_confidence)

            # Validate ENUMs
            if signal not in ("SUPPORTS", "CONTRADICTS", "INSUFFICIENT"):
                signal = "INSUFFICIENT"
            if item_status not in ("PASS", "PARTIAL", "FAIL"):
                item_status = "PARTIAL"
            if admissibility not in ("ADMISSIBLE", "PARTIAL", "INADMISSIBLE"):
                admissibility = "PARTIAL"
            if strength not in ("STRONG", "MODERATE", "WEAK"):
                strength = "MODERATE"

            # Apply special rule — INTERVIEW_RESPONSE cannot PASS HIGH weight items
            if evidence_type == "INTERVIEW_RESPONSE" and item_status == "PASS":
                checklist_item = checklist.get_item_by_id(checklist_item_id)
                if checklist_item and checklist_item.get("weight") == "HIGH":
                    item_status = "PARTIAL"
                    logger.info(
                        f"[Module D] Interview response downgraded from PASS to PARTIAL "
                        f"for HIGH weight item {checklist_item_id}"
                    )

            # New V3 fields from results_map
            confidence_classification = result_data.get("confidence_classification", "IMPLIED")
            supporting_extract = result_data.get("supporting_extract", "")
            admissibility_status_v3 = result_data.get("admissibility_status", admissibility)
            assurance_impact = result_data.get("assurance_impact", "NEUTRAL")

            result_record = EveEvidenceResult(
                project_checklist_id=project_checklist_id,
                evidence_artifact_id=project_evidence_artifact_id,
                checklist_item_id=checklist_item_id,
                admissibility=admissibility,
                admissibility_reason=admissibility_reason,
                evidence_type=evidence_type,
                evidence_strength=strength,
                evidence_role=role,
                signal=signal,
                signal_basis=signal_basis,
                item_status=item_status,
                confidence=item_confidence,
                evidence_reference=evidence_reference,
                sample_applicable=sample_applicable,
                sample_size=int(sample_size) if sample_size else None,
                exception_rate=float(exception_rate) if exception_rate else None,
                sample_within_audit_period=within_audit_period,
                raw_output_json=raw_output,
                generated_at=datetime.utcnow(),
            )
            db.session.add(result_record)
            stored_count += 1

        # ── 8. Process Inquiry Triggers ────────────────────────────────
        inquiry_triggers = raw_output.get("inquiry_triggers", [])
        inquiry_count = 0
        for trigger in inquiry_triggers:
            checklist_item_id = trigger.get("checklist_id", "")
            inquiry_question = trigger.get("inquiry_question", "")
            if not checklist_item_id or not inquiry_question:
                continue

            # Check if inquiry already exists for this checklist item
            from app.models.eve_models import EveInquiry
            existing_inquiry = (
                db.session.query(EveInquiry)
                .filter_by(
                    project_checklist_id=project_checklist_id,
                    checklist_item_id=checklist_item_id,
                    status="PENDING_INQUIRY"
                )
                .first()
            )
            if existing_inquiry:
                continue  # Already raised

            severity = trigger.get("severity", "MINOR")
            if severity not in ("MATERIAL", "MINOR"):
                severity = "MINOR"

            inquiry = EveInquiry(
                project_checklist_id=project_checklist_id,
                checklist_item_id=checklist_item_id,
                contradiction_type=trigger.get("trigger_type", "CONTRADICTION_DETECTED"),
                severity=severity,
                evidence_a_id=project_evidence_artifact_id,
                evidence_a_type=evidence_type,
                evidence_a_claim=trigger.get("evidence_a_claim", ""),
                evidence_b_claim=trigger.get("evidence_b_claim", ""),
                inquiry_question=inquiry_question,
                suggested_evidence=trigger.get("suggested_additional_evidence", ""),
                status="PENDING_INQUIRY",
            )
            db.session.add(inquiry)
            inquiry_count += 1

        logger.info(f"[Module D] {inquiry_count} inquiry triggers saved for checklist_id={project_checklist_id}")

        # ── 9. Update Assurance State ──────────────────────────────────
        assurance_update = raw_output.get("assurance_state_update", {})
        evidence_integrity = raw_output.get("evidence_integrity", {})

        from app.models.eve_models import EveAssuranceState
        assurance_state = (
            db.session.query(EveAssuranceState)
            .filter_by(project_checklist_id=project_checklist_id)
            .first()
        )

        if not assurance_state:
            assurance_state = EveAssuranceState(
                project_checklist_id=project_checklist_id,
                total_checklist_items=len(checklist_items),
            )
            db.session.add(assurance_state)

        # Update counts
        assurance_state.total_evidence_count = (assurance_state.total_evidence_count or 0) + 1
        if admissibility in ("ADMISSIBLE", "VALID", "PROVIDED_INSUFFICIENT"):
            assurance_state.admissible_evidence_count = (assurance_state.admissible_evidence_count or 0) + 1

        # Update inquiry counts
        assurance_state.inquiry_count = (assurance_state.inquiry_count or 0) + inquiry_count
        if assurance_update.get("contradiction_detected") == "YES":
            assurance_state.contradiction_count = (assurance_state.contradiction_count or 0) + 1

        # Update scores based on assurance_update delta
        score_delta = float(assurance_update.get("assurance_score_delta", 0.0))
        coverage_delta = float(assurance_update.get("coverage_delta", 0.0))
        assurance_state.assurance_score = min(1.0, max(0.0, (assurance_state.assurance_score or 0.0) + score_delta))
        assurance_state.coverage_score = min(1.0, max(0.0, (assurance_state.coverage_score or 0.0) + coverage_delta))

        # Evidence quality impact
        eq_impact = assurance_update.get("evidence_quality_impact", "MEDIUM")
        eq_map = {"HIGH": 0.1, "MEDIUM": 0.05, "LOW": 0.01}
        assurance_state.evidence_quality_score = min(1.0, max(0.0,
            (assurance_state.evidence_quality_score or 0.0) + eq_map.get(eq_impact, 0.05)
        ))

        # OE reliability impact
        oe_impact = assurance_update.get("oe_reliability_impact", "NEUTRAL")
        oe_map = {"POSITIVE": 0.1, "NEUTRAL": 0.0, "NEGATIVE": -0.1}
        assurance_state.oe_reliability_score = min(1.0, max(0.0,
            (assurance_state.oe_reliability_score or 0.0) + oe_map.get(oe_impact, 0.0)
        ))

        assurance_state.last_evidence_id = project_evidence_artifact_id
        from datetime import datetime
        assurance_state.last_updated_at = datetime.utcnow()

        logger.info(
            f"[Module D] Assurance state updated: "
            f"assurance_score={assurance_state.assurance_score:.2f}, "
            f"coverage_score={assurance_state.coverage_score:.2f}, "
            f"inquiry_count={assurance_state.inquiry_count}"
        )

        db.session.commit()

        logger.info(
            f"[Module D] Done for evidence_id={project_evidence_artifact_id}: "
            f"stored={stored_count}, skipped={skipped_count}, "
            f"admissibility={admissibility}, evidence_type={evidence_type}"
        )

        return {
            "status": "success",
            "project_evidence_artifact_id": project_evidence_artifact_id,
            "project_checklist_id": project_checklist_id,
            "admissibility": admissibility,
            "evidence_type": evidence_type,
            "strength": strength,
            "items_evaluated": stored_count,
            "items_skipped": skipped_count,
        }

    except self.MaxRetriesExceededError:
        logger.error(
            f"[Module D] Max retries exceeded for "
            f"evidence_id={project_evidence_artifact_id}"
        )
        return {
            "status": "error",
            "message": "Max retries exceeded",
            "project_evidence_artifact_id": project_evidence_artifact_id,
        }
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module D] DB error: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module D] Unexpected error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "project_evidence_artifact_id": project_evidence_artifact_id,
        }


# ─────────────────────────────────────────────────────────────
# BULK TASK — run Step 5 for ALL evidence under a checklist
# ─────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_eve_step5_for_all_evidence(
    self,
    project_checklist_id: int,
    upload_base_path: str = None,
):
    """
    Trigger EVE Step 5 for ALL evidence artifacts under a project checklist.
    Dispatches one run_eve_step5_for_evidence task per artifact.

    Args:
        project_checklist_id: ID from project_checklist table

    Returns:
        dict with count of tasks dispatched
    """
    logger.info(
        f"[Module D Bulk] Triggering Step 5 for all evidence "
        f"under project_checklist_id={project_checklist_id}"
    )

    try:
        checklist = db.session.query(ProjectChecklist).get(project_checklist_id)
        if not checklist:
            return {
                "status": "error",
                "message": f"ProjectChecklist {project_checklist_id} not found",
            }

        # Get all evidence for the linked project_control_activity
        pca_id = checklist.project_control_activity_id
        artifacts = (
            db.session.query(ProjectEvidenceArtifact)
            .filter_by(project_control_activity_id=pca_id)
            .all()
        )

        if not artifacts:
            return {
                "status": "error",
                "message": "No evidence artifacts found for this control activity",
                "project_checklist_id": project_checklist_id,
            }

        dispatched = []
        for artifact in artifacts:
            task = run_eve_step5_for_evidence.apply_async(
                args=[artifact.id, project_checklist_id],
                kwargs={"upload_base_path": upload_base_path},
                queue="eve_evaluate",
            )
            dispatched.append({
                "evidence_artifact_id": artifact.id,
                "task_id": task.id,
            })

        # Update checklist status to in_progress
        checklist.status = "in_progress"
        db.session.commit()

        logger.info(
            f"[Module D Bulk] Dispatched {len(dispatched)} Step 5 tasks "
            f"for project_checklist_id={project_checklist_id}"
        )

        return {
            "status": "started",
            "project_checklist_id": project_checklist_id,
            "evidence_count": len(artifacts),
            "tasks_dispatched": len(dispatched),
            "tasks": dispatched,
        }

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module D Bulk] DB error: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module D Bulk] Error: {e}")
        return {"status": "error", "message": str(e)}


# ─────────────────────────────────────────────────────────────
# MODULE E — Step 5B: Cross-Evidence Contradiction Detection
# ─────────────────────────────────────────────────────────────

def _build_step5b_prompt(
    checklist_items: list,
    evidence_results: list,
) -> str:
    """Build Step 5B prompt — cross-evidence contradiction detection."""

    return f"""You are an Audit Cross-Evidence Contradiction Engine.

TASK:
Compare ALL evidence results for the same checklist items and detect contradictions ACROSS different evidence sources.

This is NOT about within-document contradictions (already handled in Step 5A).
This is about comparing what DIFFERENT evidence sources say about the SAME checklist item.

Return ONLY valid JSON. No explanation. No markdown.

---

INPUT:

* Checklist Items:
  {json.dumps(checklist_items, indent=2)}

* All Evidence Results (per evidence, per checklist item):
  {json.dumps(evidence_results, indent=2)}

---

TASK:
For each checklist item that has results from 2+ evidence sources:

1. Compare signals across all evidence sources
2. Detect logical contradictions between different evidence sources
3. Generate inquiry triggers for material contradictions

CONTRADICTION TYPES:
* FREQUENCY_MISMATCH: Evidence A says quarterly, Evidence B says annual
* EXISTENCE_CONFLICT: Evidence A says control exists, Evidence B shows it does not
* PERIOD_MISMATCH: Evidence A is current, Evidence B is outdated/different period
* APPROVAL_CONFLICT: Evidence A shows approved, Evidence B shows pending/rejected
* SCOPE_CONFLICT: Different populations or scopes claimed
* VERSION_CONFLICT: Different document versions referenced
* AUTHORITY_CONFLICT: Different approval authorities mentioned

RULES:
* Only flag CLEAR logical contradictions — not minor differences in wording
* Absence of evidence in one source is NOT a contradiction
* If all sources SUPPORT → consistent = YES
* If sources CONTRADICT each other → generate inquiry trigger
* contradiction_action = INQUIRY always (never auto-FAIL)
* Only MATERIAL contradictions require inquiry (MINOR ones just note)

---

OUTPUT FORMAT (return ONLY this structure):

{{
  "cross_evidence_analysis": [
    {{
      "checklist_id": "",
      "evidence_count": 0,
      "signals": [
        {{
          "evidence_id": 0,
          "evidence_type": "",
          "signal": "SUPPORTS | CONTRADICTS | INSUFFICIENT",
          "claim": ""
        }}
      ],
      "consistent": "YES | NO | PARTIAL",
      "contradiction_detected": "YES | NO",
      "contradiction_type": "",
      "severity": "MATERIAL | MINOR",
      "evidence_a": {{
        "id": 0,
        "type": "",
        "claim": ""
      }},
      "evidence_b": {{
        "id": 0,
        "type": "",
        "claim": ""
      }},
      "inquiry_question": "",
      "suggested_additional_evidence": "",
      "inquiry_trigger": "YES | NO"
    }}
  ],
  "summary": {{
    "total_items_analyzed": 0,
    "contradictions_found": 0,
    "material_contradictions": 0,
    "consistent_items": 0,
    "inquiry_triggers_generated": 0
  }}
}}

STRICT CONSTRAINTS:
* Only analyze items with 2+ evidence sources
* Do NOT generate findings or conclusions
* contradiction_action is always INQUIRY — never auto-FAIL
* inquiry_question must be specific and actionable
"""


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def run_eve_step5b_cross_evidence(
    self,
    project_checklist_id: int,
):
    """
    Module E — EVE Step 5B: Cross-Evidence Contradiction Detection.

    Runs AFTER all Step 5A evidence evaluations are complete.
    Compares signals across ALL evidence sources for each checklist item.
    Detects contradictions between different evidence sources.
    Generates inquiry triggers for material contradictions.

    Args:
        project_checklist_id: ID from project_checklist table
    """
    logger.info(
        f"[Module E] Starting Step 5B cross-evidence analysis "
        f"for project_checklist_id={project_checklist_id}"
    )

    try:
        # ── 1. Load checklist ──────────────────────────────────────────
        checklist = db.session.query(ProjectChecklist).get(project_checklist_id)
        if not checklist:
            return {
                "status": "error",
                "message": f"ProjectChecklist {project_checklist_id} not found",
            }

        checklist_items = checklist.get_checklist_items()
        if not checklist_items:
            return {
                "status": "error",
                "message": "No checklist items found",
            }

        # ── 2. Load all evidence results for this checklist ────────────
        all_results = (
            db.session.query(EveEvidenceResult)
            .filter_by(project_checklist_id=project_checklist_id)
            .all()
        )

        if not all_results:
            return {
                "status": "skipped",
                "message": "No evidence results found — run Step 5A first",
                "project_checklist_id": project_checklist_id,
            }

        # ── 3. Group results by checklist_item_id ─────────────────────
        # Only process items with 2+ evidence sources
        from collections import defaultdict
        items_by_checklist = defaultdict(list)

        for result in all_results:
            items_by_checklist[result.checklist_item_id].append({
                "evidence_id": result.evidence_artifact_id,
                "evidence_type": result.evidence_type,
                "signal": result.signal,
                "signal_basis": result.signal_basis,
                "item_status": result.item_status,
                "admissibility": result.admissibility,
                "confidence": result.confidence,
                "evidence_reference": result.evidence_reference,
            })

        # Filter items with 2+ evidence sources
        multi_evidence_items = {
            k: v for k, v in items_by_checklist.items() if len(v) >= 2
        }

        if not multi_evidence_items:
            logger.info(
                f"[Module E] No checklist items with 2+ evidence sources "
                f"for project_checklist_id={project_checklist_id}"
            )
            return {
                "status": "skipped",
                "message": "No checklist items with multiple evidence sources",
                "project_checklist_id": project_checklist_id,
                "items_analyzed": 0,
            }

        logger.info(
            f"[Module E] Analyzing {len(multi_evidence_items)} items "
            f"with multiple evidence sources"
        )

        # ── 4. Build evidence results for prompt ───────────────────────
        evidence_results_for_prompt = []
        for checklist_id, results in multi_evidence_items.items():
            evidence_results_for_prompt.append({
                "checklist_id": checklist_id,
                "evidence_count": len(results),
                "results": results,
            })

        # ── 5. Call Step 5B LLM ────────────────────────────────────────
        prompt = _build_step5b_prompt(
            checklist_items=checklist_items,
            evidence_results=evidence_results_for_prompt,
        )

        raw_output = _call_eve_step5(prompt)

        if not raw_output:
            return {
                "status": "error",
                "message": "LLM returned no output for Step 5B",
                "project_checklist_id": project_checklist_id,
            }

        # ── 6. Process cross-evidence contradictions ───────────────────
        from app.models.eve_models import EveInquiry, EveAssuranceState

        analysis = raw_output.get("cross_evidence_analysis", [])
        summary = raw_output.get("summary", {})

        inquiry_count = 0
        contradiction_count = 0

        for item_analysis in analysis:
            checklist_item_id = item_analysis.get("checklist_id", "")
            contradiction_detected = item_analysis.get("contradiction_detected", "NO") == "YES"
            inquiry_trigger = item_analysis.get("inquiry_trigger", "NO") == "YES"
            severity = item_analysis.get("severity", "MINOR")
            inquiry_question = item_analysis.get("inquiry_question", "")

            if not checklist_item_id:
                continue

            if contradiction_detected:
                contradiction_count += 1

            if inquiry_trigger and inquiry_question and severity == "MATERIAL":
                # Check if inquiry already exists
                existing_inquiry = (
                    db.session.query(EveInquiry)
                    .filter_by(
                        project_checklist_id=project_checklist_id,
                        checklist_item_id=checklist_item_id,
                        status="PENDING_INQUIRY",
                    )
                    .first()
                )

                if not existing_inquiry:
                    evidence_a = item_analysis.get("evidence_a", {})
                    evidence_b = item_analysis.get("evidence_b", {})

                    inquiry = EveInquiry(
                        project_checklist_id=project_checklist_id,
                        checklist_item_id=checklist_item_id,
                        contradiction_type=item_analysis.get(
                            "contradiction_type", "CROSS_EVIDENCE_CONTRADICTION"
                        ),
                        severity=severity,
                        evidence_a_id=evidence_a.get("id"),
                        evidence_a_type=evidence_a.get("type", ""),
                        evidence_a_claim=evidence_a.get("claim", ""),
                        evidence_b_id=evidence_b.get("id"),
                        evidence_b_type=evidence_b.get("type", ""),
                        evidence_b_claim=evidence_b.get("claim", ""),
                        inquiry_question=inquiry_question,
                        suggested_evidence=item_analysis.get(
                            "suggested_additional_evidence", ""
                        ),
                        status="PENDING_INQUIRY",
                    )
                    db.session.add(inquiry)
                    inquiry_count += 1

        # ── 7. Update assurance state ──────────────────────────────────
        assurance_state = (
            db.session.query(EveAssuranceState)
            .filter_by(project_checklist_id=project_checklist_id)
            .first()
        )

        if assurance_state:
            assurance_state.contradiction_count = (
                assurance_state.contradiction_count or 0
            ) + contradiction_count
            assurance_state.inquiry_count = (
                assurance_state.inquiry_count or 0
            ) + inquiry_count

            # Cross-evidence contradictions reduce assurance score
            if contradiction_count > 0:
                assurance_state.assurance_score = max(
                    0.0,
                    (assurance_state.assurance_score or 0.0)
                    - (0.05 * contradiction_count),
                )

            from datetime import datetime
            assurance_state.last_updated_at = datetime.utcnow()

        db.session.commit()

        logger.info(
            f"[Module E] Step 5B complete: "
            f"items_analyzed={len(multi_evidence_items)}, "
            f"contradictions={contradiction_count}, "
            f"inquiries_raised={inquiry_count}"
        )

        return {
            "status": "success",
            "project_checklist_id": project_checklist_id,
            "items_analyzed": len(multi_evidence_items),
            "contradictions_found": contradiction_count,
            "inquiry_triggers_raised": inquiry_count,
            "summary": summary,
        }

    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module E] DB error: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module E] Unexpected error: {e}")
        return {
            "status": "error",
            "message": str(e),
            "project_checklist_id": project_checklist_id,
        }

