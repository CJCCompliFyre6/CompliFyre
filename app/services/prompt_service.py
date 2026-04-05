import json


class PromptsText:
    prompt_1 = f"""
            You are an expert in regulatory compliance, IT governance, and financial institution risk management. 
            Please analyze the selected regulatory circular or guideline and provide a detailed breakdown in the following structured JSON format:

            {{
                "DocumentDetails": {{
                    "DocumentName": "<Full name of the document>",
                    "IssuingAuthority": "<Regulator name and country>",
                    "ApplicableIndustries": "<Industries it applies to (e.g., Banking, NBFCs, fintechs, corporates, government entities)>",
                    "ApplicableOrganizations": "<Categories of organizations it applies to (e.g., banks, NBFCs, fintechs, corporates, government entities)>",
                    "ApplicableGeography": "<National or international applicability (only return the name of the country or region)>",
                    "PurposeAndIntent": "<Purpose and intent of the guideline>",
                    "IssuanceDate": "<Date of issuance>",
                    "ComplianceDeadline": "<Effective compliance deadline>"
                }},
                "RegulatoryAndComplianceAspects": {{
                    "LegalStatus": "<Legally binding or best practice recommendation>",
                    "NonComplianceConsequences": "<Penalties, enforcement actions, reputational risks>",
                    "RelationToPreviousRegulations": "<Whether it replaces, updates, or supplements any previous regulations>"
                }},
                "StakeholdersAndApplicability": {{
                    "ScopeOfApplicability": "<Financial institutions, tech firms, government agencies, etc.>",
                    "ImpactOnThirdParties": "<Impact on third-party service providers, outsourcing firms, and other stakeholders>"
                }},
                "ImplementationAndOversight": {{
                    "ComplianceRequirements": "<Reporting, self-assessments, audits>",
                    "ImplementationTimeline": "<Phased implementation timeline, if applicable>",
                    "GuidanceAvailability": "<Templates, FAQs, or official guidance for implementation>",
                    "OverseeingBody": "<Designated regulatory body or department overseeing compliance>",
                    "ResponsibleOfficerRequirement": "<Whether organizations must appoint a responsible officer (e.g., CISO, Compliance Head)>"
                }},
                "RelatedRegulations": {{
                    "OverlappingRegulations": "<Other regulations issued by the same regulator>",
                    "RelatedNationalRegulations": "<Related regulations from other national regulators>",
                    "ComparableInternationalStandards": "<Basel, ISO 27001, NIST, GDPR, FATF, COSO, etc.>"
                }},
                "ComparisonAndIndustryImpact": {{
                    "AlignmentWithGlobalPractices": "<How this guideline aligns with global best practices>",
                    "JurisdictionalDifferences": "<Differences from similar regulations in other jurisdictions (e.g., US, EU, UK, Singapore)>",
                    "ComplianceChallenges": "<Potential compliance challenges for affected organizations>",
                    "ImpactOnBusinessOperations": "<Expected impact on business operations, risk management, and governance practices>"
                }}
            }}

            Document:
            """
    prompt_2 = f"""
            You are an expert in regulatory compliance, IT governance, and financial institution risk management. 
            Extract every distinct regulatory requirement, mandate, or instruction that regulated entities (REs) must follow from the <document name>. Each requirement should be a clear directive and should exclude general explanations, definitions, or background information.

            Format the output as structured JSON with the following structure:

            {{
              "requirements": [
                {{
                  "clause_number": "<Clause Number (if available, otherwise generate sequential numbering)>",
                  "clause_text": "<The exact requirement or instruction>"
                }}
              ]
            }}

            Only include statements that impose a specific action, restriction, or compliance obligation on REs. Do not include general discussions, introductions, or conceptual overviews.
            """
    prompt_3 = """
                        
                **Objective:**

                You are an expert in regulatory compliance, financial institution risk management, and IT Governance, Risk, and Compliance (ITGRC). You will analyze a specific clause from a regulatory circular and provide actionable compliance steps.

                **Task:**

                1.  **Department Identification:**
                    * From the provided list of departments relevant to a financial institution, identify the most pertinent department(s) directly impacted by the given clause.

                2.  **Process and Sub-Process Mapping:**
                    * Map the clause to a specific existing process within the identified department(s).
                    * Further, pinpoint the precise sub-process within that process that requires attention.

                3.  **Detailed Compliance Activities:**
                    * Generate a comprehensive list of specific, actionable compliance activities that must be executed within the selected sub-process to ensure strict adherence to the clause.
                    * These activities must be directly relevant to financial institutions (banks, NBFCs, etc.) and should be practical and implementable.

                **Constraints:**

                * Avoid generic responses.
                * Provide precise, institution-specific actions.
                * Ensure regulatory accuracy in all mappings and activities.

                **Output Format:**

                **ITGRC Clause:**

                [Paste the clause from the regulatory circular here]

                **Mapped Department:**

                [List the relevant department(s)]

                **Mapped Process:**

                [Identify the overarching process]

                **Mapped Sub-Process:**

                [Specify the exact sub-process]

                **Compliance Activities:**

                1.  [Specific, actionable compliance activity 1]
                2.  [Specific, actionable compliance activity 2]
                3.  [Specific, actionable compliance activity 3]
                4.  [Specific, actionable compliance activity 4]
                    ... and so on.
            return above output in markdown format
            **Note:** Ensure that the output is structured and easy to read, with clear headings and bullet points where necessary.
            """

    def prompt_4(self, clause_text, department_list):
        return f"""
            You are an expert BFSI compliance and audit consultant. You specialize in regulatory frameworks from RBI, SEBI, IRDAI, and other bodies.

            **Objective:** Your task is to interpret a specific regulatory clause and generate a comprehensive, structured list of actionable compliance activities in JSON format. The goal is to produce practical steps that a financial institution can use for compliance.

            ---

            ### Task Breakdown

            1.  **Deconstruct the Clause:**
                * Carefully read and interpret the regulatory clause provided, analyzing its full intent, definitions, and any implicit requirements.
                * Identify the core compliance obligation(s) and classify them by function (e.g., governance, operational processes, IT systems, reporting, monitoring, documentation, training).

            2.  **Generate Actionable Activities:**
                * For each identified obligation, create a list of high-level activities (e.g., Policy & Governance, Operational Implementation, Monitoring & Reporting).
                * Under each high-level activity, define specific, measurable **sub-activities**. These sub-activities must be clear, actionable, and auditable.
                * Ensure the activities cover the entire compliance lifecycle: **Preparation**, **Implementation**, **Monitoring**, and **Evidence Maintenance**.
            
            3.  **Assign Compliance Levels:**
                * For each activity, assign the appropriate compliance level:
                **"Design"**: Activities related to policy creation, control design, framework development
                **"Implementation"**: Activities related to deployment, configuration, training, rollout  
                **"Operating Effectiveness"**: Activities related to monitoring, testing, reporting, ongoing maintenance
            ---

            ### Input

            **Regulatory Clause:** {clause_text}

            **Available Organization Data:**
            * **Departments:** {department_list}
            * **Processes & Sub-processes:** (You may infer these from standard financial institution operations, such as 'KYC,' 'Loan Origination,' 'Transaction Monitoring,' etc.)

            ---

            ### Output Format

            Provide your response as a single, valid JSON array of objects. Do not include any text before or after the JSON.

            ```json
            {{
                "compliance_activities": [
                    {{
                        "clause": "{clause_text}",
                        "department_id": "<select the best-fit department from the provided list>",
                        "relevant_departments": "<list of names of all departments involved>",
                        "process_name": "<the main business process>",
                        "sub_process_name": "<the specific sub-process>",
                        "activity_id": "<A unique numerical identifier starting from 1 in ascending order>",
                        "activity_description": "<A detailed, actionable, and auditable description of the activity.>",
                        "responsible_party": "<The specific department or role responsible>",
                        "frequency": "<The required frequency (e.g., One-time, Daily, Monthly, Annually, Event-driven)>",
                        "evidence_required": "<Specific documentation or proof needed for audit (e.g., Board Resolution, Audit Trail Report, Training Attendance Log)>"
                        "compliance_level": "<Must be one of: 'Design', 'Implementation', or 'Operating Effectiveness'>"
                    }}
                ]
            }}
            ```
            
            **Important:**
            * **Be Specific:** All `<...>` placeholders must be replaced with precise and relevant information. Avoid generic terms.
            * **Department Mapping:** Select the most appropriate `department_id` and list all `relevant_departments` from the `department_list` provided. If no department is a perfect match, infer a standard financial institution department (e.g., 'Risk Management').
            * **Process Mapping:** Infer realistic `process_name` and `sub_process_name` that align with the clause's requirements and standard banking operations.
            * **Actionable Content:** The `activity_description` must be a direct instruction that an employee can follow.
            * **Single JSON Object:** Your final output must be a single, complete JSON object.
            * **Activity ID:** Must be numerical values starting from 1 and incrementing by 1 for each subsequent activity (e.g., 1, 2, 3, 4, etc.).
            * **Compliance Level:** Assign the appropriate compliance level based on the activity type.

            **Activity ID Rules:**
            - Start with 1 for the first activity
            - Increment by 1 for each subsequent activity (2, 3, 4, etc.)
            - Use only numerical values (no letters or special characters)
            - Ensure sequential ordering
        """

    def prompt_5(self, clause_text, activity):
        return f"""
           You are an expert in regulatory compliance, IT governance, and financial institution risk management.

            You are given a clause and activity information from the <document name> circular:

            {clause_text},
            {activity}

            Your task is to analyze the clause and return the findings in a structured JSON format.

            The JSON output should adhere to the following schema:
            
            
            {{
                "activity_code": "<activity_code>",
                "activity": "<exact_clause_activity_wording>",
                "how_to_perform": {{
                    "execution_steps": ["Step 1: ...", "Step 2: ..."],
                    "responsible_roles": ["Role 1", "Role 2"],
                    "timelines": ["Date/Period", "Date/Period"]
                }},
                "test_procedures": {{
                    "objective": "<brief statement of what the testing aims to verify (e.g., control effectiveness, compliance adherence)>",
                    "test_type": ["Inspection", "Observation", "Inquiry", "Reperformance", "Recalculation", "Analytical Procedures"],
                    "execution_steps": ["Step 1: ...", "Step 2: ..."],
                    "responsible_roles": ["Auditor", "Control Owner", "Compliance Officer"],
                    "timelines": ["Frequency or audit period (e.g., Quarterly, Monthly)"]
                }},
                "evidences_artifacts": {{
                    "documents": ["Document 1", "Document 2"],
                    "logs": ["Log 1", "Log 2"],
                    "approvals": ["Approval 1", "Approval 2"],
                    "dashboards": ["Dashboard 1", "Dashboard 2"]
                }},
                "redundancy_check": "<redundancy_check_or_linked_clauses>",
                "risk_level": "<Low/Medium/High>",
                "mitigation_actions": "<mitigation_actions>",
                "relevant_departments": {{
                    "key_owner": "<department_a>",
                    "supporting_teams": ["<department_b>", "<department_c>"]
                }},
                "impacted_processes_sub_processes": [
                    {{"process": "<process_x>", "sub_process": "<sub_process_y>"}},
                    {{"process": "<process_a>", "sub_process": "<sub_process_b>"}}
                ],
                "clause_intent_analysis": {{
                    "intent": "<intent>",
                    "regulatory_expectations": "<regulatory_expectations>",
                    "risk_areas": "<risk_areas>",
                    "operational_impact": "<operational_impact>",
                    "core_purpose": "<core_purpose>"
                }},
                "frequency": "<frequency>"
            }}

            Please provide the output in valid JSON format.
    """

    def prompt_6(self, control_clauses, control_activity):
        return f"""
        You are an expert in regulatory compliance, internal controls, and audit procedures.

        You are given a control clause and control activity from the regulatory compliance framework:
        Design a step by step procedure to perform such an audit. It must include the below as appropriate. Make sure to consolidate the test steps that concern a single piece of evidence so that the evidence list contains unique items only (avoid redundancy in asking for evidences)

        {control_clauses},

        {control_activity}

        Your task is to generate a control testing workpaper in valid JSON format based on the control activity provided.

        The JSON output should follow this schema:

        {{
            "activity_code": "<activity_code>",
            "activity_name": "<exact_clause_activity_wording>",
            "activity_description": "<Purpose and scope of the control>",
            "objective": "<Intended outcome or goal of the control>",
            "owner": "<Person or role responsible for the control>",
            "control_type": "<Preventive | Detective | Corrective>",
            "frequency": "<Daily | Weekly | Monthly | Quarterly | Annually | As Needed | One Time>",
            "test_procedure": {{
                "review_of_documentation": ["Document 1", "Document 2"],
                "interviews": {{
                    "roles": < list of roles to be interviewed>,
                    "key_questions": < list of questions the auditor can ask the auditee to assess the control's design and effectiveness>
                }},
                "Walkthrough": "<Procedural step in an audit where the auditor traces a single transaction or process from its beginning to its completion>",
                "sampling": "<Explain sampling method and criteria used.>"
            }},
            "evidences_artifacts_needed": <based on test procedure categorize evidences in the categories such as list[
                "Policies and procedures",
                "Training records",
                "System logs",
                "Audit reports",
                "Meeting minutes", etc depending on the clause under evaluation
            ]>,
            "sampling_guidance": "<Instructions on sample size and selection criteria.>",
            "auditor_observation": "<Auditor's real-time observations during testing.>",
            "findings": "<Description of gaps or deficiencies identified during control testing.>",
            "impact": "<Assessment of risk or consequence to the organization if findings are not addressed.>",
            "severity": "<Low | Medium | High | Critical>",
            "recommendations": "<Actionable remediation or improvement suggestions.>",
            "reviewer_notes": "<Additional reviewer comments or observations.>"
        }}

        Please ensure the JSON output is accurate, specific, and complete.
        """


