import shutil

path = "app/utils/email_service.py"
with open(path) as f:
    content = f.read()

old = '''def send_invite_email(recipient_email, subject, html_body):
    try:
        sender_email = current_app.config["MAIL_USERNAME"]
        sender_password = current_app.config["MAIL_PASSWORD"]
        msg = MIMEMultipart("alternative")
        msg["From"] = f"CompliFyre <{sender_email}>"
        msg["To"] = recipient_email
        msg["Subject"] = subject
        plain_fallback = re.sub("<[^<]+?>", "", html_body)
        plain_fallback = re.sub(r"\\n\\s*\\n+", "\\n\\n", plain_fallback).strip()
        msg.attach(MIMEText(plain_fallback, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        use_tls = current_app.config.get("MAIL_USE_TLS", False)
        use_ssl = current_app.config.get("MAIL_USE_SSL", False)
        if use_ssl:
            server = smtplib.SMTP_SSL(current_app.config["MAIL_SERVER"], current_app.config["MAIL_PORT"])
        else:
            server = smtplib.SMTP(current_app.config["MAIL_SERVER"], current_app.config["MAIL_PORT"])
            if use_tls:
                server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"Invite email sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send invite email to {recipient_email}: {str(e)}")
        return False'''

new = '''AZURE_INVITE_SENDER_ADDRESS = "DoNotReply@81e374c8-c1f6-4ca1-bf01-f50362e6b216.azurecomm.net"


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
        return False'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_azure_email_migration")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched email_service.py (backup at email_service.py.bak_azure_email_migration)")
