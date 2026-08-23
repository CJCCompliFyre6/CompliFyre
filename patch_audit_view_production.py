import shutil

path = "app/routes/audit/view.py"
with open(path) as f:
    content = f.read()

old_import = "from app.utils.extract_clause_helper import check_free_report_used\n"
new_import = "from app.utils.extract_clause_helper import check_free_report_used\nfrom app.routes.loi.view import loi_gate_redirect_if_needed\n"

old_gate = '''def add_my_guidelines():
    """
    This route add guidelines to my guidelines
    """
    if current_user.is_authenticated:
        if current_user.auditor_profile_id:'''

new_gate = '''def add_my_guidelines():
    """
    This route add guidelines to my guidelines
    """
    if current_user.is_authenticated:
        # LOI soft-gate (Group 8) added 2026-08-01: redirect to LOI signing
        # if this trial user's gate state calls for it, before the download proceeds.
        gate_response = loi_gate_redirect_if_needed("download_guideline")
        if gate_response is not None:
            return gate_response
        if current_user.auditor_profile_id:'''

checks = [
    ("import line", content.count(old_import)),
    ("add_my_guidelines gate block", content.count(old_gate)),
]
bad = [(name, count) for name, count in checks if count != 1]

if bad:
    print(f"WARNING: exact-match failed for: {bad}. Full counts: {checks}. No edit made.")
else:
    shutil.copy(path, path + ".bak_pre_loi_gate_port")
    content = content.replace(old_import, new_import, 1)
    content = content.replace(old_gate, new_gate, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched audit/view.py (backup at view.py.bak_pre_loi_gate_port)")
