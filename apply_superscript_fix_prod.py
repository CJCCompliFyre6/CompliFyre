#!/usr/bin/env python3
"""
Self-contained, idempotent patch for the number-dropping bug in
app/services/pdf_structure_parser.py (Stage 1 PDF parser).

Root cause: PATTERNS['superscript'] strips ANY isolated 1-4 digit number
surrounded by spaces (meant to remove PDF-extraction artifacts around real
footnote-citation markers like "etc.[8]"), but this shape is indistinguishable
from a legitimate spaced content-number like "minimum 100 per cent" — so it
silently deletes real regulatory threshold values.

Fix: cross-reference against a document-scanned set of CONFIRMED footnote
numbers (from actual footnote-definition lines like "8 Vide circulars...").
Only strip a number if it's a confirmed footnote marker; otherwise leave it.

Usage:
    python3 apply_superscript_fix.py --dry-run    # preview, no changes written
    python3 apply_superscript_fix.py               # apply + create .bak backup
    python3 apply_superscript_fix.py --rollback     # restore from .bak
"""
import argparse
import shutil
import sys

TARGET = "app/services/pdf_structure_parser.py"
BACKUP = TARGET + ".bak"

PATCHES = [
    # PATCH A — add collect_footnote_numbers(), gate strip_page_noise signature
    {
        "name": "A: add collect_footnote_numbers() + update strip_page_noise signature",
        "old": """def strip_page_noise(page_text):
    lines = page_text.split('\\n')""",
        "new": '''def collect_footnote_numbers(pdf):
    """Scan all pages for footnote-definition lines (e.g. '8 Vide circulars...',
    '3 Inserted by...') and return the set of genuinely-defined footnote numbers.
    Used to gate superscript-stripping so it never touches a number unless it's
    a confirmed real footnote — prevents legitimate inline values (e.g. '100 per
    cent') from being silently deleted by the superscript-cleanup heuristic."""
    footnote_numbers = set()
    footnote_def_pattern = re.compile(
        r'^\\s{0,4}(\\d{1,3})\\.?\\s+(Inserted|Substituted|Omitted|Added|Prior to|Deleted|Vide)\\b',
        re.IGNORECASE
    )
    for page in pdf.pages:
        text = page.extract_text() or ''
        for line in text.split('\\n'):
            m = footnote_def_pattern.match(line.strip())
            if m:
                footnote_numbers.add(m.group(1))
    return footnote_numbers


def strip_page_noise(page_text, footnote_numbers=None):
    footnote_numbers = footnote_numbers or set()
    lines = page_text.split('\\n')''',
    },
    # PATCH B — gate the superscript substitution itself
    {
        "name": "B: gate superscript substitution against footnote_numbers",
        "old": "    clean_text = PATTERNS['superscript'].sub(' ', clean_text)",
        "new": """    def _strip_superscript(m):
        digit = m.group(0).strip()
        if digit in footnote_numbers:
            return ' '          # confirmed footnote marker — strip as before
        return m.group(0)       # unknown number — leave untouched, it's content
    clean_text = PATTERNS['superscript'].sub(_strip_superscript, clean_text)""",
    },
    # PATCH C — compute footnote_numbers once per document
    {
        "name": "C: compute footnote_numbers after opening pdf_plumber",
        "old": """        pdf_plumber = pdfplumber.open(file_path)
        pdf_fitz = fitz.open(file_path)
        total_pages = len(pdf_fitz)
        logger.info(f"Stage 1: {total_pages} pages")
    except Exception as e:""",
        "new": """        pdf_plumber = pdfplumber.open(file_path)
        pdf_fitz = fitz.open(file_path)
        total_pages = len(pdf_fitz)
        logger.info(f"Stage 1: {total_pages} pages")
        footnote_numbers = collect_footnote_numbers(pdf_plumber)
        logger.info(f"Stage 1: {len(footnote_numbers)} confirmed footnote markers detected: {sorted(footnote_numbers)}")
    except Exception as e:""",
    },
    # PATCH D — thread footnote_numbers into the per-page call site
    {
        "name": "D: pass footnote_numbers into strip_page_noise call",
        "old": "            clean_text = strip_page_noise(raw_text)",
        "new": "            clean_text = strip_page_noise(raw_text, footnote_numbers)",
    },
]


def rollback():
    import os
    if not os.path.exists(BACKUP):
        print(f"No backup found at {BACKUP} — nothing to roll back.")
        sys.exit(1)
    shutil.copy(BACKUP, TARGET)
    print(f"Rolled back: restored {TARGET} from {BACKUP}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rollback", action="store_true")
    args = ap.parse_args()

    if args.rollback:
        rollback()
        return

    with open(TARGET, "r") as f:
        content = f.read()

    original_content = content
    for patch in PATCHES:
        count = content.count(patch["old"])
        if count == 0:
            print(f"ABORT — pattern not found for patch '{patch['name']}'.")
            print("The file may have changed since this script was written.")
            print("Not applying ANY changes. Re-confirm the exact source lines and update this script.")
            sys.exit(1)
        if count > 1:
            print(f"ABORT — pattern for patch '{patch['name']}' matches {count} times (expected exactly 1).")
            print("Ambiguous — not applying ANY changes.")
            sys.exit(1)
        content = content.replace(patch["old"], patch["new"], 1)
        print(f"OK — patch '{patch['name']}' matched exactly once.")

    if args.dry_run:
        print("\\n--dry-run: all patches would apply cleanly. No files written.")
        return

    shutil.copy(TARGET, BACKUP)
    with open(TARGET, "w") as f:
        f.write(content)
    print(f"\\nApplied {len(PATCHES)} patches to {TARGET}")
    print(f"Backup saved at {BACKUP}")
    print("\\nNEXT STEPS:")
    print("  1. sudo systemctl restart celery-staging.service   (code change needs worker restart)")
    print("  2. Re-run extract_clauses on a NEW guideline_id and check CH III 62 / 69 / 70 / 76A etc.")
    print("  3. Re-run against the 9 baseline-tested RBI docs to confirm no regression")
    print("  4. Rollback if needed: python3 apply_superscript_fix.py --rollback")


if __name__ == "__main__":
    main()
