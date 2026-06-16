import json
import logging
from pydantic import BaseModel, Field, model_validator, field_validator
from datetime import date
from app.models.ai import *
from typing import List, Optional

logger = logging.getLogger(__name__)


class ClausesModel(BaseModel):
    clause_number: str = Field(
        ...,
        description="Clause Number (if available, otherwise generate sequential numbering with section name before number example, <section name>-1)",
    )
    clause_text: str
    page_number: int


class ClauseJSON(BaseModel):
    requirements: List[ClausesModel] = Field(
        ..., description="List of extracted clauses"
    )


class ConsolidatedTestProcedureJSON(BaseModel):
    consolidated_summary: str
    key_testing_areas: List[str]
    walkthrough_approach: str
    sampling_methodology: str


class ConsolidatedFindingsJSON(BaseModel):
    consolidated_summary: List[str]  # This will be bullet points


class ConsolidatedObservationJSON(BaseModel):
    consolidated_summary: str
    key_observations: List[str]
    common_patterns: List[str]
    risk_areas: List[str]
    improvement_opportunities: List[str]


class ConsolidatedRecommendationsJSON(BaseModel):
    consolidated_summary: List[str]  # This will be bullet points


def consolidated_test_procedure_prompt(test_procedures_data: dict) -> str:
    """
    Generates the prompt for consolidated test procedure summary extraction.
    """
    user_test_procedure = ""
    test_procedure_prompt_obj = AIPrompts.query.filter_by(
        prompt_type="CONSOLIDATED_TEST_PROCEDURE", is_active=True
    ).first()

    if test_procedure_prompt_obj:
        user_test_procedure = test_procedure_prompt_obj.prompt_text

    consolidated_prompt = f"""
    You are an expert IT auditor and compliance specialist with deep knowledge of control testing methodologies.

    Your task is to analyze multiple individual test procedures and create a comprehensive, consolidated test procedure summary that can be used for efficient auditing.

    **INPUT DATA:**
    {json.dumps(test_procedures_data, indent=2)}

    <ADDITIONALUSERINSTRUCTIONS>
    {user_test_procedure}
    </ADDITIONALUSERINSTRUCTIONS>

    **Instructions for Analysis:**

    1. **Consolidate Walkthrough Procedures**: Combine all walkthrough approaches into a unified methodology
    2. **Integrate Sampling Methods**: Create a comprehensive sampling strategy that covers all testing needs
    3. **Identify Dependencies**: Highlight any dependencies or relationships between different control activities
    4. **Optimize Testing Sequence**: Suggest the most efficient sequence for executing test procedures
    5. **Risk-Based Focus**: Prioritize testing areas based on risk and materiality

    **REQUIRED OUTPUT STRUCTURE:**

    1. **Consolidated Summary**: A comprehensive overview of the unified testing approach
    2. **Key Testing Areas**: List of critical areas that require focused attention
    3. **Walkthrough Approach**: Detailed methodology for process walkthroughs
    4. **Sampling Methodology**: Comprehensive sampling strategy for evidence collection

    **QUALITY REQUIREMENTS:**

    - Must be practical and actionable for auditors
    - Should eliminate redundancy across individual procedures
    - Must maintain audit trail requirements
    - Should optimize testing effort while maintaining coverage
    - Must identify potential testing efficiencies

    Your output must be a JSON object that strictly adheres to the provided ConsolidatedTestProcedureJSON Pydantic model.
    """

    return consolidated_prompt


