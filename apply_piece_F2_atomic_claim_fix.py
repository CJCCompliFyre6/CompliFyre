#!/usr/bin/env python3
"""
Piece F2 (v2, atomic): Replaces the earlier check-then-act race-guard (which
is NOT safe against genuinely concurrent workers, as observed - two workers
checked within 10 seconds of each other and both saw the clause as
unclaimed) with a single atomic UPDATE...WHERE claim. The database itself
guarantees only one worker can successfully claim a given clause, even
under true parallel execution.

Steps:
  1. Add nullable column `activity_generation_claimed_at` (raw SQL, idempotent).
  2. Add corresponding column to the Clauses SQLAlchemy model.
  3. Replace the check-then-act guard in generate_missing_activities_for_guideline
     with an atomic claim (UPDATE...WHERE...RETURNING-equivalent via rowcount).

Usage:
    python3 apply_piece_F2_atomic_claim_fix.py --dry-run
    python3 apply_piece_F2_atomic_claim_fix.py
    python3 apply_piece_F2_atomic_claim_fix.py --rollback
"""
import argparse
import shutil
import sys
import os

SQL_ADD_COLUMN = "ALTER TABLE clauses ADD COLUMN IF NOT EXISTS activity_generation_claimed_at TIMESTAMP;"

PATCHES = [
    {
        "name": "model: add activity_generation_claimed_at column to Clauses",
        "file": "app/models/ai.py",
        "old": """    flag_reason = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())""",
        "new": """    flag_reason = db.Column(db.String(200), nullable=True)
    activity_generation_claimed_at = db.Column(db.TIMESTAMP, nullable=True)  # atomic claim marker for race-safe activity generation
    created_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())""",
    },
    {
        "name": "manual_task: replace check-then-act guard with atomic claim",
        "file": "app/services/manual_task.py",
        "old": """                logger.info(f"Processing clause {clause.id} ({clause.clause_no})")

                # Re-check right before processing — another worker may have
                # generated activities for this clause since the initial
                # bulk query (e.g. after a Celery broker redelivery caused
                # by visibility_timeout expiring on a long-running task).
                if ComplianceActivities.query.filter_by(clause_id=clause.id).first():
                    logger.info(f"Skipping clause {clause.id} ({clause.clause_no}) - activity already exists (race-condition guard)")
                    continue

                # Extract compliance activities
                activity_response = extract_structured_info(""",
        "new": """                logger.info(f"Processing clause {clause.id} ({clause.clause_no})")

                # Atomically claim this clause before processing - a single
                # UPDATE...WHERE guarantees only one worker can succeed even
                # under genuinely concurrent execution (a plain check-then-act
                # guard is not safe against true parallelism).
                from datetime import datetime, timedelta, timezone
                _now = datetime.now(timezone.utc)
                _stale_before = _now - timedelta(hours=2)
                _claimed = db.session.execute(
                    db.update(Clauses)
                    .where(
                        Clauses.id == clause.id,
                        db.or_(
                            Clauses.activity_generation_claimed_at.is_(None),
                            Clauses.activity_generation_claimed_at < _stale_before
                        )
                    )
                    .values(activity_generation_claimed_at=_now)
                ).rowcount
                db.session.commit()
                if _claimed == 0:
                    logger.info(f"Skipping clause {clause.id} ({clause.clause_no}) - already claimed by another worker")
                    continue

                # Extract compliance activities
                activity_response = extract_structured_info(""",
    },
]


def run_sql():
    from run import app
    from app import db
    with app.app_context():
        db.session.execute(db.text(SQL_ADD_COLUMN))
        db.session.commit()
    print(f"SQL applied: {SQL_ADD_COLUMN}")


def rollback():
    for patch in PATCHES:
        backup = patch["file"] + ".pieceF2.bak"
        if os.path.exists(backup):
            shutil.copy(backup, patch["file"])
            print(f"Rolled back: restored {patch['file']} from {backup}")
        else:
            print(f"No backup found for {patch['file']} at {backup} - skipping")
    print("\nNote: this does NOT drop the activity_generation_claimed_at column.")
    print("The column is harmless to leave in place (nullable, unused if code is rolled back).")
    print("To drop it manually: ALTER TABLE clauses DROP COLUMN activity_generation_claimed_at;")


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
        print(f"\nWould also run this SQL: {SQL_ADD_COLUMN}")
        print("dry-run: all patches would apply cleanly. No files written, no SQL executed.")
        return

    for f, content in file_contents.items():
        backup = f + ".pieceF2.bak"
        shutil.copy(f, backup)
        with open(f, "w") as fh:
            fh.write(content)
        print(f"Applied changes to {f} (backup: {backup})")

    run_sql()

    print("\nNEXT STEPS:")
    print("  1. Restart the relevant Celery worker (celery-staging.service on staging, celery.service on production)")
    print("  2. Re-run generate_missing_activities_for_guideline (try triggering it twice back-to-back to stress-test the claim)")
    print("  3. Confirm no activity_id reset pattern (no duplicates) after the run")
    print("  4. Rollback if needed: python3 apply_piece_F2_atomic_claim_fix.py --rollback")


if __name__ == "__main__":
    main()
