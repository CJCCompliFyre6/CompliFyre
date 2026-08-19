#!/usr/bin/env python3
"""
Piece F2b: Fix the timezone-aware/naive datetime comparison crash in the
atomic-claim logic (Piece F2). PostgreSQL TIMESTAMP column stores naive
values; comparing against a tz-aware datetime.now(timezone.utc) raises
'can't compare offset-naive and offset-aware datetimes' once the column
has a value (the first claim, against NULL, doesn't hit the comparison
and so didn't surface this bug).

Fix: use naive UTC datetimes throughout, matching the DB column's actual
storage format.

Usage:
    python3 apply_piece_F2b_datetime_fix.py --dry-run
    python3 apply_piece_F2b_datetime_fix.py
    python3 apply_piece_F2b_datetime_fix.py --rollback
"""
import argparse
import shutil
import sys
import os

TARGET = "app/services/manual_task.py"

PATCHES = [
    {
        "name": "F2b: use naive UTC datetimes for the claim comparison",
        "old": """                from datetime import datetime, timedelta, timezone
                _now = datetime.now(timezone.utc)
                _stale_before = _now - timedelta(hours=2)""",
        "new": """                from datetime import datetime, timedelta, timezone
                _now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive - matches DB column storage
                _stale_before = _now - timedelta(hours=2)""",
    },
]


def rollback():
    backup = TARGET + ".pieceF2b.bak"
    if os.path.exists(backup):
        shutil.copy(backup, TARGET)
        print(f"Rolled back: restored {TARGET} from {backup}")
    else:
        print(f"No backup found at {backup} - nothing to roll back.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    if args.rollback:
        rollback()
        return

    with open(TARGET, "r") as f:
        content = f.read()

    for patch in PATCHES:
        count = content.count(patch["old"])
        if count == 0:
            print(f"ABORT - pattern not found for patch '{patch['name']}'.")
            sys.exit(1)
        if count > 1:
            print(f"ABORT - pattern matches {count} times (expected exactly 1).")
            sys.exit(1)
        content = content.replace(patch["old"], patch["new"], 1)
        print(f"OK - patch '{patch['name']}' matched exactly once.")

    if args.dry_run:
        print("\ndry-run: patch would apply cleanly. No files written.")
        return

    backup = TARGET + ".pieceF2b.bak"
    shutil.copy(TARGET, backup)
    with open(TARGET, "w") as f:
        f.write(content)
    print(f"\nApplied to {TARGET} (backup: {backup})")
    print("\nNEXT STEPS:")
    print("  1. Restart celery-staging.service")
    print("  2. Re-run the concurrent-trigger test on a fresh guideline copy")
    print("  3. Confirm 'Skipping clause ... already claimed' lines now appear")
    print("  4. Rollback if needed: python3 apply_piece_F2b_datetime_fix.py --rollback")


if __name__ == "__main__":
    main()
