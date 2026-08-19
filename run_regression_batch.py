"""
Creates a fresh copy of each candidate guideline (reusing its existing PDF
file + already-confirmed structure_map) and triggers extract_clauses on the
NEW id — so the original/live records are never touched. Prints an
old_id -> new_id mapping table at the end for UI-checking.
"""
from run import app
from app.models.ai import Guidelines
from app.services.manual_task import extract_clauses
from app import db

CANDIDATES = [
    (158, "Credit Facilities (Commercial Banks) 2025 - Updated Apr 2026"),
    (187, "Credit Facilities (NBFC) 2025"),
    (148, "KYC Master Direction 2016"),
    (176, "MNBC Directions 2016"),
    (173, "Public Deposits Acceptance MNBC 2016"),
    (169, "Outsourcing IT Directions 2023"),
    (168, "IT Governance Directions 2023"),
    (200, "ALM Directions 2025 (original G200)"),
    (175, "Digital Lending Directions 2025"),
    (174, "MSME Master Direction"),
    (181, "Statutory Audit Directions 2026"),
    (178, "Auditor's Report Directions 2026"),
    (180, "Supervisory Returns Directions 2026"),
    (182, "Internal Audit Function Directions 2026"),
    (183, "Fraud Risk Management Directions 2026"),
    (185, "Compliance Function Directions 2026"),
    (186, "Internal Ombudsman Directions 2026"),
    (177, "Cybersecurity Framework Directions 2026"),
    (184, "Digital Payment Security Controls 2026"),
    (201, "Master Circulars - Misc Instructions to NBFCs"),
    (188, "SEBI LODR 2015"),
]

with app.app_context():
    results = []
    for old_id, label in CANDIDATES:
        old_g = Guidelines.query.get(old_id)
        if not old_g:
            results.append((old_id, None, label, "SKIPPED - old guideline_id not found"))
            continue
        sm = old_g.structure_map
        if not sm or not sm.get("confirmed"):
            results.append((old_id, None, label, "SKIPPED - no confirmed structure_map on original"))
            continue
        if not old_g.file_id:
            results.append((old_id, None, label, "SKIPPED - no file_id on original"))
            continue

        new_data = dict(old_g.guideline_data or {})
        # tag the copy clearly so it's obvious in the UI which is which
        if "DocumentDetails" in new_data and isinstance(new_data["DocumentDetails"], dict):
            new_data["DocumentDetails"] = dict(new_data["DocumentDetails"])
            orig_name = new_data["DocumentDetails"].get("DocumentName", label)
            new_data["DocumentDetails"]["DocumentName"] = f"{orig_name} [superscript-fix regression retest]"
        else:
            new_data["_regression_retest_of"] = old_id

        new_g = Guidelines(
            guideline_data=new_data,
            file_id=old_g.file_id,
            applicable_licenses=old_g.applicable_licenses,
            structure_map=sm,
        )
        db.session.add(new_g)
        db.session.commit()
        results.append((old_id, new_g.id, label, "QUEUED"))
        extract_clauses.delay(new_g.id)

    print("\n=== old_id | new_id | label | status ===")
    for old_id, new_id, label, status in results:
        print(f"{old_id} | {new_id} | {label} | {status}")
