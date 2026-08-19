"""Check if the number-dropping already exists in Stage 1 (raw parser output),
before Stage 2 LLM touches anything — isolates root cause."""
from app.services.pdf_structure_parser import parse_pdf_structure

structure_map = {
  "confirmed": True,
  "sections": [
    {"type": "chapter", "id": "I", "label": "Preliminary", "start_page": 3, "end_page": 5},
    {"type": "chapter", "id": "II", "label": "Liquidity Risk Management Framework", "start_page": 6, "end_page": 16},
    {"type": "chapter", "id": "III", "label": "Liquidity Coverage Ratio", "start_page": 17, "end_page": 24},
    {"type": "chapter", "id": "IV", "label": "Repeal and Other Provisions", "start_page": 25, "end_page": 26},
    {"type": "annexure", "id": "I", "label": "Public disclosure on liquidity risk", "start_page": 27, "end_page": 27},
    {"type": "annexure", "id": "II", "label": "Maturity Profile - Liquidity", "start_page": 28, "end_page": 32},
    {"type": "annexure", "id": "III", "label": "Interest Rate Sensitivity", "start_page": 33, "end_page": 35},
    {"type": "annexure", "id": "IV", "label": "Formats for Returns", "start_page": 36, "end_page": 41}
  ]
}

pdf_path = "master circular ALM.pdf"  # adjust if the actual scp'd filename differs
nodes = parse_pdf_structure(pdf_path, structure_map=structure_map)

# Find the raw node(s) that should contain the LCR-100% clause (CH III 62 in final DB)
for n in nodes:
    if n.get('clause_no', '').startswith('CH III') and ('LCR' in n.get('raw_text', '') and 'minimum' in n.get('raw_text', '')):
        print("=== RAW STAGE-1 TEXT ===")
        print(n.get('clause_no'), "|", n.get('raw_text'))
        print()

# Also dump anything with "per cent" to eyeball
print("=== ALL 'per cent' occurrences in Stage 1 raw nodes ===")
for n in nodes:
    text = n.get('raw_text', '')
    if 'per cent' in text:
        print(n.get('clause_no'), "|", text[:200])
