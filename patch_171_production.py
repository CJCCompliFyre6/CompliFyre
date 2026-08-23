import shutil

path = "app/routes/re/view.py"
with open(path) as f:
    content = f.read()

old = '''        # If disabling, remove associations to auditor_selected_guidelines so auditors won't see it
        if not new_enabled:
            # Assuming auditor_selected_guidelines is a Table object available in scope
            stmt = delete(auditor_selected_guidelines).where(
                auditor_selected_guidelines.c.guideline_id == guideline_id
            )
            db.session.execute(stmt)'''

new = '''        # Fix 2026-08-09 (item #171, real live bug, deliberately parked
        # 2026-07-29 pending the LOI/login system which is now built):
        # withdrawing/disabling a guideline must NOT remove an auditor's
        # existing access to it. This used to hard-DELETE the
        # auditor_selected_guidelines row, wiping out any auditor who
        # already had it in their library. Now it only flips enabled/
        # disabled_reason/disabled_at -- re/view.py's guidelines() list
        # (what NEW downloads pull from) already filters on enabled=True,
        # so a withdrawn guideline correctly stops being offered as a new
        # download, while my_guidelines() (which never filtered on
        # enabled) continues showing it for auditors who already have it.'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_item171_production_port")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched re/view.py (backup at view.py.bak_item171_production_port)")
