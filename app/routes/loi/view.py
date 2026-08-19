# app/routes/loi/view.py
"""
LOI Capture + Guideline Enablement subsystem routes.
First porting pass: Group 4 (admin invite creation/list) and Group 5
(activation flow), re-wired to CompliFyre's REAL existing
authentication mechanisms rather than the sandbox's standalone
versions:
  - Flask-Login (login_user, current_user, login_required) instead of
    a custom session dict
  - The existing tfa_secret/tfa_enabled columns and pyotp+qrcode
    enrollment pattern already used in app/routes/main.py, instead of
    a separate MFA implementation
  - The existing Users.password_hash column (already present, used by
    the current login system) instead of a new column

Groups 6-12 (LOI signing, forward, expiry/extension, admin dashboard,
settings, bundles) follow in a subsequent porting pass.
"""
import hashlib
import uuid
import io
import base64
import secrets
import os
from datetime import datetime, timezone, timedelta

import pyotp
import qrcode
from flask import (
    Blueprint, request, render_template, redirect, url_for, flash,
    current_app, session,
)
from flask_login import login_required, current_user, login_user
from werkzeug.security import generate_password_hash
from app.utils.permission_handler import role_required

from app import db
from app.models.loi import EditableContent
from app.utils.email_service import send_invite_email, render_invite_email_content, DEFAULT_INVITE_SUBJECT, DEFAULT_INVITE_BODY
from app.models import (
    SignupInvites, InvitePreloadGuidelines, Guidelines, Organizations,
    Users, UserJourneyEvents, LoiTemplates, LoiSignatures, LoiForwardRequests,
    AuditOrganization,
)

loi_bp = Blueprint(
    "loi",
    __name__,
    template_folder="../../templates/dashboards/loi",
)


ENTITY_TYPES = [
    "Scheduled Commercial Bank", "NBFC (Deposit-Taking)", "NBFC (Non-Deposit-Taking)",
    "Housing Finance Company", "Small Finance Bank", "Payments Bank",
    "Cooperative Bank", "Primary Dealer", "Asset Management Company", "Other",
]


def generate_invite_token():
    """
    32 random bytes, hex-encoded. Only the SHA-256 hash is ever stored
    in signup_invites.token_hash -- the raw token itself is never
    persisted, only ever handed to the invitee via the email link.
    """
    raw_token = secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return raw_token, token_hash


# ============================================================
# Group 4 -- Admin invite creation and list
# ============================================================

@loi_bp.route("/admin/invite-new-user")
@login_required
def invite_new_user_form():
    catalogue_guidelines = Guidelines.query.filter_by(catalogue_enabled=True).all()
    return render_template(
        "dashboards/loi/invite_new_user.html",
        catalogue_guidelines=catalogue_guidelines,
    )


@loi_bp.route("/admin/create-invite", methods=["POST"])
@login_required
def create_invite():
    email = request.form.get("email")
    entity_name = request.form.get("entity_name")
    contact_name = request.form.get("contact_name")
    designation = request.form.get("designation")
    phone = request.form.get("phone")
    guideline_ids = request.form.getlist("guideline_ids", type=int)

    raw_token, token_hash = generate_invite_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=14)

    invite = SignupInvites(
        email=email, entity_name=entity_name, contact_name=contact_name,
        designation=designation, phone=phone, token_hash=token_hash,
        status="INVITED", expires_at=expires_at,
    )
    db.session.add(invite)
    db.session.flush()

    for gid in guideline_ids:
        db.session.add(InvitePreloadGuidelines(invite_id=invite.id, guideline_id=gid))

    db.session.add(UserJourneyEvents(
        invite_id=invite.id, event_type="invite_sent",
        event_detail=f"Sent to {email} with {len(guideline_ids)} preloaded guideline(s)"
    ))
    db.session.commit()

    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)

    subject, html_body = render_invite_email_content(
        contact_name=contact_name or "there",
        entity_name=entity_name or "your organization",
        guideline_count=len(guideline_ids),
        activation_link=activation_link,
        expiry_date=expires_at.strftime("%d %B %Y"),
        email=email,
    )
    email_sent = send_invite_email(email, subject, html_body)

    if email_sent:
        flash(f"Invite sent to {email}.", "success")
    else:
        flash(
            f"Invite created for {email}, but the email failed to send. "
            f"Activation link (share manually): {activation_link}", "warning"
        )

    return redirect(url_for("loi.invite_list"))


@loi_bp.route("/admin/invites")
@login_required
def invite_list():
    invites = SignupInvites.query.order_by(SignupInvites.created_at.desc()).all()
    return render_template("dashboards/loi/invite_list.html", invites=invites)
