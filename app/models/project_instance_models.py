from app import db
from sqlalchemy.sql import func
from datetime import datetime


# --- Project Instance Tables ---
# These tables are copies of the central 'template' tables (Guidelines, Clauses, etc.)
# but are specifically tied to a single project. This ensures data isolation.


class ProjectGuideline(db.Model):
    __tablename__ = "project_guidelines"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    project_id = db.Column(db.BigInteger, db.ForeignKey("projects.id"), nullable=False)
    original_guideline_id = db.Column(
        db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False
    )
    guideline_data = db.Column(db.JSON, nullable=True)  # Copied from original
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    project = db.relationship("Projects", back_populates="project_guidelines")
    original_guideline = db.relationship("Guidelines")
    project_clauses = db.relationship(
        "ProjectClause",
        back_populates="project_guideline",
        cascade="all, delete-orphan",
    )


class ProjectClause(db.Model):
    __tablename__ = "project_clauses"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    project_guideline_id = db.Column(
        db.BigInteger, db.ForeignKey("project_guidelines.id"), nullable=False
    )
    original_clause_id = db.Column(
        db.BigInteger, db.ForeignKey("clauses.id"), nullable=False
    )
    clause_no = db.Column(db.String(50), nullable=True)
    clause_text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    applicability = db.Column(db.Boolean, default=False)
    overall_compliance_status = db.Column(db.String(50), default="To be Assessed")
    updated_at = db.Column(db.TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())
    # In your models.py, add to ProjectClause model:
    assessment_status = db.Column(db.String(50), default="In Progress")  # "In Progress", "Completed"
    assessment_closed_at = db.Column(db.DateTime, nullable=True)
    assessment_closed_by = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)

    # Relationships
    project_guideline = db.relationship(
        "ProjectGuideline", back_populates="project_clauses"
    )
    original_clause = db.relationship("Clauses")
    consolidated_findings = db.relationship(
        "ConsolidatedFindingsSummary", 
        back_populates="clause", 
        uselist=False,
        cascade="all, delete-orphan"
    )
    consolidated_recommendations = db.relationship(
        "ConsolidatedRecommendationsSummary", 
        back_populates="clause", 
        uselist=False,
        cascade="all, delete-orphan"
    )
    project_compliance_activities = db.relationship(
        "ProjectComplianceActivity",
        back_populates="project_clause",
        cascade="all, delete-orphan",
    )


class ProjectComplianceActivity(db.Model):
    __tablename__ = "project_compliance_activities"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    project_clause_id = db.Column(
        db.BigInteger, db.ForeignKey("project_clauses.id"), nullable=False
    )
    original_activity_id = db.Column(
        db.BigInteger, db.ForeignKey("compliance_activities.id"), nullable=False
    )
    activity_id = db.Column(db.String(255), nullable=False)
    activity_description = db.Column(db.Text, nullable=False)
    responsible_party = db.Column(db.String(255), nullable=False)
    frequency = db.Column(db.String(50), nullable=False)
    evidence_required = db.Column(
        db.Text, nullable=False
    )  # This is the description of what's required
    
    applicability = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    project_clause = db.relationship(
        "ProjectClause", back_populates="project_compliance_activities"
    )
    original_activity = db.relationship("ComplianceActivities")
    project_control_activities = db.relationship(
        "ProjectControlActivity",
        back_populates="project_compliance_activity",
        cascade="all, delete-orphan",
    )

     


