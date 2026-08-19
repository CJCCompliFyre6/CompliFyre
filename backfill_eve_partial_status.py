#!/usr/bin/env python3
"""
Backfill: normalize EveControlResult.final_status = 'PARTIAL' ->
'PARTIALLY_COMPLIANT'.

Context: DB audit found 6 rows with final_status = 'PARTIAL', versus 18 rows
correctly using the canonical EVE value 'PARTIALLY_COMPLIANT' (alongside
'COMPLIANT' and 'NON_COMPLIANT'). These 6 rows share the exact same
project_control_activity_id set as the 6 rows we already backfilled in
ProjectControlActivity.compliant_status ('Partial' -> 'Partially Compliant')
-- confirming this is leftover demo-data seeding noise on the same 6
activities, not a real EVE pipeline output value.

This script only touches rows where final_status is EXACTLY 'PARTIAL'.
It does not touch any other status value.

Usage:
    python3 backfill_eve_partial_status.py --dry-run
    python3 backfill_eve_partial_status.py --apply
    python3 backfill_eve_partial_status.py --rollback
"""
import argparse
import json
import sys
from pathlib import Path

BACKUP_FILE = Path.home() / "CompliFyre-staging" / "backfill_eve_partial_status.rollback.json"


def get_app_and_models():
    from app import create_app, db
    from app.models.eve_models import EveControlResult
    app = create_app()
    return app, db, EveControlResult


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    app, db, EveControlResult = get_app_and_models()

    with app.app_context():
        if args.rollback:
            if not BACKUP_FILE.exists():
                print(f"No rollback file found at {BACKUP_FILE}. Nothing to roll back.")
                sys.exit(1)
            ids = json.loads(BACKUP_FILE.read_text())
            rows = EveControlResult.query.filter(EveControlResult.id.in_(ids)).all()
            for row in rows:
                row.final_status = "PARTIAL"
            db.session.commit()
            print(f"Rolled back {len(rows)} row(s) to 'PARTIAL'.")
            return

        rows = EveControlResult.query.filter_by(final_status="PARTIAL").all()

        if not rows:
            print("No rows with final_status = 'PARTIAL' found. Nothing to do.")
            return

        print(f"Found {len(rows)} row(s) with final_status = 'PARTIAL':")
        for row in rows:
            print(f"  id={row.id} project_control_activity_id={row.project_control_activity_id}")

        if args.dry_run:
            print("\n(No changes written. Re-run with --apply to update these rows to 'PARTIALLY_COMPLIANT'.)")
            return

        if args.apply:
            ids = [row.id for row in rows]
            BACKUP_FILE.write_text(json.dumps(ids))
            for row in rows:
                row.final_status = "PARTIALLY_COMPLIANT"
            db.session.commit()
            print(f"\nUpdated {len(rows)} row(s) to 'PARTIALLY_COMPLIANT'.")
            print(f"Rollback list saved to {BACKUP_FILE}")


if __name__ == "__main__":
    main()
