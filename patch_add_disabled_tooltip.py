#!/usr/bin/env python3
"""
Patch: Enhance the existing "DISABLED" badge on the Guidelines table
to show the reason (and date) on hover, using the disabled_reason and
disabled_at fields captured by the extended toggle route. The badge
itself already existed; it just had no way to show WHY.

Usage:
    python3 patch_add_disabled_tooltip.py --dry-run
    python3 patch_add_disabled_tooltip.py --apply
    python3 patch_add_disabled_tooltip.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "view.html"
BACKUP = TARGET.with_suffix(".html.bak_disabled_tooltip")

ANCHOR = '''                            {% if not item.enabled %}
                            <span class="ml-2 text-xs px-2 py-0.5 bg-red-100 text-red-600 rounded-full font-semibold">DISABLED</span>
                            {% endif %}'''

NEW = '''                            {% if not item.enabled %}
                            <span class="ml-2 text-xs px-2 py-0.5 bg-red-100 text-red-600 rounded-full font-semibold"
                                title="{% if item.disabled_reason %}{{ item.disabled_reason }}{% else %}No reason recorded{% endif %}{% if item.disabled_at %} (disabled {{ item.disabled_at.strftime('%d %b %Y') }}){% endif %}">
                                DISABLED{% if item.disabled_reason %} &mdash; {{ item.disabled_reason[:40] }}{% if item.disabled_reason|length > 40 %}...{% endif %}{% endif %}
                            </span>
                            {% endif %}'''


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

    if "No reason recorded" in content:
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
