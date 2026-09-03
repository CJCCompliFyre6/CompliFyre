from app import db
import enum
import os
from sqlalchemy.sql import func
from app.models.download import *
from app.models.auditOrganization import *
import sqlalchemy as sa
from datetime import datetime

# this is for the request guidelines model
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, FileField, SubmitField
from wtforms.validators import DataRequired, Optional, URL
from flask_wtf.file import FileAllowed


class PromptType(enum.Enum):
    GUIDELINES = "guidelines"
    CLAUSES = "clauses"
    ACTIVITY = "activity"
    TEST_PROCEDURE = "test_procedure"
    EVALUATION = "evaluation"


class AIPrompts(db.Model):
    """Stores AI prompts, their type, version, and creator. Deleting a user will delete their prompts."""

    __tablename__ = "AIPrompts"

    prompt_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)

    prompt_type = db.Column(
        db.String(256),
        nullable=False,
    )

    prompt_text = db.Column(db.Text, nullable=False)
    version = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    user = db.relationship(
        "Users", backref=db.backref("ai_prompts", cascade="all, delete-orphan")
    )

    def __repr__(self):
        return f"<AIPrompt {self.prompt_type.value} v{self.version}>"

    def to_dict(self):
        """Converts the object to a dictionary for JSON serialization."""
        return {
            "prompt_id": self.prompt_id,
            "prompt_type": self.prompt_type.value if self.prompt_type else None,
            "prompt_text": self.prompt_text,
            "version": self.version,
            "is_active": self.is_active,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RawLLMResponse(db.Model):
    """
    Stores raw LLM responses for debugging and analysis purposes.
    """

    __tablename__ = "raw_llm_responses"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_id = db.Column(
        db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False
    )
    task_type = db.Column(db.String(50), nullable=False)
    page_range = db.Column(db.String(100), nullable=True)

    # Context information
    context_start_text = db.Column(db.Text, nullable=True)  # First 500 chars of context
    context_end_text = db.Column(db.Text, nullable=True)  # Last 500 chars of context
    total_context_length = db.Column(
        db.Integer, nullable=True
    )  # Total chars in context

    # LLM metrics
    raw_response = db.Column(db.Text, nullable=True)
    prompt_tokens = db.Column(db.Integer, nullable=True)
    completion_tokens = db.Column(db.Integer, nullable=True)
    total_tokens = db.Column(db.Integer, nullable=True)

    # Extraction quality metrics
    expected_clauses_count = db.Column(
        db.Integer, nullable=True
    )  # Expected clauses (if known)
    extracted_clauses_count = db.Column(db.Integer, nullable=True)  # Actual extracted
    missing_clauses = db.Column(
        db.Text, nullable=True
    )  # JSON of missing clause numbers/names
    confidence_score = db.Column(db.Float, nullable=True)  # Overall confidence

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    guideline = db.relationship(
        "Guidelines",
        backref=db.backref("raw_llm_responses", cascade="all, delete-orphan"),
    )


class GuidelineRequestForm(FlaskForm):
    guideline_name = StringField('Guideline Name', validators=[DataRequired()])
    regulator_name = StringField('Regulator Name', validators=[DataRequired()])
    web_link = StringField('Web Link', validators=[Optional(), URL()])
    attachment = FileField('Attach Guideline (PDF)', validators=[
        Optional(),
        FileAllowed(['pdf'], 'Only PDF files are allowed!')
    ])
    submit = SubmitField('Submit Request')

class GuidelineRequest(db.Model):
    __tablename__ = 'guideline_requests'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=False)
    guideline_name = db.Column(db.String(500), nullable=False)
    regulator_name = db.Column(db.String(500), nullable=False)
    web_link = db.Column(db.String(1000))
    attachment_path = db.Column(db.String(500))
    status = db.Column(db.String(50), default='pending')  # pending, processing, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('Users', backref=db.backref('guideline_requests', lazy=True))
    
    def to_dict(self):
        """Convert model to dictionary for API responses"""
        org_name = None
        if self.user and self.user.organization:
            org_name = self.user.organization.organization_name
        
        attachment_filename = None
        if self.attachment_path:
            attachment_filename = os.path.basename(self.attachment_path)
        
        return {
            'id': self.id,
            'guideline_name': self.guideline_name,
            'regulator_name': self.regulator_name,
            'web_link': self.web_link,
            'attachment_filename': attachment_filename,
            'status': self.status,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None,
            'updated_at': self.updated_at.strftime('%Y-%m-%d %H:%M:%S') if self.updated_at else None,
            'user_name': self.user.name if self.user else None,
            'user_email': self.user.email if self.user else None,
            'user_phone': getattr(self.user, 'phone_no', None) if self.user else None,
            'organization': org_name
        }



