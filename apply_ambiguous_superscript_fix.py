#!/usr/bin/env python3
"""
Layer 2 fix: font-size + registry hybrid check for the superscript/digit
classifier, with explicit ambiguity-flagging instead of silent guessing.

Decision matrix:
  - normal font-size (or font-data unavailable) -> PRESERVE (content, always)
  - small font-size AND digit matches a confirmed footnote number -> STRIP
  - small font-size but digit does NOT match a confirmed footnote number
    -> AMBIGUOUS (could be exponent/math formula, could be an undetected
       footnote) -> never delete; mark with a sentinel that validate_nodes()
       converts into extraction_status='FLAGGED', flag_reason='AMBIGUOUS_TEXT_FORMAT'

Applies on top of apply_superscript_fix.py (must be applied first).

Usage:
    python3 apply_ambiguous_superscript_fix.py --dry-run
    python3 apply_ambiguous_superscript_fix.py
    python3 apply_ambiguous_superscript_fix.py --rollback
"""
import argparse
import shutil
import sys

TARGET = "app/services/pdf_structure_parser.py"
BACKUP = TARGET + ".ambig.bak"

PATCHES = [
    # E1 — add font-size helper functions + update strip_page_noise signature
    {
        "name": "E1: add get_body_font_size/get_ordered_digit_words, update strip_page_noise signature",
        "old": """def strip_page_noise(page_text, footnote_numbers=None):
    footnote_numbers = footnote_numbers or set()
    lines = page_text.split('\\n')""",
        "new": '''def get_body_font_size(plumber_page):
    """Compute the page's dominant (body-text) font size from word-level data.
    Returns None if font data is unavailable — callers must treat that as
    'unknown, default to safe/preserve' rather than guessing."""
    try:
        words = plumber_page.extract_words(extra_attrs=["size"])
    except Exception:
        return None
    from collections import Counter
    sizes = [round(w['size'], 1) for w in words if w.get('size')]
    if not sizes:
        return None
    return Counter(sizes).most_common(1)[0][0]


def get_ordered_digit_words(plumber_page):
    """Return, in reading order, (text, size) for every standalone 1-4 digit
    word on the page — candidates for the superscript/content classifier."""
    try:
        words = plumber_page.extract_words(extra_attrs=["size"])
    except Exception:
        return []
    return [(w['text'], round(w['size'], 1)) for w in words if re.match(r'^\\d{1,4}$', w['text'])]


def strip_page_noise(page_text, footnote_numbers=None, digit_word_queue=None, body_font_size=None):
    footnote_numbers = footnote_numbers or set()
    digit_word_queue = list(digit_word_queue or [])
    _queue_idx = [0]
    lines = page_text.split('\\n')''',
    },
    # E2 — replace the registry-only _strip_superscript with the font+registry hybrid
    {
        "name": "E2: hybrid font-size + registry ambiguity-aware superscript classifier",
        "old": """    def _strip_superscript(m):
        digit = m.group(0).strip()
        if digit in footnote_numbers:
            return ' '          # confirmed footnote marker — strip as before
        return m.group(0)       # unknown number — leave untouched, it's content
    clean_text = PATTERNS['superscript'].sub(_strip_superscript, clean_text)""",
        "new": """    def _strip_superscript(m):
        digit = m.group(0).strip()
        size = None
        idx = _queue_idx[0]
        while idx < len(digit_word_queue):
            wtext, wsize = digit_word_queue[idx]
            if wtext == digit:
                size = wsize
                _queue_idx[0] = idx + 1
                break
            idx += 1
        is_small_font = (body_font_size is not None and size is not None and size < body_font_size * 0.75)
        is_registered_footnote = digit in footnote_numbers
        if is_small_font and is_registered_footnote:
            return ' '                                  # both signals agree — confirmed footnote
        elif not is_small_font:
            return m.group(0)                           # normal-size — content, preserve regardless of registry
        else:
            return f'\\x01AMBIG:{digit}\\x01' + m.group(0)  # small font, not a known footnote — ambiguous, flag don't delete
    clean_text = PATTERNS['superscript'].sub(_strip_superscript, clean_text)""",
    },
    # E3 — thread digit_word_queue/body_font_size from the per-page loop
    {
        "name": "E3: compute + pass font-size data at the strip_page_noise call site",
        "old": """            clean_text = strip_page_noise(raw_text, footnote_numbers)
            plumber_page = pdf_plumber.pages[page_num]
            has_tables = bool(plumber_page.extract_tables())""",
        "new": """            plumber_page = pdf_plumber.pages[page_num]
            body_font_size = get_body_font_size(plumber_page)
            digit_word_queue = get_ordered_digit_words(plumber_page)
            clean_text = strip_page_noise(raw_text, footnote_numbers, digit_word_queue, body_font_size)
            has_tables = bool(plumber_page.extract_tables())""",
    },
    # E4 — detect the ambiguity sentinel in validate_nodes and flag instead of silently passing through
    {
        "name": "E4: validate_nodes detects AMBIG sentinel, flags for review, strips marker from stored text",
        "old": """    for node in nodes:
        if not node.get('clause_no'):""",
        "new": """    for node in nodes:
        _raw = node.get('raw_text', '') or ''
        _ambig = re.findall(r'\\x01AMBIG:(\\d+)\\x01', _raw)
        if _ambig:
            node['raw_text'] = re.sub(r'\\x01AMBIG:\\d+\\x01', '', _raw)
            node['extraction_status'] = 'FLAGGED'
            node['flag_reason'] = f'AMBIGUOUS_TEXT_FORMAT: possible superscript/formula digits {_ambig} — verify on page {node.get("page_number")}'
        if not node.get('clause_no'):""",
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

    for patch in PATCHES:
        count = content.count(patch["old"])
        if count == 0:
            print(f"ABORT — pattern not found for patch '{patch['name']}'.")
            print("This likely means the file state differs from what this script expects")
            print("(e.g. apply_superscript_fix.py wasn't applied first, or the file changed).")
            print("Not applying ANY changes.")
            sys.exit(1)
        if count > 1:
            print(f"ABORT — pattern for patch '{patch['name']}' matches {count} times (expected exactly 1).")
            sys.exit(1)
        content = content.replace(patch["old"], patch["new"], 1)
        print(f"OK — patch '{patch['name']}' matched exactly once.")

    if args.dry_run:
        print("\ndry-run: all patches would apply cleanly. No files written.")
        return

    shutil.copy(TARGET, BACKUP)
    with open(TARGET, "w") as f:
        f.write(content)
    print(f"\nApplied {len(PATCHES)} patches to {TARGET}")
    print(f"Backup saved at {BACKUP}")
    print("\nNEXT STEPS:")
    print("  1. sudo systemctl restart celery-staging.service")
    print("  2. Re-run extraction on fresh guideline copies of ALM and Misc Instructions")
    print("  3. Check for FLAGGED clauses with flag_reason LIKE 'AMBIGUOUS_TEXT_FORMAT%'")
    print("  4. Rollback if needed: python3 apply_ambiguous_superscript_fix.py --rollback")


if __name__ == "__main__":
    main()
