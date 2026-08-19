#!/usr/bin/env python3
"""
Piece A: Update Clauses model docstring to include REFERENCE (currently
undocumented despite being a real, actively-used clause_type from Stage 2).

Piece B: Filter generate_missing_activities_for_guideline() to only process
OBLIGATION/PRINCIPLE/MIXED clauses — DEFINITION/APPLICABILITY/EXEMPTION/
REFERENCE should never reach activity-generation.

Usage:
    python3 apply_piece_A_B_fix.py --dry-run
    python3 apply_piece_A_B_fix.py
    python3 apply_piece_A_B_fix.py --rollback
"""
import argparse
import shutil
import sys

PATCHES = [
    {
        "name": "A: document REFERENCE in Clauses model docstring",
        "file": "app/models/ai.py",
        "old": """    clause_type: OBLIGATION / PRINCIPLE / MIXED / DEFINITION / APPLICABILITY / EXEMPTION
    extraction_status: EXTRACTED / APPROVED / FLAGGED
    flag_reason: UNKNOWN_APPLICABILITY / AMBIGUOUS_MERGE / UNKNOWN_LICENSE / CROSS_GUIDELINE_REF / EXTERNAL_REF
    \"\"\"""",
        "new": """    clause_type: OBLIGATION / PRINCIPLE / MIXED / DEFINITION / APPLICABILITY / EXEMPTION / REFERENCE
    extraction_status: EXTRACTED / APPROVED / FLAGGED
    flag_reason: UNKNOWN_APPLICABILITY / AMBIGUOUS_MERGE / UNKNOWN_LICENSE / CROSS_GUIDELINE_REF / EXTERNAL_REF
    \"\"\"""",
    },
    {
        "name": "B: filter activity-generation to OBLIGATION/PRINCIPLE/MIXED only",
        "file": "app/services/manual_task.py",
        "old": """        # Find clauses without activities
        clauses_without_activities = Clauses.query.filter(
            Clauses.guideline_id == guideline_id,
            ~Clauses.id.in_(
                db.session.query(ComplianceActivities.clause_id).filter(
                    ComplianceActivities.clause_id.isnot(None)
                )
            ),
        ).all()""",
        "new": """        # Find clauses without activities
        # Only OBLIGATION/PRINCIPLE/MIXED clauses carry an independent duty
        # for the RE to act on — DEFINITION/APPLICABILITY/EXEMPTION/REFERENCE
        # clauses should never reach activity-generation on their own.
        ACTIVITY_ELIGIBLE_TYPES = ['OBLIGATION', 'PRINCIPLE', 'MIXED']
        clauses_without_activities = Clauses.query.filter(
            Clauses.guideline_id == guideline_id,
            Clauses.clause_type.in_(ACTIVITY_ELIGIBLE_TYPES),
            ~Clauses.id.in_(
                db.session.query(ComplianceActivities.clause_id).filter(
                    ComplianceActivities.clause_id.isnot(None)
                )
            ),
        ).all()""",
    },
]


def rollback():
    for patch in PATCHES:
        backup = patch["file"] + ".pieceAB.bak"
        import os
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
        backup = f + ".pieceAB.bak"
        shutil.copy(f, backup)
        with open(f, "w") as fh:
            fh.write(content)
        print(f"Applied changes to {f} (backup: {backup})")

    print("\nNEXT STEPS:")
    print("  1. Restart the relevant Celery worker (celery-staging.service on staging, celery.service on production)")
    print("  2. Create a fresh test guideline copy, run generate_missing_activities_for_guideline")
    print("  3. Confirm no DEFINITION/APPLICABILITY/EXEMPTION/REFERENCE clauses got activities")
    print("  4. Rollback if needed: python3 apply_piece_A_B_fix.py --rollback")


if __name__ == "__main__":
    main()
