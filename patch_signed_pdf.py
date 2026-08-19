import shutil

path = "app/utils/email_service.py"
with open(path) as f:
    lines = f.readlines()

start_idx = None
for i, line in enumerate(lines):
    if line.startswith("def send_loi_signed_pdf_email("):
        start_idx = i
        break

if start_idx is None:
    print("WARNING: could not find 'def send_loi_signed_pdf_email(' anywhere in the file. No edit made.")
else:
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        stripped = lines[j].strip()
        if lines[j].startswith("def ") or lines[j].startswith("@") or lines[j].startswith("class "):
            end_idx = j
            break

    print(f"Found send_loi_signed_pdf_email spanning lines {start_idx+1} to {end_idx} (exclusive)")
    print("--- Full detected function, for a sanity check ---")
    for l in lines[start_idx:end_idx]:
        print(repr(l))

    new_function = '''def send_loi_signed_pdf_email(recipient_email, subject, body_text, pdf_bytes, pdf_filename):
    """
    Send a signed LOI PDF as an attachment to a single recipient.
    Added 2026-08-01. Call this twice -- once for the CompliFyre internal
    copy, once for the signer's own copy -- each wrapped in its own
    try/except at the call site so one failing never blocks the other.

    Fix 2026-08-09: switched from raw smtplib (crackerjacktech.com relay,
    permanent MailChannels [ESA] abuse block found the previous night) to
    Azure Communication Services via the shared send_via_azure_email()
    helper in this same file, using Azure's attachments format
    (base64-encoded content, no import needed since both functions
    already live in email_service.py).
    """
    import base64
    encoded_pdf = base64.b64encode(pdf_bytes).decode()
    attachments = [{
        "name": pdf_filename,
        "contentType": "application/pdf",
        "contentInBase64": encoded_pdf,
    }]
    return send_via_azure_email(
        recipient_email=recipient_email,
        subject=subject,
        html_body=f"<p>{body_text}</p>",
        plain_text=body_text,
        attachments=attachments,
    )


'''

    shutil.copy(path, path + ".bak_azure_signed_pdf_migration")
    new_lines = lines[:start_idx] + [new_function] + lines[end_idx:]
    with open(path, "w") as f:
        f.writelines(new_lines)
    print("Patched email_service.py (backup at email_service.py.bak_azure_signed_pdf_migration)")
