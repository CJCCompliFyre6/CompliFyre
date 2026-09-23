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

class ChecklistItem(db.Model):
    """Build Sequence #TBD -- Phase 6 foundation, GRACE/EVE traceability chain,
    step 1 of 5 (bottom of the chain). One row per ATOMIC checklist item --
    previously these existed only as JSON array entries inside
    ControlChecklist.checklist_json, with no individually queryable or
    linkable row of their own. Real Ankita design decision (21 Sept 2026):
    multi-user, parallel-background-task usage (this session's own new
    per-file evidence mapping being the immediate driver) makes JSON blobs
    unsafe for anything that needs concurrent, item-level writes.

    ADDITIVE ONLY -- ControlChecklist.checklist_json is NOT modified, removed,
    or replaced by this table in any way. Every existing code path that reads
    checklist_json directly continues to work completely unchanged. This
    table is a new, parallel, queryable index built FROM that JSON, alongside
    it -- not a migration away from it. Confirmed with Ankita as an explicit
    requirement before this was written (21 Sept 2026).

    Deliberately narrow: only pulls out item_id and requirement text as real
    columns -- everything else EVE's own evaluation logic needs stays exactly
    as originally authored, preserved whole in full_item_json.
    """

    __tablename__ = "checklist_items"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    control_checklist_id = db.Column(
        db.BigInteger, db.ForeignKey("control_checklist.id", ondelete="CASCADE"), nullable=False
    )

    item_id = db.Column(db.String(50), nullable=False)
    requirement = db.Column(db.Text, nullable=True)
    full_item_json = db.Column(db.JSON, nullable=False)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    control_checklist = db.relationship("ControlChecklist", backref="checklist_items")

    __table_args__ = (
        db.UniqueConstraint("control_checklist_id", "item_id", name="uq_checklist_item_per_checklist"),
    )


class RawEvidenceRequirement(db.Model):
    """Build Sequence #TBD -- Phase 6 foundation, GRACE/EVE traceability chain,
    step 2 of 5. One row per D1-level raw evidence ask (the "Extract All
    Activities" pipeline's own Phase 5 D1 output -- see process_clauses_chunk
    in app/routes/audit/view.py) -- previously these existed only as
    transient Python dicts during a single pipeline run, never persisted.

    CORRECTED (22-23 Sept 2026, before any real data was ever written to this
    table): the original design linked to a single control_activity_id,
    assuming a raw evidence item belongs to exactly one control activity.
    Real schema check with Ankita found this wrong -- EvidenceArtifact is
    explicitly many-to-many with ControlActivity (its own docstring: "This
    can be linked to multiple ControlActivities", via the existing
    control_evidences association table) -- confirmed against real guideline
    210 data, where a single evidence_id's group spanned 26 different
    activity_ids. This table now links to evidence_artifact_id (a real FK to
    evidence_artifacts.id) instead, and derives ALL of its control-activity
    traceability through EvidenceArtifact.controls, the existing many-to-many
    relationship -- not a new backward-mapping table, since control_evidences
    already IS that backward mapping and re-deriving it would only risk
    drifting out of sync with the source of truth.
    """

    __tablename__ = "raw_evidence_requirements"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_id = db.Column(db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False)
    clause_id = db.Column(db.BigInteger, nullable=True)
    clause_no = db.Column(db.String(100), nullable=True)

    # Matches EvidenceArtifact's own two real fields -- this table indexes
    # the same underlying evidence text, not a redefinition of it.
    category = db.Column(db.String(255), nullable=True)
    evidence_item = db.Column(db.Text, nullable=False)

    # Real FK to evidence_artifacts.id -- nullable because a raw item can
    # exist without one (e.g. the "no evidence submitted" / "no control
    # activities" placeholder rows process_clauses_chunk also produces).
    # Control-activity traceability (and therefore checklist traceability)
    # comes from EvidenceArtifact.controls (existing many-to-many), reached
    # via this FK -- not stored redundantly on this row.
    evidence_artifact_id = db.Column(
        db.Integer, db.ForeignKey("evidence_artifacts.id", ondelete="SET NULL"), nullable=True
    )

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    evidence_artifact = db.relationship("EvidenceArtifact", backref="raw_evidence_requirements")


