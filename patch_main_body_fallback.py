#!/usr/bin/env python3
"""
Patch: Add a Stage 1A fallback in generate_structure_map()
(app/services/manual_task.py) for documents with zero Chapter/Schedule/
Annexure/Appendix headings anywhere -- creates a single 'main_body'
section spanning the whole document, so it flows into the existing
extract-decision LLM step and Stage 1B parser (pdf_structure_parser.py)
exactly like any other detected section.

Root cause of the gap: generate_structure_map() only recognizes
Chapter/Schedule/Annexure/Appendix-keyword headings. Some RBI departments
(confirmed: Financial Markets Regulation Department, e.g. Master
Direction - Reserve Bank of India (Credit Derivatives) Directions, 2026)
use plain decimal-numbered sections instead, with zero occurrences of
any of those keywords -- confirmed via direct regex count against the
full document text. Without any headings detected, sections_with_pages
stays empty and the structure map comes back with 0 sections, even
though pdf_structure_parser.py already has full, tested support for a
'main_body' section type (build_clause_no, build_prefix_from_section,
and the main parsing loop all already handle it) -- that support was
just never reachable because Stage 1A never produced a main_body
section to feed it.

This fix only activates when NO headings were found via the normal
path -- documents that do have Chapter-style structure are completely
unaffected.

Usage:
    python3 patch_main_body_fallback.py --dry-run
    python3 patch_main_body_fallback.py --apply
    python3 patch_main_body_fallback.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "manual_task.py"
BACKUP = TARGET.with_suffix(".py.bak_main_body_fallback")

OLD_BLOCK = """            sections_with_pages.append({
                "page": start_page,
                "start_page": start_page,
                "end_page": end_page,
                "type": sec_type,
                "id": sec_id,
                "label": label_part[:80],
                "heading_raw": heading_text,
            })

        # Ask LLM only to decide extract:true/false for each section"""

NEW_BLOCK = """            sections_with_pages.append({
                "page": start_page,
                "start_page": start_page,
                "end_page": end_page,
                "type": sec_type,
                "id": sec_id,
                "label": label_part[:80],
                "heading_raw": heading_text,
            })

        if not sections_with_pages:
            logger.warning(
                f"Stage 1A: No Chapter/Schedule/Annexure/Appendix headings found anywhere "
                f"in {total_pages} pages -- falling back to a single main_body section "
                f"spanning the whole document"
            )
            sections_with_pages.append({
                "page": 1,
                "start_page": 1,
                "end_page": total_pages,
                "type": "main_body",
                "id": "",
                "label": "Main Document Body (no Chapter/Schedule structure detected)",
                "heading_raw": "MAIN BODY",
            })

        # Ask LLM only to decide extract:true/false for each section"""


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

    if "falling back to a single main_body section" in content:
        print("Patch already applied. Nothing to do.")
        return

    if OLD_BLOCK not in content:
        print("ERROR: expected OLD_BLOCK not found verbatim in file.")
        print("The file may have changed since this script was written. Aborting.")
        sys.exit(1)

    count = content.count(OLD_BLOCK)
    if count != 1:
        print(f"ERROR: OLD_BLOCK matched {count} times (expected exactly 1). Aborting for safety.")
        sys.exit(1)

    patched = content.replace(OLD_BLOCK, NEW_BLOCK)

    if args.dry_run:
        print("=== DRY RUN: would insert main_body fallback block ===")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nRestart complifyre-staging + celery-staging, then regenerate the structure map")
        print("for guideline 222 and confirm a single main_body section now appears.")


if __name__ == "__main__":
    main()