def consolidated_observation_prompt(observations_data: dict) -> str:
    """
    Generates the prompt for consolidated observation summary extraction.
    """
    user_observation_prompt_obj = AIPrompts.query.filter_by(
        prompt_type="CONSOLIDATED_OBSERVATION", is_active=True
    ).first()

    user_observation_instructions = ""
    if user_observation_prompt_obj:
        user_observation_instructions = user_observation_prompt_obj.prompt_text

    consolidated_prompt = f"""
    You are an expert IT auditor and compliance specialist with deep knowledge of control testing and observation analysis.

    Your task is to analyze multiple auditor observations from control activities and create a comprehensive, consolidated observation summary that highlights key insights and patterns.

    **INPUT DATA:**
    {json.dumps(observations_data, indent=2)}

    <ADDITIONALUSERINSTRUCTIONS>
    {user_observation_instructions}
    </ADDITIONALUSERINSTRUCTIONS>

    **Instructions for Analysis:**

    1. **Identify Common Themes**: Look for recurring patterns across different observations
    2. **Assess Risk Implications**: Evaluate the risk impact of observed issues
    3. **Highlight Strengths**: Note any positive observations or well-implemented controls
    4. **Prioritize Issues**: Rank observations based on severity and business impact
    5. **Connect Related Observations**: Group related observations that might have cumulative impact
    6. **Focus on Applicable Activities**: Only analyze observations from activities marked as applicable

    **REQUIRED OUTPUT STRUCTURE:**

    1. **Consolidated Summary**: A comprehensive overview of all observations with key insights
    2. **Key Observations**: List of the most significant observations that require attention
    3. **Common Patterns**: Recurring themes or issues across multiple activities
    4. **Risk Areas**: Specific areas where risks are most pronounced
    5. **Improvement Opportunities**: Concrete suggestions for addressing observed issues

    **QUALITY REQUIREMENTS:**

    - Must be analytical and actionable for management
    - Should prioritize observations based on risk and impact
    - Must maintain audit objectivity and professionalism
    - Should provide clear recommendations for improvement
    - Must highlight both strengths and weaknesses
    - Focus only on applicable activities with meaningful observations

    Your output must be a JSON object that strictly adheres to the provided ConsolidatedObservationJSON Pydantic model.
    """

    return consolidated_prompt


