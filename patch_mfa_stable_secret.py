import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '''    if current_user.tfa_enabled:
        return redirect(url_for("loi.welcome"))
    secret = pyotp.random_base32()
    current_user.tfa_secret = secret
    db.session.commit()
    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email, issuer_name="Complifyre"
    )'''

new = '''    if current_user.tfa_enabled:
        return redirect(url_for("loi.welcome"))

    # Fix 2026-08-07: this used to generate a BRAND NEW secret on every
    # GET, unconditionally. Since verify_mfa()'s failure path redirects
    # straight back here on a wrong code, a user who mistypes once got
    # a new QR code that invalidated the one they'd just scanned --
    # making the retry loop unwinnable by design. Now only generates a
    # secret if one doesn't already exist, so the same QR code (and
    # authenticator app entry) stays valid across reloads/retries.
    if current_user.tfa_secret:
        secret = current_user.tfa_secret
    else:
        secret = pyotp.random_base32()
        current_user.tfa_secret = secret
        db.session.commit()

    provisioning_uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=current_user.email, issuer_name="Complifyre"
    )'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_mfa_stable_secret_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched view.py (backup at view.py.bak_mfa_stable_secret_fix)")
