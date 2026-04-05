# app/routes/re/eve_routes.py
#
# Module A + B — API routes for triggering EVE tasks from RE dashboard
#
# Routes:
#   POST /re/eve/guideline/<id>/generate-context     — Module A
#   GET  /re/eve/guideline/<id>/context-status       — check Module A result
#   POST /re/eve/control/<id>/generate-checklist     — Module B
#   GET  /re/eve/control/<id>/checklist-status       — check Module B result
#   POST /re/eve/guideline/<id>/generate-all-checklists — Module B bulk
#
# These are JSON APIs called from the RE dashboard UI (fetch/AJAX).
# No templates needed — responses are JSON.

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app import db
from app.models.ai import Guidelines, ControlActivity, ComplianceActivities, Clauses
from app.models.eve_models import GuidelineEveContext, ControlChecklist
from app.utils.permission_handler import role_required
from app.services.eve_tasks import (
    generate_guideline_eve_context,
    generate_control_checklist,
)

eve_re_bp = Blueprint("eve_re", __name__)


# ─────────────────────────────────────────────────────────────
# MODULE A — Context Classification
# ─────────────────────────────────────────────────────────────

@eve_re_bp.route("/re/eve/guideline/<int:guideline_id>/generate-context", methods=["POST"])
@login_required
@role_required("RE")
def trigger_guideline_context(guideline_id):
    """
    Trigger EVE Step 1 context classification for a guideline.
    Runs as a Celery background task.

    Returns task_id immediately — poll /context-status to check result.
    """
    # Check guideline exists
    guideline = db.session.query(Guidelines).get(guideline_id)
    if not guideline:
        return jsonify({
            "status": "error",
            "message": f"Guideline {guideline_id} not found"
        }), 404

    # Check if already done
    existing = (
        db.session.query(GuidelineEveContext)
        .filter_by(guideline_id=guideline_id)
        .first()
    )
    if existing:
        return jsonify({
            "status": "already_exists",
            "message": "Context already classified — no need to regenerate",
            "guideline_id": guideline_id,
            "regulation_type": existing.regulation_type,
            "domain": existing.domain,
            "auditor_profile": existing.auditor_profile,
            "generated_at": existing.generated_at.isoformat() if existing.generated_at else None,
        }), 200

    # Trigger Celery task
    task = generate_guideline_eve_context.apply_async(
        args=[guideline_id],
        kwargs={"generated_by": current_user.id},
        queue="eve_context",
    )

    return jsonify({
        "status": "started",
        "message": "Context classification started in background",
        "guideline_id": guideline_id,
        "task_id": task.id,
    }), 202


@eve_re_bp.route("/re/eve/guideline/<int:guideline_id>/context-status", methods=["GET"])
@login_required
@role_required("RE")
def get_guideline_context_status(guideline_id):
    """
    Check the EVE context classification status for a guideline.
    Poll this after triggering /generate-context.
    """
    existing = (
        db.session.query(GuidelineEveContext)
        .filter_by(guideline_id=guideline_id)
        .first()
    )

    if existing:
        return jsonify({
            "status": "completed",
            "guideline_id": guideline_id,
            "regulation_type": existing.regulation_type,
            "domain": existing.domain,
            "auditor_profile": existing.auditor_profile,
            "generated_at": existing.generated_at.isoformat() if existing.generated_at else None,
        }), 200

    return jsonify({
        "status": "pending",
        "message": "Context classification not yet completed",
        "guideline_id": guideline_id,
    }), 200


# ─────────────────────────────────────────────────────────────
# MODULE B — Checklist Generation (single control activity)
# ─────────────────────────────────────────────────────────────

@eve_re_bp.route("/re/eve/control/<int:control_activity_id>/generate-checklist", methods=["POST"])
@login_required
@role_required("RE")
def trigger_control_checklist(control_activity_id):
    """
    Trigger EVE Steps 3+4 checklist generation for a single control activity.
    Runs as a Celery background task.

    Returns task_id immediately — poll /checklist-status to check result.
    """
    # Check control activity exists
    control = db.session.query(ControlActivity).get(control_activity_id)
    if not control:
        return jsonify({
            "status": "error",
            "message": f"ControlActivity {control_activity_id} not found"
        }), 404

    # Check if already done
    existing = (
        db.session.query(ControlChecklist)
        .filter_by(control_activity_id=control_activity_id)
        .first()
    )
    if existing:
        return jsonify({
            "status": "already_exists",
            "message": "Checklist already generated",
            "control_activity_id": control_activity_id,
            "checklist_id": existing.id,
            "checklist_items_count": len(existing.checklist_json or []),
            "version": existing.version,
            "generated_at": existing.generated_at.isoformat() if existing.generated_at else None,
        }), 200

    # Trigger Celery task
    task = generate_control_checklist.apply_async(
        args=[control_activity_id],
        kwargs={"generated_by": current_user.id},
        queue="eve_checklist",
    )

    return jsonify({
        "status": "started",
        "message": "Checklist generation started in background",
        "control_activity_id": control_activity_id,
        "task_id": task.id,
    }), 202


