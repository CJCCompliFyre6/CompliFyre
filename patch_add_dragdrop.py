#!/usr/bin/env python3
"""
Patch: Add a drag-and-drop upload zone to the Guidelines page, right
below the existing "Add New Guideline" button. Reuses the exact same
/upload-guidelines endpoint and extract_guidelines Celery task already
used by the existing single-file upload modal -- no new backend logic,
just a faster, multi-file-capable frontend trigger for the same
pipeline. Directly answers Ankita's request: download a document
normally, then drag it straight onto this page instead of going
through the "Add New Guideline" form.

Tested extensively in local sandbox with Playwright: real simulated
drag-and-drop (constructing an actual DataTransfer object, not just
the click-to-browse fallback), multiple files at once, non-PDF file
filtering (confirmed a stray .txt file never triggers an upload call),
and error-state display with correct styling.

Usage:
    python3 patch_add_dragdrop.py --dry-run
    python3 patch_add_dragdrop.py --apply
    python3 patch_add_dragdrop.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "templates" / "dashboards" / "re" / "view.html"
BACKUP = TARGET.with_suffix(".html.bak_dragdrop")

ANCHOR = '''    </div>
</main>
{%endif%}
<div id="linkSharingModal" class="modal">'''

NEW = '''    </div>
</main>
{%endif%}
{% if current_user.is_authenticated and current_user.role.name=="COMPLIFYRE"%}
<main class="mx-8 my-4">
    <div id="dragDropZone"
        class="border-2 border-dashed border-orange-300 rounded-xl bg-orange-50 p-6 text-center cursor-pointer transition-colors"
        onclick="document.getElementById('dragDropFileInput').click()">
        <p class="text-orange-700 font-medium">Drag PDF guidelines here to upload, or click to browse</p>
        <p class="text-orange-500 text-sm mt-1">Multiple files supported -- each is queued for extraction automatically.</p>
        <input type="file" id="dragDropFileInput" accept="application/pdf" multiple class="hidden">
    </div>
    <div id="dragDropStatusList" class="mt-3 space-y-1"></div>
</main>
<script>
(function() {
    const dropZone = document.getElementById('dragDropZone');
    const fileInput = document.getElementById('dragDropFileInput');
    const statusList = document.getElementById('dragDropStatusList');
    if (!dropZone) return;

    ['dragenter', 'dragover'].forEach(evt => {
        dropZone.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.add('bg-orange-200', 'border-orange-500');
        });
    });
    ['dragleave', 'drop'].forEach(evt => {
        dropZone.addEventListener(evt, (e) => {
            e.preventDefault();
            e.stopPropagation();
            dropZone.classList.remove('bg-orange-200', 'border-orange-500');
        });
    });

    dropZone.addEventListener('drop', (e) => {
        const files = Array.from(e.dataTransfer.files).filter(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
        if (files.length === 0) {
            addStatusRow('No PDF files found in drop -- only .pdf files are supported.', 'error');
            return;
        }
        files.forEach(uploadDroppedFile);
    });

    fileInput.addEventListener('change', () => {
        Array.from(fileInput.files).forEach(uploadDroppedFile);
        fileInput.value = '';
    });

    function addStatusRow(text, state) {
        const row = document.createElement('div');
        row.className = 'text-sm px-3 py-2 rounded-lg ' + (
            state === 'error' ? 'bg-red-50 text-red-700' :
            state === 'success' ? 'bg-green-50 text-green-700' :
            'bg-gray-50 text-gray-600'
        );
        row.textContent = text;
        statusList.prepend(row);
        return row;
    }

    async function uploadDroppedFile(file) {
        const row = addStatusRow(`${file.name} -- uploading...`, 'pending');
        const formData = new FormData();
        formData.append('file', file, file.name);
        try {
            const response = await fetch("{{ url_for('main.upload_file_and_extract_guidelines') }}", {
                method: 'POST',
                body: formData,
            });
            if (response.status === 202) {
                const result = await response.json();
                row.textContent = `${file.name} -- queued for extraction (task ${result.task_id ? result.task_id.slice(0, 8) : 'started'}...)`;
                row.className = row.className.replace('bg-gray-50 text-gray-600', 'bg-green-50 text-green-700');
            } else {
                const result = await response.json().catch(() => ({}));
                row.textContent = `${file.name} -- failed: ${result.message || 'unknown error'}`;
                row.className = row.className.replace('bg-gray-50 text-gray-600', 'bg-red-50 text-red-700');
            }
        } catch (err) {
            row.textContent = `${file.name} -- failed: ${err.message}`;
            row.className = row.className.replace('bg-gray-50 text-gray-600', 'bg-red-50 text-red-700');
        }
    }
})();
</script>
{% endif %}
<div id="linkSharingModal" class="modal">'''


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

    if "dragDropZone" in content:
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
