#!/usr/bin/env python3
"""
Patch: Fix a real bug found live -- SEBI's stored circulars URL returns
a genuine HTTP 404 (SEBI likely reorganized their site since the URL
was researched). This wasn't caught as a block (block-detection only
checks 401/403/429/503) and the 404 error page's content (5200 bytes)
was well above the "suspiciously short" threshold, so it silently
passed through as "not blocked", got sent to the LLM, which correctly
found zero real documents on an error page -- reported as
{'status': 'SUCCESS', 'new_count': 0}, indistinguishable from a
genuinely clean check with nothing new.

Adds a distinct check_url_not_found() check, run BEFORE block
detection, with its own status "URL_NOT_FOUND" -- deliberately
separate from "BLOCKED", since a dead URL needs the URL corrected in
the regulator table, while an active block needs a manual-browser
workaround. Conflating them would send Ankita toward the wrong fix.

Usage:
    python3 patch_url_not_found.py --dry-run
    python3 patch_url_not_found.py --apply
    python3 patch_url_not_found.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "check_guidelines_service.py"
BACKUP = TARGET.with_suffix(".py.bak_url_not_found")

ANCHOR_FUNC = '''def detect_fetch_block(http_status, content_length, page_text):'''

NEW_FUNC = '''def check_url_not_found(http_status):
    """
    Distinct from detect_fetch_block: a 404/410 means the specific URL
    is wrong or moved, NOT that the site is blocking us. Different
    problem, different fix -- needs the URL corrected in the regulator
    table, not a manual-browser workaround.
    """
    if http_status in (404, 410):
        return True, f"HTTP {http_status} -- this URL no longer exists, the regulator likely moved or renamed this page"
    return False, None


def detect_fetch_block(http_status, content_length, page_text):'''

ANCHOR_FLOW = '''    is_blocked, block_reason = detect_fetch_block(http_status, content_length, page_text_or_error)
    if is_blocked:
        regulator.last_check_status = "BLOCKED"
        regulator.last_checked_at = datetime.now(timezone.utc)
        regulator.last_check_notes = block_reason
        db.session.commit()
        logger.warning(f"[CheckGuidelines] {regulator.name}: BLOCKED -- {block_reason}")
        return {"status": "BLOCKED", "reason": block_reason}'''

NEW_FLOW = '''    url_not_found, not_found_reason = check_url_not_found(http_status)
    if url_not_found:
        regulator.last_check_status = "URL_NOT_FOUND"
        regulator.last_checked_at = datetime.now(timezone.utc)
        regulator.last_check_notes = not_found_reason
        db.session.commit()
        logger.warning(f"[CheckGuidelines] {regulator.name}: URL_NOT_FOUND -- {not_found_reason}")
        return {"status": "URL_NOT_FOUND", "reason": not_found_reason}

    is_blocked, block_reason = detect_fetch_block(http_status, content_length, page_text_or_error)
    if is_blocked:
        regulator.last_check_status = "BLOCKED"
        regulator.last_checked_at = datetime.now(timezone.utc)
        regulator.last_check_notes = block_reason
        db.session.commit()
        logger.warning(f"[CheckGuidelines] {regulator.name}: BLOCKED -- {block_reason}")
        return {"status": "BLOCKED", "reason": block_reason}'''


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

    if "def check_url_not_found" in content:
        print("Patch already applied. Nothing to do.")
        return

    for name, anchor in [("FUNC", ANCHOR_FUNC), ("FLOW", ANCHOR_FLOW)]:
        count = content.count(anchor)
        if count != 1:
            print(f"ERROR: anchor '{name}' matched {count} times (expected 1). Aborting.")
            sys.exit(1)

    patched = content.replace(ANCHOR_FUNC, NEW_FUNC)
    patched = patched.replace(ANCHOR_FLOW, NEW_FLOW)

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
