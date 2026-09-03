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
        
        2b. **RE PERSPECTIVE RULE** (CRITICAL — Non-negotiable):
            - Generate ONLY activities that the **RE (Regulated Entity)** — i.e., the Bank, NBFC, or financial institution being audited — must perform to comply with the clause
            - Do NOT generate activities for: RBI/Regulator, SEBI, IRDAI, LSPs, third-party vendors, external auditors, rating agencies, or any body outside the RE
            - Do NOT generate activities that describe what the regulator expects to see or what regulators/supervisors will do — only what the RE must DO
            - Do NOT generate activities about what an industry body, association, or committee outside the RE is supposed to do
            - Every activity must be owned and executable by the RE internally
            - Every activity_description must start with an action verb owned by the RE: "Develop", "Implement", "Monitor", "Establish", "Ensure", "Maintain", "Submit", "Train", "Review", "Document", "Conduct", "Designate", "Appoint", "Report", "Verify"
            - WRONG example: "RBI will inspect the institution's KYC records" → this is regulator's action, NOT RE's
            - WRONG example: "LSP shall not exercise sanctioning authority" → this is LSP's obligation, NOT RE's
            - RIGHT example: "Develop and implement a KYC policy framework approved by the Board" → RE's own action

        2a. **STRICT UNIQUENESS RULES** (CRITICAL):
            - Every activity_description must be **completely different** from every other activity in the list
            - Do NOT generate two activities that do the same thing with slightly different wording
            - Each activity must cover a **distinct action, obligation, or control** from the clause
            - If two activities seem similar, merge them into one more detailed activity
            - Within the same compliance_level (Design/Implementation/Operating Effectiveness), activities must cover **different aspects** — never repeat the same control type
            - Example of WRONG (duplicate): "Maintain access control policy" + "Document access control policy" → these are the same
            - Example of RIGHT (unique): "Develop access control policy framework" + "Conduct quarterly access review" + "Generate monthly access violation reports"
        
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
            - Ensure each activity has a unique numerical ID within this clause
            - Maintain sequential ordering throughout all activities
            - Total number of activities should be between 4 and 8 — enough for comprehensive coverage but not redundant    
        9.  **Adhere to the Schema**: Your response **must** be a single JSON object that perfectly conforms to the `ComplianceRequirements` Pydantic model. Do not include any introductory or concluding text.

        ---
        <ADDITIONAL_USER_INSTRUCTION>
        {activity_prompt}
        <ADDITIONAL_USER_INSTRUCTION>

        ### Input Data
        **Regulatory Clause:** {clause_text}
        **Available Departments (with IDs):** {department_list}
    """


    

# ─────────────────────────────────────────────────────────────
# V2 PIPELINE — 2-call activity extraction
# ─────────────────────────────────────────────────────────────

CALL1_SYSTEM = """You are a senior compliance analyst at a BFSI regulatory firm.
Your task is to analyse a regulatory clause and extract structured intelligence about its obligations.
Return ONLY valid JSON. No explanation. No markdown."""

CALL2_SYSTEM = """You are a senior process owner and compliance auditor at a bank.
Your task is to generate a precise, non-redundant list of compliance activities based on provided obligations.
Think like an experienced auditor — generate only what the clause actually mandates.
Return ONLY valid JSON. No explanation. No markdown."""


def call1_obligation_intelligence_prompt(clause_text: str) -> str:
    return f"""Analyse this regulatory clause and extract structured obligation intelligence.

CLAUSE:
{clause_text}

CLASSIFICATION RULES:
- subject: Who bears the primary obligation?
  * "listed_entity" = bank, NBFC, financial institution, listed company being regulated
  * "regulator" = RBI, SEBI, IRDAI, stock exchange, Board
  * "third_party" = LSP, vendor, auditor, rating agency
  * "mixed" = multiple subjects including listed_entity

- clause_type:
  * "core_obligation" = direct mandatory requirement on listed_entity
  * "exception_carve_out" = exemption or exception to a rule
  * "penalty_consequence" = fine, penalty, action for non-compliance
  * "definition_explanation" = defines a term or explains a concept
  * "mixed" = combination of above

