from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func


auditor_selected_guidelines = db.Table(
    "auditor_selected_guidelines",
    db.Column("audit_id", db.BigInteger, db.ForeignKey("AuditOrganization.id")),
    db.Column("guideline_id", db.BigInteger, db.ForeignKey("guidelines.id")),
)

auditor_client = db.Table(
    "auditor_client",
    db.Column("audit_id", db.BigInteger, db.ForeignKey("AuditOrganization.id")),
    db.Column(
        "client_id", db.BigInteger, db.ForeignKey("Organizations.organization_id")
    ),
)

project_location = db.Table(
    "project_location",
    db.Column("project_id", db.BigInteger, db.ForeignKey("projects.id")),
    db.Column(
        "ord_location_id",
        db.BigInteger,
        db.ForeignKey("OrganizationAddresses.address_id"),
    ),
)


class AuditOrganization(db.Model):
    """
    Represents an auditing firm. Deleting an AuditOrganization will cascade delete all its
    related addresses, focus areas, hierarchy, contacts, certifications, users, and projects.
    """

    __tablename__ = "AuditOrganization"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    firm_name = db.Column(db.String(255), nullable=False)
    firm_registration_no = db.Column(db.String(255), nullable=False)
    firm_description = db.Column(db.Text, nullable=False)
    number_of_employees = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    addresses = db.relationship(
        "AuditOrgAddress", back_populates="audit_org_rel", cascade="all, delete-orphan"
    )
    focus_areas = db.relationship(
        "OrgAuditFocusAreas",
        back_populates="audit_org_rel",
        cascade="all, delete-orphan",
    )
    hierarchy = db.relationship(
        "AuditOrgHierarchy",
        back_populates="audit_org_rel",
        cascade="all, delete-orphan",
    )
    contact_persons = db.relationship(
        "AuditOrgContactPerson",
        back_populates="audit_org_rel",
        cascade="all, delete-orphan",
    )
    audit_certifications = db.relationship(
        "OrgAuditCertifications",
        back_populates="audit_org_rel",
        cascade="all, delete-orphan",
    )
    user = db.relationship(
        "Users", back_populates="auditor_profile", cascade="all, delete-orphan"
    )
    projects = db.relationship(
        "Projects", back_populates="audit_org_rel", cascade="all, delete-orphan"
    )
    selected_guidelines = db.relationship(
        "Guidelines", secondary=auditor_selected_guidelines, back_populates="audits"
    )


