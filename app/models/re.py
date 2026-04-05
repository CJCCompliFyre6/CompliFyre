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
