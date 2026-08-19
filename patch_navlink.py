#!/usr/bin/env python3
"""
Patch: Add a "Regulator Sources" navigation link to the sidebar
(app/templates/dashboards/re/audit_base.html), visible only to the
COMPLIFYRE role, positioned directly above the "Guidelines" submenu --
per Ankita's explicit placement and visibility request.

The file contains TWO "Guidelines" submenu blocks with byte-identical
heading text: one inside the existing COMPLIFYRE-only {% if %} block
(the one we want), and a second inside a separate auditor-only
{% if current_user.auditor_profile_id %} block. Targets the FIRST
occurrence specifically by line index (not a text-count match), to
avoid any ambiguity between the two.

The new link sits inside the existing COMPLIFYRE-only {% if %} block
(opened earlier in the file, around the "Prompt" submenu) rather than
adding a new conditional -- confirmed via the surrounding markup that
this insertion point is already scoped to COMPLIFYRE only.

Usage:
    python3 patch_add_regulator_sources_navlink.py --dry-run
    python3 patch_add_regulator_sources_navlink.py --apply
    python3 patch_add_regulator_sources_navlink.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "audit_base.html"
BACKUP = TARGET.with_suffix(".html.bak_regulator_navlink")

TARGET_LINE = '            <i class="bx bx-book"></i> Guidelines <i class="bx bx-chevron-down"></i>'

NEW_NAVLINK = '''        <li><a href="{{ url_for('re.regulators') }}"><i class="bx bx-buildings"></i> Regulator Sources</a></li>
'''


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

    lines = TARGET.read_text().splitlines(keepends=True)
    full_text = "".join(lines)

    if "Regulator Sources" in full_text:
        print("Patch already applied. Nothing to do.")
        return

    matches = [i for i, l in enumerate(lines) if l.rstrip("\n") == TARGET_LINE]
    if len(matches) != 2:
        print(f"ERROR: expected exactly 2 occurrences of the Guidelines heading line, found {len(matches)}. Aborting.")
        sys.exit(1)

    first_idx = matches[0]
    # The <li class="submenu"> opening tag is 2 lines above the heading line
    # (submenu li, then <a onclick=...>, then the heading line itself).
    insert_idx = first_idx - 2
    if lines[insert_idx].strip() != '<li class="submenu">':
        print(f"ERROR: expected '<li class=\"submenu\">' 2 lines above the first Guidelines heading, found: {lines[insert_idx]!r}. Aborting.")
        sys.exit(1)

    out = lines[:insert_idx] + [NEW_NAVLINK] + lines[insert_idx:]
    new_content = "".join(out)

    if args.dry_run:
        print(f"First Guidelines heading found at line {first_idx+1}.")
        print(f"Would insert new nav link before line {insert_idx+1} ('<li class=\"submenu\">').")
        print("New line:")
        print(" ", NEW_NAVLINK.strip())
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(new_content)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
