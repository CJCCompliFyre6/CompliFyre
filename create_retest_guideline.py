from run import app
from app.models.download import File
from app.models.ai import Guidelines
from app import db
import os

with app.app_context():
    pdf_path = os.path.abspath('master circular ALM.pdf')
    file_rec = File(path=pdf_path, size=os.path.getsize(pdf_path))
    db.session.add(file_rec)
    db.session.commit()

    structure_map = {
      'confirmed': True,
      'sections': [
        {'type': 'chapter', 'id': 'I', 'label': 'Preliminary', 'start_page': 3, 'end_page': 5},
        {'type': 'chapter', 'id': 'II', 'label': 'Liquidity Risk Management Framework', 'start_page': 6, 'end_page': 16},
        {'type': 'chapter', 'id': 'III', 'label': 'Liquidity Coverage Ratio', 'start_page': 17, 'end_page': 24},
        {'type': 'chapter', 'id': 'IV', 'label': 'Repeal and Other Provisions', 'start_page': 25, 'end_page': 26},
        {'type': 'annexure', 'id': 'I', 'label': 'Public disclosure on liquidity risk', 'start_page': 27, 'end_page': 27},
        {'type': 'annexure', 'id': 'II', 'label': 'Maturity Profile - Liquidity', 'start_page': 28, 'end_page': 32},
        {'type': 'annexure', 'id': 'III', 'label': 'Interest Rate Sensitivity', 'start_page': 33, 'end_page': 35},
        {'type': 'annexure', 'id': 'IV', 'label': 'Formats for Returns', 'start_page': 36, 'end_page': 41}
      ]
    }
    g = Guidelines(
        guideline_data={'Regulator': 'RBI', 'DocumentDetails': {'DocumentName': 'RBI NBFC ALM Directions 2025 - superscript fix retest'}},
        file_id=file_rec.id,
        applicable_licenses=['RBI_NBFC_ICC', 'RBI_NBFC_MFI', 'RBI_NBFC_IFC', 'RBI_NBFC_HFC', 'RBI_NBFC_SI', 'RBI_MNBC'],
        structure_map=structure_map,
    )
    db.session.add(g)
    db.session.commit()
    print('NEW guideline_id:', g.id)
