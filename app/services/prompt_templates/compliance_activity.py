from pydantic import BaseModel, Field
from app.models.ai import AIPrompts


class ComplianceActivity(BaseModel):
    compliance_level: str = Field(..., description="Compliance level: Design, Implementation, or Operating Effectiveness")
    clause: str = Field(..., description="The full text of the clause from the circular.")
    department_id: int = Field(..., description="A list unique identifier for the department.")
    relevant_departments: str = Field(..., description="The name of the department responsible for the activity.")
    process_name: str = Field(..., description="The name of the existing process within the institution.")
    sub_process_name: str = Field(..., description="The name of the existing sub-process within the institution.")
    activity_id: str = Field(..., description="A unique numerical identifier for the compliance activity (e.g., '1', '2', '3').")
    activity_description: str = Field(..., description="A detailed and actionable description of the compliance activity.")
    responsible_party: str = Field(..., description="The department or role accountable for the activity.")
    frequency: str = Field(..., description="The frequency at which the activity should be performed (e.g., daily, monthly, annually).")
    evidence_required: str = Field(..., description="Specific documentation or proof needed to demonstrate compliance.")
    justification: None | str = Field(None, description="A concise explanation for the department relevance or process mapping.")

class ComplianceRequirements(BaseModel):
    compliance_activities: list[ComplianceActivity] = Field(..., description="A list of compliance activities generated for the given clause.")

class PromptModel(BaseModel):
    clause_text: str = Field(..., description="The text of the regulatory clause to be analyzed.")
    department_list: list[str] = Field(..., description="A list of valid departments within the financial institution.")


# Updated compliance_prompt
def compliance_prompt(clause_text, department_list):
    activity_prompt = ""
    activity = AIPrompts.query.filter_by(prompt_type="ACTIVITY", is_active=True).first()
    if activity:
        activity_prompt = activity.prompt_text
    return f"""
        You are an expert BFSI compliance and audit consultant. Your task is to analyze a regulatory clause and generate a structured list of compliance activities that a financial institution must perform.

        **Objective:** Produce a complete, actionable, and auditable set of compliance activities in JSON format. Each activity must be broken down into logical steps and mapped to the appropriate department.

        ---

        ### Instructions

        1.  **Analyze the Clause**: Carefully interpret the full intent of the regulatory clause to identify every single, distinct obligation.

        2.  **Apply MECE Principle**: All activities must follow the MECE rule (Mutually Exclusive and Collectively Exhaustive) to ensure comprehensive coverage while eliminating redundancy of effort.
        
        3.  **Structure by Compliance Levels**: Organize activities under three comprehensive compliance levels:
            * **1. Design Effectiveness**: Activities ensuring the control is properly designed to prevent/detect errors
            * **2. Implementation Assessment**: Activities verifying the control has been properly deployed and implemented
            * **3. Operating Effectiveness**: Activities testing whether the control is operating as intended over time
        
        4.  **Break Down Activities**: For each obligation, break down the required action into multiple, logical activities. For example, a single clause might require activities related to:
            * **Policy & Governance**: Creating, updating, or reviewing policies.
            * **Operational Implementation**: Putting new rules into practice.
            * **Monitoring & Reporting**: Checking for compliance and reporting findings.
            * **Documentation & Evidence**: Maintaining records and proofs.

        5.  **COMPLIANCE LEVEL MAPPING:**
          - Policy creation, framework development, control design → **Design Effectiveness**
          - Deployment, configuration, training, rollout → **Implementation Assessment** 
          - Monitoring, testing, reporting, maintenance → **Operating Effectiveness**    
            
        6.  **Use Specifics**: For each activity, you must provide the following:
            * **`compliance_level`**:  MUST be one of: "Design", "Implementation", or "Operating Effectiveness"
            * **`relevant_departments`**: Identify the specific department(s) from the provided list that are responsible for the activity. If a department is not in the list, state it as "Compliance."
            * **`department_id`**: Map the identified department(s) to their corresponding `department_id` from the provided list.
            * **`process_name`**: Provide the name of a relevant business process (e.g., "KYC," "Internal Audit," "Risk Management").
            * **`sub_process_name`**: The specific step or sub-process within the main process (e.g., "Customer Onboarding," "Annual Audit," "Transaction Review").
            * **`activity_id`**: **MUST be numerical values starting from 1 and incrementing by 1 for each activity (1, 2, 3, 4, etc.)**
            * **`activity_description`**: Write a clear, detailed, and actionable description of the compliance activity. This is the most crucial part.
            * **`responsible_party`**: The specific role or team responsible for the activity (e.g., "Head of Compliance," "IT Security Team").
            * **`frequency`**: The required frequency of the activity (e.g., "Annually," "Monthly," "One-time," "As needed").
            * **`evidence_required`**: Specify the exact document or artifact that serves as proof of compliance (e.g., "Audit report," "Policy document," "System log file").
            * **`justification`**: A brief reason why this activity and department are relevant to the clause.
        
        7.  **Ensure Comprehensive Coverage**: 
            - **Design Level**: Must include activities related to policy creation, control design, framework development, and governance structure
            - **Implementation Level**: Must include activities related to deployment, configuration, training, and rollout
            - **Operating Level**: Must include activities related to monitoring, testing, reporting, and ongoing maintenance
        8.  **Activity ID Rules**:
            - **CRITICAL**: activity_id MUST be numerical values only (no letters, prefixes, or special characters)
            - Start with 1 for the first activity and increment sequentially (1, 2, 3, 4, etc.)
            - Ensure each activity has a unique numerical ID
            - Maintain sequential ordering throughout all activities    
        9.  **Adhere to the Schema**: Your response **must** be a single JSON object that perfectly conforms to the `ComplianceRequirements` Pydantic model. Do not include any introductory or concluding text.

        ---
        <ADDITIONAL_USER_INSTRUCTION>
        {activity_prompt}
        <ADDITIONAL_USER_INSTRUCTION>

        ### Input Data
        **Regulatory Clause:** {clause_text}
        **Available Departments (with IDs):** {department_list}
    """


    