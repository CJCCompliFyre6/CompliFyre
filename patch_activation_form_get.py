import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '''def activation_form(raw_token):
    invite, status = validate_invite_token(raw_token)
    if not invite:
        flash(f"This invite link is no longer valid ({status}).", "error")
        return redirect(url_for("main.login"))
    return render_template(
        "dashboards/loi/activation_form.html",
        invite=invite, entity_types=ENTITY_TYPES,
    )'''

new = '''def activation_form(raw_token):
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
    )'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_activation_form_parent_org")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched view.py (backup at view.py.bak_activation_form_parent_org)")
