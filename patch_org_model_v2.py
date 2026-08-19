import shutil

path = "app/models/organization.py"
with open(path) as f:
    content = f.read()

anchor = "    projects = db.relationship("
count = content.count(anchor)
print(f"Anchor 'projects = db.relationship(' occurs {count} time(s)")

if count != 1:
    print("WARNING: anchor not unique. No edit made.")
else:
    insertion = '''    # +++ ADDED FOR LOI CAPTURE SUBSYSTEM +++
    entity_type = db.Column(db.String(100), nullable=True)
    cin = db.Column(db.String(50), nullable=True)
    registered_address = db.Column(db.Text, nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    loi_required = db.Column(db.Boolean, nullable=False, default=True)
    loi_status = db.Column(db.String(50), nullable=False, default="NOT_REQUIRED")
    loi_signed_at = db.Column(db.TIMESTAMP, nullable=True)
    loi_signature_id = db.Column(db.BigInteger, nullable=True)
    temp_access_expires_at = db.Column(db.TIMESTAMP, nullable=True)
'''
    shutil.copy(path, path + ".bak_pre_loi_org_columns_v2")
    pos = content.find(anchor)
    new_content = content[:pos] + insertion + content[pos:]
    with open(path, "w") as f:
        f.write(new_content)
    print("Patched organization.py (backup at organization.py.bak_pre_loi_org_columns_v2)")
