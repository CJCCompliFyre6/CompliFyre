from dotenv import load_dotenv
load_dotenv()
import os, sys
from app import create_app

app = create_app(os.getenv('FLASK_ENV', 'development'))

with app.app_context():
    from app.models import Guidelines, File
    from app.services.pdf_structure_parser import parse_pdf_structure

    guideline = Guidelines.query.get(241)
    file_record = File.query.get(guideline.file_id)
    print("REAL_FILE_PATH=" + str(file_record.path), flush=True)

    print("PARSING_NOW (read-only, does not touch the database)...", flush=True)
    nodes = parse_pdf_structure(file_record.path, structure_map=guideline.structure_map)
    print("TOTAL_NODES=" + str(len(nodes)), flush=True)

    print(flush=True)
    print("=== All nodes whose text mentions 'Asset Size' or clause_no starts with CH III (the relevant table area) ===", flush=True)
    for n in nodes:
        cno = n.get('clause_no', '')
        text = n.get('raw_text', '')
        if cno.startswith('CH III') and (len(cno) <= 9):  # CH III <= 2 digits, catches both broken fragments and ROW entries
            print(f"clause_no={cno!r} | node_type={n.get('node_type')} | text={text[:150]!r}", flush=True)
