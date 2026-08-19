import shutil

path = "app/models/organization.py"
with open(path) as f:
    content = f.read()

anchor = "    projects = db.relationship("
first_pos = content.find(anchor)

# Verify this first occurrence genuinely falls within the Organizations class,
# not some other class -- confirm "class Organizations(" appears before it,
# and no other "class " definition appears between that and this anchor.
org_class_pos = content.find("class Organizations(")
if org_class_pos == -1 or org_class_pos > first_pos:
    print("WARNING: could not confirm 'class Organizations(' precedes the anchor. No edit made.")
else:
    between = content[org_class_pos + len("class Organizations("):first_pos]
    if "\nclass " in between:
        print("WARNING: another class definition appears between Organizations and the anchor -- first occurrence does NOT belong to Organizations. No edit made.")
    else:
        print(f"Confirmed: first 'projects = db.relationship(' at position {first_pos} genuinely belongs to the Organizations class.")
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
        shutil.copy(path, path + ".bak_pre_loi_org_columns_v3")
        new_content = content[:first_pos] + insertion + content[first_pos:]
        with open(path, "w") as f:
            f.write(new_content)
        print("Patched organization.py (backup at organization.py.bak_pre_loi_org_columns_v3)")
