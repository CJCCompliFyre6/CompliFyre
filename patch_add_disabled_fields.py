#!/usr/bin/env python3
"""
Patch: Add disabled_reason and disabled_at fields to the Guidelines
model, matching the columns already added to the real database.
Supports capturing WHY a guideline was disabled (e.g. "Withdrawn --
superseded by Circular X") -- the existing toggle_guideline_enabled
route already correctly disables auditor visibility, but had no way
to record a reason, and the Guidelines table had no visible indicator
of disabled/withdrawn status at all.

Usage:
    python3 patch_add_disabled_fields.py --dry-run
    python3 patch_add_disabled_fields.py --apply
    python3 patch_add_disabled_fields.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "models" / "ai.py"
BACKUP = TARGET.with_suffix(".py.bak_disabled_fields")

ANCHOR = '''    enabled = db.Column(
        db.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    applicable_licenses = db.Column(db.JSON, nullable=True)'''

NEW = '''    enabled = db.Column(
        db.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    disabled_reason = db.Column(db.Text, nullable=True)
    disabled_at = db.Column(db.TIMESTAMP, nullable=True)
    applicable_licenses = db.Column(db.JSON, nullable=True)'''


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

    if "disabled_reason = db.Column" in content:
        print("Patch already applied. Nothing to do.")
        return

    count = content.count(ANCHOR)
    if count != 1:
        print(f"ERROR: anchor matched {count} times (expected 1). Aborting.")
        sys.exit(1)

    patched = content.replace(ANCHOR, NEW)

    if args.dry_run:
        print("Anchor matched exactly once.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
