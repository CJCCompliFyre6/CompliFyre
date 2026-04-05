# app/models/dashboard.py
from app import db
from sqlalchemy.sql import func


class Dashboards(db.Model):
    __tablename__ = "Dashboards"
    dashboard_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(
        db.BigInteger, db.ForeignKey("Organizations.organization_id")
    )
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    user_type_id = db.Column(db.BigInteger, db.ForeignKey("UserTypes.type_id"))
    layout_config = db.Column(db.JSON)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    organization = db.relationship("Organizations", backref="dashboards")
    user_type = db.relationship("UserTypes", backref="dashboards")


class DashboardWidgets(db.Model):
    __tablename__ = "DashboardWidgets"
    widget_id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    dashboard_id = db.Column(db.BigInteger, db.ForeignKey("Dashboards.dashboard_id"))
    widget_type = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(255))
    config = db.Column(db.JSON)
    position_config = db.Column(db.JSON)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())

    # Relationships
    dashboard = db.relationship("Dashboards", backref="dashboard_widgets")
