#!/usr/bin/env python3
"""
Patch: add Group 6 (LOI signing) and Group 7 (forward to colleague)
routes to the already-deployed app/routes/loi/view.py, and update its
imports accordingly.

Usage:
    python3 patch_add_group6_7_routes.py --dry-run
    python3 patch_add_group6_7_routes.py --apply
    python3 patch_add_group6_7_routes.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "loi" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_group6_7")

IMPORT_ANCHOR = '''from app.models import (
    SignupInvites, InvitePreloadGuidelines, Guidelines, Organizations,
    Users, UserJourneyEvents,
)'''

IMPORT_NEW = '''from app.models import (
    SignupInvites, InvitePreloadGuidelines, Guidelines, Organizations,
    Users, UserJourneyEvents, LoiTemplates, LoiSignatures, LoiForwardRequests,
)'''

APPEND_ANCHOR = '''    return render_template(
        "dashboards/loi/welcome.html", org=org, preloaded_count=preloaded_count,
    )'''

APPEND_NEW = APPEND_ANCHOR + '''


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
body { font-family: Georgia, serif; padding: 40px; line-height: 1.6; }
h1 { font-size: 20px; }
.field { font-weight: bold; }
</style></head><body>
<h1>Letter of Intent</h1>
<p>This Letter of Intent is entered into by:</p>
<p><span class="field">Entity:</span> {{ entity_name }}<br>
   <span class="field">Represented by:</span> {{ signer_name }}, {{ designation }}</p>
<p>The above entity expresses its intent to evaluate CompliFyre's regulatory compliance
platform on a trial basis. <strong>This carries no immediate financial obligation, and is
only a signal of intent.</strong></p>
<p><span class="field">Date:</span> {{ date }}</p>
</body></html>
"""


@loi_bp.route("/loi/preview.pdf")
@login_required
def loi_preview_pdf():
    from flask import Response
    org = Organizations.query.get(current_user.organization_id)
    pdf_bytes, _, _ = render_loi_pdf(org.name, "[Preview]", "[Preview]", datetime.now().strftime("%d %b %Y"))
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
        signer_name = request.form.get("signer_name")
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

    if parent_invite_id:
        parent_invite = SignupInvites.query.get(parent_invite_id)
        if parent_invite:
            parent_invite.status = "FORWARDED"

    db.session.add(UserJourneyEvents(
        organization_id=org.organization_id, invite_id=parent_invite_id,
        user_id=current_user.id, event_type="forwarded",
        event_detail=f"Forwarded to {forwarded_name} ({forwarded_email})"
    ))
    db.session.commit()

    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)
    flash(f"Invite sent to {forwarded_name}. Activation link: {activation_link}", "success")

    return render_template("dashboards/loi/forward_sent.html", forwarded_name=forwarded_name)'''


def apply_patch(content):
    count1 = content.count(IMPORT_ANCHOR)
    if count1 != 1:
        print(f"ERROR: import anchor matched {count1} times (expected 1). Aborting.")
        sys.exit(1)
    count2 = content.count(APPEND_ANCHOR)
    if count2 != 1:
        print(f"ERROR: append anchor matched {count2} times (expected 1). Aborting.")
        sys.exit(1)
    content = content.replace(IMPORT_ANCHOR, IMPORT_NEW)
    content = content.replace(APPEND_ANCHOR, APPEND_NEW)
    return content


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        if not BACKUP.exists():
            print(f"No backup found at {BACKUP}. Nothing to roll back.")
            sys.exit(1)
        shutil.copy2(BACKUP, TARGET)
        print(f"Rolled back {TARGET} from {BACKUP}.")
        return

    if not TARGET.exists():
        print(f"ERROR: target file not found: {TARGET}")
        sys.exit(1)

    content = TARGET.read_text()

    if "Group 6 -- LOI signing" in content:
        print("Patch already applied. Nothing to do.")
        return

    patched = apply_patch(content)

    if args.dry_run:
        print("Both anchors matched exactly once.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
