#!/usr/bin/env python3
"""
Patch: Fix a real safety issue found live -- the "Select All" checkbox
on Tracked Guidelines selected ALL rows in a potentially hundreds-long
filtered list (Ankita saw "Open Selected (451)"), which would have
frozen or crashed her browser if clicked. Unlike the Regulator Sources
page (a bounded ~29 rows, safe to select-all), this table has no such
bound, so "select all" doesn't make sense here at all.

Two fixes:
1. Remove the "Select All" header checkbox entirely -- selection here
   should always be a deliberate, small, manual choice.
2. Replace the soft "confirm to override" warning at 20 with a HARD
   CAP at 15 (matching Ankita's own stated "10-15 at a time" request)
   that refuses outright and asks her to narrow the selection, rather
   than a confirm() dialog that's too easy to click through without
   registering the real risk.

Usage:
    python3 patch_fix_select_all_safety.py --dry-run
    python3 patch_fix_select_all_safety.py --apply
    python3 patch_fix_select_all_safety.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "tracked_guidelines.html"
BACKUP = TARGET.with_suffix(".html.bak_selectall_safety")

ANCHOR_HEADER = '''                    <th class="p-3"><input type="checkbox" id="selectAllTracked" onclick="toggleSelectAllTracked()"></th>'''
NEW_HEADER = '''                    <th class="p-3">Select</th>'''

ANCHOR_JS = '''function toggleSelectAllTracked() {
    const selectAll = document.getElementById('selectAllTracked');
    const checkboxes = document.querySelectorAll('.tracked-row-checkbox');
    checkboxes.forEach(cb => {
        if (cb.closest('tr').style.display !== 'none') {
            cb.checked = selectAll.checked;
        }
    });
    updateTrackedSelectedCount();
}

function updateTrackedSelectedCount() {
    const count = document.querySelectorAll('.tracked-row-checkbox:checked').length;
    document.getElementById('trackedSelectedCount').textContent = count;
    const btn = document.getElementById('openSelectedBtn');
    if (count > 0) {
        btn.disabled = false;
        btn.classList.remove('bg-gray-300', 'text-gray-500', 'cursor-not-allowed');
        btn.classList.add('bg-orange-500', 'hover:bg-orange-600', 'text-white');
    } else {
        btn.disabled = true;
        btn.classList.add('bg-gray-300', 'text-gray-500', 'cursor-not-allowed');
        btn.classList.remove('bg-orange-500', 'hover:bg-orange-600', 'text-white');
    }
}

function openSelectedTracked() {
    const checked = document.querySelectorAll('.tracked-row-checkbox:checked');
    if (checked.length > 20) {
        if (!confirm(`You've selected ${checked.length} documents. Most browsers may block opening this many tabs at once. Continue anyway?`)) {
            return;
        }
    }
    // Fire every window.open() synchronously within this single click
    // handler -- browsers generally only block popups triggered
    // asynchronously after the initiating user gesture, so this is the
    // pattern most likely to open all of them successfully. The exact
    // number that succeeds still depends on your browser's own
    // popup-blocker settings.
    checked.forEach(cb => window.open(cb.value, '_blank'));
}'''

NEW_JS = '''function updateTrackedSelectedCount() {
    const count = document.querySelectorAll('.tracked-row-checkbox:checked').length;
    document.getElementById('trackedSelectedCount').textContent = count;
    const btn = document.getElementById('openSelectedBtn');
    if (count > 0) {
        btn.disabled = false;
        btn.classList.remove('bg-gray-300', 'text-gray-500', 'cursor-not-allowed');
        btn.classList.add('bg-orange-500', 'hover:bg-orange-600', 'text-white');
    } else {
        btn.disabled = true;
        btn.classList.add('bg-gray-300', 'text-gray-500', 'cursor-not-allowed');
        btn.classList.remove('bg-orange-500', 'hover:bg-orange-600', 'text-white');
    }
}

// Hard cap, not a soft confirm-to-override warning -- opening dozens
// or hundreds of tabs at once can genuinely freeze or crash a browser,
// so this refuses outright rather than tempting a quick "OK" click
// past a risk that's easy to underestimate in the moment.
const MAX_TABS_AT_ONCE = 15;

function openSelectedTracked() {
    const checked = document.querySelectorAll('.tracked-row-checkbox:checked');
    if (checked.length === 0) return;
    if (checked.length > MAX_TABS_AT_ONCE) {
        alert(`You've selected ${checked.length} documents. To keep your browser responsive, please select ${MAX_TABS_AT_ONCE} or fewer at a time -- use the search box to narrow the list, or uncheck some rows.`);
        return;
    }
    // Fire every window.open() synchronously within this single click
    // handler -- browsers generally only block popups triggered
    // asynchronously after the initiating user gesture, so this is the
    // pattern most likely to open all of them successfully.
    checked.forEach(cb => window.open(cb.value, '_blank'));
}'''


def apply_patch(content):
    for name, anchor in [("HEADER", ANCHOR_HEADER), ("JS", ANCHOR_JS)]:
        count = content.count(anchor)
        if count != 1:
            print(f"ERROR: anchor '{name}' matched {count} times (expected 1). Aborting.")
            sys.exit(1)
    content = content.replace(ANCHOR_HEADER, NEW_HEADER)
    content = content.replace(ANCHOR_JS, NEW_JS)
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

    if "MAX_TABS_AT_ONCE" in content:
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
