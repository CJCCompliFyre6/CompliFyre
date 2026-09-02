import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app
from email.mime.base import MIMEBase
from email import encoders
import os

logger = logging.getLogger(__name__)


def send_contact_credentials_email(
    contact_email, contact_name, organization_name, login_url, temp_password
):
    """
    Send login credentials to organization contact person with better error handling
    """
    try:
        # Email configuration from app config
        smtp_server = current_app.config.get("MAIL_SERVER")
        smtp_port = current_app.config.get("MAIL_PORT", 587)
        sender_email = current_app.config.get("MAIL_USERNAME")
        sender_password = current_app.config.get("MAIL_PASSWORD")
        use_tls = current_app.config.get("MAIL_USE_TLS", False)
        use_ssl = current_app.config.get("MAIL_USE_SSL", False)

        # Validate configuration
        if not all([smtp_server, smtp_port, sender_email, sender_password]):
            logger.error(
                "Email configuration missing. Check MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD"
            )
            return False

        logger.info(
            f"Attempting to send email to {contact_email} via {smtp_server}:{smtp_port}"
        )
        logger.info(f"TLS: {use_tls}, SSL: {use_ssl}")

        # Create message with better headers
        message = MIMEMultipart("alternative")
        message["Subject"] = (
            f"Your Complifyre Account Credentials - {organization_name}"
        )
        message["From"] = f"Complifyre <{sender_email}>"
        message["To"] = contact_email
        message["Reply-To"] = sender_email
        message["X-Priority"] = "1"  # High priority
        message["X-Mailer"] = "Complifyre Platform"
        message["List-Unsubscribe"] = f"<mailto:{sender_email}?subject=Unsubscribe>"

        # Create HTML content
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Your Complifyre Account Credentials</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 20px; background-color: #f6f9fc;">
            <div style="max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1);">
                <div style="text-align: center; margin-bottom: 30px; border-bottom: 2px solid #2c5aa0; padding-bottom: 20px;">
                    <h1 style="color: #2c5aa0; margin: 0 0 10px 0;">Complifyre</h1>
                    <p style="color: #666; font-size: 16px; margin: 0;">Compliance Management System</p>
                </div>
                
                <h2 style="color: #2c5aa0; margin-top: 0;">Welcome to Complifyre!</h2>
                <p>Dear <strong style="color: #2c5aa0;">{contact_name}</strong>,</p>
                
                <p>You have been added as a contact person for <strong style="color: #2c5aa0;">{organization_name}</strong> on the Complifyre Platform.</p>
                
                <div style="background-color: #f8f9fa; padding: 25px; border-left: 4px solid #2c5aa0; border-radius: 5px; margin: 25px 0;">
                    <h3 style="color: #2c5aa0; margin-top: 0;">Your Login Credentials</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; width: 120px;"><strong>Email:</strong></td>
                            <td style="padding: 8px 0;">{contact_email}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Temporary Password:</strong></td>
                            <td style="padding: 8px 0;">
                                <code style="background: #f1f1f1; padding: 8px 12px; border-radius: 4px; font-size: 16px; font-weight: bold; font-family: monospace; display: inline-block;">
                                    {temp_password}
                                </code>
                            </td>
                        </tr>
                    </table>
                    <div style="margin-top: 20px; text-align: center;">
                        <a href="{login_url}" style="background-color: #2c5aa0; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                            Click here to login
                        </a>
                    </div>
                    <p style="text-align: center; margin-top: 10px; font-size: 12px; color: #666;">
                        Or copy this URL: {login_url}
                    </p>
                </div>
                
                <div style="background-color: #fff3cd; padding: 15px; border: 1px solid #ffeaa7; border-radius: 5px; margin: 20px 0;">
                    <p style="color: #856404; margin: 0;">
                        <strong>🔒 Important Security Notice:</strong> 
                        Please change your password immediately after your first login for security reasons.
                    </p>
                </div>
                
                <p>If you have any questions or need assistance, please contact your organization's administrator or reply to this email.</p>
                
                <div style="margin-top: 30px; padding-top: 20px; border-top: 1px solid #eee; text-align: center;">
                    <p style="color: #666; font-size: 14px; margin: 0;">
                        Best regards,<br>
                        <strong>The Complifyre Team</strong>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """

        # Create plain text version
        text = f"""Welcome to Complifyre!

Dear {contact_name},

You have been added as a contact person for {organization_name} on Complifyre Platform.

YOUR LOGIN CREDENTIALS:
Email: {contact_email}
Temporary Password: {temp_password}
Login URL: {login_url}

