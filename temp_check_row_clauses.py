from dotenv import load_dotenv
load_dotenv()
import os
from app import create_app

app = create_app(os.getenv('FLASK_ENV', 'development'))

with app.app_context():
    from app.models import Guidelines, File
    from app.services.pdf_structure_parser import parse_pdf_structure

    guideline = Guidelines.query.get(241)
    file_record = File.query.get(guideline.file_id)
    nodes = parse_pdf_structure(file_record.path, structure_map=guideline.structure_map)

    print("=== Confirm the correct ROW-style table clauses are still present and correct ===", flush=True)
    for n in nodes:
        cno = n.get('clause_no', '')
        if 'ROW' in cno and cno.startswith('CH III'):
            print(f"clause_no={cno!r} | node_type={n.get('node_type')} | text={n.get('raw_text','')[:150]!r}", flush=True)