- is_actionable: true ONLY if listed_entity must DO something specific
  * false for pure definitions, pure exceptions, pure regulator actions

- atomic_obligations: List ONLY obligations where listed_entity is the actor
  * Each obligation must be directly stated in the clause — no inference
  * action_verb: the primary verb (e.g. "maintain", "disclose", "appoint", "submit")
  * trigger: "one_time" | "event_based" | "periodic" | "ongoing"
  * period: specific period if mentioned (e.g. "quarterly", "within 30 days", "annually")
  * explicitly_requires_training: true ONLY if clause text explicitly mentions training/awareness
  * explicitly_requires_audit: true ONLY if clause text explicitly mentions audit/review/inspection

Return this exact JSON structure:
{{
  "subject": "listed_entity | regulator | third_party | mixed",
  "clause_type": "core_obligation | exception_carve_out | penalty_consequence | definition_explanation | mixed",
  "is_actionable": true,
  "stop_reason": null,
  "atomic_obligations": [
    {{
      "id": "OB-1",
      "what": "exact mandatory action the listed entity must take",
      "when": "one_time | event_based | periodic | ongoing",
      "period": "specific period or null",
      "explicitly_requires_training": false,
      "explicitly_requires_audit": false
    }}
  ]
}}

If is_actionable = false, set atomic_obligations = [] and stop_reason = brief explanation.
If clause_type = exception_carve_out, include maximum 1 obligation about managing the exception.
If clause_type = penalty_consequence, include maximum 1 obligation about tracking/paying the penalty.
If clause_type = definition_explanation, set is_actionable = false."""


def call2_activity_generation_prompt(clause_text: str, obligations: list, department_list: list) -> str:
    import json
    _obs = json.dumps(obligations, indent=2)
    _depts = json.dumps(department_list) if department_list else "[]"
    return f"""You are a senior process owner and compliance auditor at a bank.
Generate a precise, non-redundant list of compliance activities based ONLY on the obligations provided.

REGULATORY CLAUSE (for context only):
{clause_text}

ATOMIC OBLIGATIONS TO COVER:
{_obs}

AVAILABLE DEPARTMENTS:
{_depts}

STRICT RULES:
1. Generate activities ONLY for obligations listed above — do NOT invent new obligations
2. Each activity must map to a specific obligation via maps_to_obligation field
3. Maximum 2 activities per obligation — if obligation is simple, 1 is enough
4. DO NOT add training activities unless explicitly_requires_training = true in the obligation
5. DO NOT add internal audit activities unless explicitly_requires_audit = true in the obligation
6. DO NOT apply a fixed Design→Implementation→Operating template — only generate what the obligation requires
7. Merge activities if two obligations would result in the same activity
8. Total activities: minimum 1, no maximum — generate as many as the obligations require, but never more

COMPLIANCE LEVEL DECISION RULES (apply strictly):
- Design: Creating a NEW policy/framework/charter/template that does not yet exist → frequency MUST be One-time
- Implementation: Setting up a process/system/workflow/appointment for the first time → can be one-time or per-event
- Operating Effectiveness: Ongoing execution/monitoring/verification/reporting of something already set up → recurring frequency

NEVER assign:
- Design to a recurring/monitoring activity
- Implementation to a "monitor" or "verify ongoing" activity  
- One-time frequency to a monitoring/ongoing activity

UNIQUENESS CHECK (before finalizing):
- Review all activities — if two cover the same action, merge into one
- Each activity must be distinctly and independently testable
- Different wording of the same action = duplicate → merge it

