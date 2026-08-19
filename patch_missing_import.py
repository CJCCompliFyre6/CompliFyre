import shutil

path = "app/routes/re/view.py"
with open(path) as f:
    content = f.read()

if "from app.models.loi import InvitePreloadGuidelines" in content:
    print("Import already present -- no edit made.")
else:
    old_import = "from app.models.re import RegulatoryBodies, RegulatoryDocuments\n"
    count = content.count(old_import)
    print(f"Anchor import line occurs {count} time(s)")
    if count != 1:
        print("WARNING: anchor not unique. No edit made.")
    else:
        new_import = old_import + "from app.models.loi import InvitePreloadGuidelines\n"
        shutil.copy(path, path + ".bak_pre_missing_import_fix")
        content = content.replace(old_import, new_import, 1)
        with open(path, "w") as f:
            f.write(content)
        print("Patched re/view.py -- added the missing import (backup at view.py.bak_pre_missing_import_fix)")
