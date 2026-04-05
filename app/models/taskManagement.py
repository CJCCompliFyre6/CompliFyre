# app/models/taskManagement.py
from app import db
from sqlalchemy import Enum
from sqlalchemy.sql import func


class Tasks(db.Model):
    __tablename__ = "Tasks"
    task_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    document_id = db.Column(
        db.BigInteger, db.ForeignKey("RegulatoryDocuments.document_id")
    )
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(
        Enum("pending", "in_progress", "completed", "canceled", name="task_status_enum"), 
        default="pending"
    )
    priority = db.Column(
        Enum("low", "medium", "high", "critical", name="task_priority_enum"), 
        default="medium"
    )
    category_id = db.Column(
        db.BigInteger, db.ForeignKey("DocumentCategories.category_id")
    )
    owner_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    approver_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    due_date = db.Column(db.Date)
    completed_date = db.Column(db.Date)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    # Relationships
    organization = db.relationship("Organizations", backref="tasks")
    document = db.relationship("RegulatoryDocuments", backref="tasks")
    category = db.relationship("DocumentCategories", backref="tasks")
    owner = db.relationship("Users", foreign_keys=[owner_id], backref="owned_tasks")
    approver = db.relationship(
        "Users", foreign_keys=[approver_id], backref="approved_tasks"
    )


class TaskComments(db.Model):
    __tablename__ = "TaskComments"
    comment_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    task_id = db.Column(db.BigInteger, db.ForeignKey("Tasks.task_id"))
    user_id = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    task = db.relationship("Tasks", backref="comments")
    user = db.relationship("Users", backref="task_comments")


class TaskEscalations(db.Model):
    __tablename__ = "TaskEscalations"
    escalation_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    task_id = db.Column(db.BigInteger, db.ForeignKey("Tasks.task_id"))
    escalation_level = db.Column(db.Integer, nullable=False)
    escalated_to = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    escalated_by = db.Column(db.BigInteger, db.ForeignKey("Users.id"))
    reason = db.Column(db.Text)
    resolved_at = db.Column(db.TIMESTAMP)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    task = db.relationship("Tasks", backref="escalations")
    escalated_user = db.relationship(
        "Users", foreign_keys=[escalated_to], backref="escalated_tasks"
    )
    escalated_by_user = db.relationship(
        "Users", foreign_keys=[escalated_by], backref="escalated_by_tasks"
    )
