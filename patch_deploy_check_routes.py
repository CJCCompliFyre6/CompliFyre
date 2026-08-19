#!/usr/bin/env python3
"""
Patch: Deploy the single and bulk "Check for new guidelines" trigger
routes. Both dispatch check_regulator_for_new_guidelines as a background
Celery task via .delay() -- never run synchronously in the request,
since a real check can take genuine time (RBI's first live check found
226 documents and involved a real fetch + LLM extraction cycle).

Importing check_guidelines_service here also fixes a real bug found
live: the Celery worker had never loaded this module before (nothing
in the app's normal import chain touched it, since it was only ever
exercised directly via flask shell), so the task was completely
unregistered with Celery -- confirmed via the worker's own [tasks]
startup listing and a live dispatch attempt that was rejected with
"Received unregistered task". This import is what actually registers it.

Both routes tested extensively in local sandbox first: status badge
rendering for all 4 states (Success/Blocked/URL Not Found/Not checked
yet), checkbox selection, Select All toggle, bulk button enable/disable
state, and both single-row and bulk form submissions verified to
dispatch the correct body_ids.

Usage:
    python3 patch_deploy_check_routes.py --dry-run
    python3 patch_deploy_check_routes.py --apply
    python3 patch_deploy_check_routes.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_check_routes")

NEW_ROUTES = '''

# ============================================================
# "Check for new guidelines" triggers (item #133 UI, part 2) --
# core team only, NOT exposed to the AUDITOR role. Both dispatch
# as background Celery tasks, never run synchronously in the
# request.
# ============================================================

@re_bp.route("/regulators/<int:body_id>/check", methods=["POST"])
@role_required("COMPLIFYRE", "RE")
def check_regulator(body_id):
    """
    Triggers a single regulator's "Check for new guidelines" as a
    background Celery task -- never runs synchronously in the request,
    since even a simple check can take real time (fetch + possible
    Playwright rendering + LLM extraction; RBI's first real check found
    226 documents and was not instant).
    """
    from app.services.check_guidelines_service import check_regulator_for_new_guidelines
    regulator = RegulatoryBodies.query.get_or_404(body_id)
    check_regulator_for_new_guidelines.delay(body_id)
    flash(f"Check queued for {regulator.name}"
          f"{' -- ' + regulator.description if regulator.description else ''}. "
          f"Refresh in a moment to see results.", "success")
    return redirect(url_for("re.regulators"))


@re_bp.route("/regulators/check-bulk", methods=["POST"])
@role_required("COMPLIFYRE", "RE")
def check_regulators_bulk():
    """
    Triggers "Check for new guidelines" for multiple selected regulators
    at once, dispatched as separate background Celery tasks -- processed
    one at a time by the worker, not run in parallel within this
    request, matching the "not a sweep, still deliberate" principle
    agreed on for this feature.
    """
    from app.services.check_guidelines_service import check_regulator_for_new_guidelines
    body_ids = request.form.getlist("body_ids", type=int)
    if not body_ids:
        flash("No regulators selected.", "error")
        return redirect(url_for("re.regulators"))
    for bid in body_ids:
        check_regulator_for_new_guidelines.delay(bid)
    flash(f"Queued checks for {len(body_ids)} regulator(s). Refresh in a moment to see results.", "success")
    return redirect(url_for("re.regulators"))
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

    if "def check_regulator(body_id):" in content:
        print("Patch already applied. Nothing to do.")
        return

    patched = content.rstrip("\n") + "\n" + NEW_ROUTES

    if args.dry_run:
        print(f"Would append the check-trigger routes at the end of the file")
        print(f"(currently {len(content.splitlines())} lines).")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nStill need to update regulators.html, then restart both services.")


if __name__ == "__main__":
    main()
