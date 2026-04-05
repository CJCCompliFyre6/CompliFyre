# app/models/auditManagement.py
from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func


class AuditEngagements(db.Model):
    __tablename__ = "AuditEngagements"
    engagement_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(
        Enum("planned", "in_progress", "completed", "archived", name="audit_engagement_status_enum"), 
        default="planned"
    )
    lead_auditor_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    organization = db.relationship("Organizations", backref="audit_engagements")
    lead_auditor = db.relationship("Users", backref="audit_engagements")


class AuditControls(db.Model):
    __tablename__ = "AuditControls"
    control_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    control_type = db.Column(db.String(100))
    test_procedure = db.Column(db.Text)
    required_evidence = db.Column(db.Text)
    risk_rating = db.Column(
        Enum("LOW", "MEDIUM", "HIGH", name="control_risk_rating_enum"), 
        nullable=False
    )
    owner_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    reviewer_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    organization = db.relationship("Organizations", backref="audit_controls")
    owner = db.relationship(
        "Users", foreign_keys=[owner_id], backref="owned_audit_controls"
    )
    reviewer = db.relationship(
        "Users", foreign_keys=[reviewer_id], backref="reviewed_audit_controls"
    )


class ControlRegulationMapping(db.Model):
    __tablename__ = "ControlRegulationMapping"
    mapping_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    control_id = db.Column(db.BigInteger, db.ForeignKey("AuditControls.control_id"))
    document_id = db.Column(
        db.BigInteger, db.ForeignKey("RegulatoryDocuments.document_id")
    )
    mapping_justification = db.Column(db.Text)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    control = db.relationship("AuditControls", backref="control_regulation_mappings")
    document = db.relationship(
        "RegulatoryDocuments", backref="control_regulation_mappings"
    )


class AuditTestingTemplates(db.Model):
    __tablename__ = "AuditTestingTemplates"
    template_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    control_id = db.Column(db.BigInteger, db.ForeignKey("AuditControls.control_id"))
    question = db.Column(db.Text, nullable=False)
    expected_response = db.Column(db.Text)
    sequence_no = db.Column(db.Integer)
    is_mandatory = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    organization = db.relationship("Organizations", backref="audit_testing_templates")
    control = db.relationship("AuditControls", backref="audit_testing_templates")


class AuditEvidence(db.Model):
    __tablename__ = "AuditEvidence"
    evidence_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    control_id = db.Column(db.BigInteger, db.ForeignKey("AuditControls.control_id"))
    engagement_id = db.Column(
        db.BigInteger, db.ForeignKey("AuditEngagements.engagement_id")
    )
    evidence_type = db.Column(db.String(100))
    file_path = db.Column(db.String(255))
    analysis_result = db.Column(db.Text)
    analyzed_by = db.Column(
        Enum("AI", "manual", name="evidence_analysis_type_enum"), 
        nullable=False
    )
    upload_date = db.Column(db.TIMESTAMP)
    uploaded_by = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    control = db.relationship("AuditControls", backref="audit_evidences")
    engagement = db.relationship("AuditEngagements", backref="audit_evidences")
    uploaded_user = db.relationship("Users", backref="audit_evidences")


class AuditReportTemplates(db.Model):
    __tablename__ = "AuditReportTemplates"
    template_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    name = db.Column(db.String(255), nullable=False)
    content_structure = db.Column(db.JSON)
    created_by = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    organization = db.relationship("Organizations", backref="audit_report_templates")
    created_user = db.relationship("Users", backref="audit_report_templates")


class AuditReports(db.Model):
    __tablename__ = "AuditReports"
    report_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    engagement_id = db.Column(
        db.BigInteger, db.ForeignKey("AuditEngagements.engagement_id")
    )
    template_id = db.Column(
        db.BigInteger, db.ForeignKey("AuditReportTemplates.template_id")
    )
    content = db.Column(db.JSON)
    status = db.Column(
        Enum("draft", "review", "final", name="audit_report_status_enum"), 
        default="draft"
    )
    generated_pdf_path = db.Column(db.String(255))
    created_by = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    organization = db.relationship("Organizations", backref="audit_reports")
    engagement = db.relationship("AuditEngagements", backref="audit_reports")
    template = db.relationship("AuditReportTemplates", backref="audit_reports")
    created_user = db.relationship("Users", backref="audit_reports")
