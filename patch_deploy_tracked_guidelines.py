#!/usr/bin/env python3
"""
Patch: Deploy the Tracked Guidelines route (item #133 UI, part 1) --
shows every document discovered by "Check for new guidelines" across
all regulators. Tested in local sandbox first (real Flask server, real
SQLite data resembling actual staging documents, functional content
verification of all status badges).

Appended at the END of the file, same safe pattern used for the
regulator management routes -- avoids any risk of disrupting existing
code in a file this large.

Usage:
    python3 patch_deploy_tracked_guidelines.py --dry-run
    python3 patch_deploy_tracked_guidelines.py --apply
    python3 patch_deploy_tracked_guidelines.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_tracked_guidelines")

NEW_ROUTE = '''

# ============================================================
# Tracked Guidelines (item #133 UI, part 1) -- core team only,
# NOT exposed to the AUDITOR role. Shows discovered documents
# from "Check for new guidelines" across all regulators.
# ============================================================

@re_bp.route("/tracked-guidelines", methods=["GET"])
@role_required("COMPLIFYRE", "RE")
def tracked_guidelines():
    """
    Tracked Guidelines (item #133 UI, part 1) -- core team only, not
    exposed to AUDITOR. Shows every document discovered by "Check for
    new guidelines" across all regulators, with status and a direct
    link to download it manually.
    """
    add_to_breadcrumb(request.full_path, "Tracked Guidelines")
    docs = (
        RegulatoryDocuments.query
        .join(RegulatoryBodies, RegulatoryDocuments.body_id == RegulatoryBodies.body_id)
        .add_columns(RegulatoryBodies.name.label("regulator_name"))
        .order_by(RegulatoryDocuments.created_at.desc())
        .all()
    )
    return render_template("tracked_guidelines.html", docs=docs)
'''


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

    if "def tracked_guidelines():" in content:
        print("Patch already applied. Nothing to do.")
        return

    patched = content.rstrip("\n") + "\n" + NEW_ROUTE

    if args.dry_run:
        print(f"Would append the tracked_guidelines() route at the end of the file")
        print(f"(currently {len(content.splitlines())} lines).")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nStill need to copy tracked_guidelines.html into")
        print("app/templates/dashboards/re/tracked_guidelines.html, then restart both services.")


if __name__ == "__main__":
    main()
