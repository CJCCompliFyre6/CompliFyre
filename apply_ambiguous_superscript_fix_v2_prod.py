#!/usr/bin/env python3
"""
Layer 2 fix (v2, corrected) — font-size + registry hybrid check for the
superscript/digit classifier, with SIDE-CHANNEL ambiguity flagging.

v1 mistake: injected a sentinel marker directly into clean_text, which fed
into structural clause-boundary regexes and the 1500-char split threshold,
causing real structural regressions (boundary merges, spurious splits).

v2 fix: clean_text is NEVER modified for the ambiguous case (identical to
"preserve"). Ambiguous matches are recorded in a separate list and only
correlated to nodes — as pure metadata (extraction_status/flag_reason) —
AFTER all structural node-building is complete. The clause_text string
itself is guaranteed byte-identical to the plain-preserve behavior.

Must be applied on top of apply_superscript_fix.py only (the v1 ambiguity
patch must NOT also be applied — roll it back first if it was applied).

Usage:
    python3 apply_ambiguous_superscript_fix_v2.py --dry-run
    python3 apply_ambiguous_superscript_fix_v2.py
    python3 apply_ambiguous_superscript_fix_v2.py --rollback
"""
import argparse
import shutil
import sys

TARGET = "app/services/pdf_structure_parser.py"
BACKUP = TARGET + ".ambigv2.bak"

PATCHES = [
    # F1 — helper functions + strip_page_noise signature (adds ambiguous_records local list)
    {
        "name": "F1: add font-size helpers, extend strip_page_noise signature",
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
    ambiguous_records = []
    lines = page_text.split('\\n')''',
    },
    # F2 — hybrid classifier; text is NEVER altered for the ambiguous case;
    # function now returns (clean_text, ambiguous_records) instead of just clean_text
    {
        "name": "F2: hybrid classifier — ambiguous case leaves text untouched, records side-channel only",
        "old": """    def _strip_superscript(m):
        digit = m.group(0).strip()
        if digit in footnote_numbers:
            return ' '          # confirmed footnote marker — strip as before
        return m.group(0)       # unknown number — leave untouched, it's content
    clean_text = PATTERNS['superscript'].sub(_strip_superscript, clean_text)
    clean_text = PATTERNS['omitted'].sub('', clean_text)
    return clean_text""",
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
            return ' '                  # both signals agree — confirmed footnote, strip
        elif not is_small_font:
            return m.group(0)           # normal-size — content, preserve regardless of registry
        else:
            # small font but not a known footnote: genuinely ambiguous (could be
            # an exponent/formula, could be an undetected footnote). Text is
            # NEVER altered here — just recorded for a separate, metadata-only
            # flagging pass run after all node-building completes.
            context = m.string[max(0, m.start()-25):m.end()+20].replace('\\n', ' ')
            ambiguous_records.append((digit, context))
            return m.group(0)
    clean_text = PATTERNS['superscript'].sub(_strip_superscript, clean_text)
    clean_text = PATTERNS['omitted'].sub('', clean_text)
    return clean_text, ambiguous_records""",
    },
    # F3 — init the page-loop-level accumulator
    {
        "name": "F3: init all_ambiguous_matches accumulator",
        "old": """    buf_text = []
    buf_clause_no = None
    buf_node_type = None
    buf_page = None
    buf_parent = None
    buf_depth = 0

    def flush():""",
        "new": """    buf_text = []
    buf_clause_no = None
    buf_node_type = None
    buf_page = None
    buf_parent = None
    buf_depth = 0
    all_ambiguous_matches = []

    def flush():""",
    },
    # F4 — call site: unpack tuple, compute font data, accumulate page-tagged records
    {
        "name": "F4: call site unpacks (clean_text, page_ambiguous) and accumulates with page number",
        "old": """            clean_text = strip_page_noise(raw_text, footnote_numbers)
            plumber_page = pdf_plumber.pages[page_num]
            has_tables = bool(plumber_page.extract_tables())""",
        "new": """            plumber_page = pdf_plumber.pages[page_num]
            body_font_size = get_body_font_size(plumber_page)
            digit_word_queue = get_ordered_digit_words(plumber_page)
            clean_text, page_ambiguous = strip_page_noise(raw_text, footnote_numbers, digit_word_queue, body_font_size)
            for digit, ctx in page_ambiguous:
                all_ambiguous_matches.append((page_num + 1, digit, ctx))
            has_tables = bool(plumber_page.extract_tables())""",
    },
    # F5 — correlation pass, purely metadata (flag_reason/extraction_status), no text mutation
    {
        "name": "F5: post-build correlation pass — flags matching nodes, never touches raw_text",
        "old": """    nodes = _assign_parents(nodes)
    logger.info(f"Stage 1: {len(nodes)} nodes extracted")
    return nodes
def _assign_parents(nodes):""",
        "new": """    nodes = _assign_parents(nodes)
    if all_ambiguous_matches:
        logger.warning(f"Stage 1: {len(all_ambiguous_matches)} ambiguous digit(s) found (not stripped, not deleted) - flagging matching nodes")
        for pg, digit, ctx in all_ambiguous_matches:
            snippet = ctx[:30].strip()
            candidates = [n for n in nodes if n.get('page_number') == pg and snippet and snippet in n.get('raw_text', '')]
            if not candidates:
                candidates = [n for n in nodes if n.get('page_number') == pg]
            for n in candidates:
                n['extraction_status'] = 'FLAGGED'
                existing = n.get('flag_reason') or ''
                reason = f'AMBIGUOUS_TEXT_FORMAT: possible superscript/formula digit "{digit}" on page {pg} - verify (context: {ctx.strip()[:60]})'
                n['flag_reason'] = (existing + '; ' + reason).strip('; ') if existing else reason
    logger.info(f"Stage 1: {len(nodes)} nodes extracted")
    return nodes
def _assign_parents(nodes):""",
    },
]


def rollback():
    import os
    if not os.path.exists(BACKUP):
        print(f"No backup found at {BACKUP} - nothing to roll back.")
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
            print(f"ABORT - pattern not found for patch '{patch['name']}'.")
            print("Not applying ANY changes. Confirm current file state and update this script.")
            sys.exit(1)
        if count > 1:
            print(f"ABORT - pattern for patch '{patch['name']}' matches {count} times (expected exactly 1).")
            sys.exit(1)
        content = content.replace(patch["old"], patch["new"], 1)
        print(f"OK - patch '{patch['name']}' matched exactly once.")

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
    print("  3. Confirm stage1_nodes/saved counts MATCH the plain-superscript-fix baseline (315/164 for ALM, 124/57 for Misc)")
    print("  4. Check FLAGGED clauses with flag_reason LIKE 'AMBIGUOUS_TEXT_FORMAT%'")
    print("  5. Rollback if needed: python3 apply_ambiguous_superscript_fix_v2.py --rollback")


if __name__ == "__main__":
    main()
