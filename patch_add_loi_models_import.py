#!/usr/bin/env python3
"""
Patch: add the LOI models import to app/models/__init__.py, matching
the exact existing pattern used for every other model file.

Usage:
    python3 patch_add_loi_models_import.py --dry-run
    python3 patch_add_loi_models_import.py --apply
    python3 patch_add_loi_models_import.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "models" / "__init__.py"
BACKUP = TARGET.with_suffix(".py.bak_loi_import")

ANCHOR = "from .eve_models import ("

NEW = '''from .loi import (
    SignupInvites,
    InvitePreloadGuidelines,
    LoiTemplates,
    LoiSignatures,
    UserJourneyEvents,
    LoiForwardRequests,
    ExtensionRequests,
    EditableContent,
    LoiTriggerConfig,
    LoiGlobalConfig,
    GuidelineBundles,
    GuidelineBundleItems,
)
from .eve_models import ('''


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

    if "from .loi import" in content:
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
