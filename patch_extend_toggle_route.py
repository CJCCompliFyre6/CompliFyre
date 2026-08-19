#!/usr/bin/env python3
"""
Patch: Extend the existing toggle_guideline_enabled route to accept and
store an optional reason + timestamp when disabling a guideline, and
clear both when re-enabling. The route already correctly cascades
disabling to auditor visibility -- this just adds the "why" that was
missing.

Usage:
    python3 patch_extend_toggle_route.py --dry-run
    python3 patch_extend_toggle_route.py --apply
    python3 patch_extend_toggle_route.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_toggle_reason")

ANCHOR = '''        data = request.get_json(silent=True) or {}
        # optional: client may pass {"enabled": true/false}; otherwise toggle
        enabled_from_client = data.get("enabled", None)
        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            return jsonify({"error": "Guideline not found"}), 404

        # Compute new value
        if enabled_from_client is None:
            new_enabled = not guideline.enabled
        else:
            new_enabled = bool(enabled_from_client)

        guideline.enabled = new_enabled
        db.session.add(guideline)'''

NEW = '''        data = request.get_json(silent=True) or {}
        # optional: client may pass {"enabled": true/false}; otherwise toggle
        enabled_from_client = data.get("enabled", None)
        reason_from_client = data.get("reason", None)
        guideline = Guidelines.query.get(guideline_id)
        if not guideline:
            return jsonify({"error": "Guideline not found"}), 404

        # Compute new value
        if enabled_from_client is None:
            new_enabled = not guideline.enabled
        else:
            new_enabled = bool(enabled_from_client)

        guideline.enabled = new_enabled
        if not new_enabled:
            guideline.disabled_reason = reason_from_client or None
            guideline.disabled_at = datetime.now(timezone.utc)
        else:
            guideline.disabled_reason = None
            guideline.disabled_at = None
        db.session.add(guideline)'''


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

    if "reason_from_client" in content:
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
