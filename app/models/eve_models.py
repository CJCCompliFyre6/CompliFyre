# app/models/eve_models.py
#
# Module C — EVE v2 Data Model
#
# 5 new tables:
#   1. GuidelineEveContext       — Module A output (context classification per guideline)
#   2. ControlChecklist          — Module B output (master checklist per control activity)
#   3. ProjectChecklist          — Module B project copy (per project_control_activity)
#   4. EveEvidenceResult         — Module D output (per evidence x per checklist item)
#   5. EveControlResult          — Modules E+F+G output (per project_control_activity)
#
# IMPORTANT — migration strategy:
#   All new columns are nullable so existing data is never broken.
#   Old EVE fields on ProjectControlActivity are NOT dropped here —
#   drop them only after all routes have been updated to use these tables.

from app import db
from datetime import datetime
from sqlalchemy.sql import func


# ---------------------------------------------------------------------------
# Table 1 — GuidelineEveContext
# Stores EVE Step 1 (context classification) output at the guideline level.
# Run once per guideline centrally on the Complifyre side (Module A Celery task).
# ---------------------------------------------------------------------------

class GuidelineEveContext(db.Model):
    """
    EVE Step 1 output — regulation type, domain, auditor profile.
    Stored at guideline level so it is reused across all projects
    that use the same guideline. Never regenerated unless the
    guideline itself changes.
    """

    __tablename__ = "guideline_eve_context"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    guideline_id = db.Column(
        db.BigInteger,
        db.ForeignKey("guidelines.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # one context record per guideline
    )

    # EVE Step 1 outputs — fixed ENUM values from EVE v2 prompt
    regulation_type = db.Column(
        db.String(50),
        nullable=False,
        # valid: RBI, SEBI, IRDAI, NABARD, ISO, PCI_DSS, SWIFT, DPDP, GDPR, BASEL, OTHER
    )
    domain = db.Column(
        db.String(50),
        nullable=False,
        # valid: INFOSEC, DATA_PRIVACY, CREDIT_RISK, MARKET_RISK,
        #        OPERATIONAL_RISK, IT_GOVERNANCE, VENDOR_RISK, FINANCIAL_REPORTING
    )
    auditor_profile = db.Column(
        db.String(50),
        nullable=False,
        # valid: INFOSEC_AUDITOR, PRIVACY_AUDITOR, ITGC_AUDITOR,
        #        RISK_AUDITOR, FINANCIAL_AUDITOR
    )

    # Full raw JSON returned by Step 1 — kept for auditability
    raw_output_json = db.Column(db.JSON, nullable=True)

    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    generated_by = db.Column(
        db.BigInteger,
        db.ForeignKey("Users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    guideline = db.relationship(
        "Guidelines",
        backref=db.backref("eve_context", uselist=False, lazy="select"),
    )
    generator = db.relationship("Users", foreign_keys=[generated_by])

    def to_dict(self):
        return {
            "id": self.id,
            "guideline_id": self.guideline_id,
            "regulation_type": self.regulation_type,
            "domain": self.domain,
            "auditor_profile": self.auditor_profile,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }


# ---------------------------------------------------------------------------
# Table 2 — ControlChecklist
# Stores EVE Steps 3+4 output at the master control_activity level.
# Run once per control activity centrally (Module B Celery task).
# All projects using the same control activity get the same checklist.
# ---------------------------------------------------------------------------

class ControlChecklist(db.Model):
    """
    EVE Steps 3+4 output — required dimensions + atomic checklist items.
    Master copy stored against the central control_activities table.
    Project-level copy is in ProjectChecklist (Table 3).
    """

    __tablename__ = "control_checklist"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    control_activity_id = db.Column(
        db.Integer,
        db.ForeignKey("control_activities.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # one master checklist per control activity
    )

    # EVE Step 3 output — required effectiveness dimensions
    # stored flat for easy querying
    dimension_design = db.Column(db.Boolean, nullable=False, default=False)
    dimension_implementation = db.Column(db.Boolean, nullable=False, default=False)
    dimension_operating = db.Column(db.Boolean, nullable=False, default=False)

    # EVE Step 4 output — full atomic checklist
    # JSON array of checklist items — each item has:
    #   id (CHK_001...), requirement, control_pattern, lifecycle_stage,
    #   effectiveness_type, weight, testing_method, testing_approach,
    #   expected_evidence_types, evidence_logic, requirement_type,
    #   allows_compensating_control, compensating_control_logic,
    #   evaluation_logic {check_for, pass_condition, fail_condition},
    #   failure_impact
    checklist_json = db.Column(db.JSON, nullable=False)

    # EVE Step 2 output — admissibility + sampling + scoring rules
    admissibility_rules_json = db.Column(db.JSON, nullable=True)
    sampling_rules_json = db.Column(db.JSON, nullable=True)
    scoring_rules_json = db.Column(db.JSON, nullable=True)

    # Version — increment when checklist is regenerated
    version = db.Column(db.Integer, nullable=False, default=1)

    # Full raw JSON from the prompt — kept for auditability
    raw_output_json = db.Column(db.JSON, nullable=True)

    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    generated_by = db.Column(
        db.BigInteger,
        db.ForeignKey("Users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    control_activity = db.relationship(
        "ControlActivity",
        backref=db.backref("eve_checklist", uselist=False, lazy="select"),
    )
    generator = db.relationship("Users", foreign_keys=[generated_by])
    project_checklists = db.relationship(
        "ProjectChecklist",
        back_populates="source_checklist",
        lazy="dynamic",
    )

    def get_checklist_items(self):
        """Return checklist items as a list of dicts."""
        if isinstance(self.checklist_json, list):
            return self.checklist_json
        return []

    def get_high_weight_items(self):
        """Return only HIGH weight checklist items."""
        return [i for i in self.get_checklist_items() if i.get("weight") == "HIGH"]

    def to_dict(self):
        return {
            "id": self.id,
            "control_activity_id": self.control_activity_id,
            "dimension_design": self.dimension_design,
            "dimension_implementation": self.dimension_implementation,
            "dimension_operating": self.dimension_operating,
            "checklist_items_count": len(self.get_checklist_items()),
            "version": self.version,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
        }


# ---------------------------------------------------------------------------
# Table 3 — ProjectChecklist
# Project-specific copy of the master checklist — one per
# project_control_activity. Copied at project creation time so
# future changes to the master checklist do not affect running audits.
# ---------------------------------------------------------------------------

class ProjectChecklist(db.Model):
    """
    Project-specific copy of ControlChecklist.
    Auditors work against this — not the master.
    Status tracks whether the auditor has completed testing this checklist.
    """

    __tablename__ = "project_checklist"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    project_control_activity_id = db.Column(
        db.BigInteger,
        db.ForeignKey("project_control_activities.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # one checklist per project control activity
    )

    source_checklist_id = db.Column(
        db.BigInteger,
        db.ForeignKey("control_checklist.id", ondelete="SET NULL"),
        nullable=True,   # nullable — master may be deleted but project copy lives on
    )

    # Copied dimensions (flat — for quick querying without parsing JSON)
    dimension_design = db.Column(db.Boolean, nullable=False, default=False)
    dimension_implementation = db.Column(db.Boolean, nullable=False, default=False)
    dimension_operating = db.Column(db.Boolean, nullable=False, default=False)

    # Full checklist copy — same structure as ControlChecklist.checklist_json
    checklist_json = db.Column(db.JSON, nullable=False)

    # Copied rules
    admissibility_rules_json = db.Column(db.JSON, nullable=True)
    sampling_rules_json = db.Column(db.JSON, nullable=True)
    scoring_rules_json = db.Column(db.JSON, nullable=True)

    # Checklist version that was copied (for traceability)
    source_version = db.Column(db.Integer, nullable=True)

    # Auditor testing status
    status = db.Column(
        db.String(20),
        nullable=False,
        default="pending",
        # valid: "pending", "in_progress", "completed"
    )
    completed_at = db.Column(db.DateTime, nullable=True)
    completed_by = db.Column(
        db.BigInteger,
        db.ForeignKey("Users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    project_control_activity = db.relationship(
        "ProjectControlActivity",
        backref=db.backref("eve_checklist", uselist=False, lazy="select"),
    )
    source_checklist = db.relationship(
        "ControlChecklist",
        back_populates="project_checklists",
    )
    evidence_results = db.relationship(
        "EveEvidenceResult",
        back_populates="project_checklist",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    control_result = db.relationship(
        "EveControlResult",
        back_populates="project_checklist",
        uselist=False,
        cascade="all, delete-orphan",
    )
    completer = db.relationship("Users", foreign_keys=[completed_by])

    def get_checklist_items(self):
        if isinstance(self.checklist_json, list):
            return self.checklist_json
        return []

    def get_item_by_id(self, checklist_item_id):
        """Find a specific checklist item by its CHK_### id."""
        for item in self.get_checklist_items():
            if item.get("id") == checklist_item_id:
                return item
        return None

    def to_dict(self):
        return {
            "id": self.id,
            "project_control_activity_id": self.project_control_activity_id,
            "dimension_design": self.dimension_design,
            "dimension_implementation": self.dimension_implementation,
            "dimension_operating": self.dimension_operating,
            "checklist_items_count": len(self.get_checklist_items()),
            "source_version": self.source_version,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ---------------------------------------------------------------------------
# Table 4 — EveEvidenceResult
# Stores EVE Step 5 output — one row per evidence x checklist item pair.
# This is the most granular table — full traceability of
# which evidence supported / contradicted / was insufficient for which check.
# ---------------------------------------------------------------------------

class EveEvidenceResult(db.Model):
    """
    EVE Step 5 output — evidence execution results per checklist item.
    One row per (project_checklist, evidence_artifact, checklist_item).
    This table enables full traceability — every signal and status
    is linked to a specific piece of evidence and a specific check.
    """

    __tablename__ = "eve_evidence_result"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    project_checklist_id = db.Column(
        db.BigInteger,
        db.ForeignKey("project_checklist.id", ondelete="CASCADE"),
        nullable=False,
    )

    evidence_artifact_id = db.Column(
        db.Integer,
        db.ForeignKey("project_evidence_artifacts.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The CHK_### id from the checklist item this result applies to
    checklist_item_id = db.Column(db.String(20), nullable=False)

    # Admissibility — EVE Step 5 Sub-step 3
    admissibility = db.Column(
        db.String(20),
        nullable=False,
        # valid: "ADMISSIBLE", "PARTIAL", "INADMISSIBLE"
    )
    admissibility_reason = db.Column(db.Text, nullable=True)

    # Evidence metadata — EVE Step 5 Sub-step 4
    evidence_type = db.Column(db.String(50), nullable=True)
    evidence_strength = db.Column(
        db.String(20),
        nullable=True,
        # valid: "STRONG", "MODERATE", "WEAK"
    )
    evidence_role = db.Column(
        db.String(20),
        nullable=True,
        # valid: "PRIMARY", "SUPPORTING"
    )

    # Signal — EVE Step 5 Sub-step 7
    signal = db.Column(
        db.String(20),
        nullable=False,
        # valid: "SUPPORTS", "CONTRADICTS", "INSUFFICIENT"
    )
    signal_basis = db.Column(db.Text, nullable=True)

    # Item-level status — EVE Step 5 Sub-step 8
    item_status = db.Column(
        db.String(10),
        nullable=False,
        # valid: "PASS", "PARTIAL", "FAIL"
    )

    # Confidence — EVE Step 5 Sub-step 10
    confidence = db.Column(
        db.String(10),
        nullable=True,
        # valid: "HIGH", "MEDIUM", "LOW"
    )

    # Exact reference within the evidence (section, page, identifier)
    evidence_reference = db.Column(db.Text, nullable=True)

    # Sample evaluation (if applicable) — EVE Step 5 Sub-step 8 special rules
    sample_applicable = db.Column(db.Boolean, nullable=True)
    sample_size = db.Column(db.Integer, nullable=True)
    population_size = db.Column(db.Integer, nullable=True)
    exception_rate = db.Column(db.Float, nullable=True)
    sample_within_audit_period = db.Column(db.Boolean, nullable=True)

    # Full raw JSON output from Step 5 for this evidence item
    raw_output_json = db.Column(db.JSON, nullable=True)

    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    project_checklist = db.relationship(
        "ProjectChecklist",
        back_populates="evidence_results",
    )
    evidence_artifact = db.relationship(
        "ProjectEvidenceArtifact",
        backref=db.backref("eve_results", lazy="dynamic"),
    )

    # Composite unique constraint — one result per evidence x checklist item pair
    __table_args__ = (
        db.UniqueConstraint(
            "project_checklist_id",
            "evidence_artifact_id",
            "checklist_item_id",
            name="uq_eve_evidence_checklist_item",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "project_checklist_id": self.project_checklist_id,
            "evidence_artifact_id": self.evidence_artifact_id,
            "checklist_item_id": self.checklist_item_id,
            "admissibility": self.admissibility,
            "evidence_strength": self.evidence_strength,
            "signal": self.signal,
            "item_status": self.item_status,
            "confidence": self.confidence,
            "evidence_reference": self.evidence_reference,
            "sample_applicable": self.sample_applicable,
            "exception_rate": self.exception_rate,
        }


# ---------------------------------------------------------------------------
# Table 5 — EveControlResult
# Stores EVE Steps 6+7+8 output — one row per project_control_activity.
# This replaces the scattered fields on ProjectControlActivity and the
# blob-based ConsolidatedFindingsSummary / ConsolidatedObservationSummary tables.
# ---------------------------------------------------------------------------

class EveControlResult(db.Model):
    """
    EVE Steps 6+7+8 aggregated output per project_control_activity.

    Step 6 — checklist_summary_json, observations_json, findings_json
    Step 7 — recommendations_json
    Step 8 — clause_rollup_json (populated after all controls in a clause are done)

    final_status and final_severity are stored flat for fast querying
    without parsing JSON — used by compliance_utils.py for dashboard aggregation.
    """

    __tablename__ = "eve_control_result"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    project_control_activity_id = db.Column(
        db.BigInteger,
        db.ForeignKey("project_control_activities.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,   # one EVE result per project control activity
    )

    project_checklist_id = db.Column(
        db.BigInteger,
        db.ForeignKey("project_checklist.id", ondelete="SET NULL"),
        nullable=True,
    )

    # --- Step 6 outputs ---

    # Per-checklist-item final status after evidence weighting + signal resolution
    # JSON array: [{checklist_id, requirement, final_status, basis, confidence}, ...]
    checklist_summary_json = db.Column(db.JSON, nullable=True)

    # One observation per checklist item — structured format per EVE v2 Step 6
    # JSON array: [{checklist_id, observation_text, status}, ...]
    observations_json = db.Column(db.JSON, nullable=True)

    # Findings — only for FAIL and material PARTIAL items
    # JSON array: [{finding_id, checklist_id, issue, impact, severity, evidence_reference}, ...]
    findings_json = db.Column(db.JSON, nullable=True)

    # --- Step 7 outputs ---

    # One recommendation per finding — 1:1 mapping
    # JSON array: [{finding_id, recommendation, implementation_steps, owner, timeline}, ...]
    recommendations_json = db.Column(db.JSON, nullable=True)

    # --- Step 8 outputs ---

    # Clause-level rollup — populated after all controls under a clause are evaluated
    # JSON: {clause_id, clause_status, clause_severity, summary,
    #        observations, findings, recommendations}
    clause_rollup_json = db.Column(db.JSON, nullable=True)

    # --- Flat summary fields for fast querying ---
    # These mirror the JSON but allow SQL filtering without JSON parsing

    final_status = db.Column(
        db.String(30),
        nullable=True,
        # valid: "COMPLIANT", "PARTIALLY_COMPLIANT", "NON_COMPLIANT"
    )

    final_severity = db.Column(
        db.String(20),
        nullable=True,
        # valid: "CRITICAL", "HIGH", "MEDIUM", "LOW", None (if compliant)
    )

    findings_count = db.Column(db.Integer, nullable=True, default=0)
    critical_findings_count = db.Column(db.Integer, nullable=True, default=0)
    high_findings_count = db.Column(db.Integer, nullable=True, default=0)

    checklist_pass_count = db.Column(db.Integer, nullable=True, default=0)
    checklist_partial_count = db.Column(db.Integer, nullable=True, default=0)
    checklist_fail_count = db.Column(db.Integer, nullable=True, default=0)

    # Tracks which EVE steps have been completed for this control
    step6_completed = db.Column(db.Boolean, nullable=False, default=False)
    step7_completed = db.Column(db.Boolean, nullable=False, default=False)
    step8_completed = db.Column(db.Boolean, nullable=False, default=False)

    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    generated_by = db.Column(
        db.BigInteger,
        db.ForeignKey("Users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    project_control_activity = db.relationship(
        "ProjectControlActivity",
        backref=db.backref("eve_result", uselist=False, lazy="select"),
    )
    project_checklist = db.relationship(
        "ProjectChecklist",
        back_populates="control_result",
    )
    generator = db.relationship("Users", foreign_keys=[generated_by])

    def get_findings(self):
        """Return findings as list — empty list if none."""
        if isinstance(self.findings_json, list):
            return self.findings_json
        return []

    def get_observations(self):
        if isinstance(self.observations_json, list):
            return self.observations_json
        return []

    def get_recommendations(self):
        if isinstance(self.recommendations_json, list):
            return self.recommendations_json
        return []

    def sync_counts(self):
        """
        Recompute flat count fields from findings_json.
        Call this after updating findings_json before saving.
        """
        findings = self.get_findings()
        self.findings_count = len(findings)
        self.critical_findings_count = sum(
            1 for f in findings if f.get("severity") == "CRITICAL"
        )
        self.high_findings_count = sum(
            1 for f in findings if f.get("severity") == "HIGH"
        )

    def sync_checklist_counts(self):
        """
        Recompute pass/partial/fail counts from checklist_summary_json.
        Call after updating checklist_summary_json before saving.
        """
        items = self.checklist_summary_json or []
        self.checklist_pass_count = sum(
            1 for i in items if i.get("final_status") == "PASS"
        )
        self.checklist_partial_count = sum(
            1 for i in items if i.get("final_status") == "PARTIAL"
        )
        self.checklist_fail_count = sum(
            1 for i in items if i.get("final_status") == "FAIL"
        )

    def to_dict(self):
        return {
            "id": self.id,
            "project_control_activity_id": self.project_control_activity_id,
            "final_status": self.final_status,
            "final_severity": self.final_severity,
            "findings_count": self.findings_count,
            "critical_findings_count": self.critical_findings_count,
            "high_findings_count": self.high_findings_count,
            "checklist_pass_count": self.checklist_pass_count,
            "checklist_partial_count": self.checklist_partial_count,
            "checklist_fail_count": self.checklist_fail_count,
            "step6_completed": self.step6_completed,
            "step7_completed": self.step7_completed,
            "step8_completed": self.step8_completed,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
