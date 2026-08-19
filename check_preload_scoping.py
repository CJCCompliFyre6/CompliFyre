from app.models.user import Users
from app.models.loi import SignupInvites, InvitePreloadGuidelines

u = Users.query.filter_by(email='shubha@globaltarush.com').first()
print('User found:', u is not None)
if u:
    print('user.invite_id:', u.invite_id)
    print('user.role_id:', u.role_id)
    print('user.auditor_profile_id:', u.auditor_profile_id)

i = SignupInvites.query.filter_by(email='shubha@globaltarush.com').order_by(SignupInvites.id.desc()).first()
print('Invite found:', i is not None)
if i:
    print('invite.id:', i.id)
    print('invite.parent_invite_id:', i.parent_invite_id)
    print('invite.status:', i.status)
    preloaded = InvitePreloadGuidelines.query.filter_by(invite_id=i.id).all()
    print('Preloaded guideline_ids for this invite:', [p.guideline_id for p in preloaded])
    print('Count:', len(preloaded))

print('DONE')
