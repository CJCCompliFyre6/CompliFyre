#!/usr/bin/env python3
"""
Patch: Add checkboxes + "Select All" + "Open Selected" to the Tracked
Guidelines page, so Ankita can select a batch (e.g. 10-15) of documents
and open all their source links in new tabs at once, for manual
download-and-drag-drop workflow. Added as the LAST column, not the
first, specifically to avoid disrupting the existing sortTrackedTable()
column-index logic (Regulator=0, Title=1, Discovered=3), which would
otherwise need updating too.

All window.open() calls fire synchronously within the single click
handler -- the pattern most likely to avoid browser popup-blocking,
since blockers generally only intervene on calls fired asynchronously
after the triggering user gesture. The exact number that successfully
opens still depends on the user's own browser popup-blocker settings,
which this cannot fully control or guarantee.

Usage:
    python3 patch_add_open_selected.py --dry-run
    python3 patch_add_open_selected.py --apply
    python3 patch_add_open_selected.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "tracked_guidelines.html"
BACKUP = TARGET.with_suffix(".html.bak_open_selected")

ANCHOR_SEARCHBAR = '''    <div class="mb-4">
        <input type="text" id="searchInput" oninput="filterTrackedTable()"
            placeholder="Search by title or regulator..."
            class="border rounded-lg px-4 py-2.5 w-full max-w-md">
    </div>'''

NEW_SEARCHBAR = '''    <div class="mb-4 flex items-center gap-3">
        <input type="text" id="searchInput" oninput="filterTrackedTable()"
            placeholder="Search by title or regulator..."
            class="border rounded-lg px-4 py-2.5 w-full max-w-md">
        <button id="openSelectedBtn" onclick="openSelectedTracked()" disabled
            class="bg-gray-300 text-gray-500 font-medium px-5 py-2.5 rounded-lg whitespace-nowrap cursor-not-allowed">
            Open Selected (<span id="trackedSelectedCount">0</span>) in New Tabs
        </button>
    </div>'''

ANCHOR_HEADER = '''                    <th class="p-3 font-bold text-gray-700">Link</th>
                </tr>
            </thead>'''

NEW_HEADER = '''                    <th class="p-3 font-bold text-gray-700">Link</th>
                    <th class="p-3"><input type="checkbox" id="selectAllTracked" onclick="toggleSelectAllTracked()"></th>
                </tr>
            </thead>'''

ANCHOR_ROW = '''                    <td class="p-3">
                        <a href="{{ doc.source_url }}" target="_blank" class="text-blue-600 hover:underline text-sm">Open</a>
                    </td>
                </tr>'''

NEW_ROW = '''                    <td class="p-3">
                        <a href="{{ doc.source_url }}" target="_blank" class="text-blue-600 hover:underline text-sm">Open</a>
                    </td>
                    <td class="p-3">
                        <input type="checkbox" class="tracked-row-checkbox" value="{{ doc.source_url }}" onclick="updateTrackedSelectedCount()">
                    </td>
                </tr>'''

ANCHOR_SCRIPT_END = '''function filterTrackedTable() {
    const input = document.getElementById('searchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#trackedTable tbody tr');
    rows.forEach(row => {
        const text = row.innerText.toLowerCase();
        row.style.display = text.includes(input) ? '' : 'none';
    });
}'''

NEW_SCRIPT_END = '''function filterTrackedTable() {
    const input = document.getElementById('searchInput').value.toLowerCase();
    const rows = document.querySelectorAll('#trackedTable tbody tr');
    rows.forEach(row => {
        const text = row.innerText.toLowerCase();
        row.style.display = text.includes(input) ? '' : 'none';
    });
}

function toggleSelectAllTracked() {
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


def apply_patch(content):
    for name, anchor in [
        ("SEARCHBAR", ANCHOR_SEARCHBAR),
        ("HEADER", ANCHOR_HEADER),
        ("ROW", ANCHOR_ROW),
        ("SCRIPT_END", ANCHOR_SCRIPT_END),
    ]:
        count = content.count(anchor)
        if count != 1:
            print(f"ERROR: anchor '{name}' matched {count} times (expected 1). Aborting.")
            sys.exit(1)
    content = content.replace(ANCHOR_SEARCHBAR, NEW_SEARCHBAR)
    content = content.replace(ANCHOR_HEADER, NEW_HEADER)
    content = content.replace(ANCHOR_ROW, NEW_ROW)
    content = content.replace(ANCHOR_SCRIPT_END, NEW_SCRIPT_END)
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

    if "openSelectedTracked" in content:
        print("Patch already applied. Nothing to do.")
        return

    patched = apply_patch(content)

    if args.dry_run:
        print("All 4 anchors matched exactly once.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
