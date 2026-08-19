from app import db
from app.models.loi import EditableContent
from app.utils.email_service import DEFAULT_INVITE_SUBJECT, DEFAULT_INVITE_BODY
if not EditableContent.query.get("invite_email"):
    db.session.add(EditableContent(key="invite_email", subject=DEFAULT_INVITE_SUBJECT, body=DEFAULT_INVITE_BODY))
    db.session.commit()
    print("seeded")
else:
    print("already exists, not overwriting")
