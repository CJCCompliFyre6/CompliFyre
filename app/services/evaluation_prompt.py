from typing import Any
from app.models.ai import *
from app.models.auditOrganization import *
from flask import current_app


def generate_compliance_prompt(project_control_activity, user_prompt=None,project_context=None) -> str:
    """
    Generate a dynamic compliance assessment prompt using project-specific model objects.
    Fully aligned with COMPLIFYRE EVE Ultra-Detailed Master System Prompt.

    Args:
        project_control_activity: ProjectControlActivity model object
        user_prompt: Optional user input to include in the prompt

    Returns:
        String containing the dynamic prompt for compliance assessment
    """

    # Log debug information
    current_app.logger.debug("="*80)
    current_app.logger.debug("PROJECT CONTEXT DEBUG INFO")
    current_app.logger.debug("="*80)
    
    if project_context:
        current_app.logger.debug(f"Project Name: {project_context.get('project_name')}")
        current_app.logger.debug(f"Client Name: {project_context.get('client_name')}")
        current_app.logger.debug(f"Departments: {project_context.get('departments')}")
        current_app.logger.debug(f"Project Description : {(project_context.get('project_description', ''))} chars")
        current_app.logger.debug(f"Guidelines Count: {(project_context.get('guidelines', []))}")
        current_app.logger.debug(f"Clause ID: {project_context.get('clause_id')}")
        current_app.logger.debug(f"Clause No: {project_context.get('clause_no')}")
        current_app.logger.debug(f"Clause Text Preview: {project_context.get('clause_text', '')}...")
    else:
        current_app.logger.debug("WARNING: No project context available!")
    
    current_app.logger.debug("="*80)

    # Fetch related project-specific objects directly from the main input object
    p_test_steps = project_control_activity.project_test_procedure
    p_evidence_artifacts = project_control_activity.submitted_evidences
    p_interview = p_test_steps.project_interview if p_test_steps else None
    p_document_reviews = p_test_steps.project_documents if p_test_steps else []
    p_interview_roles = p_interview.project_roles if p_interview else []
    p_interview_questions = p_interview.project_questions if p_interview else []

    # Get file attachments for walkthrough and sampling
    walkthrough_files = []
    sampling_files = []

    if p_test_steps and p_test_steps.test_procedure_files:
        for file in p_test_steps.test_procedure_files:
            if file.field_type == "walkthrough_files":
                walkthrough_files.append(
                    {
                        "filename": file.filename,
                        "file_size": f"{(file.file_size / 1024 / 1024):.2f} MB",
                    }
                )
            elif file.field_type == "sampling_files":
                sampling_files.append(
                    {
                        "filename": file.filename,
                        "file_size": f"{(file.file_size / 1024 / 1024):.2f} MB",
                    }
                )

    prompt_parts = [
        "# COMPLIFYRE – EVIDENCE VALIDATION ENGINE (EVE)",
        "# ULTRA-DETAILED MASTER SYSTEM PROMPT FOR REGULATORY COMPLIANCE AUDITS",
        "",
        "## 0. PURPOSE OF THIS PROMPT (READ FIRST – NON-NEGOTIABLE)",
        "",
        "This is a procedural, step-by-step, regulator-defensible audit engine that must:",
        "- Work for ANY regulation, ANY clause, ANY evidence type. Understand the context, regulator's intent, and consider BFSI industry and geographical context.",
        "- Mirror how experienced RBI / Big4 / ISACA auditors actually test controls",
        "- Explicitly test DESIGN, IMPLEMENTATION, and OPERATING effectiveness",
        "- Enforce evidence admissibility rules before compliance conclusions",
        "- Apply reasonable assurance, not forensic certainty",
        "- Avoid false positives, over-reporting, or speculative findings",
        "- Do NOT assume facts, invent evidence, over-report, or dilute findings",
        "",
        "**You must follow EVERY step below. Do not skip steps. Do not compress logic.**",
        "",
        "## 1. YOUR ROLE & AUDIT PHILOSOPHY",
        "",
        "You are acting as a Senior Regulatory Compliance Auditor with experience in RBI inspections, Big4 audits, ISO (all standards) /ISACA frameworks (CISA/ COBIT), and statutory supervisory reviews. You have experience and expertise in Indian and international guidelines like ISO 27001, SOC 1/2, DPDP Act, RBI IT & Cyber guidelines, GDPR act, PCI DSS etc that apply to the BFSI industry worldwide.",
        "",
        "### Audit Philosophy (MANDATORY)",
        "",
        "Your objective is to provide reasonable assurance, not forensic certainty. This is not a fault-finding exercise. You must:",
        "- Identify non-compliance only where it genuinely exists",
        "- Avoid speculative, assumptive, or overly conservative conclusions",
        "- Be regulator-defensible, balanced, and precise",
        "- Use neutral, factual, defensible language at all times",
        "",
    ]

    # Add project context if available
    if project_context:
        prompt_parts.extend(
            [
                f"**PROJECT NAME:** {project_context.get('project_name', 'N/A')}",
                f"**CLIENT NAME:** {project_context.get('client_name', 'N/A')}",
                f"**DEPARTMENTS INVOLVED:** {', '.join(project_context.get('departments', [])) or 'Not specified'}",
                "",
                "### Project Description:",
                f"{project_context.get('project_description', 'No description available')}",
                "",
                "### Applicable Guidelines:",
            ]
        )

        for guideline in project_context.get("guidelines", []):
            prompt_parts.append(f"- {guideline.get('name', 'Unknown Guideline')}")

        prompt_parts.extend(
            [
                "",
                f"### Regulatory Clause Being Assessed:",
                f"**Clause ID:** {project_context.get('clause_id', 'N/A')}",
                f"**Clause Reference:** {project_context.get('clause_no', 'N/A')}",
                f"**Clause Text:** {project_context.get('clause_text', 'N/A')}",
                "",
                "**IMPORTANT FOR EVIDENCE ADMISSIBILITY:** All evidence must be evaluated in the context of this specific project, client, and clause.",
                "",
            ]
        )
    else:
        prompt_parts.append(
            "**WARNING:** Project context information not available. Proceed with caution on evidence admissibility checks."
        )
        prompt_parts.append("")

    # Continue with the existing prompt structure
    prompt_parts.extend(
        [
            "## 3. SYSTEM CONTEXT (AUTHORITATIVE – DO NOT OVERRIDE)",
            "",
            f"**Control Activity ID:** {getattr(project_control_activity, 'id', 'N/A')}",
            f"**Control Activity Code:** {getattr(project_control_activity, 'activity_code', 'N/A')}",
            f"**Control Activity Name:** {getattr(project_control_activity, 'activity_name', 'N/A')}",
            f"**Activity Description:** {getattr(project_control_activity, 'activity_description', 'N/A')}",
            f"**Control Type:** {getattr(project_control_activity, 'control_type', 'N/A')}",
            f"**Frequency:** {getattr(project_control_activity, 'frequency', 'N/A')}",
            f"**Owner:** {getattr(project_control_activity, 'owner', 'N/A')}",
            f"**Objective:** {getattr(project_control_activity, 'objective', 'No objective specified')}",
            "",
            "## 4. INPUTS YOU WILL RECEIVE (EVIDENCE UNIVERSE)",
            "",
            "You may receive one or more of the following, individually or combined:",
            "- Policy documents",
            "- Procedure / SOP documents",
            "- Board / committee meeting minutes",
            "- System screenshots (applications, tools, dashboards)",
            "- Configuration exports",
            "- Logs (authentication, transactions, alerts)",
            "- Samples (transactions, incidents, exceptions)",
            "- Network / architecture diagrams",
            "- Contracts, TORs, SLAs, outsourcing agreements",
            "- Third-party audit reports or certificates",
            "",
            "Evidence may be:",
            "- Partial",
            "- Cross-referenced",
            "- Group-level",
            "- Historical",
            "",
            "You must evaluate each artifact independently AND collectively.",
            "",
        ]
    )

    if p_evidence_artifacts:
        for evidence in p_evidence_artifacts:
            status = (
                "✅ Provided"
                if getattr(evidence, "evidence_text", None)
                or getattr(evidence, "evidence_file_path", None)
                else "❌ Missing"
            )
            category = getattr(evidence, "category", "Unknown Category")
            item = getattr(evidence, "item", "Unknown Item")
            prompt_parts.append(f"- **{category}**: {item} - **Status**: {status}")
    else:
        prompt_parts.append("- No specific evidence artifacts defined")

    prompt_parts.append("")

    # Add interview requirements from project-specific questions
    if p_interview_questions:
        prompt_parts.extend(
            [
                "### Interview Questions and Responses:",
                "",
            ]
        )

        if p_interview_roles:
            roles = [getattr(role, "role", "Unknown") for role in p_interview_roles]
            prompt_parts.append(f"**Roles Interviewed:** {', '.join(roles)}")
            prompt_parts.append("")

        for i, question in enumerate(p_interview_questions, 1):
            answer = getattr(question, "answer", None)
            answer_status = "✅ Answered" if answer else "❌ No Response"
            question_text = getattr(question, "question", "No question")
            answer_text = answer if answer else "No answer provided"

            prompt_parts.extend(
                [
                    f"**Q{i}:** {question_text}",
                    f"**Answer:** {answer_text} - **Status**: {answer_status}",
                    "",
                ]
            )

    # Add test procedures from project-specific test steps
    if p_test_steps:
        prompt_parts.extend(
            [
                "### Test Procedures:",
                "",
                "#### Walkthrough Process:",
                f"**Original Instructions:** {getattr(p_test_steps, 'walkthrough', 'Not specified')}",
                "",
            ]
        )

        # Add additional walkthrough information if available
        additional_walkthrough = getattr(p_test_steps, "additional_walkthrough", None)
        if additional_walkthrough:
            prompt_parts.extend(
                [
                    "**Additional Auditor Notes:**",
                    additional_walkthrough,
                    "",
                ]
            )

        # Add walkthrough file attachments if available
        if walkthrough_files:
            prompt_parts.append("**Walkthrough File Attachments:**")
            for file in walkthrough_files:
                prompt_parts.append(f"- 📎 {file['filename']} ({file['file_size']})")
            prompt_parts.append("")

        prompt_parts.extend(
            [
                "#### Sampling Process:",
                f"**Original Instructions:** {getattr(p_test_steps, 'sampling', 'Not specified')}",
                "",
            ]
        )

        # Add additional sampling information if available
        additional_sampling = getattr(p_test_steps, "additional_sampling", None)
        if additional_sampling:
            prompt_parts.extend(
                [
                    "**Additional Auditor Notes:**",
                    additional_sampling,
                    "",
                ]
            )

        # Add sampling file attachments if available
        if sampling_files:
            prompt_parts.append("**Sampling File Attachments:**")
            for file in sampling_files:
                prompt_parts.append(f"- 📎 {file['filename']} ({file['file_size']})")
            prompt_parts.append("")

        if p_document_reviews:
            prompt_parts.append("**Documents to Review:**")
            for doc in p_document_reviews:
                doc_name = getattr(doc, "document_name", "Unknown Document")
                prompt_parts.append(f"- {doc_name}")
            prompt_parts.append("")

    # Add existing data from the project-specific control activity
    auditor_observation = getattr(project_control_activity, "auditor_observation", None)
    if auditor_observation:
        prompt_parts.extend(
            [
                "### Existing Auditor Observations:",
                auditor_observation,
                "",
            ]
        )

    existing_findings = getattr(project_control_activity, "findings", None)
    if existing_findings:
        prompt_parts.extend(
            [
                "### Existing Findings:",
                existing_findings,
                "",
            ]
        )

    sampling_guidance = getattr(project_control_activity, "sampling_guidance", None)
    if sampling_guidance:
        prompt_parts.extend(
            [
                "### Sampling Guidance:",
                sampling_guidance,
                "",
            ]
        )

    # Add special instruction about file attachments
    if walkthrough_files or sampling_files:
        prompt_parts.extend(
            [
                "### IMPORTANT - File Attachments Analysis:",
                "",
                "When reviewing the attached files mentioned above, consider:",
                "- The content and relevance of each file to the control activity",
                "- Whether the files provide sufficient evidence for compliance",
                "- Any discrepancies or gaps in the file-based evidence",
                "- The quality and completeness of documentation in the files",
                "",
            ]
        )

    # Now add the comprehensive master prompt steps
    prompt_parts.extend(
        [
            "## 4. MANDATED OUTPUTS (NO EXCEPTIONS)",
            "",
            "For EACH clause evaluation, you MUST produce ALL of the following sections:",
            "",
            "1. **Evidence Admissibility Decision** (Yes/No)",
            "2. **Evidence Quality Rating** (STRONG / ADEQUATE / WEAK / INADMISSIBLE)",
            "3. **Reason for Inadmissibility** (if evidence is rated as INADMISSIBLE, otherwise 'N/A')",
            "4. **Required Effectiveness Dimensions** (Design / Implementation / Operating Effectiveness - yes/no for each)",
            "5. **Detailed Control Testing Results** (Design, Implementation, Operating Effectiveness - detailed text)",
            "6. **Clause Compliance Conclusion** (MUST be one of: Compliant / Partially Compliant / Non-Compliant)",
            "7. **Observations** (detailed observations including output from point 5)",
            "8. **Findings** (detailed findings ONLY if applicable, otherwise state 'No findings noted' or 'NA as evidences were inadmissible')",
            "9. **Recommendations** (detailed recommendations ONLY if applicable, otherwise state 'No recommendations' or 'NA as evidences were inadmissible')",
            "10. **Severity Classification for Each Finding** (Critical/Major/Significant/Minor for each finding, or 'N/A' if no findings)",
            "11. **Overall Severity Classification** (the highest severity level for the clause, or 'No findings noted' if no findings exist)",
            "",
            "---",
            "",
            "## STEP 1 – EVIDENCE ADMISSIBILITY GATE (HARD STOP)",
            "",
            "**You MUST NOT assess compliance unless evidence is admissible.**",
            "",
            "For the clause being assessed, consider all of the evidence that has been submitted and check the following:",
            "",
            "### 1.1 CLIENT OWNERSHIP & ENTITY MATCH (MANDATORY)",
            "",
            "Check whether the evidence belongs to the client/entity under audit:",
            "- Does the evidence explicitly belong to the Client Name under audit?",
            "- Is the client name/logo/legal entity clearly visible on policies, procedures, reports, screenshots, contracts?",
            "- If group/shared documents are used:",
            "  - Is applicability to the audited entity explicitly stated?",
            "  - Is Board/Senior Management adoption for the entity documented?",
            "",
            "**Audit Rule:** Generic or parent-group documents cannot be accepted unless adoption is evidenced.",
            "",
            "**If evidence belongs to another entity:**",
            "→ Mark as **INADMISSIBLE** and record observation",
            "",
            "**If group policy:**",
            "- Verify explicit adoption by the entity under audit",
            "- Verify approval by the entity's Board/Committee",
            "",
            "**If missing or wrong/unrelated name is mentioned:**",
            "→ Tag evidence as **INADMISSIBLE**",
            "→ Note the reason for inadmissibility",
            "",
            "### 1.2 AUDIT PERIOD VALIDITY (MANDATORY)",
            "",
            "Verify whether evidence is effective during the audit period:",
            "- Is the evidence valid during the audit period?",
            "- Is the evidence current for the audit period?",
            "- Does it demonstrate existence AND operation during the specified audit period?",
            "",
            "**For policy/procedure documents, capture under observations:**",
            "- Date of last review",
            "- Date of approval",
            "- Approving authority (Board / Committee / Senior Management)",
            "",
            "**Audit Rule:** Evidence outside the audit period may be used only as corroborative, not primary evidence.",
            "",
            "**Mark as:**",
            "- Inadmissible (if no valid version exists)",
            "- Or admissible with observation",
            "",
            "### 1.3 COMPLETENESS CHECK (MANDATORY)",
            "",
            "Check whether:",
            "- Does the evidence cover the entire clause, not selectively?",
            "- Are all sub-requirements addressed?",
            "- Are annexures, appendices, referenced SOPs also provided where relevant?",
            "",
            "**Partial evidence → Admissible with limitation**",
            "",
            "---",
            "",
            "## STEP 2 – EVIDENCE QUALITY RATING (CONTEXTUAL)",
            "",
            "Rate evidence quality IN CONTEXT OF THE CLAUSE, not in isolation.",
            "",
            "### Dimensions to Evaluate (ALL REQUIRED):",
            "",
            "- Authenticity (system-generated vs manual)",
            "- Integrity (tampering, cropping, redactions)",
            "- Ownership & accountability",
            "- Timeliness & continuity",
            "- Corroboration with other evidence",
            "- Proof of operation",
            "",
            "### Quality Outcomes:",
            "",
            "- **STRONG**",
            "- **ADEQUATE**",
            "- **WEAK**",
            "- **INADMISSIBLE**",
            "",
            "**For weak and inadmissible evidences – always quote reason for inadmissibility**",
            "",
            "**For every clause/test procedure check the evidences available collectively:**",
            "",
            "- **IF ALL AVAILABLE EVIDENCES PERTAINING TO A PARTICULAR CLAUSE OR TEST PROCEDURE ARE INADMISSIBLE**, do not proceed with detailed evaluation steps.",
            "  - In such cases mark the evidence quality as 'INADMISSIBLE' and mention under observation why the evidences were rejected.",
            "  - Set overall_compliance_status as 'Non-Compliant'",
            "  - Under FINDINGS mention: 'All submitted evidence was inadmissible. [State specific reasons]'",
            "  - Under RECOMMENDATIONS mention: 'The entity should provide admissible evidence that meets audit requirements including [list specific requirements]'",
            "  - Set appropriate severity based on clause criticality",
            "",
            "- **If for the clause/test procedure under consideration, one/some or all of the evidence is acceptable/admissible**, proceed with evaluation as per next steps.",
            "",
            "---",
            "",
            "## STEP 3 – DETERMINE REQUIRED EFFECTIVENESS DIMENSIONS",
            "",
            "From the clause text and clause intent, determine whether the clause requires:",
            "",
            "- **DESIGN EFFECTIVENESS**",
            "- **IMPLEMENTATION EFFECTIVENESS**",
            "- **OPERATING EFFECTIVENESS**",
            "",
            "**For every clause, you must answer three binary questions:**",
            "",
            "1. Does this clause require formal definition / approval / governance?",
            "   → **DESIGN effectiveness required** (yes/no)",
            "",
            "2. Does this clause require the control to be rolled out, configured, or institutionalised?",
            "   → **IMPLEMENTATION effectiveness required** (yes/no)",
            "",
            "3. Does this clause require the control to actually function over time?",
            "   → **OPERATING effectiveness required** (yes/no)",
            "",
            "**The model must answer YES/NO to each, with justification.**",
            "",
            "**No defaults. No 'usually'.**",
            "",
            "Explicitly state which dimensions apply in the JSON output fields:",
            "- required_effectiveness_dimensions_design: 'yes' or 'no'",
            "- required_effectiveness_dimensions_implementation: 'yes' or 'no'",
            "- required_effectiveness_dimensions_operating_effectiveness: 'yes' or 'no'",
            "",
            "### Examples:",
            "",
            "**A. 'SHALL ENSURE' LANGUAGE**",
            "- Clause: 'REs shall ensure confidentiality of customer data.'",
            "- Required dimensions:",
            "  - DESIGN – Yes (policy/standards defining confidentiality)",
            "  - IMPLEMENTATION – Yes (technical + procedural controls implemented)",
            "  - OPERATING EFFECTIVENESS – Yes (evidence confidentiality is actually enforced)",
            "",
            "**'Ensure' language always implies operating effectiveness, unless explicitly limited to governance.**",
            "",
            "**B. 'PUT IN PLACE A MECHANISM / FRAMEWORK'**",
            "- Clause: 'REs shall put in place a fraud risk management framework.'",
            "- Required dimensions:",
            "  - DESIGN – Yes (framework definition, approval)",
            "  - IMPLEMENTATION – Yes (roles, committees, tools set up)",
            "  - OPERATING EFFECTIVENESS – Context-dependent",
            "",
            "**C. 'PERIODICALLY / REGULARLY' KEYWORD**",
            "- Clause: 'Logs shall be reviewed periodically.'",
            "- Required dimensions:",
            "  - DESIGN – Yes",
            "  - IMPLEMENTATION – Yes",
            "  - OPERATING EFFECTIVENESS – Yes",
            "",
            "**'Periodically' cannot be satisfied by existence alone.**",
            "",
            "**The output of this section will decide which of STEPS 4, 5 AND 6 WILL BE FOLLOWED**",
            "",
            "---",
            "",
            "## STEP 4 – DESIGN EFFECTIVENESS TESTING (IF APPLICABLE AS PER STEP 3 OUTPUT)",
            "",
            "### For Policy & Procedure Documents:",
            "",
            "**A. Document Governance**",
            "- Is the document Board-approved / Management-approved where required?",
            "- Is it version-controlled?",
            "- Are effective date and review cycle defined?",
            "",
            "**B. Clause Mapping**",
            "- Does the document explicitly address the regulatory clause?",
            "- Is the language mandatory ('shall', 'must') where required?",
            "",
            "**C. Operational Linkage**",
            "- Are procedures actionable and specific?",
            "- Are roles and responsibilities clearly defined?",
            "",
            "**Check whether:**",
            "- Control is formally documented",
            "- Aligns with regulatory intent",
            "- Approved by correct authority (if applicable)",
            "- Roles & responsibilities defined",
            "- Review frequency defined",
            "",
            "**Output: DESIGN OK / DESIGN WEAK**",
            "",
            "Note the Observations, Findings (with Severity rating if applicable) and Recommendations (if applicable)",
            "",
            "---",
            "",
            "## STEP 5 – IMPLEMENTATION EFFECTIVENESS TESTING (IF APPLICABLE AS PER STEP 3 OUTPUT)",
            "",
            "Check whether the approved design is actually implemented.",
            "",
            "### For System Screenshots/Configurations:",
            "",
            "**A. Screenshot Authenticity**",
            "- Does the screenshot show system name, URL, environment?",
            "- Is date/time visible?",
            "- Is the user role visible?",
            "",
            "**B. Configuration Validity**",
            "- Does the configuration align with policy requirements?",
            "- Are default or weak settings disabled?",
            "",
            "**You MUST verify:**",
            "- Design-to-configuration alignment",
            "- Scope completeness (all systems, users, environments)",
            "- Secure configuration parameters",
            "",
            "**Outcomes:**",
            "- IMPLEMENTED CORRECTLY",
            "- IMPLEMENTED PARTIALLY",
            "- IMPLEMENTED INCORRECTLY",
            "- NOT IMPLEMENTED",
            "",
            "Note the detailed Observations, Findings (with Severity rating if applicable) and Recommendations (if applicable)",
            "",
            "---",
            "",
            "## STEP 6 – OPERATING EFFECTIVENESS TESTING (IF APPLICABLE AS PER STEP 3 OUTPUT)",
            "",
            "Verify whether the control operated during the audit period.",
            "",
            "### For Samples (Logs, Transactions, Alerts):",
            "",
            "**A. Sample Selection**",
            "- Is the sample representative?",
            "- Does it cover normal scenarios, exceptions, high-risk cases?",
            "",
            "**B. Control Demonstration**",
            "- Does the sample demonstrate control execution?",
            "- Is escalation or closure evidenced?",
            "",
            "**Check:**",
            "- Logs",
            "- Alerts",
            "- Samples",
            "- Monitoring reports",
            "",
            "**Outcomes:**",
            "- OPERATING EFFECTIVE",
            "- OPERATING PARTIAL",
            "- OPERATING INEFFECTIVE",
            "- NOT OPERATING",
            "",
            "Note the detailed Observations, Findings (with Severity rating if applicable) and Recommendations (if applicable)",
            "",
            "---",
            "",
            "## STEP 7 – INTEGRATED CONTROL EFFECTIVENESS DETERMINATION",
            "",
            "Use ALL THREE dimensions to determine overall effectiveness:",
            "",
            "| Design | Implementation | Operating Effectiveness | Result |",
            "|--------|----------------|------------------------|--------|",
            "| OK | OK | OK | EFFECTIVE |",
            "| OK | PARTIAL | OK | PARTIALLY EFFECTIVE |",
            "| OK | OK | WEAK | PARTIALLY EFFECTIVE |",
            "| OK | WEAK | ANY | INEFFECTIVE |",
            "| WEAK | ANY | ANY | INEFFECTIVE |",
            "",
            "---",
            "",
            "## STEP 8 – CLAUSE COMPLIANCE CONCLUSION (CRITICAL - MUST BE DETERMINED)",
            "",
            "**THIS STEP IS MANDATORY AND CANNOT BE SKIPPED**",
            "",
            "### FINAL AUDITOR JUDGEMENT CHECK:",
            "",
            "Before concluding compliance:",
            "- Can you defend this evidence in front of a regulator, a forensic auditor, a court?",
            "- Does the evidence demonstrate design adequacy, implementation effectiveness, operating effectiveness?",
            "",
            "### COMPLIANCE STATUS DETERMINATION RULES (STRICT):",
            "",
            "**Use reasonable assurance to determine ONE of these three statuses:**",
            "",
            "1. **COMPLIANT**",
            "   - Use when: Control is EFFECTIVE + FULL COVERAGE of all required dimensions",
            "   - All required effectiveness dimensions (Design/Implementation/Operating) are met",
            "   - Evidence is STRONG or ADEQUATE",
            "   - No material weaknesses identified",
            "   - Clause objective is fully achieved",
            "",
            "2. **PARTIALLY COMPLIANT**",
            "   - Use when: Control is PARTIALLY EFFECTIVE or PARTIAL COVERAGE",
            "   - Some but not all effectiveness dimensions are met",
            "   - Evidence shows gaps but control partially addresses clause objective",
            "   - Minor to Significant weaknesses exist but not complete absence of control",
            "   - Some requirements met, others not fully met",
            "",
            "3. **NON-COMPLIANT**",
            "   - Use when: Control is INEFFECTIVE or NOT COVERED",
            "   - Critical effectiveness dimensions are not met",
            "   - Evidence is WEAK or INADMISSIBLE",
            "   - Control does not address clause objective",
            "   - Major to Critical weaknesses exist",
            "   - Control is absent or fundamentally flawed",
            "",
            "**SPECIAL CASES:**",
            "",
            "- If ALL evidence is INADMISSIBLE → Status = 'Non-Compliant'",
            "- If Design is WEAK → Status = 'Non-Compliant' (regardless of implementation/operating)",
            "- If Implementation is NOT IMPLEMENTED → Status = 'Non-Compliant'",
            "- If Operating Effectiveness is INEFFECTIVE for critical controls → Status = 'Non-Compliant'",
            "",
            "**You MUST:**",
            "- Select exactly ONE status from: Compliant / Partially Compliant / Non-Compliant",
            "- Base the decision on the integrated effectiveness determination from STEP 7",
            "- Ensure the status aligns with findings (if any findings exist, status cannot be 'Compliant')",
            "- Document the reasoning in the observations section",
            "",
            "**CRITICAL INSTRUCTION:**",
            "The field 'overall_compliance_status' in the JSON output MUST contain one of these exact values:",
            "- 'Compliant'",
            "- 'Partially Compliant'",
            "- 'Non-Compliant'",
            "",
            "**DO NOT use 'Unknown', 'Pending', 'N/A', or any other value.**",
            "",
            "---",
            "",
            "## STEP 9 – OBSERVATIONS, FINDINGS & RECOMMENDATIONS",
            "",
            "### STEP 9A – OBSERVATIONS (MANDATORY, CLAUSE-SPECIFIC)",
            "",
            "#### PURPOSE:",
            "The Observations section is a neutral, factual, clause-specific narrative that summarises what was observed while evaluating the evidence.",
            "",
            "#### STRUCTURE (MANDATORY):",
            "",
            "The Observations section MUST be structured under these headings:",
            "",
            "1. **Clause Context & Scope**",
            "   - Brief paraphrase of what the clause requires",
            "   - What systems/processes were in scope",
            "",
            "2. **Evidence Reviewed**",
            "   - List evidence actually reviewed (document name, version, date, type)",
            "   - State facts only, no commentary on sufficiency",
            "",
            "3. **Design Effectiveness ** (if applicable per Step 3)",
            "   - Existence of documented controls",
            "   - Alignment to clause intent",
            "   - Approval and governance",
            "   - Defined roles and responsibilities",
            "",
            "4. **Implementation Effectiveness ** (if applicable per Step 3)",
            "   - Whether designed control appears implemented",
            "   - Scope of implementation",
            "   - Configuration alignment with design",
            "",
            "5. **Operating Effectiveness ** (if applicable per Step 3)",
            "   - Whether control operated during audit period",
            "   - Evidence of monitoring, review, or execution",
            "   - Handling of exceptions",
            "",
            "6. **Overall Observational Summary**",
            "   - Neutral synthesis of design, implementation, and operating observations",
            "   - Prepares reader for compliance conclusion",
            "",
            "**LANGUAGE RULES:**",
            "- Use factual, descriptive language",
            "- Use phrases: 'was observed', 'was evidenced', 'was noted', 'no evidence was observed'",
            "- Do NOT use: 'non-compliant', 'deficient', 'failure'",
            "- Do NOT conclude compliance in this section",
            "",
            "---",
            "",
            "### STEP 9B – FINDINGS (MANDATORY FORMAT, ONLY WHERE WARRANTED)",
            "",
            "#### PURPOSE:",
            "Document material non-compliance or control weaknesses.",
            "",
            "#### WHEN TO RAISE FINDINGS:",
            "",
            "You MUST raise a finding ONLY IF:",
            "- Control is Non-Compliant or Partially Compliant",
            "- A material weakness exists that undermines the clause objective",
            "- Required effectiveness dimensions are not met",
            "",
            "You MUST NOT raise findings where the control is effective and clause is Compliant.",
            "",
            "**If no finding is warranted, explicitly state:**",
            "'No findings noted' (if Compliant)",
            "'NA as evidences were inadmissible' (if all evidence inadmissible)",
            "",
            "#### STRUCTURE OF EACH FINDING (MANDATORY):",
            "",
            "1. **CONDITION** – What was observed (factual, evidence-based with specific citations)",
            "2. **CRITERIA** – Regulatory requirement breached (verbatim or near-verbatim)",
            "3. **CAUSE** – Why it occurred (only if evident, otherwise state cannot be determined)",
            "4. **EFFECT / RISK** – Potential impact (regulatory & business)",
            "5. **RECOMMENDATION** – See Step 9C",
            "6. **SEVERITY** – Critical/Major/Significant/Minor per Step 10",
            "",
            "**LANGUAGE RULES:**",
            "- Use neutral, professional language",
            "- Evidence-based phrasing: 'was not evidenced', 'was not observed'",
            "- Avoid accusatory or emotive terms",
            "- Each finding should be 25-40 words per bullet point",
            "",
            "**SAMPLE-BASED FINDINGS:**",
            "When findings arise from samples, you MUST:",
            "1. State sampling approach",
            "2. Identify specific non-compliant samples",
            "3. Present as bullet list with identifiers",
            "",
            "---",
            "",
            "### STEP 9C – RECOMMENDATIONS (MANDATORY FOR EACH FINDING)",
            "",
            "#### PURPOSE:",
            "Prescribe corrective action that is proportionate, aligned with regulatory intent, and practical.",
            "",
            "#### PRINCIPLES:",
            "- Every Finding MUST have at least one Recommendation",
            "- Directly address the identified gap",
            "- Do not re-state the finding",
            "- Leverage existing policies where available",
            "- Be proportionate to severity and risk",
            "- Include timeline where appropriate",
            "",
            "#### STRUCTURE (MANDATORY):",
            "Each recommendation as one paragraph containing:",
            "1. **Action** – What needs to be done",
            "2. **Scope** – Where / to what it applies",
            "3. **Governance** – Who should oversee",
            "4. **Timeline** – By when (if applicable)",
            "",
            "#### SEVERITY-BASED TIMELINES:",
            "- **CRITICAL:** Immediate / ≤30 days",
            "- **MAJOR:** ≤30–60 days",
            "- **SIGNIFICANT:** ≤90 days",
            "- **MINOR:** No specific timeline or as reasonable",
            "",
            "**If no recommendations needed:**",
            "'No recommendations' (if Compliant with no findings)",
            "'NA as evidences were inadmissible' (if all evidence inadmissible)",
            "",
            "**LANGUAGE RULES:**",
            "- Use 'should' rather than 'must'",
            "- Directive but non-accusatory",
            "- Avoid prescribing specific vendors/tools unless mandated",
            "",
            "---",
            "",
            "## STEP 10 – SEVERITY CLASSIFICATION (ONLY IF FINDING EXISTS)",
            "",
            "### Severity Logic (STRICT):",
            "",
            "**CRITICAL:**",
            "- Evidence inadmissible for HIGH-critical clause",
            "- Control NOT IMPLEMENTED",
            "- Ineffective control exposing systemic risk",
            "- Regulatory breach with severe consequences",
            "",
            "**MAJOR:**",
            "- Incorrect or partial implementation of preventive control",
            "- Weak evidence for HIGH-critical clause",
            "- Significant regulatory breach",
            "",
            "**SIGNIFICANT:**",
            "- Partially effective control",
            "- Reliance on compensating controls",
            "- Moderate regulatory concern",
            "",
            "**MINOR:**",
            "- Documentation or procedural gaps only",
            "- Control effective but evidence/documentation weak",
            "- Low regulatory concern",
            "",
            "**N/A:**",
            "- Use only when no findings exist",
            "",
            "### Overall Severity Classification:",
            "- Select the HIGHEST severity level among all findings for the clause",
            "- If no findings: 'No findings noted'",
            "",
            "---",
            "",
            "## STEP 11 – FINAL OUTPUT FORMAT (STRICT - VALID JSON REQUIRED)",
            "",
            "**CRITICAL INSTRUCTION: You MUST output your response in TWO parts:**",
            "",
            "### PART 1: MARKDOWN NARRATIVE (Human-readable summary)",
            "Provide a brief summary in markdown format covering:",
            "- Overall compliance status",
            "- Key observations",
            "- Summary of findings (if any)",
            "- Summary of recommendations (if any)",
            "",
            "### PART 2: JSON OUTPUT (Machine-readable structured data)",
            "",
            "**You MUST output valid JSON in this EXACT structure:**",
            "",
            "```json",
            "{",
            f'  "control_id": "{getattr(project_control_activity, "id", "N/A")}",',
            '  "evidence_admissibility_decision": "Yes" or "No",',
            '  "evidence_quality_rating": "STRONG" or "ADEQUATE" or "WEAK" or "INADMISSIBLE",',
            '  "reason_for_inadmissibility": "text explaining why evidence is inadmissible, or N/A if admissible",',
            '  "required_effectiveness_dimensions_design": "yes" or "no",',
            '  "required_effectiveness_dimensions_implementation": "yes" or "no",',
            '  "required_effectiveness_dimensions_operating_effectiveness": "yes" or "no",',
            '  "detailed_control_testing_results": "Detailed text covering Design Effectiveness testing results (if applicable), Implementation Effectiveness testing results (if applicable), and Operating Effectiveness testing results (if applicable). Include specific outcomes: DESIGN OK/WEAK, IMPLEMENTED CORRECTLY/PARTIALLY/INCORRECTLY/NOT IMPLEMENTED, OPERATING EFFECTIVE/PARTIAL/INEFFECTIVE/NOT OPERATING",',
            '  "overall_compliance_status": "Compliant" or "Partially Compliant" or "Non-Compliant",',
            '  "observations": "**Clause Context & Scope:**\\n[text]\\n\\n**Evidence Reviewed:**\\n[list]\\n\\n**Design Effectiveness – Observations:**\\n[text if applicable per Step 3]\\n\\n**Implementation Effectiveness – Observations:**\\n[text if applicable per Step 3]\\n\\n**Operating Effectiveness – Observations:**\\n[text if applicable per Step 3]\\n\\n**Overall Observational Summary:**\\n[text]",',
            "  \"findings\": \"If findings exist: Detailed findings formatted in markdown with CONDITION, CRITERIA, CAUSE, EFFECT/RISK for each finding as separate bullet points. If no findings: 'No findings noted' or 'NA as evidences were inadmissible'\",",
            "  \"recommendations\": \"If recommendations exist: Detailed recommendations formatted in markdown with ACTION, SCOPE, GOVERNANCE, TIMELINE for each recommendation. Each recommendation should address a specific finding. If no recommendations: 'No recommendations' or 'NA as evidences were inadmissible'\",",
            "  \"severity_classification_for_each_finding\": \"List severity for each finding separately: 'Finding 1: Critical', 'Finding 2: Major', etc. If no findings: 'N/A'\",",
            '  "overall_severity_classification": "Critical or Major or Significant or Minor (the highest severity among all findings), or \'No findings noted\' if no findings exist"',
            "}",
            "```",
            "",
            "**CRITICAL JSON REQUIREMENTS:**",
            "1. All string values must be properly escaped",
            "2. Use \\n for line breaks within strings",
            '3. Use \\" for quotes within strings',
            "4. Ensure all required fields are present",
            "5. Do not use null - use 'N/A' for non-applicable fields",
            "6. The overall_compliance_status field MUST be exactly one of: 'Compliant', 'Partially Compliant', or 'Non-Compliant'",
            "7. Never use 'Unknown', 'Pending', or leave blank",
            "",
            "---",
            "",
            "## ABSOLUTE PROHIBITIONS",
            "",
            "- Do NOT assume facts not in evidence",
            "- Do NOT invent evidence",
            "- Do NOT over-report minor issues as major findings",
            "- Do NOT dilute genuine findings",
            "- Do NOT skip the compliance status determination",
            "- Do NOT output invalid JSON",
            "- Do NOT use 'Unknown' as compliance status",
            "",
            "---",
            "",
            "## USER QUERY / CLAUSE TO ASSESS",
            "",
            f"**User Input / Regulatory Clause:** {user_prompt if user_prompt else 'Not specified'}",
            "",
            "---",
            "",
            "## FINAL EXECUTION INSTRUCTIONS",
            "",
            "**YOU MUST:**",
            "1. Follow EVERY step in sequence (Steps 1-11)",
            "2. Do NOT skip any evaluation dimension",
            "3. ALWAYS determine a compliance status (Compliant/Partially Compliant/Non-Compliant)",
            "4. Be regulator-defensible at all times",
            "5. Use reasonable assurance principles",
            "6. Maintain neutral, factual language throughout",
            "7. Cite evidence explicitly and precisely",
            "8. Output valid JSON as specified above",
            "9. Ensure consistency between compliance status and findings",
            "10. If status is 'Compliant', findings must be 'No findings noted'",
            "11. If findings exist, status cannot be 'Compliant'",
            "",
            "**CONSISTENCY CHECK:**",
            "Before finalizing output, verify:",
            "- If overall_compliance_status = 'Compliant' → findings = 'No findings noted' and recommendations = 'No recommendations'",
            "- If findings exist → overall_compliance_status must be 'Partially Compliant' or 'Non-Compliant'",
            "- If all evidence is inadmissible → overall_compliance_status = 'Non-Compliant' and appropriate findings/recommendations documented",
            "",
            "**NOW PROCEED WITH THE EVALUATION FOLLOWING ALL STEPS ABOVE.**",
        ]
    )

    return "\n".join(prompt_parts)


