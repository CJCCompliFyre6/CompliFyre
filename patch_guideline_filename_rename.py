#!/usr/bin/env python3
"""
Patch: Rename guideline PDFs from random hash filenames to human-readable
names derived from guideline_id + DocumentName, immediately after the
Guidelines DB record is created (the earliest point both values exist
together) in extract_guidelines() (app/services/manual_task.py).

Root problem: uploaded PDFs are saved with a random hash filename
(os.urandom(8).hex() + '.pdf', e.g. 'a11e99bafa52fed8.pdf') at upload time,
before any guideline_id or DocumentName exists. This makes it impossible
to identify which file corresponds to which guideline just by browsing
the uploads/ directory -- confirmed as a real pain point across tonight's
session, where every file lookup required querying the database.

Fix: immediately after the Guidelines record is committed and guideline_id
is known, rename the file on disk to '{guideline_id}_{sanitized_document_
name}.pdf' and update the stored File.path to match. Uses werkzeug's
existing secure_filename() (already used elsewhere in this codebase, per
Rule 15 -- reuse before rebuilding) for sanitization, with word-boundary-
aware truncation (never cuts a word in half) and a guideline_id prefix
that guarantees uniqueness even for two guidelines with identical titles.

Failure-safe by design: if the rename fails for any reason (permissions,
disk issue), it's logged as a warning and the guideline still saves
successfully with its original hash filename -- this is a cosmetic
improvement, never a blocker for the actual upload.

Tested locally against a fixture reproducing the exact real code
structure: normal rename (verified old file gone, new file exists, DB
path updated), simulated rename failure (verified non-fatal, original
file untouched), and missing/empty DocumentDetails (verified sensible
fallback filename, no crash).

Usage:
    python3 patch_guideline_filename_rename.py --dry-run
    python3 patch_guideline_filename_rename.py --apply
    python3 patch_guideline_filename_rename.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "manual_task.py"
BACKUP = TARGET.with_suffix(".py.bak_guideline_filename_rename")

HELPER_FUNC = '''def _build_guideline_filename(guideline_id, document_name, max_len=100):
    """
    Build a human-readable, filesystem-safe filename for a guideline PDF, e.g.
    '223_Reserve_Bank_of_India_Commercial_Banks_Know_Your_Customer_Directions.pdf'.
    Prefixed with guideline_id for guaranteed uniqueness even if two guidelines
    share an identical DocumentName. Truncates at a word boundary, never mid-word.
    """
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(document_name) or "Untitled_Guideline"
    prefix = f"{guideline_id}_"
    budget = max_len - len(prefix) - len(".pdf")
    if budget < 10:
        budget = 10
    if len(safe_name) > budget:
        truncated = safe_name[:budget]
        last_underscore = truncated.rfind("_")
        if last_underscore > budget * 0.5:
            truncated = truncated[:last_underscore]
        safe_name = truncated.rstrip("_")
    return f"{prefix}{safe_name}.pdf"


'''

ANCHOR_DECORATOR = "@shared_task(bind=True)"
ANCHOR_DEF = "def extract_guidelines("
ANCHOR_IDS_LINE1 = "            file_id = file_record.id"
ANCHOR_IDS_LINE2 = "            guideline_id = guideline_record.id"

RENAME_BLOCK = '''            file_id = file_record.id
            guideline_id = guideline_record.id

            # Rename the saved PDF from its random hash name to a human-readable
            # name derived from guideline_id + DocumentName, so files on disk map
            # 1:1 to guidelines just by looking at the filename. Non-fatal on
            # failure -- the guideline still saves successfully either way.
            doc_name = (
                guidelines_result_json.get("DocumentDetails", {}).get("DocumentName")
                if guidelines_result_json else None
            ) or "Untitled_Guideline"
            new_filename = _build_guideline_filename(guideline_id, doc_name)
            new_path_rel = os.path.join(os.path.dirname(save_path), new_filename)
            try:
                os.rename(save_path, new_path_rel)
                file_record.path = new_path_rel
                logger.info(f"Renamed guideline PDF to: {new_filename}")
            except OSError as e:
                logger.warning(f"Could not rename PDF file (keeping original hash name): {e}")'''


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

    if "_build_guideline_filename" in full_text:
        print("Patch already applied. Nothing to do.")
        return

    # Find the decorator+def pair for extract_guidelines (must be adjacent, decorator then def)
    sig_idx = None
    for i in range(len(lines) - 1):
        if lines[i].rstrip("\n") == ANCHOR_DECORATOR and lines[i + 1].lstrip().startswith(ANCHOR_DEF):
            sig_idx = i
            break
    if sig_idx is None:
        print("ERROR: could not find the @shared_task(bind=True) / def extract_guidelines( pair. Aborting.")
        sys.exit(1)

    # Find the two-line "file_id = ... / guideline_id = ..." combo, unique in the file
    ids_idx = None
    for i in range(len(lines) - 1):
        if lines[i].rstrip("\n") == ANCHOR_IDS_LINE1 and lines[i + 1].rstrip("\n") == ANCHOR_IDS_LINE2:
            ids_idx = i
            break
    if ids_idx is None:
        print("ERROR: could not find the file_id/guideline_id assignment lines. Aborting.")
        sys.exit(1)

    out = []
    for i, line in enumerate(lines):
        if i == sig_idx:
            out.append(HELPER_FUNC)
            out.append(line)
            continue
        if i == ids_idx:
            out.append(RENAME_BLOCK + "\n")
            continue
        if i == ids_idx + 1:
            continue  # already emitted as part of RENAME_BLOCK
        out.append(line)

    new_content = "".join(out)

    if args.dry_run:
        print(f"Anchors found: decorator/def at line {sig_idx+1}, file_id/guideline_id at line {ids_idx+1}")
        print("Would insert _build_guideline_filename() helper before extract_guidelines(),")
        print("and the rename block right after guideline_id is assigned.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(new_content)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nRestart complifyre-staging + celery-staging, then upload a test PDF")
        print("and confirm the saved file on disk has a human-readable name, not a hash.")


if __name__ == "__main__":
    main()
