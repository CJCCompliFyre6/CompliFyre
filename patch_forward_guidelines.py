import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '''    db.session.add(child_invite)
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

    subject, html_body = render_invite_email_content(
        contact_name=forwarded_name or "there",
        entity_name=org.name or "your organization",
        guideline_count=0,
        activation_link=activation_link,
        expiry_date=child_invite.expires_at.strftime("%d %B %Y"),
        email=forwarded_email,
    )'''

new = '''    db.session.add(child_invite)
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
    )'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_forward_guidelines_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched view.py (backup at view.py.bak_forward_guidelines_fix)")
