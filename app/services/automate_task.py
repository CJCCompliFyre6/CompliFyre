

import os
import json
import hashlib
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Any

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError
from flask import current_app
from app import db

# Import your models (keep as explicit as you can in your real code)
from app.models.ai import *
from app.models.auditOrganization import *
from app.models.download import *
from app.models.organization import *

# Prompt templates and model response wrappers (unchanged)
from .prompt_templates.guidelines_prompt import *
from .prompt_templates.clasue_prompt import *
from .prompt_templates.compliance_activity import *
from .prompt_templates.test_procedure import *
from .model_response import *

logger = get_task_logger(__name__)




# ---------- Utility helpers ----------

def _safe_get_upload_folder() -> str:
    """
    Resolve upload folder safely when running inside Celery (no Flask app context guaranteed).
    Priority: ENV[UPLOAD_FOLDER] > Flask current_app.config > /tmp/uploads
    """
    path = os.getenv("UPLOAD_FOLDER")
    if not path:
        try:
            from flask import current_app
            path = current_app.config.get("UPLOAD_FOLDER")
        except Exception:
            path = None
    if not path:
        path = "/tmp/uploads"
    os.makedirs(path, exist_ok=True)
    return path


def _safe_vec_id(vec_info) -> str | None:
    """Support both object-like (has .id) and dict-like ({'id': ...}) vector info."""
    if vec_info is None:
        return None
    vid = getattr(vec_info, "id", None)
    if vid:
        return vid
    if isinstance(vec_info, dict):
        return vec_info.get("id")
    return None


def _as_dict(obj: Any) -> dict:
    """Convert pydantic model or dataclass-ish to dict; pass dicts through; else best-effort."""
    if obj is None:
        return {}
    # Pydantic v2
    if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
        try:
            return obj.model_dump()
        except Exception:
            pass
    
    if isinstance(obj, dict):
        return obj
    try:
        # Last resort shallow conversion (avoid dumping private attrs)
        return {k: getattr(obj, k) for k in dir(obj) if not k.startswith("_") and not callable(getattr(obj, k))}
    except Exception:
        return {"value": str(obj)}


def _as_json(obj: Any) -> str | None:
    """Return JSON string regardless of whether obj is string/pydantic/dict/list."""
    if obj is None:
        return None
    if isinstance(obj, (str, bytes)):
        return obj if isinstance(obj, str) else obj.decode("utf-8", "ignore")
    d = _as_dict(obj)
    try:
        return json.dumps(d, ensure_ascii=False)
    except Exception:
        try:
            return json.dumps(str(obj), ensure_ascii=False)
        except Exception:
            return None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Uniform getter for dicts or objects."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _ci_get(d: dict, key: str, default: Any = None) -> Any:
    """
    Case-insensitive getter for dicts produced by LLMs (keys may be 'Walkthrough' or 'walkthrough').
    Works for flat keys.
    """
    if not isinstance(d, dict):
        return default
    if key in d:
        return d[key]
    lk = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == lk:
            return v
    return default


@contextmanager
def session_scope():
    """Provide a short-lived transactional scope for DB operations (uses scoped session)."""
    try:
        yield db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    finally:
        db.session.remove()


# ---------- Main Task ----------

