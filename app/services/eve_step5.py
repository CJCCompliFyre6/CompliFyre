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

    # Text evidence
    if artifact.evidence_text and artifact.evidence_text.strip():
        parts.append(f"[Evidence Text]\n{artifact.evidence_text.strip()}")

    # Uploaded files
    files = artifact.evidence_files.all() if artifact.evidence_files else []
    for ef in files:
        file_path = os.path.join(upload_base, ef.stored_filename) if ef.stored_filename else ef.file_path
        text = _extract_text_from_file(file_path, ef.content_type)
        parts.append(f"[File: {ef.file_name}]\n{text}")

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
    """Build EVE Step 5 prompt — matches Excel sheet exactly."""

    return f"""You are an Audit Evidence Execution Engine.

TASK:
Analyze the provided evidence and generate structured evaluation signals against relevant checklist items.

You must extract facts, detect support and contradictions, and prepare outputs for aggregation.

DO NOT:
* assign final compliance status
* generate findings
* conclude control effectiveness

Return ONLY valid JSON.

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

SUB-STEP-1 — CLASSIFY EVIDENCE TYPE

Classify evidence using predefined types:
POLICY_DOCUMENT | PROCEDURE_DOCUMENT | SOP_DOCUMENT | SYSTEM_SCREENSHOT |
SYSTEM_CONFIGURATION | TRANSACTION_DATASET | SAMPLED_RECORDS | SYSTEM_LOG |
APPLICATION_LOG | SECURITY_LOG | REPORT | DASHBOARD_EXPORT |
EMAIL_COMMUNICATION | APPROVAL_EMAIL | MEETING_MINUTES | BOARD_DOCUMENT |
PROCESS_FLOW_DIAGRAM | NETWORK_DIAGRAM | ARCHITECTURE_DIAGRAM |
THIRD_PARTY_DOCUMENT | CONTRACT | SLA_DOCUMENT | CERTIFICATE |
AUDIT_REPORT | INTERVIEW_RESPONSE | EXCEPTION_RECORD | INCIDENT_RECORD

Return: "evidence_type": ""

---

SUB-STEP-2 — EXTRACT METADATA

Extract if available:
* entity_name
* document_title
* approval_authority
* approval_date
* effective_date

---

SUB-STEP-3 — ADMISSIBILITY CHECK

Evaluate:

A. Ownership:
* match with auditee → PASS
* mismatch → FAIL
* unclear → UNKNOWN

B. Audit Period:
* within period → PASS
* outside → FAIL
* unknown → UNKNOWN

C. Approval:
* if applicable → validate presence
* else → NOT_REQUIRED

D. Integrity:
* structured and readable → PASS
* partial → PARTIAL
* poor → FAIL

DETERMINE admissibility:
* ADMISSIBLE / PARTIAL / INADMISSIBLE

Rules:
* ownership FAIL → INADMISSIBLE
* period FAIL → INADMISSIBLE
* integrity FAIL → PARTIAL
* UNKNOWN values → PARTIAL

---

SUB-STEP-4 — SET EVIDENCE META

Assign:
* strength:
  STRONG → logs, configs, datasets, policies
  MODERATE → reports, screenshots
  WEAK → interviews

* role:
  PRIMARY → direct evidence (policy, logs, config)
  SUPPORTING → indirect evidence (interviews)

---

SUB-STEP-5 — FILTER RELEVANT CHECKLIST ITEMS

Evaluate ONLY items where:
evidence_type ∈ expected_evidence_types

---

SUB-STEP-6 — EXTRACT CLAIMS AND CHECKPOINTS

For each relevant checklist item extract:
* claims: structured statements from evidence
* checkpoints: atomic facts aligned to requirement

Classify claim_type:
* DOCUMENTED
* OBSERVED
* ASSERTION

---

SUB-STEP-7 — DETECT SIGNALS

For each checklist item determine:
signal = SUPPORTS / CONTRADICTS / INSUFFICIENT

RULES:
SUPPORTS:
* evidence aligns with requirement
* satisfies pass_condition fully or partially

INSUFFICIENT:
* evidence exists but incomplete
* does not fully meet pass_condition

CONTRADICTS:
* evidence conflicts with requirement OR
* evidence conflicts with another statement within the same evidence

Examples:
* required quarterly, evidence shows annual → CONTRADICTS
* interview says yes, document shows no → CONTRADICTS
* internal inconsistency → CONTRADICTS

IMPORTANT:
* CONTRADICTS must only be used for clear logical conflict
* absence of evidence is NOT contradiction

---

SUB-STEP-8 — APPLY TEST LOGIC

Use:
* testing_method
* testing_approach
* evaluation_logic

STATUS RULES:
* PASS → pass_condition fully satisfied
* PARTIAL → partially satisfied or incomplete
* FAIL → fail_condition met

SPECIAL RULES:
1. INTERVIEW_RESPONSE:
   * strength = WEAK
   * cannot independently PASS HIGH weight items
   * at best → PARTIAL

2. PROCESS_TRACE:
   * must show full flow + execution
   * only flow → PARTIAL

3. SAMPLE TESTING:
   * evaluate: sample_size, exceptions_found, exception_rate, audit_period coverage

---

SUB-STEP-9 — EVIDENCE REFERENCE

Provide precise reference:
* section / clause / identifiable text

---

SUB-STEP-10 — CONFIDENCE

Assign:
HIGH → strong, clear evidence
MEDIUM → moderate clarity
LOW → weak / indirect

---

OUTPUT FORMAT (return exactly this structure):

{{
  "evidence_id": "{evidence_id}",
  "evidence_type": "",
  "admissibility": "",
  "admissibility_reason": "",
  "confidence": "",
  "evidence_meta": {{
    "strength": "",
    "role": "",
    "entity_name": "",
    "document_title": "",
    "approval_authority": "",
    "approval_date": "",
    "effective_date": ""
  }},
  "claims": [
    {{
      "checklist_id": "",
      "claim": "",
      "claim_type": "",
      "confidence": ""
    }}
  ],
  "checkpoints": [
    {{
      "checklist_id": "",
      "checkpoint": ""
    }}
  ],
  "item_signals": [
    {{
      "checklist_id": "",
      "signal": "",
      "basis": "",
      "confidence": ""
    }}
  ],
  "results": [
    {{
      "checklist_id": "",
      "status": "",
      "evidence_reference": "",
      "confidence": ""
    }}
  ],
  "sample_evaluation": {{
    "applicable": "YES/NO",
    "sample_size": null,
    "exception_rate": null,
    "within_audit_period": "YES/NO"
  }}
}}

STRICT CONSTRAINTS:
* Do NOT generate findings
* Do NOT conclude compliance
* Do NOT evaluate non-relevant checklist items
* Do NOT assume missing information
* All outputs must be structured and explicit"""


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