@eve_re_bp.route("/re/eve/control/<int:control_activity_id>/checklist-status", methods=["GET"])
@login_required
@role_required("RE")
def get_control_checklist_status(control_activity_id):
    """
    Check the checklist generation status for a control activity.
    Poll this after triggering /generate-checklist.
    """
    existing = (
        db.session.query(ControlChecklist)
        .filter_by(control_activity_id=control_activity_id)
        .first()
    )

    if existing:
        return jsonify({
            "status": "completed",
            "control_activity_id": control_activity_id,
            "checklist_id": existing.id,
            "checklist_items_count": len(existing.checklist_json or []),
            "dimension_design": existing.dimension_design,
            "dimension_implementation": existing.dimension_implementation,
            "dimension_operating": existing.dimension_operating,
            "version": existing.version,
            "generated_at": existing.generated_at.isoformat() if existing.generated_at else None,
        }), 200

    return jsonify({
        "status": "pending",
        "message": "Checklist not yet generated",
        "control_activity_id": control_activity_id,
    }), 200


# ─────────────────────────────────────────────────────────────
# MODULE B — Bulk: generate checklists for ALL control
# activities under a guideline in one go
# ─────────────────────────────────────────────────────────────

@eve_re_bp.route("/re/eve/guideline/<int:guideline_id>/generate-all-checklists", methods=["POST"])
@login_required
@role_required("RE")
def trigger_all_checklists_for_guideline(guideline_id):
    """
    Trigger checklist generation for ALL control activities under a guideline.
    Skips control activities that already have a checklist.

    Returns list of task_ids — one per control activity queued.
    """
    # Check guideline exists
    guideline = db.session.query(Guidelines).get(guideline_id)
    if not guideline:
        return jsonify({
            "status": "error",
            "message": f"Guideline {guideline_id} not found"
        }), 404

    # Get all control activities under this guideline
    # Path: Guideline → Clauses → ComplianceActivities → ControlActivity
    control_activities = (
        db.session.query(ControlActivity)
        .join(ComplianceActivities, ControlActivity.compliance_activity_id == ComplianceActivities.id)
        .join(Clauses, ComplianceActivities.clause_id == Clauses.id)
        .filter(Clauses.guideline_id == guideline_id)
        .all()
    )

    if not control_activities:
        return jsonify({
            "status": "error",
            "message": "No control activities found under this guideline",
            "guideline_id": guideline_id,
        }), 404

    # Get already-generated checklist IDs
    existing_ids = {
        row.control_activity_id
        for row in db.session.query(ControlChecklist.control_activity_id)
        .filter(
            ControlChecklist.control_activity_id.in_(
                [ca.id for ca in control_activities]
            )
        )
        .all()
    }

    queued = []
    skipped = []

    for control in control_activities:
        if control.id in existing_ids:
            skipped.append(control.id)
            continue

        task = generate_control_checklist.apply_async(
            args=[control.id],
            kwargs={"generated_by": current_user.id},
            queue="eve_checklist",
        )
        queued.append({
            "control_activity_id": control.id,
            "task_id": task.id,
        })

    return jsonify({
        "status": "started",
        "message": f"Queued {len(queued)} checklist generation tasks",
        "guideline_id": guideline_id,
        "total_controls": len(control_activities),
        "queued_count": len(queued),
        "skipped_count": len(skipped),
        "skipped_ids": skipped,
        "tasks": queued,
    }), 202


# ─────────────────────────────────────────────────────────────
# SUMMARY — get EVE generation status for entire guideline
# ─────────────────────────────────────────────────────────────

@eve_re_bp.route("/re/eve/guideline/<int:guideline_id>/summary", methods=["GET"])
@login_required
@role_required("RE")
def get_guideline_eve_summary(guideline_id):
    """
    Get a full EVE generation summary for a guideline:
    - Context classification status
    - How many control activities have checklists vs pending
    """
    # Context status
    context = (
        db.session.query(GuidelineEveContext)
        .filter_by(guideline_id=guideline_id)
        .first()
    )

    # All control activities under this guideline
    control_activities = (
        db.session.query(ControlActivity)
        .join(ComplianceActivities, ControlActivity.compliance_activity_id == ComplianceActivities.id)
        .join(Clauses, ComplianceActivities.clause_id == Clauses.id)
        .filter(Clauses.guideline_id == guideline_id)
        .all()
    )

    total_controls = len(control_activities)

    # How many have checklists
    checklist_count = 0
    if control_activities:
        checklist_count = (
            db.session.query(ControlChecklist)
            .filter(
                ControlChecklist.control_activity_id.in_(
                    [ca.id for ca in control_activities]
                )
            )
            .count()
        )

    return jsonify({
        "guideline_id": guideline_id,
        "context": {
            "status": "completed" if context else "pending",
            "regulation_type": context.regulation_type if context else None,
            "domain": context.domain if context else None,
            "auditor_profile": context.auditor_profile if context else None,
        },
        "checklists": {
            "total_controls": total_controls,
            "completed": checklist_count,
            "pending": total_controls - checklist_count,
            "completion_percentage": (
                round((checklist_count / total_controls) * 100)
                if total_controls > 0 else 0
            ),
        },
        "ready_for_audit": (
            context is not None and checklist_count == total_controls and total_controls > 0
        ),
    }), 200