@shared_task(ignore_result=False)
def process_all_activities(file: str, file_content: bytes):
    logger.info("Starting process_all_activities")

    if not file:
        logger.error("No file provided")
        return {"status": "error", "message": "No file uploaded"}

    if not file_content:
        logger.error("Empty file content")
        return {"status": "error", "message": "Empty file"}

    try:
        # --- 1) Create vector store ---
        store_name = os.path.splitext(os.path.basename(file))[0]
        logger.info("Creating vector store: %s", store_name)
        vector_info = create_vector_store(store_name)
        vec_id = _safe_vec_id(vector_info)
        if not vec_id:
            logger.error("Vector store creation failed: %s", vector_info)
            return {"status": "error", "message": "Vector store creation failed"}

        # --- 2) Persist the uploaded file to disk (without requiring Flask app context) ---
        upload_dir = current_app.config.get("UPLOAD_FOLDER")
        file_hash = hashlib.sha256(file_content).hexdigest()
        filename = f"{os.urandom(8).hex()}.pdf"
        save_path = os.path.join(upload_dir, filename)
        with open(save_path, "wb") as f:
            f.write(file_content)
        logger.info("File saved: %s (sha256=%s, size=%d)", save_path, file_hash, len(file_content))

        # --- 3) Read departments early and then close session (avoid long idle DB session) ---
        departments = [
            {   
                "department_id": d.department_id,
                "department_name": d.department_name,
                "process": d.process_name,
                "sub_process": d.sub_process,
            }
            for d in OrganizationDepartments.query.all()
        ]
        logger.info("Loaded %d departments", len(departments))
        # remove any session state to be safe
        try:
            db.session.remove()
        except Exception:
            pass

        # --- 4) Upload file to vector store ---
        up_resp = upload_single_file(save_path, vec_id)
        if not isinstance(up_resp, dict) or up_resp.get("status") != "success":
            logger.error("Vector store upload failed: %s", up_resp)
            return {"status": "error", "message": "File upload to vector store failed"}

        # --- 5) Extract guidelines ---
        guideline_response = extract_structured_info(query=guideline_prompt_def(), vector_store_id=vec_id, schema=RegulatoryDocument)
        guidelines_result_json = None
        if guideline_response:
            # try:
                # Prefer pydantic v2 .model_dump_json()
            guidelines_result_json = json.loads(guideline_response.model_dump_json())
            # except Exception:
            #     # fallback to generic JSON
            #     guidelines_result_json = _as_json(guideline_response) or str(guideline_response)
            logger.info("Guidelines extracted")

        # --- 6) Extract clauses (requirements) ---
        clause_response = extract_structured_info(query=clause_prompt_def(), vector_store_id=vec_id, schema=ClauseJSON)
        logger.info("clause extracted %s", clause_response)
        clauses = []
        if clause_response:
            # model_dict = _as_dict(clause_response) or {}
            # reqs = model_dict.get("requirements") or []
            # clauses = reqs if isinstance(reqs, list) else []
            clauses = json.loads(clause_response.model_dump_json())['requirements']
            logger.info("Clause extraction returned %d items", len(clauses))
        else:
            logger.warning("Clause extraction returned no parsed output")

        # --- 7) Save File & Download & Guidelines in one short transaction and commit ---
        saved_file_id = None
        saved_download_id = None
        saved_guideline_id = None

        with session_scope() as session:
            file_record = File(
                hash=file_hash,
                path=save_path,
                size=len(file_content),
                data=guidelines_result_json,
                clause=clause_response.model_dump_json(),
                created_at=datetime.now(timezone.utc),
            )
            download_record = Download(
                url=save_path,
                status="completed",
                data=guidelines_result_json,
                clause=clause_response.model_dump_json(),
                file_hash=file_hash,
            )
            session.add_all([file_record, download_record])
            session.flush()

            saved_file_id = file_record.id
            saved_download_id = download_record.id

            if guidelines_result_json:
                g = Guidelines(
                    guideline_data=guidelines_result_json,
                    url_id=download_record.id,
                    file_id=file_record.id,
                )
                session.add(g)
                # guidelines_result_json
                session.flush()
                saved_guideline_id = g.id

            logger.info("Saved File(id=%s) and Download(id=%s) and Guideline(id=%s)",
                        saved_file_id, saved_download_id, saved_guideline_id)

        # Commit finished. Now process clauses in separate short transactions.
        # clauses = [clauses[]]
        if clauses and saved_guideline_id:
            for idx, clause in enumerate(clauses, start=1):
                try:
                    process_clause(clause, vec_id, departments, guideline_id=saved_guideline_id)
                    logger.info("Processed clause %d/%d", idx, len(clauses))
                except Exception as ce:
                    logger.exception("Error processing clause %s: %s", _get(clause, "clause_number"), ce)
        elif clauses and not saved_guideline_id:
            logger.warning("Clauses were extracted, but no Guideline record was created. Skipping clause processing.")

        logger.info("process_all_activities completed successfully")
        return {
            "status": "success",
            "message": "Processing completed",
            "clauses": len(clauses),
        }

    except SQLAlchemyError as e:
        logger.exception("Database error occurred")
        return {"status": "error", "message": "Database error", "details": str(e)}

    except Exception as e:
        logger.exception("Unexpected error in process_all_activities")
        return {"status": "error", "message": str(e)}


# ---------- Sub-steps ----------

