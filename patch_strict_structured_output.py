#!/usr/bin/env python3
"""
Patch: Fix silent missing-required-field failures in extract_structured_info
by adding an opt-in `strict` parameter that uses Azure OpenAI's actual
structured-outputs mode (response_format type "json_schema" with
strict: true) instead of the weaker "json_object" mode.

Root cause: "json_object" mode only guarantees the model's output PARSES as
JSON. It does not enforce that the output matches the Pydantic schema --
that's done entirely by prompt instruction ("Return ONLY valid JSON
matching EXACTLY this schema..."), then checked client-side by Pydantic
after the fact. For ControlWorkpaper (20 fields, with the longest and most
open-ended field -- explain_test_procedure -- last in the schema), this
reliably dropped that field: confirmed by 6 consecutive failures (2 attempts
x 3 separate invocations) all failing on the exact same field for
compliance_activity_id=45893, clause_id=11732 (guideline 201).

Fix: add strict=False default parameter. When strict=True, build an
OpenAI-strict-mode-compliant JSON schema (every property forced into
"required", additionalProperties: false on every object, "default" keys
stripped -- all required by the strict-mode spec) and pass response_format
as {"type": "json_schema", "json_schema": {"name", "schema", "strict": true}}.
This makes the API itself guarantee schema compliance instead of relying on
prompt instruction + post-hoc retry.

Scope: opt-in only. No existing call site's behavior changes unless it
explicitly passes strict=True. Only the ControlWorkpaper call site in
extract_test_procedures is switched on by this patch; other schemas/call
sites should be verified individually before opting in, since strict mode
has schema constraints (no bare "default", all fields effectively required)
that may need testing against each schema.

Usage:
    python3 patch_strict_structured_output.py --dry-run
    python3 patch_strict_structured_output.py --apply
    python3 patch_strict_structured_output.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "model_response.py"
BACKUP = TARGET.with_suffix(".py.bak_strict_structured_output")

OLD_BLOCK = '''def extract_structured_info(
    query: str,
    vector_store_id: str,
    schema: Any,
    retries: int = 2,
    backoff_factor: float = 1.5,
) -> Any | None:
    """
    Extracts structured info using chat completions — provider agnostic.
    vector_store_id parameter kept for backward compatibility but ignored.
    Works with Azure OpenAI, OpenAI, and any chat completions compatible provider.
    """
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
    attempt = 0
    while attempt < retries:
        try:
            logger.info("Attempt #%d to extract structured info for schema: %s", attempt + 1, schema.__name__)
            # Build schema description from Pydantic model
            try:
                schema_json = json.dumps(schema.model_json_schema(), indent=2)
            except Exception:
                schema_json = str(schema)

            system_msg = (
                "You are an expert compliance consultant. "
                "Return ONLY valid JSON matching EXACTLY this schema — no extra fields, no missing fields:\n"
                f"{schema_json}\n"
                "All required fields must be present. Return only the JSON object, no markdown."
            )
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": query},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )'''

NEW_BLOCK = '''def _to_strict_json_schema(schema: Any) -> dict:
    """
    Convert a Pydantic model's JSON schema into an OpenAI-strict-mode-compliant
    schema: every property forced into "required" (nullable fields stay
    optional-in-spirit via their anyOf/null typing, not via omission from
    required), additionalProperties: false on every object, and "default"
    keys stripped -- all required by OpenAI/Azure structured-outputs strict
    mode. Walks $defs recursively since Pydantic nests referenced models there.
    """
    import copy as _copy

    def _fix_object(node: dict) -> None:
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


def extract_structured_info(
    query: str,
    vector_store_id: str,
    schema: Any,
    retries: int = 2,
    backoff_factor: float = 1.5,
    strict: bool = False,
) -> Any | None:
    """
    Extracts structured info using chat completions — provider agnostic.
    vector_store_id parameter kept for backward compatibility but ignored.
    Works with Azure OpenAI, OpenAI, and any chat completions compatible provider.

    strict: when True, uses Azure/OpenAI structured-outputs strict mode
    (response_format type "json_schema", strict: true) instead of the
    weaker "json_object" mode -- the API then guarantees every required
    field is present and correctly typed, rather than relying on prompt
    instruction alone. Opt-in per call site; default False preserves
    existing behavior for every other caller of this function.
    """
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
    attempt = 0
    while attempt < retries:
        try:
            logger.info("Attempt #%d to extract structured info for schema: %s (strict=%s)", attempt + 1, schema.__name__, strict)
            # Build schema description from Pydantic model
            try:
                schema_json = json.dumps(schema.model_json_schema(), indent=2)
            except Exception:
                schema_json = str(schema)

            system_msg = (
                "You are an expert compliance consultant. "
                "Return ONLY valid JSON matching EXACTLY this schema — no extra fields, no missing fields:\n"
                f"{schema_json}\n"
                "All required fields must be present. Return only the JSON object, no markdown."
            )
            if strict:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.__name__,
                        "schema": _to_strict_json_schema(schema),
                        "strict": True,
                    },
                }
            else:
                response_format = {"type": "json_object"}
            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": query},
                ],
                response_format=response_format,
                temperature=0.0,
            )'''


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
        print("=== DRY RUN: OLD_BLOCK found and would be replaced ===")
        print("(diff omitted for brevity -- new block adds _to_strict_json_schema() helper")
        print(" and a strict=False parameter to extract_structured_info)")
        print("\n(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")
        print("\nNext: also update the ControlWorkpaper call site in extract_test_procedures")
        print("to pass strict=True, then restart complifyre-staging + celery-staging.")


if __name__ == "__main__":
    main()
