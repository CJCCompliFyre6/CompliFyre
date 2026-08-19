path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

if "send_invite_email" in content:
    print("Already patched, skipping.")
else:
    import shutil
    shutil.copy(path, path + ".bak_invite_email_feature")

    content = content.replace(
        "from app import db\n",
        "from app import db\n"
        "from app.models.loi import EditableContent\n"
        "from app.utils.email_service import send_invite_email, render_invite_email_content, DEFAULT_INVITE_SUBJECT, DEFAULT_INVITE_BODY\n",
        1
    )

    old_todo = '''    # TODO (next porting pass): wire to CompliFyre's real email-sending
    # service. For now the activation link is flashed to the admin so
    # invites remain testable on staging before email sending is wired.
    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)
    flash(f"Invite sent to {email}. Activation link: {activation_link}", "success")'''

    new_send = '''    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)

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
        )'''

    if old_todo not in content:
        print("WARNING: could not find the exact TODO block to replace -- file may have changed. No edits made.")
    else:
        content = content.replace(old_todo, new_send, 1)

        new_route = '''

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
'''
        content += new_route

        with open(path, "w") as f:
            f.write(content)
        print("Patched loi/view.py (backup at view.py.bak_invite_email_feature)")
