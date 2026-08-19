"""
Removes duplicate-batch activities caused by the generate_missing_activities_for_guideline
race-condition (task dispatched twice, two workers processed overlapping clauses).

Detection: within a clause's activities (ordered by insertion/id), find the point
where activity_id resets (current <= previous) - that marks the start of the
duplicate second batch. Keeps the FIRST batch (earliest-inserted), deletes the rest.

CAUTION: Deleting a ComplianceActivity cascades to delete related Projects,
ControlActivities, HowToPerformActivity, and TestProcedures (per model docstring).
Safe here since guideline 214 is a fresh test-copy with no real downstream usage.
Do NOT run this against a live/production guideline without re-checking that.

Usage:
    python3 cleanup_duplicate_activities.py --guideline-id 214 --dry-run
    python3 cleanup_duplicate_activities.py --guideline-id 214 --apply
"""
import argparse

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guideline-id", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not args.dry_run and not args.apply:
        print("Specify --dry-run or --apply")
        return

    from run import app
    from app.models.ai import Clauses, ComplianceActivities
    from app import db

    with app.app_context():
        all_clauses = Clauses.query.filter_by(guideline_id=args.guideline_id).all()
        total_deleted = 0
        affected_count = 0

        for c in all_clauses:
            acts = ComplianceActivities.query.filter_by(clause_id=c.id).order_by(ComplianceActivities.id).all()
            if not acts:
                continue
            prev_id = None
            reset_at = None
            for i, a in enumerate(acts):
                try:
                    cur = int(a.activity_id)
                except (TypeError, ValueError):
                    cur = None
                if prev_id is not None and cur is not None and cur <= prev_id:
                    reset_at = i
                    break
                prev_id = cur
            if reset_at is None:
                continue

            to_delete = acts[reset_at:]
            affected_count += 1
            print(f"{c.clause_no}: keeping {reset_at} activities, deleting {len(to_delete)} (ids: {[a.id for a in to_delete]})")

            if args.apply:
                for a in to_delete:
                    db.session.delete(a)
                total_deleted += len(to_delete)

        if args.apply:
            db.session.commit()
            print(f"\nApplied: deleted {total_deleted} duplicate activities across {affected_count} clauses.")
        else:
            print(f"\ndry-run: would delete duplicates across {affected_count} clauses. Re-run with --apply to execute.")

if __name__ == "__main__":
    main()
