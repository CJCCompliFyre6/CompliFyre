import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '''        # Scenario 1: a direct (non-forward) invite collided with an
        # existing account. Needs a human decision.
        return redirect(url_for("loi.admin_reauthorize_decision", invite_id=invite.id))

    org = Organizations('''

new = '''        # Scenario 1: a direct (non-forward) invite collided with an
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

    org = Organizations('''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_forward_org_link_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched view.py (backup at view.py.bak_forward_org_link_fix)")
