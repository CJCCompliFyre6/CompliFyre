import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '        signer_name = request.form.get("signer_name")'
new = '''        # Fix 2026-08-06: previously trusted signer_name directly from the
        # POST body. HTML readonly on the template field is client-side only
        # and doesn't stop a raw POST carrying a different value -- for a
        # compliance-relevant, append-only signature record, the server now
        # ignores whatever was posted and uses the authenticated user's real
        # name, so the signed record can never diverge from who actually
        # signed in.
        signer_name = current_user.name'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_signer_name_server_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched loi/view.py (backup at view.py.bak_signer_name_server_fix)")
