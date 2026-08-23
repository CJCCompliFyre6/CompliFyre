import shutil

path = "app/models/user.py"
with open(path) as f:
    content = f.read()

anchor = "    # +++ ADDED FOR NEW FEATURES +++"
count = content.count(anchor)
print(f"Anchor '# +++ ADDED FOR NEW FEATURES +++' occurs {count} time(s)")

if count != 1:
    print("WARNING: anchor not unique. No edit made.")
else:
    insertion = '''    invite_id = db.Column(db.BigInteger, nullable=True)
    designation = db.Column(db.String(100), nullable=True)
'''
    shutil.copy(path, path + ".bak_pre_loi_user_columns_v2")
    pos = content.find(anchor)
    new_content = content[:pos] + insertion + content[pos:]
    with open(path, "w") as f:
        f.write(new_content)
    print("Patched user.py (backup at user.py.bak_pre_loi_user_columns_v2)")