@loi_bp.route("/admin/invites/<int:invite_id>/resend", methods=["POST"])
@login_required
def resend_invite_link(invite_id):
    """
    Generates a fresh token for an existing invite (old links for it
    stop working, same pattern as a password-reset flow -- the raw
    token is never stored, so there's no way to retroactively display
    a link that was already issued). Also refreshes the 14-day expiry
    and resets status to INVITED, since regenerating a link implies
    restarting the activation attempt.
    """
    invite = SignupInvites.query.get_or_404(invite_id)
    raw_token, token_hash = generate_invite_token()
    invite.token_hash = token_hash
    invite.expires_at = datetime.now(timezone.utc) + timedelta(days=14)
    invite.status = "INVITED"
    db.session.add(UserJourneyEvents(
        invite_id=invite.id, user_id=current_user.id,
        event_type="link_resent", event_detail=f"Link regenerated for {invite.email}"
    ))
    db.session.commit()
    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)

    # Fix 2026-08-07: this predates #257 and was never wired to actually
    # send an email -- it just flashed the link to the admin, same as
    # every other invite path used to. "Resend Link" looked like it
    # notified the person but never contacted them at all, which is why
    # test resends to real Gmail addresses never arrived: nothing was
    # ever sent, not a deliverability problem.
    guideline_count = InvitePreloadGuidelines.query.filter_by(invite_id=invite.id).count()
    subject, html_body = render_invite_email_content(
        contact_name=invite.contact_name or "there",
        entity_name=invite.entity_name or "your organization",
        guideline_count=guideline_count,
        activation_link=activation_link,
        expiry_date=invite.expires_at.strftime("%d %B %Y"),
        email=invite.email,
    )
    email_sent = send_invite_email(invite.email, subject, html_body)

    if email_sent:
        flash(f"New activation link sent to {invite.email}.", "success")
    else:
        flash(
            f"Link regenerated for {invite.email}, but the email failed to send. "
            f"Activation link (share manually): {activation_link}", "warning"
        )

    return redirect(url_for("loi.invite_list"))


# ============================================================
# Group 5 -- Activation flow
# ============================================================

def validate_invite_token(raw_token):
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    invite = SignupInvites.query.filter_by(token_hash=token_hash).first()
    if not invite:
        return None, "invalid_token"
    if invite.status not in ("INVITED", "DETAILS_SUBMITTED"):
        return None, "invite_already_used_or_revoked"
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None, "invite_expired"
    return invite, "ok"


@loi_bp.route("/activate/<raw_token>")
def activation_form(raw_token):
    invite, status = validate_invite_token(raw_token)
    if not invite:
        flash(f"This invite link is no longer valid ({status}).", "error")
        return redirect(url_for("main.login"))

    # Fix 2026-08-06: a forwarded invite to a genuinely new colleague
    # (no existing account) still showed blank, required org-detail
    # fields (Entity Type, CIN, address, City, State) -- but that org
    # already exists (created when the ORIGINAL invitee activated).
    # These fields were never actually used for a forward (the
    # activation_submit() join-branch never reads them), so the
    # invitee was being forced to invent throwaway data just to get
    # past HTML required= on fields that were silently discarded.
    # Look up the real org the same way activation_submit()'s join
    # branch does, and show its real values instead, locked.
    parent_org = None
    if invite.parent_invite_id:
        parent_user = Users.query.filter_by(invite_id=invite.parent_invite_id).first()
        if parent_user and parent_user.organization_id:
            parent_org = Organizations.query.get(parent_user.organization_id)

    return render_template(
        "dashboards/loi/activation_form.html",
        invite=invite, entity_types=ENTITY_TYPES, parent_org=parent_org,
    )


def _resume_existing_account_for_forward(invite, existing_user):
    """
    Scenario 2 (item #253): a colleague was forwarded the LOI (Group 7)
    and already has a Users account. Per Ankita's direction 2026-08-04:
    auto-resume, no admin approval gate -- the point of forwarding is
    getting the LOI signed, so normal trial gating shouldn't block it.

    DEFAULT ASSUMED, NOT YET CONFIRMED: "resume" means extending the
    SAME existing account/org the person already has, rather than
    re-pointing them onto the forwarding org. Safer, non-destructive
    interpretation -- but the alternative is still an open question,
    see Pending -- Ankita.
    """
    existing_org = Organizations.query.get(existing_user.organization_id) if existing_user.organization_id else None
    if existing_org and existing_org.loi_status != "SIGNED":
        existing_org.temp_access_expires_at = datetime.now(timezone.utc) + timedelta(days=14)
        existing_org.loi_required = True
        db.session.add(UserJourneyEvents(
            organization_id=existing_org.organization_id, invite_id=invite.id,
            user_id=existing_user.id, event_type="trial_resumed_via_forward",
            event_detail=f"Access resumed 14 days via forward from invite {invite.parent_invite_id}"
        ))
    invite.status = "RESOLVED_EXISTING_ACCOUNT"
    db.session.commit()
    flash(
        f"You already have a CompliFyre account ({existing_user.email}). "
        f"Your trial access has been resumed for 14 more days -- please log in with your existing password.",
        "success"
    )
    return redirect(url_for("main.login"))
