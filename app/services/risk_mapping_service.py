"""
Risk-mapping service for the RCM (Risk Control Matrix) feature.
Build Sequence #372.

Generates the risk-area mapping for a single ControlActivity, using its
existing activity_description and objective fields as input against the
seeded risk taxonomy. Never trusts free-text risk-area names from the LLM
as final -- matches them back against the real, seeded RiskArea rows by
exact name, and silently drops (with a log warning) anything that doesn't
match, rather than creating orphaned or misspelled mappings.
"""
import logging

logger = logging.getLogger(__name__)


def generate_risk_mapping_for_control(control_activity_id: int) -> dict:
    from app import db
    from app.models.ai import ControlActivity, RiskCategory, RiskArea, ControlRiskMapping
    from app.services.model_response import _call_llm_json_raw
    from app.services.prompt_templates.risk_mapping import (
        RISK_MAPPING_SYSTEM,
        build_risk_taxonomy_text,
        risk_mapping_prompt,
    )

    control = ControlActivity.query.get(control_activity_id)
    if not control:
        return {"status": "error", "message": f"ControlActivity {control_activity_id} not found"}

    activity_description = control.activity_description or ""
    objective = control.objective or ""
    if not activity_description:
        return {"status": "error", "message": "Control has no activity_description to map from"}

    categories = RiskCategory.query.order_by(RiskCategory.display_order).all()
    categories_with_areas = [
        (cat.name, [(ra.name, ra.description or "") for ra in cat.risk_areas])
        for cat in categories
    ]
    valid_risk_area_names = {
        ra.name: ra.id for cat in categories for ra in cat.risk_areas
    }

    taxonomy_text = build_risk_taxonomy_text(categories_with_areas)
    prompt = risk_mapping_prompt(activity_description, objective, taxonomy_text)

    result = _call_llm_json_raw(system_msg=RISK_MAPPING_SYSTEM, user_msg=prompt)
    if not result or not result.get("mappings"):
        logger.warning(f"[RiskMapping] No mappings returned for control_activity_id={control_activity_id}")
        return {"status": "error", "message": "LLM returned no mappings", "control_activity_id": control_activity_id}

    # Clear any existing mappings for this control before saving fresh ones
    ControlRiskMapping.query.filter_by(control_activity_id=control_activity_id).delete()

    saved = 0
    skipped = []
    for m in result.get("mappings", []):
        risk_area_name = m.get("risk_area", "")
        rationale = m.get("rationale", "")
        risk_area_id = valid_risk_area_names.get(risk_area_name)
        if risk_area_id is None:
            skipped.append(risk_area_name)
            continue
        db.session.add(ControlRiskMapping(
            control_activity_id=control_activity_id,
            risk_area_id=risk_area_id,
            rationale=rationale,
        ))
        saved += 1

    db.session.commit()

    if skipped:
        logger.warning(f"[RiskMapping] control_activity_id={control_activity_id}: skipped {len(skipped)} non-matching risk area name(s): {skipped}")

    return {
        "status": "success",
        "control_activity_id": control_activity_id,
        "mappings_saved": saved,
        "mappings_skipped": len(skipped),
    }


from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_rcm_for_guideline(self, guideline_id: int, generated_by: int = None):
    """
    Bulk-dispatch risk-mapping generation for every control activity in a
    guideline, skipping any that already have mappings (same idempotent
    pattern as generate_control_checklist). Build Sequence #372.
    """
    from app import db
    from app.models.ai import Clauses, ControlRiskMapping

    logger.info(f"[RCM] Starting bulk risk-mapping generation for guideline_id={guideline_id}")

    clauses = Clauses.query.filter_by(guideline_id=guideline_id).all()
    total_processed = 0
    total_skipped_existing = 0
    total_errors = 0
    total_mappings_saved = 0

    for clause in clauses:
        for activity in clause.compliance_activities:
            for control in activity.control_activities:
                existing = ControlRiskMapping.query.filter_by(control_activity_id=control.id).first()
                if existing:
                    total_skipped_existing += 1
                    continue
                try:
                    result = generate_risk_mapping_for_control(control.id)
                    if result.get("status") == "success":
                        total_processed += 1
                        total_mappings_saved += result.get("mappings_saved", 0)
                    else:
                        total_errors += 1
                        logger.warning(f"[RCM] control_activity_id={control.id}: {result.get('message')}")
                except Exception as e:
                    total_errors += 1
                    logger.error(f"[RCM] control_activity_id={control.id} failed: {e}")

    logger.info(
        f"[RCM] Bulk generation complete for guideline_id={guideline_id}: "
        f"{total_processed} controls processed, {total_mappings_saved} mappings saved, "
        f"{total_skipped_existing} already had mappings, {total_errors} errors"
    )

    return {
        "status": "success",
        "guideline_id": guideline_id,
        "controls_processed": total_processed,
        "mappings_saved": total_mappings_saved,
        "already_mapped_skipped": total_skipped_existing,
        "errors": total_errors,
    }
