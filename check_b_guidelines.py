from app.models.user import Users
from app.models.loi import SignupInvites, InvitePreloadGuidelines

TARGET_EMAIL = "YOUR_ACTUAL_FORWARDED_EMAIL_HERE"

b = Users.query.filter_by(email=TARGET_EMAIL).first()
print("Users row found:", b is not None)

child_invite = SignupInvites.query.filter_by(email=TARGET_EMAIL).order_by(SignupInvites.id.desc()).first()
print("SignupInvites row found:", child_invite is not None)
print("invite id / parent_invite_id / status:", child_invite.id if child_invite else None, "/", child_invite.parent_invite_id if child_invite else None, "/", child_invite.status if child_invite else None)

invite_id_to_check = b.invite_id if b else (child_invite.id if child_invite else None)
guideline_rows = InvitePreloadGuidelines.query.filter_by(invite_id=invite_id_to_check).all() if invite_id_to_check else []
print("preloaded guideline_ids for this invite:", [g.guideline_id for g in guideline_rows])

print("organization_id (if activated):", b.organization_id if b else "not activated yet")
print("DONE")