@loi_bp.route("/admin/reauthorize/<int:invite_id>")
@login_required
def admin_reauthorize_decision(invite_id):
    invite = SignupInvites.query.get_or_404(invite_id)
    existing_user = Users.query.filter_by(email=invite.email).first()
    if not existing_user:
        flash("No existing account found for this invite -- nothing to decide.", "error")
        return redirect(url_for("loi.invite_list"))
    existing_org = Organizations.query.get(existing_user.organization_id) if existing_user.organization_id else None
    recent_events = (
        UserJourneyEvents.query
        .filter_by(user_id=existing_user.id)
        .order_by(UserJourneyEvents.occurred_at.desc())
        .limit(10)
        .all()
    )
    trial_expired = False
    if existing_org and existing_org.temp_access_expires_at:
        expires_at = existing_org.temp_access_expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        trial_expired = expires_at < datetime.now(timezone.utc)
    return render_template(
        "dashboards/loi/admin_reauthorize.html",
        invite=invite, existing_user=existing_user, existing_org=existing_org,
        recent_events=recent_events, trial_expired=trial_expired,
    )
@loi_bp.route("/admin/reauthorize/<int:invite_id>/action", methods=["POST"])
@login_required
def admin_reauthorize_action(invite_id):
    invite = SignupInvites.query.get_or_404(invite_id)
    existing_user = Users.query.filter_by(email=invite.email).first()
    decision = request.form.get("decision")
    if not existing_user:
        flash("No existing account found for this invite.", "error")
        return redirect(url_for("loi.invite_list"))
    if decision == "reauthorize":
        existing_org = Organizations.query.get(existing_user.organization_id) if existing_user.organization_id else None
        if existing_org:
            existing_org.temp_access_expires_at = datetime.now(timezone.utc) + timedelta(days=14)
            existing_org.loi_required = True
        invite.status = "REAUTHORIZED"
        db.session.add(UserJourneyEvents(
            organization_id=existing_user.organization_id, invite_id=invite.id,
            user_id=current_user.id, event_type="admin_reauthorized_existing_user",
            event_detail=f"Admin re-authorized trial for {existing_user.email}"
        ))
        db.session.commit()
        flash(f"{existing_user.email} has been re-authorized for 14 more days.", "success")
    else:
        invite.status = "CANCELLED"
        db.session.add(UserJourneyEvents(
            invite_id=invite.id, user_id=current_user.id,
            event_type="admin_declined_reauthorize",
            event_detail=f"Admin declined to re-authorize {existing_user.email}"
        ))
        db.session.commit()
        flash("Invite cancelled.", "success")
    return redirect(url_for("loi.invite_list"))
