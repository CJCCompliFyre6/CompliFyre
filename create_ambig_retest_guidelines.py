"""Create fresh guideline copies of ALM and Misc Instructions to test the
font-size + registry ambiguity-aware superscript fix.
ALM uses our own known-good file_id (228) since guideline 200's original
file_id points to a PDF that doesn't exist on this VM's disk."""
from run import app
from app.models.ai import Guidelines
from app.services.manual_task import extract_clauses
from app import db

# (source_guideline_id_for_structure_map, override_file_id_or_None, label)
CANDIDATES = [
    (200, 228, "ALM Directions 2025"),           # reuse our own uploaded file
    (201, None, "Misc Instructions to NBFCs"),   # original file_id (227) exists on disk
]

with app.app_context():
    results = []
    for old_id, override_file_id, label in CANDIDATES:
        old_g = Guidelines.query.get(old_id)
        if not old_g:
            results.append((old_id, None, label, "SKIPPED - not found"))
            continue
        sm = old_g.structure_map
        file_id = override_file_id or old_g.file_id
        new_data = dict(old_g.guideline_data or {})
        if "DocumentDetails" in new_data and isinstance(new_data["DocumentDetails"], dict):
            new_data["DocumentDetails"] = dict(new_data["DocumentDetails"])
            orig_name = new_data["DocumentDetails"].get("DocumentName", label)
            new_data["DocumentDetails"]["DocumentName"] = f"{orig_name} [ambiguity-fix retest]"

        new_g = Guidelines(
            guideline_data=new_data,
            file_id=file_id,
            applicable_licenses=old_g.applicable_licenses,
            structure_map=sm,
        )
        db.session.add(new_g)
        db.session.commit()
        results.append((old_id, new_g.id, label, f"QUEUED (file_id={file_id})"))
        extract_clauses.delay(new_g.id)

    print("\n=== old_id | new_id | label | status ===")
    for old_id, new_id, label, status in results:
        print(f"{old_id} | {new_id} | {label} | {status}")