def process_clause(clause_obj: Any, vec_id: str, department_list: list[dict], guideline_id: int):
    """
    clause_obj is dict-like (pydantic->dict) with keys: clause_number, clause_text, page_number.
    This function performs its DB writes in one short transaction, collects created ComplianceActivities IDs,
    then after the transaction exits it calls process_test_procedures for each created activity using raw IDs.
    """
    clause_number = _get(clause_obj, "clause_number") or _get(clause_obj, "clause_no") or "unknown"
    logger.info("Starting processing for clause number=%s", clause_number)
    clause_text = _get(clause_obj, "clause_text") or _get(clause_obj, "text") or ""
    page_number = _get(clause_obj, "page_number") or _get(clause_obj, "page") or None

    if not clause_text:
        logger.warning("Skipping clause with no text (number=%s)", clause_number)
        return

    # We'll accumulate (comp_id, clause_text, act_payload_json, vec_id) to process after commit
    comps_to_process = []

    with session_scope() as session:
        add_clause = Clauses(
            clause_no=clause_number,
            clause_text=clause_text,
            guideline_id=guideline_id
        )
        session.add(add_clause)
        session.flush()

        # store raw ID to avoid DetachedInstanceError later
        clause_id_val = add_clause.id
        logger.info("Saved Clause(id=%s, number=%s, page=%s)", clause_id_val, clause_number, page_number)

        # Extract compliance activities for this clause
        activity_response = extract_structured_info(
            query=compliance_prompt(clause_text, list(department_list)),
            vector_store_id=vec_id,
            schema=ComplianceRequirements
        )
        logger.info('New Activity %s',activity_response)

        if not activity_response:
            logger.info("No compliance activities for clause %s", clause_number)
            return

        parsed_dict = _as_dict(activity_response) or {}
        activities = parsed_dict.get("compliance_activities") or parsed_dict.get("activities") or []
        logger.info("Found %d compliance activities for clause %s", len(activities), clause_number)

        for act in activities:
            # Resolve department id safely (validate or create)
            raw_dept_id = None
            try:
                raw_dept_id = int(_get(act, "department_id", 0) or 0)
            except Exception:
                raw_dept_id = None

            dept_obj = None
            if raw_dept_id:
                dept_obj = session.query(OrganizationDepartments).filter_by(department_id=raw_dept_id).first()

            if not dept_obj:
                # Try to match by name in department_list (case-insensitive contains)
                dept_name_from_ai = _get(act, "relevant_departments") or _get(act, "department_name") or None
                if dept_name_from_ai:
                    ai_lower = dept_name_from_ai.strip().lower()
                    for d in (department_list or []):
                        dn = (d.get("department_name") or "").strip()
                        if dn:
                            dn_l = dn.lower()
                            if ai_lower in dn_l or dn_l in ai_lower:
                                dept_obj = session.query(OrganizationDepartments).filter_by(department_id=d["department_id"]).first()
                                if dept_obj:
                                    break

            if not dept_obj:
                # Last resort: create minimal department record to satisfy FK.
                # Change this behavior if you prefer to skip or mark as unknown.
                dept_to_create_name = _get(act, "relevant_departments") or "Unknown"
                dept_obj = OrganizationDepartments(department_name=dept_to_create_name)
                session.add(dept_obj)
                session.flush()

            relevant_departments_id_val = getattr(dept_obj, "department_id", None)

            comp = ComplianceActivities(
                clause_id=clause_id_val,
                relevant_departments_id=relevant_departments_id_val,
                relevant_departments=_get(act, "relevant_departments"),
                process=_get(act, "process_name"),
                sub_process=_get(act, "sub_process_name"),
                activity_id=_get(act, "activity_id"),
                activity_description=_get(act, "activity_description"),
                responsible_party=_get(act, "responsible_party"),
                frequency=_get(act, "frequency"),
                evidence_required=_get(act, "evidence_required"),
            )
            session.add(comp)
            session.flush()
            comp_id_val = comp.id
            logger.info("Saved ComplianceActivity(id=%s) for Clause(id=%s)", comp_id_val, clause_id_val)

            # schedule test procedure processing after we exit the transaction
            comps_to_process.append(
                (comp_id_val, clause_text, _as_json(act), vec_id)
            )

    # End with session_scope() -> commit done. Now process test procedures in independent transactions.
    for comp_id_val, clause_text_val, comp_payload_json, vec_id_val in comps_to_process:
        try:
            process_test_procedures(
                comp_id=comp_id_val,
                clause_text=clause_text_val,
                compliance_activity_payload=comp_payload_json,
                vec_id=vec_id_val
            )
        except Exception as te:
            logger.exception("Error in test procedures for comp(id=%s): %s", comp_id_val, te)


