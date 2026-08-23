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

    print("=== Find CH III 8 (the FTP-minimums table intro) and everything on the same page ===", flush=True)
    ch3_8 = next((n for n in nodes if n.get('clause_no') == 'CH III 8'), None)
    if ch3_8:
        print("CH_III_8_PAGE=" + str(ch3_8.get('page_number')), flush=True)
        target_page = ch3_8.get('page_number')
        print(flush=True)
        print("=== All nodes on that same page ===", flush=True)
        for n in nodes:
            if n.get('page_number') == target_page:
                print(f"clause_no={n.get('clause_no')!r} | node_type={n.get('node_type')} | text={n.get('raw_text','')[:100]!r}", flush=True)
    else:
        print("CH_III_8_NOT_FOUND_BY_THAT_EXACT_NUMBER", flush=True)
