#!/usr/bin/env python3
"""
Patch: Deploy the regulator management routes (item #134 UI, Phase 2) to
app/routes/re/view.py -- fully tested in an isolated local sandbox first
(real Flask server, real SQLite database, real browser interaction via
Playwright: create, edit, delete, and duplicate-URL rejection all
verified against actual HTTP requests and actual database state).

Adds:
  - Import for RegulatoryBodies (app.models.re) -- confirmed not
    previously imported in this file.
  - Four routes: GET /regulators (list), POST /regulators/add,
    POST /regulators/<id>/edit, POST /regulators/<id>/delete.
    All restricted to COMPLIFYRE and RE roles only -- NOT exposed to
    AUDITOR, per explicit requirement this page is core-team only.

Appended at the END of the file (7701 lines) rather than inserted
mid-file, to avoid any risk of disrupting existing route definitions in
a file this large that hasn't been fully reviewed line-by-line.

Usage:
    python3 patch_deploy_regulator_routes.py --dry-run
    python3 patch_deploy_regulator_routes.py --apply
    python3 patch_deploy_regulator_routes.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_regulator_routes")

IMPORT_ANCHOR = "from app.models.auditOrganization import *"
NEW_IMPORT_LINE = "\nfrom app.models.re import RegulatoryBodies\n"

NEW_ROUTES = '''

# ============================================================
# Regulator source management (item #134) -- core team only,
# NOT exposed to the AUDITOR role. Feeds the guideline-tracking
# table and the "Check for new guidelines" button (item #133).
# ============================================================

@re_bp.route("/regulators", methods=["GET"])
@role_required("COMPLIFYRE", "RE")
def regulators():
    """
    Regulator source management (item #134) -- core team only, not
    exposed to the AUDITOR role. Lists all regulator entries and their
    listing-page links, feeding the guideline-tracking table and the
    'Check for new guidelines' button (item #133).
    """
    add_to_breadcrumb(request.full_path, "Regulator Sources")
    regulators = RegulatoryBodies.query.order_by(RegulatoryBodies.name).all()
    return render_template("regulators.html", regulators=regulators)


@re_bp.route("/regulators/add", methods=["POST"])
@role_required("COMPLIFYRE", "RE")
def add_regulator():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    geography = request.form.get("geography", "").strip()
    industry = request.form.get("industry", "").strip()
    governed_institutions = request.form.get("governed_institutions", "").strip()
    website_url = request.form.get("website_url", "").strip()

    if not name or not website_url:
        flash("Regulator name and URL are required.", "error")
        return redirect(url_for("re_bp.regulators"))

    existing = RegulatoryBodies.query.filter_by(website_url=website_url).first()
    if existing:
        flash(f"This URL is already tracked (under '{existing.name}') -- URLs must be unique. "
              f"If this regulator has another page, use a different URL.", "error")
        return redirect(url_for("re_bp.regulators"))

    regulator = RegulatoryBodies(
        name=name,
        description=description or None,
        geography=geography or None,
        industry=industry or None,
        governed_institutions=governed_institutions or None,
        website_url=website_url,
    )
    db.session.add(regulator)
    db.session.commit()
    flash(f"Added regulator page: {name}", "success")
    return redirect(url_for("re_bp.regulators"))


@re_bp.route("/regulators/<int:body_id>/edit", methods=["POST"])
@role_required("COMPLIFYRE", "RE")
def edit_regulator(body_id):
    regulator = RegulatoryBodies.query.get_or_404(body_id)
    name = request.form.get("name", "").strip()
    website_url = request.form.get("website_url", "").strip()
    if not name or not website_url:
        flash("Regulator name and URL are required.", "error")
        return redirect(url_for("re_bp.regulators"))

    existing = RegulatoryBodies.query.filter(
        RegulatoryBodies.website_url == website_url,
        RegulatoryBodies.body_id != body_id,
    ).first()
    if existing:
        flash(f"This URL is already tracked (under '{existing.name}') -- URLs must be unique.", "error")
        return redirect(url_for("re_bp.regulators"))

    regulator.name = name
    regulator.description = request.form.get("description", "").strip() or None
    regulator.geography = request.form.get("geography", "").strip() or None
    regulator.industry = request.form.get("industry", "").strip() or None
    regulator.governed_institutions = request.form.get("governed_institutions", "").strip() or None
    regulator.website_url = website_url
    db.session.commit()
    flash(f"Updated regulator page: {regulator.name}", "success")
    return redirect(url_for("re_bp.regulators"))


@re_bp.route("/regulators/<int:body_id>/delete", methods=["POST"])
@role_required("COMPLIFYRE", "RE")
def delete_regulator(body_id):
    regulator = RegulatoryBodies.query.get_or_404(body_id)
    name = regulator.name
    db.session.delete(regulator)
    db.session.commit()
    flash(f"Deleted regulator: {name}", "success")
    return redirect(url_for("re_bp.regulators"))
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

    if "def regulators():" in content:
        print("Patch already applied. Nothing to do.")
        return

    if content.count(IMPORT_ANCHOR) != 1:
        print(f"ERROR: import anchor matched {content.count(IMPORT_ANCHOR)} times (expected 1). Aborting.")
        sys.exit(1)

    patched = content.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + NEW_IMPORT_LINE)
    patched = patched.rstrip("\n") + "\n" + NEW_ROUTES

    if args.dry_run:
        print("Import anchor found exactly once -- would insert import line after it.")
        print("Would append 4 new routes (regulators, add_regulator, edit_regulator, delete_regulator)")
        print(f"at the end of the file (currently {len(content.splitlines())} lines).")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nStill need to copy the regulators.html template into")
        print("app/templates/dashboards/re/regulators.html, then restart both services.")


if __name__ == "__main__":
    main()
