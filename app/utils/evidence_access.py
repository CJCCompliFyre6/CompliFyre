"""
Tenant ownership check for ProjectEvidenceArtifact records.

Real chain, confirmed 2026-08-17 by direct model inspection (no git history
available to trace, so verified against live schema instead):

  ProjectEvidenceArtifact.project_control_activity_id -> ProjectControlActivity.id
  ProjectControlActivity.project_compliance_activity_id -> ProjectComplianceActivity.id
  ProjectComplianceActivity.project_clause_id -> ProjectClause.id
  ProjectClause.project_guideline_id -> ProjectGuideline.id
  ProjectGuideline.project_id -> Projects.id
  Projects.client -> Organizations.organization_id       (client-org side)
  Projects.auditing_firm -> AuditOrganization.id          (audit-firm side)

"Ownership" here is two-sided, per the real relationship model confirmed in
app/models/user.py and app/routes/re/view.py: a client-org user (matched via
current_user.organization_id == Projects.client) and an audit-firm user
(matched via current_user.auditor_profile_id == Projects.auditing_firm) are
both legitimate owners of a project's evidence. Internal CompliFyre-role users
are NOT given a bypass here -- role_required (a separate, purely functional
gate) doesn't establish cross-tenant access intent, and no existing route
using role_required("COMPLIFYRE", ...) currently touches these evidence
routes. If internal support staff need cross-tenant access to evidence later,
that should be a deliberate, separate decision -- not an inferred bypass.
"""

from app.models.project_instance_models import (
    ProjectControlActivity,
    ProjectComplianceActivity,
    ProjectClause,
    ProjectGuideline,
)
from app.models.auditOrganization import Projects


def get_project_for_evidence_artifact(artifact):
    """
    Walk the full chain from a ProjectEvidenceArtifact up to its owning Project.
    Returns the Projects row, or None if any link in the chain is broken
    (treated as "no access" by the caller, not as an error).
    """
    if not artifact or not artifact.project_control_activity_id:
        return None
    pca = ProjectControlActivity.query.get(artifact.project_control_activity_id)
    if not pca or not pca.project_compliance_activity_id:
        return None
    pcompl = ProjectComplianceActivity.query.get(pca.project_compliance_activity_id)
    if not pcompl or not pcompl.project_clause_id:
        return None
    pclause = ProjectClause.query.get(pcompl.project_clause_id)
    if not pclause or not pclause.project_guideline_id:
        return None
    pguideline = ProjectGuideline.query.get(pclause.project_guideline_id)
    if not pguideline or not pguideline.project_id:
        return None
    return Projects.query.get(pguideline.project_id)


def _user_matches_org_or_firm(user, client_org_id, auditing_firm_id):
    """
    Shared two-sided comparison: client-org side OR audit-firm side.
    Returns False for any missing/None input -- callers should treat False
    the same as "not found" (404), not a 500 error.

    IMPORTANT: current_user can be a Users row OR an OrganizationContacts row
    (Flask-Login's user_loader tries Users first, falls back to
    OrganizationContacts -- confirmed in app/__init__.py). OrganizationContacts
    has organization_id but does NOT have auditor_profile_id at all -- direct
    attribute access would raise AttributeError and crash the route for any
    client-org user logged in via OrganizationContacts. Using getattr() with a
    default handles both user types safely without assuming a shared shape.
    """
    if user is None:
        return False
    user_org_id = getattr(user, "organization_id", None)
    if user_org_id is not None and client_org_id is not None and user_org_id == client_org_id:
        return True
    user_auditor_profile_id = getattr(user, "auditor_profile_id", None)
    if user_auditor_profile_id is not None and auditing_firm_id is not None and user_auditor_profile_id == auditing_firm_id:
        return True
    return False


def user_can_access_project(project, user):
    """Two-sided ownership check against a Projects row directly."""
    if not project:
        return False
    return _user_matches_org_or_firm(user, project.client, project.auditing_firm)


def check_evidence_artifact_access(artifact, user):
    """
    Convenience combined check for use at the top of a route, right after
    fetching the artifact. Returns True/False -- callers should abort(404)
    on False, not 403, to avoid confirming the artifact's existence to a
    user who shouldn't see it either way.

    FAST PATH (S-51, 2026-08-18): uses the denormalized client_organization_id
    / auditing_firm_id columns directly on the artifact, avoiding the 5-hop
    join for the common case. Falls back to the original chain-walk if either
    denormalized column is None -- should not happen given the backfill plus
    the after_insert event listener that keeps these in sync going forward,
    but failing safe to the proven-correct slow path on an unexpected NULL is
    worth the rare extra query rather than risking an incorrect fast-path
    result on a security-relevant check.
    """
    if not artifact or not user:
        return False

    if artifact.client_organization_id is not None and artifact.auditing_firm_id is not None:
        return _user_matches_org_or_firm(
            user, artifact.client_organization_id, artifact.auditing_firm_id
        )

    project = get_project_for_evidence_artifact(artifact)
    return user_can_access_project(project, user)
