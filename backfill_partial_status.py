#!/usr/bin/env python3
"""
Backfill: normalize compliant_status = 'Partial' -> 'Partially Compliant'
on ProjectControlActivity rows.

Context: DB audit found 6 rows with compliant_status = 'Partial', which is
not a value any code path in the app writes (confirmed via grep across
app/*.py and app/templates/). This appears to be a stray value from earlier
manual demo-data seeding, not an application bug. The canonical value is
'Partially Compliant' (confirmed with Ankita).

This script only touches rows where compliant_status is EXACTLY 'Partial'.
It does not touch any other status value.

Usage:
    python3 backfill_partial_status.py --dry-run
    python3 backfill_partial_status.py --apply
    python3 backfill_partial_status.py --rollback
"""
import argparse
import json
import sys
from pathlib import Path

BACKUP_FILE = Path.home() / "CompliFyre-staging" / "backfill_partial_status.rollback.json"


def get_app_and_models():
    from app import create_app, db
    from app.models.project_instance_models import ProjectControlActivity
    app = create_app()
    return app, db, ProjectControlActivity


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    app, db, ProjectControlActivity = get_app_and_models()

    with app.app_context():
        if args.rollback:
            if not BACKUP_FILE.exists():
                print(f"No rollback file found at {BACKUP_FILE}. Nothing to roll back.")
                sys.exit(1)
            ids = json.loads(BACKUP_FILE.read_text())
            rows = ProjectControlActivity.query.filter(
                ProjectControlActivity.id.in_(ids)
            ).all()
            for row in rows:
                row.compliant_status = "Partial"
            db.session.commit()
            print(f"Rolled back {len(rows)} row(s) to 'Partial'.")
            return

        rows = ProjectControlActivity.query.filter_by(compliant_status="Partial").all()

        if not rows:
            print("No rows with compliant_status = 'Partial' found. Nothing to do.")
            return

        print(f"Found {len(rows)} row(s) with compliant_status = 'Partial':")
        for row in rows:
            print(f"  id={row.id} activity_code={getattr(row, 'activity_code', '?')} "
                  f"project_compliance_activity_id={getattr(row, 'project_compliance_activity_id', '?')}")

        if args.dry_run:
            print("\n(No changes written. Re-run with --apply to update these rows to 'Partially Compliant'.)")
            return

        if args.apply:
            ids = [row.id for row in rows]
            BACKUP_FILE.write_text(json.dumps(ids))
            for row in rows:
                row.compliant_status = "Partially Compliant"
            db.session.commit()
            print(f"\nUpdated {len(rows)} row(s) to 'Partially Compliant'.")
            print(f"Rollback list saved to {BACKUP_FILE}")


if __name__ == "__main__":
    main()
