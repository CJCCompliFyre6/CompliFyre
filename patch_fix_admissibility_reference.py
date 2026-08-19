#!/usr/bin/env python3
"""
Patch: Fix AttributeError-causing reference to ecr.admissibility in the
"Evidence Quality by Clause" chart data computation in app/routes/re/view.py.

Bug: EveControlResult has no 'admissibility' column (confirmed via model
inspection -- that field exists on a different model entirely). This line
would raise AttributeError the moment a real EveAssuranceState row was
found (eas truthy), which -- like the project_control_activity_id join bug
fixed earlier -- was silently swallowed by the surrounding broad
try/except, resetting both bubble_data and evidence_quality_data to empty.

Fix: drop the nonexistent field reference and default to 'NOT_EVALUATED'
without touching ecr.admissibility. This is a safe placeholder until/unless
a real admissibility signal is wired up for this model.

Usage:
    python3 patch_fix_admissibility_reference.py --dry-run
    python3 patch_fix_admissibility_reference.py --apply
    python3 patch_fix_admissibility_reference.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_admissibility_ref")

OLD_BLOCK = """                        if eas:
                            quality_entries.append({
                                'score': eas.evidence_quality_score or 0,
                                'admissibility': ecr.admissibility or 'NOT_EVALUATED',
                            })"""

NEW_BLOCK = """                        if eas:
                            # NOTE: EveControlResult has no 'admissibility' column --
                            # that field does not exist on this model. The old
                            # reference to ecr.admissibility always raised
                            # AttributeError here, silently swallowed by the outer
                            # try/except. Defaulting to 'NOT_EVALUATED' until a real
                            # admissibility signal is wired up for this model.
                            quality_entries.append({
                                'score': eas.evidence_quality_score or 0,
                                'admissibility': 'NOT_EVALUATED',
                            })"""


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
