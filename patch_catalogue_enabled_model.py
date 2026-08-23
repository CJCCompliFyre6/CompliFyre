import shutil

path = "app/models/ai.py"
with open(path) as f:
    content = f.read()

old = "    disabled_reason = db.Column(db.Text, nullable=True)\n    disabled_at = db.Column(db.TIMESTAMP, nullable=True)\n"
new = "    disabled_reason = db.Column(db.Text, nullable=True)\n    disabled_at = db.Column(db.TIMESTAMP, nullable=True)\n    catalogue_enabled = db.Column(db.Boolean, nullable=False, default=False)\n"

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_pre_catalogue_enabled")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched ai.py (backup at ai.py.bak_pre_catalogue_enabled)")
