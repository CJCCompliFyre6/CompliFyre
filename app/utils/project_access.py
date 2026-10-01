from flask import abort
from flask_login import current_user


def can_edit_project(project, user=None):
    """Only the user who created a project may edit it."""
    user = user or current_user
    if project is None or not getattr(user, "is_authenticated", False):
        return False
    return project.created_by is not None and project.created_by == user.id


def require_project_edit(project):
    """Stop the request with 403 Forbidden if the current user can't edit this project."""
    if not can_edit_project(project):
        abort(403)


# ---------------------------------------------------------------------------
# Lookups: find the parent project from whatever ID a route receives.
# Each returns a Projects object, or None if the ID is invalid / not found.
# ---------------------------------------------------------------------------

_UP_FROM_PCA = (
    " JOIN project_compliance_activities pcma ON pca.project_compliance_activity_id = pcma.id"
    " JOIN project_clauses pc ON pcma.project_clause_id = pc.id"
    " JOIN project_guidelines pg ON pc.project_guideline_id = pg.id"
)


def _project_from_sql(sql, raw_id):
    from app.models.auditOrganization import db, Projects
    try:
        record_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    row = db.session.execute(db.text(sql), {"id": record_id}).fetchone()
    if not row or row[0] is None:
        return None
    return Projects.query.get(row[0])


def project_by_id(project_id):
    return _project_from_sql("SELECT id FROM projects WHERE id = :id", project_id)


def project_by_name(project_name, firm_id):
    from app.models.auditOrganization import Projects
    if not project_name:
        return None
    return Projects.query.filter_by(project_name=project_name, auditing_firm=firm_id).first()


def project_for_guideline(project_guideline_id):
    return _project_from_sql(
        "SELECT project_id FROM project_guidelines WHERE id = :id", project_guideline_id
    )


def project_for_clause(project_clause_id):
    return _project_from_sql(
        "SELECT pg.project_id FROM project_clauses pc"
        " JOIN project_guidelines pg ON pc.project_guideline_id = pg.id"
        " WHERE pc.id = :id",
        project_clause_id,
    )


def project_for_control_activity(pca_id):
    return _project_from_sql(
        "SELECT pg.project_id FROM project_control_activities pca" + _UP_FROM_PCA +
        " WHERE pca.id = :id",
        pca_id,
    )


def project_for_test_step(test_step_id):
    return _project_from_sql(
        "SELECT pg.project_id FROM project_test_steps pts"
        " JOIN project_control_activities pca ON pts.project_control_activity_id = pca.id"
        + _UP_FROM_PCA + " WHERE pts.id = :id",
        test_step_id,
    )


def project_for_interview_question(question_id):
    return _project_from_sql(
        "SELECT pg.project_id FROM project_interview_questions piq"
        " JOIN project_interviews pi ON piq.project_interview_id = pi.id"
        " JOIN project_test_steps pts ON pi.project_test_procedure_id = pts.id"
        " JOIN project_control_activities pca ON pts.project_control_activity_id = pca.id"
        + _UP_FROM_PCA + " WHERE piq.id = :id",
        question_id,
    )


def project_for_evidence_artifact(artifact_id):
    return _project_from_sql(
        "SELECT pg.project_id FROM project_evidence_artifacts pea"
        " JOIN project_control_activities pca ON pea.project_control_activity_id = pca.id"
        + _UP_FROM_PCA + " WHERE pea.id = :id",
        artifact_id,
    )


def project_for_evidence_file(file_id):
    return _project_from_sql(
        "SELECT pg.project_id FROM evidence_files ef"
        " JOIN project_evidence_artifacts pea ON ef.project_evidence_artifact_id = pea.id"
        " JOIN project_control_activities pca ON pea.project_control_activity_id = pca.id"
        + _UP_FROM_PCA + " WHERE ef.id = :id",
        file_id,
    )


def project_for_inquiry(inquiry_id):
    return _project_from_sql(
        "SELECT pg.project_id FROM eve_inquiry ei"
        " JOIN project_checklist pcl ON ei.project_checklist_id = pcl.id"
        " JOIN project_control_activities pca ON pcl.project_control_activity_id = pca.id"
        + _UP_FROM_PCA + " WHERE ei.id = :id",
        inquiry_id,
    )