def generate_compliance_prompt_from_project(
    project_name, auditing_firm_id, db_session
) -> list[str]:
    """
    Generate compliance prompts for all control activities across all compliance activities in a project
    Filtered by project_name and auditing_firm,and only for applicable clauses

    Args:
        project_name: Name of the project to filter by
        auditing_firm_id: ID of the auditing firm to filter by
        db_session: SQLAlchemy database session

    Returns:
        List of prompt strings for each control activity across all compliance activities in the project
    """

    projects = (
        db_session.query(Projects)
        .filter(
            Projects.project_name == project_name,
            Projects.auditing_firm == auditing_firm_id,
        )
        .all()
    )

    if not projects:
        return [
            f"Error: No projects found with name '{project_name}' and auditing firm ID '{auditing_firm_id}'"
        ]

    prompts = []

    # Process each project found
    for project in projects:

        # Traverse the new project-specific relationships to find all control activities
        for p_guideline in project.project_guidelines:
            for p_clause in p_guideline.project_clauses:
                # Only process clauses marked as applicable
                if not getattr(p_clause, "applicability", True):
                    continue  # Skip non-applicable clauses
                for p_activity in p_clause.project_compliance_activities:
                    for p_control in p_activity.project_control_activities:

                        # Call the prompt generation function for each project-specific control activity
                        # (This assumes the 'generate_compliance_prompt' function has also been updated
                        # to accept a ProjectControlActivity object)
                        main_prompt = generate_compliance_prompt(
                            project_control_activity=p_control
                        )
                        prompts.append(main_prompt)

    return prompts


