#!/usr/bin/env python3
"""
Patch: Add severity normalization to the project-level "CALCULATE SEVERITY
FOR THIS CLAUSE" loop in app/routes/re/view.py (feeds severity_counts ->
severity_stats -> "Findings by Severity" on the project dashboard,
/re/activity/<id>).

Bug: same root cause as the clause-level severity bug we already fixed in
app/routes/audit/view.py -- raw EVE-style severity values (e.g. 'MEDIUM',
'HIGH', 'LOW', 'CRITICAL') stored in overall_severity_classification pass
through unmapped. severity_hierarchy only recognizes 'Critical'/'Major'/
'Significant'/'Minor'/'No findings noted', so unmapped values score 0 and
never win the "highest severity" comparison for a clause -- causing every
clause with a raw severity value to be miscounted as 'No findings noted'
in the project dashboard's "Findings by Severity" panel.

Fix: normalize activity_severity through the same severity_map used
elsewhere, inserted after the existing fallback block and before the
scoring/counting gate.

Usage:
    python3 patch_project_severity_normalization.py --dry-run
    python3 patch_project_severity_normalization.py --apply
    python3 patch_project_severity_normalization.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_severity_norm")

OLD_BLOCK = """                # Default to 'No findings noted' if nothing found and activity is compliant
                if not activity_severity or activity_severity == 'Not Classified':
                    if activity.compliant_status == 'Compliant':
                        activity_severity = 'No findings noted'
                    else:
                        activity_severity = 'Not Classified'
                
                if activity_severity and activity_severity != 'Not Classified':
                    severity_score = severity_hierarchy.get(activity_severity, 0)"""

NEW_BLOCK = """                # Default to 'No findings noted' if nothing found and activity is compliant
                if not activity_severity or activity_severity == 'Not Classified':
                    if activity.compliant_status == 'Compliant':
                        activity_severity = 'No findings noted'
                    else:
                        activity_severity = 'Not Classified'
                
                # Normalize raw severity values (e.g. EVE-style CRITICAL/HIGH/MEDIUM/LOW)
                # to the standard labels used by severity_hierarchy / severity_counts below.
                # Without this, unmapped raw values silently score 0 and the clause is
                # miscounted as 'No findings noted' in the project dashboard.
                if activity_severity:
                    _severity_norm_map = {
                        'CRITICAL': 'Critical',
                        'HIGH': 'Major', 'MAJOR': 'Major',
                        'MEDIUM': 'Significant', 'SIGNIFICANT': 'Significant',
                        'LOW': 'Minor', 'MINOR': 'Minor',
                        'NO_FINDINGS': 'No findings noted', 'NO FINDINGS NOTED': 'No findings noted',
                    }
                    _normalized = _severity_norm_map.get(activity_severity.upper())
                    if _normalized:
                        activity_severity = _normalized
                
                if activity_severity and activity_severity != 'Not Classified':
                    severity_score = severity_hierarchy.get(activity_severity, 0)"""


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