class Guidelines(db.Model):
    """
    Stores guideline data from a URL or file. Deleting a Guideline will also delete all its
    child Clauses and Projects.
    """

    __tablename__ = "guidelines"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_data = db.Column(db.JSON, nullable=True)
    url_id = db.Column(db.BigInteger, db.ForeignKey("download.id"), nullable=True)
    file_id = db.Column(db.BigInteger, db.ForeignKey("file.id"), nullable=True)
    enabled = db.Column(
        db.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    disabled_reason = db.Column(db.Text, nullable=True)
    disabled_at = db.Column(db.TIMESTAMP, nullable=True)
    catalogue_enabled = db.Column(db.Boolean, nullable=False, default=False)
    applicable_licenses = db.Column(db.JSON, nullable=True)
    structure_map = db.Column(db.JSON, nullable=True)

    # -- Added 2026-08-20: guideline-level clause-review sign-off gate --
    # NULL = review not yet marked complete; activity generation should be blocked.
    # Not tied to reviewing every single clause -- an explicit human decision that
    # review is sufficient to proceed (Build Sequence #332/#337).
    clause_review_completed_at = db.Column(db.TIMESTAMP, nullable=True)
    clause_review_completed_by = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)

    regulator_body_id = db.Column(
        db.BigInteger,
        nullable=True
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    download = db.relationship("Download", backref="guidelines")
    file = db.relationship("File", backref="guidelines")
    clauses = db.relationship(
        "Clauses", back_populates="guideline", cascade="all, delete-orphan"
    )
    projects = db.relationship(
        "Projects", back_populates="guidelines_rel", cascade="all, delete-orphan"
    )
    audits = db.relationship(
        "AuditOrganization",
        secondary=auditor_selected_guidelines,
        back_populates="selected_guidelines",
    )


class ConsolidatedTestSummary(db.Model):
    __tablename__ = "consolidated_test_summaries"

    id = db.Column(db.Integer, primary_key=True)
    clause_id = db.Column(
        db.BigInteger, db.ForeignKey("project_clauses.id"), nullable=False
    )  # Changed to BigInteger
    consolidated_summary = db.Column(db.Text)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship to ProjectClause
    project_clause = db.relationship(
        "ProjectClause", backref=db.backref("consolidated_test_summaries", lazy=True)
    )


class ConsolidatedObservationSummary(db.Model):
    __tablename__ = "consolidated_observation_summaries"

    id = db.Column(db.Integer, primary_key=True)
    clause_id = db.Column(
        db.BigInteger, db.ForeignKey("project_clauses.id"), nullable=False
    )
    consolidated_observation = db.Column(db.Text)  # Stores JSON data
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship to ProjectClause
    project_clause = db.relationship(
        "ProjectClause",
        backref=db.backref("consolidated_observation_summaries", lazy=True),
    )


class ConsolidatedFindingsSummary(db.Model):
    __tablename__ = "consolidated_findings_summary"

    id = db.Column(db.Integer, primary_key=True)
    clause_id = db.Column(
        db.Integer, db.ForeignKey("project_clauses.id"), nullable=False
    )
    consolidated_findings = db.Column(db.Text)  # JSON string storing the findings data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship
    clause = db.relationship("ProjectClause", back_populates="consolidated_findings")


class ConsolidatedRecommendationsSummary(db.Model):
    __tablename__ = "consolidated_recommendations_summary"

    id = db.Column(db.Integer, primary_key=True)
    clause_id = db.Column(
        db.Integer, db.ForeignKey("project_clauses.id"), nullable=False
    )
    consolidated_recommendations = db.Column(
        db.Text
    )  # JSON string storing recommendations data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationship
    clause = db.relationship("ProjectClause", back_populates="consolidated_recommendations")


class Clauses(db.Model):
    """
    Represents a specific clause within a Guideline. Deleting a Clause will also delete
    all of its associated ComplianceActivities.

    clause_type: OBLIGATION / PRINCIPLE / MIXED / DEFINITION / APPLICABILITY / EXEMPTION / REFERENCE
    extraction_status: EXTRACTED / APPROVED / FLAGGED
    flag_reason: UNKNOWN_APPLICABILITY / AMBIGUOUS_MERGE / UNKNOWN_LICENSE / CROSS_GUIDELINE_REF / EXTERNAL_REF
    """

    __tablename__ = "clauses"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    clause_no = db.Column(db.String(500), nullable=True)
    clause_text = db.Column(db.Text, nullable=False)
    guideline_id = db.Column(
        db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False
    )
    page_number = db.Column(db.Integer, nullable=True)
    clause_type = db.Column(db.String(50), nullable=True, default='OBLIGATION')
    applicable_to = db.Column(db.JSON, nullable=True)
    clause_references = db.Column(db.JSON, nullable=True)
    extraction_status = db.Column(db.String(50), nullable=True, default='EXTRACTED')
    flag_reason = db.Column(db.String(200), nullable=True)
    activity_generation_claimed_at = db.Column(db.TIMESTAMP, nullable=True)  # atomic claim marker for race-safe activity generation

    # -- Added 2026-08-18: preserve AI reasoning + support human review/correction tracking --
    intent_summary = db.Column(db.Text, nullable=True)  # AI's one-sentence "what this clause does" (Stage 2 Q0)
    ai_assigned_clause_type = db.Column(db.String(50), nullable=True)  # original AI label, set once, never overwritten
    clause_type_reviewed_at = db.Column(db.TIMESTAMP, nullable=True)  # NULL = never reviewed by a human
    clause_type_reviewed_by = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    clause_type_review_notes = db.Column(db.Text, nullable=True)  # human reviewer's reasoning, if any
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    guideline = db.relationship("Guidelines", back_populates="clauses")
    compliance_activities = db.relationship(
        "ComplianceActivities", back_populates="clauses", cascade="all, delete-orphan"
    )

class ComplianceActivities(db.Model):
    """
    Defines compliance activities for a Clause. Deleting a ComplianceActivity will delete its
    related Projects, ControlActivities, HowToPerformActivity, and TestProcedures.
    """

    __tablename__ = "compliance_activities"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    clause_id = db.Column(db.BigInteger, db.ForeignKey("clauses.id"), nullable=False)
    relevant_departments_id = db.Column(
        db.BigInteger,
        db.ForeignKey("OrganizationDepartments.department_id"),
        nullable=False,
    )
    relevant_departments = db.Column(db.String(255), nullable=False)
    process = db.Column(db.String(255), nullable=False)
    sub_process = db.Column(db.String(255), nullable=False)
    activity_id = db.Column(db.String(255), nullable=False)
    activity_description = db.Column(db.Text, nullable=False)
    responsible_party = db.Column(db.String(255), nullable=False)
    frequency = db.Column(db.String(50), nullable=False)
    evidence_required = db.Column(db.Text, nullable=False)
    compliance_level = db.Column(db.String(50), nullable=False, default="Design")
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationships
    department = db.relationship(
        "OrganizationDepartments", backref="compliance_activities"
    )
    clauses = db.relationship("Clauses", back_populates="compliance_activities")
    projects = db.relationship(
        "Projects", back_populates="activity_rel", cascade="all, delete-orphan"
    )
    control_activities = db.relationship(
        "ControlActivity",
        back_populates="compliance_activity",
        cascade="all, delete-orphan",
    )
    how_to_perform_activity = db.relationship(
        "HowToPerformActivity",
        back_populates="compliance_activity",
        cascade="all, delete-orphan",
    )
    test_procedures = db.relationship(
        "TestProcedures",
        back_populates="compliance_activity",
        cascade="all, delete-orphan",
    )

    # 🔹 Universal dict serializer
    def to_dict(self, include_relationships=True):
        # Serialize columns
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns}

        # Convert timestamps
        if data.get("created_at"):
            data["created_at"] = data["created_at"].isoformat()
        if data.get("updated_at"):
            data["updated_at"] = data["updated_at"].isoformat()

        # Serialize relationships
        if include_relationships:

            def serialize(obj):
                if hasattr(obj, "to_dict"):
                    return obj.to_dict()
                return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}

            data["department"] = serialize(self.department) if self.department else None
            data["clauses"] = serialize(self.clauses) if self.clauses else None
            data["projects"] = (
                [serialize(p) for p in self.projects] if self.projects else []
            )
            data["control_activities"] = (
                [serialize(c) for c in self.control_activities]
                if self.control_activities
                else []
            )
            data["how_to_perform_activity"] = (
                [serialize(h) for h in self.how_to_perform_activity]
                if self.how_to_perform_activity
                else []
            )
            data["test_procedures"] = (
                [serialize(t) for t in self.test_procedures]
                if self.test_procedures
                else []
            )

        return data


