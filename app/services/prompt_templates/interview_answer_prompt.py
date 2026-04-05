from pydantic import BaseModel, Field

class ComplianceQuestion(BaseModel):
    """
    A Pydantic model to represent a compliance question and its extracted answer.
    """
    id: int = Field(..., description="The unique identifier for the question.")
    question: str = Field(..., description="The compliance question that was asked.")
    answer: str = Field(..., description="The answer extracted from the content.")


def get_compliance_prompt(id: int, question: str) -> str:
    """
    Generates a prompt for an LLM to answer a compliance question based on content.

    Args:
        id: The unique identifier for the question.
        question: The compliance question to be answered.
        content: The source text from which to extract the answer.

    Returns:
        A formatted prompt string for the language model.
    """
    prompt = f"""
You are an expert in regulatory compliance, IT governance, and financial institution risk management.
Your task is to analyze the **CONTENT** provided and extract a precise answer for the **QUESTION**.

**Instructions**:
1.  Find the answer to the **QUESTION** within the **CONTENT**.
2.  Your response must be a JSON object that strictly follows the defined schema.
3.  **Highlight the exact wording of the evidence** in your answer. Include the page number if available.
4.  If the evidence is insufficient or not found, explicitly state that in the answer field.



**QUESTION**:
- ID: {id}
- Text: "{question}"

Return only the final JSON object.
"""
    return prompt