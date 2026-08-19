#!/usr/bin/env python3
"""
Patch (v2, line-anchored): Fix silent missing-required-field failures in
extract_structured_info by adding an opt-in `strict` parameter that uses
Azure OpenAI's structured-outputs mode (json_schema, strict: true) instead
of the weaker "json_object" mode.

Root cause: "json_object" mode only guarantees the model's output PARSES as
JSON, not that it matches the Pydantic schema -- that's prompt-instruction
only, checked client-side after the fact. Confirmed by 6 consecutive
failures (2 attempts x 3 invocations) all missing the same required field
(explain_test_procedure) for compliance_activity_id=45893 (guideline 201).

This version anchors on short, distinctive single lines instead of a large
multi-line block, so it's robust to blank-line/whitespace differences that
broke the v1 block-match patch twice via terminal paste.

Usage:
    python3 patch_strict_structured_output_v2.py --dry-run
    python3 patch_strict_structured_output_v2.py --apply
    python3 patch_strict_structured_output_v2.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "model_response.py"
BACKUP = TARGET.with_suffix(".py.bak_strict_v2")

HELPER_FUNC = '''def _to_strict_json_schema(schema):
    """
    Convert a Pydantic model's JSON schema into an OpenAI-strict-mode-compliant
    schema: every property forced into "required", additionalProperties: false
    on every object, "default" keys stripped -- all required by OpenAI/Azure
    structured-outputs strict mode. Walks $defs recursively.
    """
    import copy as _copy

    def _fix_object(node):
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
                    _fix_object(item)

    raw = _copy.deepcopy(schema.model_json_schema())
    _fix_object(raw)
    for defn in raw.get("$defs", {}).values():
        _fix_object(defn)
    return raw


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

    lines = TARGET.read_text().splitlines(keepends=True)

    # Idempotency check
    full_text = "".join(lines)
    if "_to_strict_json_schema" in full_text:
        print("Patch already applied (found _to_strict_json_schema). Nothing to do.")
        return

    # 1. Find "def extract_structured_info(" -- must be exactly one match
    sig_idxs = [i for i, l in enumerate(lines) if l.rstrip("\n") == "def extract_structured_info("]
    if len(sig_idxs) != 1:
        print(f"ERROR: found {len(sig_idxs)} lines matching 'def extract_structured_info(' (expected 1). Aborting.")
        sys.exit(1)
    sig_idx = sig_idxs[0]

    # 2. Find the ") -> Any | None:" line shortly after the signature
    close_idx = None
    for i in range(sig_idx, min(sig_idx + 15, len(lines))):
        if lines[i].rstrip("\n") == ") -> Any | None:":
            close_idx = i
            break
    if close_idx is None:
        print("ERROR: could not find ') -> Any | None:' near the signature. Aborting.")
        sys.exit(1)

    # 3. Find 'response_format={"type": "json_object"},' after that, within the same function
    rf_idx = None
    for i in range(close_idx, min(close_idx + 60, len(lines))):
        if lines[i].strip() == 'response_format={"type": "json_object"},':
            rf_idx = i
            break
    if rf_idx is None:
        print('ERROR: could not find response_format={"type": "json_object"}, line. Aborting.')
        sys.exit(1)

    indent = lines[rf_idx][: len(lines[rf_idx]) - len(lines[rf_idx].lstrip())]

    replacement_block = (
        f"{indent}if strict:\n"
        f'{indent}    response_format = {{\n'
        f'{indent}        "type": "json_schema",\n'
        f'{indent}        "json_schema": {{\n'
        f'{indent}            "name": schema.__name__,\n'
        f'{indent}            "schema": _to_strict_json_schema(schema),\n'
        f'{indent}            "strict": True,\n'
        f"{indent}        }},\n"
        f"{indent}    }}\n"
        f"{indent}else:\n"
        f'{indent}    response_format = {{"type": "json_object"}}\n'
    )

    # Find "response = client.chat.completions.create(" between close_idx and rf_idx --
    # the if/else block must be inserted as a statement BEFORE this call starts, not
    # inline inside its argument list.
    create_idx = None
    for i in range(close_idx, rf_idx):
        if "client.chat.completions.create(" in lines[i]:
            create_idx = i
            break
    if create_idx is None:
        print("ERROR: could not find the client.chat.completions.create( call before the response_format line. Aborting.")
        sys.exit(1)
    create_indent = lines[create_idx][: len(lines[create_idx]) - len(lines[create_idx].lstrip())]
    replacement_block_at_call_indent = (
        f"{create_indent}if strict:\n"
        f'{create_indent}    response_format = {{\n'
        f'{create_indent}        "type": "json_schema",\n'
        f'{create_indent}        "json_schema": {{\n'
        f'{create_indent}            "name": schema.__name__,\n'
        f'{create_indent}            "schema": _to_strict_json_schema(schema),\n'
        f'{create_indent}            "strict": True,\n'
        f"{create_indent}        }},\n"
        f"{create_indent}    }}\n"
        f"{create_indent}else:\n"
        f'{create_indent}    response_format = {{"type": "json_object"}}\n'
    )

    out = []
    out.extend(lines[:sig_idx])
    out.append(HELPER_FUNC)
    for i in range(sig_idx, len(lines)):
        line = lines[i]
        if i == close_idx:
            out.append("    strict: bool = False,\n")
            out.append(line)
            continue
        if i == create_idx:
            out.append(replacement_block_at_call_indent)
            out.append(line)
            continue
        if i == rf_idx:
            out.append(f"{indent}response_format=response_format,\n")
            continue
        out.append(line)

    new_content = "".join(out)

    if args.dry_run:
        print(f"Found signature at line {sig_idx + 1}, ') -> Any | None:' at line {close_idx + 1}, response_format literal at line {rf_idx + 1}.")
        print("Would insert helper function, add strict parameter, and swap response_format handling.")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(new_content)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nNext: update the ControlWorkpaper call site in extract_test_procedures to pass strict=True,")
        print("then restart complifyre-staging + celery-staging.")


if __name__ == "__main__":
    main()