@loi_bp.route("/activate/<token_hash>/submit", methods=["POST"])
def activation_submit(token_hash):
    invite = SignupInvites.query.filter_by(token_hash=token_hash).first()
    if not invite:
        flash("Invite not found.", "error")
        return redirect(url_for("main.login"))

    # Item #253 (2026-08-04): the email may already belong to an
    # existing account. Branch by whether this invite is a direct
    # admin invite or a forward (Group 7) -- see Build Sequence item
    # #253 for full design context and open questions still pending.
    existing_user = Users.query.filter_by(email=invite.email).first()
    if existing_user:
        if invite.parent_invite_id:
            # Scenario 2: forwarded to a colleague who already has an
            # account. Auto-resume, no admin gate -- getting the LOI
            # signed matters more than normal trial gating here.
            return _resume_existing_account_for_forward(invite, existing_user)
        # Scenario 1: a direct (non-forward) invite collided with an
        # existing account. Needs a human decision.
        return redirect(url_for("loi.admin_reauthorize_decision", invite_id=invite.id))

    # Fix 2026-08-06: a forwarded invite to someone with NO existing
    # account previously fell straight through to the generic
    # org-creation path below, creating a brand-new, disconnected
    # Organizations row -- same entity_name as the forwarding org (both
    # copied from the same source) but a different organization_id, no
    # real relationship in the database. The forwarded colleague ended
    # up in an isolated phantom org instead of actually joining the org
    # they were forwarded on behalf of; signing as them accomplished
    # nothing for the real org. If this invite has a parent (it's a
    # forward, set only by loi_forward_submit -- admin-created invites
    # never set this) and the parent invite's original user can still
    # be found, join that user's existing organization_id /
    # auditor_profile_id directly. If the parent user can't be found
    # (e.g. data inconsistency), fall through to the normal new-org
    # path below as a safe default rather than crashing.
    parent_user = None
    if invite.parent_invite_id:
        parent_user = Users.query.filter_by(invite_id=invite.parent_invite_id).first()

    if parent_user:
        user = Users(
            organization_id=parent_user.organization_id,
            email=invite.email,
            phone_no=request.form.get("phone"),
            name=request.form.get("contact_name"),
            designation=request.form.get("designation"),
            invite_id=invite.id,
            password_hash=generate_password_hash(request.form.get("password")),
            status="active",
            email_verified=True,
            auditor_profile_id=parent_user.auditor_profile_id,
            role_id=8,
        )
        db.session.add(user)
        db.session.flush()

        invite.status = "DETAILS_SUBMITTED"
        db.session.add(UserJourneyEvents(
            invite_id=invite.id, organization_id=parent_user.organization_id, user_id=user.id,
            event_type="details_submitted",
            event_detail=f"Joined existing org {parent_user.organization_id} via forward from invite {invite.parent_invite_id}"
        ))
        db.session.commit()

        login_user(user, remember=True)
        return redirect(url_for("loi.mfa_setup"))

    org = Organizations(
        name=request.form.get("legal_name"),
        legal_name=request.form.get("legal_name"),
        entity_type=request.form.get("entity_type"),
        cin=request.form.get("cin"),
        registered_address=request.form.get("registered_address"),
        city=request.form.get("city"),
        state=request.form.get("state"),
        contact_phone=request.form.get("phone"),
        loi_required=True,
        loi_status="PENDING",
        temp_access_expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.session.add(org)
    db.session.flush()

    # Note: uses the EXISTING Users.phone_no (NOT NULL) and
    # Users.password_hash columns -- both already present on the real
    # table, not new additions.
    # Reuses the EXISTING add_my_guidelines route as-is (per Shubha's
    # decision) rather than building a separate download mechanism for
    # trial users -- that route requires auditor_profile_id to be set,
    # pointing at an AuditOrganization record. This is NOT the full
    # multi-employee consulting-firm workflow that model was originally
    # designed for (see item logged in build sequence for that rethink)
    # -- just enough mandatory info, auto-filled from what was already
    # collected at signup, so download guidelines / create clients /
    # create projects all work correctly for a new self-signup user.
    audit_org = AuditOrganization(
        firm_name=request.form.get("legal_name"),
        firm_registration_no=request.form.get("cin"),
        firm_description=f"{request.form.get('entity_type')} -- registered via CompliFyre self-signup",
        number_of_employees=1,
    )
    db.session.add(audit_org)
    db.session.flush()

    user = Users(
        organization_id=org.organization_id,
        email=invite.email,
        phone_no=request.form.get("phone"),
        name=request.form.get("contact_name"),
        designation=request.form.get("designation"),
        invite_id=invite.id,
        password_hash=generate_password_hash(request.form.get("password")),
        status="active",
        email_verified=True,  # completing the invite-token flow IS the verification for this signup path
        auditor_profile_id=audit_org.id,
        role_id=8,  # AUDITOR -- fix 2026-07-31: self-signup users had no role_id, causing verify_tfa_login to 500
    )
    db.session.add(user)
    db.session.flush()

    invite.status = "DETAILS_SUBMITTED"
    db.session.add(UserJourneyEvents(
        invite_id=invite.id, organization_id=org.organization_id, user_id=user.id,
        event_type="details_submitted", event_detail=f"Org created: {org.name}"
    ))
    db.session.commit()

    # Real auto-login via Flask-Login, matching the existing pattern
    # used everywhere else in the app (see app/routes/main.py).
    login_user(user, remember=True)

    return redirect(url_for("loi.mfa_setup"))


@loi_bp.route("/activate/mfa-setup")
@login_required
def mfa_setup():
    """
    Reuses the EXISTING tfa_secret/tfa_enabled columns and the same
    pyotp + qrcode enrollment pattern already live in
    app/routes/main.py's setup_tfa() -- not a separate mechanism.
    """
    if current_user.tfa_enabled:
        return redirect(url_for("loi.welcome"))

    # Fix 2026-08-07: this used to generate a BRAND NEW secret on every
    # GET, unconditionally. Since verify_mfa()'s failure path redirects
    # straight back here on a wrong code, a user who mistypes once got
    # a new QR code that invalidated the one they'd just scanned --
    # making the retry loop unwinnable by design. Now only generates a
    # secret if one doesn't already exist, so the same QR code (and
    # authenticator app entry) stays valid across reloads/retries.
    if current_user.tfa_secret:
        secret = current_user.tfa_secret
    else:
        secret = pyotp.random_base32()
        current_user.tfa_secret = secret
        db.session.commit()

    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email, issuer_name="Complifyre"
    )
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

    return render_template(
        "dashboards/loi/mfa_setup.html", qr_code=img_str, secret=secret,
    )


