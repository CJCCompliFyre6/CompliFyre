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
