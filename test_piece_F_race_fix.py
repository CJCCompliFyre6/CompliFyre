"""Create a fresh ALM guideline copy, run extract_clauses, then run
generate_missing_activities_for_guideline to verify Piece F's race-condition
fix — no duplicate activity batches should be created this time."""
from run import app
from app.models.ai import Guidelines
from app.services.manual_task import extract_clauses
from app import db

with app.app_context():
    old_g = Guidelines.query.get(200)  # ALM, has confirmed structure_map
    sm = old_g.structure_map
    new_data = dict(old_g.guideline_data or {})
    if "DocumentDetails" in new_data and isinstance(new_data["DocumentDetails"], dict):
        new_data["DocumentDetails"] = dict(new_data["DocumentDetails"])
        orig_name = new_data["DocumentDetails"].get("DocumentName", "ALM")
        new_data["DocumentDetails"]["DocumentName"] = f"{orig_name} [piece-F race-condition retest]"

    new_g = Guidelines(
        guideline_data=new_data,
        file_id=228,
        applicable_licenses=old_g.applicable_licenses,
        structure_map=sm,
    )
    db.session.add(new_g)
    db.session.commit()
    NEW_GID = new_g.id
    print("NEW guideline_id:", NEW_GID)

    extract_clauses.delay(NEW_GID)
    print(f"extract_clauses queued for guideline_id={NEW_GID}")
    print(f"Once extraction succeeds, run: generate_missing_activities_for_guideline.delay({NEW_GID})")
