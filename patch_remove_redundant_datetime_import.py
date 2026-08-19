#!/usr/bin/env python3
"""
Patch: Remove redundant local 'from datetime import datetime' inside the
activity() view function in app/routes/re/view.py.

Bug: datetime is already imported at module level (line 32: 'from datetime
import datetime'). A second, local import of the same name later in the
same function (around the 'current_time = datetime.now()' line) makes
Python treat 'datetime' as a local variable for the ENTIRE function body --
including earlier lines like 'assessment_end_date = datetime.now().date()'
that run before the local import statement is reached. This raises:
    UnboundLocalError: cannot access local variable 'datetime' where it is
    not associated with a value

This bug was dormant: it only fires when execution reaches the
'if all_clauses_completed:' branch that calls datetime.now().date() before
the local import line. Before we fixed the all_clauses_completed
applicability bug, that branch was never reached (all_clauses_completed was
always False), so this was never triggered. Fixing that bug exposed this
pre-existing, unrelated one.

Fix: remove the redundant local import; the module-level import already
covers this scope.

Usage:
    python3 patch_remove_redundant_datetime_import.py --dry-run
    python3 patch_remove_redundant_datetime_import.py --apply
    python3 patch_remove_redundant_datetime_import.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_datetime_shadow")

OLD_BLOCK = """        from datetime import datetime
        current_time = datetime.now()"""

NEW_BLOCK = """        # NOTE: datetime is already imported at module level (see top of file).
        # A local re-import here previously shadowed it for this entire function,
        # causing UnboundLocalError on earlier datetime.now() calls in this
        # function (e.g. assessment_end_date calculation above).
        current_time = datetime.now()"""


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
