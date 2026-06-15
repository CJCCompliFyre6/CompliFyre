import os
import json
import hashlib
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Any
import fitz  # PyMuPDF
from openai import OpenAI
import redis
import time

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload
from flask import current_app
from app import db
from config import settings

# Aapke models import karein
from app.models.ai import *
from app.models.auditOrganization import *
from app.models.download import *
from app.models.organization import *
from app.models.task_status import TaskStatus
from app.utils.extract_clause_helper import *

# Aapke prompt templates aur model response functions import karein
from .prompt_templates.guidelines_prompt import *
from .prompt_templates.clasue_prompt import *
from .prompt_templates.compliance_activity import *
from .prompt_templates.test_procedure import *
from .model_response import (
    create_vector_store,
    upload_single_file,
    extract_structured_info,
)
from app.models.project_instance_models import *

logger = get_task_logger(__name__)


# ---------- Utility Helpers ----------


def _safe_get_upload_folder() -> str:
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
    if vec_info is None:
        return None
    vid = getattr(vec_info, "id", None)
    if vid:
        return vid
    if isinstance(vec_info, dict):
        return vec_info.get("id")
    return None


def _as_dict(obj: Any) -> dict:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if isinstance(obj, dict):
        return obj
    try:
        return {
            k: getattr(obj, k)
            for k in dir(obj)
            if not k.startswith("_") and not callable(getattr(obj, k))
        }
    except Exception:
        return {"value": str(obj)}


