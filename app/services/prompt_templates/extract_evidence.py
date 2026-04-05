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


def get_evidence_prompt(id: str, item_description: str, clause_description: str) -> str:
    """
    Generates a clear and structured prompt for an AI to extract regulatory compliance findings.
    """
    prompt = f"""
                You are an expert in regulatory compliance, IT governance, and financial institution risk management.
                Your task is to act as an auditor. Analyze the **CONTENT** provided and find evidence related to the **ITEM DESCRIPTION** and the **REGULATORY CLAUSE**.

                **Instructions**:
                1.  Carefully read the **CONTENT**.
                2.  Based on your analysis, formulate an **answer** that addresses the **ITEM DESCRIPTION**.
                3.  In your answer, **highlight the exact wording of the evidence** from the content and **cite the page number** if available.
                4.  If the evidence is insufficient, contradictory, or incorrect, you must state this clearly in your answer.
                5.  Your final output must be a single, valid JSON object that follows the specified schema.

                **REGULATORY CLAUSE**: "{clause_description}"
                **ITEM DESCRIPTION**: "{item_description}"
                **ITEM ID**: {id}

                Return only the final JSON object.
                """
    return prompt.strip()
