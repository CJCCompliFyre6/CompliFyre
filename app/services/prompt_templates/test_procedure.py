from enum import Enum
from pydantic import BaseModel, Field, field_validator
from app.models.ai import AIPrompts

class ControlType(str, Enum):
    preventive = "Preventive"
    detective = "Detective"
    corrective = "Corrective"
    governance = "Governance"
    directive = "Directive"
    compensating = "Compensating"

class Frequency(str, Enum):
    daily = "Daily"
    weekly = "Weekly"
    monthly = "Monthly"
    quarterly = "Quarterly"
    semi_annual = "Semi-Annual"
    annually = "Annually"
    as_needed = "As Needed"
    one_time = "One Time"
    continuous = "Continuous"
    ad_hoc = "Ad-hoc"
    per_transaction = "Per Transaction"
    event_driven = "Event-Driven"

class Severity(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"
    critical = "Critical"

class AssessmentObjectiveType(str, Enum):
    design_effectiveness = "Design Effectiveness"
    operating_effectiveness = "Operating Effectiveness"
    substantive_testing = "Substantive Testing"

class FilterCondition(BaseModel):
    column_description: str = Field(..., description="Natural language description of the column to filter on. e.g. 'Loan Type column', 'Applicant Category column'")
    filter_value: str = Field(..., description="Value to filter for. e.g. 'Home Loan', 'BPL', 'Yes'")
    filter_type: str = Field(..., description="Type of filter: 'equals', 'contains', 'greater_than', 'less_than', 'not_equals'")

class TestAttribute(BaseModel):
    attribute_name: str = Field(..., description="Name of the specific attribute being tested. e.g. 'Interest rate within limit for BPL home loan applicants'")
    attribute_description: str = Field(..., description="Detailed description of what this attribute tests and why it matters for compliance.")
    
    # Data filtering — how to identify the right population
    population_filters: list[FilterCondition] = Field(..., description="Sequential filters to apply to identify the exact population to test. e.g. First filter: Loan Type = Home Loan, Second filter: Applicant Category = BPL")
    population_description: str = Field(..., description="Plain English description of the population after filters. e.g. 'All home loans granted to BPL applicants during audit period'")
    
    # Test condition — what to test on the filtered population
    test_column_description: str = Field(..., description="Natural language description of the column to test. e.g. 'Interest Rate column'")
    test_condition: str = Field(..., description="The condition to test. e.g. 'must not exceed 7%', 'must be present', 'must be within 24 hours'")
    test_type: str = Field(..., description="Type of test: 'numeric_threshold', 'presence_check', 'date_difference', 'value_match', 'percentage_check'")
    
    # Expected vs Actual
    expected_value: str = Field(..., description="The expected/compliant value or range. e.g. '≤ 7%', 'Present', 'Within 24 hours'")
    threshold: str = Field(..., description="Specific threshold value if applicable. e.g. '7', '24', '100'")
    threshold_unit: str = Field(..., description="Unit of threshold if applicable. e.g. '%', 'hours', 'days', 'INR'")
    
    # Pass/Fail criteria
    pass_criteria: str = Field(..., description="Precise measurable criteria for PASS. e.g. 'Interest rate ≤ 7% for all BPL home loan applicants'")
    fail_criteria: str = Field(..., description="Precise measurable criteria for FAIL. e.g. 'Interest rate > 7% for any BPL home loan applicant'")
    
    # Reporting
    exception_identifier_column: str = Field(..., description="Column that uniquely identifies each record for exception reporting. e.g. 'Application Number', 'Loan ID', 'Transaction ID'")
    regulatory_reference: str = Field(..., description="Specific regulatory clause or policy reference this attribute tests. e.g. 'Clause 7.2 — Interest rate cap for BPL applicants'")
    severity_if_failed: str = Field(..., description="Severity if this attribute fails: 'Critical', 'Major', 'Significant', 'Minor'")
    
    # Testing sequence
    testing_sequence: int = Field(..., description="Order in which this attribute should be tested. Start from 1.")
    depends_on_attribute: str | None = Field(None, description="Name of attribute that must pass before this one is tested. Leave null if independent.")

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
    @field_validator("frequency", mode="before")
    @classmethod
    def normalize_frequency(cls, v):
        if isinstance(v, str):
            synonym_map = {
                "periodic": "As Needed",
                "periodically": "As Needed",
                "ongoing": "Continuous",
                "regular": "As Needed",
                "yearly": "Annually",
                "annual": "Annually",
                "half-yearly": "Semi-Annual",
                "half yearly": "Semi-Annual",
                "bi-annual": "Semi-Annual",
                "biannual": "Semi-Annual",
                "event driven": "Event-Driven",
                "adhoc": "Ad-hoc",
                "ad hoc": "Ad-hoc",
                "one-time": "One Time",
                "onetime": "One Time",
            }
            return synonym_map.get(v.strip().lower(), v)
        return v

    # These three are correctly None at initial generation time -- they belong to a
    # later, separate stage. assessment_objective/rationale and test_attributes are
    # mechanically derived from the project's OE checklist items when an auditor
    # uploads real test data (see app/routes/audit/view.py upload_test_data() ->
    # app/services/attribute_testing_engine.py run_attribute_testing()) -- not
    # generated here, and never should be, to avoid a second, independent,
    # potentially-drifting source of the same data. Build Sequence #377.
    assessment_objective: None | AssessmentObjectiveType = Field(None, description="Primary objective of this assessment — Design Effectiveness, Operating Effectiveness, or Substantive Testing. Populated later from the checklist, not at initial generation.")
    assessment_objective_rationale: None | str = Field(None, description="Brief explanation of why this assessment objective was selected. Populated later from the checklist, not at initial generation.")
    test_attributes: None | list[TestAttribute] = Field(None, description="List of specific attributes to be tested. Populated later from the checklist's OE items when real audit data is uploaded, not at initial generation.")
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
    test_procedure = AIPrompts.query.filter_by(
        prompt_type="TEST_PROCEDURE", is_active=True
    ).first()
    if test_procedure and test_procedure.prompt_text:
        test_procedure_prompt = f"""
ADDITIONAL INSTRUCTIONS:
{test_procedure.prompt_text}
"""

    return f"""
You are an expert in regulatory compliance, internal controls, and audit procedures.
Your task is to generate a detailed control testing workpaper in valid JSON format.

Your output MUST be a single JSON object that strictly adheres to the schema defined below.

INPUT DATA:
- Regulatory Clause: {control_clauses}
- Compliance Activity: {control_activity}

Note: From the Compliance Activity, use activity_description for the content and compliance_level for the testing scope — strictly follow section 3 guidance.
CRITICAL — DATES & PERIODS: NEVER use any specific year, quarter, or date in evidence names or descriptions (e.g., do NOT write "Q2 2023 Report", "Q1 2024 Report", "2023 Compliance Report").

INSTRUCTIONS:

0. ASSESSMENT OBJECTIVE & TEST ATTRIBUTES:

   A. ASSESSMENT OBJECTIVE (Mandatory):
   Determine the PRIMARY objective of this assessment based on the compliance_level:
   - If compliance_level = "Design": Assessment Objective = "Design Effectiveness"
     Rationale: Testing whether the control is properly designed — policies documented, framework defined, roles assigned.
   - If compliance_level = "Implementation": Assessment Objective = "Operating Effectiveness"
     Rationale: Testing whether the designed control has been implemented and is operating.
   - If compliance_level = "Operating Effectiveness": Assessment Objective = "Operating Effectiveness"
     Rationale: Testing whether the control operates consistently over the audit period.
   - If controls are absent or fundamentally weak: Consider "Substantive Testing"
     Rationale: When controls cannot be relied upon, substantive procedures provide direct evidence.

   B. TEST ATTRIBUTES (Mandatory — Core of Attribute Testing):
   Define specific, measurable attributes that will be tested for this control.
   
   ATTRIBUTE TESTING PHILOSOPHY:
   Attribute testing is the systematic examination of EACH item in a population against 
   specific, pre-defined criteria. Unlike subjective review, attribute testing produces:
   - Binary Pass/Fail results per item
   - Exception rates (e.g., "4 out of 25 loans exceeded the interest cap = 16% exception rate")
   - Population impact assessment
   - Specific exception identifiers (application numbers, transaction IDs)

   RULES FOR DEFINING ATTRIBUTES:
   - Each attribute must be BINARY testable (Pass/Fail per record)
   - Define EXACT filters to identify the correct population BEFORE testing
   - Filters must be SEQUENTIAL — apply in the right order to narrow down population
   - Test conditions must be PRECISE and MEASURABLE
   - Minimum 3 attributes, maximum 7 attributes per control
   - Assign testing sequence — simpler/broader tests first
   - Identify the UNIQUE IDENTIFIER column for exception reporting

   POPULATION FILTERING — CRITICAL:
   Before testing any attribute, you MUST define how to filter the data:
   Step 1: What is the FULL dataset? (e.g., "All loans granted during audit period")
   Step 2: What filters narrow it to the RELEVANT population? 
           (e.g., Filter 1: Loan_Type = "Home Loan" → Filter 2: Applicant_Category = "BPL")
   Step 3: What is the FINAL population to test?
           (e.g., "All home loans granted to BPL applicants during audit period")

   EXAMPLE — Interest Rate Control for BPL Home Loans:
   Control: "Interest for home loans should not exceed 7% for BPL applicants"
   
   Attribute 1: "Interest rate within regulatory cap for BPL home loan applicants"
   - Population Filters: 
     Filter 1: Loan_Type column = "Home Loan" (equals)
     Filter 2: Applicant_Category column = "BPL" (equals)
   - Population Description: "All home loans granted to BPL applicants during audit period"
   - Test Column: "Interest_Rate column"
   - Test Condition: "must not exceed 7%"
   - Test Type: "numeric_threshold"
   - Expected Value: "≤ 7%"
   - Threshold: "7", Unit: "%"
   - Pass Criteria: "Interest rate ≤ 7% for ALL BPL home loan applicants"
   - Fail Criteria: "Interest rate > 7% for ANY BPL home loan applicant"
   - Exception Identifier: "Application_Number column"
   - Severity if Failed: "Critical"
   - Testing Sequence: 1

   EXAMPLE — Approval TAT Control:
   Control: "Loan applications must be approved within 3 working days"
   
   Attribute 1: "Approval turnaround time within prescribed limit"
   - Population Filters:
     Filter 1: Application_Status column = "Approved" (equals)
   - Test Column: "Days_to_Approval column" (or calculated from Application_Date and Approval_Date)
   - Test Condition: "must not exceed 3 working days"
   - Test Type: "date_difference" or "numeric_threshold"
   - Expected Value: "≤ 3 working days"
   - Threshold: "3", Unit: "days"
   - Pass Criteria: "Days between application and approval ≤ 3 working days"
   - Fail Criteria: "Days between application and approval > 3 working days"
   - Exception Identifier: "Application_ID column"
   - Severity if Failed: "Major"
   - Testing Sequence: 1

   CRITICAL RULES:
   - ALWAYS define population_filters before defining test conditions
   - Column names should be DESCRIPTIVE (not assumed) — describe what the column contains
   - exception_identifier_column MUST uniquely identify each record
   - testing_sequence determines order of execution — dependencies first
   - If one attribute depends on another passing, set depends_on_attribute

1. WORKPAPER IDENTIFICATION:
   - activity_code: Use the activity_id from the Compliance Activity input.
   - activity_name: Exact wording of the compliance activity.
   - activity_description: Detailed summary of the control's purpose and scope.
   - objective: Specific goal this control is designed to achieve.
   - owner: Role or team responsible (e.g. "IT Manager", "Head of Compliance").

2. CONTROL CLASSIFICATION:
   - control_type: One of "Preventive", "Detective", or "Corrective".
   - frequency: e.g. "Daily", "Annually", "One Time".

3. COMPLIANCE LEVEL GUIDANCE:
   The activity has been pre-classified as: {control_activity.get("compliance_level", "Design") if isinstance(control_activity, dict) else "Design"}
   
   DEPENDENCY HIERARCHY — MANDATORY:
   Each level DEPENDS on the previous level. You MUST understand and acknowledge this dependency in your test procedure:

   - If "Design": 
     INDEPENDENT level — no dependency on other levels.
     Focus ONLY on: Are policies documented? Is the control framework defined? Are roles and responsibilities assigned? Is the control approved by the correct authority?
     Evidence: Policy documents, framework documentation, board/management approvals, role definitions.
     Do NOT test implementation or operating effectiveness.

   - If "Implementation":
     DEPENDS ON Design. You MUST first confirm that a Design exists (policy/framework is in place), then test whether it has been implemented.
     Step 1 — Acknowledge Design: Note that the control design (policy/framework) is assumed to be in place as a prerequisite.
     Step 2 — Test Implementation: Has the control been deployed as designed? Are systems configured? Are staff trained? Are procedures being followed?
     Evidence: System configuration screenshots, training completion records, deployment evidence, SOPs.
     Do NOT re-test design. Do NOT test operating effectiveness.

   - If "Operating Effectiveness":
     DEPENDS ON both Design AND Implementation. You MUST first confirm both exist, then test whether the control operates consistently.
     Step 1 — Acknowledge Design & Implementation: Note that design and implementation are assumed to be in place as prerequisites.
     Step 2 — Test Operating Effectiveness: Is the control operating consistently over the audit period? Sample transactions, verify evidence of repeated execution, test adherence over time.
     Evidence: Transaction logs, monitoring reports, samples from audit period, exception reports.
     Sampling is MANDATORY for Operating Effectiveness — select representative samples from the audit period.
     Do NOT re-test design or implementation.

4. TEST PROCEDURE:
   Design a step-by-step audit procedure aligned to the compliance level above. Consolidate steps that concern the same
   piece of evidence — the evidence list must contain unique items only.
   - review_of_documentation: List every specific document an auditor must review.
   - interviews:
       - roles: All job roles to be interviewed.
       - key_questions: Specific open-ended questions per role.
   - walkthrough: Step-by-step description an auditor can follow to observe the control.
   - sampling: IMPORTANT — Sampling applies ONLY to "Operating Effectiveness" level activities. 
     If compliance_level is "Design" or "Implementation", set sampling to "Not applicable — sampling is only required for Operating Effectiveness testing."
     If compliance_level is "Operating Effectiveness", provide sampling method and rationale (e.g. "Random sample of 25 records from the past 12 months").

5. EVIDENCE AND GUIDANCE:
   - evidences_artifacts_needed: List of objects, each with:
       - category: e.g. "System Logs", "Reports"
       - items: list of specific evidence items. Where an item is a formal document that would
         typically go through drafting and approval (a policy, procedure, SOP, or similar governance
         document), it must always refer to the FINAL, approved/signed-off version -- never "draft,"
         "preliminary," or "pending approval." This does not apply to items without a draft/final
         distinction, such as logs, records, screenshots, or system reports.
         Where the activity involves staff training or awareness sessions, evidence must include a
         post-training assessment score demonstrating comprehension -- never attendance records alone,
         since attendance does not prove understanding. Specify a minimum passing score of 70% as the
         acceptance criterion for the assessment.
         Where the activity describes creating, building, configuring, or deploying a specific, named
         technical deliverable (a flowchart, a system integration, a technical configuration, a
         dashboard, a tool), evidence must include the deliverable itself or direct proof of its
         existence and functioning -- e.g. the actual flowchart document, screenshots of the configured
         system, or validation results confirming it works -- never governance-style documentation
         alone (roles, approvals, policy documents) about the deliverable, since that proves who
         authorized it, not that it actually exists or functions.
   - sampling_guidance: IMPORTANT — Only provide sampling guidance for "Operating Effectiveness" activities. For "Design" or "Implementation", set to "Not applicable."

6. NULL FIELDS (post-audit only — do NOT generate content for these):
   - auditor_observation: null
   - findings: null
   - recommendations: null
   - reviewer_notes: null

REQUIRED JSON SCHEMA:
{{
  "activity_code": "string",
  "activity_name": "string",
  "activity_description": "string",
  "objective": "string",
  "owner": "string",
  "control_type": "Preventive | Detective | Corrective | Governance | Directive | Compensating",
  "frequency": "string",
  "test_procedure": {{
    "review_of_documentation": ["string"],
    "interviews": {{
      "roles": ["string"],
      "key_questions": ["string"]
    }},
    "walkthrough": "string",
    "sampling": "string"
  }},
  "evidences_artifacts_needed": [
    {{
      "category": "string",
      "items": ["string"]
    }}
  ],
  "sampling_guidance": "string",
  "explain_test_procedure": "Step-by-step guidance in Markdown for performing this activity's testing -- what evidence to gather and when, what to review, who to interview and in what order, what to check during walkthrough. Do not repeat the structured walkthrough/sampling fields verbatim -- this is the narrative explanation an auditor reads before starting the test.",
  "auditor_observation": null,
  "findings": null,
  "recommendations": null,
  "reviewer_notes": null
}}{test_procedure_prompt}
Return only the JSON object. No markdown, no extra text, no explanation.
""".strip()

