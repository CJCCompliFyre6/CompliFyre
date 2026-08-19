import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

# 1. Add `session` to the flask import
old_import = "from flask import (\n    Blueprint, request, render_template, redirect, url_for, flash,\n    current_app,\n)"
new_import = "from flask import (\n    Blueprint, request, render_template, redirect, url_for, flash,\n    current_app, session,\n)"

# 2. Add uuid import (not currently imported in this file)
old_uuid = "import hashlib\n"
new_uuid = "import hashlib\nimport uuid\n"

# 3. Set session_token in verify_mfa() right where tfa_enabled gets set
old_verify = '''    token = request.form.get("token")
    if not pyotp.TOTP(current_user.tfa_secret).verify(token):
        flash("Incorrect code, please try again.", "error")
        return redirect(url_for("loi.mfa_setup"))

    current_user.tfa_enabled = True'''

new_verify = '''    token = request.form.get("token")
    if not pyotp.TOTP(current_user.tfa_secret).verify(token):
        flash("Incorrect code, please try again.", "error")
        return redirect(url_for("loi.mfa_setup"))

    current_user.tfa_enabled = True
    # Fix 2026-08-06: verify_mfa() never set session_token, so the
    # single-session check in main.py's before_request would bounce
    # the user with a confusing "accessed from another device" message
    # the moment they hit any main_bp route. Same pattern used by
    # verify_tfa_login() and setup_tfa()'s sibling routes.
    new_token = str(uuid.uuid4())
    current_user.session_token = new_token
    session["session_token"] = new_token'''

checks = [
    ("flask import block", old_import in content),
    ("uuid import point", old_uuid in content),
    ("verify_mfa block", old_verify in content),
]
missing = [name for name, found in checks if not found]

if missing:
    print(f"WARNING: could not find exact match for: {', '.join(missing)}. No edits made.")
else:
    shutil.copy(path, path + ".bak_session_token_fix")
    content = content.replace(old_import, new_import, 1)
    content = content.replace(old_uuid, new_uuid, 1)
    content = content.replace(old_verify, new_verify, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched loi/view.py (backup at view.py.bak_session_token_fix)")