def _as_json(obj: Any) -> str | None:
    if obj is None:
        return None
    if isinstance(obj, (str, bytes)):
        return obj if isinstance(obj, str) else obj.decode("utf-8", "ignore")
    d = _as_dict(obj)
    try:
        return json.dumps(d, ensure_ascii=False)
    except Exception:
        return None


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _ci_get(d: dict, key: str, default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    if key in d:
        return d[key]
    lk = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == lk:
            return v
    return default


def _get_dynamic_chunk_size(total_pages: int) -> int:
    if total_pages <= 10:
        return 10
    if total_pages <= 50:
        return 8
    return 10


def clean_markdown_text(text: str) -> str:
    """
    Remove common Markdown formatting from text so stored summaries are plain text.
    Keeps the visible content and strips code fences, backticks, headings, emphasis,
    strikethrough and converts links to their label.
    """
    if not text:
        return ""
    try:
        import re

        s = str(text)
        # Remove fenced code blocks (```...```)
        s = re.sub(r"```[\s\S]*?```", "", s)
        # Remove inline code backticks
        s = re.sub(r"`+", "", s)
        # Remove markdown headings like #, ##, etc.
        s = re.sub(r"(?m)^\s*#{1,6}\s*", "", s)
        # Convert links [text](url) -> text
        s = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", s)
        # Remove bold/italic/underline/strikethrough markers but keep content
        s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
        s = re.sub(r"\*(.*?)\*", r"\1", s)
        s = re.sub(r"__(.*?)__", r"\1", s)
        s = re.sub(r"_(.*?)_", r"\1", s)
        s = re.sub(r"~~(.*?)~~", r"\1", s)
        # Collapse multiple blank lines and trim
        s = re.sub(r"\r\n", "\n", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()
    except Exception:
        return str(text)


@contextmanager
def session_scope():
    try:
        yield db.session
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


@shared_task(bind=True)
def generate_consolidated_test_procedure(self, clause_id: int):
    """Generate AI-powered consolidated test procedure summary"""
    logger.info(f"Generating consolidated test procedure for clause_id={clause_id}")

    try:
        with session_scope() as session:
            # CORRECT QUERY: Get compliance activities for this PROJECT clause
            compliance_activities = (
                session.query(ProjectComplianceActivity)
                .filter(
                    ProjectComplianceActivity.project_clause_id == clause_id,
                    ProjectComplianceActivity.applicability == True,
                )
                .all()
            )

            logger.info(
                f"DEBUG: Found {len(compliance_activities)} APPLICABLE compliance activities"
            )

            if not compliance_activities:
                logger.info(
                    f"No compliance activities found for project_clause_id={clause_id}"
                )
                return {
                    "status": "success",
                    "message": "No compliance activities found",
                    "clause_id": clause_id,
                }

            # Get control activities for these compliance activities
            compliance_activity_ids = [ca.id for ca in compliance_activities]

            clause_activities = (
                session.query(ProjectControlActivity)
                .filter(
                    ProjectControlActivity.project_compliance_activity_id.in_(
                        compliance_activity_ids
                    )
                )
                .options(
                    joinedload(ProjectControlActivity.project_test_procedure),
                    joinedload(ProjectControlActivity.project_compliance_activity),
                )
                .all()
            )

            if not clause_activities:
                logger.info(
                    f"No control activities found for project_clause_id={clause_id}"
                )
                return {
                    "status": "success",
                    "message": "No control activities found for consolidation",
                    "clause_id": clause_id,
                }

            # Prepare test procedure data for AI processing
            test_procedures_data = {
                "clause_id": clause_id,
                "total_activities": len(clause_activities),
                "activities": [],
            }

            for activity in clause_activities:
                activity_data = {
                    "activity_code": activity.activity_code,
                    "activity_name": activity.activity_name,
                    "control_type": activity.control_type,
                    "frequency": activity.frequency,
                    "severity": activity.severity,
                }

                if activity.project_test_procedure:
                    test_procedure = activity.project_test_procedure
                    activity_data.update(
                        {
                            "walkthrough": test_procedure.walkthrough or "",
                            "sampling": test_procedure.sampling or "",
                            "additional_walkthrough": test_procedure.additional_walkthrough
                            or "",
                            "additional_sampling": test_procedure.additional_sampling
                            or "",
                            "has_test_procedure": True,
                        }
                    )
                else:
                    activity_data.update({"has_test_procedure": False})

                test_procedures_data["activities"].append(activity_data)

            logger.info(
                f"Prepared {len(test_procedures_data['activities'])} activities for AI processing"
            )

            # Generate AI summary
            ai_response = extract_structured_info(
                query=consolidated_test_procedure_prompt(test_procedures_data),
                vector_store_id=None,
                schema=ConsolidatedTestProcedureJSON,
            )

            if ai_response is not None:
                # Save the consolidated summary - UPDATE EXISTING INSTEAD OF CREATE NEW
                summary_data = {
                    "consolidated_summary": ai_response.consolidated_summary,
                    "key_testing_areas": ai_response.key_testing_areas,
                    "walkthrough_approach": ai_response.walkthrough_approach,
                    "sampling_methodology": ai_response.sampling_methodology,
                    "generated_at": datetime.utcnow().isoformat(),
                    "activities_processed": len(clause_activities),
                    "task_completed": True,  # Task completion flag
                    "task_id": str(self.request.id),  # task ID for tracking
                }

                # Check if summary already exists for this clause
                existing_summary = (
                    session.query(ConsolidatedTestSummary)
                    .filter_by(clause_id=clause_id)
                    .first()
                )

                if existing_summary:
                    # UPDATE existing record
                    logger.info(
                        f"DEBUG: Updating existing test procedure summary for clause_id={clause_id}"
                    )
                    existing_summary.consolidated_summary = json.dumps(summary_data)
                    existing_summary.updated_at = datetime.utcnow()
                else:
                    # CREATE new record only if it doesn't exist
                    logger.info(
                        f"DEBUG: Creating new test procedure summary for clause_id={clause_id}"
                    )
                    consolidated_summary = ConsolidatedTestSummary(
                        clause_id=clause_id,
                        consolidated_summary=json.dumps(summary_data),
                    )
                    session.add(consolidated_summary)

                session.commit()

                logger.info(
                    f"Successfully saved consolidated test summary for project_clause_id={clause_id}"
                )

                return {
                    "status": "success",
                    "clause_id": clause_id,
                    "summary_generated": True,
                    "activities_processed": len(clause_activities),
                    "action": "updated" if existing_summary else "created",
                }
            else:
                logger.error("AI response was empty or invalid")
                self.update_state(
                    state="FAILURE",
                    meta={"exc_message": "AI response was empty or invalid"},
                )
                return {"status": "failure", "message": "AI response was empty"}

    except Exception as e:
        logger.exception("Consolidated test procedure generation failed")
        self.update_state(
            state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )
        raise


@shared_task(bind=True)
def generate_consolidated_observation_summary(self, clause_id: int):
    """Generate AI-powered consolidated observation summary"""
    logger.info(
        f"DEBUG: Starting consolidated observation task for clause_id={clause_id}"
    )

    try:
        with session_scope() as session:
            # Get compliance activities for this PROJECT clause
            compliance_activities = (
                session.query(ProjectComplianceActivity)
                .filter(
                    ProjectComplianceActivity.project_clause_id == clause_id,
                    ProjectComplianceActivity.applicability == True,
                )
                .all()
            )

            logger.info(
                f"DEBUG: Found {len(compliance_activities)} APPLICABLE compliance activities"
            )

            if not compliance_activities:
                logger.info(
                    f"No compliance activities found for project_clause_id={clause_id}"
                )
                return {
                    "status": "success",
                    "message": "No compliance activities found",
                    "clause_id": clause_id,
                }

            # Get control activities for these compliance activities
            compliance_activity_ids = [ca.id for ca in compliance_activities]

            clause_activities = (
                session.query(ProjectControlActivity)
                .filter(
                    ProjectControlActivity.project_compliance_activity_id.in_(
                        compliance_activity_ids
                    )
                )
                .options(joinedload(ProjectControlActivity.project_compliance_activity))
                .all()
            )

            logger.info(f"DEBUG: Found {len(clause_activities)} control activities")

            if not clause_activities:
                logger.info(
                    f"No control activities found for project_clause_id={clause_id}"
                )
                return {
                    "status": "success",
                    "message": "No control activities found for consolidation",
                    "clause_id": clause_id,
                }

            # Prepare observation data for AI processing
            observations_data = {
                "clause_id": clause_id,
                "total_activities": len(clause_activities),
                "activities": [],
            }

            activities_with_observations = 0
            for activity in clause_activities:
                auditor_observation = (
                    activity.auditor_observation or "No observation provided"
                )
                if auditor_observation != "No observation provided":
                    activities_with_observations += 1

                activity_data = {
                    "activity_code": activity.activity_code,
                    "activity_name": activity.activity_name,
                    "control_type": activity.control_type,
                    "compliant_status": activity.compliant_status,
                    "severity": activity.severity,
                    "auditor_observation": auditor_observation,
                    "findings": activity.findings or "No findings",
                    "recommendations": activity.recommendations or "No recommendations",
                }

                observations_data["activities"].append(activity_data)

            logger.info(
                f"DEBUG: {activities_with_observations} activities have observations"
            )
            logger.info(
                f"DEBUG: Prepared {len(observations_data['activities'])} activities for AI processing"
            )

            # Generate AI summary
            logger.info("DEBUG: Calling AI extraction...")
            ai_response = extract_structured_info(
                query=consolidated_observation_prompt(observations_data),
                vector_store_id=None,
                schema=ConsolidatedObservationJSON,
            )

            if ai_response is not None:
                logger.info("DEBUG: AI response received successfully")

                # Save the consolidated observation summary - UPDATE EXISTING INSTEAD OF CREATE NEW
                summary_data = {
                    "consolidated_summary": ai_response.consolidated_summary,
                    "key_observations": ai_response.key_observations,
                    "common_patterns": ai_response.common_patterns,
                    "risk_areas": ai_response.risk_areas,
                    "improvement_opportunities": ai_response.improvement_opportunities,
                    "generated_at": datetime.utcnow().isoformat(),
                    "activities_processed": len(clause_activities),
                    "task_completed": True,  # Task completion flag
                    "task_id": str(self.request.id),  # task ID for tracking
                }

                # Check if summary already exists for this clause
                existing_summary = (
                    session.query(ConsolidatedObservationSummary)
                    .filter_by(clause_id=clause_id)
                    .first()
                )

                if existing_summary:
                    # UPDATE existing record
                    logger.info(
                        f"DEBUG: Updating existing observation summary for clause_id={clause_id}"
                    )
                    existing_summary.consolidated_observation = json.dumps(summary_data)
                    existing_summary.updated_at = datetime.utcnow()
                else:
                    # CREATE new record only if it doesn't exist
                    logger.info(
                        f"DEBUG: Creating new observation summary for clause_id={clause_id}"
                    )
                    consolidated_observation = ConsolidatedObservationSummary(
                        clause_id=clause_id,
                        consolidated_observation=json.dumps(summary_data),
                    )
                    session.add(consolidated_observation)

                session.commit()

                logger.info(
                    f"DEBUG: Successfully saved consolidated observation summary for project_clause_id={clause_id}"
                )

                return {
                    "status": "success",
                    "clause_id": clause_id,
                    "summary_generated": True,
                    "activities_processed": len(clause_activities),
                    "action": "updated" if existing_summary else "created",
                }
            else:
                logger.error("AI response was empty or invalid")
                self.update_state(
                    state="FAILURE",
                    meta={"exc_message": "AI response was empty or invalid"},
                )
                return {"status": "failure", "message": "AI response was empty"}

    except Exception as e:
        logger.exception("Consolidated observation summary generation failed")
        self.update_state(
            state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )
        raise


@shared_task(bind=True)
def generate_consolidated_findings_summary(self, clause_id: int):
    """Generate AI-powered consolidated findings summary"""
    logger.info(f"DEBUG: Starting consolidated findings task for clause_id={clause_id}")

    try:
        with session_scope() as session:
            # Get compliance activities for this PROJECT clause
            compliance_activities = (
                session.query(ProjectComplianceActivity)
                .filter(
                    ProjectComplianceActivity.project_clause_id == clause_id,
                    ProjectComplianceActivity.applicability == True,
                )
                .all()
            )

            logger.info(
                f"DEBUG: Found {len(compliance_activities)} APPLICABLE compliance activities"
            )

            if not compliance_activities:
                logger.info(
                    f"No compliance activities found for project_clause_id={clause_id}"
                )
                return {
                    "status": "success",
                    "message": "No compliance activities found",
                    "clause_id": clause_id,
                }

            # Get control activities for these compliance activities
            compliance_activity_ids = [ca.id for ca in compliance_activities]

            clause_activities = (
                session.query(ProjectControlActivity)
                .filter(
                    ProjectControlActivity.project_compliance_activity_id.in_(
                        compliance_activity_ids
                    )
                )
                .options(joinedload(ProjectControlActivity.project_compliance_activity))
                .all()
            )

            logger.info(f"DEBUG: Found {len(clause_activities)} control activities")

            if not clause_activities:
                logger.info(
                    f"No control activities found for project_clause_id={clause_id}"
                )
                return {
                    "status": "success",
                    "message": "No control activities found for consolidation",
                    "clause_id": clause_id,
                }

            # Prepare findings data for AI processing
            findings_data = {
                "clause_id": clause_id,
                "total_activities": len(clause_activities),
                "activities": [],
            }

            activities_with_findings = 0
            for activity in clause_activities:
                findings = activity.findings or "No findings provided"
                if findings != "No findings provided":
                    activities_with_findings += 1

                activity_data = {
                    "activity_code": activity.activity_code,
                    "activity_name": activity.activity_name,
                    "control_type": activity.control_type,
                    "compliant_status": activity.compliant_status,
                    "severity": activity.severity,
                    "findings": findings,
                    "auditor_observation": activity.auditor_observation
                    or "No observation",
                    "recommendations": activity.recommendations or "No recommendations",
                }

                findings_data["activities"].append(activity_data)

            logger.info(f"DEBUG: {activities_with_findings} activities have findings")
            logger.info(
                f"DEBUG: Prepared {len(findings_data['activities'])} activities for AI processing"
            )

            # Generate AI summary
            logger.info("DEBUG: Calling AI extraction for findings...")
            ai_response = extract_structured_info(
                query=consolidated_findings_prompt(findings_data),
                vector_store_id=None,
                schema=ConsolidatedFindingsJSON,
            )

            if ai_response is not None:
                logger.info("DEBUG: AI response for findings received successfully")

                # Save the consolidated findings summary - UPDATE EXISTING INSTEAD OF CREATE NEW
                summary_data = {
                    "consolidated_summary": ai_response.consolidated_summary,
                    "generated_at": datetime.utcnow().isoformat(),
                    "activities_processed": len(clause_activities),
                    "task_completed": True,  # Task completion flag
                    "task_id": str(self.request.id),  #  task ID for tracking
                }

                # Check if summary already exists for this clause
                existing_summary = (
                    session.query(ConsolidatedFindingsSummary)
                    .filter_by(clause_id=clause_id)
                    .first()
                )

                if existing_summary:
                    # UPDATE existing record
                    logger.info(
                        f"DEBUG: Updating existing findings summary for clause_id={clause_id}"
                    )
                    existing_summary.consolidated_findings = json.dumps(summary_data)
                    existing_summary.updated_at = datetime.utcnow()
                else:
                    # CREATE new record only if it doesn't exist
                    logger.info(
                        f"DEBUG: Creating new findings summary for clause_id={clause_id}"
                    )
                    consolidated_findings = ConsolidatedFindingsSummary(
                        clause_id=clause_id,
                        consolidated_findings=json.dumps(summary_data),
                    )
                    session.add(consolidated_findings)

                session.commit()

                logger.info(
                    f"DEBUG: Successfully saved consolidated findings summary for project_clause_id={clause_id}"
                )

                return {
                    "status": "success",
                    "clause_id": clause_id,
                    "summary_generated": True,
                    "activities_processed": len(clause_activities),
                    "action": "updated" if existing_summary else "created",
                }
            else:
                logger.error("AI response for findings was empty or invalid")
                self.update_state(
                    state="FAILURE",
                    meta={
                        "exc_message": "AI response for findings was empty or invalid"
                    },
                )
                return {
                    "status": "failure",
                    "message": "AI response for findings was empty",
                }

    except Exception as e:
        logger.exception("Consolidated findings summary generation failed")
        self.update_state(
            state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )
        raise


@shared_task(bind=True)
def generate_consolidated_recommendations_summary(self, clause_id: int):
    """Generate AI-powered consolidated recommendations summary"""
    logger.info(
        f"🚀 DEBUG: Starting consolidated recommendations task for clause_id={clause_id}"
    )

    try:
        with session_scope() as session:
            # Get compliance activities for this PROJECT clause
            compliance_activities = (
                session.query(ProjectComplianceActivity)
                .filter(
                    ProjectComplianceActivity.project_clause_id == clause_id,
                    ProjectComplianceActivity.applicability == True,
                )
                .all()
            )

            logger.info(
                f"📊 DEBUG: Found {len(compliance_activities)} APPLICABLE compliance activities"
            )

            if not compliance_activities:
                logger.info(
                    f"❌ No compliance activities found for project_clause_id={clause_id}"
                )
                return {
                    "status": "success",
                    "message": "No compliance activities found",
                    "clause_id": clause_id,
                }

            # Get control activities for these compliance activities
            compliance_activity_ids = [ca.id for ca in compliance_activities]

            clause_activities = (
                session.query(ProjectControlActivity)
                .filter(
                    ProjectControlActivity.project_compliance_activity_id.in_(
                        compliance_activity_ids
                    )
                )
                .all()
            )

            logger.info(f"🔍 DEBUG: Found {len(clause_activities)} control activities")

            if not clause_activities:
                logger.info(
                    f"❌ No control activities found for project_clause_id={clause_id}"
                )
                return {
                    "status": "success",
                    "message": "No control activities found for consolidation",
                    "clause_id": clause_id,
                }

            # Prepare recommendations data for AI processing
            recommendations_data = {
                "clause_id": clause_id,
                "total_activities": len(clause_activities),
                "activities": [],
            }

            activities_with_recommendations = 0
            for activity in clause_activities:
                recommendations = (
                    activity.recommendations or "No recommendations provided"
                )
                if recommendations and recommendations != "No recommendations provided":
                    activities_with_recommendations += 1

                activity_data = {
                    "activity_code": activity.activity_code,
                    "activity_name": activity.activity_name,
                    "control_type": activity.control_type,
                    "compliant_status": activity.compliant_status,
                    "severity": activity.severity,
                    "findings": activity.findings or "No findings",
                    "recommendations": recommendations,
                    "auditor_observation": activity.auditor_observation
                    or "No observation",
                }

                recommendations_data["activities"].append(activity_data)

            logger.info(
                f"✅ DEBUG: {activities_with_recommendations} activities have recommendations"
            )
            logger.info(
                f"📋 DEBUG: Prepared {len(recommendations_data['activities'])} activities for AI processing"
            )

            # Generate AI summary
            logger.info("🤖 DEBUG: Calling AI extraction for recommendations...")

            ai_response = extract_structured_info(
                query=consolidated_recommendations_prompt(recommendations_data),
                vector_store_id=None,
                schema=ConsolidatedRecommendationsJSON,
            )

            if ai_response is not None:
                logger.info(
                    "✅ DEBUG: AI response for recommendations received successfully"
                )

                # Clean the text - Remove any markdown formatting
                cleaned_summary = []
                for bullet_point in ai_response.consolidated_summary:
                    cleaned_point = clean_markdown_text(bullet_point)
                    cleaned_summary.append(cleaned_point)

                # Save the consolidated recommendations summary
                summary_data = {
                    "consolidated_summary": cleaned_summary,
                    "generated_at": datetime.utcnow().isoformat(),
                    "activities_processed": len(clause_activities),
                }

                # Check if summary already exists for this clause
                existing_summary = (
                    session.query(ConsolidatedRecommendationsSummary)
                    .filter_by(clause_id=clause_id)
                    .first()
                )

                if existing_summary:
                    # UPDATE existing record
                    logger.info(
                        f"🔄 DEBUG: Updating existing recommendations summary for clause_id={clause_id}"
                    )
                    existing_summary.consolidated_recommendations = json.dumps(
                        summary_data
                    )
                    existing_summary.updated_at = datetime.utcnow()
                else:
                    # CREATE new record only if it doesn't exist
                    logger.info(
                        f"🆕 DEBUG: Creating new recommendations summary for clause_id={clause_id}"
                    )
                    consolidated_recommendations = ConsolidatedRecommendationsSummary(
                        clause_id=clause_id,
                        consolidated_recommendations=json.dumps(summary_data),
                    )
                    session.add(consolidated_recommendations)

                session.commit()

                logger.info(
                    f"💾 DEBUG: Successfully saved consolidated recommendations summary for project_clause_id={clause_id}"
                )

                return {
                    "status": "success",
                    "clause_id": clause_id,
                    "summary_generated": True,
                    "activities_processed": len(clause_activities),
                    "action": "updated" if existing_summary else "created",
                }
            else:
                logger.error("❌ AI response for recommendations was empty or invalid")
                self.update_state(
                    state="FAILURE",
                    meta={
                        "exc_message": "AI response for recommendations was empty or invalid"
                    },
                )
                return {
                    "status": "failure",
                    "message": "AI response for recommendations was empty",
                }

    except Exception as e:
        logger.exception("❌ Consolidated recommendations summary generation failed")
        self.update_state(
            state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )
        raise


def extract_text_from_pdf_page_by_page(file_path):
    """Extract text from PDF page by page with header/footer removal."""
    import re as _re
    try:
        with fitz.open(file_path) as doc:
            num_pages = doc.page_count
            for page_num in range(num_pages):
                page = doc[page_num]
                page_text = page.get_text()
                # Remove headers and footers
                lines = page_text.split("\n")
                cleaned_lines = []
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    # Skip standalone page numbers (footer)
                    if _re.match(r"^\d{1,4}$", stripped):
                        continue
                    # Skip common header patterns
                    if stripped in ("GAZETTE OF INDIA", "EXTRAORDINARY", "PUBLISHED BY AUTHORITY"):
                        continue
                    # Skip footnote lines (Inserted/Substituted/Omitted by...)
                    if _re.match(r"^\d+\s+(Inserted|Substituted|Omitted|Added).+by", stripped, _re.IGNORECASE):
                        continue
                    if _re.match(r"^\d+\s+Prior to the", stripped, _re.IGNORECASE):
                        continue
                    cleaned_lines.append(line)
                clean_text = "\n".join(cleaned_lines)
                # Strip inline footnote references: 600[text] → text
                clean_text = _re.sub(r'\d+\[([^\]]+)\]', r'\1', clean_text)
                # Strip standalone superscript numbers between words: word1 234 word2 → word1 word2
                clean_text = _re.sub(r'(?<=\w)\s+\d+(?=\s+[a-z\(\[])', ' ', clean_text)
                # Strip footnote numbers at start of clause text like: 3[(ia)...] → [(ia)...]
                clean_text = _re.sub(r'^\d+(?=\[)', '', clean_text, flags=_re.MULTILINE)
                yield page_num + 1, clean_text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        raise


def get_llm_service():
    """Get OpenAI client"""
    try:
        api_key = os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found")

        client = OpenAI(api_key=api_key)
        return client
    except Exception as e:
        logger.error(f"Error initializing OpenAI client: {e}")
        raise


# Add Redis connection for progress tracking
def get_redis_connection(max_retries=3, retry_delay=1):
    """Get Redis connection with retry logic."""
    for attempt in range(max_retries):
        try:
            redis_conn = redis.Redis(
                host=current_app.config.get("REDIS_HOST", "localhost"),
                port=current_app.config.get("REDIS_PORT", 6379),
                password=current_app.config.get("REDIS_PASSWORD"),
                db=current_app.config.get("CELERY_REDIS_DB", 0),
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
                health_check_interval=30,
            )

            # Test connection
            redis_conn.ping()
            current_app.logger.info("✅ Redis connection successful")
            return redis_conn

        except redis.ConnectionError as e:
            current_app.logger.warning(
                f"Redis connection attempt {attempt + 1} failed: {e}"
            )
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            raise
        except Exception as e:
            current_app.logger.error(f"Unexpected Redis error: {e}")
            raise


def debug_redis_connection():
    """Debug Redis connection with detailed logging."""
    try:
        redis_conn = get_redis_connection()

        # Test basic operations
        test_key = f"redis_test_{int(time.time())}"
        redis_conn.setex(test_key, 10, "test_value")
        value = redis_conn.get(test_key)
        redis_conn.delete(test_key)

        # Test pub/sub capability (for SSE)
        pubsub_test = redis_conn.pubsub()
        pubsub_test.close()

        current_app.logger.info("✅ Redis debug: All tests passed")
        return {
            "status": "SUCCESS",
            "message": "Redis connection is working correctly",
            "host": current_app.config.get("REDIS_HOST", "localhost"),
            "port": current_app.config.get("REDIS_PORT", 6379),
            "db": current_app.config.get("CELERY_REDIS_DB", 0),
        }

    except Exception as e:
        current_app.logger.error(f"❌ Redis debug failed: {str(e)}")
        return {
            "status": "ERROR",
            "message": f"Redis connection failed: {str(e)}",
            "host": current_app.config.get("REDIS_HOST", "localhost"),
            "port": current_app.config.get("REDIS_PORT", 6379),
            "db": current_app.config.get("CELERY_REDIS_DB", 0),
        }


def update_progress(guideline_id, status, progress, message, clauses_extracted=0):
    """Update progress in Redis for SSE streaming"""
    try:
        redis_conn = get_redis_connection()
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "clauses_extracted": clauses_extracted,
        }
        redis_conn.setex(
            f"clause_progress:{guideline_id}", 300, json.dumps(progress_data)
        )  # 5 min expiry
    except Exception as e:
        logger.error(f"Error updating progress: {e}")


def update_guideline_progress(task_id, status, progress, message, guideline_id=None):
    """Update progress for guideline extraction tasks in Redis"""
    try:
        redis_conn = get_redis_connection()
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "guideline_id": guideline_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),  # Add timestamp
        }
        redis_conn.setex(
            f"guideline_progress:{task_id}", 300, json.dumps(progress_data)
        )  # 5 min expiry
        logger.info(
            f"Guideline progress updated - Task: {task_id}, Status: {status}, Progress: {progress}%"
        )
    except Exception as e:
        logger.error(f"Error updating guideline progress: {e}")