class GuidelineEvidenceRequirement(db.Model):
    """Build Sequence #TBD -- Phase 6 foundation, GRACE/EVE traceability chain,
    step 3 of 5. One row per FINAL grouped evidence requirement -- the real
    output of the "Extract All Activities" pipeline's Phase 5 consolidation
    (D5a-i / D2 / D3 / normalize / second-pass -- see
    consolidate_evidence_for_pipeline in app/services/manual_task.py).

    Real design correction from Ankita (21-22 Sept 2026): this is
    GUIDELINE-level, not project-level -- GRACE produces this list ONCE,
    centrally, per guideline; every project that uses that guideline reads
    the same central list, rather than each project generating or owning its
    own copy. Multi-user, parallel-background-task usage (per-file async
    mapping) makes JSON blobs genuinely unsafe for anything needing
    concurrent, row-level writes -- this table is the real, durable,
    queryable final output Phase 5 exists to produce; ComplifyreConsolidatedEvidence's
    JSON blob was the mid-stage storage for this same output before this
    table existed and remains available for historical/debug reference.

    Deliberately does NOT duplicate clause_no / activity_id here -- those
    already live on RawEvidenceRequirement (step 2), and which raw items
    belong to this group is the job of the raw-to-grouped link table (step 4,
    not yet built), not a re-storage of that same data on this row.
    """

    __tablename__ = "guideline_evidence_requirements"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_id = db.Column(db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False)

    # The canonical, final name for this requirement -- what Phase 5's D3
    # merge judgment (or D5a-i's containment match) settled on as the
    # group's evidence_item_name.
    evidence_item_name = db.Column(db.Text, nullable=False)

    # Which Phase 5 pass produced this row -- useful for understanding a
    # given requirement's provenance without re-deriving it (e.g. a
    # "possible_duplicate" group flagged for human review is recorded
    # distinctly from a confident D3 merge).
    consolidation_source = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    guideline = db.relationship("Guidelines", backref="guideline_evidence_requirements")

    __table_args__ = (
        db.UniqueConstraint("guideline_id", "evidence_item_name", name="uq_requirement_per_guideline"),
    )


class RawToGroupedRequirementLink(db.Model):
    """Build Sequence #TBD -- Phase 6 foundation, GRACE/EVE traceability chain,
    step 4 of 5. Records exactly which RawEvidenceRequirement rows (step 2)
    were merged into which GuidelineEvidenceRequirement row (step 3) -- the
    real grouping decision Phase 5's D5a-i/D2/D3 pipeline made, preserved as
    queryable data rather than lost once the final grouped list is saved.

    Directly required by Ankita's own real requirement (22 Sept 2026): the
    grouped/deduplicated final list is only useful for EVE's downstream
    per-checklist-item evaluation if every file mapped to a grouped
    requirement can be traced back through it to EVERY checklist item any of
    its constituent raw requirements originated from -- collapsing multiple
    near-duplicate raw asks into one canonical row is only safe if this
    backward path survives the collapse, not lost to it.

    merge_mechanism records provenance -- which Phase 5 stage (or later
    backfill/cleanup pass) made this specific merge decision, useful for
    understanding why two items were judged the same without re-deriving it.
    """

    __tablename__ = "raw_to_grouped_requirement_links"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    raw_evidence_requirement_id = db.Column(
        db.BigInteger, db.ForeignKey("raw_evidence_requirements.id", ondelete="CASCADE"), nullable=False
    )
    guideline_evidence_requirement_id = db.Column(
        db.BigInteger, db.ForeignKey("guideline_evidence_requirements.id", ondelete="CASCADE"), nullable=False
    )

    # e.g. 'd5a1_fuzzy_containment', 'd2_d3_embedding_cluster',
    # 'backfill_case_insensitive_merge' -- which mechanism decided this raw
    # item belongs in this group.
    merge_mechanism = db.Column(db.String(100), nullable=True)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    raw_evidence_requirement = db.relationship("RawEvidenceRequirement", backref="grouped_links")
    guideline_evidence_requirement = db.relationship("GuidelineEvidenceRequirement", backref="raw_links")

    __table_args__ = (
        db.UniqueConstraint(
            "raw_evidence_requirement_id", "guideline_evidence_requirement_id",
            name="uq_raw_to_grouped_link"
        ),
    )


