from app.models.loi import SignupInvites
from app.models.user import Users

invites = SignupInvites.query.filter_by(email='complifyre@gmail.com').order_by(SignupInvites.id.desc()).all()
for i in invites:
    print('INVITE id:', i.id, '| status:', i.status, '| parent_invite_id:', i.parent_invite_id, '| expires_at:', i.expires_at)

u = Users.query.filter_by(email='complifyre@gmail.com').first()
print('USER row exists:', u is not None)
if u:
    print('user status:', u.status, '| has password_hash:', bool(u.password_hash), '| tfa_enabled:', u.tfa_enabled)

print('DONE')