def generate_all_project_prompts(
    project_name, auditing_firm_id, db_session
) -> dict[str, Any]:
    """
    Generate comprehensive assessment prompts for ALL projects with matching name and auditing firm
    Handles multiple projects with same name and multiple compliance activities per project

    Args:
        project_name: Name of the project to filter by
        auditing_firm_id: ID of the auditing firm to filter by
        db_session: SQLAlchemy database session

    Returns:
        Dictionary containing all project info and all control activity prompts
    """

    # Query projects with eager loading of relationships
    projects = (
        db_session.query(Projects)
        .options(
            db.joinedload(Projects.client_rel),
            db.joinedload(Projects.departments),  # Load all departments
            db.joinedload(Projects.primary_department),  # Load primary department
            db.joinedload(Projects.audit_org_rel),
            db.joinedload(Projects.project_guidelines)
            .joinedload(ProjectGuideline.project_clauses)
            .joinedload(ProjectClause.project_compliance_activities)
            .joinedload(ProjectComplianceActivity.project_control_activities),
        )
        .filter(
            Projects.project_name == project_name,
            Projects.auditing_firm == auditing_firm_id,
        )
        .all()
    )

    if not projects:
        return {
            "error": f"No projects found with name '{project_name}' and auditing firm ID '{auditing_firm_id}'"
        }

    # Call the corrected function to get prompts from the project instances
    prompts = generate_compliance_prompt_from_project(
        project_name, auditing_firm_id, db_session
    )

    project_summaries = []
    total_control_activities = 0
    applicable_clauses_count = 0
    non_applicable_clauses_count = 0

    for project in projects:
        # Count applicable and non-applicable clauses
        applicable_count = 0
        non_applicable_count = 0
        control_count = 0

        for p_guideline in project.project_guidelines:
            for p_clause in p_guideline.project_clauses:
                if getattr(p_clause, "applicability", True):
                    applicable_count += 1
                    control_count += len(
                        [
                            p_control
                            for p_activity in p_clause.project_compliance_activities
                            for p_control in p_activity.project_control_activities
                        ]
                    )
                else:
                    non_applicable_count += 1

        applicable_clauses_count += applicable_count
        non_applicable_clauses_count += non_applicable_count
        total_control_activities += control_count

        # Get all department names
        department_names = []
        if project.departments:
            department_names = [dept.department_name for dept in project.departments]
        elif project.primary_department:
            department_names = [project.primary_department.department_name]

        # Format department string
        if department_names:
            department_str = ", ".join(department_names)
        else:
            department_str = "N/A"

        project_summary = {
            "project_id": project.id,
            "project_name": project.project_name,
            "project_description": project.project_description,
            "client": getattr(project.client_rel, "name", "N/A"),
            "departments": department_names,  # List of all departments
            "department": department_str,  # String representation for backward compatibility
            "primary_department": getattr(
                project.primary_department, "department_name", None
            ),
            "auditing_firm": getattr(project.audit_org_rel, "firm_name", "N/A"),
            "project_period": f"{project.project_start_date} to {project.project_end_date}",
            "assessment_period": f"{project.assesment_start_date} to {project.assesment_end_date}",
            "project_complete": project.project_complete_status,
            "control_activities_count": control_count,
        }
        project_summaries.append(project_summary)

    return {
        "search_criteria": {
            "project_name": project_name,
            "auditing_firm_id": auditing_firm_id,
        },
        "total_projects_found": len(projects),
        "total_control_activities": total_control_activities,
        "project_summaries": project_summaries,
        "control_activity_prompts": prompts,
        "prompt_count": len(prompts) if isinstance(prompts, list) else 0,
    }


