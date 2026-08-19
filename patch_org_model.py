import shutil

path = "app/models/organization.py"
with open(path) as f:
    content = f.read()

old = '''    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    projects = db.relationship('''

new = '''    updated_at = db.Column(
        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    # +++ ADDED FOR LOI CAPTURE SUBSYSTEM +++
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
    projects = db.relationship('''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_pre_loi_org_columns")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched organization.py (backup at organization.py.bak_pre_loi_org_columns)")
