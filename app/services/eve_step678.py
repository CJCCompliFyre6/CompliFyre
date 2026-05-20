# app/services/eve_step678.py
#
# Module E — EVE Step 6: Aggregation + Severity Engine
# Module F — EVE Step 7: Recommendation Engine
# Module G — EVE Step 8: Clause-Level Aggregation
#
# Runs on AUDITOR side after all evidence has been evaluated (Step 5).
# Steps 6+7 run together per control activity.
# Step 8 runs after ALL control activities under a clause are done.

import json
import time
import logging
from datetime import datetime

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from app import db, client
from app.models.ai import Clauses
from app.models.project_instance_models import (
    ProjectControlActivity,
    ProjectClause,
    ProjectComplianceActivity,
)
from app.models.eve_models import (
    ProjectChecklist,
    EveEvidenceResult,
    EveControlResult,
)

logger = get_task_logger(__name__)


# ─────────────────────────────────────────────────────────────
# LLM call — temperature=0 for determinism
# ─────────────────────────────────────────────────────────────

def _call_llm_json(system_msg: str, user_msg: str, retries: int = 3, backoff: float = 2.0) -> dict | None:
    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,
                top_p=0.1,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
            )
            raw = response.choices[0].message.content
            if not raw:
                raise ValueError("Empty response from LLM")
            return json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"Attempt {attempt + 1}: JSON decode error — {e}")
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1}: LLM call failed — {e}")

        if attempt < retries - 1:
            wait = backoff ** (attempt + 1)
            logger.info(f"Retrying in {wait:.1f}s...")
            time.sleep(wait)

    logger.error("All LLM retries exhausted")
    return None


# ─────────────────────────────────────────────────────────────
# Prompt builders — match EVE v2 Excel exactly
# ─────────────────────────────────────────────────────────────