def update_compliance_progress(
    task_id,
    status,
    progress,
    message,
    activities_processed=0,
    total_clauses=0,
    current_clause_id=None,
):
    """
    Update progress for compliance activities extraction
    """
    progress_data = {
        "status": status,
        "progress": progress,
        "message": message,
        "activities_processed": activities_processed,
        "total_clauses": total_clauses,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if current_clause_id:
        progress_data["current_clause_id"] = current_clause_id

    # Store progress in Redis or your preferred cache
    try:
        redis_conn = get_redis_connection()
        redis_conn.setex(
            f"compliance_progress:{task_id}", 3600, json.dumps(progress_data)
        )
    except Exception as e:
        logger.error(f"Error updating compliance progress: {e}")

    # Also update for SSE if needed
    return progress_data


def update_evidence_progress(task_id, status, progress, message, guideline_id=None):
    """Update progress for evidence consolidation tasks in Redis."""
    try:
        redis_conn = get_redis_connection()
        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "guideline_id": guideline_id,
            "timestamp": time.time(),
            "task_id": task_id,
        }

        # Store with longer expiry for debugging
        redis_conn.setex(
            f"evidence_progress:{task_id}",
            3600,  # 1 hour for debugging
            json.dumps(progress_data),
        )

        current_app.logger.info(
            f"Progress updated - Task: {task_id}, Status: {status}, Progress: {progress}%"
        )
        return True

    except Exception as e:
        current_app.logger.error(f"Error updating evidence progress: {e}")
        return False