class FileRequirementMapping(db.Model):
    """Build Sequence #TBD -- Phase 6 foundation, GRACE/EVE traceability chain,
    step 5 of 5 (the actual deliverable the whole chain exists to support).
    Many-to-many link between a project's uploaded evidence files
    (ProjectEvidenceFile) and the guideline-level evidence requirements they
    satisfy (GuidelineEvidenceRequirement) -- genuinely many-to-many in both
    directions per Ankita's explicit direction (21 Sept 2026): one file can
    satisfy multiple requirements, one requirement can be satisfied by
    multiple files.

    This is the row the two-column mapping UI (requirements on the left,
    incoming files mapped against them on the right) reads and writes, and
    the row a per-file background mapping task (run in parallel across many
    concurrently-uploading files -- Ankita's own explicit design direction)
    creates as its output. Real rows with a real composite unique constraint
    are what make that parallelism safe -- two mapping tasks writing
    different files' matches never touch the same row, unlike a shared JSON
    array would.

    Once a file's mappings exist here, EVE reaches every checklist item that
    file is now relevant to by following: this row -> GuidelineEvidenceRequirement
    -> RawToGroupedRequirementLink -> RawEvidenceRequirement -> EvidenceArtifact
    -> (existing control_evidences many-to-many) -> ControlActivity ->
    ControlChecklist -> ChecklistItem. EVE's own evaluation logic is not
    built here -- this table only establishes the mapping EVE then acts on,
    per Ankita's explicit scoping (22 Sept 2026): "eve is designed to do
    that... once that mapping is clear... eve should do its job."
    """

    __tablename__ = "file_requirement_mappings"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    project_evidence_file_id = db.Column(
        db.BigInteger, db.ForeignKey("project_evidence_files.id", ondelete="CASCADE"), nullable=False
    )
    guideline_evidence_requirement_id = db.Column(
        db.BigInteger, db.ForeignKey("guideline_evidence_requirements.id", ondelete="CASCADE"), nullable=False
    )

    # 'pending' = mapping task queued/running for this pair (not applicable
    # in practice since rows are only created once a match is decided, but
    # kept for symmetry with ProjectEvidenceFile.mapping_status and for any
    # future two-phase mapping flow); 'confirmed' = the mapping task judged
    # this file satisfies this requirement; 'needs_review' = low-confidence
    # match, surfaced to a human; 'rejected' = a human or later pass
    # explicitly ruled this match out (row kept, not deleted, for audit
    # trail -- a rejected match is still a real event worth preserving).
    status = db.Column(db.String(50), nullable=False, default="confirmed")

    # Which mechanism produced this specific mapping -- e.g. an LLM-based
    # content-matching task's own name/version, or 'manual' if a human
    # created/confirmed it directly in the UI.
    mapping_mechanism = db.Column(db.String(100), nullable=True)

    # Free-text rationale the mapping mechanism can record for why it judged
    # this file relevant to this requirement -- shown to a human reviewing a
    # needs_review match, not required for a confirmed one.
    mapping_reasoning = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    project_evidence_file = db.relationship("ProjectEvidenceFile", backref="requirement_mappings")
    guideline_evidence_requirement = db.relationship("GuidelineEvidenceRequirement", backref="file_mappings")

    __table_args__ = (
        db.UniqueConstraint(
            "project_evidence_file_id", "guideline_evidence_requirement_id",
            name="uq_file_requirement_mapping"
        ),
    )


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
        db.String(30),
        nullable=True,
        # fix 2026-08-01: widened from 20 to 30 -- actual values written by
        # EVIDENCE_ROLE_MAP in eve_step5.py are DESIGN_EVIDENCE (15),
        # OPERATING_EVIDENCE (18), IMPLEMENTATION_EVIDENCE (23 -- overflowed
        # VARCHAR(20), causing every TRAINING_RECORD/EMAIL_COMMUNICATION/
        # CONFIGURATION_FILE/NETWORK_DIAGRAM/ARCHITECTURE_DIAGRAM evidence
        # upload to fail and retry-exhaust. Comment above was stale --
        # never actually PRIMARY/SUPPORTING in this code path. Ported from
        # production fix, same day.
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
        db.String(20),
        nullable=False,
        # fix 2026-08-01: widened from 10 to 20, and added NOT_APPLICABLE as a
        # valid value -- previously any item_status outside PASS/PARTIAL/FAIL
        # (including a correctly-computed NOT_APPLICABLE from evidence-type
        # relevance filtering, #238) was silently forced to PARTIAL in
        # eve_step5.py, creating a contradictory signal that likely confused
        # Step 6's LLM into raising findings it was explicitly told not to.
        # valid: "PASS", "PARTIAL", "FAIL", "NOT_APPLICABLE"
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
    # V3 Step 6 — Assurance Consolidation
    assurance_state_json = db.Column(db.JSON, nullable=True)

    # V3 Step 7 — Observations + Findings + Risks + Recommendations
    risks_json = db.Column(db.JSON, nullable=True)
    oe_exception_register_json = db.Column(db.JSON, nullable=True)
    inquiry_register_json = db.Column(db.JSON, nullable=True)
    control_support_status = db.Column(db.String(50), nullable=True)
    evidence_sufficiency_json = db.Column(db.JSON, nullable=True)
    contradiction_summary_json = db.Column(db.JSON, nullable=True)
    oe_exception_summary_json = db.Column(db.JSON, nullable=True)

    # Cross-dimension (DE -> IE -> OE) parameter carry-forward -- Build Sequence #394.
    # Populated once DE evaluation genuinely completes for this activity (every DE
    # discovers_parameter-tagged checklist item has reached a final answer -- found
    # with a citation, or conclusively not-found). Never expires and is never
    # silently overwritten -- persists until a NEWER Design-level document actually
    # supersedes an earlier one (bank policy changes rarely; re-evaluation of IE/OE
    # then triggers only for the specific checklist items whose depends_on_parameter
    # matches what changed, not the whole activity).
    # JSON: {parameter_name: {"value": ..., "evidence_artifact_id": ..., "checklist_item_id": ...,
    #        "evidence_reference": ..., "discovered_at": ...}}
    # A parameter genuinely not found in any Design evidence is recorded explicitly as
    # {"value": None, "status": "not_found", ...} -- distinct from the key being absent,
    # which means DE hasn't evaluated that item yet at all.
    design_parameters_json = db.Column(db.JSON, nullable=True)

    # True once every DE discovers_parameter-tagged checklist item for this activity
    # has reached a final answer. IE/OE evaluation must check this before running
    # (Build Sequence #394, Option A) -- queued, not evaluated against an incomplete
    # or assumed picture, until this flips true.
    de_discovery_completed = db.Column(db.Boolean, nullable=False, default=False)

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


