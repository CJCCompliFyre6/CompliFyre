import shutil

path = "app/routes/loi/view.py"
with open(path) as f:
    content = f.read()

old = '''    org = Organizations.query.get(current_user.organization_id)
    pdf_bytes, _, _ = render_loi_pdf(org.name, "[Preview]", "[Preview]", datetime.now().strftime("%d %b %Y"))'''

new = '''    org = Organizations.query.get(current_user.organization_id)
    signer_name = current_user.name or "[Name not on file]"
    designation = current_user.designation or "[Designation not on file]"
    pdf_bytes, _, _ = render_loi_pdf(org.name, signer_name, designation, datetime.now().strftime("%d %b %Y"))'''

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_loi_preview_fix")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched loi/view.py (backup at view.py.bak_loi_preview_fix)")