Return this exact JSON structure:
{{
  "activities": [
    {{
      "activity_id": "1",
      "activity_description": "Clear, actionable description starting with action verb",
      "compliance_level": "Design | Implementation | Operating Effectiveness",
      "relevant_departments": "Department name",
      "department_id": 0,
      "process_name": "Process name",
      "sub_process_name": "Sub-process name",
      "responsible_party": "Role or team",
      "frequency": "One-time | Quarterly | Annually | Monthly | As needed | Ongoing | Per event",
      "evidence_required": "Specific document or artifact",
      "maps_to_obligation": "OB-1",
      "justification": "Which part of clause mandates this"
    }}
  ]
}}"""


def validate_and_fix_activities(activities: list) -> list:
    """Python-level Step E1 — compliance level + frequency consistency check + renumbering."""
    MONITOR_VERBS = ["monitor", "verify", "track", "review ongoing", "ensure ongoing", "report periodically"]
    ONE_TIME_FREQS = ["one-time", "one time", "onetime"]
    RECURRING_FREQS = ["quarterly", "monthly", "annually", "annual", "daily", "weekly", "ongoing", "continuous", "every", "periodic", "bi-annual", "semi-annual", "three years", "two years"]

    fixed = []
    for act in activities:
        desc = (act.get("activity_description") or "").lower()
        level = (act.get("compliance_level") or "").strip()
        freq = (act.get("frequency") or "").lower().strip()

        # Fix 1: Design + recurring frequency → change to Operating Effectiveness
        if level == "Design" and any(f in freq for f in RECURRING_FREQS):
            act["compliance_level"] = "Operating Effectiveness"

        # Fix 2: Monitor verb + Design or Implementation → Operating Effectiveness
        if any(v in desc for v in MONITOR_VERBS) and level in ("Design", "Implementation"):
            act["compliance_level"] = "Operating Effectiveness"
            if any(f in freq for f in ONE_TIME_FREQS):
                act["frequency"] = "Ongoing"

        # Fix 3: Design + One-time only (correct — no change needed)
        fixed.append(act)

    # Renumber sequentially
    for idx, act in enumerate(fixed, start=1):
        act["activity_id"] = str(idx)

    return fixed


# ─────────────────────────────────────────────────────────────
# Call 3: Reasonable Assurance Validation (Build Sequence #367)
# Separate, dedicated check -- NOT bundled into Call 2's own prompt.
# An LLM critiquing its own just-generated output in the same breath
# tends to be a weaker critic than one given real distance (same
# reasoning as the evidence-consolidation redesign, #361).
# ────────────────────────────────────────────────────────────
CALL3_SYSTEM = """You are a senior BFSI regulatory auditor performing quality review of generated compliance activities.
Your task is to assess whether a set of compliance activities genuinely provides reasonable assurance for a specific regulatory clause.
Return ONLY valid JSON. No explanation. No markdown."""


def reasonable_assurance_prompt(clause_text: str, activities: list) -> str:
    activities_text = "\n".join(
        f"{i+1}. {act.get('activity_description', '')}" for i, act in enumerate(activities)
    )
    return f"""Assess whether this set of compliance activities provides REASONABLE ASSURANCE for the regulatory clause below.

CLAUSE TEXT:
{clause_text}

GENERATED ACTIVITIES:
{activities_text}

Evaluate against ALL of these dimensions:
1. GROUNDING: Is each activity genuinely derived from what THIS SPECIFIC clause requires -- not a generic topic-area activity that happens to relate to the same subject but isn't actually mandated by this clause's own text?
2. RISK MITIGATION: Do the activities, collectively, help mitigate the actual risk the regulator intends to address through this clause?
3. OBJECTIVE ACHIEVEMENT: If all activities were fully implemented, would the clause's real regulatory objective actually be met?
4. NO DUPLICATION: Are any two activities substantially the same requirement worded differently (e.g. "Develop an Access Management Policy" and "Develop an Access Control Policy" for the same underlying requirement)?

Be a genuinely critical reviewer, not a rubber stamp -- your job is to catch real gaps and over-generation, not to approve by default.

Return ONLY valid JSON with this exact structure:
{{
    "passes": true or false,
    "feedback": "If passes is false, specific, actionable feedback on exactly what is wrong and what should change. If passes is true, empty string."
}}
"""