class EveInquiry(db.Model):
    __tablename__ = "eve_inquiry"

    id = db.Column(db.BigInteger, primary_key=True)
    project_checklist_id = db.Column(db.BigInteger, nullable=False)
    checklist_item_id = db.Column(db.String(20), nullable=False)

    # Contradiction details
    contradiction_type = db.Column(
        db.String(100),
        # fix 2026-08-01: widened from 50 to 100 -- this field is populated
        # directly from LLM output at 2 sites in eve_step5.py with no
        # length validation on the Python side. First site's prompt at
        # least enumerates options (longest is INSUFFICIENT_EVIDENCE, 21
        # chars); second site's prompt gives zero enumeration guidance at
        # all ("contradiction_type": ""), pure free text. Same risk shape
        # as evidence_role's VARCHAR(20) overflow found and fixed the same
        # day -- widening here proactively rather than waiting for a real
        # occurrence, per Rules 18/19.
    )
    severity = db.Column(db.String(20), default="MINOR")

    # Evidence references
    evidence_a_id = db.Column(db.Integer)
    evidence_a_type = db.Column(db.String(50))
    evidence_a_claim = db.Column(db.Text)
    evidence_b_id = db.Column(db.Integer)
    evidence_b_type = db.Column(db.String(50))
    evidence_b_claim = db.Column(db.Text)

    # Inquiry
    inquiry_question = db.Column(db.Text, nullable=False)
    suggested_evidence = db.Column(db.Text)

    # Auditor response
    auditor_response = db.Column(db.Text)

    # Re-evaluation result
    re_evaluation_status = db.Column(db.String(20))
    re_evaluation_reason = db.Column(db.Text)
    re_evaluation_pass_condition_met = db.Column(db.Boolean)

    # Status lifecycle
    # PENDING_INQUIRY / RESPONDED / RE_EVALUATING / RESOLVED / ESCALATED_TO_FINDING
    status = db.Column(db.String(30), default="PENDING_INQUIRY")
    resolution_note = db.Column(db.Text)
    escalation_reason = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=db.func.now())
    responded_at = db.Column(db.DateTime)
    re_evaluated_at = db.Column(db.DateTime)
    resolved_at = db.Column(db.DateTime)
    resolved_by = db.Column(db.BigInteger)