@loi_bp.route("/activate/verify-mfa", methods=["POST"])
@login_required
def verify_mfa():
    token = request.form.get("token")
    if not pyotp.TOTP(current_user.tfa_secret).verify(token):
        flash("Incorrect code, please try again.", "error")
        return redirect(url_for("loi.mfa_setup"))

    current_user.tfa_enabled = True
    # Fix 2026-08-06: verify_mfa() never set session_token, so the
    # single-session check in main.py's before_request would bounce
    # the user with a confusing "accessed from another device" message
    # the moment they hit any main_bp route. Same pattern used by
    # verify_tfa_login() and setup_tfa()'s sibling routes.
    new_token = str(uuid.uuid4())
    current_user.session_token = new_token
    session["session_token"] = new_token

    invite = SignupInvites.query.get(current_user.invite_id) if current_user.invite_id else None
    if invite:
        invite.status = "ACTIVE"
        db.session.add(UserJourneyEvents(
            invite_id=invite.id, organization_id=current_user.organization_id,
            user_id=current_user.id, event_type="mfa_enrolled",
            event_detail="TOTP verified successfully"
        ))

    db.session.commit()
    return redirect(url_for("loi.welcome"))


@loi_bp.route("/welcome")
@login_required
def welcome():
    org = Organizations.query.get(current_user.organization_id)
    preloaded_count = 0
    if current_user.invite_id:
        preloaded_count = InvitePreloadGuidelines.query.filter_by(invite_id=current_user.invite_id).count()
    return render_template(
        "dashboards/loi/welcome.html", org=org, preloaded_count=preloaded_count,
    )


# ============================================================
# Group 6 -- LOI signing
# ============================================================

def get_active_loi_template():
    active = LoiTemplates.query.filter_by(is_active=True).first()
    if active and active.content:
        return active.content, active.version_label
    return DEFAULT_LOI_TEMPLATE_HTML, "default"


def render_loi_pdf(entity_name, signer_name, designation, date_str):
    from jinja2 import Template
    from weasyprint import HTML as WeasyHTML
    template_content, version_label = get_active_loi_template()
    html_content = Template(template_content).render(
        entity_name=entity_name, signer_name=signer_name,
        designation=designation, date=date_str,
    )
    pdf_bytes = WeasyHTML(string=html_content).write_pdf()
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    return pdf_bytes, pdf_sha256, version_label


DEFAULT_LOI_TEMPLATE_HTML = """
<html><head><style>
body { font-family: Georgia, serif; padding: 40px; line-height: 1.6; font-size: 13px; }
h1 { font-size: 18px; text-align: center; margin-bottom: 4px; }
.meta { margin-bottom: 20px; }
ul { margin-top: 4px; margin-bottom: 12px; }
li { margin-bottom: 4px; }
.sig-block { margin-top: 40px; }
.sig-line { margin-bottom: 2px; }
</style></head><body>
<h1>EVALUATION LETTER OF INTENT</h1>
<p class="meta">Date: {{ date }}</p>
<p class="meta">To<br>CompliFyre AI Labs Private Limited</p>
<p><strong>Subject: Evaluation of CompliFyre Platform</strong></p>

<p>This letter confirms that <strong>{{ entity_name }}</strong> ("Organization") intends to evaluate the CompliFyre Intelligent Regulatory Decomposition and Audit Platform through a 14-day evaluation/trial.</p>

<p>The undersigned confirms that they are duly authorized to sign this letter on behalf of the Organization.</p>

<p>The Organization understands that the purpose of the evaluation is to assess CompliFyre's capabilities against its business, regulatory, operational, technical, information security, and procurement requirements.</p>

<p>Subject to a satisfactory evaluation and successful completion of the Organization's internal review processes, the Organization intends to consider one or more of the following:</p>
<ul>
<li>Procurement of a subscription to the CompliFyre platform;</li>
<li>Deployment of CompliFyre within the Organization (cloud, private cloud, or on-premises, as applicable);</li>
<li>Engagement for a pilot or proof of value; or</li>
<li>Any other commercial engagement mutually agreed between the parties.</li>
</ul>

<p>The Organization acknowledges that any commercial engagement shall remain subject to, among other things:</p>
<ul>
<li>Internal technical evaluation;</li>
<li>Information security review;</li>
<li>Vendor due diligence;</li>
<li>Procurement and commercial approvals;</li>
<li>Legal review;</li>
<li>Budget approvals;</li>
<li>Compliance with internal policies and applicable regulations.</li>
</ul>

<p>Accordingly, this letter does not constitute a purchase order, binding commitment to procure, or legally enforceable obligation to enter into a commercial agreement.</p>

<p>This letter merely records the Organization's genuine intention to evaluate the CompliFyre platform in good faith and, should the evaluation prove satisfactory and internal approvals be obtained, to pursue commercial discussions.</p>

<div class="sig-block">
<p class="sig-line">Signed: {{ signer_name }}</p>
<p class="sig-line">Designation: {{ designation }}</p>
<p class="sig-line">Organization: {{ entity_name }}</p>
</div>
</body></html>
"""


