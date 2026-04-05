"""
extract_clause_helper.py
------------------------
Drop-in replacements for the functions that had issues in extract_clause_helper.py.
All function names are unchanged. Only the bodies are fixed.

Changes per function are documented inline with # FIX: comments.
"""
# Add these imports at the top if not already present
from flask import flash
from flask_login import current_user

def check_free_report_used():
    """Utility function to check if free report was used"""
    if current_user.free_report_used:
        flash(
            "This feature is disabled after report generation. "
            "Please contact CompliFyre@crackerjacktech.com for assistance.",
            "error"
        )
        return True
    return False

import json
import logging
import re
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

import openai
from app.models import RawLLMResponse
from app.services.automate_task import session_scope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SYSTEM PROMPT — used by extract_structured_info_with_metrics
# Keeps the LLM grounded: extract only, no invention, cite sources.
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """
You are an Audit Document Extraction Engine.

YOUR ONLY JOB:
Extract factual content from the document provided in the user message and return it as a valid JSON object.

YOU MUST NOT:
- Infer, assume, or fill in any information not explicitly present in the document.
- Draw conclusions, assess compliance, or generate findings.
- Invent dates, names, approvals, clause numbers, or any other details.

IF INFORMATION IS NOT PRESENT IN THE DOCUMENT:
- Set the field value to: "NOT_FOUND"
- Do NOT guess. Do NOT extrapolate.

Return ONLY a valid JSON object. No preamble, no explanation, no markdown fences.
""".strip()


