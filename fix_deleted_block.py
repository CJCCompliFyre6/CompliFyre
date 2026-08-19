path = "app/utils/email_service.py"
backup_path = "app/utils/email_service.py.bak_azure_signed_pdf_migration"

with open(backup_path) as f:
    backup_content = f.read()

start_marker = "from string import Template\n"
end_marker = '</html>"""\n'

start_pos = backup_content.find(start_marker)
if start_pos == -1:
    print("WARNING: could not find start_marker in backup. Aborting, no changes made.")
else:
    end_pos = backup_content.find(end_marker, start_pos)
    if end_pos == -1:
        print("WARNING: could not find end_marker in backup. Aborting, no changes made.")
    else:
        end_pos = end_pos + len(end_marker)
        recovered_block = backup_content[start_pos:end_pos]
        print(f"Recovered block length: {len(recovered_block)} chars")
        print("--- First line ---")
        print(repr(recovered_block.split(chr(10))[0]))
        print("--- Last line ---")
        print(repr(recovered_block.rstrip(chr(10)).split(chr(10))[-1]))

        with open(path) as f:
            current_content = f.read()

        if "DEFAULT_INVITE_BODY" in current_content:
            print("DEFAULT_INVITE_BODY already present in current file -- nothing to recover, no changes made.")
        else:
            marker_in_current = "        attachments=attachments,\n    )\n\n\n"
            if current_content.count(marker_in_current) != 1:
                print(f"WARNING: expected exactly 1 match for insertion marker, found {current_content.count(marker_in_current)}. No edit made -- need manual review.")
            else:
                import shutil
                shutil.copy(path, path + ".bak_before_recovery_fix")
                new_content = current_content.replace(marker_in_current, marker_in_current + recovered_block + "\n\n", 1)
                with open(path, "w") as f:
                    f.write(new_content)
                print("RECOVERED: re-inserted the deleted block into email_service.py (backup at email_service.py.bak_before_recovery_fix)")
