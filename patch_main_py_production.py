import shutil

path = "app/routes/main.py"
with open(path) as f:
    content = f.read()

# --- Change 1: verify_user_login OTP send -> Azure ---
old1 = '''    # Send OTP email
    msg = Message(
        subject="Complifyre - Your Login OTP",
        recipients=[user.email],
        html=f"<p>Welcome back!</p><p>Your OTP code is: <b>{otp}</b></p>",
    )
    mail.send(msg)'''

new1 = '''    # Send OTP email

    # Fix 2026-08-09: switched the actual send from Flask-Mail's
    # mail.send() (crackerjacktech.com relay, permanent MailChannels
    # [ESA] abuse block found the previous night) to Azure Communication
    # Services via the shared send_via_azure_email() helper. OTP
    # generation and storage logic is unchanged.
    from app.utils.email_service import send_via_azure_email

    send_via_azure_email(
        recipient_email=user.email,
        subject="Complifyre - Your Login OTP",
        html_body=f"<p>Welcome back!</p><p>Your OTP code is: <b>{otp}</b></p>",
    )'''

# --- Change 2: send_password_reset_email -> Azure ---
old2 = '''    msg = Message(
        subject="Complifyre - Password Reset Request",
        recipients=[user_email],
        html=f"<p>Click the link to reset your password:</p><p><a href='{reset_url}'>Reset Password</a></p>",
    )
    mail.send(msg)'''

new2 = '''    # Fix 2026-08-09: switched the actual send from Flask-Mail's
    # mail.send() (crackerjacktech.com relay, permanent MailChannels
    # [ESA] abuse block found the previous night) to Azure Communication
    # Services via the shared send_via_azure_email() helper. Token
    # generation logic is unchanged.
    from app.utils.email_service import send_via_azure_email

    send_via_azure_email(
        recipient_email=user_email,
        subject="Complifyre - Password Reset Request",
        html_body=f"<p>Click the link to reset your password:</p><p><a href='{reset_url}'>Reset Password</a></p>",
    )'''

# --- Change 3: defensive role_id None-guard (July 31 fix, missing on production) ---
old3 = '''            if current_user.role.name == "COMPLIFYRE":
                return redirect(url_for("main.comp_dash"))
            elif current_user.role.name == "AUDITOR":'''

new3 = '''            # Defensive guard added 2026-07-31 (staging), ported 2026-08-09:
            # role_id was found missing on some self-signup users, causing
            # a 500 here. Root cause fixed in loi/view.py activation_submit;
            # this guard just prevents a repeat 500 if a role is ever
            # missing again.
            if current_user.role and current_user.role.name == "COMPLIFYRE":
                return redirect(url_for("main.comp_dash"))
            elif current_user.role and current_user.role.name == "AUDITOR":'''

checks = [
    ("verify_user_login block", content.count(old1)),
    ("send_password_reset_email block", content.count(old2)),
    ("role_id guard block", content.count(old3)),
]
bad = [(name, count) for name, count in checks if count != 1]

if bad:
    print(f"WARNING: exact-match failed for: {bad}. Full counts: {checks}. No edit made.")
else:
    shutil.copy(path, path + ".bak_pre_azure_and_guard_port")
    content = content.replace(old1, new1, 1)
    content = content.replace(old2, new2, 1)
    content = content.replace(old3, new3, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched main.py (backup at main.py.bak_pre_azure_and_guard_port)")
