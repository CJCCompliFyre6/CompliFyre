#!/usr/bin/env python3
"""
Patch: Add scan_watch_folder() -- a periodic Celery task that scans a
designated watch_intake/ folder tree for new PDF files and triggers the
same extract_guidelines() ingestion pipeline used for manual uploads.

Design (discussed and confirmed before implementation, per Rule 1):
  - Watch folder is watch_intake/ (sibling to uploads/, same relative-path
    convention already used by _safe_get_upload_folder()). Subfolders are
    supported and walked recursively, purely for the user's own
    organization -- no functional meaning to the code.
  - Runs every 5 minutes via Celery Beat (matches the existing
    "fix-pending-checklists-every-5-min" convention already in
    celery_app.py -- see the companion celery_app.py patch).
  - Routed to the existing "extract_guidelines" queue rather than a new
    dedicated queue, since celery-staging.service's worker uses a fixed
    -Q list and this avoids any systemd/infrastructure changes -- pure
    code + Celery config, our established low-risk pattern.
  - Deduplication uses SHA-256 hash comparison against the existing
    File.hash column (the same field already used for upload dedup in
    extract_guidelines() itself) -- robust across scan cycles and service
    restarts, not dependent on filesystem state alone.
  - Every scanned PDF (whether newly queued or an already-ingested
    duplicate) gets moved to watch_intake/_processed/ so the same file
    is never rescanned indefinitely. Filename collisions in _processed/
    are handled by appending a hash suffix -- verified to never overwrite
    or lose data.
  - Deliberately stops at structure-map review, same as every manual
    upload tonight -- this automates the *ingestion trigger*, not the
    human review step.

Core scanning logic was tested in isolation (new files, subfolder walking,
duplicate-by-hash detection and skipping, idempotent rescans, filename
collision handling) before this integration patch was written.

Usage:
    python3 patch_watch_folder_task.py --dry-run
    python3 patch_watch_folder_task.py --apply
    python3 patch_watch_folder_task.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "manual_task.py"
BACKUP = TARGET.with_suffix(".py.bak_watch_folder_task")

TASK_FUNC = '''@shared_task(bind=True)
def scan_watch_folder(self):
    """
    Periodic task (see celery_app.py beat_schedule): scans the watch_intake/
    folder tree for new PDF files and triggers the same extract_guidelines()
    ingestion pipeline used for manual uploads -- stops at structure-map
    review, does not auto-extract. Uses SHA-256 hash comparison against
    File.hash (the same field already used for upload deduplication) to
    avoid re-ingesting a file already in the system, even across scan
    cycles or service restarts. Successfully-scanned files (whether newly
    queued or already-ingested duplicates) are moved to watch_intake/
    _processed/ so they aren't rescanned indefinitely.
    """
    import shutil as _shutil
    watch_dir = "watch_intake"
    if not os.path.isdir(watch_dir):
        logger.info(f"[WatchFolder] {watch_dir} does not exist -- nothing to scan")
        return {"scanned": 0, "queued": 0}

    processed_dir = os.path.join(watch_dir, "_processed")
    os.makedirs(processed_dir, exist_ok=True)

    scanned = 0
    queued = 0
    for root, dirs, files in os.walk(watch_dir):
        if os.path.abspath(root).startswith(os.path.abspath(processed_dir)):
            continue
        for fname in files:
            if not fname.lower().endswith(".pdf"):
                continue
            scanned += 1
            full_path = os.path.join(root, fname)
            with open(full_path, "rb") as f:
                content = f.read()
            file_hash = hashlib.sha256(content).hexdigest()

            existing = File.query.filter_by(hash=file_hash).first()
            if existing:
                logger.info(f"[WatchFolder] {fname} already ingested (hash match, file_id={existing.id}) -- skipping")
            else:
                extract_guidelines.delay(fname, content)
                logger.info(f"[WatchFolder] Queued {fname} for ingestion")
                queued += 1

            dest_path = os.path.join(processed_dir, fname)
            if os.path.exists(dest_path):
                base, ext = os.path.splitext(fname)
                dest_path = os.path.join(processed_dir, f"{base}_{file_hash[:8]}{ext}")
            _shutil.move(full_path, dest_path)

    logger.info(f"[WatchFolder] Scan complete: {scanned} PDFs found, {queued} newly queued")
    return {"scanned": scanned, "queued": queued}


'''

ANCHOR_DECORATOR = "@shared_task(bind=True)"
ANCHOR_DEF = "def extract_guidelines("


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

    if "def scan_watch_folder(self):" in full_text:
        print("Patch already applied. Nothing to do.")
        return

    sig_idx = None
    for i in range(len(lines) - 1):
        if lines[i].rstrip("\n") == ANCHOR_DECORATOR and lines[i + 1].lstrip().startswith(ANCHOR_DEF):
            sig_idx = i
            break
    if sig_idx is None:
        print("ERROR: could not find the @shared_task(bind=True) / def extract_guidelines( pair. Aborting.")
        sys.exit(1)

    out = []
    for i, line in enumerate(lines):
        if i == sig_idx:
            out.append(TASK_FUNC)
            out.append(line)
            continue
        out.append(line)

    new_content = "".join(out)

    if args.dry_run:
        print(f"Anchor found at line {sig_idx+1} (extract_guidelines decorator+def).")
        print("Would insert scan_watch_folder() task function right before it.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(new_content)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
