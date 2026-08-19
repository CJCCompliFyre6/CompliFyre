#!/usr/bin/env python3
"""
Patch: Add last_check_status/last_checked_at/last_check_notes fields to the
RegulatoryBodies model (app/models/re.py), matching the columns already
added to the real database.

Usage:
    python3 patch_add_check_status_model.py --dry-run
    python3 patch_add_check_status_model.py --apply
    python3 patch_add_check_status_model.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "models" / "re.py"
BACKUP = TARGET.with_suffix(".py.bak_check_status_model")

ANCHOR = "    governed_institutions = db.Column(db.Text)"
NEW_FIELDS = (
    "    governed_institutions = db.Column(db.Text)\n"
    '    last_check_status = db.Column(db.String(50), nullable=False, default="NEVER_CHECKED")\n'
    "    last_checked_at = db.Column(db.TIMESTAMP)\n"
    "    last_check_notes = db.Column(db.Text)\n"
)


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

    if "last_check_status" in content:
        print("Patch already applied. Nothing to do.")
        return

    if content.count(ANCHOR) != 1:
        print(f"ERROR: anchor matched {content.count(ANCHOR)} times (expected 1). Aborting.")
        sys.exit(1)

    patched = content.replace(ANCHOR, NEW_FIELDS.rstrip("\n"))

    if args.dry_run:
        print("=== DRY RUN: would replace ===")
        print(ANCHOR)
        print("=== WITH ===")
        print(NEW_FIELDS)
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
