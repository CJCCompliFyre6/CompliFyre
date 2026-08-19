import shutil

path = "app/utils/email_service.py"
with open(path) as f:
    lines = f.readlines()

start_idx = None
for i, line in enumerate(lines):
    if line.startswith("def send_invite_email("):
        start_idx = i
        break

if start_idx is None:
    print("WARNING: could not find 'def send_invite_email(' anywhere in the file. No edit made.")
else:
    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        stripped = lines[j]
        if stripped.startswith("def ") or stripped.startswith("@") or stripped.startswith("class "):
            end_idx = j
            break

    print(f"Found send_invite_email spanning lines {start_idx+1} to {end_idx} (exclusive)")
    print("--- Last 3 lines of detected function, for a sanity check ---")
    for l in lines[max(start_idx, end_idx-3):end_idx]:
        print(repr(l))

    new_function = '''AZURE_INVITE_SENDER_ADDRESS = "DoNotReply@81e374c8-c1f6-4ca1-bf01-f50362e6b216.azurecomm.net"


def send_invite_email(recipient_email, subject, html_body):
    """
    Fix 2026-08-08: switched from the crackerjacktech.com SMTP relay to
    Azure Communication Services Email, after that relay was found to
    have a PERMANENT MailChannels abuse block (550 5.7.1 [ESA] Sender
    blocked) silently killing delivery -- confirmed via raw SMTP debug
    tests showing clean acceptance by the relay itself (250 OK with a
    real queue ID) while nothing ever arrived at Gmail or YopMail, and
    via hundreds of unread bounce notices sitting in the sending
    mailbox. Same function name/signature as before, so create_invite(),
    loi_forward_submit(), and resend_invite_link() all needed zero
    changes. Login OTP, password reset, and signed-LOI-PDF emails are
    DELIBERATELY NOT migrated yet -- still on the old relay until this
    path proves stable over real use.
    """
    from azure.communication.email import EmailClient
    from azure.core.exceptions import HttpResponseError

    connection_string = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING")
    if not connection_string:
        logger.error("AZURE_COMMUNICATION_CONNECTION_STRING not set -- cannot send invite email")
        return False

    plain_fallback = re.sub("<[^<]+?>", "", html_body)
    plain_fallback = re.sub(r"\\n\\s*\\n+", "\\n\\n", plain_fallback).strip()

    message = {
        "content": {"subject": subject, "plainText": plain_fallback, "html": html_body},
        "recipients": {"to": [{"address": recipient_email}]},
        "senderAddress": AZURE_INVITE_SENDER_ADDRESS,
    }

    try:
        client = EmailClient.from_connection_string(connection_string)
        poller = client.begin_send(message)
        result = poller.result()
        if result["status"] == "Succeeded":
            logger.info(f"Invite email sent via Azure to {recipient_email} (id: {result['id']})")
            return True
        logger.error(f"Azure email send did not succeed for {recipient_email}: {result.get('error')}")
        return False
    except HttpResponseError as e:
        logger.error(f"Azure HttpResponseError sending invite email to {recipient_email}: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending invite email via Azure to {recipient_email}: {str(e)}")
        return False


'''

    shutil.copy(path, path + ".bak_azure_email_migration")
    new_lines = lines[:start_idx] + [new_function] + lines[end_idx:]
    with open(path, "w") as f:
        f.writelines(new_lines)
    print("Patched email_service.py (backup at email_service.py.bak_azure_email_migration)")
