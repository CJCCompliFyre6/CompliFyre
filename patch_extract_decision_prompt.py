#!/usr/bin/env python3
"""
Patch: Fix extract-decision misjudgment in stage1a_structure_map_prompt
(app/services/prompt_templates/clasue_prompt.py).

Root cause (different in kind from the ToC-detection bug fixed earlier):
this is a prompt-design gap, not a code/regex bug. The prompt lists each
section by LABEL ONLY (e.g. "CHAPTER I — Preliminary"), and while the
actual page content for early sections IS included separately as
toc_text (first 3 pages), the prompt never instructs the LLM to actually
cross-reference that content against each section before deciding
extract:true/false. The model defaults to judging by the label alone --
"Preliminary" reads as introductory/definitional, so it excludes the
whole section even when, as in this case, it also contains Applicability
and Scope sub-sections (substantive content, not definitions).

Confirmed via a real document: RBI (NBFC - Voluntary Amalgamation)
Directions, 2025 -- Chapter I "Preliminary" contains A. Short Title,
B. Applicability, C. Definitions, D. Scope. Only C is actually
definitional. The LLM excluded the whole chapter as "definitions only."

This pattern (Preliminary chapters containing Applicability + Scope
alongside Definitions) is common in Indian regulatory drafting generally,
not specific to this one document -- likely to recur across many future
uploads if left unfixed.

Fix: two additions to the prompt --
  1. Explicit instruction to read the actual section content already
     provided (not just the label) before deciding.
  2. Tightened "definitions only" criterion: exclude only if the ENTIRE
     section is pure definitions, with explicit callout that Applicability
     and Scope are substantive content even inside a "Preliminary" or
     "Definitions"-labeled chapter.

Note: unlike the earlier ToC-detection fix, this changes LLM prompt
behavior, not deterministic code -- it cannot be locally unit-tested the
same way. The real verification is the next document upload.

Usage:
    python3 patch_extract_decision_prompt.py --dry-run
    python3 patch_extract_decision_prompt.py --apply
    python3 patch_extract_decision_prompt.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "prompt_templates" / "clasue_prompt.py"
BACKUP = TARGET.with_suffix(".py.bak_extract_decision_prompt")

OLD_BLOCK = '''YOUR ONLY TASK:

For each section listed above, decide whether to EXTRACT clauses from it or not.

EXTRACT = true for:
- Chapters with obligations, requirements, governance rules, disclosures, penalties
- Schedules with compliance requirements, forms, procedures, tables of requirements

EXTRACT = false for:
- Sections with ONLY definitions and no obligations
- Lists of rescinded or repealed circulars
- Sections amending OTHER regulations entirely
- Omitted sections marked [***]'''

NEW_BLOCK = '''YOUR ONLY TASK:

For each section listed above, decide whether to EXTRACT clauses from it or not.

IMPORTANT: Before deciding on any section whose page range falls within the
TABLE OF CONTENTS / FIRST PAGES text above, actually READ that section's content
in the text provided -- do not decide from the section label alone. A section
labeled "Preliminary" or "Chapter I" is not automatically definitions-only:
in Indian regulatory drafting this chapter very commonly also contains an
Applicability sub-section (who must comply) and a Scope sub-section (what
situations/transactions are covered) alongside Definitions. Applicability and
Scope are substantive content, not definitions, regardless of which chapter
they sit in.

EXTRACT = true for:
- Chapters with obligations, requirements, governance rules, disclosures, penalties
- Applicability or Scope sub-sections, even when they appear inside a chapter
  also titled or labeled "Preliminary" or "Definitions"
- Schedules with compliance requirements, forms, procedures, tables of requirements

EXTRACT = false for:
- Sections where EVERY part of the section's actual content (not just its
  label) is pure definitions, with no applicability, scope, or obligations
  content anywhere in the section
- Lists of rescinded or repealed circulars
- Sections amending OTHER regulations entirely
- Omitted sections marked [***]'''


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

    if NEW_BLOCK in content:
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
        print("=== DRY RUN: would replace ===")
        print(OLD_BLOCK)
        print("=== WITH ===")
        print(NEW_BLOCK)
        print("\n(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nRestart complifyre-staging + celery-staging, then re-upload the test document")
        print("and confirm Chapter I is now correctly toggled ON with no exclude reason.")


if __name__ == "__main__":
    main()
