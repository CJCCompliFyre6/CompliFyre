# app/routes/audit/eve_audit_routes.py
#
# Module H — Auditor side API routes for EVE v2 pipeline
#
# Routes:
#   POST /audit/eve/control/<id>/run-step5        — trigger Step 5 for all evidence
#   GET  /audit/eve/control/<id>/step5-status     — check Step 5 results
#   POST /audit/eve/control/<id>/run-step67       — trigger Steps 6+7
#   GET  /audit/eve/control/<id>/step67-status    — check Steps 6+7 results
#   POST /audit/eve/clause/<id>/run-step8         — trigger Step 8 clause rollup
#   GET  /audit/eve/clause/<id>/step8-status      — check Step 8 results
#   GET  /audit/eve/control/<id>/full-result      — get complete EVE result
#   GET  /audit/eve/clause/<id>/full-result       — get complete clause result
#   POST /audit/eve/control/<id>/run-full-pipeline — run Steps 5+6+7 in sequence

from flask import Blueprint, jsonify, request, current_app
from flask_login import login_required, current_user
from sqlalchemy.orm import joinedload

from app import db
from app.models.project_instance_models import (
    ProjectControlActivity,
    ProjectEvidenceArtifact,
    ProjectComplianceActivity,
    ProjectClause,
)
from app.models.eve_models import (
    ProjectChecklist,
    EveEvidenceResult,
    EveControlResult,
)
from app.utils.permission_handler import role_required
from app.services.eve_step5 import (
    run_eve_step5_for_evidence,
    run_eve_step5_for_all_evidence,
)
from app.services.eve_step678 import (
    run_eve_step6_and_7,
    run_eve_step8_clause_rollup,
)

eve_audit_bp = Blueprint("eve_audit", __name__)


# ─────────────────────────────────────────────────────────────
# Helper — get upload base path
# ─────────────────────────────────────────────────────────────

def _get_upload_base():
    import os
    return current_app.config.get(
        "UPLOAD_FOLDER_EVIDENCE",
        os.path.join(current_app.root_path, "../uploads"),
    )


# ─────────────────────────────────────────────────────────────
# MODULE D routes — EVE Step 5
# ─────────────────────────────────────────────────────────────

@eve_audit_bp.route("/audit/eve/control/<int:pca_id>/run-step5", methods=["POST"])
@login_required
@role_required("AUDITOR")
def trigger_step5(pca_id):
    """
    Trigger EVE Step 5 for ALL evidence under a control activity.
    Dispatches one Celery task per evidence artifact.
    """
    # Validate control activity exists
    pca = db.session.query(ProjectControlActivity).get(pca_id)
    if not pca:
        return jsonify({"status": "error", "message": f"Control activity {pca_id} not found"}), 404

    # Get project checklist
    checklist = db.session.query(ProjectChecklist).filter_by(
        project_control_activity_id=pca_id
    ).first()
    if not checklist:
        return jsonify({
            "status": "error",
            "message": "No checklist found for this control activity — contact your admin to generate it",
        }), 400

    if not checklist.checklist_json:
        return jsonify({
            "status": "error",
            "message": "Checklist is empty — contact your admin to regenerate it",
        }), 400

    # Check evidence exists
    evidence_count = db.session.query(ProjectEvidenceArtifact).filter_by(
        project_control_activity_id=pca_id
    ).count()
    if evidence_count == 0:
        return jsonify({
            "status": "error",
            "message": "No evidence found — please upload evidence first",
        }), 400

    # Trigger bulk Step 5 task
    task = run_eve_step5_for_all_evidence.apply_async(
        args=[checklist.id],
        kwargs={"upload_base_path": _get_upload_base()},
        queue="eve_evaluate",
    )

    # Update checklist status
    checklist.status = "in_progress"
    db.session.commit()

    return jsonify({
        "status": "started",
        "message": f"Step 5 started for {evidence_count} evidence artifact(s)",
        "pca_id": pca_id,
        "checklist_id": checklist.id,
        "evidence_count": evidence_count,
        "task_id": task.id,
    }), 202


