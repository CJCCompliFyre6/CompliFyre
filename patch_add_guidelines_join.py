#!/usr/bin/env python3
"""
Patch: Extend the tracked_guidelines() query with an outer join to
Guidelines (via RegulatoryDocuments.guideline_id), so linked Tracked
Guidelines rows can show the same "Withdrawn" status as the real
Guidelines record -- one source of truth (the flag lives on the
Guidelines row), reflected consistently wherever that document
appears, rather than a second separate flag to keep in sync.

Usage:
    python3 patch_add_guidelines_join.py --dry-run
    python3 patch_add_guidelines_join.py --apply
    python3 patch_add_guidelines_join.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_guidelines_join")

ANCHOR = '''    query = (
        RegulatoryDocuments.query
        .join(RegulatoryBodies, RegulatoryDocuments.body_id == RegulatoryBodies.body_id)
        .add_columns(RegulatoryBodies.name.label("regulator_name"))
    )'''

NEW = '''    query = (
        RegulatoryDocuments.query
        .join(RegulatoryBodies, RegulatoryDocuments.body_id == RegulatoryBodies.body_id)
        .outerjoin(Guidelines, RegulatoryDocuments.guideline_id == Guidelines.id)
        .add_columns(
            RegulatoryBodies.name.label("regulator_name"),
            Guidelines.enabled.label("linked_guideline_enabled"),
            Guidelines.disabled_reason.label("linked_guideline_disabled_reason"),
        )
    )'''


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

    if "linked_guideline_enabled" in content:
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
