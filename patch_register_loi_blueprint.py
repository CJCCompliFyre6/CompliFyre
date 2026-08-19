#!/usr/bin/env python3
"""
Patch: register the new loi_bp blueprint in app/__init__.py, matching
the exact existing pattern used for every other blueprint.

Usage:
    python3 patch_register_loi_blueprint.py --dry-run
    python3 patch_register_loi_blueprint.py --apply
    python3 patch_register_loi_blueprint.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "__init__.py"
BACKUP = TARGET.with_suffix(".py.bak_loi_blueprint")

ANCHOR = '    app.register_blueprint(re_bp, url_prefix="/re")'
NEW = '''    app.register_blueprint(re_bp, url_prefix="/re")
    from app.routes.loi.view import loi_bp
    app.register_blueprint(loi_bp, url_prefix="/loi")'''


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

    if "from app.routes.loi.view import loi_bp" in content:
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
