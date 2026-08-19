import shutil

path = "app/models/user.py"
with open(path) as f:
    content = f.read()

old = '''    free_report_used = db.Column(db.Boolean, default=False)
    # +++ ADDED FOR NEW FEATURES +++'''

new = '''    free_report_used = db.Column(db.Boolean, default=False)
    invite_id = db.Column(db.BigInteger, nullable=True)
    designation = db.Column(db.String(100), nullable=True)
    # +++ ADDED FOR NEW FEATURES +++'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_pre_loi_user_columns")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched user.py (backup at user.py.bak_pre_loi_user_columns)")
