#!/usr/bin/env python3
"""
Patch: Show a "View in Guidelines" link on Tracked Guidelines rows that
have been auto-linked to a real Guidelines row (guideline_id set by
try_link_tracked_guideline() on upload).

Usage:
    python3 patch_view_in_guidelines_link.py --dry-run
    python3 patch_view_in_guidelines_link.py --apply
    python3 patch_view_in_guidelines_link.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "tracked_guidelines.html"
BACKUP = TARGET.with_suffix(".html.bak_view_in_guidelines")

ANCHOR = '''                        {% else %}
                        <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700">{{ doc.pipeline_status }}</span>
                        {% endif %}
                    </td>'''

NEW = '''                        {% else %}
                        <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-700">{{ doc.pipeline_status }}</span>
                        {% endif %}
                        {% if doc.guideline_id %}
                        <div class="mt-1">
                            <a href="{{ url_for('re.guidelines') }}" class="text-xs text-blue-600 hover:underline">View in Guidelines &rarr;</a>
                        </div>
                        {% endif %}
                    </td>'''


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

    if "View in Guidelines" in content:
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
