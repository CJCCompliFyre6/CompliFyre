#!/usr/bin/env python3
"""
Patch: Fix a genuine bug in the just-deployed regulator management routes
-- all url_for("re_bp.regulators") calls used the wrong blueprint name.
The blueprint is registered as "re", not "re_bp" (confirmed directly from
the real traceback: "Could not build url for endpoint 're_bp.regulators'.
Did you mean 're.regulators' instead?"). This never surfaced in local
sandbox testing because that used raw hardcoded URLs, not this app's
actual url_for()-based redirect pattern.

Replaces every occurrence of 'url_for("re_bp.regulators")' with
'url_for("re.regulators")' -- confirmed via grep that this exact string
only appears in the newly-added regulator routes, nowhere else in this
7700+ line file, so a global replace is safe.

Usage:
    python3 patch_fix_blueprint_name.py --dry-run
    python3 patch_fix_blueprint_name.py --apply
    python3 patch_fix_blueprint_name.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "re" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_blueprint_name_fix")

OLD_STRING = 'url_for("re_bp.regulators")'
NEW_STRING = 'url_for("re.regulators")'


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
    count = content.count(OLD_STRING)

    if count == 0:
        print("No occurrences of the broken reference found. Patch already applied or nothing to do.")
        return

    patched = content.replace(OLD_STRING, NEW_STRING)

    if args.dry_run:
        print(f"Found {count} occurrences of '{OLD_STRING}'.")
        print(f"Would replace all with '{NEW_STRING}'.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET} -- replaced {count} occurrences.")


if __name__ == "__main__":
    main()
