import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import current_app

sender_email = current_app.config['MAIL_USERNAME']
sender_password = current_app.config['MAIL_PASSWORD']
server_host = current_app.config['MAIL_SERVER']
server_port = current_app.config['MAIL_PORT']
use_tls = current_app.config.get('MAIL_USE_TLS', False)

print("Connecting to:", server_host, server_port, "TLS:", use_tls)

msg = MIMEMultipart('alternative')
msg['From'] = f"CompliFyre <{sender_email}>"
msg['To'] = "shubs0602@gmail.com"
msg['Subject'] = "Verbose SMTP debug test"
msg.attach(MIMEText("Plain text body for debug test", 'plain'))
msg.attach(MIMEText("<p>HTML body for debug test</p>", 'html'))

server = smtplib.SMTP(server_host, server_port)
server.set_debuglevel(2)
if use_tls:
    server.starttls()
server.login(sender_email, sender_password)
result = server.send_message(msg)
print("send_message() return value (empty dict = fully accepted):", result)
server.quit()
print("DONE")