@eve_audit_bp.route("/audit/eve/control/<int:pca_id>/step5-status", methods=["GET"])
@login_required
@role_required("AUDITOR")
def get_step5_status(pca_id):
    """
    Check Step 5 completion status for a control activity.
    Returns how many checklist items have been evaluated per evidence.
    """
    checklist = db.session.query(ProjectChecklist).filter_by(
        project_control_activity_id=pca_id
    ).first()
    if not checklist:
        return jsonify({"status": "error", "message": "No checklist found"}), 404

    evidence_artifacts = db.session.query(ProjectEvidenceArtifact).filter_by(
        project_control_activity_id=pca_id
    ).all()

    total_evidence = len(evidence_artifacts)
    evaluated_evidence_ids = {
        r.evidence_artifact_id
        for r in db.session.query(EveEvidenceResult.evidence_artifact_id)
        .filter_by(project_checklist_id=checklist.id)
        .distinct()
        .all()
    }

    total_results = db.session.query(EveEvidenceResult).filter_by(
        project_checklist_id=checklist.id
    ).count()

    # Signal breakdown
    signal_counts = {}
    results = db.session.query(EveEvidenceResult).filter_by(
        project_checklist_id=checklist.id
    ).all()
    for r in results:
        signal_counts[r.signal] = signal_counts.get(r.signal, 0) + 1

    all_evaluated = (
        total_evidence > 0 and
        len(evaluated_evidence_ids) >= total_evidence
    )

    return jsonify({
        "status": "completed" if all_evaluated else "in_progress",
        "pca_id": pca_id,
        "checklist_id": checklist.id,
        "checklist_status": checklist.status,
        "total_evidence": total_evidence,
        "evaluated_evidence": len(evaluated_evidence_ids),
        "total_results": total_results,
        "signal_breakdown": signal_counts,
        "ready_for_step6": all_evaluated,
    }), 200


# ─────────────────────────────────────────────────────────────
# MODULE E+F routes — EVE Steps 6+7
# ─────────────────────────────────────────────────────────────

@eve_audit_bp.route("/audit/eve/control/<int:pca_id>/run-step67", methods=["POST"])
@login_required
@role_required("AUDITOR")
def trigger_step67(pca_id):
    """
    Trigger EVE Steps 6+7 for a control activity.
    Step 5 must be complete first.
    """
    pca = db.session.query(ProjectControlActivity).get(pca_id)
    if not pca:
        return jsonify({"status": "error", "message": f"Control activity {pca_id} not found"}), 404

    # Check Step 5 results exist
    checklist = db.session.query(ProjectChecklist).filter_by(
        project_control_activity_id=pca_id
    ).first()
    if not checklist:
        return jsonify({"status": "error", "message": "No checklist found — run Step 5 first"}), 400

    step5_count = db.session.query(EveEvidenceResult).filter_by(
        project_checklist_id=checklist.id
    ).count()
    if step5_count == 0:
        return jsonify({
            "status": "error",
            "message": "No Step 5 results found — run Step 5 first",
        }), 400

    # Check if already completed
    existing = db.session.query(EveControlResult).filter_by(
        project_control_activity_id=pca_id
    ).first()
    if existing and existing.step7_completed:
        return jsonify({
            "status": "already_completed",
            "message": "Steps 6+7 already completed — use full-result to view",
            "pca_id": pca_id,
            "final_status": existing.final_status,
            "final_severity": existing.final_severity,
        }), 200

    # Trigger task
    task = run_eve_step6_and_7.apply_async(
        args=[pca_id],
        kwargs={"generated_by": current_user.id},
        queue="eve_evaluate",
    )

    return jsonify({
        "status": "started",
        "message": "Steps 6+7 (Aggregation + Recommendations) started",
        "pca_id": pca_id,
        "task_id": task.id,
    }), 202


@eve_audit_bp.route("/audit/eve/control/<int:pca_id>/step67-status", methods=["GET"])
@login_required
@role_required("AUDITOR")
def get_step67_status(pca_id):
    """Check Steps 6+7 completion status for a control activity."""
    result = db.session.query(EveControlResult).filter_by(
        project_control_activity_id=pca_id
    ).first()

    if not result:
        return jsonify({
            "status": "pending",
            "message": "Steps 6+7 not yet started",
            "pca_id": pca_id,
        }), 200

    return jsonify({
        "status": "completed" if result.step7_completed else "in_progress",
        "pca_id": pca_id,
        "step6_completed": result.step6_completed,
        "step7_completed": result.step7_completed,
        "final_status": result.final_status,
        "final_severity": result.final_severity,
        "findings_count": result.findings_count,
        "checklist_pass_count": result.checklist_pass_count,
        "checklist_partial_count": result.checklist_partial_count,
        "checklist_fail_count": result.checklist_fail_count,
        "ready_for_step8": result.step7_completed,
    }), 200


# ─────────────────────────────────────────────────────────────
# MODULE G routes — EVE Step 8
# ─────────────────────────────────────────────────────────────