def _build_step6_prompt(required_dimensions: dict, checklist: list, evidence_results: list) -> str:
    return f"""You are an Audit Aggregation and Evaluation Engine.

TASK:
Using structured outputs from STEP 5, you must:
1. Determine final status for each checklist item
2. Generate structured observations (one per checklist item)
3. Generate findings (only for FAIL and material PARTIAL items)
4. Assign severity using a deterministic severity engine

Return ONLY valid JSON.

DO NOT:
* re-evaluate evidence content
* generate recommendations
* assume missing information
* use vague or generic language

---

INPUT:

* Required Dimensions:
  {json.dumps(required_dimensions, indent=2)}

* Checklist:
  {json.dumps(checklist, indent=2)}

* Evidence Results:
  {json.dumps(evidence_results, indent=2)}

* Escalated Inquiries (unresolved contradictions → must generate findings):
  {{escalated_inquiries_json}}

---

IMPORTANT — ESCALATED INQUIRIES:
Escalated inquiries represent contradictions or issues that the auditor could NOT resolve.
These MUST contribute to findings generation regardless of signal status.
For each escalated inquiry:
* Create a finding with severity based on inquiry severity (MATERIAL → HIGH, MINOR → MEDIUM)
* Finding must clearly state: the contradiction detected, the checklist item, and why it was escalated
* Do NOT ignore escalated inquiries — they are confirmed audit issues

---

SUB-STEP-1 — GROUP BY CHECKLIST ITEM
Group all admissible evidence by checklist_id.
Ignore INADMISSIBLE evidence.

SUB-STEP-2 — APPLY EVIDENCE WEIGHTING
Priority: STRONG > MODERATE > WEAK, PRIMARY > SUPPORTING
Rules:
* WEAK evidence cannot independently PASS HIGH weight items
* SUPPORTING evidence cannot override PRIMARY

SUB-STEP-3 — RESOLVE SIGNALS TO FINAL STATUS

3.1 CONTRADICTION RULE
IF any STRONG evidence has CONTRADICTS → final_status = FAIL
IF only WEAK evidence contradicts → ignore contradiction
IF checklist item has ESCALATED inquiry → final_status = FAIL (override)

3.2 SUPPORT RULE
IF at least one STRONG or MODERATE evidence SUPPORTS AND no strong contradiction → proceed

3.3 NO EVIDENCE
IF no admissible evidence → final_status = FAIL

SUB-STEP-4 — SAMPLE-BASED LOGIC (IF APPLICABLE)
IF testing_approach = SAMPLE:
  IF within_audit_period = NO → final_status = FAIL
  IF population_size is NULL → sample_validity = LOW
  ELSE compute sampling_ratio = sample_size / population_size
    IF population ≤ 10 AND ratio ≥ 50% → HIGH
    IF population 10-100 AND ratio ≥ 20% → ACCEPTABLE
    IF population > 100 AND ratio ≥ 10% → ACCEPTABLE
    ELSE → LOW

  IF critical exception present → FAIL
  IF exception_rate = 0: HIGH validity → PASS, else → PARTIAL
  IF exception_rate > 0 AND ≤ 10% → PARTIAL
  IF exception_rate > 10% → FAIL

SUB-STEP-5 — NON-SAMPLE ITEMS
IF SUPPORTS present AND no contradiction → PASS
IF only WEAK evidence OR incomplete → PARTIAL

SUB-STEP-6 — FINAL CHECKLIST SUMMARY
For each checklist item:
{{"checklist_id": "", "requirement": "", "final_status": "PASS/PARTIAL/FAIL", "basis": "", "confidence": "HIGH/MEDIUM/LOW"}}

SUB-STEP-7 — GENERATE OBSERVATIONS (MANDATORY)
Generate EXACTLY ONE observation per checklist item.
FORMAT: "• [Checklist ID] – [Requirement]: Observed that [specific fact] in [evidence type] (Reference: [section/page]). The requirement was [met/partially met/not met]. Status: COMPLIANT/PARTIAL/EXCEPTION"
Rules:
* STRICT: Maximum 2 sentences per observation
* Must reference actual evidence and location
* Avoid vague wording
* Do NOT write paragraphs — one concise sentence per observation
* Do NOT repeat information from other observations

SUB-STEP-8 — GENERATE FINDINGS (STRICT LOGIC)
Generate findings FOR:
* final_status = FAIL
* final_status = PARTIAL (only if requirement_type = PRIMARY or weight = HIGH)
* ALL escalated inquiries (regardless of final_status)

8.1 FINDING CREATION RULES
* One finding per UNIQUE issue
* If multiple checklist failures relate to same root issue → combine
* Findings must be written like a professional auditor

8.2 FINDING FORMAT (STRICT)
"• [Issue Title]: It was noted that [clear description]. Specifically, [expected vs observed]. Evidence: [type and reference]. Impact: [risk]. (Severity: [computed severity])"

SUB-STEP-9 — SEVERITY ENGINE
Base severity from failure_impact:
  CRITICAL → CRITICAL, MAJOR → HIGH, SIGNIFICANT → MEDIUM, MINOR → LOW

Adjustments:
  IF final_status = PARTIAL → downgrade one level
  IF STRONG contradiction present → upgrade one level (max CRITICAL)
  IF exception_rate > 10% → minimum severity = HIGH
  IF only WEAK evidence → cap severity at MEDIUM

OUTPUT FORMAT (return exactly this):
{{
  "checklist_summary": [
    {{"checklist_id": "", "requirement": "", "final_status": "", "basis": "", "confidence": ""}}
  ],
  "observations": [
    {{"checklist_id": "", "observation_text": "", "status": ""}}
  ],
  "findings": [
    {{"finding_id": "", "checklist_id": "", "issue": "", "impact": "", "severity": "", "evidence_reference": ""}}
  ]
}}

STRICT CONSTRAINTS:
* Do NOT generate recommendations
* Do NOT ignore contradictions
* Do NOT produce vague observations or findings
* All outputs must be traceable to evidence
* All logic must be deterministic"""


