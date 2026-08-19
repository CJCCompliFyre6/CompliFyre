import shutil

path = "app/routes/re/view.py"
with open(path) as f:
    content = f.read()

old_import = "from app.models.re import RegulatoryBodies, RegulatoryDocuments\n"
new_import = "from app.models.re import RegulatoryBodies, RegulatoryDocuments\nfrom app.models.loi import InvitePreloadGuidelines\n"

old_logic = '''        user_role_id = current_user.role_id if current_user.role_id else None
        if user_role_id == AUDITOR_ROLE_ID:
            # Auditor view — show only ENABLED guidelines not yet downloaded by this auditor
            if current_user.auditor_profile_id:
                subquery = select(auditor_selected_guidelines.c.guideline_id).where(
                    auditor_selected_guidelines.c.audit_id
                    == current_user.auditor_profile_id
                )
                stmt = select(Guidelines).where(
                    ~Guidelines.id.in_(subquery),
                    Guidelines.enabled == True
                )
            else:
                # Auditor without auditor_profile — show enabled guidelines only (none downloaded yet)
                stmt = select(Guidelines).where(Guidelines.enabled == True)
            guidelines = db.session.execute(stmt).scalars().all()'''

new_logic = '''        user_role_id = current_user.role_id if current_user.role_id else None
        if user_role_id == AUDITOR_ROLE_ID:
            # Auditor view — show only ENABLED guidelines not yet downloaded by this auditor
            # Fix 2026-08-01: self-signup (invite-based) auditors should only see the
            # specific guidelines their admin preloaded for them, not the full enabled
            # catalogue. Legacy auditors (invite_id is None) are unaffected -- they keep
            # seeing the full enabled catalogue exactly as before.
            preload_filter = None
            if current_user.invite_id:
                preload_subquery = select(InvitePreloadGuidelines.guideline_id).where(
                    InvitePreloadGuidelines.invite_id == current_user.invite_id
                )
                preload_filter = Guidelines.id.in_(preload_subquery)

            if current_user.auditor_profile_id:
                subquery = select(auditor_selected_guidelines.c.guideline_id).where(
                    auditor_selected_guidelines.c.audit_id
                    == current_user.auditor_profile_id
                )
                conditions = [
                    ~Guidelines.id.in_(subquery),
                    Guidelines.enabled == True
                ]
                if preload_filter is not None:
                    conditions.append(preload_filter)
                stmt = select(Guidelines).where(*conditions)
            else:
                # Auditor without auditor_profile — show enabled guidelines only (none downloaded yet)
                conditions = [Guidelines.enabled == True]
                if preload_filter is not None:
                    conditions.append(preload_filter)
                stmt = select(Guidelines).where(*conditions)
            guidelines = db.session.execute(stmt).scalars().all()'''

checks = [
    ("import line", content.count(old_import)),
    ("guidelines() logic block", content.count(old_logic)),
]
bad = [(name, count) for name, count in checks if count != 1]

if bad:
    print(f"WARNING: exact-match failed for: {bad}. Full counts: {checks}. No edit made.")
else:
    shutil.copy(path, path + ".bak_pre_loi_gate_port")
    content = content.replace(old_import, new_import, 1)
    content = content.replace(old_logic, new_logic, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched re/view.py (backup at view.py.bak_pre_loi_gate_port)")