class ProjectControlActivity(db.Model):
    __tablename__ = "project_control_activities"
    id = db.Column(db.Integer, primary_key=True)
    project_compliance_activity_id = db.Column(
        db.BigInteger, db.ForeignKey("project_compliance_activities.id"), nullable=False
    )
    original_control_id = db.Column(
        db.Integer, db.ForeignKey("control_activities.id"), nullable=False
    )

    # Template data (copied over for context)
    activity_code = db.Column(db.String, nullable=False)
    activity_name = db.Column(db.Text)
    activity_description = db.Column(db.Text)
    objective = db.Column(db.Text)
    owner = db.Column(db.String)
    control_type = db.Column(db.String)
    frequency = db.Column(db.String)
    sampling_guidance = db.Column(db.Text)

    # Fields for auditor/RE input (project-specific data)
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

    # NEW FIELDS FOR COMPLETE EVALUATION DATA
    evidence_admissibility_decision = db.Column(db.String(10))  # "Yes" or "No"
    evidence_quality_rating = db.Column(db.String(50))  # "STRONG", "ADEQUATE", "WEAK", "INADMISSIBLE"
    reason_for_inadmissibility = db.Column(db.Text)  # Text explanation or "N/A"
    
    required_effectiveness_design = db.Column(db.String(10))  # "yes" or "no"
    required_effectiveness_implementation = db.Column(db.String(10))  # "yes" or "no"
    required_effectiveness_operating = db.Column(db.String(10))  # "yes" or "no"
    
    detailed_control_testing_results = db.Column(db.Text)  # Detailed testing results
    
    severity_classification_per_finding = db.Column(db.Text)  # "Finding 1: Critical, Finding 2: Major" etc
    overall_severity_classification = db.Column(db.String(50))  # "Critical", "Major", "Significant", "Minor", "No findings noted"

    # Relationships
    project_compliance_activity = db.relationship(
        "ProjectComplianceActivity", back_populates="project_control_activities"
    )
    original_control = db.relationship("ControlActivity")
    project_test_procedure = db.relationship(
        "ProjectTestSteps",
        back_populates="project_control_activity",
        uselist=False,
        cascade="all, delete-orphan",
    )
    submitted_evidences = db.relationship(
        "ProjectEvidenceArtifact",
        back_populates="project_control_activity",
        cascade="all, delete-orphan",
    )


class TestProcedureFile(db.Model):
    __tablename__ = "test_procedure_files"

    id = db.Column(db.Integer, primary_key=True)
    test_procedure_id = db.Column(db.Integer, db.ForeignKey("project_test_steps.id"))
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(100))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    field_type = db.Column(db.String(50))  # 'walkthrough_files' or 'sampling_files'

    # Relationship back to ProjectTestSteps
    project_test_steps = db.relationship(
        "ProjectTestSteps", back_populates="test_procedure_files"
    )


