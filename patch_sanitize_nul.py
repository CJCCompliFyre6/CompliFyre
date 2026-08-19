#!/usr/bin/env python3
"""
Patch: Fix a real bug found live -- SIDBI's page (and likely others)
contains NUL bytes (0x00) embedded in some extracted text, apparently
replacing spaces in part of a title due to some source-page encoding
quirk. Postgres refuses NUL bytes in string literals outright, causing
the INSERT to fail with: "ValueError: A string literal cannot contain
NUL (0x00) characters."

Confirmed the correct fix is replacing NUL with a space (not deleting
it), since deleting glues words together (e.g. "Revision\\x00of\\x00
Interest" -> "RevisionofInterest" if simply removed, vs the correct
"Revision of Interest" when replaced with a space).

Usage:
    python3 patch_sanitize_nul_bytes.py --dry-run
    python3 patch_sanitize_nul_bytes.py --apply
    python3 patch_sanitize_nul_bytes.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "check_guidelines_service.py"
BACKUP = TARGET.with_suffix(".py.bak_nul_sanitize")

ANCHOR = '''        title = (doc.get("title") or "").strip()
        url = (doc.get("url") or "").strip()'''

NEW = '''        title = (doc.get("title") or "").replace("\\x00", " ").strip()
        url = (doc.get("url") or "").replace("\\x00", " ").strip()'''


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

    if 'replace("\\x00"' in content:
        print("Patch already applied. Nothing to do.")
        return

    count = content.count(ANCHOR)
    if count != 1:
        print(f"ERROR: anchor matched {count} times (expected 1). Aborting.")
        sys.exit(1)

    patched = content.replace(ANCHOR, NEW)

    if args.dry_run:
        print("Anchor matched exactly once. Would replace:")
        print(ANCHOR)
        print("--- WITH ---")
        print(NEW)
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