class HowToPerformActivity(db.Model):
    """Stores JSON data describing how to perform a specific ComplianceActivity."""

    __tablename__ = "how_to_perform_activity"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    activity_id = db.Column(
        db.BigInteger, db.ForeignKey("compliance_activities.id"), nullable=False
    )
    data = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    compliance_activity = db.relationship(
        "ComplianceActivities", back_populates="how_to_perform_activity"
    )


activity_guideline_impacted_departments = db.Table(
    "activity_guideline_impacted_departments",
    db.Column(
        "guideline_id",
        db.BigInteger,
        db.ForeignKey("activity_guidelines.id"),
        primary_key=True,
    ),
    db.Column(
        "department_id",
        db.BigInteger,
        db.ForeignKey("OrganizationDepartments.department_id"),
        primary_key=True,
    ),
)


activity_guideline_supporting_teams = db.Table(
    "activity_guideline_supporting_teams",
    db.Column(
        "guideline_id",
        db.BigInteger,
        db.ForeignKey("activity_guidelines.id"),
        primary_key=True,
    ),
    db.Column(
        "department_id",
        db.BigInteger,
        db.ForeignKey("OrganizationDepartments.department_id"),
        primary_key=True,
    ),
)


class ActivityGuideline(db.Model):
    """
    Central model for an activity guideline. Deleting an ActivityGuideline will also delete its
    child intent analysis, performance instructions, and evidence artifacts.
    """

    __tablename__ = "activity_guidelines"

    id = db.Column(db.BigInteger, primary_key=True)
    activity_code = db.Column(db.String(100), nullable=False)
    activity = db.Column(db.Text, nullable=False)
    redundancy_check = db.Column(db.Text)
    risk_level = db.Column(db.String(20))
    mitigation_actions = db.Column(db.Text)
    frequency = db.Column(db.String(50))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    key_owner_id = db.Column(
        db.BigInteger,
        db.ForeignKey("OrganizationDepartments.department_id"),
        nullable=True,
    )

    key_owner = db.relationship(
        "OrganizationDepartments",
        foreign_keys=[key_owner_id],
        backref="owned_guidelines",
    )
    supporting_teams = db.relationship(
        "OrganizationDepartments",
        secondary="activity_guideline_supporting_teams",
        backref="supported_guidelines",
    )
    impacted_departments = db.relationship(
        "OrganizationDepartments",
        secondary="activity_guideline_impacted_departments",
        backref="impacted_guidelines",
    )
    intent_analysis = db.relationship(
        "ClauseIntentAnalysis",
        back_populates="guideline",
        uselist=False,
        cascade="all, delete-orphan",
    )
    how_to_perform = db.relationship(
        "HowToPerform",
        back_populates="guideline",
        uselist=False,
        cascade="all, delete-orphan",
    )
    evidences_artifacts = db.relationship(
        "EvidencesArtifacts",
        back_populates="guideline",
        uselist=False,
        cascade="all, delete-orphan",
    )


