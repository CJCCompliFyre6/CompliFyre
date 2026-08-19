#!/usr/bin/env python3
"""
Patch: Fix ToC-page misdetection in generate_structure_map
(app/services/manual_task.py).

Root cause: the existing TOC_HEADING_THRESHOLD = 3 heuristic ("a page
listing 3+ headings is a TOC page") never triggers for documents whose
entire structure is only 1 or 2 chapters -- the ToC page for such a
document has fewer than 3 heading-pattern matches, so it slips through
and gets treated as real chapter content. This produces phantom sections
with the ToC's dot-leader text still attached (e.g. "Preliminary
........................") and impossible page ranges (e.g. "1 to 0",
since two same-page phantom entries compute end_page as
next_entry_page - 1 = 1 - 1 = 0).

Confirmed via a real document: Reserve Bank of India (Non-Banking
Financial Companies - Voluntary Amalgamation) Directions, 2025 -- exactly
2 real chapters, ToC page produced 2 heading matches (below the
threshold of 3), both leaked into the structure map as phantom sections.

Fix (two independent, complementary signals, neither relying on the
fragile heading-count threshold):
  1. Explicit label check: if the page text contains "table of contents"
     (case-insensitive) anywhere, treat the whole page as ToC regardless
     of heading count.
  2. Dot-leader check: even on pages below the threshold, any individual
     heading whose captured heading or title text contains a run of 3+
     periods (the standard ToC dot-leader) is routed to toc_reference
     instead of first_lines, since that's a direct, count-independent
     signature of ToC-formatted text.

Tested locally against a fixture reproducing the exact bug (fixed both
phantom entries, correctly preserved both real chapters) and against a
regression case (two genuine short chapters sharing one physical page,
no dot leaders -- both correctly preserved, unaffected by this fix).

Usage:
    python3 patch_toc_detection_fix.py --dry-run
    python3 patch_toc_detection_fix.py --apply
    python3 patch_toc_detection_fix.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "manual_task.py"
BACKUP = TARGET.with_suffix(".py.bak_toc_detection_fix")

ANCHOR_THRESHOLD = "        TOC_HEADING_THRESHOLD = 3  # a page listing 3+ headings is an index/TOC page, not real content"
ANCHOR_HEADINGS_CALL = "            headings = extract_headings(text)"
ANCHOR_ELIF = "            elif len(headings) >= TOC_HEADING_THRESHOLD:"
ANCHOR_ELSE_FOR = "                for heading, heading_title in headings:"
ANCHOR_ELSE_APPEND = '                    first_lines.append({"page": page_num + 1, "heading": heading, "title": heading_title})'


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

    if "page_is_toc_by_label" in full_text:
        print("Patch already applied (found page_is_toc_by_label). Nothing to do.")
        return

    def find_unique(anchor, label):
        idxs = [i for i, l in enumerate(lines) if l.rstrip("\n") == anchor]
        if len(idxs) != 1:
            print(f"ERROR: anchor '{label}' matched {len(idxs)} times (expected 1). Aborting.")
            sys.exit(1)
        return idxs[0]

    idx_threshold = find_unique(ANCHOR_THRESHOLD, "TOC_HEADING_THRESHOLD line")
    idx_headings_call = find_unique(ANCHOR_HEADINGS_CALL, "extract_headings(text) call")
    idx_elif = find_unique(ANCHOR_ELIF, "elif TOC_HEADING_THRESHOLD line")

    # Find the unique "for heading, heading_title in headings:" immediately
    # followed by "first_lines.append(...)" -- this combination only occurs
    # once (in the else branch); the elif branch's for-loop appends to
    # toc_reference instead, and the "if not headings" branch has no
    # for-loop at all.
    idx_else_for = None
    for i in range(len(lines) - 1):
        if lines[i].rstrip("\n") == ANCHOR_ELSE_FOR and lines[i + 1].rstrip("\n") == ANCHOR_ELSE_APPEND:
            idx_else_for = i
            break
    if idx_else_for is None:
        print("ERROR: could not find the unique else-branch for-loop (for heading... / first_lines.append...). Aborting.")
        sys.exit(1)

    out = []
    for i, line in enumerate(lines):
        if i == idx_threshold:
            out.append(line)
            out.append('        _DOT_LEADER_RE = _re.compile(r"\\.{3,}")  # 3+ periods = classic TOC dot-leader\n')
            continue
        if i == idx_headings_call:
            out.append(line)
            out.append('            page_is_toc_by_label = "table of contents" in text.lower()\n')
            continue
        if i == idx_elif:
            out.append("            elif page_is_toc_by_label or len(headings) >= TOC_HEADING_THRESHOLD:\n")
            continue
        if i == idx_else_for:
            out.append(line)  # "for heading, heading_title in headings:"
            out.append("                    if _DOT_LEADER_RE.search(heading) or _DOT_LEADER_RE.search(heading_title):\n")
            out.append('                        toc_reference.append({"page": page_num + 1, "heading": heading, "title": heading_title})\n')
            out.append("                        continue\n")
            out.append(lines[i + 1])  # the original first_lines.append(...) line
            continue
        if i == idx_else_for + 1:
            continue  # already emitted above as part of idx_else_for handling
        out.append(line)

    new_content = "".join(out)

    if args.dry_run:
        print(f"Anchors found at lines: threshold={idx_threshold+1}, headings_call={idx_headings_call+1}, elif={idx_elif+1}, else_for={idx_else_for+1}")
        print("Would insert: _DOT_LEADER_RE definition, page_is_toc_by_label check,")
        print("updated elif condition, and per-heading dot-leader filtering in the else branch.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(new_content)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nRestart complifyre-staging + celery-staging, then re-upload the test document")
        print("and confirm the structure map shows exactly 2 clean chapters, no phantom entries.")


if __name__ == "__main__":
    main()