class EveAssuranceState(db.Model):
    __tablename__ = "eve_assurance_state"

    id = db.Column(db.BigInteger, primary_key=True)
    project_checklist_id = db.Column(db.BigInteger, nullable=False, unique=True)

    # Scores
    assurance_score = db.Column(db.Float, default=0.0)
    coverage_score = db.Column(db.Float, default=0.0)
    evidence_quality_score = db.Column(db.Float, default=0.0)
    oe_reliability_score = db.Column(db.Float, default=0.0)

    # Counts
    total_checklist_items = db.Column(db.Integer, default=0)
    evaluated_items = db.Column(db.Integer, default=0)
    passed_items = db.Column(db.Integer, default=0)
    failed_items = db.Column(db.Integer, default=0)
    partial_items = db.Column(db.Integer, default=0)
    needs_review_items = db.Column(db.Integer, default=0)

    # Inquiry tracking
    inquiry_count = db.Column(db.Integer, default=0)
    contradiction_count = db.Column(db.Integer, default=0)
    resolved_inquiry_count = db.Column(db.Integer, default=0)
    escalated_inquiry_count = db.Column(db.Integer, default=0)

    # Evidence tracking
    total_evidence_count = db.Column(db.Integer, default=0)
    admissible_evidence_count = db.Column(db.Integer, default=0)

    # State
    last_updated_at = db.Column(db.DateTime, default=db.func.now())
    last_evidence_id = db.Column(db.Integer)


# ---------------------------------------------------------------------------
# Table — ClauseChecklistReview
# Build Sequence #TBD — Part C, Step C6 (Clause-level checklist assurance review).
#
# One row per review attempt for a clause, run once every sibling activity's
# checklist under that clause exists AND cross-sibling dependency resolution
# (#398, resolve_cross_sibling_dependencies) has already run against them.
#
# A single LLM call produces two things, together:
#   (a) sufficiency -- do these checklists, as a whole, let an auditor reach
#       an accurate conclusion for the clause
#   (c) genuine duplication across sibling activities -- candidate pairs only.
#       C8 (not yet built) persists CONFIRMED links permanently, only after
#       C6/C7 settle -- this table holds candidates from each review attempt,
#       not the final, permanent link records.
#
# Dependency resolution (b) is intentionally NOT part of this table or this
# review call -- that already runs mechanically, with no LLM, immediately
# after sibling checklists are generated (see resolve_cross_sibling_dependencies
# in eve_tasks.py).
#
# `iteration` exists for C7 (regenerate-once-then-flag, not yet built) --
# multiple rows per clause_id will exist once that orchestration is built.
# ---------------------------------------------------------------------------