@eve_audit_bp.route("/audit/eve/clause/<int:project_clause_id>/run-step8", methods=["POST"])
@login_required
@role_required("AUDITOR")
def trigger_step8(project_clause_id):
    """
    Trigger EVE Step 8 clause rollup.
    ALL control activities under this clause must have Steps 6+7 complete.
    """
    project_clause = db.session.query(ProjectClause).get(project_clause_id)
    if not project_clause:
        return jsonify({"status": "error", "message": f"ProjectClause {project_clause_id} not found"}), 404

    # Check all controls under this clause have Steps 6+7 done
    pcas = (
        db.session.query(ProjectControlActivity)
        .join(ProjectComplianceActivity,
              ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id)
        .filter(ProjectComplianceActivity.project_clause_id == project_clause_id)
        .all()
    )

    if not pcas:
        return jsonify({"status": "error", "message": "No control activities found under this clause"}), 400

    pca_ids = [pca.id for pca in pcas]
    completed_results = db.session.query(EveControlResult).filter(
        EveControlResult.project_control_activity_id.in_(pca_ids),
        EveControlResult.step7_completed == True,
    ).all()

    pending_count = len(pca_ids) - len(completed_results)
    if pending_count > 0:
        return jsonify({
            "status": "error",
            "message": f"{pending_count} control activity(ies) still pending Steps 6+7 — complete them first",
            "total_controls": len(pca_ids),
            "completed_controls": len(completed_results),
            "pending_count": pending_count,
        }), 400

    # Trigger Step 8
    task = run_eve_step8_clause_rollup.apply_async(
        args=[project_clause_id],
        kwargs={"generated_by": current_user.id},
        queue="eve_evaluate",
    )

    return jsonify({
        "status": "started",
        "message": "Step 8 clause rollup started",
        "project_clause_id": project_clause_id,
        "controls_to_aggregate": len(pca_ids),
        "task_id": task.id,
    }), 202


@eve_audit_bp.route("/audit/eve/clause/<int:project_clause_id>/step8-status", methods=["GET"])
@login_required
@role_required("AUDITOR")
def get_step8_status(project_clause_id):
    """Check Step 8 clause rollup status."""
    pcas = (
        db.session.query(ProjectControlActivity)
        .join(ProjectComplianceActivity,
              ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id)
        .filter(ProjectComplianceActivity.project_clause_id == project_clause_id)
        .all()
    )

    if not pcas:
        return jsonify({"status": "error", "message": "No control activities found"}), 404

    pca_ids = [pca.id for pca in pcas]
    results = db.session.query(EveControlResult).filter(
        EveControlResult.project_control_activity_id.in_(pca_ids),
        EveControlResult.step8_completed == True,
    ).all()

    if not results:
        return jsonify({
            "status": "pending",
            "message": "Step 8 not yet completed",
            "project_clause_id": project_clause_id,
        }), 200

    # Get clause rollup from first result (all have same clause_rollup_json)
    rollup = results[0].clause_rollup_json or {}

    return jsonify({
        "status": "completed",
        "project_clause_id": project_clause_id,
        "clause_status": rollup.get("clause_status", ""),
        "clause_severity": rollup.get("clause_severity", ""),
        "findings_count": len(rollup.get("findings", [])),
        "recommendations_count": len(rollup.get("recommendations", [])),
        "controls_aggregated": len(results),
    }), 200


# ─────────────────────────────────────────────────────────────
# FULL RESULT endpoints — for UI rendering
# ─────────────────────────────────────────────────────────────

@eve_audit_bp.route("/audit/eve/control/<int:pca_id>/full-result", methods=["GET"])
@login_required
@role_required("AUDITOR")
def get_control_full_result(pca_id):
    """
    Get complete EVE result for a control activity.
    Returns all checklist summary, observations, findings, recommendations.
    """
    result = db.session.query(EveControlResult).filter_by(
        project_control_activity_id=pca_id
    ).first()

    if not result:
        return jsonify({
            "status": "pending",
            "message": "EVE evaluation not yet run for this control activity",
            "pca_id": pca_id,
        }), 200

    # Get evidence signals summary
    checklist = db.session.query(ProjectChecklist).filter_by(
        project_control_activity_id=pca_id
    ).first()

    evidence_signals = []
    if checklist:
        signals = db.session.query(EveEvidenceResult).filter_by(
            project_checklist_id=checklist.id
        ).all()
        evidence_signals = [r.to_dict() for r in signals]

    return jsonify({
        "status": "completed" if result.step7_completed else "partial",
        "pca_id": pca_id,
        "final_status": result.final_status,
        "final_severity": result.final_severity,
        "findings_count": result.findings_count,
        "critical_findings_count": result.critical_findings_count,
        "high_findings_count": result.high_findings_count,
        "checklist_pass_count": result.checklist_pass_count,
        "checklist_partial_count": result.checklist_partial_count,
        "checklist_fail_count": result.checklist_fail_count,
        "step6_completed": result.step6_completed,
        "step7_completed": result.step7_completed,
        "step8_completed": result.step8_completed,
        "checklist_summary": result.checklist_summary_json or [],
        "observations": result.observations_json or [],
        "findings": result.findings_json or [],
        "recommendations": result.recommendations_json or [],
        "evidence_signals": evidence_signals,
        "generated_at": result.generated_at.isoformat() if result.generated_at else None,
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
    }), 200


