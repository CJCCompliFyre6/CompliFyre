#!/usr/bin/env python3
"""
Patch: Fix "Compliance Rate" and "Issues Found" stats in
app/templates/dashboards/auditor/clause_test_steps.html

Bugs:
1. Compliance Rate incorrectly added Partially Compliant into the numerator
   alongside Compliant, so a clause with any Partial activities could still
   show 100% -- contradicting the Compliance Status Distribution panel above it.
2. Issues Found only counted strictly Non-Compliant activities, ignoring
   Partially Compliant entirely -- so it showed 0 even when the Overall
   Severity Level panel correctly showed 1 finding.

Fix (per decision: Partially Compliant counts as an issue, same weight as
Non-Compliant, since it represents a real finding):
- Compliance Rate = Compliant / total * 100  (Partial no longer inflates it)
- Issues Found = Non-Compliant + Partially Compliant

Usage:
    python3 patch_clause_compliance_rate_issues.py --dry-run
    python3 patch_clause_compliance_rate_issues.py --apply
    python3 patch_clause_compliance_rate_issues.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = (
    Path.home() / "CompliFyre-staging" / "app" / "templates"
    / "dashboards" / "auditor" / "clause_test_steps.html"
)
BACKUP = TARGET.with_suffix(".html.bak_rate_issues")

OLD_BLOCK = """                    <!-- Compliance Rate -->
                    <div class="flex justify-between items-center py-2 border-b border-gray-100">
                        <span class="text-sm text-gray-600">Compliance Rate:</span>
                        <span class="text-lg font-bold text-green-600">
                            {% set compliant_total = clause_status_info.statistics.Compliant + clause_status_info.statistics['Partially Compliant'] %}
                            {{ (compliant_total / clause_status_info.statistics.total * 100)|round|int if clause_status_info.statistics.total > 0 else 0 }}%
                        </span>
                    </div>
                    
                    <!-- Non-Compliance Rate -->
                    <div class="flex justify-between items-center py-2 border-b border-gray-100">
                        <span class="text-sm text-gray-600">Issues Found:</span>
                        <span class="text-lg font-bold text-red-600">
                            {{ clause_status_info.statistics['Non-Compliant'] }}
                        </span>
                    </div>"""

NEW_BLOCK = """                    <!-- Compliance Rate -->
                    <div class="flex justify-between items-center py-2 border-b border-gray-100">
                        <span class="text-sm text-gray-600">Compliance Rate:</span>
                        <span class="text-lg font-bold text-green-600">
                            {{ (clause_status_info.statistics.Compliant / clause_status_info.statistics.total * 100)|round|int if clause_status_info.statistics.total > 0 else 0 }}%
                        </span>
                    </div>
                    
                    <!-- Non-Compliance Rate -->
                    <div class="flex justify-between items-center py-2 border-b border-gray-100">
                        <span class="text-sm text-gray-600">Issues Found:</span>
                        <span class="text-lg font-bold text-red-600">
                            {{ clause_status_info.statistics['Non-Compliant'] + clause_status_info.statistics['Partially Compliant'] }}
                        </span>
                    </div>"""


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
        print("\nTemplates are typically picked up without a restart, but restart")
        print("complifyre-staging.service if the change doesn't show up on refresh.")


if __name__ == "__main__":
    main()
