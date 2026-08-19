import shutil

path = "app/routes/main.py"
with open(path) as f:
    lines = f.readlines()

start_idx = None
for i, line in enumerate(lines):
    if line.startswith("def send_password_reset_email("):
        start_idx = i
        break

if start_idx is None:
    print("WARNING: could not find 'def send_password_reset_email(' anywhere in the file. No edit made.")
else:
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith("def ") or lines[j].startswith("@") or lines[j].startswith("class "):
            end_idx = j
            break

    print(f"Found send_password_reset_email spanning lines {start_idx+1} to {end_idx} (exclusive)")
    print("--- Full detected function, for a sanity check ---")
    for l in lines[start_idx:end_idx]:
        print(repr(l))

    new_function = '''def send_password_reset_email(user_email):
    """
    Fix 2026-08-09: switched the actual send from Flask-Mail's
    mail.send() (crackerjacktech.com relay, permanent MailChannels
    [ESA] abuse block found the previous night) to Azure Communication
    Services via the shared send_via_azure_email() helper. Token
    generation logic is unchanged.
    """
    from app.utils.email_service import send_via_azure_email

    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = serializer.dumps(user_email, salt="password-reset-salt")
    reset_url = url_for("main.reset_password_token", token=token, _external=True)
    send_via_azure_email(
        recipient_email=user_email,
        subject="Complifyre - Password Reset Request",
        html_body=f"<p>Click the link to reset your password:</p><p><a href='{reset_url}'>Reset Password</a></p>",
    )


'''

    shutil.copy(path, path + ".bak_azure_password_reset_migration")
    new_lines = lines[:start_idx] + [new_function] + lines[end_idx:]
    with open(path, "w") as f:
        f.writelines(new_lines)
    print("Patched main.py (backup at main.py.bak_azure_password_reset_migration)")
