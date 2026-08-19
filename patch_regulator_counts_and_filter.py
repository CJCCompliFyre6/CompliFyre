#!/usr/bin/env python3
"""
Patch: Add document counts to Regulator Sources page (clickable through
to a filtered Tracked Guidelines view), add body_id filter support to
Tracked Guidelines, and add `func` import needed for the count query.
Both routes fully tested in local sandbox first (real Flask app with a
proper blueprint matching the real app's structure, real interactive
Playwright testing of counts, click-through filter, clear filter,
search, and sort -- both ascending and descending, both text and date
columns).

Usage:
    python3 patch_regulator_counts_and_filter.py --dry-run
    python3 patch_regulator_counts_and_filter.py --apply
    python3 patch_regulator_counts_and_filter.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_regulator_counts")

ANCHOR_IMPORT = "from sqlalchemy import desc"
NEW_IMPORT = "from sqlalchemy import desc, func"

ANCHOR_REGULATORS = '''def regulators():
    """
    Regulator source management (item #134) -- core team only, not
    exposed to the AUDITOR role. Lists all regulator entries and their
    listing-page links, feeding the guideline-tracking table and the
    'Check for new guidelines' button (item #133).
    """
    add_to_breadcrumb(request.full_path, "Regulator Sources")
    regulators = RegulatoryBodies.query.order_by(RegulatoryBodies.name).all()
    return render_template("regulators.html", regulators=regulators)'''

NEW_REGULATORS = '''def regulators():
    """
    Regulator source management (item #134) -- core team only, not
    exposed to the AUDITOR role. Lists all regulator entries and their
    listing-page links, feeding the guideline-tracking table and the
    'Check for new guidelines' button (item #133). Now includes a
    per-regulator count of tracked documents, clickable through to the
    filtered Tracked Guidelines view.
    """
    add_to_breadcrumb(request.full_path, "Regulator Sources")
    regulators = RegulatoryBodies.query.order_by(RegulatoryBodies.name).all()
    doc_counts = dict(
        db.session.query(RegulatoryDocuments.body_id, func.count(RegulatoryDocuments.document_id))
        .group_by(RegulatoryDocuments.body_id)
        .all()
    )
    return render_template("regulators.html", regulators=regulators, doc_counts=doc_counts)'''

ANCHOR_TRACKED = '''def tracked_guidelines():
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
    return render_template("tracked_guidelines.html", docs=docs)'''

NEW_TRACKED = '''def tracked_guidelines():
    """
    Tracked Guidelines (item #133 UI, part 1) -- core team only, not
    exposed to AUDITOR. Shows every document discovered by "Check for
    new guidelines" across all regulators, with status and a direct
    link to download it manually. Accepts an optional ?body_id= query
    param to filter to a single regulator (used by the click-through
    from the Regulator Sources page).
    """
    add_to_breadcrumb(request.full_path, "Tracked Guidelines")
    body_id_filter = request.args.get("body_id", type=int)

    query = (
        RegulatoryDocuments.query
        .join(RegulatoryBodies, RegulatoryDocuments.body_id == RegulatoryBodies.body_id)
        .add_columns(RegulatoryBodies.name.label("regulator_name"))
    )

    filtered_regulator_name = None
    if body_id_filter:
        query = query.filter(RegulatoryDocuments.body_id == body_id_filter)
        filtered_regulator = RegulatoryBodies.query.get(body_id_filter)
        filtered_regulator_name = filtered_regulator.name if filtered_regulator else None

    docs = query.order_by(RegulatoryDocuments.created_at.desc()).all()
    return render_template(
        "tracked_guidelines.html",
        docs=docs,
        filtered_regulator_name=filtered_regulator_name,
        body_id_filter=body_id_filter,
    )'''


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

    if "doc_counts = dict(" in content:
        print("Patch already applied. Nothing to do.")
        return

    for name, anchor in [
        ("IMPORT", ANCHOR_IMPORT),
        ("REGULATORS", ANCHOR_REGULATORS),
        ("TRACKED", ANCHOR_TRACKED),
    ]:
        count = content.count(anchor)
        if count != 1:
            print(f"ERROR: anchor '{name}' matched {count} times (expected 1). Aborting.")
            sys.exit(1)

    patched = content.replace(ANCHOR_IMPORT, NEW_IMPORT)
    patched = patched.replace(ANCHOR_REGULATORS, NEW_REGULATORS)
    patched = patched.replace(ANCHOR_TRACKED, NEW_TRACKED)

    if args.dry_run:
        print("All 3 anchors matched exactly once.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nStill need to update both templates, then restart both services.")


if __name__ == "__main__":
    main()
