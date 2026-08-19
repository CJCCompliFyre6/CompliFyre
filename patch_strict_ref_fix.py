#!/usr/bin/env python3
"""
Patch (round 2): Fix the $ref+description strict-mode violation in
_to_strict_json_schema's _fix_object helper, already inserted into
app/services/model_response.py by patch_strict_structured_output_v2.py.

Discovered via Azure's own 400 response when testing strict=True against
compliance_activity_id=45893:
    "Invalid schema for response_format 'ControlWorkpaper': context=
    ('properties', 'interviews'), $ref cannot have keywords {'description'}."

OpenAI/Azure structured-outputs strict mode requires any "$ref" node to
appear bare, with no sibling keys. Pydantic's model_json_schema() generates
{"$ref": "...", "description": "..."} for any field typed as a nested
model with a Field(description=...) -- which ControlWorkpaper has several
of (interviews, test_procedure, and others). This applies generically to
every such field at once, not just "interviews".

Usage:
    python3 patch_strict_ref_fix.py --dry-run
    python3 patch_strict_ref_fix.py --apply
    python3 patch_strict_ref_fix.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "model_response.py"
BACKUP = TARGET.with_suffix(".py.bak_strict_ref_fix")

OLD_BLOCK = '''    def _fix_object(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
            for prop in node["properties"].values():
                prop.pop("default", None)
                _fix_object(prop)
        for key in ("items", "anyOf", "allOf", "oneOf"):
            val = node.get(key)
            if isinstance(val, dict):
                _fix_object(val)
            elif isinstance(val, list):
                for item in val:
                    _fix_object(item)'''

NEW_BLOCK = '''    def _fix_object(node):
        if not isinstance(node, dict):
            return
        if "$ref" in node and len(node) > 1:
            ref_val = node["$ref"]
            node.clear()
            node["$ref"] = ref_val
            return
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
            for prop in node["properties"].values():
                prop.pop("default", None)
                _fix_object(prop)
        for key in ("items", "anyOf", "allOf", "oneOf"):
            val = node.get(key)
            if isinstance(val, dict):
                _fix_object(val)
            elif isinstance(val, list):
                for item in val:
                    _fix_object(item)'''


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
        print("\nRestart complifyre-staging + celery-staging, then retry activity 45893 in a FRESH flask shell.")


if __name__ == "__main__":
    main()