def extract_clauses_with_openai(document_text, guideline_id, page_range):
    """Extract clauses using OpenAI - adapted from app.py"""
    try:
        client = get_llm_service()

        text_to_process = document_text[:500000]  # Limit text length
        logger.info(
            f"Preparing AI prompt for text chunk size: {len(text_to_process)} for guideline {guideline_id}"
        )

        # Get the prompt
        extraction_prompt = clause_prompt_def(page_range)

        full_prompt = f"{extraction_prompt}\n\n--- DOCUMENT TEXT START ---\n{text_to_process}\n--- DOCUMENT TEXT END ---"

        logger.info(
            f"Sending request to OpenAI for guideline {guideline_id}, page range: {page_range}"
        )

        # FIXED: Use the correct method name - chat.completions.create()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": full_prompt},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        response_content = response.choices[0].message.content

        # Parse the response - same logic as app.py
        json_string = response_content.strip()
        match = re.search(r"```json\s*([\s\S]*?)\s*```", response_content)
        if match:
            json_string = match.group(1).strip()
        elif not json_string.startswith("{"):
            try:
                start_index = json_string.index("{")
                json_string = json_string[start_index:]
            except ValueError:
                pass

        try:
            result_json = json.loads(json_string)
            logger.info(
                f"Successfully parsed JSON response for guideline {guideline_id}"
            )
            return result_json, {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        except json.JSONDecodeError as jde:
            logger.error(f"JSON Decode Error for guideline {guideline_id}: {jde}")
            logger.error(f"Content received from OpenAI: '{response_content[:500]}...'")
            raise Exception(
                f"Failed to parse JSON response. Model output was invalid."
            ) from jde

    except Exception as e:
        logger.error(
            f"OpenAI API Error during clause extraction for guideline {guideline_id}: {e}"
        )
        raise


# ---------- Step 0: Consolidate evidence ----------
@shared_task(bind=True)
def consolidate_evidence_task(self, guideline_id: int, user_id: int = None):
    """Celery task to consolidate evidence for a guideline with robust progress tracking."""
    task_id = self.request.id
    
    # Initial setup and logging
    logger.info(f"🔍 Starting evidence consolidation task {task_id} for guideline {guideline_id}")
    
    try:
        # Import required modules inside function to avoid circular imports
        from app.routes.audit.view import (
            process_clauses_chunk,
            merge_evidence_groups,
            create_fallback_evidence,
        )
        from app.models import Guidelines, ComplifyreConsolidatedEvidence, db
        import time

        # Step 1: Test Redis connection and initialize progress
        logger.info("Testing Redis connection...")
        if not update_evidence_progress(task_id, "STARTING", 0, "Initializing evidence consolidation task..."):
            raise Exception("Failed to connect to Redis for progress tracking")
        
        logger.info("✅ Redis connection successful")

        # Step 2: Fetch guideline data
        update_evidence_progress(task_id, "PROCESSING", 5, "Fetching guideline information...")
        logger.info(f"Fetching guideline {guideline_id}")
        
        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            raise ValueError(f"Guideline with ID {guideline_id} not found")

        # Step 3: Get all clauses
        update_evidence_progress(task_id, "PROCESSING", 10, "Retrieving clauses...")
        all_clauses = guideline.clauses
        total_clauses = len(all_clauses)

        if total_clauses == 0:
            raise ValueError("No clauses found for this guideline")

        logger.info(f"Found {total_clauses} clauses for guideline {guideline_id}")

        # Step 4: Prepare for chunk processing
        CHUNK_SIZE = 5
        all_consolidated_evidence = []
        chunks_processed = 0
        total_chunks = (total_clauses + CHUNK_SIZE - 1) // CHUNK_SIZE

        update_evidence_progress(
            task_id, 
            "PROCESSING", 
            15, 
            f"Preparing to process {total_clauses} clauses in {total_chunks} chunks..."
        )

        logger.info(f"📦 Processing {total_clauses} clauses in {total_chunks} chunks")

        # Step 5: Process clauses in chunks
        for chunk_start in range(0, total_clauses, CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, total_clauses)
            chunk_clauses = all_clauses[chunk_start:chunk_end]
            chunk_number = chunk_start // CHUNK_SIZE + 1
            chunks_processed += 1

            # Calculate progress (15% to 80% for chunk processing)
            base_progress = 15
            progress_per_chunk = 65 / total_chunks
            current_progress = base_progress + ((chunk_number - 1) * progress_per_chunk)

            # Update progress at start of chunk
            update_evidence_progress(
                task_id,
                "PROCESSING",
                min(round(current_progress), 80),
                f"Processing chunk {chunk_number}/{total_chunks} (clauses {chunk_start+1}-{chunk_end})"
            )

            logger.info(f"Processing chunk {chunk_number}/{total_chunks}")

            try:
                # Step 5a: Extract evidence items from chunk
                chunk_evidence_items = process_clauses_chunk(chunk_clauses, guideline.id)
                
                update_evidence_progress(
                    task_id,
                    "PROCESSING", 
                    min(round(current_progress + (progress_per_chunk * 0.2)), 80),
                    f"Prepared {len(chunk_evidence_items)} evidence items from chunk {chunk_number}"
                )

                # Step 5b: AI Processing if we have evidence items
                if chunk_evidence_items:
                    try:
                        from app.services.prompt_service import evidences_consolidate
                        from app.utils.cleaning import generate_chat_output

                        update_evidence_progress(
                            task_id,
                            "PROCESSING",
                            min(round(current_progress + (progress_per_chunk * 0.4)), 80),
                            f"Sending chunk {chunk_number} to AI for consolidation..."
                        )

                        # Generate prompt and get AI response
                        prompt = evidences_consolidate(chunk_evidence_items, chunk_number)
                        logger.info(f"Calling AI for chunk {chunk_number}")
                        res = generate_chat_output(prompt)

                        update_evidence_progress(
                            task_id,
                            "PROCESSING",
                            min(round(current_progress + (progress_per_chunk * 0.6)), 80),
                            f"Processing AI response for chunk {chunk_number}..."
                        )

                        # Parse and validate AI response
                        chunk_consolidated_data = json.loads(res)

                        # Validate response structure
                        if (isinstance(chunk_consolidated_data, dict) and 
                            "grouped_evidences" in chunk_consolidated_data and 
                            isinstance(chunk_consolidated_data["grouped_evidences"], list)):
                            
                            all_consolidated_evidence.extend(chunk_consolidated_data["grouped_evidences"])
                            logger.info(f"✅ Successfully processed chunk {chunk_number} with AI")
                            
                        else:
                            # Use fallback for invalid AI response
                            logger.warning(f"⚠️ AI returned invalid format for chunk {chunk_number}, using fallback")
                            fallback_data = create_fallback_evidence(chunk_clauses, guideline_id)
                            all_consolidated_evidence.extend(fallback_data["grouped_evidences"])

                    except json.JSONDecodeError as e:
                        logger.error(f"❌ JSON decode error for chunk {chunk_number}: {str(e)}")
                        # Use fallback for JSON errors
                        fallback_data = create_fallback_evidence(chunk_clauses, guideline_id)
                        all_consolidated_evidence.extend(fallback_data["grouped_evidences"])
                        
                    except Exception as e:
                        logger.error(f"❌ AI processing error for chunk {chunk_number}: {str(e)}")
                        # Use fallback for other AI errors
                        fallback_data = create_fallback_evidence(chunk_clauses, guideline_id)
                        all_consolidated_evidence.extend(fallback_data["grouped_evidences"])
                else:
                    # No evidence items in this chunk, create basic structure
                    logger.info(f"📝 No evidence items in chunk {chunk_number}, creating basic structure")
                    fallback_data = create_fallback_evidence(chunk_clauses, guideline_id)
                    all_consolidated_evidence.extend(fallback_data["grouped_evidences"])

                # Final progress update for this chunk
                update_evidence_progress(
                    task_id,
                    "PROCESSING",
                    min(round(current_progress + progress_per_chunk), 80),
                    f"Completed chunk {chunk_number}/{total_chunks}"
                )

            except Exception as chunk_error:
                logger.error(f"❌ Error processing chunk {chunk_number}: {str(chunk_error)}")
                # Continue with next chunk even if this one fails
                continue

        # Step 6: Merge evidence groups from all chunks
        update_evidence_progress(
            task_id, "PROCESSING", 85, "Merging evidence groups from all chunks..."
        )
        logger.info("Merging evidence groups...")

        final_consolidated_evidence = merge_evidence_groups(all_consolidated_evidence)

        # Step 7: Save to database
        update_evidence_progress(
            task_id, "PROCESSING", 90, "Saving consolidated evidence to database..."
        )
        logger.info("Saving to database...")

        final_output = {"grouped_evidences": final_consolidated_evidence}

        # Find existing record or create new one
        evidence_record = ComplifyreConsolidatedEvidence.query.filter_by(
            guideline_id=guideline.id
        ).first()

        if evidence_record:
            evidence_record.consolidate_evidence = final_output
            logger.info("Updated existing evidence record")
        else:
            evidence_record = ComplifyreConsolidatedEvidence(
                guideline_id=guideline.id, 
                consolidate_evidence=final_output
            )
            db.session.add(evidence_record)
            logger.info("Created new evidence record")

        # Commit to database
        db.session.commit()
        logger.info("✅ Database commit successful")

        # Step 8: Final success updates
        update_evidence_progress(
            task_id,
            "PROCESSING",
            95,
            "Finalizing evidence consolidation..."
        )
        
        # Small delay to ensure progress is delivered
        time.sleep(1)
        
        # Final success message
        success_message = (
            f"✅ Evidence consolidation completed! "
            f"Processed {chunks_processed}/{total_chunks} chunks with "
            f"{len(final_consolidated_evidence)} evidence groups."
        )
        
        update_evidence_progress(
            task_id,
            "COMPLETED",
            100,
            success_message,
            guideline_id,
        )

        logger.info(f"🎉 Evidence consolidation task {task_id} completed successfully")
        
        # Extra delay to ensure final message is delivered
        time.sleep(2)

        return {
            "status": "success",
            "task_id": task_id,
            "guideline_id": guideline_id,
            "chunks_processed": chunks_processed,
            "total_chunks": total_chunks,
            "evidence_groups": len(final_consolidated_evidence),
            "total_clauses": total_clauses,
        }

    except Exception as e:
        # Comprehensive error handling
        error_message = f"❌ Evidence consolidation task {task_id} failed: {str(e)}"
        logger.exception(error_message)
        
        try:
            # Multiple error updates to ensure delivery
            update_evidence_progress(
                task_id, "PROCESSING", 95, "Encountered an error, finalizing..."
            )
            time.sleep(0.5)
            
            update_evidence_progress(
                task_id, "FAILED", 100, error_message
            )
            
            # Extra delay for error message delivery
            time.sleep(2)
            
        except Exception as progress_error:
            logger.error(f"Failed to update progress on error: {str(progress_error)}")

        # Update Celery task state
        if hasattr(self, "update_state"):
            self.update_state(
                state="FAILURE",
                meta={
                    "exc_type": type(e).__name__, 
                    "exc_message": str(e),
                    "task_id": task_id,
                    "guideline_id": guideline_id
                },
            )
        
        # Re-raise the exception for Celery
        raise



# ---------- Step 1: Extract Guidelines ----------


@shared_task(bind=True)
def extract_guidelines(
    self, filename: str, file_content_bytes: bytes, user_id: int = None
):
    """Step 1: Extract a single guideline object by scanning the entire document using direct extraction."""
    logger.info(f"Step 1: Extracting guidelines for file: {filename}")

    # Define variables at the function level to avoid scope issues
    task_id = self.request.id
    guideline_id = None

    try:
        # Initialize progress
        update_guideline_progress(
            task_id, "PROCESSING", 10, "Starting guideline extraction..."
        )
        logger.info(f"Starting guideline extraction for task {task_id}")

        # Save uploaded file
        upload_dir = _safe_get_upload_folder()
        file_hash = hashlib.sha256(file_content_bytes).hexdigest()
        save_path = os.path.join(upload_dir, f"{os.urandom(8).hex()}.pdf")
        with open(save_path, "wb") as f:
            f.write(file_content_bytes)

        update_guideline_progress(
            task_id, "PROCESSING", 30, "File saved, extracting text from PDF..."
        )
        logger.info(f"File saved to: {save_path}")

        # Extract text directly from PDF (no vector store)
        pdf_text = _extract_text_from_pdf_direct(save_path)

        if not pdf_text:
            raise ValueError("Failed to extract text from PDF file")

        update_guideline_progress(
            task_id,
            "PROCESSING",
            50,
            "Text extracted, analyzing document structure...",
        )
        logger.info("PDF text extracted successfully")

        # Send a heartbeat update during the long-running extraction
        import time

        time.sleep(1)  # Small delay to ensure previous message is processed

        # Extract guidelines using direct OpenAI call (no vector store)
        guideline_response = _extract_guidelines_direct(pdf_text)

        update_guideline_progress(
            task_id, "PROCESSING", 80, "Guidelines extracted, processing data..."
        )
        logger.info("Guidelines extracted successfully")

        guidelines_result_json = (
            json.loads(guideline_response.model_dump_json())
            if guideline_response
            else None
        )

        # Save file and guideline into DB
        with session_scope() as session:
            file_record = File(
                hash=file_hash,
                path=save_path,
                size=len(file_content_bytes),
                vector_store_id=None,  # No vector store ID
                data=guidelines_result_json,
                created_at=datetime.now(timezone.utc),
            )

            session.add(file_record)
            session.flush()

            guideline_record = Guidelines(
                guideline_data=guidelines_result_json, file_id=file_record.id
            )
            session.add(guideline_record)
            session.flush()

            file_id = file_record.id
            guideline_id = guideline_record.id

        update_guideline_progress(
            task_id,
            "COMPLETED",
            100,
            f"Guideline extraction completed successfully! Guideline ID: {guideline_id}",
            guideline_id,
        )

        logger.info(f"Guideline saved: file_id={file_id}, guideline_id={guideline_id}")

        # Auto-trigger EVE context classification (background task)
        try:
            from app.services.eve_tasks import generate_guideline_eve_context
            generate_guideline_eve_context.apply_async(
                args=[guideline_id],
                queue='eve_context'
            )
            logger.info(f"[EVE] Triggered context classification for guideline_id={guideline_id}")
        except Exception as eve_err:
            logger.warning(f"[EVE] Could not trigger context classification: {eve_err}")

        return {"status": "success", "file_id": file_id, "guideline_id": guideline_id}

    except Exception as e:
        logger.exception("Guideline extraction failed")
        update_guideline_progress(
            task_id, "FAILED", 100, f"Guideline extraction failed: {str(e)}"
        )
        if hasattr(self, "update_state"):
            self.update_state(
                state="FAILURE",
                meta={"exc_type": type(e).__name__, "exc_message": str(e)},
            )
        raise


def _extract_text_from_pdf_direct(pdf_path: str) -> str:
    """
    Extract text directly from PDF without using vector store
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        text = ""

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text += f"\n--- Page {page_num + 1} ---\n"
            text += page.get_text("text") + "\n"

        doc.close()
        logger.info(f"Extracted {len(text)} characters from PDF")
        return text

    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
        return ""


def _extract_guidelines_direct(pdf_text: str):
    """
    Extract guidelines using your existing extract_structured_info function
    """
    try:
        from app.services.prompt_templates.guidelines_prompt import (
            guideline_prompt_def,
            RegulatoryDocument,
        )
        from app.services.model_response import extract_structured_info

        # Create the prompt with the PDF text
        prompt = f"""
        {guideline_prompt_def()}
        
        **PDF Content:**
        {pdf_text[:12000]}
        """

        # Use your existing function (it handles Pydantic validation internally)
        guideline_response = extract_structured_info(
            query=prompt,
            vector_store_id=None,  # No vector store
            schema=RegulatoryDocument,
        )

        return guideline_response

    except Exception as e:
        logger.error(f"Direct guideline extraction failed: {str(e)}")
        return _create_fallback_guideline(pdf_text)


def _create_fallback_guideline(pdf_text: str):
    """
    Create a fallback guideline when extraction fails
    """
    try:
        from app.services.prompt_templates.guidelines_prompt import RegulatoryDocument

        # Extract basic information from PDF text
        document_name = "Unknown Document"
        if "RBI" in pdf_text.upper():
            document_name = "RBI Guideline"
        elif "SEBI" in pdf_text.upper():
            document_name = "SEBI Regulation"
        elif "IRDAI" in pdf_text.upper():
            document_name = "IRDAI Guideline"

        # Create COMPLETE fallback data with all required fields
        fallback_data = {
            "DocumentDetails": {
                "DocumentName": document_name,
                "IssuingAuthority": "Unknown Authority",
                "ApplicableIndustries": ["Banking", "Financial Services"],
                "ApplicableOrganizations": ["Banks", "NBFCs"],
                "ApplicableGeography": ["India"],
                "PurposeAndIntent": "Regulatory compliance requirements",
                "IssuanceDate": "2024-01-01",
                "ComplianceDeadline": None,
            },
            "RegulatoryAndComplianceAspects": {
                "LegalStatus": "Legally Binding",
                "NonComplianceConsequences": "Penalties and enforcement actions",
                "RelationToPreviousRegulations": "Updates previous regulations",
            },
            "StakeholdersAndApplicability": {
                "ScopeOfApplicability": "Financial institutions",
                "ImpactOnThirdParties": "Affects third-party service providers",
            },
            "ImplementationAndOversight": {
                "ComplianceRequirements": "Reporting and audits required",
                "ImplementationTimeline": None,
                "GuidanceAvailability": "Official guidance available",
                "OverseeingBody": "Regulatory Authority",
                "ResponsibleOfficerRequirement": "Yes, compliance officer required",
            },
            "RelatedRegulations": {
                "OverlappingRegulations": "Related regulations exist",
                "RelatedNationalRegulations": "National regulations apply",
                "ComparableInternationalStandards": "International standards referenced",
            },
            "ComparisonAndIndustryImpact": {
                "AlignmentWithGlobalPractices": "Aligns with global standards",
                "JurisdictionalDifferences": "Specific to local jurisdiction",
                "ComplianceChallenges": "Implementation challenges expected",
                "ImpactOnBusinessOperations": "Significant operational impact",
            },
            "industries": ["Banking", "Financial Services"],
            "type_of_organization": {
                "Category": "Financial",
                "OrgType": "Banking Institutions",
            },
        }

        return RegulatoryDocument(**fallback_data)

    except Exception as e:
        logger.error(f"Fallback guideline creation also failed: {str(e)}")
        return None


# ---------- Step 2: Extract Clauses for a Guideline ----------


@shared_task(bind=True)
def extract_clauses(self, guideline_id: int):
    """Step 2: Extract clauses for a guideline using app.py logic"""
    logger.info(
        f"Step 2: Extracting clauses for guideline_id={guideline_id} using enhanced PDF processing"
    )

    try:
        # Update initial progress
        update_progress(guideline_id, "PROCESSING", 30, "Starting PDF processing...")

        with session_scope() as session:
            guideline = session.query(Guidelines).filter_by(id=guideline_id).first()
            if not guideline:
                raise ValueError("Guideline not found")
            file_record = session.query(File).filter_by(id=guideline.file_id).first()
            if not file_record:
                raise ValueError("File record not found")
            file_path = file_record.path

        # Update progress
        update_progress(guideline_id, "PROCESSING", 50, "Extracting text from PDF...")

        # Process PDF page by page like app.py
        page_texts = {}
        for page_num, page_text in extract_text_from_pdf_page_by_page(file_path):
            page_texts[page_num] = page_text

        total_pages = len(page_texts)
        saved_clauses = []
        all_extracted_clause_numbers = []

        # Collect all clauses first, then sort and save
        unsorted_clauses = []

        # Update progress
        update_progress(guideline_id, "PROCESSING", 70, "Sending to AI for analysis...")

        # Process in chunks (similar to app.py but using actual pages)
        page_chunk_size = min(10, total_pages)  # Process 10 pages at a time max
        if total_pages <= 5:
            page_chunk_size = total_pages

        for start_page in range(1, total_pages + 1, page_chunk_size):
            end_page = min(start_page + page_chunk_size - 1, total_pages)
            page_range_str = f"pages {start_page} to {end_page}"

            logger.info(f"Processing {page_range_str} for guideline {guideline_id}")

            # Combine text from pages in this chunk
            chunk_text = ""
            for page_num in range(start_page, end_page + 1):
                if page_num in page_texts:
                    chunk_text += f"\n--- Page {page_num} ---\n{page_texts[page_num]}\n"

            if not chunk_text.strip():
                logger.warning(f"No text found for {page_range_str}")
                continue

            # Extract context for analysis
            context_text = chunk_text

            try:
                # Use the enhanced OpenAI extraction
                chunk_response, usage_metrics = extract_clauses_with_openai(
                    chunk_text, guideline_id, page_range_str
                )

                logger.info(f"LLM response received for {page_range_str}")

                # Analyze extraction quality
                extraction_metrics = analyze_extraction_quality(
                    chunk_response, context_text, total_pages, page_range_str
                )

                # Save raw LLM response to database
                try:
                    with session_scope() as session:
                        raw_response_text = (
                            json.dumps(chunk_response)
                            if chunk_response
                            else "No response"
                        )

                        context_start_clean = (
                            clean_string_for_db(context_text[:500])
                            if context_text
                            else ""
                        )
                        context_end_clean = (
                            clean_string_for_db(context_text[-500:])
                            if context_text
                            else ""
                        )

                        raw_response_obj = RawLLMResponse(
                            guideline_id=guideline_id,
                            task_type="clause_extraction",
                            page_range=page_range_str,
                            raw_response=raw_response_text,
                            context_start_text=context_start_clean,
                            context_end_text=context_end_clean,
                            total_context_length=(
                                len(context_text) if context_text else 0
                            ),
                            prompt_tokens=usage_metrics.get("prompt_tokens", 0),
                            completion_tokens=usage_metrics.get("completion_tokens", 0),
                            total_tokens=usage_metrics.get("total_tokens", 0),
                            expected_clauses_count=extraction_metrics.get(
                                "expected_count", 0
                            ),
                            extracted_clauses_count=extraction_metrics.get(
                                "extracted_count", 0
                            ),
                            missing_clauses=json.dumps(
                                extraction_metrics.get("missing_clauses", {})
                            ),
                            confidence_score=extraction_metrics.get(
                                "confidence_score", 0.0
                            ),
                        )
                        session.add(raw_response_obj)
                        session.commit()
                        logger.info(
                            f"✅ Successfully saved raw response for {page_range_str}"
                        )
                except Exception as db_error:
                    logger.error(
                        f"❌ Failed to save raw response for {page_range_str}: {str(db_error)}"
                    )

                # Process extracted requirements - COLLECT BUT DON'T SAVE YET
                if chunk_response and "extracted_requirements" in chunk_response:
                    requirements_list = chunk_response["extracted_requirements"]
                    logger.info(
                        f"📝 Processing {len(requirements_list)} requirements from {page_range_str}"
                    )

                    for requirement in requirements_list:
                        clause_text = requirement.get("clause_text", "").strip()
                        clause_number = requirement.get("clause_number", "").strip()
                        page_number = requirement.get("page_number", 0)

                        if not clause_text:
                            logger.warning(
                                "Skipping requirement with empty clause text"
                            )
                            continue

                        # Track extracted clause numbers
                        if clause_number:
                            all_extracted_clause_numbers.append(str(clause_number))

                        logger.info(
                            f"📄 Collected clause {clause_number} from page {page_number}"
                        )

                        # Store for later sorting - DON'T SAVE TO DB YET
                        unsorted_clauses.append(
                            {
                                "clause_number": clause_number,
                                "clause_text": clause_text,
                                "page_number": page_number,
                                "guideline_id": guideline_id,
                            }
                        )

                else:
                    logger.warning(
                        f"No extracted_requirements found in response for {page_range_str}"
                    )

            except Exception as chunk_error:
                logger.error(
                    f"Error processing chunk {page_range_str}: {str(chunk_error)}"
                )
                continue

        # AFTER PROCESSING ALL CHUNKS - NOW SORT AND SAVE ALL CLAUSES TOGETHER
        logger.info(
            f"📊 Processing complete. Now sorting {len(unsorted_clauses)} clauses..."
        )

        # Sort clauses using natural sorting
        def roman_to_int(s):
            """Convert Roman numeral string to integer for correct sorting."""
            vals = {"i":1,"v":5,"x":10,"l":50,"c":100,"d":500,"m":1000}
            s = s.lower()
            result = 0
            for idx in range(len(s)):
                if idx+1 < len(s) and vals.get(s[idx],0) < vals.get(s[idx+1],0):
                    result -= vals.get(s[idx], 0)
                else:
                    result += vals.get(s[idx], 0)
            return result

        def natural_sort_key(item):
            text = item["clause_number"]
            if text is None or text == "":
                return [float("inf")]
            key = []
            for part in re.split(r"(\s+|\(|\))", str(text)):
                part = part.strip("() ")
                if not part:
                    continue
                if part.isdigit():
                    key.append(int(part))
                elif re.match(r"^[IVXivx]+$", part) and len(part) <= 8 and part.upper() not in ("CH", "SCH", "ANN", "A", "B", "C", "D", "E", "F", "G", "H"):
                    # Pure Roman numeral — convert to int (exclude known prefixes)
                    key.append(roman_to_int(part))
                else:
                    key.append(part.lower())
            return key

        sorted_clauses = sorted(unsorted_clauses, key=natural_sort_key)

        logger.info(
            f"✅ Sorting complete. Saving {len(sorted_clauses)} clauses to database..."
        )

        # Save sorted clauses
        with session_scope() as session:
            for clause_data in sorted_clauses:
                clause_number = clause_data["clause_number"]
                clause_text = clause_data["clause_text"]
                guideline_id = clause_data["guideline_id"]

                # Check for duplicates by text
                existing_clause = (
                    session.query(Clauses)
                    .filter_by(guideline_id=guideline_id, clause_text=clause_text)
                    .first()
                )

                if existing_clause:
                    logger.info(f"Skipping duplicate clause text: {clause_number}")
                    continue

                # Check for duplicates by clause number
                if clause_number:
                    existing_by_number = (
                        session.query(Clauses)
                        .filter_by(
                            guideline_id=guideline_id,
                            clause_no=clause_number[:500] if clause_number else None,
                        )
                        .first()
                    )

                    if existing_by_number:
                        logger.info(
                            f"Skipping duplicate clause number: {clause_number}"
                        )
                        continue

                # Save new clause
                clause_obj = Clauses(
                    clause_no=clause_number[:500] if clause_number else None,
                    clause_text=clause_text,
                    guideline_id=guideline_id,
                    page_number=clause_data["page_number"],
                )
                session.add(clause_obj)
                session.flush()
                saved_clauses.append(clause_obj.id)
                logger.info(f"✅ Saved clause: {clause_number}")

        # Final analysis
        analyze_overall_missing_data(guideline_id, all_extracted_clause_numbers)

        # Update final progress
        update_progress(
            guideline_id,
            "COMPLETED",
            100,
            f"Clause extraction completed successfully! Saved {len(saved_clauses)} clauses.",
            len(saved_clauses),
        )

        logger.info(
            f"✅ Clause extraction completed for guideline {guideline_id}. Saved {len(saved_clauses)} clauses in correct numerical order."
        )

        # Auto-trigger activities generation for all saved clauses
        try:
            triggered_count = 0
            for clause_id in saved_clauses:
                extract_activities.apply_async(
                    args=[clause_id],
                    queue='extract_activities'
                )
                triggered_count += 1
            logger.info(f"[AUTO] Triggered activities generation for {triggered_count} clauses")
        except Exception as trigger_err:
            logger.warning(f"[AUTO] Could not trigger activities: {trigger_err}")

        return {
            "status": "success",
            "guideline_id": guideline_id,
            "clauses_saved": saved_clauses,
            "total_extracted_clauses": len(all_extracted_clause_numbers),
        }

    except Exception as e:
        logger.exception(f"Clause extraction failed for guideline {guideline_id}")
        self.update_state(
            state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )
        raise


# ---------- Step 3: Extract Activities for a Clause ----------


@shared_task(bind=True)
def extract_activities(self, clause_id: int):
    """Step 3: Extract activities for a clause and save in DB"""
    logger.info(f"Step 3: Extracting activities for clause_id={clause_id}")
    try:
        with session_scope() as session:
            clause = session.query(Clauses).filter_by(id=clause_id).first()
            if not clause:
                raise ValueError("Clause not found")
            guideline = (
                session.query(Guidelines).filter_by(id=clause.guideline_id).first()
            )
            file_record = session.query(File).filter_by(id=guideline.file_id).first()
            vec_id = file_record.vector_store_id

        activity_response = extract_structured_info(
            query=compliance_prompt(clause.clause_text, []),
            vector_store_id=vec_id,
            schema=ComplianceRequirements,
        )
        activities = _as_dict(activity_response).get("compliance_activities", [])

        saved_activities = []
        with session_scope() as session:
            for act in activities:
                comp_activity = ComplianceActivities(
                    clause_id=clause_id,
                    relevant_departments=_get(act, "relevant_departments"),
                    process=_get(act, "process_name"),
                    sub_process=_get(act, "sub_process_name"),
                    activity_id=_get(act, "activity_id"),
                    activity_description=_get(act, "activity_description"),
                    responsible_party=_get(act, "responsible_party"),
                    frequency=_get(act, "frequency"),
                    evidence_required=_get(act, "evidence_required"),
                    compliance_level=_get(act, "compliance_level", "Design"),
                )
                session.add(comp_activity)
                session.flush()
                saved_activities.append(comp_activity.id)

        return {
            "status": "success",
            "clause_id": clause_id,
            "activities_saved": saved_activities,
        }

    except Exception as e:
        logger.exception("Activity extraction failed")
        self.update_state(
            state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )
        raise


# ---------- Step 4: Extract Test Procedures for an Activity ----------


@shared_task(bind=True)
def extract_test_procedures(self, activity_id: int):
    """Step 4: Extract test procedures for an activity and save in DB"""
    logger.info(f"Step 4: Extracting test procedures for activity_id={activity_id}")
    try:
        with session_scope() as session:
            activity = (
                session.query(ComplianceActivities).filter_by(id=activity_id).first()
            )
            if not activity:
                raise ValueError("Activity not found")
            clause = session.query(Clauses).filter_by(id=activity.clause_id).first()
            guideline = (
                session.query(Guidelines).filter_by(id=clause.guideline_id).first()
            )
            file_record = session.query(File).filter_by(id=guideline.file_id).first()
            vec_id = file_record.vector_store_id

        test_proc_response = extract_structured_info(
            query=test_procedure(clause.clause_text, _as_json(activity)),
            vector_store_id=vec_id,
            schema=ControlWorkpaper,
        )
        if not test_proc_response:
            return {"status": "warning", "message": "No test procedures extracted"}

        test_data_dict = _as_dict(test_proc_response)

        with session_scope() as session:
            session.add(
                TestProcedures(
                    activity_id=activity_id, data=_as_json(test_proc_response)
                )
            )
            # Check if control activity already exists — UPDATE instead of INSERT
            control = session.query(ControlActivity).filter_by(
                compliance_activity_id=activity_id
            ).first()

            if control:
                # UPDATE existing record
                control.activity_code = _get(test_data_dict, "activity_code")
                control.activity_name = _get(test_data_dict, "activity_name")
                control.activity_description = _get(test_data_dict, "activity_description")
                control.objective = _get(test_data_dict, "objective")
                control.owner = _get(test_data_dict, "owner")
                control.control_type = _get(test_data_dict, "control_type")
                control.frequency = _get(test_data_dict, "frequency")
                control.sampling_guidance = _get(test_data_dict, "sampling_guidance")
                control.explain_test_procedure = _get(test_data_dict, "explain_test_procedure")
                control.assessment_objective = _get(test_data_dict, "assessment_objective")
                control.assessment_objective_rationale = _get(test_data_dict, "assessment_objective_rationale")
                control.test_attributes = _get(test_data_dict, "test_attributes")
                session.flush()
                control_id = control.id
            else:
                # INSERT new record
                control = ControlActivity(
                    activity_code=_get(test_data_dict, "activity_code"),
                    activity_name=_get(test_data_dict, "activity_name"),
                    activity_description=_get(test_data_dict, "activity_description"),
                    objective=_get(test_data_dict, "objective"),
                    owner=_get(test_data_dict, "owner"),
                    control_type=_get(test_data_dict, "control_type"),
                    frequency=_get(test_data_dict, "frequency"),
                    sampling_guidance=_get(test_data_dict, "sampling_guidance"),
                    auditor_observation=_get(test_data_dict, "auditor_observation"),
                    findings=_get(test_data_dict, "findings"),
                    impact=_get(test_data_dict, "impact"),
                    severity=_get(test_data_dict, "severity"),
                    recommendations=_get(test_data_dict, "recommendations"),
                    reviewer_notes=_get(test_data_dict, "reviewer_notes"),
                    explain_test_procedure=_get(test_data_dict, "explain_test_procedure"),
                    assessment_objective=_get(test_data_dict, "assessment_objective"),
                    assessment_objective_rationale=_get(test_data_dict, "assessment_objective_rationale"),
                    test_attributes=_get(test_data_dict, "test_attributes"),
                    compliance_activity_id=activity_id,
                )
                session.add(control)
                session.flush()
                control_id = control.id

            # Auto-trigger EVE checklist generation (background task)
            try:
                from app.services.eve_tasks import generate_control_checklist
                generate_control_checklist.apply_async(
                    args=[control_id],
                    queue='eve_checklist'
                )
                logger.info(f"[EVE] Triggered checklist generation for control_id={control_id}")
            except Exception as eve_err:
                logger.warning(f"[EVE] Could not trigger checklist generation: {eve_err}")

            test_steps_payload = _ci_get(test_data_dict, "test_procedure", {})
            test_steps = TestSteps(
                walkthrough=_ci_get(test_steps_payload, "walkthrough"),
                sampling=_ci_get(test_steps_payload, "sampling"),
                control_id=control_id,
            )
            session.add(test_steps)
            session.flush()
            test_steps_id = test_steps.id

            for doc_name in (
                _ci_get(test_steps_payload, "review_of_documentation") or []
            ):
                session.add(
                    DocumentReview(
                        test_procedure_id=test_steps_id, document_name=doc_name
                    )
                )

            interviews_data = _ci_get(test_steps_payload, "interviews", {})
            interview = Interview(test_procedure_id=test_steps_id)
            session.add(interview)
            session.flush()
            interview_id = interview.id

            for role in _ci_get(interviews_data, "roles") or []:
                session.add(InterviewRole(interview_id=interview_id, role=role))
            for question in _ci_get(interviews_data, "key_questions") or []:
                session.add(
                    InterviewQuestion(interview_id=interview_id, question=question)
                )

            evidence_input = _ci_get(test_data_dict, "evidences_artifacts_needed", [])
            iter_evidence = []
            if isinstance(evidence_input, dict):
                iter_evidence = (
                    (k, v if isinstance(v, list) else [v])
                    for k, v in evidence_input.items()
                )
            elif isinstance(evidence_input, list):

                def _yield_from_list(lst):
                    for entry in lst:
                        if not entry:
                            continue
                        if isinstance(entry, dict):
                            cat = (
                                entry.get("category") or entry.get("name") or "Unknown"
                            )
                            items = entry.get("items") or entry.get("items_list") or []
                            yield (cat, items if isinstance(items, list) else [items])
                        else:
                            yield ("Unknown", [str(entry)])

                iter_evidence = _yield_from_list(evidence_input)

            for category, items in iter_evidence:
                category = (category or "Unknown").strip()
                for item in items or []:
                    artifact = (
                        session.query(EvidenceArtifact)
                        .filter_by(category=category, item=item)
                        .first()
                    )
                    if not artifact:
                        artifact = EvidenceArtifact(category=category, item=item)
                        session.add(artifact)
                        session.flush()
                    control.evidences.append(artifact)

        return {
            "status": "success",
            "activity_id": activity_id,
            "control_id": control_id,
        }

    except Exception as e:
        logger.exception("Test procedure extraction failed")
        self.update_state(
            state="FAILURE", meta={"exc_type": type(e).__name__, "exc_message": str(e)}
        )
        raise


def get_clause_completion_status(clause_id: int) -> str:
    """
    Check if a clause has been fully extracted — activities + test procedures + checklists.
    Returns:
      'EMPTY'                — no activities at all
      'INCOMPLETE_STRUCTURE' — missing activities or test procedures — delete + regenerate
      'INCOMPLETE_CHECKLIST' — activities + test procs exist but some checklists missing/empty
                               — only regenerate missing checklists, do NOT delete activities
      'COMPLETE'             — all activities have test procedures + valid checklists
    """
    from app.models.ai import ControlActivity
    from app.models.eve_models import ControlChecklist

    activities = ComplianceActivities.query.filter_by(clause_id=clause_id).all()
    if not activities:
        return "EMPTY"

    has_missing_checklist = False

    for act in activities:
        ctrl = ControlActivity.query.filter_by(
            compliance_activity_id=act.id
        ).first()
        if not ctrl:
            return "INCOMPLETE_STRUCTURE"

        if not ctrl.test_procedure:
            return "INCOMPLETE_STRUCTURE"

        checklist = ControlChecklist.query.filter_by(
            control_activity_id=ctrl.id
        ).first()
        if not checklist or not checklist.raw_output_json:
            has_missing_checklist = True

    if has_missing_checklist:
        return "INCOMPLETE_CHECKLIST"

    return "COMPLETE"


def _delete_clause_data(clause_id: int):
    """
    Delete ALL data for a clause in correct cascade order.
    Called when clause is INCOMPLETE — clean slate before regeneration.
    """
    from app.models.ai import ControlActivity
    from sqlalchemy import text as sql_text

    try:
        # Get all control_activity ids for this clause
        ctrl_ids = [
            row[0] for row in db.session.execute(sql_text("""
                SELECT cta.id FROM control_activities cta
                JOIN compliance_activities ca ON ca.id = cta.compliance_activity_id
                WHERE ca.clause_id = :cid
            """), {"cid": clause_id}).fetchall()
        ]

        # Get test_step ids
        ts_ids = [
            row[0] for row in db.session.execute(sql_text("""
                SELECT ts.id FROM test_steps ts
                WHERE ts.control_id = ANY(:ctrl_ids)
            """), {"ctrl_ids": ctrl_ids}).fetchall()
        ] if ctrl_ids else []

        if ts_ids:
            db.session.execute(sql_text(
                "DELETE FROM interview_questions WHERE interview_id IN "
                "(SELECT id FROM interviews WHERE test_procedure_id = ANY(:ts_ids))"
            ), {"ts_ids": ts_ids})
            db.session.execute(sql_text(
                "DELETE FROM interview_roles WHERE interview_id IN "
                "(SELECT id FROM interviews WHERE test_procedure_id = ANY(:ts_ids))"
            ), {"ts_ids": ts_ids})
            db.session.execute(sql_text(
                "DELETE FROM interviews WHERE test_procedure_id = ANY(:ts_ids)"
            ), {"ts_ids": ts_ids})
            db.session.execute(sql_text(
                "DELETE FROM document_reviews WHERE test_procedure_id = ANY(:ts_ids)"
            ), {"ts_ids": ts_ids})

        if ctrl_ids:
            db.session.execute(sql_text(
                "DELETE FROM control_evidences WHERE control_id = ANY(:ctrl_ids)"
            ), {"ctrl_ids": ctrl_ids})
            db.session.execute(sql_text(
                "DELETE FROM test_steps WHERE control_id = ANY(:ctrl_ids)"
            ), {"ctrl_ids": ctrl_ids})
            # Delete EVE checklists + project checklists
            db.session.execute(sql_text(
                "DELETE FROM control_checklist WHERE control_activity_id = ANY(:ctrl_ids)"
            ), {"ctrl_ids": ctrl_ids})
            db.session.execute(sql_text(
                "DELETE FROM control_activities WHERE id = ANY(:ctrl_ids)"
            ), {"ctrl_ids": ctrl_ids})

        # Delete test procedures
        act_ids = [
            row[0] for row in db.session.execute(sql_text(
                "SELECT id FROM compliance_activities WHERE clause_id = :cid"
            ), {"cid": clause_id}).fetchall()
        ]
        if act_ids:
            db.session.execute(sql_text(
                "DELETE FROM test_procedures WHERE activity_id = ANY(:act_ids)"
            ), {"act_ids": act_ids})

        # Finally delete compliance activities
        db.session.execute(sql_text(
            "DELETE FROM compliance_activities WHERE clause_id = :cid"
        ), {"cid": clause_id})

        db.session.commit()
        logger.info(f"Deleted all data for clause_id={clause_id}")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete clause data for clause_id={clause_id}: {e}")
        raise


@shared_task(bind=True, max_retries=0)
def extract_all_activities_and_tests(self, guideline_id: int):
    """
    Batch extraction of clauses, compliance activities, and test procedures
    for a given guideline. Combines logic from process_clause + process_test_procedures.
    Skips clauses that already have compliance activities.
    """
    logger.info(f"Starting full extraction for guideline_id={guideline_id}")
    results = {"clauses": [], "activities": [], "test_procedures": [], "skipped": []}

    try:
        # Initialize progress
        update_compliance_progress(
            guideline_id,
            "PROCESSING",
            5,
            "Starting compliance activities extraction...",
        )

        guideline = Guidelines.query.filter_by(id=guideline_id).first()
        if not guideline:
            raise ValueError("Guideline not found")

        file_record = File.query.filter_by(id=guideline.file_id).first()
        if not file_record:
            raise ValueError("File record not found for guideline")

        vec_id = file_record.vector_store_id

        # Preload known departments for AI matching
        update_compliance_progress(
            guideline_id, "PROCESSING", 10, "Loading departments and clauses..."
        )
        department_list = [
            {"department_id": d.department_id, "department_name": d.department_name}
            for d in OrganizationDepartments.query.all()
        ]

        # Collect (comp_id, clause_text, act_payload_json, vec_id) for post-commit test-procedure processing
        comps_to_process = []

        # Step 1: Get all clauses
        clauses = Clauses.query.filter_by(guideline_id=guideline_id).all()
        if not clauses:
            raise ValueError("No clauses found for this guideline")

        total_clauses = len(clauses)
        processed_clauses = 0
        skipped_clauses = 0

        update_compliance_progress(
            guideline_id,
            "PROCESSING",
            15,
            f"Found {total_clauses} clauses to process...",
            0,
            total_clauses,
        )

        for clause in clauses:
            clause_id_val = clause.id
            clause_text = clause.clause_text
            clause_number = clause.clause_no or "unknown"

            if not clause_text:
                logger.warning("Skipping clause with no text (id=%s)", clause_id_val)
                skipped_clauses += 1
                processed_clauses += 1  # Increment processed count even for skipped
                continue

            # Completeness check — COMPLETE=skip, INCOMPLETE=delete+regen, EMPTY=generate
            completion = get_clause_completion_status(clause_id_val)
            if completion == "COMPLETE":
                logger.info(
                    "Skipping clause %s (id=%s) — fully complete",
                    clause_number, clause_id_val,
                )
                results["skipped"].append(clause_id_val)
                skipped_clauses += 1
                processed_clauses += 1
                continue
            elif completion == "INCOMPLETE_CHECKLIST":
                # Activities + test procedures exist — only generate missing checklists
                logger.warning(
                    "Clause %s (id=%s) — activities complete but checklists missing — generating checklists only",
                    clause_number, clause_id_val,
                )
                from app.models.ai import ControlActivity as _CtrlAct
                from app.models.eve_models import ControlChecklist as _CC
                from app.services.eve_tasks import generate_control_checklist
                activities_for_clause = ComplianceActivities.query.filter_by(
                    clause_id=clause_id_val
                ).all()
                for act in activities_for_clause:
                    ctrl = _CtrlAct.query.filter_by(compliance_activity_id=act.id).first()
                    if ctrl:
                        existing_cc = _CC.query.filter_by(control_activity_id=ctrl.id).first()
                        if not existing_cc or not existing_cc.raw_output_json:
                            logger.info("Generating missing checklist for control_id=%s", ctrl.id)
                            generate_control_checklist(ctrl.id)
                results["skipped"].append(clause_id_val)
                skipped_clauses += 1
                processed_clauses += 1
                continue
            elif completion == "INCOMPLETE_STRUCTURE":
                # Missing activities or test procedures — full delete + regenerate
                logger.warning(
                    "Clause %s (id=%s) is INCOMPLETE_STRUCTURE — deleting partial data and regenerating",
                    clause_number, clause_id_val,
                )
                _delete_clause_data(clause_id_val)
                # Fall through to generate fresh

            with session_scope() as session:
                # Inside-session check as safety net
                existing_count = session.query(ComplianceActivities).filter_by(
                    clause_id=clause_id_val
                ).count()
                if existing_count > 0:
                    logger.warning(
                        "Clause %s (id=%s) still has %d activities after delete — skipping",
                        clause_number, clause_id_val, existing_count,
                    )
                    results["skipped"].append(clause_id_val)
                    skipped_clauses += 1
                    processed_clauses += 1
                    continue

                # Extract compliance activities
                progress = 15 + (processed_clauses / total_clauses) * 60
                update_compliance_progress(
                    guideline_id,
                    "PROCESSING",
                    int(progress),
                    f"Extracting activities for clause {clause_number}...",
                    processed_clauses,
                    total_clauses,
                )

                activity_response = extract_structured_info(
                    query=compliance_prompt(clause_text, list(department_list)),
                    vector_store_id=vec_id,
                    schema=ComplianceRequirements,
                )

                if not activity_response:
                    logger.info("No compliance activities for clause %s", clause_number)
                    results["activities"].append({clause_id_val: []})
                    processed_clauses += 1  # Increment processed count
                    continue

                parsed_dict = _as_dict(activity_response) or {}
                activities = (
                    parsed_dict.get("compliance_activities")
                    or parsed_dict.get("activities")
                    or []
                )
                logger.info(
                    "Found %d compliance activities for clause %s",
                    len(activities),
                    clause_number,
                )

                saved_activities = []

                # Fix: Add numerical activity ID validation with enumerate
                for index, act in enumerate(activities, start=1):
                    # Ensure activity_id is numerical - use AI response if numerical, otherwise use index
                    activity_id_from_ai = _get(act, "activity_id", "")

                    # Try to extract numerical value, if fails use the index
                    try:
                        # Extract numbers from string if it contains numbers
                        import re

                        numbers = re.findall(r"\d+", str(activity_id_from_ai))
                        if numbers:
                            activity_id = numbers[0]  # Take first number found
                        else:
                            activity_id = str(index)  # Use the loop index as fallback
                    except (ValueError, TypeError):
                        activity_id = str(index)  # Use the loop index as fallback

                    # Resolve department id safely (validate or create)
                    raw_dept_id = None
                    try:
                        raw_dept_id = int(_get(act, "department_id", 0) or 0)
                    except Exception:
                        raw_dept_id = None

                    dept_obj = None
                    if raw_dept_id:
                        dept_obj = (
                            session.query(OrganizationDepartments)
                            .filter_by(department_id=raw_dept_id)
                            .first()
                        )

                    if not dept_obj:
                        dept_name_from_ai = (
                            _get(act, "relevant_departments")
                            or _get(act, "department_name")
                            or None
                        )
                        if dept_name_from_ai:
                            ai_lower = dept_name_from_ai.strip().lower()
                            for d in department_list or []:
                                dn = (d.get("department_name") or "").strip()
                                if dn:
                                    dn_l = dn.lower()
                                    if ai_lower in dn_l or dn_l in ai_lower:
                                        dept_obj = (
                                            session.query(OrganizationDepartments)
                                            .filter_by(department_id=d["department_id"])
                                            .first()
                                        )
                                        if dept_obj:
                                            break

                    if not dept_obj:
                        dept_to_create_name = (
                            _get(act, "relevant_departments") or "Unknown"
                        )
                        dept_obj = OrganizationDepartments(
                            department_name=dept_to_create_name
                        )
                        session.add(dept_obj)
                        session.flush()

                    relevant_departments_id_val = getattr(
                        dept_obj, "department_id", None
                    )

                    # Duplicate check: skip if similar activity already exists for this clause
                    new_desc = (_get(act, "activity_description") or "").strip().lower()
                    new_level = (_get(act, "compliance_level") or "Design").strip().lower()
                    existing_for_clause = session.query(ComplianceActivities).filter_by(clause_id=clause_id_val).all()
                    is_duplicate = False
                    for existing in existing_for_clause:
                        existing_desc = (existing.activity_description or "").strip().lower()
                        existing_level = (existing.compliance_level or "").strip().lower()
                        # Check: same compliance level AND description similarity > 70%
                        if existing_level == new_level and existing_desc and new_desc:
                            # Simple word overlap check — 50% threshold (was 70%)
                            new_words = set(new_desc.split())
                            existing_words = set(existing_desc.split())
                            if len(new_words) > 0:
                                overlap = len(new_words & existing_words) / len(new_words)
                                if overlap > 0.5:
                                    logger.warning(
                                        "Skipping duplicate activity for clause %s (level=%s, overlap=%.0f%%): %s",
                                        clause_id_val, new_level, overlap*100, new_desc[:80]
                                    )
                                    is_duplicate = True
                                    break

                    if is_duplicate:
                        continue

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
                        compliance_level=_get(act, "compliance_level", "Design"),
                    )
                    session.add(comp)
                    session.flush()
                    comp_id_val = comp.id
                    saved_activities.append(comp_id_val)

                    logger.info(
                        "Saved ComplianceActivity(id=%s) for Clause(id=%s)with compliance_level=%s",
                        comp_id_val,
                        clause_id_val,
                        _get(act, "compliance_level", "Design"),  # Log compliance level
                    )

                    # Generate test procedure — synchronous
                    act_dict = _as_dict(act) if not isinstance(act, dict) else act
                    _generate_test_procedure_for_activity(comp_id_val, clause_text, act_dict)

                    # Generate EVE checklist — NOW SYNCHRONOUS (was async)
                    # Must complete before clause is marked done
                    try:
                        from app.services.eve_tasks import generate_control_checklist
                        from app.models.ai import ControlActivity as _CtrlAct
                        from app import db as _db
                        ctrl = _db.session.query(_CtrlAct).filter_by(
                            compliance_activity_id=comp_id_val
                        ).first()
                        if ctrl:
                            # Direct synchronous call — not apply_async
                            generate_control_checklist(ctrl.id)
                            logger.info(
                                f"[EVE] Checklist generated synchronously for control_id={ctrl.id}"
                            )
                        else:
                            logger.warning(
                                f"[EVE] ControlActivity not found for comp_id={comp_id_val} "
                                f"— checklist skipped"
                            )
                    except Exception as eve_err:
                        logger.error(
                            f"[EVE] Checklist generation failed for comp_id={comp_id_val}: {eve_err}"
                        )
                        # Re-raise — clause should be marked INCOMPLETE not silently skipped
                        raise

                results["activities"].append({clause_id_val: saved_activities})
                processed_clauses += (
                    1  # Increment processed count after successful processing
                )

                # Update progress
                progress = (
                    15 + (processed_clauses / total_clauses) * 60
                )  # 15-75% range for clause processing
                update_compliance_progress(
                    guideline_id,
                    "PROCESSING",
                    int(progress),
                    f"Processed clause {clause_number}... ({processed_clauses}/{total_clauses} clauses)",
                    processed_clauses,
                    total_clauses,
                )

        # Step 2: Process test procedures (outside clause transaction)
        update_compliance_progress(
            guideline_id,
            "PROCESSING",
            75,
            "Generating test procedures...",
            processed_clauses,
            total_clauses,
        )

        total_test_procedures = len(comps_to_process)
        processed_test_procedures = 0

        for (
            comp_id_val,
            clause_text_val,
            comp_payload_json,
            vec_id_val,
        ) in comps_to_process:
            try:
                update_compliance_progress(
                    guideline_id,
                    "PROCESSING",
                    75 + (processed_test_procedures / total_test_procedures) * 20,
                    f"Generating test procedures... ({processed_test_procedures + 1}/{total_test_procedures})",
                    processed_clauses,
                    total_clauses,
                )

                process_test_procedures(
                    comp_id=comp_id_val,
                    clause_text=clause_text_val,
                    compliance_activity_payload=comp_payload_json,
                    vec_id=vec_id_val,
                )
                results["test_procedures"].append({comp_id_val: "processed"})
                processed_test_procedures += 1

            except Exception as te:
                logger.exception(
                    "Error in test procedures for comp(id=%s): %s", comp_id_val, te
                )
                results["test_procedures"].append({comp_id_val: "failed"})
                processed_test_procedures += 1

        # Final completion
        total_activities = len(comps_to_process)
        update_compliance_progress(
            guideline_id,
            "COMPLETED",
            100,
            f"Successfully generated {total_activities} compliance activities and test procedures for {processed_clauses} clauses!",
            processed_clauses,
            total_clauses,
        )

        logger.info(f"Extraction completed for guideline_id={guideline_id}")
        # Auto-queue any missing test procedures after completion
        try:
            from sqlalchemy import text as sql_text
            with session_scope() as cleanup_session:
                missing = cleanup_session.execute(sql_text("""
                    SELECT ca.id FROM compliance_activities ca
                    JOIN clauses c ON ca.clause_id = c.id
                    LEFT JOIN control_activities cta ON cta.compliance_activity_id = ca.id
                    WHERE c.guideline_id = :gid AND cta.id IS NULL
                """), {'gid': guideline_id}).fetchall()
                for row in missing:
                    extract_test_procedures.delay(row[0])
                if missing:
                    logger.info("Auto-queued %d missing test procedures for guideline %s", len(missing), guideline_id)
        except Exception as e:
            logger.warning("Auto-cleanup for missing test procedures failed: %s", e)

        return {"status": "success", "guideline_id": guideline_id, "results": results}

    except Exception as e:
        logger.exception("Full extraction failed")
        update_compliance_progress(
            guideline_id,
            "FAILED",
            100,
            f"Compliance activities extraction failed: {str(e)}",
        )
        self.update_state(
            state="FAILURE",
            meta={"exc_type": type(e).__name__, "exc_message": str(e)},
        )
        raise


@shared_task(bind=True, max_retries=0)
def extract_selected_activities_and_tests(self, guideline_id: int, clause_ids: list):
    """
    Batch extraction of compliance activities and test procedures for selected clauses only.
    SIMPLIFIED VERSION: Uses direct extraction without vector database
    """
    logger.info(
        f"Starting selective extraction for guideline_id={guideline_id}, clauses={clause_ids}"
    )
    results = {"clauses": [], "activities": [], "test_procedures": [], "skipped": []}

    try:
        # Initialize progress
        update_compliance_progress(
            self.request.id,
            "PROCESSING",
            5,
            f"Starting compliance activities extraction for {len(clause_ids)} selected clauses...",
        )

        guideline = Guidelines.query.filter_by(id=guideline_id).first()
        if not guideline:
            raise ValueError("Guideline not found")

        # Preload known departments for AI matching
        update_compliance_progress(
            self.request.id, "PROCESSING", 10, "Loading departments..."
        )
        department_list = [
            {"department_id": d.department_id, "department_name": d.department_name}
            for d in OrganizationDepartments.query.all()
        ]

        # Step 1: Get selected clauses
        clauses = Clauses.query.filter(
            Clauses.id.in_(clause_ids), Clauses.guideline_id == guideline_id
        ).all()

        if not clauses:
            raise ValueError("No selected clauses found")

        total_clauses = len(clauses)
        processed_clauses = 0
        skipped_clauses = 0

        update_compliance_progress(
            self.request.id,
            "PROCESSING",
            15,
            f"Processing {total_clauses} selected clauses...",
            0,
            total_clauses,
        )

        for clause in clauses:
            clause_id_val = clause.id
            clause_text = clause.clause_text
            clause_number = clause.clause_no or "unknown"

            if not clause_text:
                logger.warning("Skipping clause with no text (id=%s)", clause_id_val)
                skipped_clauses += 1
                processed_clauses += 1
                continue

            # Completeness check
            completion = get_clause_completion_status(clause_id_val)
            if completion == "COMPLETE":
                logger.info(
                    "Skipping clause %s (id=%s) — fully complete",
                    clause_number, clause_id_val,
                )
                results["skipped"].append(clause_id_val)
                skipped_clauses += 1
                processed_clauses += 1
                continue
            elif completion == "INCOMPLETE_CHECKLIST":
                logger.warning(
                    "Clause %s (id=%s) — checklists missing — generating checklists only",
                    clause_number, clause_id_val,
                )
                from app.models.ai import ControlActivity as _CtrlAct
                from app.models.eve_models import ControlChecklist as _CC
                from app.services.eve_tasks import generate_control_checklist
                activities_for_clause = ComplianceActivities.query.filter_by(
                    clause_id=clause_id_val
                ).all()
                for act in activities_for_clause:
                    ctrl = _CtrlAct.query.filter_by(compliance_activity_id=act.id).first()
                    if ctrl:
                        existing_cc = _CC.query.filter_by(control_activity_id=ctrl.id).first()
                        if not existing_cc or not existing_cc.raw_output_json:
                            generate_control_checklist(ctrl.id)
                results["skipped"].append(clause_id_val)
                skipped_clauses += 1
                processed_clauses += 1
                continue
            elif completion == "INCOMPLETE_STRUCTURE":
                logger.warning(
                    "Clause %s (id=%s) is INCOMPLETE_STRUCTURE — deleting and regenerating",
                    clause_number, clause_id_val,
                )
                _delete_clause_data(clause_id_val)

            # Update progress with current clause info
            update_compliance_progress(
                self.request.id,
                "PROCESSING",
                15 + (processed_clauses / total_clauses) * 60,
                f"Extracting activities for clause {clause_number}...",
                processed_clauses,
                total_clauses,
                clause_id_val,
            )

            with session_scope() as session:
                # SIMPLIFIED: Direct extraction without vector store
                compliance_data = _extract_compliance_activities_direct(
                    clause_text, department_list
                )

                if (
                    not compliance_data
                    or "compliance_activities" not in compliance_data
                ):
                    logger.warning(
                        "No compliance activities for clause %s", clause_number
                    )
                    results["activities"].append({clause_id_val: []})
                    processed_clauses += 1
                    continue

                activities = compliance_data["compliance_activities"]

                if not activities:
                    logger.warning("Empty activities list for clause %s", clause_number)
                    results["activities"].append({clause_id_val: []})
                    processed_clauses += 1
                    continue

                logger.info(
                    "Found %d compliance activities for clause %s",
                    len(activities),
                    clause_number,
                )

                saved_activities = []

                for index, act in enumerate(activities, start=1):
                    # Ensure activity_id is numerical
                    activity_id_from_ai = act.get("activity_id", "")
                    try:
                        import re

                        numbers = re.findall(r"\d+", str(activity_id_from_ai))
                        if numbers:
                            activity_id = numbers[0]
                        else:
                            activity_id = str(index)
                    except (ValueError, TypeError):
                        activity_id = str(index)

                    # Resolve department
                    raw_dept_id = None
                    try:
                        raw_dept_id = int(act.get("department_id", 0) or 0)
                    except Exception:
                        raw_dept_id = None

                    dept_obj = None
                    if raw_dept_id:
                        dept_obj = (
                            session.query(OrganizationDepartments)
                            .filter_by(department_id=raw_dept_id)
                            .first()
                        )

                    if not dept_obj:
                        dept_name_from_ai = (
                            act.get("relevant_departments")
                            or act.get("department_name")
                            or "Unknown"
                        )
                        # Try to find matching department
                        ai_lower = dept_name_from_ai.strip().lower()
                        for d in department_list:
                            dn = (d.get("department_name") or "").strip()
                            if dn and (
                                ai_lower in dn.lower() or dn.lower() in ai_lower
                            ):
                                dept_obj = (
                                    session.query(OrganizationDepartments)
                                    .filter_by(department_id=d["department_id"])
                                    .first()
                                )
                                if dept_obj:
                                    break

                    if not dept_obj:
                        dept_to_create_name = (
                            act.get("relevant_departments") or "Unknown"
                        )
                        dept_obj = OrganizationDepartments(
                            department_name=dept_to_create_name
                        )
                        session.add(dept_obj)
                        session.flush()

                    relevant_departments_id_val = getattr(
                        dept_obj, "department_id", None
                    )

                    comp = ComplianceActivities(
                        clause_id=clause_id_val,
                        relevant_departments_id=relevant_departments_id_val,
                        relevant_departments=act.get("relevant_departments", ""),
                        process=act.get("process_name", ""),
                        sub_process=act.get("sub_process_name", ""),
                        activity_id=activity_id,
                        activity_description=act.get("activity_description", ""),
                        responsible_party=act.get("responsible_party", ""),
                        frequency=act.get("frequency", ""),
                        evidence_required=act.get("evidence_required", ""),
                        compliance_level=act.get("compliance_level", "Design"),
                    )
                    session.add(comp)
                    session.flush()
                    comp_id_val = comp.id
                    saved_activities.append(comp_id_val)

                    # Generate test procedures for this activity
                    _generate_test_procedure_for_activity(comp_id_val, clause_text, act)

                results["activities"].append({clause_id_val: saved_activities})
                processed_clauses += 1

        # Final completion
        total_activities = sum(len(item.values()) for item in results["activities"])
        update_compliance_progress(
            self.request.id,
            "COMPLETED",
            100,
            f"Successfully generated {total_activities} compliance activities and test procedures for {processed_clauses} selected clauses!",
            processed_clauses,
            total_clauses,
        )

        logger.info(f"Selective extraction completed for guideline_id={guideline_id}")
        # Auto-queue any missing test procedures after completion
        try:
            from sqlalchemy import text as sql_text
            with session_scope() as cleanup_session:
                missing = cleanup_session.execute(sql_text("""
                    SELECT ca.id FROM compliance_activities ca
                    JOIN clauses c ON ca.clause_id = c.id
                    LEFT JOIN control_activities cta ON cta.compliance_activity_id = ca.id
                    WHERE c.guideline_id = :gid AND cta.id IS NULL
                """), {'gid': guideline_id}).fetchall()
                for row in missing:
                    extract_test_procedures.delay(row[0])
                if missing:
                    logger.info("Auto-queued %d missing test procedures for guideline %s", len(missing), guideline_id)
        except Exception as e:
            logger.warning("Auto-cleanup for missing test procedures failed: %s", e)

        return {"status": "success", "guideline_id": guideline_id, "results": results}

    except Exception as e:
        logger.exception("Selective extraction failed")
        update_compliance_progress(
            self.request.id,
            "FAILED",
            100,
            f"Compliance activities extraction failed: {str(e)}",
        )
        self.update_state(
            state="FAILURE",
            meta={"exc_type": type(e).__name__, "exc_message": str(e)},
        )
        raise


def _extract_compliance_activities_direct(
    clause_text: str, department_list: list
) -> dict:
    """
    Direct extraction of compliance activities without vector database
    Uses the same approach as your working individual method
    """
    try:
        from app.services.pdf_service import PDFService

        # Create PDFService instance to use the working method
        pdf_service = PDFService()

        # Use the same method that works for individual clauses
        compliance_data = pdf_service.retrive_regulatory_complience(
            clause_text, ""  # Empty text since we're using direct clause text
        )

        if compliance_data:
            import json
            result = json.loads(compliance_data)

            # Hard limit — max 8 activities per clause
            if isinstance(result, dict) and "compliance_activities" in result:
                activities = result["compliance_activities"]
                if len(activities) > 8:
                    logger.warning(f"LLM returned {len(activities)} activities — trimming to 8")
                    result["compliance_activities"] = activities[:8]

                # Fix activity_id — ensure sequential 1,2,3... not 111,222,333
                for idx, act in enumerate(result["compliance_activities"], start=1):
                    act["activity_id"] = str(idx)

            return result

    except Exception as e:
        logger.error("Direct compliance extraction failed: %s", str(e))

    return None


def _generate_test_procedure_for_activity(
    comp_id: int, clause_text: str, activity_data: dict
):
    """
    Generate test procedures for a compliance activity using the same approach as individual button
    This mimics the update_control_activity_by_comp_id route logic
    """
    try:
        from app.services.prompt_templates.test_procedure import (
            test_procedure,
            ControlWorkpaper,
        )
        from app.services.model_response import extract_structured_info_2

        # Prepare the data for the LLM call (same as individual route)
        compliance_activity_payload = {
            "activity_id": activity_data.get("activity_id", ""),
            "activity_description": activity_data.get("activity_description", ""),
            "relevant_departments": activity_data.get("relevant_departments", ""),
            "process_name": activity_data.get("process_name", ""),
            "sub_process_name": activity_data.get("sub_process_name", ""),
            "responsible_party": activity_data.get("responsible_party", ""),
            "frequency": activity_data.get("frequency", ""),
            "evidence_required": activity_data.get("evidence_required", ""),
            "compliance_level": activity_data.get("compliance_level", "Design"),
        }

        # Generate test procedure using the same prompt as individual route
        test_procedure_prompt = test_procedure(clause_text, compliance_activity_payload)

        # Use the same LLM call as individual route
        updated_data = extract_structured_info_2(
            test_procedure_prompt, ControlWorkpaper
        )
        updated_data_dict = _as_dict(updated_data) or {}

        with session_scope() as session:
            if not updated_data_dict.get("activity_code"):
                logger.warning("Skipping test procedure for comp_id %s - empty response", comp_id)
                return  # Skip instead of saving null values
            # Find or create the ControlActivity record (same as individual route)
            control = (
                session.query(ControlActivity)
                .filter_by(compliance_activity_id=comp_id)
                .first()
            )

            if not control:
                # Create a new ControlActivity if it doesn't exist
                control = ControlActivity(
                    compliance_activity_id=comp_id,
                    activity_code=f"CA-{comp_id}",
                    activity_name=f"Control for Activity {comp_id}",
                )
                session.add(control)
                session.flush()

            # --- Update the ControlActivity record itself ---
            control.activity_code = updated_data_dict.get("activity_code")
            control.activity_name = updated_data_dict.get("activity_name")
            control.activity_description = updated_data_dict.get("activity_description")
            control.objective = updated_data_dict.get("objective")
            control.owner = updated_data_dict.get("owner")
            control.control_type = updated_data_dict.get("control_type")
            control.frequency = updated_data_dict.get("frequency")
            control.sampling_guidance = updated_data_dict.get("sampling_guidance")
            control.auditor_observation = updated_data_dict.get("auditor_observation")
            control.findings = updated_data_dict.get("findings")
            control.impact = updated_data_dict.get("impact")
            control.severity = updated_data_dict.get("severity")
            control.recommendations = updated_data_dict.get("recommendations")
            control.reviewer_notes = updated_data_dict.get("reviewer_notes")
            control.explain_test_procedure = updated_data_dict.get(
                "explain_test_procedure"
            )

            # --- Handle related records (TestSteps, Interviews, etc.) ---
            # Find or create TestSteps
            test_steps_payload = updated_data_dict.get("test_procedure") or {}
            test_steps = control.test_procedure
            if not test_steps:
                test_steps = TestSteps(control_id=control.id)
                session.add(test_steps)
                session.flush()

            # Update TestSteps attributes in place
            test_steps.walkthrough = _ci_get(test_steps_payload, "walkthrough")
            test_steps.sampling = _ci_get(test_steps_payload, "sampling")

            # Sync Document Reviews
            new_docs_list = (
                test_steps_payload.get("review_of_documentation")
                or test_steps_payload.get("review_of_documents")
                or []
            )
            if isinstance(new_docs_list, (str, bytes)):
                new_docs_list = [new_docs_list]

            existing_doc_names = {doc.document_name for doc in test_steps.documents}
            new_doc_names = set(new_docs_list)

            # Add new documents
            docs_to_add = new_doc_names - existing_doc_names
            for doc_name in docs_to_add:
                session.add(
                    DocumentReview(
                        test_procedure_id=test_steps.id, document_name=doc_name
                    )
                )

            # Sync Interviews
            interviews_data = test_steps_payload.get("interviews") or {}
            interview = test_steps.interviews
            if not interview:
                interview = Interview(test_procedure_id=test_steps.id)
                session.add(interview)
                session.flush()

            # Sync Interview Roles
            new_roles = set(interviews_data.get("roles") or [])
            existing_roles = {role.role for role in interview.roles}
            roles_to_add = new_roles - existing_roles
            for role_name in roles_to_add:
                session.add(InterviewRole(interview_id=interview.id, role=role_name))

            # Sync Interview Questions
            new_questions = set(
                interviews_data.get("key_questions")
                or interviews_data.get("questions")
                or []
            )
            existing_questions = {q.question for q in interview.questions}
            questions_to_add = new_questions - existing_questions
            for question_text in questions_to_add:
                session.add(
                    InterviewQuestion(interview_id=interview.id, question=question_text)
                )

            # Evidence artifacts: Clear existing and add new
            control.evidences.clear()
            evidence_input = updated_data_dict.get("evidences_artifacts_needed") or []
            if isinstance(evidence_input, dict):
                iter_evidence = (
                    (k, v if isinstance(v, list) else [v])
                    for k, v in evidence_input.items()
                )
            elif isinstance(evidence_input, list):

                def _yield_from_list(lst):
                    for entry in lst:
                        if not entry:
                            continue
                        if isinstance(entry, dict):
                            cat = (
                                entry.get("category") or entry.get("name") or "Unknown"
                            )
                            items = entry.get("items") or entry.get("items_list") or []
                            yield (cat, items if isinstance(items, list) else [items])
                        else:
                            yield ("Unknown", [str(entry)])

                iter_evidence = _yield_from_list(evidence_input)
            else:
                iter_evidence = []

            for category, items in iter_evidence:
                category = (category or "Unknown").strip()
                for item in items or []:
                    artifact = (
                        session.query(EvidenceArtifact)
                        .filter_by(category=category, item=item)
                        .first()
                    )
                    if not artifact:
                        artifact = EvidenceArtifact(category=category, item=item)
                        session.add(artifact)
                    control.evidences.append(artifact)

            session.flush()
            logger.info(f"Generated test procedure for activity {comp_id}")

    except Exception as e:
        logger.error(
            "Test procedure generation failed for comp_id %s: %s", comp_id, str(e)
        )
        # Re-raise so caller knows this activity is incomplete
        # Clause will be marked INCOMPLETE on next run → delete + regenerate
        raise


def _extract_using_alternative_method(
    clause_text: str, department_list: list, vec_id: str
):
    """
    Alternative extraction method using the same approach as the working individual method
    """
    try:
        from app.services.pdf_service import PDFService

        # Create a temporary PDFService instance
        pdf_service = PDFService()

        # Use the same method that works for individual clauses
        compliance_data = pdf_service.retrive_regulatory_complience(
            clause_text,
            "",  # Empty text since we're not using PDF content in this context
        )

        if compliance_data:
            import json

            claus_json = json.loads(compliance_data)

            # Convert to ComplianceRequirements schema
            from app.services.prompt_templates.compliance_activity import (
                ComplianceRequirements,
            )

            return ComplianceRequirements(**claus_json)

    except Exception as e:
        logger.error("Alternative extraction method failed: %s", str(e))

    return None


def process_test_procedures(
    comp_id: int, clause_text: str, compliance_activity_payload: str, vec_id: str
):
    """
    Extracts test procedures and saves related records.
    Uses its own transactional scope. Accepts raw IDs only.
    """
    logger.info("Started Processing Activity comp_id=%s", comp_id)

    # Ask the model for control workpaper based on the clause text + activity JSON payload
    test_proc_response = extract_structured_info(
        query=test_procedure(clause_text, compliance_activity_payload),
        vector_store_id=vec_id,
        schema=ControlWorkpaper,
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
            assessment_objective=test_data_dict.get("assessment_objective"),
            assessment_objective_rationale=test_data_dict.get("assessment_objective_rationale"),
            test_attributes=test_data_dict.get("test_attributes"),
            compliance_activity_id=comp_id,
        )
        session.add(control)
        session.flush()
        control_id_val = control.id

        # Normalize test_procedure payload keys (case-insensitive)
        test_steps_payload = (
            test_data_dict.get("test_procedure")
            or test_data_dict.get("testProcedure")
            or {}
        )
        # Build TestSteps using case-insensitive getter
        test_steps = TestSteps(
            walkthrough=_ci_get(test_steps_payload, "walkthrough"),
            sampling=_ci_get(test_steps_payload, "sampling"),
            control_id=control_id_val,
        )
        session.add(test_steps)
        session.flush()
        test_steps_id_val = test_steps.id

        # Document reviews
        docs_list = (
            test_steps_payload.get("review_of_documentation")
            or test_steps_payload.get("review_of_documents")
            or []
        )
        if isinstance(docs_list, (str, bytes)):
            docs_list = [docs_list]
        for doc in docs_list or []:
            session.add(
                DocumentReview(test_procedure_id=test_steps_id_val, document_name=doc)
            )

        # Interviews
        interviews_data = test_steps_payload.get("interviews") or {}
        interview = Interview(test_procedure_id=test_steps_id_val)
        session.add(interview)
        session.flush()
        interview_id_val = interview.id
        for role in interviews_data.get("roles") or []:
            session.add(InterviewRole(interview_id=interview_id_val, role=role))
        for question in (
            interviews_data.get("key_questions")
            or interviews_data.get("questions")
            or []
        ):
            session.add(
                InterviewQuestion(interview_id=interview_id_val, question=question)
            )

        # Evidence artifacts: normalize both list and dict shapes
        evidence_input = (
            test_data_dict.get("evidences_artifacts_needed")
            or test_data_dict.get("evidences")
            or []
        )

        if isinstance(evidence_input, dict):
            iter_evidence = (
                (k, v if isinstance(v, list) else [v])
                for k, v in evidence_input.items()
            )
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
            for item in items or []:
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

        logger.info(
            "Activity processing completed for comp_id=%s (control_id=%s)",
            comp_id,
            control_id_val,
        )


@shared_task(bind=True)
def generate_missing_activities_for_guideline(self, guideline_id):
    """
    Cron job to generate activities for clauses without activities in a specific guideline
    """
    logger.info(
        f"Starting missing activities generation for guideline_id={guideline_id}"
    )

    try:
        # Find guideline
        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            raise ValueError(f"Guideline {guideline_id} not found")

        # Find clauses without activities
        clauses_without_activities = Clauses.query.filter(
            Clauses.guideline_id == guideline_id,
            ~Clauses.id.in_(
                db.session.query(ComplianceActivities.clause_id).filter(
                    ComplianceActivities.clause_id.isnot(None)
                )
            ),
        ).all()

        total_clauses = len(clauses_without_activities)

        if total_clauses == 0:
            logger.info(
                f"No clauses without activities found for guideline {guideline_id}"
            )
            return {
                "status": "success",
                "message": "No clauses without activities found",
                "clauses_processed": 0,
            }

        logger.info(
            f"Found {total_clauses} clauses without activities for guideline {guideline_id}"
        )

        # Get file record and vector store
        file_record = File.query.filter_by(id=guideline.file_id).first()
        if not file_record:
            raise ValueError("File record not found for guideline")

        vec_id = file_record.vector_store_id

        # Preload departments
        department_list = [
            {"department_id": d.department_id, "department_name": d.department_name}
            for d in OrganizationDepartments.query.all()
        ]

        processed_clauses = 0
        successful_clauses = 0
        failed_clauses = 0

        # Process each clause without activities
        for i, clause in enumerate(clauses_without_activities):
            try:
                logger.info(f"Processing clause {clause.id} ({clause.clause_no})")

                # Extract compliance activities
                activity_response = extract_structured_info(
                    query=compliance_prompt(clause.clause_text, list(department_list)),
                    vector_store_id=vec_id,
                    schema=ComplianceRequirements,
                )

                if activity_response:
                    parsed_dict = _as_dict(activity_response) or {}
                    activities = (
                        parsed_dict.get("compliance_activities")
                        or parsed_dict.get("activities")
                        or []
                    )

                    if activities:
                        # Save activities to database
                        with session_scope() as session:
                            for index, act in enumerate(activities, start=1):
                                # Ensure activity_id is numerical - use AI response if numerical, otherwise use index
                                activity_id_from_ai = _get(act, "activity_id", "")

                                # Try to extract numerical value, if fails use the index
                                try:
                                    # Extract numbers from string if it contains numbers
                                    import re

                                    numbers = re.findall(
                                        r"\d+", str(activity_id_from_ai)
                                    )
                                    if numbers:
                                        activity_id = numbers[
                                            0
                                        ]  # Take first number found
                                    else:
                                        activity_id = str(
                                            index
                                        )  # Use the loop index as fallback
                                except (ValueError, TypeError):
                                    activity_id = str(
                                        index
                                    )  # Use the loop index as fallback
                                # Department resolution
                                raw_dept_id = None
                                try:
                                    raw_dept_id = int(
                                        _get(act, "department_id", 0) or 0
                                    )
                                except Exception:
                                    raw_dept_id = None

                                dept_obj = None
                                if raw_dept_id:
                                    dept_obj = (
                                        session.query(OrganizationDepartments)
                                        .filter_by(department_id=raw_dept_id)
                                        .first()
                                    )

                                if not dept_obj:
                                    dept_name_from_ai = (
                                        _get(act, "relevant_departments")
                                        or _get(act, "department_name")
                                        or None
                                    )
                                    if dept_name_from_ai:
                                        ai_lower = dept_name_from_ai.strip().lower()
                                        for d in department_list or []:
                                            dn = (
                                                d.get("department_name") or ""
                                            ).strip()
                                            if dn:
                                                dn_l = dn.lower()
                                                if ai_lower in dn_l or dn_l in ai_lower:
                                                    dept_obj = (
                                                        session.query(
                                                            OrganizationDepartments
                                                        )
                                                        .filter_by(
                                                            department_id=d[
                                                                "department_id"
                                                            ]
                                                        )
                                                        .first()
                                                    )
                                                    if dept_obj:
                                                        break

                                if not dept_obj:
                                    dept_to_create_name = (
                                        _get(act, "relevant_departments") or "Unknown"
                                    )
                                    dept_obj = OrganizationDepartments(
                                        department_name=dept_to_create_name
                                    )
                                    session.add(dept_obj)
                                    session.flush()

                                relevant_departments_id_val = getattr(
                                    dept_obj, "department_id", None
                                )

                                comp = ComplianceActivities(
                                    clause_id=clause.id,
                                    relevant_departments_id=relevant_departments_id_val,
                                    relevant_departments=_get(
                                        act, "relevant_departments"
                                    ),
                                    process=_get(act, "process_name"),
                                    sub_process=_get(act, "sub_process_name"),
                                    activity_id=_get(act, "activity_id"),
                                    activity_description=_get(
                                        act, "activity_description"
                                    ),
                                    responsible_party=_get(act, "responsible_party"),
                                    frequency=_get(act, "frequency"),
                                    evidence_required=_get(act, "evidence_required"),
                                    compliance_level=_get(
                                        act, "compliance_level", "Design"
                                    ),
                                )
                                session.add(comp)

                            session.commit()

                        successful_clauses += 1
                        logger.info(f"Successfully processed clause {clause.id}")

                processed_clauses += 1

                # Rate limiting - wait between clauses to avoid OpenAI limits
                if i < len(clauses_without_activities) - 1:
                    time.sleep(35)  # Wait 35 seconds before next clause

            except Exception as e:
                failed_clauses += 1
                logger.error(f"Failed to process clause {clause.id}: {str(e)}")
                continue

        logger.info(
            f"Completed missing activities generation for guideline {guideline_id}"
        )
        return {
            "status": "success",
            "message": f"Processed {processed_clauses} clauses: {successful_clauses} successful, {failed_clauses} failed",
            "guideline_id": guideline_id,
            "total_clauses": total_clauses,
            "successful_clauses": successful_clauses,
            "failed_clauses": failed_clauses,
        }

    except Exception as e:
        logger.exception(
            f"Failed to generate missing activities for guideline {guideline_id}"
        )
        return {"status": "error", "message": str(e), "guideline_id": guideline_id}


@shared_task(bind=True)
def generate_single_clause_activities(self, guideline_id: int, clause_id: int):
    """
    Generate activities for a single specific clause
    """
    logger.info(
        f"Starting single clause activity generation for guideline_id={guideline_id}, clause_id={clause_id}"
    )

    try:
        # Verify clause exists and belongs to guideline
        clause = Clauses.query.filter_by(
            id=clause_id, guideline_id=guideline_id
        ).first()
        if not clause:
            raise ValueError(
                f"Clause {clause_id} not found in guideline {guideline_id}"
            )

        # Check if clause already has activities
        existing_activities = ComplianceActivities.query.filter_by(
            clause_id=clause_id
        ).first()
        if existing_activities:
            return {
                "status": "skipped",
                "message": f"Clause {clause_id} already has compliance activities",
                "clause_id": clause_id,
            }

        # Use the selective extraction function for this single clause - pass as list
        result = extract_selected_activities_and_tests(guideline_id, [clause_id])

        return {
            "status": "success",
            "guideline_id": guideline_id,
            "clause_id": clause_id,
            "result": result,
        }

    except Exception as e:
        logger.exception(f"Error generating activities for clause {clause_id}")
        self.update_state(
            state="FAILURE",
            meta={"exc_type": type(e).__name__, "exc_message": str(e)},
        )
        raise