@eve_audit_bp.route("/audit/eve/clause/<int:project_clause_id>/full-result", methods=["GET"])
@login_required
@role_required("AUDITOR")
def get_clause_full_result(project_clause_id):
    """
    Get complete EVE clause rollup result.
    Returns consolidated observations, grouped findings, recommendations.
    """
    pcas = (
        db.session.query(ProjectControlActivity)
        .join(ProjectComplianceActivity,
              ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id)
        .filter(ProjectComplianceActivity.project_clause_id == project_clause_id)
        .all()
    )

    if not pcas:
        return jsonify({"status": "error", "message": "No control activities found"}), 404

    pca_ids = [pca.id for pca in pcas]
    results = db.session.query(EveControlResult).filter(
        EveControlResult.project_control_activity_id.in_(pca_ids),
        EveControlResult.step8_completed == True,
    ).first()

    if not results:
        return jsonify({
            "status": "pending",
            "message": "Step 8 clause rollup not yet completed",
            "project_clause_id": project_clause_id,
        }), 200

    rollup = results.clause_rollup_json or {}

    return jsonify({
        "status": "completed",
        "project_clause_id": project_clause_id,
        "clause_status": rollup.get("clause_status", ""),
        "clause_severity": rollup.get("clause_severity", ""),
        "summary": rollup.get("summary", ""),
        "observations": rollup.get("observations", []),
        "findings": rollup.get("findings", []),
        "recommendations": rollup.get("recommendations", []),
    }), 200


# ─────────────────────────────────────────────────────────────
# PIPELINE route — run Steps 5+6+7 in one call
# Triggers Step 5, then Step 6+7 is triggered automatically
# after Step 5 completes via a chained task
# ─────────────────────────────────────────────────────────────

@eve_audit_bp.route("/audit/eve/control/<int:pca_id>/run-full-pipeline", methods=["POST"])
@login_required
@role_required("AUDITOR")
def trigger_full_pipeline(pca_id):
    """
    Run full EVE pipeline for a control activity:
    Step 5 (evidence execution) → Step 6+7 (aggregation + recommendations)

    Step 5 runs first. After polling confirms Step 5 is done,
    call /run-step67 to proceed. Or use this endpoint which
    triggers both — Step 6+7 will wait and retry if Step 5 not done.
    """
    pca = db.session.query(ProjectControlActivity).get(pca_id)
    if not pca:
        return jsonify({"status": "error", "message": f"Control activity {pca_id} not found"}), 404

    checklist = db.session.query(ProjectChecklist).filter_by(
        project_control_activity_id=pca_id
    ).first()
    if not checklist or not checklist.checklist_json:
        return jsonify({
            "status": "error",
            "message": "No checklist found — contact admin to generate checklist first",
        }), 400

    evidence_count = db.session.query(ProjectEvidenceArtifact).filter_by(
        project_control_activity_id=pca_id
    ).count()
    if evidence_count == 0:
        return jsonify({
            "status": "error",
            "message": "No evidence found — upload evidence first",
        }), 400

    # Trigger Step 5
    step5_task = run_eve_step5_for_all_evidence.apply_async(
        args=[checklist.id],
        kwargs={"upload_base_path": _get_upload_base()},
        queue="eve_evaluate",
    )

    # Trigger Step 6+7 with a delay — gives Step 5 time to complete
    # Step 6+7 will fail gracefully if Step 5 not done and can be retried
    step67_task = run_eve_step6_and_7.apply_async(
        args=[pca_id],
        kwargs={"generated_by": current_user.id},
        queue="eve_evaluate",
        countdown=60,  # wait 60 seconds before starting Step 6+7
    )

    checklist.status = "in_progress"
    db.session.commit()

    return jsonify({
        "status": "started",
        "message": f"Full pipeline started — Step 5 running for {evidence_count} evidence, Step 6+7 queued",
        "pca_id": pca_id,
        "evidence_count": evidence_count,
        "step5_task_id": step5_task.id,
        "step67_task_id": step67_task.id,
        "polling_url": f"/audit/eve/control/{pca_id}/step67-status",
    }), 202
