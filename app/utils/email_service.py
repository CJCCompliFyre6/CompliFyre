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
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
            logger.info("Using SSL connection")
        else:
            server = smtplib.SMTP(smtp_server, smtp_port)
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
    """Send email notification for new guideline request"""
    
    user = guideline_request.user
    if not user:
        logger.error("No user found for guideline request")
        return False
    
    # Use system SMTP credentials
    sender_email = current_app.config['MAIL_USERNAME']  # System email
    sender_password = current_app.config['MAIL_PASSWORD']  # System password
    recipient_email = "complifyre2fa@crackerjacktech.com"  # Send to ComplifyRe
    
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
    
    # Send email
    try:
        # Configure based on .env settings
        use_tls = current_app.config.get('MAIL_USE_TLS', False)
        use_ssl = current_app.config.get('MAIL_USE_SSL', False)
        
        if use_ssl:
            server = smtplib.SMTP_SSL(
                current_app.config['MAIL_SERVER'], 
                current_app.config['MAIL_PORT']
            )
        else:
            server = smtplib.SMTP(
                current_app.config['MAIL_SERVER'], 
                current_app.config['MAIL_PORT']
            )
            if use_tls:
                server.starttls()
        
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"Guideline request email sent to ComplifyRe for request ID: {guideline_request.id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send guideline request email: {str(e)}")
        return False