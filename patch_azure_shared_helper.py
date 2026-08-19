import shutil

path = "app/utils/email_service.py"
with open(path) as f:
    content = f.read()

marker = "AZURE_INVITE_SENDER_ADDRESS = \"DoNotReply@81e374c8-c1f6-4ca1-bf01-f50362e6b216.azurecomm.net\"\n"

if content.count(marker) != 1:
    print(f"WARNING: expected exactly 1 match for the sender-address marker, found {content.count(marker)}. No edit made.")
elif "def send_via_azure_email" in content:
    print("send_via_azure_email already exists -- skipping, no edit made.")
else:
    addition = '''

def send_via_azure_email(recipient_email, subject, html_body, plain_text=None, attachments=None):
    """
    Generic Azure Communication Services sender, added 2026-08-09 while
    migrating login OTP, password reset, and signed-LOI-PDF emails off
    the crackerjacktech.com relay (permanent MailChannels [ESA] abuse
    block found the previous night, confirmed via raw SMTP debug tests
    and hundreds of unread bounce notices). send_invite_email() has its
    own separate, already-proven implementation and is deliberately
    left untouched rather than refactored to share this helper.
    attachments, if given, must already be a list of dicts matching
    Azure's format: {"name": ..., "contentType": ..., "contentInBase64": ...}
    """
    from azure.communication.email import EmailClient
    from azure.core.exceptions import HttpResponseError

    connection_string = os.getenv("AZURE_COMMUNICATION_CONNECTION_STRING")
    if not connection_string:
        logger.error("AZURE_COMMUNICATION_CONNECTION_STRING not set -- cannot send email")
        return False

    if plain_text is None:
        plain_text = re.sub("<[^<]+?>", "", html_body)
        plain_text = re.sub(r"\\n\\s*\\n+", "\\n\\n", plain_text).strip()

    message = {
        "content": {"subject": subject, "plainText": plain_text, "html": html_body},
        "recipients": {"to": [{"address": recipient_email}]},
        "senderAddress": AZURE_INVITE_SENDER_ADDRESS,
    }
    if attachments:
        message["attachments"] = attachments

    try:
        client = EmailClient.from_connection_string(connection_string)
        poller = client.begin_send(message)
        result = poller.result()
        if result["status"] == "Succeeded":
            logger.info(f"Email sent via Azure to {recipient_email} (id: {result['id']})")
            return True
        logger.error(f"Azure email send did not succeed for {recipient_email}: {result.get('error')}")
        return False
    except HttpResponseError as e:
        logger.error(f"Azure HttpResponseError sending email to {recipient_email}: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email via Azure to {recipient_email}: {str(e)}")
        return False
'''
    shutil.copy(path, path + ".bak_azure_shared_helper")
    content = content.replace(marker, marker + addition, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Added send_via_azure_email() to email_service.py (backup at email_service.py.bak_azure_shared_helper)")