def prompt_get_answer(id, question, content):
    prompt = f"""
            You are an expert in regulatory compliance, IT governance, and financial institution risk management. 
            You will be provided a content and a json object with question id, question and answer with empty string. Your task is to extract answer for a question from the content
            and return a json object with answer.
            **Highlight the exact wording of the evidence provided along with the page number**.
            **If evidence provided is not sufficient or incorrect highlight this in answer**. 

            <input>
            **CONTENT** : {content}

            **input_json** : {{
            'id' : {id},
            'question' : '{question}'
            'answer' : ''

            }}

            return the output in below format
            ```json
            {{
            'id' : {id},
            'question' : '{question}'
            'answer' : '<answer of question extracted from content>
            }}
            ```
            """
    return prompt


def prompt_get_evidence_answer(id, item_description, clause_description, content):
    """
    Generates a prompt for an AI to extract regulatory compliance findings.

    Args:
        id (str or int): The unique identifier for the evidence item.
        item_description (str): The description of the item being reviewed.
        clause_description (str): The specific clause or regulation to check against.
        content (str): The document content to be analyzed.

    Returns:
        str: A formatted prompt for the AI model.
    """

    # Create the input JSON object as a Python dictionary first
    input_data = {
        "clause_description": clause_description,
        "id": id,
        "item_description": item_description,
        "answer": "",
    }

    # Use json.dumps to handle proper escaping and formatting for the JSON string
    input_json_str = json.dumps(input_data, indent=4)

    # Create the desired output JSON object as a Python dictionary
    output_data = {
        "clause_description": clause_description,
        "id": id,
        "item_description": item_description,
        "answer": "<answer of question extracted from content>",
    }

    # Use json.dumps for the output format string
    output_json_str = json.dumps(output_data, indent=4)

    prompt = f"""
        You are an expert in regulatory compliance, IT governance, and financial institution risk management. 
        
        Your task is to analyze the provided **CONTENT** and extract findings and issues based on the **clause_description** and **item_description**. 
        **Highlight the exact wording of the evidence provided along with the page number**.
        **If evidence provided is not sufficient or incorrect highlight this in answer**. 
        You must return a single JSON object with the extracted answer.


        <input>
        **CONTENT**:
        {content}

        **input_json**:
        {input_json_str}

        return the output in the exact format below, replacing the placeholder for the 'answer' key.
        ```json
        {output_json_str}
        ```
        """
    return prompt.strip()


