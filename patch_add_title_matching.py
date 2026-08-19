#!/usr/bin/env python3
"""
Patch: Add title-matching functions that connect Tracked Guidelines
(documents discovered by "Check for new guidelines") to the real
Guidelines table once someone actually uploads the file. Uses
word-overlap (Jaccard) similarity rather than raw character matching,
since discovery-time titles often differ from the uploaded document's
own name (draft vs final wording, "Master Direction --" prefixes).
Deliberately conservative threshold: a missed match just leaves the
Tracked Guidelines entry "Pending" a bit longer (safe); a wrong match
would silently link two unrelated documents (worse).

Tested against 6 real title pairs from tonight's actual data (3 should-
match cases involving draft/final phrasing differences, 3 should-not-
match cases involving genuinely different documents) plus edge cases
(same regulation type but different year, different entity type same
year) -- all passed with a 0.6 threshold.

Usage:
    python3 patch_add_title_matching.py --dry-run
    python3 patch_add_title_matching.py --apply
    python3 patch_add_title_matching.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "check_guidelines_service.py"
BACKUP = TARGET.with_suffix(".py.bak_title_matching")

NEW_FUNCTIONS = '''

# ============================================================
# Title matching for linking Tracked Guidelines (discovered
# documents) to the real Guidelines table once uploaded.
# ============================================================

def normalize_title(title):
    """
    Strip common noise words/punctuation that differ between a
    discovery-time title (e.g. "RBI releases draft Master Direction --
    Reserve Bank of India (Credit Derivatives) Directions, 2026") and
    the eventual uploaded document's own DocumentName, so word-overlap
    comparison isn't thrown off by these.
    """
    noise_phrases = [
        "rbi releases draft", "rbi issues draft", "rbi invites public comments on the draft",
        "rbi invites comments on the draft", "rbi invites comments on",
        "master direction -", "master direction \\u2013", "master direction --",
        "draft", "amendment directions", "directions,", "directions",
    ]
    t = title.lower()
    for phrase in noise_phrases:
        t = t.replace(phrase, " ")
    t = re.sub(r"[^\\w\\s]", " ", t)
    t = re.sub(r"\\s+", " ", t).strip()
    return t


def title_similarity(title_a, title_b):
    """
    Word-overlap (Jaccard) similarity between two normalized titles --
    robust to prefix/suffix differences (draft vs final wording), since
    it only cares about which significant words are shared.
    """
    words_a = set(normalize_title(title_a).split())
    words_b = set(normalize_title(title_b).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def try_link_tracked_guideline(guideline_id, document_name, threshold=0.6):
    """
    After a new Guidelines row is created, check whether its document
    name matches a still-pending Tracked Guidelines (RegulatoryDocuments)
    entry, and if so, link them: set guideline_id and flip the pipeline
    status to IMPORTED. Deliberately conservative threshold -- a missed
    match just leaves the Tracked Guidelines entry "Pending" a bit
    longer (safe); a wrong match would silently link two unrelated
    documents (worse). Returns the linked RegulatoryDocuments row, or
    None if nothing matched confidently enough.
    """
    if not document_name:
        return None

    pending = RegulatoryDocuments.query.filter_by(guideline_id=None).all()
    if not pending:
        return None

    best_doc = None
    best_score = 0.0
    for doc in pending:
        score = title_similarity(document_name, doc.title)
        if score > best_score:
            best_score = score
            best_doc = doc

    if best_doc and best_score >= threshold:
        best_doc.guideline_id = guideline_id
        set_document_pipeline_status(
            best_doc, DocumentPipelineStatus.IMPORTED,
            notes=f"Auto-linked to guideline_id={guideline_id} on upload (title similarity {best_score:.2f})"
        )
        return best_doc
    return None
'''


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

    if "def try_link_tracked_guideline" in content:
        print("Patch already applied. Nothing to do.")
        return

    patched = content.rstrip("\n") + "\n" + NEW_FUNCTIONS

    if args.dry_run:
        print(f"Would append the title-matching functions at the end of the file")
        print(f"(currently {len(content.splitlines())} lines).")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