class ProjectTestSteps(db.Model):
    __tablename__ = "project_test_steps"
    id = db.Column(db.Integer, primary_key=True)
    project_control_activity_id = db.Column(
        db.Integer, db.ForeignKey("project_control_activities.id")
    )
    original_test_steps_id = db.Column(db.Integer, db.ForeignKey("test_steps.id"))

    # Template data
    walkthrough = db.Column(db.Text)
    sampling = db.Column(db.Text)
    # Add these fields to your ProjectTestSteps model
    additional_walkthrough = db.Column(db.Text, nullable=True)
    additional_sampling = db.Column(db.Text, nullable=True)

    # Relationships
    project_control_activity = db.relationship(
        "ProjectControlActivity", back_populates="project_test_procedure"
    )
    original_test_steps = db.relationship("TestSteps")
    project_documents = db.relationship(
        "ProjectDocumentReview",
        back_populates="project_test_procedure",
        cascade="all, delete-orphan",
    )
    project_interview = db.relationship(
        "ProjectInterview",
        back_populates="project_test_procedure",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # ADD THIS NEW RELATIONSHIP for file attachments
    test_procedure_files = db.relationship(
        "TestProcedureFile",
        back_populates="project_test_steps",
        cascade="all, delete-orphan",
        # lazy="dynamic",
    )


class ProjectDocumentReview(db.Model):
    __tablename__ = "project_document_reviews"
    id = db.Column(db.Integer, primary_key=True)
    project_test_procedure_id = db.Column(
        db.Integer, db.ForeignKey("project_test_steps.id")
    )
    original_document_review_id = db.Column(
        db.Integer, db.ForeignKey("document_reviews.id")
    )
    document_name = db.Column(db.String)

    # Relationships
    project_test_procedure = db.relationship(
        "ProjectTestSteps", back_populates="project_documents"
    )
    original_document_review = db.relationship("DocumentReview")


class ProjectInterview(db.Model):
    __tablename__ = "project_interviews"
    id = db.Column(db.Integer, primary_key=True)
    project_test_procedure_id = db.Column(
        db.Integer, db.ForeignKey("project_test_steps.id")
    )
    original_interview_id = db.Column(db.Integer, db.ForeignKey("interviews.id"))

    # Relationships
    project_test_procedure = db.relationship(
        "ProjectTestSteps", back_populates="project_interview"
    )
    original_interview = db.relationship("Interview")
    project_roles = db.relationship(
        "ProjectInterviewRole",
        back_populates="project_interview",
        cascade="all, delete-orphan",
    )
    project_questions = db.relationship(
        "ProjectInterviewQuestion",
        back_populates="project_interview",
        cascade="all, delete-orphan",
    )


class ProjectInterviewRole(db.Model):
    __tablename__ = "project_interview_roles"
    id = db.Column(db.Integer, primary_key=True)
    project_interview_id = db.Column(db.Integer, db.ForeignKey("project_interviews.id"))
    original_role_id = db.Column(db.Integer, db.ForeignKey("interview_roles.id"))
    role = db.Column(db.String)

    # Relationships
    project_interview = db.relationship(
        "ProjectInterview", back_populates="project_roles"
    )
    original_role = db.relationship("InterviewRole")


class ProjectInterviewQuestion(db.Model):
    __tablename__ = "project_interview_questions"
    id = db.Column(db.Integer, primary_key=True)
    project_interview_id = db.Column(db.Integer, db.ForeignKey("project_interviews.id"))
    original_question_id = db.Column(
        db.Integer, db.ForeignKey("interview_questions.id")
    )
    question = db.Column(db.Text)

    # Project-specific data
    answer = db.Column(db.Text, nullable=True)
    is_compliant = db.Column(db.Boolean, default=False, nullable=True)

    # Relationships
    project_interview = db.relationship(
        "ProjectInterview", back_populates="project_questions"
    )
    original_question = db.relationship("InterviewQuestion")


class EvidenceFile(db.Model):
    __tablename__ = "evidence_files"

    id = db.Column(db.Integer, primary_key=True)
    project_evidence_artifact_id = db.Column(
        db.Integer,
        db.ForeignKey("project_evidence_artifacts.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name = db.Column(db.String, nullable=False)  # original filename
    stored_filename = db.Column(db.String, nullable=False)  # actual filename on disk
    file_path = db.Column(db.String, nullable=False)  # relative or absolute path
    content_type = db.Column(db.String, nullable=True)
    file_size = db.Column(db.Integer, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    artifact = db.relationship(
        "ProjectEvidenceArtifact",
        back_populates="evidence_files",
        passive_deletes=True,
    )


class ProjectEvidenceArtifact(db.Model):
    __tablename__ = "project_evidence_artifacts"
    id = db.Column(db.Integer, primary_key=True)
    project_control_activity_id = db.Column(
        db.Integer, db.ForeignKey("project_control_activities.id"), nullable=False
    )
    original_evidence_id = db.Column(db.Integer, db.ForeignKey("evidence_artifacts.id"))

    # Template data
    category = db.Column(db.String)
    item = db.Column(db.String)

    # Project-specific data
    evidence_text = db.Column(db.Text, nullable=True)
    evidence_file_path = db.Column(db.String, nullable=True)
    is_compliant = db.Column(db.Boolean, default=False, nullable=True)

    # Relationships
    project_control_activity = db.relationship(
        "ProjectControlActivity", back_populates="submitted_evidences"
    )
    original_evidence = db.relationship("EvidenceArtifact")

    # NEW: one-to-many to EvidenceFile
    evidence_files = db.relationship(
        "EvidenceFile",
        back_populates="artifact",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )




class ClauseConsolidatedSummary(db.Model):
    __tablename__ = 'clause_consolidated_summaries'
    
    id = db.Column(db.Integer, primary_key=True)
    clause_id = db.Column(db.Integer, db.ForeignKey('project_clauses.id'), nullable=False)
    consolidated_data = db.Column(db.JSON, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('Users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    clause = db.relationship('ProjectClause', backref=db.backref('consolidated_summaries', lazy=True))
    creator = db.relationship('Users', backref=db.backref('created_summaries', lazy=True))


    