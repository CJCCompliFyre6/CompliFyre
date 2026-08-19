#!/usr/bin/env python3
"""
Patch: Fix hardcoded 0% width on the "Findings" row of the Assessment
Progress Funnel in app/templates/dashboards/auditor/my_projects_new.html.

Bug: every other row in the funnel computes its bar width as a percentage
(applicable/total_clauses*100, with_evidence/applicable*100, etc.), but the
Findings row had a literal 0 hardcoded instead of a computed percentage --
so it always showed "0%" regardless of the actual findings_count value.

Fix: compute width as findings_count / applicable * 100, consistent with
the other funnel stages (findings are scoped to applicable clauses, same
denominator as Evidence Received and Assessed).

Usage:
    python3 patch_funnel_findings_width.py --dry-run
    python3 patch_funnel_findings_width.py --apply
    python3 patch_funnel_findings_width.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = (
    Path.home() / "CompliFyre-staging" / "app" / "templates"
    / "dashboards" / "auditor" / "my_projects_new.html"
)
BACKUP = TARGET.with_suffix(".html.bak_funnel_findings")

OLD_BLOCK = """            ('Findings', findings_count, 'Total findings raised', '#DC2626', 0),"""

NEW_BLOCK = """            ('Findings', findings_count, 'Total findings raised', '#DC2626', (findings_count/applicable*100)|int if applicable > 0 else 0),"""


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
        print("\nRestart complifyre-staging.service if the change doesn't show up on refresh.")


if __name__ == "__main__":
    main()
