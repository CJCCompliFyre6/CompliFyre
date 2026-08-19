#!/usr/bin/env python3
"""
Patch: fix three real model-vs-database gaps found during genuine
end-to-end testing of the LOI activation flow. Each of these columns
already exists in the real database (migrated correctly back in
Group 1), but the ORM model class was never updated to declare them
-- exactly the same class of mistake as the activity_generation_
claimed_at incident from earlier tonight, just self-inflicted this
time rather than inherited.

Fixes:
1. Organizations -- missing all 11 LOI-related columns
2. Users -- missing invite_id
3. Guidelines -- missing catalogue_enabled

Usage:
    python3 patch_fix_model_schema_gaps.py --dry-run
    python3 patch_fix_model_schema_gaps.py --apply
    python3 patch_fix_model_schema_gaps.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

ORG_TARGET = Path.home() / "CompliFyre-staging" / "app" / "models" / "organization.py"
ORG_BACKUP = ORG_TARGET.with_suffix(".py.bak_loi_fields")

USER_TARGET = Path.home() / "CompliFyre-staging" / "app" / "models" / "user.py"
USER_BACKUP = USER_TARGET.with_suffix(".py.bak_invite_id")

AI_TARGET = Path.home() / "CompliFyre-staging" / "app" / "models" / "ai.py"
AI_BACKUP = AI_TARGET.with_suffix(".py.bak_catalogue_enabled")

ORG_ANCHOR = '''        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    projects = db.relationship('''

ORG_NEW = '''        db.TIMESTAMP,
        default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    # +++ ADDED FOR LOI CAPTURE SUBSYSTEM +++
    entity_type = db.Column(db.String(100), nullable=True)
    cin = db.Column(db.String(50), nullable=True)
    registered_address = db.Column(db.Text, nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    contact_phone = db.Column(db.String(20), nullable=True)
    loi_required = db.Column(db.Boolean, nullable=False, default=True)
    loi_status = db.Column(db.String(50), nullable=False, default="NOT_REQUIRED")
    loi_signed_at = db.Column(db.TIMESTAMP, nullable=True)
    loi_signature_id = db.Column(db.BigInteger, nullable=True)
    temp_access_expires_at = db.Column(db.TIMESTAMP, nullable=True)

    projects = db.relationship('''

USER_ANCHOR = '''    free_report_used = db.Column(db.Boolean, default=False)

    # +++ ADDED FOR NEW FEATURES +++'''

USER_NEW = '''    free_report_used = db.Column(db.Boolean, default=False)
    invite_id = db.Column(db.BigInteger, nullable=True)

    # +++ ADDED FOR NEW FEATURES +++'''

AI_ANCHOR = '''    disabled_reason = db.Column(db.Text, nullable=True)
    disabled_at = db.Column(db.TIMESTAMP, nullable=True)
    applicable_licenses = db.Column(db.JSON, nullable=True)'''

AI_NEW = '''    disabled_reason = db.Column(db.Text, nullable=True)
    disabled_at = db.Column(db.TIMESTAMP, nullable=True)
    catalogue_enabled = db.Column(db.Boolean, nullable=False, default=False)
    applicable_licenses = db.Column(db.JSON, nullable=True)'''


def patch_file(target, backup, anchor, new, args, marker):
    if not target.exists():
        print(f"ERROR: target file not found: {target}")
        sys.exit(1)

    content = target.read_text()

    if marker in content:
        print(f"{target.name}: patch already applied. Nothing to do.")
        return

    count = content.count(anchor)
    if count != 1:
        print(f"ERROR ({target.name}): anchor matched {count} times (expected 1). Aborting.")
        sys.exit(1)

    patched = content.replace(anchor, new)

    if args.dry_run:
        print(f"{target.name}: anchor matched exactly once.")
        return

    if args.apply:
        shutil.copy2(target, backup)
        target.write_text(patched)
        print(f"{target.name}: backup written to {backup}, patched.")


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        for backup, target in [(ORG_BACKUP, ORG_TARGET), (USER_BACKUP, USER_TARGET), (AI_BACKUP, AI_TARGET)]:
            if backup.exists():
                shutil.copy2(backup, target)
                print(f"Rolled back {target} from {backup}.")
            else:
                print(f"No backup found for {target}, skipping.")
        return

    patch_file(ORG_TARGET, ORG_BACKUP, ORG_ANCHOR, ORG_NEW, args, "LOI CAPTURE SUBSYSTEM")
    patch_file(USER_TARGET, USER_BACKUP, USER_ANCHOR, USER_NEW, args, "invite_id = db.Column")
    patch_file(AI_TARGET, AI_BACKUP, AI_ANCHOR, AI_NEW, args, "catalogue_enabled = db.Column")

    if args.dry_run:
        print("\n(No files written. Re-run with --apply to make the change.)")
    elif args.apply:
        print("\nAll three files patched.")


if __name__ == "__main__":
    main()
