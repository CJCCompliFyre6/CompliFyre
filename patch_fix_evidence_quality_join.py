#!/usr/bin/env python3
"""
Patch: Fix broken EveAssuranceState lookup in app/routes/re/view.py, inside
the "Evidence Quality by Clause" chart data computation.

Bug: the code queried
    EveAssuranceState.query.filter_by(project_control_activity_id=ctrl.id)
but EveAssuranceState has NO project_control_activity_id column -- it only
has project_checklist_id, which points to ProjectChecklist.id.
ProjectChecklist in turn has project_control_activity_id. So this was a
two-hop relationship being queried as if it were direct.

This raised sqlalchemy.exc.InvalidRequestError on every call, which was
silently swallowed by the surrounding broad try/except (which resets both
bubble_data and evidence_quality_data to {} / [] and only logs a warning).
This means "Evidence Quality by Clause" has likely never populated for any
project, not just this one -- the bubble chart's failure was collateral
damage from the same except block, not a separate bug (confirmed real
CONFIRMED/CLOSED findings exist elsewhere in the DB with correct
auditor_status, so that part of the logic was fine).

Fix: look up ProjectChecklist by project_control_activity_id first, then
EveAssuranceState by that checklist's id.

Usage:
    python3 patch_fix_evidence_quality_join.py --dry-run
    python3 patch_fix_evidence_quality_join.py --apply
    python3 patch_fix_evidence_quality_join.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_evidence_quality_join")

OLD_BLOCK = """                        # Evidence quality
                        eas = EveAssuranceState.query.filter_by(
                            project_control_activity_id=ctrl.id
                        ).first()
                        if eas:"""

NEW_BLOCK = """                        # Evidence quality
                        # NOTE: EveAssuranceState has no project_control_activity_id
                        # column -- it links via project_checklist_id ->
                        # ProjectChecklist.project_control_activity_id. The old
                        # direct filter_by always raised InvalidRequestError, which
                        # was silently swallowed by the outer try/except, resetting
                        # both chart datasets to empty on every request.
                        from app.models.eve_models import ProjectChecklist
                        _checklist = ProjectChecklist.query.filter_by(
                            project_control_activity_id=ctrl.id
                        ).first()
                        eas = (
                            EveAssuranceState.query.filter_by(
                                project_checklist_id=_checklist.id
                            ).first()
                            if _checklist else None
                        )
                        if eas:"""


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
