# app/models/attachment.py
from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func


class Attachments(db.Model):
    __tablename__ = "Attachments"
    attachment_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    entity_type = db.Column(
        Enum("task", "policy", name="attachment_entity_type_enum"), 
        nullable=False
    )
    entity_id = db.Column(db.BigInteger, nullable=False)
    file_name = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(100))
    file_path = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.BigInteger)
    uploaded_by = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    description = db.Column(db.Text)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    organization = db.relationship("Organizations", backref="attachments")
    user = db.relationship("Users", backref="attachments")
