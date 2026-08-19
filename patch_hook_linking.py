#!/usr/bin/env python3
"""
Patch: Call try_link_tracked_guideline() right after a new Guidelines
row is created and its DocumentName is known, so newly-uploaded
guidelines get automatically linked to a matching Tracked Guidelines
entry (if one exists and matches confidently enough).

Usage:
    python3 patch_hook_linking.py --dry-run
    python3 patch_hook_linking.py --apply
    python3 patch_hook_linking.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "manual_task.py"
BACKUP = TARGET.with_suffix(".py.bak_hook_linking")

ANCHOR = '''            doc_name = (
                guidelines_result_json.get("DocumentDetails", {}).get("DocumentName")
                if guidelines_result_json else None
            ) or "Untitled_Guideline"
            new_filename = _build_guideline_filename(guideline_id, doc_name)'''

NEW = '''            doc_name = (
                guidelines_result_json.get("DocumentDetails", {}).get("DocumentName")
                if guidelines_result_json else None
            ) or "Untitled_Guideline"
            try:
                from app.services.check_guidelines_service import try_link_tracked_guideline
                linked = try_link_tracked_guideline(guideline_id, doc_name)
                if linked:
                    logger.info(f"[TrackedGuidelines] Linked guideline_id={guideline_id} to tracked document_id={linked.document_id}")
            except Exception as link_err:
                logger.warning(f"[TrackedGuidelines] Could not attempt auto-link: {link_err}")
            new_filename = _build_guideline_filename(guideline_id, doc_name)'''


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

    if "[TrackedGuidelines] Linked guideline_id" in content:
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
