#!/usr/bin/env python3
"""
Piece F: Fix the activity-generation race-condition.

Root cause: task_acks_late=True + Redis broker's default visibility_timeout
(1 hour) means a long-running task (like generate_missing_activities_for_guideline
processing 100+ clauses, ~90+ min observed) gets redelivered to a second
worker mid-flight, because Redis assumes the first worker died. Both workers
then process overlapping clauses and generate duplicate activities.

Fix 1 (root-cause): Raise broker_transport_options visibility_timeout to 6
hours, well above any realistic single-guideline activity-generation run,
so Redis stops prematurely redelivering in-progress tasks.

Fix 2 (defense-in-depth): Re-check immediately before processing each clause
whether it already has an activity (in case of any other overlap/retry),
and skip if so — cheap, and closes the race window even if Fix 1's margin
is ever exceeded.

Usage:
    python3 apply_piece_F_race_condition_fix.py --dry-run
    python3 apply_piece_F_race_condition_fix.py
    python3 apply_piece_F_race_condition_fix.py --rollback
"""
import argparse
import shutil
import sys
import os

PATCHES = [
    {
        "name": "F1: raise broker_transport_options visibility_timeout to 6 hours",
        "file": "celery_app.py",
        "old": """        "worker_prefetch_multiplier": 1,
        "result_extended": True,  # Enable extended result features""",
        "new": """        "worker_prefetch_multiplier": 1,
        "result_extended": True,  # Enable extended result features
        "broker_transport_options": {"visibility_timeout": 21600},  # 6 hours — task_acks_late + long-running bulk tasks (e.g. activity-generation) need this longer than Redis's 1hr default, or the broker redelivers an in-progress task to another worker""",
    },
    {
        "name": "F2: per-clause re-check before generating activity (race-condition guard)",
        "file": "app/services/manual_task.py",
        "old": """                logger.info(f"Processing clause {clause.id} ({clause.clause_no})")

                # Extract compliance activities
                activity_response = extract_structured_info(""",
        "new": """                logger.info(f"Processing clause {clause.id} ({clause.clause_no})")

                # Re-check right before processing — another worker may have
                # generated activities for this clause since the initial
                # bulk query (e.g. after a Celery broker redelivery caused
                # by visibility_timeout expiring on a long-running task).
                if ComplianceActivities.query.filter_by(clause_id=clause.id).first():
                    logger.info(f"Skipping clause {clause.id} ({clause.clause_no}) - activity already exists (race-condition guard)")
                    continue

                # Extract compliance activities
                activity_response = extract_structured_info(""",
    },
]


def rollback():
    for patch in PATCHES:
        backup = patch["file"] + ".pieceF.bak"
        if os.path.exists(backup):
            shutil.copy(backup, patch["file"])
            print(f"Rolled back: restored {patch['file']} from {backup}")
        else:
            print(f"No backup found for {patch['file']} at {backup} - skipping")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    if args.rollback:
        rollback()
        return

    file_contents = {}
    for patch in PATCHES:
        f = patch["file"]
        if f not in file_contents:
            with open(f, "r") as fh:
                file_contents[f] = fh.read()
        content = file_contents[f]
        count = content.count(patch["old"])
        if count == 0:
            print(f"ABORT - pattern not found for patch '{patch['name']}' in {f}.")
            print("Not applying ANY changes.")
            sys.exit(1)
        if count > 1:
            print(f"ABORT - pattern for patch '{patch['name']}' matches {count} times in {f} (expected exactly 1).")
            sys.exit(1)
        file_contents[f] = content.replace(patch["old"], patch["new"], 1)
        print(f"OK - patch '{patch['name']}' matched exactly once.")

    if args.dry_run:
        print("\ndry-run: all patches would apply cleanly. No files written.")
        return

    for f, content in file_contents.items():
        backup = f + ".pieceF.bak"
        shutil.copy(f, backup)
        with open(f, "w") as fh:
            fh.write(content)
        print(f"Applied changes to {f} (backup: {backup})")

    print("\nNEXT STEPS:")
    print("  1. Restart the relevant Celery worker (celery-staging.service on staging, celery.service on production)")
    print("  2. Re-run generate_missing_activities_for_guideline on a fresh guideline copy")
    print("  3. Confirm no activity_id reset pattern (no duplicates) after the run")
    print("  4. Rollback if needed: python3 apply_piece_F_race_condition_fix.py --rollback")


if __name__ == "__main__":
    main()