class HowToPerform(db.Model):
    """Stores instructions, roles, and timelines for an ActivityGuideline."""

    __tablename__ = "how_to_perform"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_id = db.Column(
        db.BigInteger,
        db.ForeignKey("activity_guidelines.id"),
        nullable=False,
        unique=True,
    )
    execution_steps = db.Column(db.JSON, nullable=True)
    responsible_roles = db.Column(db.JSON, nullable=True)
    timelines = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    guideline = db.relationship("ActivityGuideline", back_populates="how_to_perform")


class EvidencesArtifacts(db.Model):
    """Stores evidence and artifact details for an ActivityGuideline."""

    __tablename__ = "evidences_artifacts"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_id = db.Column(
        db.BigInteger,
        db.ForeignKey("activity_guidelines.id"),
        nullable=False,
        unique=True,
    )
    documents = db.Column(db.JSON, nullable=True)
    logs = db.Column(db.JSON, nullable=True)
    approvals = db.Column(db.JSON, nullable=True)
    dashboards = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    guideline = db.relationship(
        "ActivityGuideline", back_populates="evidences_artifacts"
    )


class ClauseIntentAnalysis(db.Model):
    """Stores intent, risk, and impact analysis for an ActivityGuideline."""

    __tablename__ = "clause_intent_analysis"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_id = db.Column(
        db.BigInteger, db.ForeignKey("activity_guidelines.id"), nullable=False
    )
    intent = db.Column(db.Text, nullable=True)
    regulatory_expectations = db.Column(db.Text, nullable=True)
    risk_areas = db.Column(db.Text, nullable=True)
    operational_impact = db.Column(db.Text, nullable=True)
    core_purpose = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    guideline = db.relationship("ActivityGuideline", back_populates="intent_analysis")


