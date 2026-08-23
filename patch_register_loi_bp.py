import shutil

path = "app/__init__.py"
with open(path) as f:
    content = f.read()

old_import = "    from app.routes.main import main_bp\n    from app.routes.notifications import notifications_bp\n"
new_import = "    from app.routes.main import main_bp\n    from app.routes.notifications import notifications_bp\n    from app.routes.loi.view import loi_bp\n"

old_register = '    app.register_blueprint(main_bp)\n'
new_register = '    app.register_blueprint(main_bp)\n    app.register_blueprint(loi_bp, url_prefix="/loi")\n'

checks = [
    ("import block", content.count(old_import)),
    ("register block", content.count(old_register)),
]
missing = [name for name, count in checks if count != 1]

if missing:
    print(f"WARNING: exact-match failed for: {missing}. Counts were: {checks}. No edit made.")
else:
    shutil.copy(path, path + ".bak_loi_bp_registration")
    content = content.replace(old_import, new_import, 1)
    content = content.replace(old_register, new_register, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched app/__init__.py (backup at __init__.py.bak_loi_bp_registration)")