@loi_bp.route("/loi/preview.pdf")
@login_required
def loi_preview_pdf():
    from flask import Response
    org = Organizations.query.get(current_user.organization_id)
    signer_name = current_user.name or "[Name not on file]"
    designation = current_user.designation or "[Designation not on file]"
    pdf_bytes, _, _ = render_loi_pdf(org.name, signer_name, designation, datetime.now().strftime("%d %b %Y"))
    return Response(pdf_bytes, mimetype="application/pdf")


@loi_bp.route("/loi/show")
@login_required
def loi_show():
    return render_template("dashboards/loi/loi_show.html")


@loi_bp.route("/loi/sign", methods=["POST"])
@login_required
def loi_sign():
    action = request.form.get("action")
    org = Organizations.query.get(current_user.organization_id)

    if action == "sign":
        # Fix 2026-08-06: previously trusted signer_name directly from the
        # POST body. HTML readonly on the template field is client-side only
        # and doesn't stop a raw POST carrying a different value -- for a
        # compliance-relevant, append-only signature record, the server now
        # ignores whatever was posted and uses the authenticated user's real
        # name, so the signed record can never diverge from who actually
        # signed in.
        signer_name = current_user.name
        authority_confirmed = bool(request.form.get("authority_confirmed"))

        date_str = datetime.now(timezone.utc).strftime("%d %b %Y")
        pdf_bytes, pdf_sha256, template_version = render_loi_pdf(
            org.name, signer_name, current_user.designation or "", date_str
        )

        signature = LoiSignatures(
            organization_id=org.organization_id,
            template_version=template_version,
            pdf_sha256=pdf_sha256,
            signer_name=signer_name,
            designation=current_user.designation,
            email=current_user.email,
            phone=current_user.phone_no,
            authority_confirmed=authority_confirmed,
            signed_at_utc=datetime.now(timezone.utc),
            ip_address=request.remote_addr,
            user_agent=request.headers.get("User-Agent", ""),
        )
        db.session.add(signature)
        db.session.flush()

        org.loi_status = "SIGNED"
        org.loi_signed_at = datetime.now(timezone.utc)
        org.loi_signature_id = signature.id
        org.temp_access_expires_at = None

        db.session.add(UserJourneyEvents(
            organization_id=org.organization_id, user_id=current_user.id,
            event_type="loi_signed", event_detail=f"Signed by {signer_name}"
        ))
        db.session.commit()

        # Save the signed PDF to disk so it's genuinely retrievable later,
        # independent of any future template text changes (added 2026-08-01).
        # Previously only the PDF's hash was stored, not the PDF itself.
        try:
            upload_base = os.getenv("UPLOAD_FOLDER", "uploads")
            signed_dir = os.path.join(upload_base, "loi_signed")
            os.makedirs(signed_dir, exist_ok=True)
            pdf_path = os.path.join(signed_dir, f"{signature.id}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
        except Exception as save_err:
            current_app.logger.error(f"Failed to save signed LOI PDF to disk for signature_id={signature.id}: {save_err}")

        # Email the signed PDF -- two separate sends, each independently
        # guarded so one failing never blocks the other or the signature
        # itself (already committed above).
        pdf_filename = f"CompliFyre_LOI_{org.name}_{date_str}.pdf".replace(" ", "_")
        try:
            from app.utils.email_service import send_loi_signed_pdf_email
            send_loi_signed_pdf_email(
                recipient_email="complifyre2fa@crackerjacktech.com",
                subject=f"Signed LOI -- {org.name}",
                body_text=(
                    f"A Letter of Intent has been signed.\n\n"
                    f"Organization: {org.name}\n"
                    f"Signed by: {signer_name}, {current_user.designation or ''}\n"
                    f"Date: {date_str}\n"
                    f"Signature ID: {signature.id}\n"
                ),
                pdf_bytes=pdf_bytes,
                pdf_filename=pdf_filename,
            )
        except Exception as email_err:
            current_app.logger.error(f"Failed to send internal LOI copy for signature_id={signature.id}: {email_err}")

        try:
            from app.utils.email_service import send_loi_signed_pdf_email
            send_loi_signed_pdf_email(
                recipient_email=current_user.email,
                subject="Your signed CompliFyre Letter of Intent",
                body_text=(
                    f"Thank you for signing the CompliFyre Letter of Intent.\n\n"
                    f"A copy is attached for your records.\n\n"
                    f"Organization: {org.name}\n"
                    f"Signed by: {signer_name}\n"
                    f"Date: {date_str}\n"
                ),
                pdf_bytes=pdf_bytes,
                pdf_filename=pdf_filename,
            )
        except Exception as email_err:
            current_app.logger.error(f"Failed to send signer LOI copy for signature_id={signature.id}: {email_err}")

        flash("Signed successfully. Thank you.", "success")
        return redirect(url_for("loi.welcome"))

    elif action == "remind_later":
        db.session.add(UserJourneyEvents(
            organization_id=org.organization_id, user_id=current_user.id,
            event_type="loi_prompt_dismissed", event_detail="Remind me later"
        ))
        db.session.commit()
        return redirect(url_for("loi.welcome"))

    return "Unknown action", 400


@loi_bp.route("/loi/admin/signed/<int:signature_id>.pdf")
@login_required
@role_required("COMPLIFYRE")
def loi_download_signed_pdf(signature_id):
    """
    Retrieve a previously-signed LOI PDF from disk by signature ID --
    added 2026-08-01 so a signed LOI is genuinely recoverable from the
    backend (not just via email) if delivery ever fails. Restricted to
    COMPLIFYRE admin role.
    """
    from flask import Response, abort
    signature = LoiSignatures.query.get(signature_id)
    if not signature:
        abort(404)
    upload_base = os.getenv("UPLOAD_FOLDER", "uploads")
    pdf_path = os.path.join(upload_base, "loi_signed", f"{signature_id}.pdf")
    if not os.path.exists(pdf_path):
        abort(404)
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"inline; filename=LOI_signature_{signature_id}.pdf"}
    )


