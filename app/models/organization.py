from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import JSON
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import enum
from flask_login import UserMixin
from app.models.auditOrganization import project_departments


department_in_org = db.Table(
    "department_in_org",
    db.Column(
        "organization_id", db.BigInteger, db.ForeignKey("Organizations.organization_id")
    ),
    db.Column(
        "department_id",
        db.BigInteger,
        db.ForeignKey("OrganizationDepartments.department_id"),
    ),
)


class Organizations(db.Model):
    """
    Represents a central organization. Deleting an organization will cascade delete
    all related projects, addresses, contacts, info, licenses, structures, profiles, and branches.
    """

    __tablename__ = "Organizations"
    organization_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    legal_name = db.Column(db.String(255), nullable=False)
    registration_number = db.Column(db.String(100))
    tax_id = db.Column(db.String(50))
    industry_type = db.Column(JSON)
    organization_type = db.Column(JSON)
    regulatory_status = db.Column(db.String(100))
    incorporation_date = db.Column(db.Date)
    fiscal_year_end = db.Column(db.Date)
    constutution = db.Column(db.String(255))
    status = db.Column(
        Enum("active", "inactive", "suspended", name="org_status_enum"),
        default="active",
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    # +++ ADDED FOR LOI CAPTURE SUBSYSTEM +++
    entity_type = db.Column(db.String(100), nullable=True)
    cin = db.Column(db.String(50), nullable=True)
    registered_address = db.Column(db.Text, nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    loi_required = db.Column(db.Boolean, nullable=False, default=True)
    loi_status = db.Column(db.String(50), nullable=False, default="NOT_REQUIRED")
    loi_signed_at = db.Column(db.TIMESTAMP, nullable=True)
    loi_signature_id = db.Column(db.BigInteger, nullable=True)
    temp_access_expires_at = db.Column(db.TIMESTAMP, nullable=True)

    projects = db.relationship(
        "Projects", back_populates="client_rel", cascade="all, delete-orphan"
    )
    addresses = db.relationship(
        "OrganizationAddresses",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    contacts = db.relationship(
        "OrganizationContacts",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    info = db.relationship(
        "OrganizationInfo", back_populates="organization", cascade="all, delete-orphan"
    )
    licenses = db.relationship(
        "OrganizationLicenses",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    structures = db.relationship(
        "OrganizationStructure",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    compliance_profiles = db.relationship(
        "OrganizationComplianceProfiles",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
    branches = db.relationship(
        "OrganizationBranches",
        back_populates="organization",
        cascade="all, delete-orphan",
    )


class OrganizationAddresses(db.Model):
    """Stores a physical address for an Organization."""

    __tablename__ = "OrganizationAddresses"
    address_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=False
    )
    address_type = db.Column(db.String(100))
    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city = db.Column(db.String(100), nullable=False)
    state = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(100), nullable=False)
    postal_code = db.Column(db.String(20))
    is_primary = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    organization = db.relationship("Organizations", back_populates="addresses")


class OrganizationContacts(db.Model, UserMixin):
    """Stores contact information (people) for an Organization."""

    __tablename__ = "OrganizationContacts"
    contact_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=False
    )
    contact_type = db.Column(db.String(255))
    name = db.Column(db.String(255), nullable=False)
    designation = db.Column(db.String(100))
    email = db.Column(db.String(255))
    pancard = db.Column(db.String(20))
    mobile = db.Column(db.String(20))
    phone = db.Column(db.String(50))
    password_hash = db.Column(db.String(255))  # Add this field
    session_token = db.Column(db.String(255))
    # is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    organization = db.relationship("Organizations", back_populates="contacts")

    # Flask-Login required methods
    def get_id(self):
        """Return a string that uniquely identifies this contact"""
        return f"contact_{self.contact_id}" 

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        """Since we don't have is_active column, assume all contacts are active"""
        return True

    @property
    def is_anonymous(self):
        return False

    # Password methods
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def generate_temp_password(self):
        temp_password = secrets.token_urlsafe(8)
        self.set_password(temp_password)
        return temp_password


class OrganizationInfo(db.Model):
    """Stores descriptive and financial information about an Organization."""

    __tablename__ = "OrganizationInfo"
    contact_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=True
    )
    business_desc = db.Column(db.String(255), nullable=True)
    history = db.Column(db.String(255), nullable=True)
    key_events = db.Column(db.String(255), nullable=True)
    key_revenue = db.Column(db.String(255), nullable=True)
    key_markets_customers = db.Column(db.String(255), nullable=True)
    key_financials = db.Column(db.String(255), nullable=True)
    total_revenue_last_year = db.Column(db.String(255), nullable=True)
    net_profit_loss = db.Column(db.String(255), nullable=True)
    total_assets = db.Column(db.String(255), nullable=True)
    total_liabilities = db.Column(db.String(255), nullable=True)
    key_financial_challenges = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    no_of_branches_in_india = db.Column(db.Integer)
    no_of_branches_outside_india = db.Column(db.Integer)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    organization = db.relationship("Organizations", back_populates="info")


class OrganizationLicenses(db.Model):
    """Stores license information for an Organization."""

    __tablename__ = "OrganizationLicenses"
    license_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=False
    )
    license_type = db.Column(db.String(100), nullable=False)
    license_number = db.Column(db.String(100), nullable=False)
    regulator_license_id = db.Column(db.Integer, db.ForeignKey("regulator_licenses.id"), nullable=True)
    issuing_authority = db.Column(db.String(255), nullable=False)
    issue_date = db.Column(db.Date, nullable=False)
    expiry_date = db.Column(db.Date)
    status = db.Column(
        Enum("active", "expired", "revoked", "suspended", name="license_status_enum"),
        default="active",
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    organization = db.relationship("Organizations", back_populates="licenses")


class OrganizationStructure(db.Model):
    """Defines hierarchical reporting structures within an Organization."""

    __tablename__ = "OrganizationStructure"
    structure_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=False
    )
    position = db.Column(db.String(100), nullable=False)
    report_to = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    organization = db.relationship("Organizations", back_populates="structures")


class OrganizationComplianceProfiles(db.Model):
    """Stores compliance and audit information for an Organization."""

    __tablename__ = "OrganizationComplianceProfiles"
    profile_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=False
    )
    regulatory_body = db.Column(db.String(100))
    compliance_type = db.Column(db.String(100))
    compliance_status = db.Column(db.String(100))
    last_audit_date = db.Column(db.Date)
    next_audit_due = db.Column(db.Date)
    risk_rating = db.Column(db.String(100))
    business_process = db.Column(db.String(255))
    auditor_insights = db.Column(db.String(255))
    pending_litigations = db.Column(db.String(255))
    regulatory_filings = db.Column(db.String(255))
    indian_regulatory_compliance = db.Column(db.String(255))
    international_regulatory_compliance = db.Column(db.String(255))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    organization = db.relationship(
        "Organizations", back_populates="compliance_profiles"
    )


class OrganizationBranches(db.Model):
    """
    Represents a branch of an Organization. Deleting a head branch will delete its sub-branches.
    """

    __tablename__ = "OrganizationBranches"
    branch_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=False
    )
    branch_code = db.Column(db.String(50), nullable=False)
    branch_name = db.Column(db.String(255), nullable=False)
    branch_type = db.Column(db.String(100))
    address_id = db.Column(
        db.BigInteger, db.ForeignKey("OrganizationAddresses.address_id")
    )
    head_branch_id = db.Column(
        db.BigInteger, db.ForeignKey("OrganizationBranches.branch_id")
    )
    status = db.Column(
        Enum("active", "inactive", "closed", name="branch_status_enum"),
        default="active",
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    organization = db.relationship("Organizations", back_populates="branches")
    address = db.relationship("OrganizationAddresses", backref="branches")
    head_branch = db.relationship(
        "OrganizationBranches",
        remote_side=[branch_id],
        backref=db.backref("sub_branches", cascade="all, delete"),
    )


# Master Tables


class OrganizationDepartments(db.Model):
    """
    Represents a department. Deleting a department will cascade delete all
    associated compliance activities and projects.
    """

    __tablename__ = "OrganizationDepartments"
    department_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    department_name = db.Column(db.String(255), nullable=False)
    process_name = db.Column(db.String(255))
    sub_process = db.Column(db.String(255))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    comp_activity = db.relationship(
        "ComplianceActivities",
        back_populates="department",
        cascade="all, delete-orphan",
    )


    # Many-to-many relationship
    projects = db.relationship(
        "Projects",
        secondary=project_departments,
        back_populates="departments"  # Changed from projects_m2m to projects
    )
    
    # Old relationship for backward compatibility (if needed)
    old_projects = db.relationship(
        "Projects", 
        foreign_keys="Projects.primary_department_id", 
        backref="old_department_rel"
    )


class IndustryType(db.Model):
    "Represents an industry type"

    __tablename__ = "IndustryType"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    active = db.Column(db.Boolean, default=True)


class OrganizationType(db.Model):
    "Represents an organization type"

    __tablename__ = "OrganizationType"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    category = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    active = db.Column(db.Boolean, default=True)


class Constitution(db.Model):
    "Represents a constitution type"

    __tablename__ = "constitution"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    active = db.Column(db.Boolean, default=True)


class Country(db.Model):
    """Represents a country. Deleting a country will cascade delete all its states and cities."""

    __tablename__ = "Country"
    country_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    iso_code = db.Column(db.String(10), nullable=False, unique=True)
    phone_code = db.Column(db.String(10), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    states = db.relationship(
        "State", backref="country", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Country {self.name} ({self.iso_code})>"


class State(db.Model):
    """Represents a state within a country. Deleting a state will cascade delete all its cities."""

    __tablename__ = "State"
    state_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    state_name = db.Column(db.String(100), nullable=False)
    country_id = db.Column(
        db.BigInteger, db.ForeignKey("Country.country_id"), nullable=False
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    cities = db.relationship(
        "City", backref="state", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<State {self.state_name} (Country ID: {self.country_id})>"


class City(db.Model):
    """Represents a city within a state."""

    __tablename__ = "City"
    city_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    state_id = db.Column(db.BigInteger, db.ForeignKey("State.state_id"), nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    def __repr__(self):
        return f"<City {self.name} (State ID: {self.state_id})>"