def _build_step7_prompt(findings: list) -> str:
    return f"""You are an Audit Recommendation Engine.

TASK:
Generate precise, actionable recommendations for each finding.

Return ONLY valid JSON.

DO NOT:
* re-evaluate evidence
* change findings
* combine findings
* generate generic or vague recommendations

---

INPUT:
{json.dumps({{"findings": findings}}, indent=2)}

---

SUB-STEP-1 — ONE-TO-ONE MAPPING
* Generate EXACTLY one recommendation per finding
* Maintain same order as input

SUB-STEP-2 — RECOMMENDATION STRUCTURE
Each recommendation must include:
1. Corrective Action
2. Implementation Detail
3. Control Objective Alignment
4. Ownership Suggestion (role-based, not names)

SUB-STEP-3 — RECOMMENDATION WRITING RULES
* directly address the issue described in the finding
* state WHAT must be done and HOW
* avoid generic phrases like "improve", "ensure", "strengthen" without specifics
* be implementable and measurable

SUB-STEP-4 — TIMELINE DETERMINATION
CRITICAL → IMMEDIATE, HIGH → SHORT_TERM, MEDIUM → MEDIUM_TERM, LOW → LONG_TERM

SUB-STEP-5 — RECOMMENDATION FORMAT
For each finding:
{{"finding_id": "", "recommendation": "", "implementation_steps": ["", ""], "owner": "", "timeline": ""}}

SUB-STEP-6 — CONTENT GUIDELINES
6.1 CORRECTIVE ACTION: Must directly fix the issue
Example: "Obtain formal Board approval for the IT Governance Framework"

6.2 IMPLEMENTATION STEPS: 2-4 concrete steps:
* define process, assign responsibility, implement control, document evidence

6.3 OWNER (role-based):
Board / Board Committee | Senior Management | IT Function | Risk / Compliance Function | Information Security Team

SUB-STEP-7 — CONSISTENCY RULES
* Do NOT repeat wording across recommendations
* Tailor each recommendation to the specific finding
* Keep language formal, precise, and auditor-style

OUTPUT:
{{
  "recommendations": [
    {{
      "finding_id": "",
      "recommendation": "",
      "implementation_steps": [],
      "owner": "",
      "timeline": ""
    }}
  ]
}}

STRICT CONSTRAINTS:
* One finding → one recommendation (mandatory)
* No generic recommendations
* No duplication across findings
* Must be actionable and auditable"""


def _build_step8_prompt(clause_id: int, clause_text: str, control_outputs: list) -> str:
    return f"""You are an Audit Clause Aggregation Engine.

TASK:
Aggregate outputs from multiple control activities into a single clause-level result.

You must:
* consolidate observations
* merge and group findings using predefined categories
* retain full traceability
* consolidate recommendations aligned to merged findings
* determine clause-level status and severity

Return ONLY valid JSON.

DO NOT:
* re-evaluate evidence
* generate new findings
* generate new recommendations from scratch
* assume missing information

---

INPUT:
{{
  "clause_id": "{clause_id}",
  "clause_text": {json.dumps(clause_text)},
  "control_outputs": {json.dumps(control_outputs, indent=2)}
}}

---

SUB-STEP-1 — CONSOLIDATE OBSERVATIONS
* Combine all observations across controls
* Remove duplicates (semantic similarity)
* Retain evidence references
* Sequence using this order:
  1. Governance Framework & Structure
  2. Roles, Responsibilities & Accountability
  3. Oversight & Monitoring
  4. Risk Management & Control Design
  5. Implementation & Operational Effectiveness
  6. Documentation & Approval
  7. Evidence & Record Keeping
  8. Regulatory Compliance & Reporting

SUB-STEP-2 — GROUP FINDINGS INTO CONTROLLED CATEGORIES
Assign each finding to EXACTLY ONE group from the 8 categories above.
Group based on ROOT CAUSE (not symptom).
Priority: Oversight > Governance > Risk > Roles > Implementation > Documentation > Evidence > Regulatory

SUB-STEP-3 — MERGE FINDINGS
Within each group:
* Merge findings that represent the SAME underlying issue
* Do NOT merge unrelated issues
* Merged Severity = MAX(severity of grouped findings)
* Each merged finding must include source_references with control_id, checklist_id, evidence_reference

SUB-STEP-4 — CONSOLIDATE RECOMMENDATIONS
* Map recommendations to merged findings using finding_id linkage
* Combine recommendations addressing same issue
* Do NOT generate new recommendations
* Merged timeline = MOST URGENT: IMMEDIATE > SHORT_TERM > MEDIUM_TERM > LONG_TERM

SUB-STEP-5 — DETERMINE CLAUSE SEVERITY
Clause Severity = MAX(severity across all merged findings)

SUB-STEP-6 — DETERMINE CLAUSE STATUS
IF any finding severity = CRITICAL → clause_status = NON_COMPLIANT
ELSE IF any finding severity = HIGH → clause_status = PARTIALLY_COMPLIANT
ELSE → clause_status = COMPLIANT

SUB-STEP-7 — GENERATE CLAUSE SUMMARY
Write a concise paragraph: what was assessed, key strengths (if any), key issues, overall conclusion.
Tone: formal, auditor-style, evidence-based, no vague language.

OUTPUT FORMAT:
{{
  "clause_id": "{clause_id}",
  "clause_text": "",
  "clause_status": "",
  "clause_severity": "",
  "summary": "",
  "observations": [],
  "findings": [
    {{
      "finding_id": "",
      "group": "",
      "issue": "",
      "impact": "",
      "severity": "",
      "source_references": [
        {{"control_id": "", "checklist_id": "", "evidence_reference": ""}}
      ]
    }}
  ],
  "recommendations": [
    {{"finding_id": "", "recommendation": "", "implementation_steps": [], "timeline": ""}}
  ]
}}

STRICT CONSTRAINTS:
* Do NOT duplicate findings
* Do NOT lose traceability
* Do NOT weaken severity
* Do NOT introduce new issues
* Observations must remain evidence-linked
* Recommendations must map 1:1 to merged findings"""


