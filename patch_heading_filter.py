#!/usr/bin/env python3
"""
Patch: Fix heading_pattern_filter dropping headings styled "Chapter-X"
(hyphen directly attached, no space) in app/services/manual_task.py.

Root cause: extract_headings() correctly detects such headings (confirmed
via direct test against the real page text), but a SEPARATE, stricter
filter regex used later to build heading_list only accepts whitespace or
end-of-string immediately after the chapter/schedule/etc keyword -- a
directly-attached hyphen fails this second filter and the heading is
silently dropped, even though every other chapter in the same document
(styled "Chapter I - Preliminary", with a space) passes fine.

Confirmed via a real document: RBI (NBFC - Know Your Customer) Directions,
2025, page 56, "Chapter-X - Other Instructions" -- real, substantive
content (secrecy obligations, FCRA compliance, CDD/CKYCR sharing) that
was silently absorbed into the preceding Chapter IX's page range instead
of forming its own section.

Usage:
    python3 patch_heading_filter.py --dry-run
    python3 patch_heading_filter.py --apply
    python3 patch_heading_filter.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "manual_task.py"
BACKUP = TARGET.with_suffix(".py.bak_heading_filter")

OLD_BLOCK = r"""            r'^(CHAPTER|Chapter|SCHEDULE|Schedule|ANNEXURE|Annexure|ANNEX|Annex|APPENDIX|Appendix)(\s+|$)',"""
NEW_BLOCK = r"""            r'^(CHAPTER|Chapter|SCHEDULE|Schedule|ANNEXURE|Annexure|ANNEX|Annex|APPENDIX|Appendix)(\s+|$|[-\u2013])',"""


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
        print("\nRestart complifyre-staging + celery-staging, then regenerate the structure map")
        print("for guideline 221 and confirm Chapter X now appears as its own section.")


if __name__ == "__main__":
    main()