# ============================================================
# Group 7 -- Forward to colleague
# ============================================================

@loi_bp.route("/loi/forward-form")
@login_required
def loi_forward_form():
    return render_template("dashboards/loi/forward_form.html")


@loi_bp.route("/loi/forward-submit", methods=["POST"])
@login_required
def loi_forward_submit():
    org = Organizations.query.get(current_user.organization_id)
    parent_invite_id = current_user.invite_id

    forwarded_name = request.form.get("forwarded_name")
    forwarded_designation = request.form.get("forwarded_designation")
    forwarded_email = request.form.get("forwarded_email")
    forwarded_phone = request.form.get("forwarded_phone")
    relationship_note = request.form.get("relationship_note")

    fwd_request = LoiForwardRequests(
        original_invite_id=parent_invite_id,
        forwarded_name=forwarded_name,
        forwarded_designation=forwarded_designation,
        forwarded_email=forwarded_email,
        forwarded_phone=forwarded_phone,
        relationship_note=relationship_note,
    )
    db.session.add(fwd_request)

    raw_token, token_hash = generate_invite_token()
    child_invite = SignupInvites(
        email=forwarded_email,
        entity_name=org.name,
        contact_name=forwarded_name,
        designation=forwarded_designation,
        phone=forwarded_phone,
        token_hash=token_hash,
        status="INVITED",
        parent_invite_id=parent_invite_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.session.add(child_invite)
    db.session.flush()

    # Fix 2026-08-07: forwards previously gave the colleague access to
    # ZERO guidelines -- hardcoded 0 in the email, and no actual rows
    # copied into InvitePreloadGuidelines either. Since a forward means
    # "this colleague works with me on the same org's compliance work"
    # (per Ankita 2026-08-07), they should see the SAME guidelines A
    # already has, not start from an empty library. If A wants B to
    # see more/different guidelines later, that's a separate, explicit
    # admin action -- this just carries over what's already assigned.
    preloaded_guideline_ids = [
        row.guideline_id for row in
        InvitePreloadGuidelines.query.filter_by(invite_id=parent_invite_id).all()
    ] if parent_invite_id else []

    for gid in preloaded_guideline_ids:
        db.session.add(InvitePreloadGuidelines(invite_id=child_invite.id, guideline_id=gid))

    if parent_invite_id:
        parent_invite = SignupInvites.query.get(parent_invite_id)
        if parent_invite:
            parent_invite.status = "FORWARDED"

    db.session.add(UserJourneyEvents(
        organization_id=org.organization_id, invite_id=parent_invite_id,
        user_id=current_user.id, event_type="forwarded",
        event_detail=f"Forwarded to {forwarded_name} ({forwarded_email}), {len(preloaded_guideline_ids)} guideline(s) carried over"
    ))
    db.session.commit()

    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)

    subject, html_body = render_invite_email_content(
        contact_name=forwarded_name or "there",
        entity_name=org.name or "your organization",
        guideline_count=len(preloaded_guideline_ids),
        activation_link=activation_link,
        expiry_date=child_invite.expires_at.strftime("%d %B %Y"),
        email=forwarded_email,
    )
    email_sent = send_invite_email(forwarded_email, subject, html_body)

    if not email_sent:
        flash(
            f"Invite created for {forwarded_name}, but the email failed to send. "
            f"Activation link (share manually): {activation_link}", "warning"
        )

    return render_template("dashboards/loi/forward_sent.html", forwarded_name=forwarded_name)


