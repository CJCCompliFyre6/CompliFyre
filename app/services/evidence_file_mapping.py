"""Build Sequence #TBD -- Phase 6, evidence file-to-requirement mapping.
Simple first-pass version (Ankita, 23 Sept 2026: "Let's do a simple pass
first"): given a single uploaded file's extracted text and filename, judges
which of the project's guideline-level evidence requirements it satisfies,
via chunked LLM calls over the full requirements list (no embedding-based
pre-filtering yet -- that is a real, deliberate future optimization once
this simple version is proven, not built prematurely).

Filename is included as a real signal alongside extracted content, per
Ankita's own direction: a file literally named for what it is (e.g.
"Liquidity_Risk_Policy_2026.pdf") is itself useful evidence toward a match,
not just its content.
"""
from app.services.eve_tasks import _call_llm_json

REQUIREMENTS_PER_CHUNK = 40


def map_file_to_requirements(filename: str, extracted_text: str, requirements: list) -> list:
    """requirements: list of {"id": int, "evidence_item_name": str}.
    Returns a list of {"requirement_id": int, "status": "confirmed"|"needs_review",
    "reasoning": str} for every requirement judged relevant -- requirements judged
    not relevant are simply absent from the result, not returned with a
    "rejected" status (a FileRequirementMapping row is only created for an
    actual judged match; there being no row for a given requirement IS the
    "not relevant" signal, avoiding a combinatorial explosion of rows for
    every non-match across potentially thousands of requirements).
    """
    if not requirements:
        return []

    all_matches = []
    for i in range(0, len(requirements), REQUIREMENTS_PER_CHUNK):
        chunk = requirements[i:i + REQUIREMENTS_PER_CHUNK]
        prompt = _build_mapping_prompt(filename, extracted_text, chunk)
        result = _call_llm_json(prompt)
        if result and isinstance(result.get("matches"), list):
            all_matches.extend(result["matches"])

    return all_matches


def _build_mapping_prompt(filename: str, extracted_text: str, requirements_chunk: list) -> str:
    requirements_list_str = "\n".join(
        f'{r["id"]}: {r["evidence_item_name"]}' for r in requirements_chunk
    )

    # Bound extracted_text defensively -- extraction already bounds per file
    # type, but this keeps the prompt itself predictable regardless of
    # upstream changes.
    text_excerpt = (extracted_text or "")[:8000]

    return f"""You are reviewing an uploaded evidence file to judge which of a list of required evidence items it satisfies, for a compliance audit.

FILE NAME: {filename}

FILE CONTENT (representative excerpt, not necessarily the complete document):
{text_excerpt}

REQUIRED EVIDENCE ITEMS (id: description):
{requirements_list_str}

TASK: For each required evidence item in the list above, judge whether this file plausibly satisfies it. A file can satisfy zero, one, or several items. Consider both the filename and the actual content -- a filename can be a strong signal even when content excerpt alone is ambiguous, and vice versa.

For every item you judge this file satisfies (even partially or plausibly, not only with total certainty), include it in your response. Use "confirmed" when you are clearly confident, "needs_review" when it is plausible but genuinely uncertain and a human should confirm. Do not include items you judge this file does NOT satisfy -- leave those out entirely, do not list them with any status.

Return ONLY valid JSON in this exact shape, no explanation, no markdown:
{{"matches": [{{"requirement_id": <int>, "status": "confirmed"|"needs_review", "reasoning": "<one sentence>"}}]}}

If this file satisfies none of the listed items, return {{"matches": []}}."""
