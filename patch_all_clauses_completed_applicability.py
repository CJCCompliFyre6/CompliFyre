#!/usr/bin/env python3
"""
Patch: Fix all_clauses_completed calculation in app/routes/re/view.py to
only consider APPLICABLE clauses (matching every other statistics loop in
this function), not every clause in the guideline.

Bug: the loop iterated over unique_clauses.values() with no applicability
filter. A guideline can have hundreds of clauses that are Not Applicable to
a given project (e.g. 434 total, 9 applicable). Non-applicable clauses
never get assessed (correctly), so their assessment_status stays
'To Be Assessed' by default -- which immediately flipped
all_clauses_completed to False the moment the loop hit one, even when all
applicable clauses were genuinely Completed. This caused the project
dashboard to show a "In Progress" badge and non-100% progress state
alongside other panels correctly showing "9/9 clauses completed" and 100%.

Fix: skip clauses where clause.applicability is not True, same as the
severity loop, evidence loop, and clause_statistics calculation already do.

Usage:
    python3 patch_all_clauses_completed_applicability.py --dry-run
    python3 patch_all_clauses_completed_applicability.py --apply
    python3 patch_all_clauses_completed_applicability.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_all_clauses_completed")

OLD_BLOCK = """        all_clauses_completed = True
        for clause_data in unique_clauses.values():
            clause = clause_data["clause"]
            # Get assessment status from the clause or from your logic
            clause_assessment_status = getattr(clause, 'assessment_status', 'To Be Assessed')
            if clause_assessment_status != "Completed":
                all_clauses_completed = False
                break"""

NEW_BLOCK = """        all_clauses_completed = True
        for clause_data in unique_clauses.values():
            clause = clause_data["clause"]
            # Only consider clauses applicable to this project -- matches the
            # filter used by the severity loop, evidence loop, and
            # clause_statistics elsewhere in this function. Non-applicable
            # clauses are never assessed and would otherwise always read as
            # incomplete, incorrectly flipping this flag to False.
            if not getattr(clause, 'applicability', False):
                continue
            # Get assessment status from the clause or from your logic
            clause_assessment_status = getattr(clause, 'assessment_status', 'To Be Assessed')
            if clause_assessment_status != "Completed":
                all_clauses_completed = False
                break"""


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
        print("\nNext step: restart complifyre-staging.service to pick up this change.")


if __name__ == "__main__":
    main()
