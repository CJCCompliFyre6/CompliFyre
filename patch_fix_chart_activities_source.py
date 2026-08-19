#!/usr/bin/env python3
"""
Patch: Fix root cause of empty "Findings Severity vs Recommendation
Timeline" and "Evidence Quality by Clause" charts in app/routes/re/view.py.

Bug: enriched_clauses entries (clause_obj) never carry an 'activities' key
-- the dict built for each clause only has id/clause/clause_status_info/
assessment_status/assessment_status_info/representative_activity/
activities_count/old_clause_status. No 'activities' list is stored on it.

Both chart-building loops did:
    for clause_data in enriched_clauses:
        ...
        for pca in clause_data.get('activities', []):

Since 'activities' is never a real key on these dicts, .get('activities', [])
always silently returned [] -- so the outer loop body never executed a
single iteration, for any clause, on any project. This made the two
.get('project_control_activities', []) calls further downstream irrelevant
(they were never reached), and made the try/except's silent swallowing of
earlier bugs (the join bug, the admissibility bug) moot -- none of them
were ever actually being hit, because this loop never ran.

The real per-clause activities list (with working ORM relationships,
confirmed via project_control_activities) lives in
unique_clauses[clause_id]["activities"], set earlier in the same function.

Fix: look up the real activities list from unique_clauses instead of the
nonexistent key on clause_data, and access project_control_activities as
a proper ORM relationship (not dict .get()) since each entry is a
ProjectComplianceActivity object, not a dict.

Usage:
    python3 patch_fix_chart_activities_source.py --dry-run
    python3 patch_fix_chart_activities_source.py --apply
    python3 patch_fix_chart_activities_source.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_chart_activities_source")

OLD_BLOCK_1 = """                for pca in clause_data.get('activities', []):
                    if not pca.get('applicability'):
                        continue
                    ctrl_activities = pca.get('project_control_activities', [])
                    for ctrl in ctrl_activities:"""

NEW_BLOCK_1 = """                # NOTE: clause_data (from enriched_clauses) never carries an
                # 'activities' key -- the real per-clause activities list lives
                # in unique_clauses[clause_id]["activities"], with proper ORM
                # objects (not dicts). The old .get('activities', []) always
                # silently returned [], so this loop never ran for any clause.
                for pca in unique_clauses.get(clause_id, {}).get('activities', []):
                    if not pca.applicability:
                        continue
                    ctrl_activities = pca.project_control_activities
                    for ctrl in ctrl_activities:"""

OLD_BLOCK_2 = """                for pca in clause_data.get('activities', []):
                    if not pca.get('applicability'):
                        continue
                    for ctrl in pca.get('project_control_activities', []):"""

NEW_BLOCK_2 = """                # NOTE: see matching fix above -- clause_data has no 'activities'
                # key; use the real list from unique_clauses, with ORM attribute
                # access since entries are ProjectComplianceActivity objects.
                for pca in unique_clauses.get(clause_id, {}).get('activities', []):
                    if not pca.applicability:
                        continue
                    for ctrl in pca.project_control_activities:"""


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

    already_1 = NEW_BLOCK_1 in content
    already_2 = NEW_BLOCK_2 in content
    if already_1 and already_2:
        print("Patch already applied. Nothing to do.")
        return

    problems = []
    if not already_1 and content.count(OLD_BLOCK_1) != 1:
        problems.append(f"OLD_BLOCK_1 matched {content.count(OLD_BLOCK_1)} times (expected 1)")
    if not already_2 and content.count(OLD_BLOCK_2) != 1:
        problems.append(f"OLD_BLOCK_2 matched {content.count(OLD_BLOCK_2)} times (expected 1)")
    if problems:
        print("ERROR: " + "; ".join(problems) + ". Aborting for safety.")
        sys.exit(1)

    patched = content
    if not already_1:
        patched = patched.replace(OLD_BLOCK_1, NEW_BLOCK_1)
    if not already_2:
        patched = patched.replace(OLD_BLOCK_2, NEW_BLOCK_2)

    if args.dry_run:
        print("=== DRY RUN: would replace block 1 ===")
        print(OLD_BLOCK_1)
        print("=== WITH ===")
        print(NEW_BLOCK_1)
        print("\n=== DRY RUN: would replace block 2 ===")
        print(OLD_BLOCK_2)
        print("=== WITH ===")
        print(NEW_BLOCK_2)
        print("\n(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nNext step: stop+start (not just restart) complifyre-staging.service.")


if __name__ == "__main__":
    main()
