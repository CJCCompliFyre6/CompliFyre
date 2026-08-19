path = "app/utils/email_service.py"
with open(path) as f:
    content = f.read()

if "def send_invite_email" in content:
    print("Already patched, skipping.")
else:
    import shutil
    shutil.copy(path, path + ".bak_invite_email_feature")

    addition = '''

from string import Template
import re
from app.models.loi import EditableContent

DEFAULT_INVITE_SUBJECT = "$entity_name, your CompliFyre workspace is ready \\u2014 start your 14-day free trial"

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


def send_invite_email(recipient_email, subject, html_body):
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
        return False
'''
    with open(path, "a") as f:
        f.write(addition)
    print("Patched email_service.py (backup at email_service.py.bak_invite_email_feature)")
