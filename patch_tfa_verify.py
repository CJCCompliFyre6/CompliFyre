path = "app/routes/main.py"
with open(path) as f:
    content = f.read()

old = '        if str(token) == user.tfa_secret:'
new = '        if user.tfa_secret and pyotp.TOTP(user.tfa_secret).verify(token):'

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    import shutil
    shutil.copy(path, path + ".bak_tfa_verify_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched main.py (backup at main.py.bak_tfa_verify_fix)")
