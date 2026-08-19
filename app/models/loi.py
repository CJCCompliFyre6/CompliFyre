# app/models/loi.py
"""
LOI Capture + Guideline Enablement subsystem models. Ported from the
sandbox prototype (proven correct there first) into the real
codebase's conventions -- db imported from app, matching every other
model file in this project.
"""
from app import db
from sqlalchemy.sql import func


class SignupInvites(db.Model):
    __tablename__ = "signup_invites"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    email = db.Column(db.String(255), nullable=False)
    entity_name = db.Column(db.String(255), nullable=True)
    contact_name = db.Column(db.String(255), nullable=True)
    designation = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    status = db.Column(db.String(50), nullable=False, default="INVITED")
    parent_invite_id = db.Column(db.BigInteger, db.ForeignKey("signup_invites.id"), nullable=True)
    created_by_org_id = db.Column(db.BigInteger, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    expires_at = db.Column(db.TIMESTAMP, nullable=False)


class InvitePreloadGuidelines(db.Model):
    __tablename__ = "invite_preload_guidelines"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    invite_id = db.Column(db.BigInteger, db.ForeignKey("signup_invites.id"), nullable=False)
    guideline_id = db.Column(db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False)


class LoiTemplates(db.Model):
    __tablename__ = "loi_templates"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    version_label = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=False)
    content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class LoiSignatures(db.Model):
    __tablename__ = "loi_signatures"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=False)
    template_version = db.Column(db.String(50), nullable=False)
    pdf_sha256 = db.Column(db.String(64), nullable=False)
    signer_name = db.Column(db.String(255), nullable=False)
    designation = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=True)
    authority_confirmed = db.Column(db.Boolean, nullable=False)
    signed_at_utc = db.Column(db.TIMESTAMP, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    # Deliberately append-only -- no update/delete route exists anywhere
    # for this model. This is the compliance-relevant record.


class UserJourneyEvents(db.Model):
    """
    Renamed from the original spec's 'loi_prompt_events' -- scope
    expanded per product decision to cover the full journey (invite
    sent, details submitted, MFA enrolled, every LOI prompt shown and
    the choice made, forwards, extension requests, feedback
    submissions), not just LOI-prompt appearances specifically.
    """
    __tablename__ = "user_journey_events"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=True)
    user_id = db.Column(db.BigInteger, nullable=True)
    invite_id = db.Column(db.BigInteger, nullable=True)
    event_type = db.Column(db.String(100), nullable=False)
    event_detail = db.Column(db.Text, nullable=True)
    occurred_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class LoiForwardRequests(db.Model):
    __tablename__ = "loi_forward_requests"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    original_invite_id = db.Column(db.BigInteger, db.ForeignKey("signup_invites.id"), nullable=False)
    forwarded_name = db.Column(db.String(255), nullable=False)
    forwarded_designation = db.Column(db.String(100), nullable=True)
    forwarded_email = db.Column(db.String(255), nullable=False)
    forwarded_phone = db.Column(db.String(20), nullable=True)
    relationship_note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class ExtensionRequests(db.Model):
    __tablename__ = "extension_requests"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    organization_id = db.Column(db.BigInteger, db.ForeignKey("Organizations.organization_id"), nullable=False)
    requested_by_user_id = db.Column(db.BigInteger, nullable=True)
    status = db.Column(db.String(50), nullable=False, default="PENDING")
    requested_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    resolved_at = db.Column(db.TIMESTAMP, nullable=True)


class EditableContent(db.Model):
    """
    Generic admin-editable text content store -- covers invite email,
    signed-LOI email, and warning emails. Deliberately generic (one
    row per content key) rather than one column per content type, so
    adding new editable copy later needs no migration.
    """
    __tablename__ = "editable_content"
    key = db.Column(db.String(100), primary_key=True)
    subject = db.Column(db.Text, nullable=True)
    body = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.TIMESTAMP, default=func.current_timestamp(), onupdate=func.current_timestamp())


class LoiTriggerConfig(db.Model):
    __tablename__ = "loi_trigger_config"
    trigger_key = db.Column(db.String(100), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)


class LoiGlobalConfig(db.Model):
    __tablename__ = "loi_global_config"
    id = db.Column(db.Integer, primary_key=True, default=1)
    loi_globally_enabled = db.Column(db.Boolean, nullable=False, default=True)


class GuidelineBundles(db.Model):
    __tablename__ = "guideline_bundles"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    name = db.Column(db.String(255), nullable=False)
    entity_type = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())


class GuidelineBundleItems(db.Model):
    __tablename__ = "guideline_bundle_items"
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    bundle_id = db.Column(db.BigInteger, db.ForeignKey("guideline_bundles.id"), nullable=False)
    guideline_id = db.Column(db.BigInteger, db.ForeignKey("guidelines.id"), nullable=False)