# ─────────────────────────────────────────────────────────────
# Helper — build evidence results input for Step 6
# from EveEvidenceResult rows
# ─────────────────────────────────────────────────────────────

def _build_evidence_results_for_step6(checklist_id: int) -> list:
    """
    Fetch all EveEvidenceResult rows for a project_checklist
    and format them as Step 6 input.
    """
    results = (
        db.session.query(EveEvidenceResult)
        .filter_by(project_checklist_id=checklist_id)
        .all()
    )

    # Group by evidence_artifact_id
    evidence_map = {}
    for r in results:
        eid = r.evidence_artifact_id
        if eid not in evidence_map:
            evidence_map[eid] = {
                "evidence_id": eid,
                "evidence_type": r.evidence_type or "",
                "admissibility": r.admissibility,
                "confidence": r.confidence or "MEDIUM",
                "evidence_meta": {
                    "strength": r.evidence_strength or "MODERATE",
                    "role": r.evidence_role or "SUPPORTING",
                },
                "item_signals": [],
                "results": [],
                "sample_evaluation": {
                    "applicable": "YES" if r.sample_applicable else "NO",
                    "sample_size": r.sample_size,
                    "population_size": r.population_size,
                    "exception_rate": float(r.exception_rate) if r.exception_rate else None,
                    "within_audit_period": "YES" if r.sample_within_audit_period else "NO",
                },
            }

        evidence_map[eid]["item_signals"].append({
            "checklist_id": r.checklist_item_id,
            "signal": r.signal,
            "basis": r.signal_basis or "",
            "confidence": r.confidence or "MEDIUM",
        })
        evidence_map[eid]["results"].append({
            "checklist_id": r.checklist_item_id,
            "status": r.item_status,
            "evidence_reference": r.evidence_reference or "",
            "confidence": r.confidence or "MEDIUM",
        })

    return list(evidence_map.values())


