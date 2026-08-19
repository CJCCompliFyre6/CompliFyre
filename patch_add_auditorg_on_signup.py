#!/usr/bin/env python3
"""
Patch: during activation_submit(), also create a minimal
AuditOrganization record (auto-filled from the signup form's already-
collected details) and set the new User's auditor_profile_id to point
to it -- reusing the EXISTING add_my_guidelines route as-is (per
Shubha's decision), rather than building a separate download
mechanism for trial users.

Deliberately NOT the full multi-employee consulting-firm workflow
that auditor_profile_id/AuditOrganization was originally designed for
-- that needs a separate rethink, logged in the build sequence, not
solved here. This just fills the mandatory fields so existing
features (download guidelines, create clients, create projects) work
correctly for new self-signup users.

Usage:
    python3 patch_add_auditorg_on_signup.py --dry-run
    python3 patch_add_auditorg_on_signup.py --apply
    python3 patch_add_auditorg_on_signup.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "routes" / "loi" / "view.py"
BACKUP = TARGET.with_suffix(".py.bak_auditorg")

IMPORT_ANCHOR = '''from app.models import (
    SignupInvites, InvitePreloadGuidelines, Guidelines, Organizations,
    Users, UserJourneyEvents, LoiTemplates, LoiSignatures, LoiForwardRequests,
)'''

IMPORT_NEW = '''from app.models import (
    SignupInvites, InvitePreloadGuidelines, Guidelines, Organizations,
    Users, UserJourneyEvents, LoiTemplates, LoiSignatures, LoiForwardRequests,
    AuditOrganization,
)'''

ANCHOR = '''    user = Users(
        organization_id=org.organization_id,
        email=invite.email,
        phone_no=request.form.get("phone"),
        name=request.form.get("contact_name"),
        designation=request.form.get("designation"),
        invite_id=invite.id,
        password_hash=generate_password_hash(request.form.get("password")),
        status="active",
    )
    db.session.add(user)
    db.session.flush()'''

NEW = '''    # Reuses the EXISTING add_my_guidelines route as-is (per Shubha's
    # decision) rather than building a separate download mechanism for
    # trial users -- that route requires auditor_profile_id to be set,
    # pointing at an AuditOrganization record. This is NOT the full
    # multi-employee consulting-firm workflow that model was originally
    # designed for (see item logged in build sequence for that rethink)
    # -- just enough mandatory info, auto-filled from what was already
    # collected at signup, so download guidelines / create clients /
    # create projects all work correctly for a new self-signup user.
    audit_org = AuditOrganization(
        firm_name=request.form.get("legal_name"),
        firm_registration_no=request.form.get("cin"),
        firm_description=f"{request.form.get('entity_type')} -- registered via CompliFyre self-signup",
        number_of_employees=1,
    )
    db.session.add(audit_org)
    db.session.flush()

    user = Users(
        organization_id=org.organization_id,
        email=invite.email,
        phone_no=request.form.get("phone"),
        name=request.form.get("contact_name"),
        designation=request.form.get("designation"),
        invite_id=invite.id,
        password_hash=generate_password_hash(request.form.get("password")),
        status="active",
        auditor_profile_id=audit_org.id,
    )
    db.session.add(user)
    db.session.flush()'''


def apply_patch(content):
    count1 = content.count(IMPORT_ANCHOR)
    if count1 != 1:
        print(f"ERROR: import anchor matched {count1} times (expected 1). Aborting.")
        sys.exit(1)
    count2 = content.count(ANCHOR)
    if count2 != 1:
        print(f"ERROR: user-creation anchor matched {count2} times (expected 1). Aborting.")
        sys.exit(1)
    content = content.replace(IMPORT_ANCHOR, IMPORT_NEW)
    content = content.replace(ANCHOR, NEW)
    return content


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

    if "AuditOrganization" in content:
        print("Patch already applied. Nothing to do.")
        return

    patched = apply_patch(content)

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
