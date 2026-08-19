# app/models/re.py
from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func


class RegulatoryBodies(db.Model):
    __tablename__ = "RegulatoryBodies"
    body_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    website_url = db.Column(db.String(255))
    geography = db.Column(db.String(255))
    industry = db.Column(db.String(255))
    governed_institutions = db.Column(db.Text)
    last_check_status = db.Column(db.String(50), nullable=False, default="NEVER_CHECKED")
    last_checked_at = db.Column(db.TIMESTAMP)
    last_check_notes = db.Column(db.Text)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class DocumentCategories(db.Model):
    __tablename__ = "DocumentCategories"
    category_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    parent_category_id = db.Column(
        db.BigInteger, db.ForeignKey("DocumentCategories.category_id")
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationship
    parent_category = db.relationship(
        "DocumentCategories", remote_side=[category_id], backref="sub_categories"
    )


class RegulatoryDocuments(db.Model):
    __tablename__ = "RegulatoryDocuments"
    document_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    title = db.Column(db.String(255), nullable=False)
    body_id = db.Column(db.BigInteger, db.ForeignKey("RegulatoryBodies.body_id"))
    category_id = db.Column(
        db.BigInteger, db.ForeignKey("DocumentCategories.category_id")
    )
    source_url = db.Column(db.String(255))
    document_path = db.Column(db.String(255))
    file_hash = db.Column(db.String(64))
    guideline_id = db.Column(db.BigInteger, db.ForeignKey("guidelines.id", ondelete="SET NULL"))
    pipeline_status = db.Column(db.String(50), nullable=False, default="PENDING_DOWNLOAD")
    published_date = db.Column(db.Date)
    content = db.Column(db.Text)
    status = db.Column(
        Enum("active", "archived", "superseded", name="doc_status_enum"), 
        default="active"
    )
    remetadata = db.Column(db.JSON)
    vector_embedding = db.Column(db.LargeBinary)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationships
    body = db.relationship("RegulatoryBodies", backref="documents")
    category = db.relationship("DocumentCategories", backref="documents")


class RegulationDependencies(db.Model):
    __tablename__ = "RegulationDependencies"
    dependency_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    source_doc_id = db.Column(
        db.BigInteger, db.ForeignKey("RegulatoryDocuments.document_id")
    )
    target_doc_id = db.Column(
        db.BigInteger, db.ForeignKey("RegulatoryDocuments.document_id")
    )
    dependency_type = db.Column(
        Enum("overlap", "reference", "supersedes", "complements", name="dependency_type_enum"), 
        nullable=False
    )
    description = db.Column(db.Text)
    severity = db.Column(
        Enum("LOW", "MEDIUM", "HIGH", name="dependency_severity_enum"), 
        nullable=False
    )
    identified_by = db.Column(
        Enum("AI", "manual", name="identified_by_enum"), 
        nullable=False
    )
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    source_doc = db.relationship(
        "RegulatoryDocuments",
        foreign_keys=[source_doc_id],
        backref="source_dependencies",
    )
    target_doc = db.relationship(
        "RegulatoryDocuments",
        foreign_keys=[target_doc_id],
        backref="target_dependencies",
    )


class RegulatorLicenses(db.Model):
    """
    Master list of all BFSI regulators worldwide and the license types they issue.
    Used to tag guidelines and clauses with structured applicability codes.
    license_code is the canonical identifier: RBI_NBFC_ICC, SEBI_LE_EQ, IRDAI_LIFE etc.
    """
    __tablename__ = "regulator_licenses"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    regulator_name = db.Column(db.String(200), nullable=False)
    regulator_country = db.Column(db.String(100), nullable=False)
    license_name = db.Column(db.String(200), nullable=False)
    license_code = db.Column(db.String(50), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)

    # Added 2026-08-12 after validating this table's design against 13 real
    # jurisdictions (India/US/EU/UK/UAE/SEA/others). Two founding principles
    # confirmed to hold throughout: one row per independent classification
    # dimension (never merge e.g. RBI's type + scale-tier into one value),
    # and an org can hold multiple simultaneous licenses -- no forced single
    # hierarchy. All four fields below are deliberately nullable; most
    # regulators in most markets need none of them populated.
    classification_dimension = db.Column(db.String(50), nullable=True)
    parent_license_id = db.Column(db.Integer, db.ForeignKey("regulator_licenses.id"), nullable=True)
    effective_from = db.Column(db.Date, nullable=True)
    effective_to = db.Column(db.Date, nullable=True)
    # No default (stays NULL, not False) for license types outside the EEA --
    # False would wrongly imply "considered and does not passport"; NULL
    # honestly means "this concept doesn't apply here at all."
    is_eea_passportable = db.Column(db.Boolean, nullable=True)

    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'regulator_name': self.regulator_name,
            'regulator_country': self.regulator_country,
            'license_name': self.license_name,
            'license_code': self.license_code,
            'is_active': self.is_active,
        }


