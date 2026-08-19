import shutil

path = "app/templates/dashboards/loi/loi_show.html"
with open(path) as f:
    content = f.read()

old = '<input type="text" name="signer_name" required class="w-full border rounded-lg p-2 mb-4">'
new = '<input type="text" name="signer_name" value="{{ current_user.name }}" readonly required class="w-full border rounded-lg p-2 mb-4 bg-gray-100 cursor-not-allowed">'

if content.count(old) != 1:
    print(f"WARNING: expected exactly 1 match, found {content.count(old)}. No edit made.")
else:
    shutil.copy(path, path + ".bak_signer_name_lock")
    content = content.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(content)
    print("Patched loi_show.html (backup at loi_show.html.bak_signer_name_lock)")