class ClauseChecklistReview(db.Model):
    """
    EVE Part C, Step C6 output -- clause-level sufficiency verdict plus
    candidate duplicate-item pairs across sibling activities.
    """

    __tablename__ = "clause_checklist_review"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    clause_id = db.Column(
        db.Integer,
        db.ForeignKey("clauses.id", ondelete="CASCADE"),
        nullable=False,
    )

    # For C7's regenerate-once-then-flag loop (not yet built) -- which attempt
    # this review represents for the clause. Starts at 1.
    iteration = db.Column(db.Integer, nullable=False, default=1)

    # (a) sufficiency -- SUFFICIENT / INSUFFICIENT
    sufficiency_verdict = db.Column(db.String(20), nullable=False)
    sufficiency_reasoning = db.Column(db.Text, nullable=True)

    # (c) duplicate candidates -- JSON array, each item shaped:
    #   {
    #     "activity_id_a": int, "checklist_item_id_a": "CHK_00X",
    #     "activity_id_b": int, "checklist_item_id_b": "CHK_00Y",
    #     "justification": "..."
    #   }
    duplicate_pairs_json = db.Column(db.JSON, nullable=True)

    # Full raw LLM output -- kept for auditability, same pattern as
    # ControlChecklist.raw_output_json
    raw_output_json = db.Column(db.JSON, nullable=True)

    reviewed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Build Sequence #TBD -- C8: permanent, durable record of CONFIRMED genuine
# duplicate checklist-item pairs across sibling activities under a clause.
#
# Distinct from ClauseChecklistReview.duplicate_pairs_json above, which is a
# per-review CANDIDATE snapshot tied to one review row -- this table only
# holds pairs that survived the automatic confirmation rule (see promotion
# logic in eve_tasks.py):
#   - a pair that appears in both iteration=1 and iteration=2 (unchanged)
#     after a C7 patch-and-recheck cycle, or
#   - a pair found on a straight-SUFFICIENT iteration=1 review (no C7 cycle
#     occurs, so there is no second review to confirm against -- promoted
#     immediately).
#
# Function once confirmed: merge for evidence review (Part E, not yet built)
# -- both checklist items stay visible/active, but evidence submitted
# against one is treated as also satisfying the other.
#
# control_activity_id_a/b and checklist_item_id_a/b are ALWAYS normalized at
# write time so control_activity_id_a < control_activity_id_b -- this makes
# the same real pair detectable regardless of which side the LLM's
# duplicate_pairs output happened to list first on any given review, and
# lets the unique constraint actually prevent double-promotion of the same
# pair across separate pipeline runs over the clause's lifetime.
# ---------------------------------------------------------------------------

class ConfirmedDuplicatePair(db.Model):
    """
    EVE Part C, Step C8 output -- permanently confirmed cross-activity
    duplicate checklist-item pair. See module-level comment above for scope.
    """

    __tablename__ = "confirmed_duplicate_pairs"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    clause_id = db.Column(
        db.Integer,
        db.ForeignKey("clauses.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Always normalized so control_activity_id_a < control_activity_id_b --
    # see module comment above.
    control_activity_id_a = db.Column(db.Integer, nullable=False)
    checklist_item_id_a = db.Column(db.String(50), nullable=False)
    control_activity_id_b = db.Column(db.Integer, nullable=False)
    checklist_item_id_b = db.Column(db.String(50), nullable=False)

    justification = db.Column(db.Text, nullable=True)

    # Which review row triggered this confirmation -- audit trail only.
    # SET NULL on delete: losing the source review shouldn't delete the
    # permanent confirmation it produced.
    source_review_id = db.Column(
        db.BigInteger,
        db.ForeignKey("clause_checklist_review.id", ondelete="SET NULL"),
        nullable=True,
    )

    confirmed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "clause_id", "control_activity_id_a", "checklist_item_id_a",
            "control_activity_id_b", "checklist_item_id_b",
            name="uq_confirmed_duplicate_pair",
        ),
    )

