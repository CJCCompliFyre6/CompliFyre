#!/usr/bin/env python3
"""
Patch: Update the docs for-loop to unpack the new joined columns
(linked_guideline_enabled, linked_guideline_disabled_reason), and show
a "Withdrawn" badge on linked rows whose Guidelines record has been
disabled -- reflecting the SAME flag shown on the Guidelines page,
not a separate one.

Usage:
    python3 patch_show_withdrawn_badge.py --dry-run
    python3 patch_show_withdrawn_badge.py --apply
    python3 patch_show_withdrawn_badge.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "tracked_guidelines.html"
BACKUP = TARGET.with_suffix(".html.bak_withdrawn_badge")

ANCHOR_LOOP = "{% for doc, regulator_name in docs %}"
NEW_LOOP = "{% for doc, regulator_name, linked_guideline_enabled, linked_guideline_disabled_reason in docs %}"

ANCHOR_LINK = '''                        {% if doc.guideline_id %}
                        <div class="mt-1">
                            <a href="{{ url_for('re.guidelines') }}" class="text-xs text-blue-600 hover:underline">View in Guidelines &rarr;</a>
                        </div>
                        {% endif %}'''

NEW_LINK = '''                        {% if doc.guideline_id %}
                        <div class="mt-1 flex items-center gap-2 flex-wrap">
                            <a href="{{ url_for('re.guidelines') }}" class="text-xs text-blue-600 hover:underline">View in Guidelines &rarr;</a>
                            {% if linked_guideline_enabled == false %}
                            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-600"
                                title="{{ linked_guideline_disabled_reason or 'No reason recorded' }}">
                                Withdrawn
                            </span>
                            {% endif %}
                        </div>
                        {% endif %}'''


def apply_patch(content):
    count = content.count(ANCHOR_LOOP)
    if count != 1:
        print(f"ERROR: loop anchor matched {count} times (expected 1). Aborting.")
        sys.exit(1)
    count2 = content.count(ANCHOR_LINK)
    if count2 != 1:
        print(f"ERROR: link anchor matched {count2} times (expected 1). Aborting.")
        sys.exit(1)
    content = content.replace(ANCHOR_LOOP, NEW_LOOP)
    content = content.replace(ANCHOR_LINK, NEW_LINK)
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

    if "linked_guideline_enabled" in content:
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
