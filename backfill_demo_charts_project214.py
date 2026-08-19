#!/usr/bin/env python3
"""
DEMO DATA BACKFILL for project 214 (JK Bank, Credit Process Review) --
populates two charts on the project dashboard that were empty because the
underlying review/scoring steps were never run for this demo project:

1. "Findings Severity vs Recommendation Timeline" (bubble chart) --
   requires findings with auditor_status == 'CONFIRMED' and a
   related_recommendation.timeline. Sets these on the 6 existing findings
   for this project's Partial/Partially-Compliant activities.

2. "Evidence Quality by Clause" -- requires an EveAssuranceState row per
   ProjectChecklist. Creates one for each of the 6 activities with a
   plausible mid-range evidence_quality_score.

These are explicitly TEMP/DEMO values for showcasing the dashboard,
confirmed acceptable by Ankita for tomorrow's meeting. They are scoped
ONLY to the 6 known project_control_activity_ids for project 214 and do
not touch any other project's data.

Usage:
    python3 backfill_demo_charts_project214.py --dry-run
    python3 backfill_demo_charts_project214.py --apply
    python3 backfill_demo_charts_project214.py --rollback
"""
import argparse
import json
import sys
from pathlib import Path

ACTIVITY_IDS = [48268, 48497, 48542, 48548, 48189, 48723]
BACKUP_FILE = Path.home() / "CompliFyre-staging" / "backfill_demo_charts_project214.rollback.json"


def get_app_and_models():
    from app import create_app, db
    from app.models.project_instance_models import ProjectControlActivity
    from app.models.eve_models import EveControlResult, ProjectChecklist, EveAssuranceState
    app = create_app()
    return app, db, ProjectControlActivity, EveControlResult, ProjectChecklist, EveAssuranceState


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    app, db, ProjectControlActivity, EveControlResult, ProjectChecklist, EveAssuranceState = get_app_and_models()

    with app.app_context():
        if args.rollback:
            if not BACKUP_FILE.exists():
                print(f"No rollback file found at {BACKUP_FILE}. Nothing to roll back.")
                sys.exit(1)
            state = json.loads(BACKUP_FILE.read_text())

            for entry in state["findings_backup"]:
                ecr = EveControlResult.query.filter_by(
                    project_control_activity_id=entry["activity_id"]
                ).first()
                if ecr:
                    ecr.findings_json = entry["original_findings_json"]

            if state["created_eas_ids"]:
                EveAssuranceState.query.filter(
                    EveAssuranceState.id.in_(state["created_eas_ids"])
                ).delete(synchronize_session=False)

            db.session.commit()
            print(f"Rolled back findings_json on {len(state['findings_backup'])} activities "
                  f"and deleted {len(state['created_eas_ids'])} EveAssuranceState row(s).")
            return

        findings_backup = []
        created_eas_ids = []

        print(f"Processing {len(ACTIVITY_IDS)} activities: {ACTIVITY_IDS}\n")

        for aid in ACTIVITY_IDS:
            ecr = EveControlResult.query.filter_by(project_control_activity_id=aid).first()
            pc = ProjectChecklist.query.filter_by(project_control_activity_id=aid).first()

            if not ecr:
                print(f"  [{aid}] No EveControlResult found -- skipping findings update.")
            else:
                print(f"  [{aid}] Current findings_json: {ecr.findings_json}")

            if not pc:
                print(f"  [{aid}] No ProjectChecklist found -- skipping evidence quality seed.")
            else:
                existing_eas = EveAssuranceState.query.filter_by(project_checklist_id=pc.id).first()
                print(f"  [{aid}] ProjectChecklist id={pc.id}, existing EveAssuranceState: {existing_eas}")

        if args.dry_run:
            print("\n(No changes written. Re-run with --apply to:)")
            print("  1. Set auditor_status='CONFIRMED' + related_recommendation.timeline='MEDIUM_TERM'")
            print("     on each finding in findings_json for the 6 activities above.")
            print("  2. Create an EveAssuranceState row per ProjectChecklist with")
            print("     evidence_quality_score=68 (Adequate range) and matching counts.")
            return

        if args.apply:
            for aid in ACTIVITY_IDS:
                ecr = EveControlResult.query.filter_by(project_control_activity_id=aid).first()
                if ecr and ecr.findings_json:
                    findings_backup.append({
                        "activity_id": aid,
                        "original_findings_json": json.loads(json.dumps(ecr.findings_json)),
                    })
                    updated = []
                    for f in ecr.findings_json:
                        f = dict(f)
                        f["auditor_status"] = "CONFIRMED"
                        f["related_recommendation"] = {
                            "text": "Update credit policy to address the identified gap.",
                            "timeline": "MEDIUM_TERM",
                        }
                        updated.append(f)
                    ecr.findings_json = updated

                pc = ProjectChecklist.query.filter_by(project_control_activity_id=aid).first()
                if pc:
                    existing_eas = EveAssuranceState.query.filter_by(project_checklist_id=pc.id).first()
                    if not existing_eas:
                        eas = EveAssuranceState(
                            project_checklist_id=pc.id,
                            assurance_score=68.0,
                            coverage_score=75.0,
                            evidence_quality_score=68.0,
                            oe_reliability_score=70.0,
                            total_checklist_items=5,
                            evaluated_items=5,
                            passed_items=3,
                            failed_items=0,
                            partial_items=2,
                            needs_review_items=0,
                            inquiry_count=0,
                            contradiction_count=0,
                            resolved_inquiry_count=0,
                            escalated_inquiry_count=0,
                            total_evidence_count=1,
                            admissible_evidence_count=1,
                        )
                        db.session.add(eas)
                        db.session.flush()
                        created_eas_ids.append(eas.id)

            db.session.commit()

            BACKUP_FILE.write_text(json.dumps({
                "findings_backup": findings_backup,
                "created_eas_ids": created_eas_ids,
            }))

            print(f"\nUpdated findings_json on {len(findings_backup)} activities (marked CONFIRMED).")
            print(f"Created {len(created_eas_ids)} new EveAssuranceState row(s).")
            print(f"Rollback data saved to {BACKUP_FILE}")


if __name__ == "__main__":
    main()