def prompt_get_evidence_answer_activity(id, item_description, activity, content):
    prompt = f"""
            You are an expert in regulatory compliance, IT governance, and financial institution risk management. 
            You will be provided a content and a json object with evidence id, item description, activity description and answer with empty string. Your task is to extract findings for a item description from the content
            and return a json object with answer.

            <input>
            **CONTENT** : {content}

            **input_json** : {{
            'id' : {id},
            'item_description' : '{item_description}',
            'activity_description : '{activity}',
            'answer' : ''

            }}

            return the output in below format
            ```json
            {{
            'id' : {id},
            'item_description' : '{item_description}'
            'answer' : '<Findings about the evidence provided as content>
            }}
            ```
            """
    return prompt


def evidences_consolidate(item: list, chunk_number: int):
    prompt = f"""
You are an expert in regulatory compliance evidence consolidation. Analyze the compliance activities and group similar evidence requirements.

INPUT DATA (Chunk {chunk_number}):
{json.dumps(item, indent=2)}

INSTRUCTIONS:
1. Analyze ALL evidence items in this chunk
2. Group similar evidence requirements by their purpose and type
3. Include EVERY clause from the input data in the output
4. For clauses without actual evidence, still include them but mark appropriately
5. Return ONLY valid JSON format

CRITICAL: You MUST return valid JSON with this exact structure. No other text.

REQUIRED JSON STRUCTURE:
{{
    "grouped_evidences": [
        {{
            "evidence_item_name": "Descriptive name for this evidence group",
            "required_by": {{
                "guideline_ids": ["list", "of", "guideline", "ids"],
                "clause_nos": ["list", "of", "clause", "numbers"],
                "activity_ids": ["list", "of", "activity", "ids"],
                "evidence": [
                    {{
                        "evidence_id": "actual_evidence_id_or_null",
                        "evidence_item": "description of evidence"
                    }}
                ]
            }}
        }}
    ]
}}

EXAMPLES OF EVIDENCE ITEM NAMES:
- "Access Control Policy Documentation"
- "User Access Review Reports" 
- "System Configuration Documentation"
- "Security Training Records"
- "Incident Response Procedures"

Remember: Return ONLY the JSON object. No explanations, no code blocks, just pure JSON.
"""
    return prompt