class TestProcedures(db.Model):
    """Stores JSON data describing test procedures for a ComplianceActivity."""

    __tablename__ = "test_procedures"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    activity_id = db.Column(
        db.BigInteger, db.ForeignKey("compliance_activities.id"), nullable=False
    )
    data = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    compliance_activity = db.relationship(
        "ComplianceActivities", back_populates="test_procedures"
    )


control_evidences = db.Table(
    "control_evidences",
    db.Column(
        "control_id",
        db.Integer,
        db.ForeignKey("control_activities.id"),
        primary_key=True,
    ),
    db.Column(
        "evidence_id",
        db.Integer,
        db.ForeignKey("evidence_artifacts.id"),
        primary_key=True,
    ),
)


class ControlActivity(db.Model):
    """
    Defines a control activity. Deleting a ControlActivity will also delete its
    associated TestSteps.
    """

    __tablename__ = "control_activities"

    id = db.Column(db.Integer, primary_key=True)
    activity_code = db.Column(db.String, nullable=False)
    activity_name = db.Column(db.Text)
    activity_description = db.Column(db.Text)
    objective = db.Column(db.Text)
    owner = db.Column(db.String)
    control_type = db.Column(db.String)
    frequency = db.Column(db.String)
    sampling_guidance = db.Column(db.Text)
    auditor_observation = db.Column(db.Text)
    findings = db.Column(db.Text)
    impact = db.Column(db.Text)
    severity = db.Column(db.String)
    recommendations = db.Column(db.Text)
    reviewer_notes = db.Column(db.Text)
    compliant_status = db.Column(db.String)
    control_findings = db.Column(db.Text)
    control_recommendation = db.Column(db.Text)
    explain_test_procedure = db.Column(db.Text)
    assessment_objective = db.Column(db.String(100), nullable=True)
    assessment_objective_rationale = db.Column(db.Text, nullable=True)
    test_attributes = db.Column(db.JSON, nullable=True)

    compliance_activity_id = db.Column(
        db.BigInteger,
        db.ForeignKey("compliance_activities.id"),
        unique=True,
        nullable=True,
    )

    compliance_activity = db.relationship(
        "ComplianceActivities", back_populates="control_activities"
    )
    test_procedure = db.relationship(
        "TestSteps",
        back_populates="control_activity",
        uselist=False,
        cascade="all, delete-orphan",
    )
    evidences = db.relationship(
        "EvidenceArtifact", secondary=control_evidences, back_populates="controls"
    )


class TestSteps(db.Model):
    """
    Outlines test steps for a ControlActivity. Deleting TestSteps will delete its
    child DocumentReviews and Interviews.
    """

    __tablename__ = "test_steps"

    id = db.Column(db.Integer, primary_key=True)
    control_id = db.Column(db.Integer, db.ForeignKey("control_activities.id"))
    walkthrough = db.Column(db.Text)
    sampling = db.Column(db.Text)

    control_activity = db.relationship(
        "ControlActivity", back_populates="test_procedure"
    )
    documents = db.relationship(
        "DocumentReview", back_populates="test_procedure", cascade="all, delete-orphan"
    )
    interviews = db.relationship(
        "Interview",
        back_populates="test_procedure",
        uselist=False,
        cascade="all, delete-orphan",
    )


