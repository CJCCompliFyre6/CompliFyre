import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '''    db.session.commit()
    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)
    flash(f"New activation link for {invite.email}: {activation_link}", "success")
    return redirect(url_for("loi.invite_list"))'''

new = '''    db.session.commit()
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

    return redirect(url_for("loi.invite_list"))'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_resend_email_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched view.py (backup at view.py.bak_resend_email_fix)")
