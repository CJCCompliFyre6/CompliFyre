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

    print("=== Is there ANY 'CH III 8 ROW' entry now? (the table that previously had no detected rows) ===", flush=True)
    found = [n for n in nodes if 'CH III 8' in n.get('clause_no','') and 'ROW' in n.get('clause_no','')]
    print("FOUND_COUNT=" + str(len(found)), flush=True)
    for n in found:
        print(n.get('clause_no'), '|', n.get('raw_text','')[:100], flush=True)

    print(flush=True)
    print("=== Does the broken CH III 18-style fragment still appear? ===", flush=True)
    for n in nodes:
        if n.get('clause_no') == 'CH III 18':
            print(f"clause_no={n.get('clause_no')!r} | node_type={n.get('node_type')} | text={n.get('raw_text','')[:150]!r}", flush=True)