class AuditOrgAddress(db.Model):
    """Stores a physical address for an AuditOrganization."""

    __tablename__ = "AuditOrgAddress"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    address = db.Column(db.Text, nullable=False)
    city = db.Column(db.String(255), nullable=False)
    state = db.Column(db.String(255), nullable=False)
    country = db.Column(db.String(255), nullable=False)
    head_office = db.Column(db.Boolean, default=False)
    audit_org_id = db.Column(db.BigInteger, db.ForeignKey("AuditOrganization.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    audit_org_rel = db.relationship("AuditOrganization", back_populates="addresses")


class OrgAuditCertifications(db.Model):
    """Stores a certification held by an AuditOrganization."""

    __tablename__ = "OrgAuditCertifications"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    certifications = db.Column(db.String(255), nullable=False)
    audit_org_id = db.Column(db.BigInteger, db.ForeignKey("AuditOrganization.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    audit_org_rel = db.relationship(
        "AuditOrganization", back_populates="audit_certifications"
    )


class OrgAuditFocusAreas(db.Model):
    """Stores a specific focus area (e.g., 'IT Audit') for an AuditOrganization."""

    __tablename__ = "OrgAuditFocusAreas"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    focus_area = db.Column(db.String(255), nullable=False)
    audit_org_id = db.Column(db.BigInteger, db.ForeignKey("AuditOrganization.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    audit_org_rel = db.relationship("AuditOrganization", back_populates="focus_areas")


class AuditOrgHierarchy(db.Model):
    """Defines a hierarchical position within an AuditOrganization."""

    __tablename__ = "AuditOrgHierarchy"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    post = db.Column(db.String(255), nullable=False)
    reports_to = db.Column(db.String(255), nullable=False)
    audit_org_id = db.Column(db.BigInteger, db.ForeignKey("AuditOrganization.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    audit_org_rel = db.relationship("AuditOrganization", back_populates="hierarchy")


class AuditOrgContactPerson(db.Model):
    """Stores contact details for a person at an AuditOrganization."""

    __tablename__ = "AuditOrgContactPerson"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(255), nullable=False)
    audit_org_id = db.Column(db.BigInteger, db.ForeignKey("AuditOrganization.id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    audit_org_rel = db.relationship(
        "AuditOrganization", back_populates="contact_persons"
    )


# Add this after your models definition (in your models.py file)
project_departments = db.Table(
    'project_departments',
    db.Column('project_id', db.BigInteger, db.ForeignKey('projects.id'), primary_key=True),
    db.Column('department_id', db.BigInteger, db.ForeignKey('OrganizationDepartments.department_id'), primary_key=True)
)

class Projects(db.Model):
    """
    Represents a single audit project. Deleting a project will now cascade delete its
    associated ConsolidatedEvidence.
    """

    __tablename__ = "projects"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    project_name = db.Column(db.String(255), nullable=False)
    project_description = db.Column(db.Text, nullable=False)
    auditing_firm = db.Column(db.BigInteger, db.ForeignKey("AuditOrganization.id"))
    client = db.Column(db.BigInteger, db.ForeignKey("Organizations.organization_id"))
    # department = db.Column(
    #     db.BigInteger, db.ForeignKey("OrganizationDepartments.department_id")
    # )
    guidelines = db.Column(db.BigInteger, db.ForeignKey("guidelines.id"))
    activity = db.Column(db.BigInteger, db.ForeignKey("compliance_activities.id"))
    project_start_date = db.Column(db.Date)
    project_end_date = db.Column(db.Date)
    assesment_start_date = db.Column(db.Date)
    assesment_end_date = db.Column(db.Date)
    project_complete_status = db.Column(db.Boolean)

    # Keep the primary department relationship if needed
    primary_department_id = db.Column(
        db.BigInteger, db.ForeignKey("OrganizationDepartments.department_id")
    )
    
    # Many-to-many relationship for departments
    departments = db.relationship(
        "OrganizationDepartments",
        secondary=project_departments,
        back_populates="projects",  # Changed from projects_m2m to projects
        
    )
    
    # Primary department relationship
    primary_department = db.relationship(
        "OrganizationDepartments", 
        foreign_keys=[primary_department_id],
        backref="primary_projects"
    )
    
    
    audit_org_rel = db.relationship("AuditOrganization", back_populates="projects")
    client_rel = db.relationship("Organizations", back_populates="projects")
    guidelines_rel = db.relationship("Guidelines", back_populates="projects")
    activity_rel = db.relationship("ComplianceActivities", back_populates="projects")
    documentation = db.relationship(
        "Documentation",
        backref="project",
        lazy=True,
        foreign_keys="Documentation.project_id",
    )
    project_guidelines = db.relationship(
        "ProjectGuideline", back_populates="project", cascade="all, delete-orphan"
    )

    # Add these new fields
    report_generated = db.Column(db.Boolean, default=False)
    report_generated_at = db.Column(db.DateTime)
    report_generated_by = db.Column(db.BigInteger, db.ForeignKey("Users.id"))  
    free_report_used = db.Column(db.Boolean, default=False)

    # Relationship
    report_generator = db.relationship("Users", foreign_keys=[report_generated_by])


class ConsolidatedEvidence(db.Model):
    """Stores a JSON blob of consolidated evidence for a single Project."""

    __tablename__ = "consolidated_evidence"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    project_id = db.Column(db.String(255))
    consolidate_evidence = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class ComplifyreConsolidatedEvidence(db.Model):
    """Stores a JSON blob of consolidated evidence for a single Guideline."""

    __tablename__ = "complifyre_consolidated_evidence"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    guideline_id = db.Column(
        db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False
    )
    consolidate_evidence = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    guideline = db.relationship("Guidelines", backref="consolidated_evidence")


class Documentation(db.Model):
    __tablename__ = "Documentation"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    auditor_profile_id = db.Column(
        db.BigInteger, db.ForeignKey("AuditOrganization.id"), nullable=False
    )
    created_by = db.Column(db.BigInteger, db.ForeignKey("Users.id"), nullable=False)
    project_id = db.Column(
        db.BigInteger, db.ForeignKey("projects.id"), nullable=False
    )  # Foreign key to Projects table

    # Document Control Fields
    document_preparation = db.Column(db.Text)
    document_title = db.Column(db.String(500), nullable=False)
    document_id = db.Column(db.String(100), nullable=False, unique=False)
    document_version = db.Column(db.String(50), nullable=False)
    prepared_by = db.Column(db.String(255))
    reviewed_by = db.Column(db.String(255))
    approved_by = db.Column(db.String(255))
    released_by = db.Column(db.String(255))
    release_date = db.Column(db.Date)

    # Rich Text Fields
    introduction = db.Column(db.Text)
    engagement_scope = db.Column(db.Text)
    activities_timelines = db.Column(db.Text)
    methodology_criteria = db.Column(db.Text)

    # NEW: Executive Summary Field
    executive_summary = db.Column(db.Text)  # Add this field

    locations_data = db.Column(db.JSON, nullable=True)  # Store locations as JSON
    departments_data = db.Column(db.JSON, nullable=True)  # Store departments as JSON
    executive_summary_narrative = db.Column(db.Text)  # Store just the narrative text


    # status = db.Column(db.Enum('draft', 'submitted', name='doc_status_enum'), default='draft')
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationships
    change_history = db.relationship(
        "DocumentChangeHistory", backref="documentation", cascade="all, delete-orphan"
    )
    distribution_list = db.relationship(
        "DocumentDistribution", backref="documentation", cascade="all, delete-orphan"
    )
    audit_team = db.relationship(
        "AuditTeam", backref="documentation", cascade="all, delete-orphan"
    )
    tools_used = db.relationship(
        "AuditTools", backref="documentation", cascade="all, delete-orphan"
    )


class DocumentChangeHistory(db.Model):
    __tablename__ = "DocumentChangeHistory"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    documentation_id = db.Column(
        db.BigInteger, db.ForeignKey("Documentation.id"), nullable=False
    )
    version = db.Column(db.String(50), nullable=False)
    change_date = db.Column(db.Date, nullable=False)
    remarks = db.Column(db.Text)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class DocumentDistribution(db.Model):
    __tablename__ = "DocumentDistribution"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    documentation_id = db.Column(
        db.BigInteger, db.ForeignKey("Documentation.id"), nullable=False
    )
    name = db.Column(db.String(255), nullable=False)
    organization = db.Column(db.String(255))
    designation = db.Column(db.String(255))
    email = db.Column(db.String(255))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class AuditTeam(db.Model):
    __tablename__ = "AuditTeam"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    documentation_id = db.Column(
        db.BigInteger, db.ForeignKey("Documentation.id"), nullable=False
    )
    name = db.Column(db.String(255), nullable=False)
    designation = db.Column(db.String(255))
    email = db.Column(db.String(255))
    professional_qualifications = db.Column(db.Text)
    listed_in_snapshot = db.Column(
        db.Enum("Yes", "No", name="snapshot_enum"), default="No"
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class AuditTools(db.Model):
    __tablename__ = "AuditTools"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    documentation_id = db.Column(
        db.BigInteger, db.ForeignKey("Documentation.id"), nullable=False
    )
    tool_name = db.Column(db.String(500), nullable=False)
    version_control = db.Column(db.String(255))
    license_type = db.Column(
        db.Enum("Open", "Licensed", name="license_enum"), default="Open"
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
