#!/usr/bin/env python3
"""
Patch: Add a "Select Next 15 Pending" button to Tracked Guidelines --
per Ankita's request, this auto-selects the next 15 still-Pending rows
(in current sort/filter order) so she doesn't have to manually tick
each box, while leaving individual checkboxes available for manual
selection when needed. Pairs naturally with the existing 15-cap safety
fix (item #143), since this button can never select more than the
"Open Selected" limit allows.

Tested in local sandbox: correctly selects exactly 15 Pending rows and
skips non-Pending ones (e.g. Imported), correctly selects fewer than
15 when fewer are available (no error), and correctly resets and
re-selects on repeated clicks rather than accumulating.

Usage:
    python3 patch_add_select_pending.py --dry-run
    python3 patch_add_select_pending.py --apply
    python3 patch_add_select_pending.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "tracked_guidelines.html"
BACKUP = TARGET.with_suffix(".html.bak_select_pending")

ANCHOR = '''    <div class="mb-4 flex items-center gap-3">
        <input type="text" id="searchInput" oninput="filterTrackedTable()"
            placeholder="Search by title or regulator..."
            class="border rounded-lg px-4 py-2.5 w-full max-w-md">
        <button id="openSelectedBtn" onclick="openSelectedTracked()" disabled
            class="bg-gray-300 text-gray-500 font-medium px-5 py-2.5 rounded-lg whitespace-nowrap cursor-not-allowed">
            Open Selected (<span id="trackedSelectedCount">0</span>) in New Tabs
        </button>'''

NEW = '''    <div class="mb-4 flex items-center gap-3">
        <input type="text" id="searchInput" oninput="filterTrackedTable()"
            placeholder="Search by title or regulator..."
            class="border rounded-lg px-4 py-2.5 w-full max-w-md">
        <button id="selectPendingBtn" onclick="selectNext15Pending()"
            class="bg-blue-100 text-blue-700 hover:bg-blue-200 font-medium px-5 py-2.5 rounded-lg whitespace-nowrap">
            Select Next 15 Pending
        </button>
        <button id="openSelectedBtn" onclick="openSelectedTracked()" disabled
            class="bg-gray-300 text-gray-500 font-medium px-5 py-2.5 rounded-lg whitespace-nowrap cursor-not-allowed">
            Open Selected (<span id="trackedSelectedCount">0</span>) in New Tabs
        </button>'''

JS_INSERTION_POINT = "function updateTrackedSelectedCount() {"

NEW_JS_FUNCTION = '''function selectNext15Pending() {
    document.querySelectorAll('.tracked-row-checkbox').forEach(cb => cb.checked = false);
    const rows = document.querySelectorAll('#trackedTable tbody tr');
    let selected = 0;
    for (const row of rows) {
        if (selected >= 15) break;
        if (row.style.display === 'none') continue;
        const statusCell = row.querySelector('td:nth-child(3)');
        const isPending = statusCell && statusCell.textContent.trim().includes('Pending to be downloaded');
        if (isPending) {
            const checkbox = row.querySelector('.tracked-row-checkbox');
            if (checkbox) {
                checkbox.checked = true;
                selected++;
            }
        }
    }
    updateTrackedSelectedCount();
}

'''


def apply_patch(content):
    count = content.count(ANCHOR)
    if count != 1:
        print(f"ERROR: header anchor matched {count} times (expected 1). Aborting.")
        sys.exit(1)
    count2 = content.count(JS_INSERTION_POINT)
    if count2 != 1:
        print(f"ERROR: JS insertion anchor matched {count2} times (expected 1). Aborting.")
        sys.exit(1)
    content = content.replace(ANCHOR, NEW)
    content = content.replace(JS_INSERTION_POINT, NEW_JS_FUNCTION + JS_INSERTION_POINT)
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

    if "selectNext15Pending" in content:
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