IMPORTANT SECURITY NOTICE: Please change your password immediately after your first login for security reasons.

If you have any questions or need assistance, please contact your organization's administrator.

Best regards,
The Complifyre Team
"""

        # Add both HTML and plain text parts
        message.attach(MIMEText(text, "plain"))
        message.attach(MIMEText(html, "html"))

        # Send email
        logger.info(f"Connecting to SMTP server: {smtp_server}:{smtp_port}")

        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=5)
            logger.info("Using SSL connection")
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=5)
            server.set_debuglevel(1)

            if use_tls:
                logger.info("Starting TLS...")
                server.starttls()
            else:
                logger.info("Using plain connection (no TLS)")

        logger.info(f"Logging in as: {sender_email}")
        server.login(sender_email, sender_password)

        logger.info(f"Sending email to: {contact_email}")
        server.send_message(message)

        logger.info("Email sent successfully, quitting server...")
        server.quit()

        logger.info(f"✅ Credentials email sent successfully to {contact_email}")
        logger.info(f"📧 Message ID: (check server logs for actual ID)")

        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP Authentication failed: {str(e)}")
        return False

    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP error occurred: {str(e)}")
        return False

    except Exception as e:
        logger.error(
            f"❌ Failed to send email to {contact_email}: {str(e)}", exc_info=True
        )
        return False



def send_guideline_request_email(guideline_request):
    """Send email notification for new guideline request via ACS (migrated from blocked SMTP relay)"""

    user = guideline_request.user
    if not user:
        logger.error("No user found for guideline request")
        return False

    recipient_email = "complifyre2fa@gmail.com"  # Internal team notification
    
    # Create message
    msg = MIMEMultipart()
    msg['From'] = f"ComplifyRe System <{sender_email}>"
    msg['Reply-To'] = user.email  # Important: replies go to auditor
    msg['To'] = recipient_email
    msg['Subject'] = f"Guideline Request from {user.name} "
    
    # Email body with clear auditor contact info
    body = f"""
    GUIDELINE REQUEST SUBMITTED
    
    ====================================
    REQUEST DETAILS
    ====================================
    Guideline Name: {guideline_request.guideline_name}
    Regulator/Authority: {guideline_request.regulator_name}
    Web Link: {guideline_request.web_link or 'Not provided'}
    
    ====================================
    REQUESTED BY (AUDITOR)
    ====================================
    Name: {user.name}
    Email: {user.email}
    Phone: {getattr(user, 'phone_no', 'Not provided')}
    
    
    ====================================
    TECHNICAL DETAILS
    ====================================
    
    Submitted: {guideline_request.created_at.strftime('%Y-%m-%d %H:%M:%S')}
    Attachment: {'Attached' if guideline_request.attachment_path else 'None'}
    
    ====================================
    ACTION REQUIRED
    ====================================
    Please review this guideline request and:
    1. Add the guideline to the system if available
    2. Contact the auditor if more information is needed
    3. Update the request status in the system
    
    ---
    This is an automated message from ComplifyRe System.
    """
    
    msg.attach(MIMEText(body, 'plain'))
    
    # Attach file if exists
    if guideline_request.attachment_path and os.path.exists(guideline_request.attachment_path):
        with open(guideline_request.attachment_path, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            
            filename = os.path.basename(guideline_request.attachment_path)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={filename}",
            )
            msg.attach(part)
    
    # Send via ACS (SMTP relay permanently blocked — migrated to ACS)
    html_body = f"""
    <h2>Guideline Request Submitted</h2>
    <h3>Request Details</h3>
    <p><b>Guideline Name:</b> {guideline_request.guideline_name}</p>
    <p><b>Regulator/Authority:</b> {guideline_request.regulator_name}</p>
    <p><b>Web Link:</b> {guideline_request.web_link or 'Not provided'}</p>
    <h3>Requested By</h3>
    <p><b>Name:</b> {user.name}</p>
    <p><b>Email:</b> {user.email}</p>
    <p><b>Phone:</b> {getattr(user, 'phone_no', 'Not provided')}</p>
    <h3>Technical Details</h3>
    <p><b>Submitted:</b> {guideline_request.created_at.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p><b>Attachment:</b> {'Attached' if guideline_request.attachment_path else 'None'}</p>
    <p><i>Please review and add the guideline to the system if available.</i></p>
    """
    result = send_via_azure_email(
        recipient_email=recipient_email,
        subject=f"Guideline Request from {user.name}",
        html_body=html_body,
    )
    if result:
        logger.info(f"Guideline request email sent via ACS for request ID: {guideline_request.id}")
        return True
    else:
        logger.error(f"ACS failed to send guideline request email for request ID: {guideline_request.id}")
        return False


def send_loi_signed_pdf_email(recipient_email, subject, body_text, pdf_bytes, pdf_filename):
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


from string import Template
import re
from app.models.loi import EditableContent

DEFAULT_INVITE_SUBJECT = "$entity_name, your CompliFyre workspace is ready \u2014 start your 14-day free trial"

DEFAULT_INVITE_BODY = """<!DOCTYPE html>
<html>
<body style="margin:0; padding:0; background-color:#f4f4f2; font-family:Arial, Helvetica, sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f2; padding:32px 16px;">
  <tr>
    <td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px; background-color:#ffffff; border-radius:8px; overflow:hidden;">
        <tr>
          <td style="background-color:#1c1c1c; padding:28px 40px;">
            <span style="color:#ffffff; font-size:20px; font-weight:bold; letter-spacing:0.5px;">CompliFyre</span>
          </td>
        </tr>
        <tr>
          <td style="padding:40px;">
            <p style="margin:0 0 20px; font-size:15px; color:#1c1c1c;">Hi $contact_name,</p>
            <h1 style="margin:0 0 24px; font-size:23px; line-height:1.35; color:#1c1c1c; font-weight:bold;">
              $entity_name, your compliance workspace is ready.
            </h1>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 24px; background-color:#fff4ea; border-left:4px solid #f76b1c; border-radius:4px;">
              <tr>
                <td style="padding:16px 20px;">
                  <p style="margin:0; font-size:14px; line-height:1.6; color:#7a3a12;">
                    We&#39;ve already pre-loaded <strong>$guideline_count regulatory guideline(s)</strong> for $entity_name &mdash;
                    ready to explore the moment you activate your account.
                  </p>
                </td>
              </tr>
            </table>
            <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
              <tr>
                <td style="background-color:#ffa62b; border-radius:20px; padding:7px 16px;">
                  <span style="font-size:13px; font-weight:bold; color:#5c3200;">14 days free &middot; no credit card required</span>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 28px; font-size:15px; line-height:1.6; color:#3a3a3a;">
              CompliFyre turns regulatory guidelines into structured obligations and control activities automatically,
              then evaluates your evidence against them &mdash; with a human review at every step. Activate your account to
              start your 14-day trial.
            </p>
            <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 20px;">
              <tr>
                <td style="background-color:#f76b1c; border-radius:6px;">
                  <a href="$activation_link" style="display:inline-block; padding:14px 32px; font-size:15px; font-weight:bold; color:#ffffff; text-decoration:none;">
                    Activate my account &rarr;
                  </a>
                </td>
              </tr>
            </table>
            <p style="margin:0 0 28px; font-size:12px; color:#8a8a8a;">
              Button not working? Copy this link into your browser:<br>
              <span style="color:#f76b1c; word-break:break-all;">$activation_link</span>
            </p>
            <p style="margin:0; font-size:12px; color:#8a8a8a;">
              This invitation link expires on <strong>$expiry_date</strong>.
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:20px 40px; border-top:1px solid #ececec;">
            <p style="margin:0; font-size:12px; color:#a0a0a0;">
              Sent to $email &middot; CompliFyre by CAIL Pvt Ltd
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def render_invite_email_content(**tokens):
    content = EditableContent.query.get("invite_email")
    subject_template = content.subject if content and content.subject else DEFAULT_INVITE_SUBJECT
    body_template = content.body if content and content.body else DEFAULT_INVITE_BODY
    subject = Template(subject_template).safe_substitute(**tokens)
    body = Template(body_template).safe_substitute(**tokens)
    return subject, body


AZURE_INVITE_SENDER_ADDRESS = "DoNotReply@81e374c8-c1f6-4ca1-bf01-f50362e6b216.azurecomm.net"


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
        plain_text = re.sub(r"\n\s*\n+", "\n\n", plain_text).strip()

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
        result = poller.result(timeout=10)
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
    plain_fallback = re.sub(r"\n\s*\n+", "\n\n", plain_fallback).strip()

    message = {
        "content": {"subject": subject, "plainText": plain_fallback, "html": html_body},
        "recipients": {"to": [{"address": recipient_email}]},
        "senderAddress": AZURE_INVITE_SENDER_ADDRESS,
    }

    try:
        client = EmailClient.from_connection_string(connection_string)
        poller = client.begin_send(message)
        result = poller.result(timeout=10)
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


