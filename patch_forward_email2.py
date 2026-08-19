import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '''    db.session.commit()

    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)
    flash(f"Invite sent to {forwarded_name}. Activation link: {activation_link}", "success")

    return render_template("dashboards/loi/forward_sent.html", forwarded_name=forwarded_name)'''

new = '''    db.session.commit()

    activation_link = url_for("loi.activation_form", raw_token=raw_token, _external=True)

    subject, html_body = render_invite_email_content(
        contact_name=forwarded_name or "there",
        entity_name=org.name or "your organization",
        guideline_count=0,
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

    return render_template("dashboards/loi/forward_sent.html", forwarded_name=forwarded_name)'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_forward_email_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched view.py (backup at view.py.bak_forward_email_fix)")