# ─────────────────────────────────────────────────────────────
# MODULE E+F — Task: run_eve_step6_and_7
# EVE Steps 6+7 per project_control_activity
# ─────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_eve_step6_and_7(self, project_control_activity_id: int, generated_by: int = None):
    """
    Module E+F — EVE Steps 6+7:
    - Step 6: Aggregate evidence results → checklist summary, observations, findings
    - Step 7: Generate recommendations for each finding

    Stores result in eve_control_result table.

    Args:
        project_control_activity_id: ID from project_control_activities
        generated_by: User ID who triggered this (optional)
    """
    logger.info(
        f"[Module E+F] Starting Steps 6+7 for pca_id={project_control_activity_id}"
    )

    try:
        # ── 1. Load project control activity ──────────────────────────
        pca = db.session.query(ProjectControlActivity).get(project_control_activity_id)
        if not pca:
            return {"status": "error", "message": f"ProjectControlActivity {project_control_activity_id} not found"}

        # ── 2. Load project checklist ──────────────────────────────────
        checklist = (
            db.session.query(ProjectChecklist)
            .filter_by(project_control_activity_id=project_control_activity_id)
            .first()
        )
        if not checklist:
            return {"status": "error", "message": "No ProjectChecklist found — run Module B first"}

        checklist_items = checklist.get_checklist_items()
        if not checklist_items:
            return {"status": "error", "message": "ProjectChecklist has no items"}

        # ── 3. Check if Step 5 results exist ──────────────────────────
        evidence_count = (
            db.session.query(EveEvidenceResult)
            .filter_by(project_checklist_id=checklist.id)
            .count()
        )
        if evidence_count == 0:
            return {
                "status": "error",
                "message": "No Step 5 results found — run Module D (Eve Step 5) first",
                "project_control_activity_id": project_control_activity_id,
            }

        # ── 4. Get or create EveControlResult ─────────────────────────
        control_result = (
            db.session.query(EveControlResult)
            .filter_by(project_control_activity_id=project_control_activity_id)
            .first()
        )
        if not control_result:
            control_result = EveControlResult(
                project_control_activity_id=project_control_activity_id,
                project_checklist_id=checklist.id,
                generated_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                generated_by=generated_by,
            )
            db.session.add(control_result)
            db.session.flush()

        # ── 5. Build Step 6 inputs ─────────────────────────────────────
        required_dimensions = {
            "design": "YES" if checklist.dimension_design else "NO",
            "implementation": "YES" if checklist.dimension_implementation else "NO",
            "operating": "YES" if checklist.dimension_operating else "NO",
        }
        evidence_results = _build_evidence_results_for_step6(checklist.id)

        # ── Fetch escalated inquiries ──────────────────────────────────
        from app.models.eve_models import EveInquiry
        escalated_inquiries = (
            db.session.query(EveInquiry)
            .filter_by(
                project_checklist_id=checklist.id,
                status="ESCALATED_TO_FINDING"
            )
            .all()
        )
        escalated_inquiries_data = []
        for inq in escalated_inquiries:
            escalated_inquiries_data.append({
                "inquiry_id": inq.id,
                "checklist_item_id": inq.checklist_item_id,
                "contradiction_type": inq.contradiction_type,
                "severity": inq.severity,
                "inquiry_question": inq.inquiry_question,
                "evidence_a_claim": inq.evidence_a_claim,
                "evidence_b_claim": inq.evidence_b_claim,
                "escalation_reason": inq.escalation_reason,
                "auditor_response": inq.auditor_response,
            })
        logger.info(
            f"[Module E] {len(escalated_inquiries_data)} escalated inquiries "
            f"found for checklist_id={checklist.id}"
        )

        # Build Step 6 prompt with escalated inquiries
        step6_prompt = _build_step6_prompt(required_dimensions, checklist_items, evidence_results)
        step6_prompt = step6_prompt.replace(
            "{{escalated_inquiries_json}}",
            json.dumps(escalated_inquiries_data, indent=2)
        )

        # ── 6. Run Step 6 ──────────────────────────────────────────────
        logger.info(f"[Module E] Running Step 6 for pca_id={project_control_activity_id}")
        step6_output = _call_llm_json(
            system_msg=(
                "You are an Audit Aggregation and Evaluation Engine. "
                "Return ONLY valid JSON. No markdown. No explanation."
            ),
            user_msg=step6_prompt,
        )

        if not step6_output:
            raise self.retry(exc=Exception("Step 6 LLM returned no output"), countdown=60)

        checklist_summary = step6_output.get("checklist_summary", [])
        observations = step6_output.get("observations", [])
        findings = step6_output.get("findings", [])

        # Store Step 6 results
        control_result.checklist_summary_json = checklist_summary
        control_result.observations_json = observations
        control_result.findings_json = findings
        control_result.step6_completed = True
        control_result.updated_at = datetime.utcnow()
        control_result.sync_counts()
        control_result.sync_checklist_counts()
        db.session.commit()

        logger.info(
            f"[Module E] Step 6 done: {len(checklist_summary)} items, "
            f"{len(observations)} observations, {len(findings)} findings"
        )

        # ── 7. Run Step 7 (recommendations) ───────────────────────────
        if findings:
            logger.info(f"[Module F] Running Step 7 for pca_id={project_control_activity_id}")

            # Prepare findings input for Step 7
            findings_for_step7 = [
                {
                    "finding_id": f.get("finding_id", ""),
                    "checklist_id": f.get("checklist_id", ""),
                    "issue": f.get("issue", ""),
                    "impact": f.get("impact", ""),
                    "severity": f.get("severity", "MEDIUM"),
                }
                for f in findings
            ]

            step7_output = _call_llm_json(
                system_msg=(
                    "You are an Audit Recommendation Engine. "
                    "Return ONLY valid JSON. No markdown. No explanation."
                ),
                user_msg=_build_step7_prompt(findings_for_step7),
            )

            if not step7_output:
                logger.warning(
                    f"[Module F] Step 7 LLM returned no output for pca_id={project_control_activity_id} "
                    f"— recommendations will be empty"
                )
                recommendations = []
            else:
                recommendations = step7_output.get("recommendations", [])

            control_result.recommendations_json = recommendations
            control_result.step7_completed = True
            control_result.updated_at = datetime.utcnow()
            db.session.commit()

            logger.info(f"[Module F] Step 7 done: {len(recommendations)} recommendations")
        else:
            # No findings — no recommendations needed
            control_result.recommendations_json = []
            control_result.step7_completed = True
            control_result.updated_at = datetime.utcnow()
            db.session.commit()
            logger.info(f"[Module F] No findings — Step 7 skipped cleanly")

        # ── 8. Determine final_status and final_severity ───────────────
        final_status, final_severity = _compute_control_status(findings)
        control_result.final_status = final_status
        control_result.final_severity = final_severity
        control_result.updated_at = datetime.utcnow()
        db.session.commit()

        logger.info(
            f"[Module E+F] Steps 6+7 complete for pca_id={project_control_activity_id}: "
            f"status={final_status}, severity={final_severity}"
        )

        return {
            "status": "success",
            "project_control_activity_id": project_control_activity_id,
            "final_status": final_status,
            "final_severity": final_severity,
            "checklist_items": len(checklist_summary),
            "observations": len(observations),
            "findings": len(findings),
            "recommendations": len(control_result.recommendations_json or []),
        }

    except self.MaxRetriesExceededError:
        return {"status": "error", "message": "Max retries exceeded", "project_control_activity_id": project_control_activity_id}
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module E+F] DB error: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module E+F] Unexpected error: {e}")
        return {"status": "error", "message": str(e), "project_control_activity_id": project_control_activity_id}


