#!/usr/bin/env python3
"""
Patch: Extend the existing (dormant, 0-row, zero-references) RegulatoryBodies
and RegulatoryDocuments models (app/models/re.py) for items #132/#133/#134,
per Rule 15 -- reuse existing infrastructure rather than build parallel
new tables, confirmed safe since both tables are completely unused.

Adds:
  - RegulatoryBodies: geography, industry, governed_institutions columns
  - RegulatoryDocuments: file_hash, guideline_id (FK to guidelines),
    pipeline_status columns
  - New RegulatoryDocumentStatusHistory model (nothing existing covers
    per-transition timestamped history)
  - DocumentPipelineStatus status constants + set_document_pipeline_status()
    helper -- the only sanctioned way to change pipeline_status, since it
    always writes a matching history row in the same call, so "every
    transition gets its own timestamp" can never be silently skipped by
    a call site that only updates the column directly.

Companion SQL (create_tables.sql) must be run against the database first
-- this patch only updates the Python model layer to match.

Usage:
    python3 patch_regulatory_tracking_models.py --dry-run
    python3 patch_regulatory_tracking_models.py --apply
    python3 patch_regulatory_tracking_models.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "models" / "re.py"
BACKUP = TARGET.with_suffix(".py.bak_regulatory_tracking")

ANCHOR_BODIES_WEBSITE = '    website_url = db.Column(db.String(255))'
NEW_BODIES_FIELDS = (
    '    website_url = db.Column(db.String(255))\n'
    '    geography = db.Column(db.String(255))\n'
    '    industry = db.Column(db.String(255))\n'
    '    governed_institutions = db.Column(db.Text)\n'
)

ANCHOR_DOCS_PATH = '    document_path = db.Column(db.String(255))'
NEW_DOCS_FIELDS = (
    '    document_path = db.Column(db.String(255))\n'
    '    file_hash = db.Column(db.String(64))\n'
    '    guideline_id = db.Column(db.BigInteger, db.ForeignKey("guidelines.id", ondelete="SET NULL"))\n'
    '    pipeline_status = db.Column(db.String(50), nullable=False, default="PENDING_DOWNLOAD")\n'
)

NEW_CLASSES_AND_HELPER = '''

class RegulatoryDocumentStatusHistory(db.Model):
    """
    Every pipeline_status transition on a RegulatoryDocuments row gets its
    own timestamped entry here -- Ankita's explicit requirement for a real
    timestamp per status change, not just a single 'last updated' field.
    """
    __tablename__ = "regulatory_document_status_history"

    id = db.Column(db.BigInteger, primary_key=True)
    document_id = db.Column(
        db.BigInteger, db.ForeignKey("RegulatoryDocuments.document_id", ondelete="CASCADE"), nullable=False
    )
    status = db.Column(db.String(50), nullable=False)
    occurred_at = db.Column(db.TIMESTAMP, default=func.current_timestamp())
    notes = db.Column(db.Text)

    document = db.relationship("RegulatoryDocuments", backref="status_history")


class DocumentPipelineStatus:
    """
    Status constants for RegulatoryDocuments.pipeline_status, matching the
    REAL pipeline stages observed live during testing (Stage 1A structure
    map, Stage 1B/2 extraction, Stage 4 Split = "decomposition" in
    Ankita's terminology). PAUSED states are placeholders only -- no pause
    capability exists yet in the pipeline (see Build Sequence item #100,
    not started). These values exist in the data model now so the UI/table
    can be built, but nothing currently sets them to a PAUSED value.
    """
    PENDING_DOWNLOAD = "PENDING_DOWNLOAD"
    IMPORTED = "IMPORTED"
    STRUCTURE_MAP_CREATED = "STRUCTURE_MAP_CREATED"
    EXTRACTION_IN_PROGRESS = "EXTRACTION_IN_PROGRESS"
    EXTRACTION_PAUSED = "EXTRACTION_PAUSED"
    EXTRACTION_COMPLETE = "EXTRACTION_COMPLETE"
    DECOMPOSITION_IN_PROGRESS = "DECOMPOSITION_IN_PROGRESS"
    DECOMPOSITION_PAUSED = "DECOMPOSITION_PAUSED"
    DECOMPOSITION_COMPLETE = "DECOMPOSITION_COMPLETE"

    ALL = [
        PENDING_DOWNLOAD, IMPORTED, STRUCTURE_MAP_CREATED,
        EXTRACTION_IN_PROGRESS, EXTRACTION_PAUSED, EXTRACTION_COMPLETE,
        DECOMPOSITION_IN_PROGRESS, DECOMPOSITION_PAUSED, DECOMPOSITION_COMPLETE,
    ]

    PLACEHOLDER_ONLY = [EXTRACTION_PAUSED, DECOMPOSITION_PAUSED]


def set_document_pipeline_status(document, new_status, notes=None):
    """
    The ONLY sanctioned way to change a RegulatoryDocuments row's
    pipeline_status. Updates the column AND inserts a matching
    status_history row in the same call, so a transition can never be
    logged without its timestamp. Does not commit -- caller controls the
    transaction, consistent with the rest of this codebase.
    """
    if new_status not in DocumentPipelineStatus.ALL:
        raise ValueError(f"Unknown pipeline status: {new_status!r}")
    document.pipeline_status = new_status
    history_row = RegulatoryDocumentStatusHistory(
        document_id=document.document_id,
        status=new_status,
        notes=notes,
    )
    db.session.add(history_row)
    return history_row
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

    if "RegulatoryDocumentStatusHistory" in content:
        print("Patch already applied. Nothing to do.")
        return

    if content.count(ANCHOR_BODIES_WEBSITE) != 1:
        print(f"ERROR: RegulatoryBodies website_url anchor matched {content.count(ANCHOR_BODIES_WEBSITE)} times (expected 1). Aborting.")
        sys.exit(1)
    if content.count(ANCHOR_DOCS_PATH) != 1:
        print(f"ERROR: RegulatoryDocuments document_path anchor matched {content.count(ANCHOR_DOCS_PATH)} times (expected 1). Aborting.")
        sys.exit(1)

    patched = content.replace(ANCHOR_BODIES_WEBSITE, NEW_BODIES_FIELDS.rstrip("\n"))
    patched = patched.replace(ANCHOR_DOCS_PATH, NEW_DOCS_FIELDS.rstrip("\n"))
    patched = patched.rstrip("\n") + "\n" + NEW_CLASSES_AND_HELPER

    if args.dry_run:
        print("=== DRY RUN: would add to RegulatoryBodies ===")
        print(NEW_BODIES_FIELDS)
        print("=== would add to RegulatoryDocuments ===")
        print(NEW_DOCS_FIELDS)
        print("=== would append new classes/helper (truncated preview) ===")
        print(NEW_CLASSES_AND_HELPER[:300], "...")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nAlso update app/models/__init__.py's 're' import line to include")
        print("RegulatoryDocumentStatusHistory, then restart complifyre-staging + celery-staging.")


if __name__ == "__main__":
    main()