# ============================================================
# Group 8 -- Soft gate (core logic; wiring into real trigger
# points is a separate follow-on patch)
# ============================================================

def get_loi_gate_state(org, user=None):
    """
    Returns 'NONE' / 'MODAL' / 'BANNER', computed from ACTUAL logged
    events (not a manually-passed counter). Shown to every user in an
    unsigned org, not just the first -- appearance counting is
    org-wide, not per-user.
    """
    if not org.loi_required:
        return "NONE"
    if org.loi_status == "SIGNED":
        return "NONE"

    FORWARD_GRACE_DAYS = 7
    most_recent_forward = (
        UserJourneyEvents.query
        .filter_by(organization_id=org.organization_id, event_type="forwarded")
        .order_by(UserJourneyEvents.occurred_at.desc())
        .first()
    )
    # Fix 2026-08-09: this was checking org-wide, not per-user -- meaning
    # it correctly silenced the gate for A (the person who forwarded)
    # but ALSO accidentally silenced it for B (the colleague forwarded
    # TO), who has never actually seen the LOI even once. Now only
    # applies if the current viewer is the SAME user_id that did the
    # forwarding, matching this function's own (previously unused)
    # user= parameter.
    if most_recent_forward and user is not None and most_recent_forward.user_id == user.id:
        occurred_at = most_recent_forward.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - occurred_at).days < FORWARD_GRACE_DAYS:
            return "NONE"

    shown_events = (
        UserJourneyEvents.query
        .filter_by(organization_id=org.organization_id, event_type="loi_prompt_shown")
        .order_by(UserJourneyEvents.occurred_at.desc())
        .all()
    )

    if len(shown_events) >= 5:
        return "BANNER"

    if shown_events:
        most_recent_shown = shown_events[0].occurred_at
        if most_recent_shown.tzinfo is None:
            most_recent_shown = most_recent_shown.replace(tzinfo=timezone.utc)
        hours_since_shown = (datetime.now(timezone.utc) - most_recent_shown).total_seconds() / 3600
        if hours_since_shown < 24:
            return "NONE"

    return "MODAL"


def record_loi_prompt_shown(org, user, trigger):
    db.session.add(UserJourneyEvents(
        organization_id=org.organization_id, user_id=user.id if user else None,
        event_type="loi_prompt_shown", event_detail=f"Triggered by: {trigger}"
    ))
    db.session.commit()


def loi_gate_redirect_if_needed(trigger_name):
    """
    Call this at the top of any real action route that should be
    gated by the LOI soft-gate. Returns a redirect response if the
    modal should show (and logs the appearance), or None if the
    caller should proceed normally.
    """
    org = Organizations.query.get(current_user.organization_id)
    if not org:
        return None
    gate_state = get_loi_gate_state(org, current_user)
    if gate_state == "MODAL":
        record_loi_prompt_shown(org, current_user, trigger_name)
        return redirect(url_for("loi.loi_show"))
    return None


@loi_bp.route("/admin/settings/invite-email", methods=["GET", "POST"])
@login_required
def edit_invite_email_content():
    content_row = EditableContent.query.get("invite_email")

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        body = request.form.get("body", "").strip()
        if not subject or not body:
            flash("Subject and body cannot be empty.", "error")
            return redirect(url_for("loi.edit_invite_email_content"))
        if content_row:
            content_row.subject, content_row.body = subject, body
        else:
            db.session.add(EditableContent(key="invite_email", subject=subject, body=body))
        db.session.commit()
        flash("Invite email updated. Applies to every invite sent from now on.", "success")
        return redirect(url_for("loi.edit_invite_email_content"))

    return render_template(
        "dashboards/loi/edit_invite_email.html",
        current_subject=content_row.subject if content_row else DEFAULT_INVITE_SUBJECT,
        current_body=content_row.body if content_row else DEFAULT_INVITE_BODY,
    )
