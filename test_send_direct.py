from app.utils.email_service import send_invite_email, render_invite_email_content
import traceback

try:
    subject, html_body = render_invite_email_content(
        contact_name="Direct Test",
        entity_name="Test Org",
        guideline_count=2,
        activation_link="https://staging.complifyre.in/loi/activate/test",
        expiry_date="20 August 2026",
        email="shubs0602@gmail.com",
    )
    print("RENDER OK, subject:", subject)
    result = send_invite_email("shubs0602@gmail.com", subject, html_body)
    print("SEND RESULT:", result)
except Exception as e:
    print("EXCEPTION TYPE:", type(e).__name__)
    print("EXCEPTION MSG:", str(e))
    traceback.print_exc()

print("DONE")
