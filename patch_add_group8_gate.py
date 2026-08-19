#!/usr/bin/env python3
"""
Patch: add Group 8's core soft-gate function (get_loi_gate_state) to
the already-deployed app/routes/loi/view.py. Wiring this into the
actual real trigger-point routes (download guideline, evaluate,
export, invite team member) is a separate follow-on patch, once those
routes are located in the real codebase.

Usage:
    python3 patch_add_group8_gate.py --dry-run
    python3 patch_add_group8_gate.py --apply
    python3 patch_add_group8_gate.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "loi" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_group8")

ANCHOR = '''    return render_template("dashboards/loi/forward_sent.html", forwarded_name=forwarded_name)'''

NEW = ANCHOR + '''


# ============================================================
# Group 8 -- Soft gate (core logic; wiring into real trigger
# points is a separate follow-on patch)
# ============================================================

def get_loi_gate_state(org, user=None):
    """
    Returns 'NONE' / 'MODAL' / 'BANNER', computed from ACTUAL logged
    events (not a manually-passed counter). Shown to every user in an
    unsigned org, not just the first -- appearance counting is
    org-wide, not per-user.
    """
    if not org.loi_required:
        return "NONE"
    if org.loi_status == "SIGNED":
        return "NONE"

    FORWARD_GRACE_DAYS = 7
    most_recent_forward = (
        UserJourneyEvents.query
        .filter_by(organization_id=org.organization_id, event_type="forwarded")
        .order_by(UserJourneyEvents.occurred_at.desc())
        .first()
    )
    if most_recent_forward:
        occurred_at = most_recent_forward.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - occurred_at).days < FORWARD_GRACE_DAYS:
            return "NONE"

    shown_events = (
        UserJourneyEvents.query
        .filter_by(organization_id=org.organization_id, event_type="loi_prompt_shown")
        .order_by(UserJourneyEvents.occurred_at.desc())
        .all()
    )

    if len(shown_events) >= 5:
        return "BANNER"

    if shown_events:
        most_recent_shown = shown_events[0].occurred_at
        if most_recent_shown.tzinfo is None:
            most_recent_shown = most_recent_shown.replace(tzinfo=timezone.utc)
        hours_since_shown = (datetime.now(timezone.utc) - most_recent_shown).total_seconds() / 3600
        if hours_since_shown < 24:
            return "NONE"

    return "MODAL"


def record_loi_prompt_shown(org, user, trigger):
    db.session.add(UserJourneyEvents(
        organization_id=org.organization_id, user_id=user.id if user else None,
        event_type="loi_prompt_shown", event_detail=f"Triggered by: {trigger}"
    ))
    db.session.commit()


def loi_gate_redirect_if_needed(trigger_name):
    """
    Call this at the top of any real action route that should be
    gated by the LOI soft-gate. Returns a redirect response if the
    modal should show (and logs the appearance), or None if the
    caller should proceed normally.
    """
    org = Organizations.query.get(current_user.organization_id)
    if not org:
        return None
    gate_state = get_loi_gate_state(org, current_user)
    if gate_state == "MODAL":
        record_loi_prompt_shown(org, current_user, trigger_name)
        return redirect(url_for("loi.loi_show"))
    return None'''


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

    if "Group 8 -- Soft gate" in content:
        print("Patch already applied. Nothing to do.")
        return

    count = content.count(ANCHOR)
    if count != 1:
        print(f"ERROR: anchor matched {count} times (expected 1). Aborting.")
        sys.exit(1)

    patched = content.replace(ANCHOR, NEW)

    if args.dry_run:
        print("Anchor matched exactly once.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