def consolidated_findings_prompt(findings_data: dict) -> str:
    """
    Generates the prompt for consolidated findings summary extraction.
    """
    user_findings_prompt_obj = AIPrompts.query.filter_by(
        prompt_type="CONSOLIDATED_FINDINGS", is_active=True
    ).first()

    user_findings_instructions = ""
    if user_findings_prompt_obj:
        user_findings_instructions = user_findings_prompt_obj.prompt_text

    consolidated_prompt = f"""
    You are an expert IT auditor and compliance specialist with deep knowledge of control testing and findings analysis.

    Your task is to analyze multiple findings from control activities and create a comprehensive, consolidated findings summary in bullet points format.

    **INPUT DATA:**
    {json.dumps(findings_data, indent=2)}

    <ADDITIONALUSERINSTRUCTIONS>
    {user_findings_instructions}
    </ADDITIONALUSERINSTRUCTIONS>

    **CRITICAL FORMATTING REQUIREMENTS:**

    1. **NO MARKDOWN FORMATTING**: Do NOT use any markdown syntax like **bold**, *italic*, or any other formatting
    2. **CLEAN TEXT ONLY**: Use plain, clean text without any special characters for formatting
    3. **PROFESSIONAL LANGUAGE**: Maintain professional audit language but without markdown
    4. **BULLET POINTS**: Create clear bullet points using plain text only

    **Instructions for Analysis:**

    1. **Extract Key Findings**: Identify all significant findings from applicable activities
    2. **Summarize Concisely**: Create detailed but concise bullet points
    3. **Maintain Specificity**: Keep the technical details and specifics from each finding
    4. **Avoid Duplication**: Consolidate similar findings but maintain their unique aspects
    5. **Focus on Applicable Activities**: Only analyze findings from activities marked as applicable
    6. **Remove All Formatting**: Ensure no markdown, asterisks, or special formatting characters
    7.**STRICT FINDING DEFINITION (MANDATORY RULE)** :
        A finding must ONLY represent one of the following:
        - A control gap
        - A design deficiency
        - An implementation failure
        - Missing evidence
        - Ineffective operation
        - Policy non-compliance
        - Documentation absence
        
        Compliant controls, effective implementations, or normal observations MUST NOT be treated as findings under any circumstance.
        
        **OBSERVATION vs FINDING CLASSIFICATION RULE:**
        
        - Compliant activity → Observation (exclude from findings)
        - No issue identified → Observation (exclude from findings)
        - Improvement suggestion → Observation (exclude from findings)
        - Gap / failure / non-compliance → Finding (include in findings)
        
        If there is no gap, it MUST NOT appear in the findings section.
        
        **DEDUPLICATION AND CONSOLIDATION RULE:**
        
        Review the complete list of findings and for each finding ask:
        Is this finding unique? Is it talking about a gap that no other finding in this list is talking about?
        
        If YES - copy the bullet point exactly as it is, including the severity rating.
        If NO - consolidate the related findings that are talking about the same or similar gap into one single bullet point.
        
        **BULLET POINT DRAFTING GUIDANCE:**
        
        Each bullet point must follow these rules:
        - Length: 25 to 40 words per bullet point
        - One clear factual statement per bullet point
        - Must be evidence-anchored (reference specific documents, dates, screenshots, or records)
        - Severity rating must be the highest severity among all findings being consolidated into that bullet point
        
        Example of correct length and style:
        Review of system configuration screenshots dated 12 January 2024 indicates that multi-factor authentication is enabled only for administrative users and not enforced for maker or checker roles within the digital payment application. (Severity: Critical)
        
        **FINAL ARRANGEMENT RULE:**
        
        - Rearrange the final set of bullet points into a logical sequence
        - Do not repeat any findings
        - Make sure to include all findings from all test procedures
        - Apply the MECE Principle (Mutually Exclusive, Collectively Exhaustive)
    

    **REQUIRED OUTPUT STRUCTURE:**

    - A list of bullet points that comprehensively summarize all findings
    - Each bullet point should be detailed, specific, and actionable
    - Maintain the technical accuracy of the original findings
    - Group related findings but keep them as separate bullet points for clarity
    - Use plain text only - NO markdown formatting
    - **FINDINGS SECTION RULES (MANDATORY):**
      Only gaps are allowed in the findings section. No exceptions.
      
      Each finding MUST include all three of the following components in this exact order:
      - Description of the gap
      - Impact of the gap
      - Severity rating in brackets at the end
      
      Required format for every bullet point:
      Gap description. Impact explanation. (Severity: Critical/Major/Significant/Minor)
      
      **SEVERITY CALIBRATION:**
      
      - Critical → Requires immediate structural remediation
      - Major → Requires prompt corrective action
      - Significant → Requires strengthening measures
      - Minor → Requires procedural improvements
      
      **STRICTLY EXCLUDE FROM FINDINGS:**
      
      The following must NEVER appear in the findings section:
      - Compliant controls
      - Normal observations
      - Strengths or positive confirmations
      - Implementation confirmations
      - Recommendations
      
      These belong in the Observations section, NOT in Findings. If any of the above are mistakenly included in findings, remove them before finalizing the output.
      
      **FINDING FILTER CHECKLIST (apply before adding any bullet point to findings):**
      
      Before adding any bullet point to the findings section, validate against this checklist:
      - If the control is working → move to observations, exclude from findings
      - If the activity is compliant → move to observations, exclude from findings
      - If no deficiency exists → exclude entirely from findings
      - Only include if one of the following is true: gap exists, something is missing, control is ineffective, non-compliant, or undocumented

    **QUALITY REQUIREMENTS:**

    - Must be detailed and technically accurate
    - Should maintain all specific details from original findings
    - Must be in clear bullet point format WITHOUT markdown
    - Should prioritize findings based on severity and impact
    - Must focus only on applicable activities with meaningful findings
    - Absolutely NO asterisks, bold, italic, or other markdown syntax
    - **FINDING FILTER (NON-NEGOTIABLE):**
    
      Before adding any bullet point to findings, validate against the following:
      - IF control is working → move to observations
      - IF activity is compliant → move to observations
      - IF no deficiency exists → EXCLUDE from findings entirely
      
      Only include a bullet point in findings if at least one of the following is true:
      - A gap exists
      - Something is missing
      - Control is ineffective
      - Activity is non-compliant
      - Something is undocumented

    **EXAMPLES OF WHAT TO AVOID:**
    ❌ **Lack of Documentation**: Critical verification documents...
    ❌ *Inadequate Employee Engagement*: No recorded interview...
    ❌ Activity is compliant with no findings noted
    ❌ Framework is documented and approved
    ❌ Periodic assessments conducted quarterly
    These are observations, NOT findings.

    
    **EXAMPLES OF WHAT TO USE:**
    ✅ Lack of Documentation: Critical verification documents such as policies/ procedures, income assessment sheets, bank statements, and tax returns are missing, hindering compliance assessments. (Severity: Medium)
    ✅ Inadequate Employee Engagement: No recorded interview responses from key personnel including Credit Analysts and Loan Officers indicate gaps in staff understanding. (Severity: Low)
    ✅ Training records not maintained. Staff unable to demonstrate risk awareness. (Severity: High)
    ✅ No evidence of feedback mechanism for training programs. This may result in ineffective risk awareness. (Severity: Medium)

    """

    return consolidated_prompt