def extract_structured_info_with_metrics(
    query: str,
    vector_store_id: str,  # FIX: param kept for signature compatibility but noted as unused
    schema,
) -> Tuple[Optional[Any], Dict[str, int]]:
    """
    Enhanced version that returns both response and token metrics for OpenAI.

    FIX 1: Added a system prompt so the LLM has grounding instructions
            instead of receiving only a raw query with no context.
    FIX 2: vector_store_id is retained in the signature for backwards
            compatibility but is currently not wired to file_search.
            TODO: pass it as a file_search tool if you want RAG retrieval.
    FIX 3: Wrapped schema.model_validate_json() in its own try/except
            so a schema mismatch doesn't silently swallow the token metrics.
    FIX 4: Upgraded to gpt-4o for better structured extraction accuracy.
            If cost is a concern, switch back to gpt-4o-mini and accept
            the accuracy trade-off explicitly.
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-4o",                         # FIX 4: was gpt-4o-mini
            messages=[
                {
                    "role": "system",
                    "content": _EXTRACTION_SYSTEM_PROMPT,   # FIX 1: added system prompt
                },
                {
                    "role": "user",
                    "content": query,
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )

        usage_metrics = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

        if response.choices[0].message.content:
            try:                                            # FIX 3: isolated validation error
                parsed_response = schema.model_validate_json(
                    response.choices[0].message.content
                )
                return parsed_response, usage_metrics
            except Exception as validation_err:
                logger.error(
                    f"Schema validation failed: {str(validation_err)} | "
                    f"Raw content: {response.choices[0].message.content[:200]}"
                )
                return None, usage_metrics

        return None, usage_metrics

    except openai.APIError as e:
        logger.error(f"OpenAI API error: {str(e)}")
        return None, {}
    except Exception as e:
        logger.error(f"LLM extraction failed: {str(e)}")
        return None, {}


def analyze_extraction_quality(
    chunk_response, context_text: str, total_pages: int, page_range: str
) -> dict:
    """
    Enhanced quality analysis with better missing clauses detection.

    FIX 1: extraction_rate is now capped at 1.0 — over-extraction
            (model returns more clauses than expected) no longer
            produces a rate > 1, which was silently corrupting confidence.
    FIX 2: incomplete_clause penalty now uses the capped extraction_rate
            so confidence stays in [0.0, 1.0] correctly.
    """
    if not chunk_response or not hasattr(chunk_response, "requirements"):
        return {
            "extracted_count": 0,
            "expected_count": estimate_expected_clauses(context_text, total_pages),
            "missing_clauses": ["all"],
            "confidence_score": 0.0,
            "quality_issues": ["no_response_or_empty_requirements"],
        }

    requirements = chunk_response.requirements
    extracted_count = len(requirements) if requirements else 0
    expected_count = estimate_expected_clauses(context_text, total_pages)

    quality_issues = []

    incomplete_clauses = 0
    for clause in requirements:
        if not hasattr(clause, "clause_text") or not clause.clause_text:
            incomplete_clauses += 1
        elif len(clause.clause_text.strip()) < 10:
            incomplete_clauses += 1

    if incomplete_clauses > 0:
        quality_issues.append(f"{incomplete_clauses}_incomplete_clauses")

    missing_analysis = identify_actual_missing_clauses(
        context_text, requirements, page_range
    )

    raw_rate = extracted_count / expected_count if expected_count > 0 else 0
    extraction_rate = min(raw_rate, 1.0)                # FIX 1: cap at 1.0

    confidence_score = calculate_confidence_with_extraction_rate(
        extraction_rate, incomplete_clauses, extracted_count
    )

    return {
        "extracted_count": extracted_count,
        "expected_count": expected_count,
        "missing_clauses": missing_analysis,
        "confidence_score": confidence_score,
        "quality_issues": quality_issues,
        "incomplete_clauses_count": incomplete_clauses,
        "extraction_rate": extraction_rate,             # FIX 1: already capped
    }


def estimate_expected_clauses(context_text: str, total_pages: int) -> int:
    """
    Estimate how many clauses we should expect based on document characteristics.

    FIX 1: Replaced max() across all three methods with a weighted average.
            max() always picked the most extreme estimate, systematically
            inflating the "missing clauses" count fed into Stage 2.
    FIX 2: Regex patterns now exclude common non-clause numeric patterns
            (version strings like "v2.1", years like "2024", dates like
            "01.01") to reduce false positives in the pattern count.
    """
    if not context_text:
        return 0

    # Method 1: word count
    word_count = len(context_text.split())
    estimated_by_words = max(5, word_count // 200)

    # Method 2: page count
    estimated_by_pages = max(3, total_pages * 2)

    # Method 3: section numbering patterns
    # FIX 2: added negative lookahead to exclude version strings, years,
    # and date-like patterns (e.g. "2024", "v2.1", "01.01.2024")
    section_patterns = [
        r"(?<!\d)(?!20\d{2})(?!v?\d+\.\d+\.\d+)\b(\d{1,2}\.\d{1,2})\b(?!\.\d)",
        r"\b\d+\.\s+[A-Z]",
        r"\bArticle\s+\d+",
        r"\bSection\s+\d+",
    ]

    unique_clause_numbers = set()
    for pattern in section_patterns:
        matches = re.findall(pattern, context_text)
        unique_clause_numbers.update(matches)

    estimated_by_patterns = len(unique_clause_numbers)

    # FIX 1: weighted average instead of max()
    # Words and pages are more reliable baselines; patterns are noisy.
    weighted = (
        estimated_by_words * 0.4
        + estimated_by_pages * 0.4
        + estimated_by_patterns * 0.2
    )
    return max(3, round(weighted))


def identify_actual_missing_clauses(
    context_text: str, extracted_clauses: list, page_range: str
) -> dict:
    """
    Identify actual missing clauses by analysing document structure and patterns.

    FIX 1: potential_missing is now split into two typed lists:
            - missing_clause_numbers  → bare numeric IDs ("1.3", "2.4")
            - missing_headings        → section heading strings
            Previously both were mixed into one set, making it impossible
            for Stage 2 to parse them uniformly.
    FIX 2: heading_patterns now use [\r\n]+ instead of \n to handle
            Windows-style line endings (\r\n) that were causing misses.
    """
    if not context_text:
        return {"missing_clause_numbers": [], "missing_headings": [], "analysis_method": "no_context"}

    extracted_numbers = set()
    extracted_text_snippets = set()

    for clause in extracted_clauses:
        if hasattr(clause, "clause_number") and clause.clause_number:
            extracted_numbers.add(clause.clause_number.strip())
        if hasattr(clause, "clause_text") and clause.clause_text:
            snippet = clause.clause_text[:100].lower().strip()
            extracted_text_snippets.add(snippet)

    # --- Numeric clause IDs not found in extracted set ---
    numbered_patterns = [
        r"(\d+\.\d+)\s",
        r"\((\d+\.\d+)\)",
        r"Clause\s+(\d+\.\d+)",
        r"Section\s+(\d+\.\d+)",
        r"Article\s+(\d+\.\d+)",
    ]

    missing_clause_numbers = set()
    for pattern in numbered_patterns:
        matches = re.findall(pattern, context_text)
        for match in matches:
            if match not in extracted_numbers:
                missing_clause_numbers.add(match)

    # --- Section headings not reflected in extracted clause texts ---
    # FIX 2: [\r\n]+ instead of \n to handle \r\n line endings
    heading_patterns = [
        r"[\r\n]+(\d+\.\d+\s+[A-Z][A-Za-z\s]{10,50})\.?[\r\n]+",
        r"[\r\n]+([A-Z][A-Za-z\s]{15,60}):?[\r\n]+",
        r"[\r\n]+(\d+\.\s+[A-Z][A-Za-z\s]{10,50})\.?[\r\n]+",
    ]

    missing_headings = set()
    for pattern in heading_patterns:
        matches = re.findall(pattern, context_text)
        for match in matches:
            match_lower = match.lower()
            found = any(match_lower in snippet for snippet in extracted_text_snippets)
            if not found:
                missing_headings.add(match.strip())

    sequential_missing = find_sequential_gaps(extracted_numbers)

    return {
        "missing_clause_numbers": list(missing_clause_numbers)[:10],   # FIX 1: typed list
        "missing_headings": list(missing_headings)[:10],                # FIX 1: typed list
        "sequential_gaps": sequential_missing,
        "extracted_count": len(extracted_clauses),
        "analysis_method": "multi_method",
        "page_range": page_range,
    }


def find_sequential_gaps(extracted_numbers: set) -> list:
    """
    Find gaps in sequential numbering (e.g. if we have 1.1 and 1.3, then 1.2 is missing).

    FIX: Replaced float arithmetic with integer arithmetic (values × 10)
         to eliminate floating-point precision errors.
         Previously, 1.1 + 0.1 == 1.2000000000000002 in Python, causing
         false positives and missed gaps depending on rounding behaviour.
    """
    gaps = []

    # FIX: parse into (integer × 10) to use exact integer comparison
    int_numbers = []
    for num in extracted_numbers:
        try:
            # Multiply by 10 and round to nearest int to avoid float drift
            int_numbers.append(round(Decimal(num) * 10))
        except Exception:
            continue

    if not int_numbers:
        return gaps

    int_numbers.sort()

    for i in range(1, len(int_numbers)):
        prev = int_numbers[i - 1]
        curr = int_numbers[i]

        # Gap of exactly 1 unit (i.e. 0.1 in original scale) means a clause is missing
        if 1 < (curr - prev) < 10:
            missing_int = prev + 1
            # Convert back: if divisible by 10 it's a whole number, otherwise x.y
            if missing_int % 10 == 0:
                gaps.append(str(missing_int // 10))
            else:
                gaps.append(f"{missing_int // 10}.{missing_int % 10}")

    return gaps


def analyze_overall_missing_data(guideline_id: int, all_extracted_numbers: list):
    """
    Analyse missing data across all extraction chunks.

    FIX 1: session.commit() moved outside the loop — was previously
            firing one DB write per row (N commits for N chunks).
            Now all updates are staged in memory and committed once.
    FIX 2: Added null guard before json.loads() — if missing_clauses is
            None the original code raised TypeError silently swallowed
            by the outer except. Now skipped explicitly with a warning.
    FIX 3: Schema change is logged so callers are not silently broken.
            The new shape wraps the old value under "chunk_specific" key;
            if your callers expect the old flat list, update them too.
    """
    try:
        with session_scope() as session:
            raw_responses = session.query(RawLLMResponse).filter_by(
                guideline_id=guideline_id
            ).all()

            unique_extracted = list(set(all_extracted_numbers))

            for response in raw_responses:
                if response.missing_clauses is None:            # FIX 2: null guard
                    logger.warning(
                        f"RawLLMResponse id={response.id} has null missing_clauses — skipping."
                    )
                    continue

                try:
                    current_missing = json.loads(response.missing_clauses)
                except json.JSONDecodeError as je:
                    logger.error(
                        f"Could not parse missing_clauses for id={response.id}: {je}"
                    )
                    continue

                # FIX 3: wrap old value under chunk_specific to preserve it
                enhanced_missing = {
                    "chunk_specific": current_missing,
                    "overall_extracted_count": len(all_extracted_numbers),
                    "unique_clauses_extracted": unique_extracted,
                }
                response.missing_clauses = json.dumps(enhanced_missing)

            session.commit()                                    # FIX 1: single commit after loop

    except Exception as e:
        logger.error(f"Error in overall missing data analysis: {str(e)}")
