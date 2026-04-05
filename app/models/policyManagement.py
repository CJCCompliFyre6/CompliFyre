# app/models/policyManagement.py
from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func


class Policies(db.Model):
    __tablename__ = "Policies"
    policy_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    task_id = db.Column(db.BigInteger, db.ForeignKey("Tasks.task_id"))
    title = db.Column(db.String(255), nullable=False)
    category_id = db.Column(
        db.BigInteger, db.ForeignKey("DocumentCategories.category_id")
    )
    content = db.Column(db.Text)
    version = db.Column(db.Integer, nullable=False, default=1)
    status = db.Column(
        Enum("draft", "active", "archived", name="policy_status_enum"), 
        default="draft"
    )
    effective_date = db.Column(db.Date)
    expiry_date = db.Column(db.Date)
    previous_version_id = db.Column(db.BigInteger, db.ForeignKey("Policies.policy_id"))
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationships
    organization = db.relationship("Organizations", backref="policies")
    task = db.relationship("Tasks", backref="policies")
    category = db.relationship("DocumentCategories", backref="policies")
    previous_version = db.relationship(
        "Policies", remote_side=[policy_id], backref="next_versions"
    )


class PolicyApprovals(db.Model):
    __tablename__ = "PolicyApprovals"
    approval_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    policy_id = db.Column(db.BigInteger, db.ForeignKey("Policies.policy_id"))
    user_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    status = db.Column(
        Enum("pending", "approved", "rejected", name="policy_approval_status_enum"), 
        default="pending"
    )
    comments = db.Column(db.Text)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationships
    policy = db.relationship("Policies", backref="approvals")
    user = db.relationship("Users", backref="policy_approvals")