def _compute_control_status(findings: list) -> tuple[str, str | None]:
    """
    Deterministic rule — compute final_status and final_severity from findings.
    Matches EVE v2 Step 6 Sub-step 9 severity rules.
    """
    if not findings:
        return "COMPLIANT", None

    severities = [f.get("severity", "LOW") for f in findings]
    severity_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    max_sev = max(severities, key=lambda s: severity_order.get(s, 0))

    if max_sev == "CRITICAL":
        return "NON_COMPLIANT", "CRITICAL"
    elif max_sev == "HIGH":
        return "PARTIALLY_COMPLIANT", "HIGH"
    elif max_sev == "MEDIUM":
        return "PARTIALLY_COMPLIANT", "MEDIUM"
    else:
        return "PARTIALLY_COMPLIANT", "LOW"


# ─────────────────────────────────────────────────────────────
# MODULE G — Task: run_eve_step8_clause_rollup
# EVE Step 8 per project_clause
# ─────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def run_eve_step8_clause_rollup(self, project_clause_id: int, generated_by: int = None):
    """
    Module G — EVE Step 8: Aggregate all control activity results
    under a clause into a single clause-level result.

    Stores clause_rollup_json in each EveControlResult under this clause.

    Args:
        project_clause_id: ID from project_clauses table
        generated_by: User ID who triggered this (optional)
    """
    logger.info(f"[Module G] Starting Step 8 for project_clause_id={project_clause_id}")

    try:
        # ── 1. Load project clause ─────────────────────────────────────
        project_clause = db.session.query(ProjectClause).get(project_clause_id)
        if not project_clause:
            return {"status": "error", "message": f"ProjectClause {project_clause_id} not found"}

        # ── 2. Get clause text from master clauses table ───────────────
        clause_text = ""
        if project_clause.original_clause_id:
            original = db.session.query(Clauses).get(project_clause.original_clause_id)
            if original:
                clause_text = getattr(original, "clause_text", "") or ""

        # ── 3. Get all PCAs under this project clause ──────────────────
        pcas = (
            db.session.query(ProjectControlActivity)
            .join(
                ProjectComplianceActivity,
                ProjectControlActivity.project_compliance_activity_id == ProjectComplianceActivity.id,
            )
            .filter(ProjectComplianceActivity.project_clause_id == project_clause_id)
            .all()
        )

        if not pcas:
            return {
                "status": "error",
                "message": "No control activities found under this clause",
                "project_clause_id": project_clause_id,
            }

        # ── 4. Check all Steps 6+7 are done ───────────────────────────
        pca_ids = [pca.id for pca in pcas]
        control_results = (
            db.session.query(EveControlResult)
            .filter(EveControlResult.project_control_activity_id.in_(pca_ids))
            .all()
        )

        completed_ids = {cr.project_control_activity_id for cr in control_results if cr.step7_completed}
        pending = [pid for pid in pca_ids if pid not in completed_ids]

        if pending:
            logger.warning(
                f"[Module G] {len(pending)} control activities still pending Steps 6+7: {pending}"
            )
            return {
                "status": "pending",
                "message": f"{len(pending)} control activities not yet completed Steps 6+7",
                "pending_pca_ids": pending,
                "project_clause_id": project_clause_id,
            }

        # ── 5. Build control_outputs for Step 8 ───────────────────────
        control_outputs = []
        for cr in control_results:
            control_outputs.append({
                "control_id": cr.project_control_activity_id,
                "observations": cr.observations_json or [],
                "findings": cr.findings_json or [],
                "recommendations": cr.recommendations_json or [],
            })

        if not control_outputs:
            return {"status": "error", "message": "No control results to aggregate"}

        # ── 6. Run Step 8 ──────────────────────────────────────────────
        logger.info(f"[Module G] Running Step 8 for project_clause_id={project_clause_id}")
        step8_output = _call_llm_json(
            system_msg=(
                "You are an Audit Clause Aggregation Engine. "
                "Return ONLY valid JSON. No markdown. No explanation."
            ),
            user_msg=_build_step8_prompt(
                clause_id=project_clause_id,
                clause_text=clause_text or "Not available",
                control_outputs=control_outputs,
            ),
        )

        if not step8_output:
            raise self.retry(exc=Exception("Step 8 LLM returned no output"), countdown=60)

        # ── 7. Store clause_rollup_json in ALL control results ─────────
        for cr in control_results:
            cr.clause_rollup_json = step8_output
            cr.step8_completed = True
            cr.updated_at = datetime.utcnow()

        db.session.commit()

        clause_status = step8_output.get("clause_status", "")
        clause_severity = step8_output.get("clause_severity", "")
        findings_count = len(step8_output.get("findings", []))
        recommendations_count = len(step8_output.get("recommendations", []))

        logger.info(
            f"[Module G] Step 8 complete for project_clause_id={project_clause_id}: "
            f"status={clause_status}, severity={clause_severity}, "
            f"findings={findings_count}, recommendations={recommendations_count}"
        )

        return {
            "status": "success",
            "project_clause_id": project_clause_id,
            "clause_status": clause_status,
            "clause_severity": clause_severity,
            "findings_count": findings_count,
            "recommendations_count": recommendations_count,
            "controls_aggregated": len(control_results),
        }

    except self.MaxRetriesExceededError:
        return {"status": "error", "message": "Max retries exceeded", "project_clause_id": project_clause_id}
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"[Module G] DB error: {e}")
        raise self.retry(exc=e, countdown=30)
    except Exception as e:
        db.session.rollback()
        logger.error(f"[Module G] Unexpected error: {e}")
        return {"status": "error", "message": str(e), "project_clause_id": project_clause_id}