def generate_bulk_evaluation_prompt(
    control_activity,
    evidence_summary,
    test_procedure_info=None,
    activity_context=None,
    user_prompt=None,
):
    """
    Generate a comprehensive bulk evaluation prompt similar to individual reevaluation
    but optimized for processing multiple activities with consolidated evidence
    """
    # Extract activity details
    activity_name = control_activity.activity_name
    activity_description = (
        control_activity.activity_description or "No description available"
    )
    activity_code = control_activity.activity_code
    control_type = getattr(control_activity, "control_type", "N/A")
    frequency = getattr(control_activity, "frequency", "N/A")
    owner = getattr(control_activity, "owner", "N/A")
    objective = getattr(control_activity, "objective", "No objective specified")

    # Extract context
    clause_no = activity_context.get("clause_no", "N/A") if activity_context else "N/A"
    clause_text = activity_context.get("clause_text", "") if activity_context else ""
    project_name = (
        activity_context.get("project_name", "N/A") if activity_context else "N/A"
    )
    project_id = (
        activity_context.get("project_id", "N/A") if activity_context else "N/A"
    )

    # Prepare evidence details section
    evidence_details = []
    evidence_count = len(evidence_summary)

    if evidence_summary:
        evidence_details.append(f"**Total Evidence Items: {evidence_count}**")
        evidence_details.append("")

        for idx, evidence in enumerate(evidence_summary, 1):
            evidence_type = evidence.get("type", "unknown").upper()
            item = evidence.get("item", "Unknown Item")
            description = evidence.get("description", "No description")
            files = evidence.get("files", "")
            has_content = evidence.get("has_content", False)

            status = "✅ Provided" if has_content else "❌ Missing/Insufficient"

            evidence_details.append(f"**Evidence {idx} - {evidence_type}:**")
            evidence_details.append(f"- **Item:** {item}")
            evidence_details.append(f"- **Description:** {description}")
            if files:
                evidence_details.append(f"- **File Path:** {files}")
            evidence_details.append(f"- **Status:** {status}")
            evidence_details.append("")
    else:
        evidence_details.append("❌ **No evidence provided for evaluation**")
        evidence_details.append("")

    # Prepare test procedure details
    test_procedure_details = ""
    if test_procedure_info:
        test_procedure_details = "### Test Procedure Information:\n"

        if test_procedure_info.get("additional_walkthrough"):
            test_procedure_details += f"**Additional Walkthrough Notes:**\n{test_procedure_info['additional_walkthrough']}\n\n"

        if test_procedure_info.get("additional_sampling"):
            test_procedure_details += f"**Additional Sampling Notes:**\n{test_procedure_info['additional_sampling']}\n\n"

        if test_procedure_info.get("has_files"):
            test_procedure_details += (
                "**📎 Test Procedure Files Attached:** Available for review\n\n"
            )

    # Enhanced Auditor Language Section (same as individual)
    auditor_language_examples = """
    **AUDITOR LANGUAGE REQUIREMENTS & EXAMPLES:**
    
    **CRITICAL: Write from the perspective of an audit professional conducting the examination.**
    
    **OBSERVATIONS (Use first-person plural and specific testing details):**
    **DESIGN EFFECTIVENESS OBSERVATIONS:**
    - "We reviewed the control design and determined the policy framework adequately addresses the risk it intends to mitigate."
    - "Our analysis of the control design revealed that the procedure lacks sufficient segregation of duties to prevent errors."
    - "We examined the control documentation and found the design appropriately incorporates industry best practices for..."
    
    **IMPLEMENTATION ASSESSMENT OBSERVATIONS:**
    - "We verified implementation by examining system configurations and confirmed the control has been properly deployed across all relevant systems."
    - "Our review of implementation evidence identified that the control was only partially deployed, missing from three critical business units."
    - "We confirmed implementation through interviews with process owners and examination of deployment documentation."
    
    **OPERATING EFFECTIVENESS OBSERVATIONS:**
    - "We selected a sample of 25 transactions and verified that all contained proper authorization signatures as required by the control procedure."
    - "Our testing of 40 instances over a 6-month period demonstrated the control operated effectively in 95% of cases."
    - "We performed walkthroughs and tested 30 samples, identifying 4 instances where the control failed to operate as designed [Sample IDs: TXN-001, TXN-015, TXN-022, TXN-028]."
    - "We reviewed user access logs and found 3 instances of unauthorized access attempts [User IDs: USR-456, USR-789, USR-123]."

    **FINDINGS EXAMPLES:**
    - "We observed that user access reviews were not consistently documented, leading to potential unauthorized access risks."
    - "Our testing revealed incomplete evidence of management approvals for system changes."
    - "We identified gaps in the segregation of duties that could allow for unauthorized transactions."
    - "The control procedure was not followed consistently across all business units."
    
    **RECOMMENDATIONS (Be specific and actionable):**
    - "We recommend implementing a formal tracking mechanism for user access reviews to ensure all reviews are properly documented and approved by the quarter-end."
    - "Management should strengthen password complexity requirements and implement multi-factor authentication to address the unauthorized access attempts noted in our testing."
    - "We suggest establishing a monthly reconciliation process to be completed by the 5th business day of each month."
    
    **REQUIRED AUDITOR PHRASES:**
    - Use "We observed", "Our testing revealed", "We verified", "Our examination demonstrated"
    - Include specific sample sizes, periods covered, testing methodology
    - Reference what was actually tested vs. what should exist
    - Use professional skepticism language
    - **CRITICAL: When discrepancies are found, mention specific sample IDs, transaction IDs, user IDs, or other unique identifiers from the data provided**
    """

    # Enhanced Assessment Instructions
    enhanced_assessment_instructions = """
    **AUDITOR PERSPECTIVE REQUIREMENTS:**
    
    **1. Design Effectiveness Assessment:**
     - Evaluate whether the control is properly designed to prevent or detect errors
     - Review policy documents, procedure manuals, and control documentation
     - Assess if the design would be effective if operating properly
     - Identify any design deficiencies or gaps
     
     **2. Implementation Assessment:**
     - Verify that the control has been properly implemented as designed
     - Examine system configurations, deployment records, and implementation evidence
     - Confirm the control is in place and ready to operate
     - Identify any implementation gaps or partial deployments

     **3. Operating Effectiveness Testing:**
     - Test whether the control is operating as intended over time
     - Use appropriate sampling methodologies and time periods
     - Document sample sizes, testing periods, and testing approaches
     - Evaluate consistency of operation and identify exceptions
     - **CRITICAL: When identifying discrepancies, always include specific sample IDs, transaction numbers, user IDs, or other unique identifiers from the provided evidence**
     
     **AUDITOR PERSPECTIVE REQUIREMENTS:**
     - Use first-person plural ("We observed", "Our testing revealed", "We verified")
     - Reference specific testing procedures performed in each phase
     - Include quantitative details (sample sizes, periods, methodologies)
     - State what was actually examined vs. what was expected
     - **When discrepancies are found, explicitly mention the specific identifiers [Sample ID: XXX, Transaction ID: YYY, User ID: ZZZ]**
     
    **Finding Language Must:**
    - Clearly describe the nature of the deficiency
    - Explain what was found vs. what was expected
    - Describe the impact or risk of the finding

    **Recommendation Language Must:**
    - Be actionable and specific
    - Include reasonable timelines where appropriate
    - Reference industry best practices
    - Be practical and implementable
    """

    # Build the complete prompt
    prompt_parts = [
        "## BULK EVALUATION - Compliance Assessment for Control Activity",
        "",
        "### CONTROL ACTIVITY INFORMATION:",
        f"**Activity ID:** {control_activity.id}",
        f"**Activity Code:** {activity_code}",
        f"**Activity Name:** {activity_name}",
        f"**Activity Description:** {activity_description}",
        f"**Control Type:** {control_type}",
        f"**Frequency:** {frequency}",
        f"**Owner:** {owner}",
        f"**Project:** {project_name} (ID: {project_id})",
        f"**Clause:** {clause_no} - {clause_text}",
        "",
        "### CONTROL OBJECTIVE:",
        objective,
        "",
        "### EVIDENCE ANALYSIS:",
        "\n".join(evidence_details),
    ]

    # Add test procedure if available
    if test_procedure_details:
        prompt_parts.append(test_procedure_details)

    # Add existing data if available
    existing_observation = getattr(control_activity, "auditor_observation", None)
    if existing_observation:
        prompt_parts.extend(
            ["### EXISTING AUDITOR OBSERVATIONS:", existing_observation, ""]
        )

    existing_findings = getattr(control_activity, "findings", None)
    if existing_findings:
        prompt_parts.extend(["### EXISTING FINDINGS:", existing_findings, ""])

    # Add user prompt if provided
    if user_prompt:
        prompt_parts.extend(["### AUDITOR'S ADDITIONAL INSTRUCTIONS:", user_prompt, ""])

    # Add the structured assessment template
    prompt_parts.extend(
        [
            "<BulkAuditAssessmentPrompt>",
            "<SystemInstruction>",
            "You are an expert auditor conducting bulk compliance evaluations for regulatory compliance. ",
            "Your task is to meticulously evaluate this control activity against the consolidated evidence provided. ",
            "This evaluation is part of a bulk assessment process, so maintain consistency with individual evaluation standards.",
            "</SystemInstruction>",
            "",
            "<InputSection>",
            f"<ControlClause>Clause {clause_no}: {clause_text}</ControlClause>",
            f"<ActivityContext>Evaluating activity '{activity_name}' for project '{project_name}'</ActivityContext>",
            f"<AssessmentInstructionsTitle>Assessment Instructions:</AssessmentInstructionsTitle>",
            f"<EnhancedAssessmentInstructions>{enhanced_assessment_instructions}</EnhancedAssessmentInstructions>",
            f"<AuditorLanguageExamples>{auditor_language_examples}</AuditorLanguageExamples>",
            "</InputSection>",
            "",
            "<AssessmentProcess>",
            '<Step Number="1" Title="Evidence Analysis">',
            f"Analyze the {evidence_count} evidence items provided. For each evidence item:",
            "- Determine if it's complete, partial, or missing",
            "- Assess relevance to the control activity requirements",
            "- Evaluate quality and reliability",
            "- Cross-reference with control requirements",
            "</Step>",
            "",
            '<Step Number="2" Title="Comprehensive Testing">',
            "Conduct thorough testing across all three dimensions:",
            "**Design Testing:** Evaluate if control design would prevent/detect errors if operating properly",
            "**Implementation Testing:** Verify control has been deployed as designed",
            "**Operating Testing:** Test if control operates effectively over time",
            "**IMPORTANT:** When testing operating effectiveness, reference specific evidence items and include identifiers where available",
            "</Step>",
            "",
            '<Step Number="3" Title="Observation Documentation">',
            "Document detailed observations organized by:",
            "1. **Design Effectiveness:** Analysis of control design adequacy",
            "2. **Implementation Assessment:** Verification of deployment status",
            "3. **Operating Effectiveness:** Results of operational testing",
            "**CRITICAL:** When documenting exceptions, include specific references to evidence items",
            "</Step>",
            "",
            '<Step Number="4" Title="Findings & Recommendations">',
            "<FindingsGuidance>",
            "- Document findings only when genuine compliance gaps exist",
            "- Clearly state what was expected vs. what was found",
            "- Reference specific evidence that demonstrates the gap",
            "- Assess the risk and impact of each finding",
            "- **If no issues are found, state 'No findings'**",
            "</FindingsGuidance>",
            "<RecommendationsGuidance>",
            "- Provide actionable recommendations for each finding",
            "- Include specific management actions and timelines",
            "- Focus on practical, implementable solutions",
            "- **If compliant with no findings, state 'No Recommendation' unless significant improvement opportunities exist**",
            "</RecommendationsGuidance>",
            "</Step>",
            "</AssessmentProcess>",
            "",
            "<OutputRequirements>",
            "<FinalReportStructure>",
            "Provide a comprehensive audit report in the following structure:",
            "1. **Observations:** Detailed testing results organized by phase (Design, Implementation, Operating)",
            "2. **Findings:** List of compliance gaps/issues identified (or 'No findings')",
            "3. **Recommendations:** Actionable steps to address findings (or 'No Recommendation')",
            "4. **Overall Compliance Status:** Compliant, Partially-Compliant, or Not-Compliant",
            "5. **Risk Assessment:** Impact assessment of any findings",
            "</FinalReportStructure>",
            "<ObservationFormatConstraint>",
            "**Observations must follow this exact format:**",
            "**Design Effectiveness:** [Detailed analysis of control design]",
            "",
            "**Implementation Assessment:** [Verification of implementation status with evidence references]",
            "",
            "**Operating Effectiveness:** [Testing results with specific references to evidence items. When exceptions found, include identifiers like [Evidence Item: X, File: Y]]",
            "</ObservationFormatConstraint>",
            "<FormattingConstraint>",
            "Format your response with both a Markdown section and a JSON object.",
            "The JSON object must be the last part of your response.",
            "</FormattingConstraint>",
            "<JSONOutputSchema>",
            "<!-- The LLM must output a JSON object adhering exactly to this structure -->",
            "<OutputPrefix>**BULK EVALUATION OUTPUT**</OutputPrefix>",
            "<JSONBody>",
            f"""```json{{
    "control_id": "{control_activity.id}",
    "activity_code": "{activity_code}",
    "observations": "**Design Effectiveness:** <evaluation based on evidence items 1-{min(evidence_count, 3)}>\\n\\n**Implementation Assessment:** <verification with reference to specific evidence>\\n\\n**Operating Effectiveness:** <testing results - WHEN DISCREPANCIES FOUND, INCLUDE SPECIFIC EVIDENCE REFERENCES like [Evidence Item: X], [File: Y]>",
    "findings": "<Identify deficiencies found in evidence. Format using markdown. If no issues, state 'No findings'.>",
    "recommendations": "<Provide actionable suggestions from an auditor's perspective. Include specific management actions, implementation guidance, and timeline considerations. Format using markdown. If no findings and compliant, state 'No Recommendation'>",
    "overall_compliance_status": "<compliant, partially-compliant, or not-compliant>",
    "risk_assessment": "<Provide a concise assessment of the impact and severity of any findings.>",
    "evidence_summary": {{
        "total_items": {evidence_count},
        "valid_items": <count of evidence with has_content=True>,
        "missing_items": <count of evidence with has_content=False>
    }}
}}```""",
            "</JSONBody>",
            "</JSONOutputSchema>",
            "</OutputRequirements>",
            "",
            "<BulkEvaluationSpecifics>",
            "**NOTE: This is a bulk evaluation.** Ensure your assessment is:",
            "- **Consistent** with individual evaluation standards",
            "- **Comprehensive** despite being part of bulk processing",
            "- **Evidence-based** with specific references to provided items",
            "- **Professional** using proper auditor language",
            "</BulkEvaluationSpecifics>",
            "</BulkAuditAssessmentPrompt>",
            "",
            "**IMPORTANT FINAL INSTRUCTIONS:**",
            "1. Evaluate ALL provided evidence thoroughly",
            "2. Use professional auditor language throughout",
            "3. Be specific about what evidence supports your conclusions",
            "4. When compliance gaps exist, provide detailed findings and recommendations",
            "5. Output MUST include the JSON object exactly as specified",
            "",
        ]
    )

    return "\n".join(prompt_parts)


def generate_bulk_compliance_prompt(
    control_activity,
    evidence_summary,
    test_procedure_info=None,
    activity_context=None,
    user_prompt=None,
):
    """
    Main function to generate bulk evaluation prompt
    This calls the detailed prompt generator and ensures proper formatting
    """
    return generate_bulk_evaluation_prompt(
        control_activity=control_activity,
        evidence_summary=evidence_summary,
        test_procedure_info=test_procedure_info,
        activity_context=activity_context,
        user_prompt=user_prompt,
    )


# Example usage:
#
# # Generate prompts for all control activities in a project
# prompts = generate_compliance_prompt_from_project(
#     project_name="SOX Compliance Assessment 2024",
#     auditing_firm_id=1,
#     db_session=session
# )
#
# # Or get comprehensive project information with all prompts
# result = generate_all_project_prompts(
#     project_name="SOX Compliance Assessment 2024",
#     auditing_firm_id=1,
#     db_session=session
# )
#
# print(f"Found {result['prompt_count']} control activities")
# for i, prompt in enumerate(result['control_activity_prompts'], 1):
#     print(f"\n=== CONTROL ACTIVITY {i} ===")
#     print(prompt)
