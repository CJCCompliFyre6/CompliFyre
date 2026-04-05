from enum import Enum
from pydantic import BaseModel, Field
from app.models.ai import AIPrompts

class ControlType(str, Enum):
    preventive = "Preventive"
    detective = "Detective"
    corrective = "Corrective"

class Frequency(str, Enum):
    daily = "Daily"
    weekly = "Weekly"
    monthly = "Monthly"
    quarterly = "Quarterly"
    annually = "Annually"
    as_needed = "As Needed"
    one_time = "One Time"

class Severity(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"
    critical = "Critical"

class InterviewModel(BaseModel):
    roles: list[str] = Field(..., description="List of roles to be interviewed.")
    key_questions: list[str] = Field(..., description="List of questions for the auditor to ask.")

class TestProcedure(BaseModel):
    review_of_documentation: list[str] = Field(..., description="List of documents to be reviewed.")
    interviews: InterviewModel = Field(..., description="Details on interviews to be conducted.")
    walkthrough: str = Field(..., description="Description of the observed process or activity in detail.")
    sampling: str = Field(..., description="Explanation of sampling method and criteria used in detail.")

class EvidenceItem(BaseModel):
    category: str = Field(..., description="Category of evidence, e.g., 'Audit Report'.")
    items: list[str] = Field(..., description="List of evidence items under this category. ## Explain what is each item and palce it inside bracked next to item")

class ControlWorkpaper(BaseModel):
    activity_code: str = Field(..., description="Unique code for the control activity.")
    activity_name: str = Field(..., description="Exact wording of the clause activity.")
    activity_description: str = Field(..., description="Purpose and scope of the control in detail.")
    objective: str = Field(..., description="Intended outcome or goal of the control in detail.")
    owner: str = Field(..., description="Person or role responsible for the control.")
    control_type: ControlType = Field(..., description="Type of control.")
    frequency: Frequency = Field(..., description="Frequency of the control activity.")
    test_procedure: TestProcedure = Field(..., description="Detailed testing procedure.")
    evidences_artifacts_needed: list[EvidenceItem] = Field(
        ..., description="List of evidence categories and their items."
    )
    sampling_guidance: str = Field(..., description="Sample size and selection criteria.")
    auditor_observation: None |str = Field(None, description="Auditor's observations.")
    findings: None |str = Field(None, description="Gaps or deficiencies identified.")
    impact: None |str = Field(None, description="Risk assessment if findings not addressed.")
    severity: None | Severity = Field(None, description="Severity of findings.")
    recommendations: None |str = Field(None, description="Remediation suggestions.")
    reviewer_notes: None |str = Field(None, description="Additional reviewer comments.")
    explain_test_procedure: str = Field(
        ...,
        description=(
            "Step-by-step guidance for performing the activity. "
            "Include explanations of required evidence artifacts, "
            "the appropriate time for submission, and the order of questions to answer. Do not consider walkthrough and sampling "
            "All content must be formatted in Markdown."
        ),
    )


# Updated test_procedure prompt
def test_procedure(control_clauses, control_activity):
    test_procedure_prompt = ""
    test_procedure = AIPrompts.query.filter_by(prompt_type="TEST_PROCEDURE", is_active=True).first()
    if test_procedure:
        test_procedure_prompt = test_procedure.prompt_text
    return f"""
        You are an expert in regulatory compliance, internal controls, and audit procedures. Your task is to generate a detailed control testing workpaper in valid JSON format.

        Your output **must** be a single JSON object that strictly adheres to the provided `ControlWorkpaper` Pydantic model.

        ### Input Data
        **Regulatory Clause:** {control_clauses}
        **Compliance Activity:** {control_activity}
        ### From Compliance Activity only focus on activity description. Using description design test procedure

        ### Instructions for Generating the Workpaper

        1.  **Workpaper Identification:**
            * **`activity_code`**: Use the value of the `activity_id` field from the provided `Compliance Activity` input.
            * **`activity_name`**: The exact wording of the compliance activity from the input.
            * **`activity_description`**: A detailed summary of the control's purpose and scope.
            * **`objective`**: The specific goal or intended outcome of this activity, focusing on what it's designed to achieve.
            * **`owner`**: The specific role or team responsible for the control (e.g., "IT Manager," "Head of Compliance").

        2.  **Control Classification:**
            * **`control_type`**: Classify the control as either 'Preventive', 'Detective', or 'Corrective'.
            * **`frequency`**: Determine the appropriate frequency for the control activity (e.g., 'Daily', 'Annually', 'One Time').

        3.  **Detailed Test Procedure (`test_procedure`):**
            #### Design a step by step procedure to perform such an audit. It must include the below as appropriate. Make sure to consolidate the test steps that concern a single piece of evidence so that the evidence list contains unique items only (avoid redundancy in asking for evidences)
            * **`review_of_documentation`**: List every specific document or policy that an auditor needs to review to test the control (e.g., "Risk Management Policy," "Access Control Logs").
            * **`interviews`**:
                * `roles`: List all job roles to be interviewed (e.g., "System Administrator," "Compliance Officer").
                * `key_questions`: Write specific, open-ended questions for each role to verify the control's effectiveness.
            * **`walkthrough`**: Describe a step-by-step walkthrough of the process. An auditor should be able to follow this description to observe the control in action.
            * **`sampling`**: Explain the sampling method (e.g., "Random sample of 10 records," "Systematic sample of transactions") and the rationale behind it.

        4.  **Evidence & Guidance:**
            * **`evidences_artifacts_needed`**: Create a list of evidence items. Each item must have a `category` (e.g., "System Logs," "Reports") and a list of specific `items` (e.g., "Firewall log extracts for Q3," "Access review report").
            * **`sampling_guidance`**: Provide clear instructions on sample size and criteria (e.g., "Select a random sample of 25 loan files from the past quarter.").

        5.  **Optional Fields:**
            * **`auditor_observation`**, **`findings`**,  **`recommendations`**, **`reviewer_notes`**: You must explicitly set these fields to `null` as they are for post-audit findings and should be empty at this stage. **Do not generate any text for these fields.**

        <ADDITIONAL_USER_INSTRUCTION>
        {test_procedure_prompt}
        <ADDITIONAL_USER_INSTRUCTION>

        ### Your final output must contain only the JSON object, formatted as requested. No extra text, no markdown headers, and no conversational language.
    """

