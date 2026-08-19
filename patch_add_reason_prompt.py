#!/usr/bin/env python3
"""
Patch: When toggleEnabled() is about to DISABLE a guideline (detected
via the existing data-enabled="true" attribute already on the button),
prompt for an optional reason and send it along with the toggle
request. No prompt shown when re-enabling, since a reason only makes
sense for the disable direction.

Usage:
    python3 patch_add_reason_prompt.py --dry-run
    python3 patch_add_reason_prompt.py --apply
    python3 patch_add_reason_prompt.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "view.html"
BACKUP = TARGET.with_suffix(".html.bak_reason_prompt")

ANCHOR = '''        function toggleEnabled(guidelineId, btnElem) {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");

            fetch(`/re/guideline/${guidelineId}/toggle_enabled`, {
                method: "POST",
                headers: {'''

NEW = '''        function toggleEnabled(guidelineId, btnElem) {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content");

            const isCurrentlyEnabled = btnElem.dataset.enabled === "true";
            let reason = null;
            if (isCurrentlyEnabled) {
                reason = prompt("Reason for disabling this guideline (e.g. 'Withdrawn -- superseded by Circular X'). Leave blank if not applicable:");
                if (reason === null) return; // user clicked Cancel
            }

            fetch(`/re/guideline/${guidelineId}/toggle_enabled`, {
                method: "POST",
                headers: {'''

BODY_ANCHOR = "body: JSON.stringify({})"
BODY_NEW = "body: JSON.stringify({ reason: reason })"


def apply_patch(content):
    count = content.count(ANCHOR)
    if count != 1:
        print(f"ERROR: header anchor matched {count} times (expected 1). Aborting.")
        sys.exit(1)
    count2 = content.count(BODY_ANCHOR)
    if count2 != 1:
        print(f"ERROR: body anchor matched {count2} times (expected 1). Aborting.")
        sys.exit(1)
    content = content.replace(ANCHOR, NEW)
    content = content.replace(BODY_ANCHOR, BODY_NEW)
    return content


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

    if "isCurrentlyEnabled" in content:
        print("Patch already applied. Nothing to do.")
        return

    patched = apply_patch(content)

    if args.dry_run:
        print("Both anchors matched exactly once.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
