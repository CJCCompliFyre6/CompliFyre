from pydantic import BaseModel, Field


class ComplianceEvidence(BaseModel):
    """
    A Pydantic model for compliance evidence findings.
    """

    id: str = Field(..., description="The unique identifier for the evidence item.")
    item_description: str = Field(
        ..., description="The description of the item being reviewed."
    )
    clause_description: str = Field(
        ..., description="The specific clause or regulation checked."
    )
    answer: str = Field(
        ...,
        description="The extracted findings, evidence, or issues from the content, including page numbers.",
    )


def get_evidence_prompt(
    id: str,
    item_description: str,
    clause_description: str,
) -> str:
    """
    Builds a grounded evidence extraction prompt for a single checklist item.
    The document content is passed separately as the user message.
    """
    return f"""
You are an expert regulatory compliance auditor specialising in IT governance and financial institution risk management.

YOUR TASK:
Analyse the document content provided and extract evidence relevant to the checklist item and regulatory clause below.

STRICT RULES — you must follow these without exception:
1. Extract ONLY what is explicitly stated in the document. Do NOT infer, assume, or fabricate.
2. If the relevant evidence is present, quote or closely paraphrase it and cite the page number or section.
3. If the evidence is absent, write "NOT_FOUND" in the answer field. Never guess.
4. If the evidence is present but contradictory or insufficient, state this clearly and explain why.
5. Return ONLY a valid JSON object matching the schema below. No preamble, no explanation outside the JSON.

CHECKLIST ITEM:
- ID: {id}
- Item Description: {item_description}
- Regulatory Clause: {clause_description}

REQUIRED JSON SCHEMA:
{{
  "id": "{id}",
  "item_description": "{item_description}",
  "clause_description": "{clause_description}",
  "answer": "<exact quote or close paraphrase from the document, with page/section reference. If absent: NOT_FOUND>",
  "evidence_reference": "<page number, section heading, or clause number where evidence was found. If absent: NOT_FOUND>",
  "confidence": "<HIGH | MEDIUM | LOW>",
  "signal": "<SUPPORTS | CONTRADICTS | INSUFFICIENT | NOT_FOUND>"
}}

Return only the JSON object.
""".strip()
