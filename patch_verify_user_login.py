import shutil

path = "app/routes/main.py"
with open(path) as f:
    lines = f.readlines()

start_idx = None
for i, line in enumerate(lines):
    if line.startswith("def verify_user_login("):
        start_idx = i
        break

if start_idx is None:
    print("WARNING: could not find 'def verify_user_login(' anywhere in the file. No edit made.")
else:
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("def ") or lines[j].startswith("@") or lines[j].startswith("class "):
            end_idx = j
            break

    print(f"Found verify_user_login spanning lines {start_idx+1} to {end_idx} (exclusive)")
    print("--- Full detected function, for a sanity check ---")
    for l in lines[start_idx:end_idx]:
        print(repr(l))

    new_function = '''def verify_user_login(user):
    """
    Generate a 6-digit OTP, store it in the database (or session),
    and send it via email.

    Fix 2026-08-09: switched the actual send from Flask-Mail's
    mail.send() (crackerjacktech.com relay, permanent MailChannels
    [ESA] abuse block found the previous night) to Azure Communication
    Services via the shared send_via_azure_email() helper. OTP
    generation and storage logic is unchanged.
    """
    from app.utils.email_service import send_via_azure_email

    # Generate a 6-digit OTP
    otp = str(random.randint(100000, 999999))

    # Store OTP in user record (or Redis/cache for expiry handling)
    user.tfa_secret = str(otp)
    db.session.commit()

    # Send OTP email
    send_via_azure_email(
        recipient_email=user.email,
        subject="Complifyre - Your Login OTP",
        html_body=f"<p>Welcome back!</p><p>Your OTP code is: <b>{otp}</b></p>",
    )


'''

    shutil.copy(path, path + ".bak_azure_login_otp_migration")
    new_lines = lines[:start_idx] + [new_function] + lines[end_idx:]
    with open(path, "w") as f:
        f.writelines(new_lines)
    print("Patched main.py (backup at main.py.bak_azure_login_otp_migration)")