def consolidated_recommendations_prompt(recommendations_data: dict) -> str:
    """
    Generates the prompt for consolidated recommendations summary extraction.
    """
    user_recommendations_prompt_obj = AIPrompts.query.filter_by(
        prompt_type="CONSOLIDATED_RECOMMENDATIONS", is_active=True
    ).first()

    user_recommendations_instructions = ""
    if user_recommendations_prompt_obj:
        user_recommendations_instructions = user_recommendations_prompt_obj.prompt_text

    consolidated_prompt = f"""
    CRITICAL INSTRUCTION: YOU MUST OUTPUT PLAIN TEXT WITHOUT ANY MARKDOWN FORMATTING. NO ASTERISKS, NO BOLD, NO ITALICS.

    You are an expert IT auditor creating a consolidated recommendations summary. Analyze the recommendations data and create actionable bullet points.

    INPUT DATA:
    {json.dumps(recommendations_data, indent=2)}

    ADDITIONAL INSTRUCTIONS:
    {user_recommendations_instructions}

    FORMATTING RULES - STRICTLY ENFORCED:
    1. ABSOLUTELY NO MARKDOWN: Do not use ** for bold or * for italics
    2. NO ASTERISKS: Do not use asterisks at the beginning of bullet points
    3. PLAIN TEXT ONLY: Use clean, professional language without formatting
    4. Start each bullet point with an actionable recommendation

    BAD EXAMPLES (DO NOT USE):
    - **Implement Documentation Procedures**: Create a system for...
    - *Conduct Regular Training*: Establish training sessions...
    **Enhance Monitoring**: Implement automated tracking...

    GOOD EXAMPLES (USE THESE):
    - Implement Documentation Procedures: Establish a robust system for collecting and maintaining internal memos, lists of regulatory directions, and compliance artifacts to support comprehensive assessments.
    - Conduct Regular Training: Schedule structured training sessions for compliance officers and regulatory liaisons to ensure clarity on roles, responsibilities, and documentation requirements.
    - Enhance Monitoring Procedures: Implement an automated tracking system to capture daily monitoring activities and generate accurate monthly compliance reports for regulatory bodies.

    ANALYSIS INSTRUCTIONS:
    1. Extract all significant recommendations from the activities
    2. Consolidate similar recommendations while maintaining specifics
    3. Prioritize by impact and feasibility
    4. Focus on actionable, practical recommendations
    5. Ensure recommendations address the identified findings
    6. Use clear, professional audit language

    OUTPUT REQUIREMENTS:
    - List of bullet points in plain text
    - No markdown formatting of any kind
    - Each point should start with an actionable recommendation
    - Maintain technical accuracy and specifics
    - Focus on applicable activities only
    - Recommendations should be practical and implementable

    Your output must be a JSON object that strictly adheres to the provided ConsolidatedRecommendationsJSON Pydantic model.
    REMEMBER: NO MARKDOWN, NO ASTERISKS, NO FORMATTING - PLAIN TEXT ONLY.
    """

    return consolidated_prompt