def create_consolidation_prompt(activities_data, clause_no):
    """
    Create prompt for LLM to generate consolidated bullet points.
    """
    prompt = f"""
IMPORTANT: You MUST return ONLY valid JSON format. Do not include any explanatory text before or after the JSON.

You are an expert compliance auditor. Analyze the following activities for clause {clause_no} and create concise, one-line bullet point summaries for observations, findings, and recommendations.

CRITICAL REQUIREMENTS:
- Create exactly ONE bullet point per activity for each section (findings, recommendations)
- Each bullet point should be a concise one-line summary (max 15-20 words)
- Maintain the order of activities as provided
- Focus on the key insight for each activity
- Use clear, professional audit language
- Return ONLY valid JSON, no other text

Activities Data:
{json.dumps(activities_data, indent=2)}

Required JSON Output Format:
{{
    "findings": [
        {{
            "activity_code": "ACT001", 
            "activity_name": "Activity Name 1",
            "bullet_point": "Concise one-line finding summary for this activity"
        }}
    ],
    "recommendations": [
        {{
            "activity_code": "ACT001",
            "activity_name": "Activity Name 1", 
            "bullet_point": "Concise one-line recommendation summary for this activity"
        }}
    ]
}}

Remember: 
- Create exactly {len(activities_data)} bullet points for each section (one per activity)
- Keep each bullet point focused and concise
- Return ONLY the JSON object, no other text.
- DO NOT include observations section
"""
    return prompt


def create_observation_summary_prompt(activities_data, clause_no):
    """
    Create prompt for LLM to generate a consolidated observation summary.
    """
    prompt = f"""
You are an expert compliance auditor. Analyze the following activities for clause {clause_no} and create a comprehensive, well-structured observation summary.

CRITICAL REQUIREMENTS:
- Create a SINGLE, cohesive observation summary that covers all activities
- The summary should be 2-4 paragraphs long
- Focus on overall patterns, key issues, and general observations
- Use professional audit language
- Do not list activities individually - synthesize the information
- Highlight common themes and significant findings across all activities
- Keep it concise but comprehensive
- Return ONLY the JSON object, no other text.

Activities Data:
{json.dumps(activities_data, indent=2)}

Provide only the observation summary text itself, without any additional explanations, headings, or markdown formatting. Write in continuous paragraphs.
"""
    return prompt
