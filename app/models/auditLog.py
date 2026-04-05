# app/models/auditLog.py
from app import db
from sqlalchemy.sql import func


class AuditLogs(db.Model):
    __tablename__ = "AuditLogs"
    log_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    user_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.BigInteger, nullable=False)
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    organization = db.relationship("Organizations", backref="audit_logs")
    user = db.relationship("Users", backref="audit_logs")
