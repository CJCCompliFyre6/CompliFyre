#!/usr/bin/env python3
"""
Patch: Fix a real bug found live -- the LLM occasionally copies raw,
malformed backslash-u text straight from a source page into its JSON
output without properly escaping it (e.g. some literal "\\u12" fragment
in the page content, not a real completed unicode escape), producing
JSON that Python's json.loads() correctly refuses to parse:
"Invalid \\uXXXX escape".

Adds a safe_json_loads() helper that repairs this specific class of
malformed escape (backslash-u NOT followed by exactly 4 hex digits) by
escaping the backslash, turning it into literal text rather than an
invalid escape attempt -- verified this does NOT affect genuinely valid
unicode escapes (e.g. \\u00e9 for accented characters still parses
correctly and produces the right character).

Usage:
    python3 patch_safe_json_parse.py --dry-run
    python3 patch_safe_json_parse.py --apply
    python3 patch_safe_json_parse.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "check_guidelines_service.py"
BACKUP = TARGET.with_suffix(".py.bak_safe_json")

ANCHOR_IMPORT = '''import os
import json
from datetime import datetime, timezone'''

NEW_IMPORT = '''import os
import json
import re
from datetime import datetime, timezone'''

ANCHOR_PARSE = "    result = json.loads(response.choices[0].message.content)"
NEW_PARSE = "    result = safe_json_loads(response.choices[0].message.content)"

NEW_HELPER = '''

def safe_json_loads(raw):
    """
    Parse JSON that may contain invalid \\\\u escape sequences -- the LLM
    occasionally copies raw, malformed backslash-u text straight from a
    source page into its JSON output without properly escaping it,
    producing JSON that Python correctly refuses to parse as-is.
    Repairs this by escaping any backslash-u NOT followed by exactly
    4 valid hex digits, turning it into a literal string instead of
    an (invalid) attempted unicode escape. Genuinely valid unicode
    escapes (e.g. \\\\u00e9) are left untouched and still parse correctly.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = re.sub(r"\\\\u(?![0-9a-fA-F]{4})", r"\\\\\\\\u", raw)
        return json.loads(repaired)
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

    if "def safe_json_loads" in content:
        print("Patch already applied. Nothing to do.")
        return

    for name, anchor in [("IMPORT", ANCHOR_IMPORT), ("PARSE", ANCHOR_PARSE)]:
        count = content.count(anchor)
        if count != 1:
            print(f"ERROR: anchor '{name}' matched {count} times (expected 1). Aborting.")
            sys.exit(1)

    patched = content.replace(ANCHOR_IMPORT, NEW_IMPORT)
    patched = patched.replace(ANCHOR_PARSE, NEW_PARSE)
    # Insert the new helper right before "def parse_documents_with_llm"
    insertion_point = "def parse_documents_with_llm"
    patched = patched.replace(insertion_point, NEW_HELPER.strip("\n") + "\n\n\n" + insertion_point, 1)

    if args.dry_run:
        print("Both anchors matched exactly once. Would also insert safe_json_loads()")
        print("right before parse_documents_with_llm().")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