class RegulatoryDocumentStatusHistory(db.Model):
    """
    Every pipeline_status transition on a RegulatoryDocuments row gets its
    own timestamped entry here -- Ankita's explicit requirement for a real
    timestamp per status change, not just a single 'last updated' field.
    """
    __tablename__ = "regulatory_document_status_history"

    id = db.Column(db.BigInteger, primary_key=True)
    document_id = db.Column(
        db.BigInteger, db.ForeignKey("RegulatoryDocuments.document_id", ondelete="CASCADE"), nullable=False
    )
    status = db.Column(db.String(50), nullable=False)
    occurred_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    notes = db.Column(db.Text)

    document = db.relationship("RegulatoryDocuments", backref="status_history")


class DocumentPipelineStatus:
    """
    Status constants for RegulatoryDocuments.pipeline_status, matching the
    REAL pipeline stages observed live during testing (Stage 1A structure
    map, Stage 1B/2 extraction, Stage 4 Split = "decomposition" in
    Ankita's terminology). PAUSED states are placeholders only -- no pause
    capability exists yet in the pipeline (see Build Sequence item #100,
    not started). These values exist in the data model now so the UI/table
    can be built, but nothing currently sets them to a PAUSED value.
    """
    PENDING_DOWNLOAD = "PENDING_DOWNLOAD"
    IMPORTED = "IMPORTED"
    STRUCTURE_MAP_CREATED = "STRUCTURE_MAP_CREATED"
    EXTRACTION_IN_PROGRESS = "EXTRACTION_IN_PROGRESS"
    EXTRACTION_PAUSED = "EXTRACTION_PAUSED"
    EXTRACTION_COMPLETE = "EXTRACTION_COMPLETE"
    DECOMPOSITION_IN_PROGRESS = "DECOMPOSITION_IN_PROGRESS"
    DECOMPOSITION_PAUSED = "DECOMPOSITION_PAUSED"
    DECOMPOSITION_COMPLETE = "DECOMPOSITION_COMPLETE"

    ALL = [
        PENDING_DOWNLOAD, IMPORTED, STRUCTURE_MAP_CREATED,
        EXTRACTION_IN_PROGRESS, EXTRACTION_PAUSED, EXTRACTION_COMPLETE,
        DECOMPOSITION_IN_PROGRESS, DECOMPOSITION_PAUSED, DECOMPOSITION_COMPLETE,
    ]

    PLACEHOLDER_ONLY = [EXTRACTION_PAUSED, DECOMPOSITION_PAUSED]


def set_document_pipeline_status(document, new_status, notes=None):
    """
    The ONLY sanctioned way to change a RegulatoryDocuments row's
    pipeline_status. Updates the column AND inserts a matching
    status_history row in the same call, so a transition can never be
    logged without its timestamp. Does not commit -- caller controls the
    transaction, consistent with the rest of this codebase.
    """
    if new_status not in DocumentPipelineStatus.ALL:
        raise ValueError(f"Unknown pipeline status: {new_status!r}")
    document.pipeline_status = new_status
    history_row = RegulatoryDocumentStatusHistory(
        document_id=document.document_id,
        status=new_status,
        notes=notes,
    )
    db.session.add(history_row)
    return history_row
