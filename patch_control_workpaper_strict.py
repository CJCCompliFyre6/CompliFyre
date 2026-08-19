#!/usr/bin/env python3
"""
Patch: Turn on strict=True for the ControlWorkpaper extract_structured_info
call in extract_test_procedures (app/services/manual_task.py), the specific
call site that was reliably dropping the required explain_test_procedure
field. Depends on patch_strict_structured_output.py already being applied
to app/services/model_response.py.

Usage:
    python3 patch_control_workpaper_strict.py --dry-run
    python3 patch_control_workpaper_strict.py --apply
    python3 patch_control_workpaper_strict.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "manual_task.py"
BACKUP = TARGET.with_suffix(".py.bak_control_workpaper_strict")

OLD_BLOCK = """        test_proc_response = extract_structured_info(
            query=test_procedure(clause.clause_text, _as_json(activity)),
            vector_store_id=vec_id,
            schema=ControlWorkpaper,
        )"""

NEW_BLOCK = """        test_proc_response = extract_structured_info(
            query=test_procedure(clause.clause_text, _as_json(activity)),
            vector_store_id=vec_id,
            schema=ControlWorkpaper,
            strict=True,
        )"""


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        if not BACKUP.exists():
            print(f"No backup found at {BACKUP}. Nothing to roll back.")
            sys.exit(1)
        shutil.copy2(BACKUP, TARGET)
        print(f"Rolled back {TARGET} from {BACKUP}.")
        return

    if not TARGET.exists():
        print(f"ERROR: target file not found: {TARGET}")
        sys.exit(1)

    content = TARGET.read_text()

    if NEW_BLOCK in content:
        print("Patch already applied. Nothing to do.")
        return

    if OLD_BLOCK not in content:
        print("ERROR: expected OLD_BLOCK not found verbatim in file.")
        print("The file may have changed since this script was written. Aborting.")
        sys.exit(1)

    count = content.count(OLD_BLOCK)
    if count != 1:
        print(f"ERROR: OLD_BLOCK matched {count} times (expected exactly 1). Aborting for safety.")
        sys.exit(1)

    patched = content.replace(OLD_BLOCK, NEW_BLOCK)

    if args.dry_run:
        print("=== DRY RUN: would replace ===")
        print(OLD_BLOCK)
        print("=== WITH ===")
        print(NEW_BLOCK)
        print("\n(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nRestart complifyre-staging + celery-staging, then retry activity 45893.")


if __name__ == "__main__":
    main()