class DocumentReview(db.Model):
    """Represents a specific document to be reviewed as part of a TestSteps procedure."""

    __tablename__ = "document_reviews"

    id = db.Column(db.Integer, primary_key=True)
    test_procedure_id = db.Column(db.Integer, db.ForeignKey("test_steps.id"))
    document_name = db.Column(db.String)

    test_procedure = db.relationship("TestSteps", back_populates="documents")


class Interview(db.Model):
    """
    Represents an interview for a TestSteps procedure. Deleting an Interview will
    delete its associated Roles and Questions.
    """

    __tablename__ = "interviews"

    id = db.Column(db.Integer, primary_key=True)
    test_procedure_id = db.Column(db.Integer, db.ForeignKey("test_steps.id"))

    test_procedure = db.relationship("TestSteps", back_populates="interviews")
    roles = db.relationship(
        "InterviewRole", back_populates="interview", cascade="all, delete-orphan"
    )
    questions = db.relationship(
        "InterviewQuestion", back_populates="interview", cascade="all, delete-orphan"
    )


class InterviewRole(db.Model):
    """Defines a role (e.g., 'Manager') to be interviewed as part of an Interview."""

    __tablename__ = "interview_roles"

    id = db.Column(db.Integer, primary_key=True)
    interview_id = db.Column(db.Integer, db.ForeignKey("interviews.id"))
    role = db.Column(db.String)

    interview = db.relationship("Interview", back_populates="roles")


class InterviewQuestion(db.Model):
    """Stores a specific question and its answer for an Interview."""

    __tablename__ = "interview_questions"

    id = db.Column(db.Integer, primary_key=True)
    interview_id = db.Column(db.Integer, db.ForeignKey("interviews.id"))
    question = db.Column(db.Text)
    answer = db.Column(db.Text, nullable=True)
    complaint = db.Column(db.Boolean, default=False, nullable=True)

    interview = db.relationship("Interview", back_populates="questions")


class EvidenceArtifact(db.Model):
    """
    Stores a piece of evidence. This can be linked to multiple ControlActivities
    through a many-to-many relationship.
    """

    __tablename__ = "evidence_artifacts"

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String)
    item = db.Column(db.String)
    evidance = db.Column(db.Text, nullable=True)
    evidance_file = db.Column(db.String, nullable=True)
    complaint = db.Column(db.Boolean, default=False, nullable=True)

    controls = db.relationship(
        "ControlActivity", secondary=control_evidences, back_populates="evidences"
    )


class RiskCategory(db.Model):
    """
    Top-level risk category (e.g. Financial Risk, Financial Crime Risk) --
    seeded, not user-created. Each RiskArea belongs to exactly one category.
    Two-level taxonomy confirmed with Ankita, Build Sequence #372.
    """
    __tablename__ = "risk_categories"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    display_order = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    risk_areas = db.relationship("RiskArea", back_populates="category")


class RiskArea(db.Model):
    """
    Standard library of specific risks a bank typically monitors and measures --
    seeded, not user-created. Each belongs to one RiskCategory. Each
    ControlActivity can map to multiple risk areas via ControlRiskMapping.
    Foundation for the RCM (Risk Control Matrix). Build Sequence #372.
    """
    __tablename__ = "risk_areas"
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    description = db.Column(db.Text, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("risk_categories.id"), nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    category = db.relationship("RiskCategory", back_populates="risk_areas")


class ControlRiskMapping(db.Model):
    """
    Many-to-many mapping between a ControlActivity and a RiskArea, generated
    by an LLM classification call from the control's existing description and
    objective. Stores the LLM's rationale for each mapping, not just the bare
    link -- so an auditor reviewing the RCM can see WHY a control was mapped
    to a given risk area. Build Sequence #372.
    """
    __tablename__ = "control_risk_mappings"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    control_activity_id = db.Column(
        db.BigInteger, db.ForeignKey("control_activities.id"), nullable=False
    )
    risk_area_id = db.Column(
        db.Integer, db.ForeignKey("risk_areas.id"), nullable=False
    )
    rationale = db.Column(db.Text, nullable=True)
    generated_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    control_activity = db.relationship("ControlActivity", backref="risk_mappings")
    risk_area = db.relationship("RiskArea", backref="control_mappings")

    __table_args__ = (
        db.UniqueConstraint(
            "control_activity_id", "risk_area_id", name="uq_control_risk_mapping"
        ),
    )