def clause_prompt_def(page_range: str | None = None) -> str:
    """
    Generates the structured prompt for clause extraction, specifically for RBI documents, optionally focusing on a page range.
    """
    user_clauses = ""
    clause = AIPrompts.query.filter_by(prompt_type="CLAUSES", is_active=True).first()
    if clause:
        user_clauses = clause.prompt_text

    # Add a dynamic instruction for the page range
    focus_instruction = (
        f"**IMPORTANT: Focus your extraction ONLY on the content from {page_range} of the document. Do not extract clauses from other parts of the document in this request.**"
        if page_range
        else ""
    )

    clause_prompt = f"""
<ClauseExtractionPrompt>
 <SystemInstruction>
  You are an expert in regulatory compliance, IT governance, and financial institution risk management.
 </SystemInstruction>

 <TaskDescription>
  Your task is to meticulously extract every distinct regulatory requirement, mandate, or instruction that regulated entities (REs) must follow from the provided document.
 </TaskDescription>

 <FocusInstruction>
    {focus_instruction}
 </FocusInstruction>

 <PageHandlingInstructions>
  <Instruction>The document text contains page markers like "--- Page N ---". These are NOT part of the document content — they are technical separators only.</Instruction>
  <Instruction>CROSS-PAGE CLAUSES: A clause that starts on one page and continues on the next page must be extracted as ONE complete clause. Do NOT split or truncate it at the page boundary. Continue reading past page markers to get the full clause text.</Instruction>
  <Instruction>HEADERS: Ignore any repeated document title or heading at the top of a page — these are page headers, not clauses.</Instruction>
  <Instruction>FOOTERS: Ignore standalone page numbers (e.g. a lone "157" or "26") — these are page footers, not clauses.</Instruction>
  <Instruction>FOOTNOTES: Ignore any text starting with a superscript/footnote number followed by "Inserted by", "Substituted by", "Omitted by", "Added by", "Prior to", or containing "w.e.f." followed by a date — these are amendment footnotes, not regulatory requirements.</Instruction>
 </PageHandlingInstructions>

 <StructuredIdentifierInstructions>
  <Overview>
   STEP 1 — Before extracting any clause, map the document structure:
   Identify all CHAPTERS (Roman numerals: I, II, III...), SCHEDULES (Roman numerals or numbers), 
   PARTS within each Schedule (Alphabets: A, B, C...), and ANNEXURES.
  </Overview>

  <ClauseNumberFormat>
   Construct clause_number using this EXACT format: {{PREFIX}} {{SECTION}} {{PART}} {{REG}} {{SUB-LEVELS}}
   
   PREFIX codes:
   - CH  = Chapter  (e.g. CHAPTER IV)
   - SCH = Schedule (e.g. SCHEDULE III)
   - ANN = Annexure (e.g. ANNEXURE A)
   
   RULES:
   - Separate each level with a single space
   - Sub-levels use parentheses exactly as in document: (1), (a), (i), (1A), (ia)
   - Inserted sub-regulations like (1A), (1B), (1C) or inserted clauses like (ia), (na) — use exactly as written
   
   EXAMPLES:
   - Chapter IV, Regulation 17, Sub-regulation (1), Clause (a)    → CH IV 17 (1) (a)
   - Chapter I, Regulation 2, Sub-regulation (1), Clause (ia)     → CH I 2 (1) (ia)
   - Chapter IV, Regulation 17, Sub-regulation (1C), Clause (a)   → CH IV 17 (1C) (a)
   - Schedule I, Point (1), Sub-point (a)                         → SCH I (1) (a)
   - Schedule II, Part A, Point A                                  → SCH II A A
   - Schedule II, Part B, Point A, Sub-point (1)                  → SCH II B A (1)
   - Schedule II, Part C, Point A, Sub-point (4), Sub-sub (a)     → SCH II C A (4) (a)
   - Schedule III, Part A, Section A, Point 1, Sub (i), Sub (a)   → SCH III A A 1 (i) (a)
   - Schedule V, Part A, Point 1                                   → SCH V A 1
   - Schedule V, Part C, Sub-section (2), Sub-point (f)           → SCH V C (2) (f)
   - Schedule IX, Amendment 1, Sub-amendment (i)                  → SCH IX 1 (i)
   - Annexure A, Point 1, Sub-point (a)                           → ANN A 1 (a)
  </ClauseNumberFormat>

  <ExclusionRules>
   DO NOT extract as clauses:
   - Chapter/Schedule/Part headings (e.g. "CHAPTER IV", "PART A: MINIMUM INFORMATION...")
   - Cross-reference tags (e.g. "[See Regulation 17(7)]")
   - Omitted/deleted clauses marked with [***]
   - Inline footnote reference numbers embedded in text (e.g. "600[or through...]" — strip the number, keep the text)
   - Omitted Schedules/sections (e.g. "SCHEDULE VIII [***]" — do not extract)
  </ExclusionRules>

  <ClauseTextCleaning>
   clause_text must contain ONLY the clean regulatory requirement text:
   - Remove inline footnote reference numbers: "600[or through the depositories]" → "or through the depositories"
   - Remove superscript numbers embedded in text
   - Do NOT include the clause number itself in clause_text
   - Provisos: extract as separate clause with suffix _PRV on clause_number (e.g. CH I 1 (2) _PRV)
   - Explanations: extract as separate clause with suffix _EXP on clause_number
  </ClauseTextCleaning>

  <UniquenessRule>
   CRITICAL: The clause_number alone must uniquely identify any clause in the entire document.
   No two clauses should have the same clause_number.
   If two clauses would have the same number (e.g. point "1" appears in both SCH II A and SCH III A),
   the prefix ensures uniqueness: SCH II A 1 vs SCH III A 1.
  </UniquenessRule>
 </StructuredIdentifierInstructions>

  <AdditionalUserInstructions>
    {user_clauses or "Extract all clauses from the document."}
  </AdditionalUserInstructions>


 <OutputInstructions>
  <Instruction number="1">Capture all key details. For each requirement, extract its full text, clause number (if present), and page number.</Instruction>
  <Instruction number="2">Handle missing clause numbers gracefully. If a clause number isn't present, create a unique identifier by combining the relevant section or sub-section title with a sequential number (e.g., SECTION_TITLE_01).</Instruction>
  <Instruction number="3">Populate every field. Each requirement must have values for clause_number, clause_text, and page_number — none should be empty or null.</Instruction>
  <Instruction number="4">Avoid duplicates. Ensure each extracted clause is unique and not repeated.</Instruction>
  <Instruction number="5">Arrange in ascending order. Make sure the final output is sorted by clause_number.</Instruction>
  <MandatoryRequirement>COMPLETENESS IS MANDATORY: You MUST extract ALL regulatory requirements— no omissions.</MandatoryRequirement>
  <MandatoryRequirement>DENSE PAGES: Some pages have heavy footnotes at the bottom. These footnotes are NOT clauses. The actual regulatory requirements are in the main body text. Do NOT skip any clause just because the page has many footnotes.</MandatoryRequirement>
  <MandatoryRequirement>SEQUENTIAL COMPLETENESS: You are processing a CHUNK of pages. Extract EVERY clause in this chunk — do not skip middle sections. If a regulation has sub-clauses (1),(2),(3) or (a),(b),(c), extract ALL of them — not just the first few.</MandatoryRequirement>
  <MandatoryRequirement>CROSS-PAGE CONTINUITY: A regulation that starts on one page and continues on the next must be extracted as complete clauses. Do not stop at the page boundary.</MandatoryRequirement>
  <MandatoryRequirement>If the Clause has big text do not break into sub clauses return the whole text.</MandatoryRequirement>
  <Example>Given the clause is "Derogating from the prohibition on processing special categories of personal data should also be allowed when
provided for in Union or Member State law and subject to suitable safeguards, so as to protect personal data and
other fundamental rights, where it is in the public interest to do so, in particular processing personal data in the
field of employment law, social protection law including pensions and for health security, monitoring and alert
purposes, the prevention or control of communicable diseases and other serious threats to health. Such a
derogation may be made for health purposes, including public health and the management of health-care
services, especially in order to ensure the quality and cost-effectiveness of the procedures used for settling claims
for benefits and services in the health insurance system, or for archiving purposes in the public interest, scientific
or historical research purposes or statistical purposes. A derogation should also allow the processing of such
personal data where necessary for the establishment, exercise or defence of legal claims, whether in court
proceedings or in an administrative or out-of-court procedure", do not break it into parts.</Example>
  <FormattingInstruction>
   Extract all requirements exactly as written— copy and paste them without breaking lines. If a requirement has sub-items (e.g., 4a, 4b), include them together under the main clause number.
  </FormattingInstruction>
  
  <OutputFormat>
   The output must be a JSON object that strictly adheres to the following structure.
   The final output MUST be wrapped inside a markdown block: ```json ... ```
   
   {{
    "extracted_requirements": [
      {{
        "clause_number": "CH IV 17 (1) (a)",
        "clause_text": "where the chairperson of the board of directors is a non-executive director, at least one-third of the board of directors shall comprise of independent directors.",
        "page_number": 26
      }},
      {{
        "clause_number": "SCH II C A (4) (a)",
        "clause_text": "matters required to be included in the director's responsibility statement to be included in the board's report in terms of clause (c) of sub-section (3) of Section 134 of the Companies Act, 2013.",
        "page_number": 158
      }},
      ...
    ]
   }}
  </OutputFormat>
 </OutputInstructions>
</ClauseExtractionPrompt>


"""
    return clause_prompt