def process_test_procedures(comp_id: int, clause_text: str, compliance_activity_payload: str, vec_id: str):
    """
    Extracts test procedures and saves related records.
    Uses its own transactional scope. Accepts raw IDs only.
    """
    logger.info("Started Processing Activity comp_id=%s", comp_id)

    # Ask the model for control workpaper based on the clause text + activity JSON payload
    test_proc_response = extract_structured_info(
       query= test_procedure(clause_text, compliance_activity_payload),
        vector_store_id=vec_id,
        schema=ControlWorkpaper
    )

    if not test_proc_response:
        logger.info("No test procedure produced for comp_id=%s", comp_id)
        return

    # capture dict & json
    test_data_dict = _as_dict(test_proc_response) or {}
    test_data_json = _as_json(test_proc_response)

    with session_scope() as session:
        # Persist Test Procedure (raw JSON for traceability)
        activity_data = TestProcedures(activity_id=comp_id, data=test_data_json)
        session.add(activity_data)

        control = ControlActivity(
            activity_code=test_data_dict.get("activity_code"),
            activity_name=test_data_dict.get("activity_name"),
            activity_description=test_data_dict.get("activity_description"),
            objective=test_data_dict.get("objective"),
            owner=test_data_dict.get("owner"),
            control_type=test_data_dict.get("control_type"),
            frequency=test_data_dict.get("frequency"),
            sampling_guidance=test_data_dict.get("sampling_guidance"),
            auditor_observation=test_data_dict.get("auditor_observation"),
            findings=test_data_dict.get("findings"),
            impact=test_data_dict.get("impact"),
            severity=test_data_dict.get("severity"),
            recommendations=test_data_dict.get("recommendations"),
            reviewer_notes=test_data_dict.get("reviewer_notes"),
            explain_test_procedure=test_data_dict.get("explain_test_procedure"),
            compliance_activity_id=comp_id
        )
        session.add(control)
        session.flush()
        control_id_val = control.id

        # Normalize test_procedure payload keys (case-insensitive)
        test_steps_payload = test_data_dict.get("test_procedure") or test_data_dict.get("testProcedure") or {}
        # Build TestSteps using case-insensitive getter
        test_steps = TestSteps(
            walkthrough=_ci_get(test_steps_payload, "walkthrough"),
            sampling=_ci_get(test_steps_payload, "sampling"),
            control_id=control_id_val
        )
        session.add(test_steps)
        session.flush()
        test_steps_id_val = test_steps.id

        # Document reviews
        docs_list = test_steps_payload.get("review_of_documentation") or test_steps_payload.get("review_of_documents") or []
        if isinstance(docs_list, (str, bytes)):
            docs_list = [docs_list]
        for doc in (docs_list or []):
            session.add(DocumentReview(test_procedure_id=test_steps_id_val, document_name=doc))

        # Interviews
        interviews_data = test_steps_payload.get("interviews") or {}
        interview = Interview(test_procedure_id=test_steps_id_val)
        session.add(interview)
        session.flush()
        interview_id_val = interview.id
        for role in (interviews_data.get("roles") or []):
            session.add(InterviewRole(interview_id=interview_id_val, role=role))
        for question in (interviews_data.get("key_questions") or interviews_data.get("questions") or []):
            session.add(InterviewQuestion(interview_id=interview_id_val, question=question))

        # Evidence artifacts: normalize both list and dict shapes
        evidence_input = test_data_dict.get("evidences_artifacts_needed") or test_data_dict.get("evidences") or []

        if isinstance(evidence_input, dict):
            iter_evidence = ((k, v if isinstance(v, list) else [v]) for k, v in evidence_input.items())
        elif isinstance(evidence_input, list):
            def _yield_from_list(lst):
                for entry in lst:
                    if not entry:
                        continue
                    if isinstance(entry, dict):
                        cat = entry.get("category") or entry.get("name") or "Unknown"
                        items = entry.get("items") or entry.get("items_list") or []
                        yield (cat, items if isinstance(items, list) else [items])
                    else:
                        yield ("Unknown", [str(entry)])
            iter_evidence = _yield_from_list(evidence_input)
        else:
            iter_evidence = []

        for category, items in iter_evidence:
            category = (category or "Unknown").strip()
            for item in (items or []):
                artifact = (
                    session.query(EvidenceArtifact)
                    .filter_by(category=category, item=item)
                    .first()
                )
                if not artifact:
                    artifact = EvidenceArtifact(category=category, item=item)
                    session.add(artifact)
                    session.flush()
                # append relationship using same session
                control.evidences.append(artifact)

        logger.info("Activity processing completed for comp_id=%s (control_id=%s)", comp_id, control_id_val)
