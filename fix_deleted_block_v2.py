import shutil

path = "app/utils/email_service.py"
backup_path = "app/utils/email_service.py.bak_azure_signed_pdf_migration"

with open(backup_path) as f:
    backup_content = f.read()

start_marker = "from string import Template\n"
end_marker = '</html>"""\n'

start_pos = backup_content.find(start_marker)
end_pos = backup_content.find(end_marker, start_pos)
end_pos = end_pos + len(end_marker)
recovered_block = backup_content[start_pos:end_pos]

print(f"Recovered block length: {len(recovered_block)} chars, from real backup")

with open(path) as f:
    current_content = f.read()

marker_in_current = "        attachments=attachments,\n    )\n\n\n"

if current_content.count(marker_in_current) != 1:
    print(f"WARNING: expected exactly 1 match for insertion marker, found {current_content.count(marker_in_current)}. No edit made -- need manual review.")
else:
    shutil.copy(path, path + ".bak_before_recovery_fix_v2")
    new_content = current_content.replace(marker_in_current, marker_in_current + recovered_block + "\n\n", 1)
    with open(path, "w") as f:
        f.write(new_content)
    print("RECOVERED (unconditional this time): re-inserted the deleted block (backup at email_service.py.bak_before_recovery_fix_v2)")
