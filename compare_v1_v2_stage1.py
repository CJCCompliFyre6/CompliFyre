"""
Loads v1 (backup, verified 315/164-working) and v2 (current) source of
pdf_structure_parser.py via exec() into separate namespaces, runs Stage 1 on
the SAME ALM PDF with the SAME structure_map, and diffs results in-memory.
No DB, no Celery, no LLM calls.
"""

def load_as_module(path, mod_name):
    with open(path) as f:
        source = f.read()
    ns = {"__name__": mod_name, "__file__": path}
    exec(compile(source, path, "exec"), ns)
    return ns

old_ns = load_as_module("app/services/pdf_structure_parser.py.ambigv2.bak", "pdf_structure_parser_v1")
new_ns = load_as_module("app/services/pdf_structure_parser.py", "pdf_structure_parser_v2")

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
pdf_path = "master circular ALM.pdf"

print("Running OLD (v1)...")
old_nodes = old_ns["parse_pdf_structure"](pdf_path, structure_map=structure_map)
print("Running NEW (v2)...")
new_nodes = new_ns["parse_pdf_structure"](pdf_path, structure_map=structure_map)

old_texts = {n['clause_no']: n['raw_text'] for n in old_nodes}
new_texts = {n['clause_no']: n['raw_text'] for n in new_nodes}

print(f"\nold node count: {len(old_nodes)}  new node count: {len(new_nodes)}")
print("Missing in new (present in old, gone in new):", sorted(set(old_texts) - set(new_texts)))
print("New in new (not in old):", sorted(set(new_texts) - set(old_texts)))

diffs = [k for k in old_texts if k in new_texts and old_texts[k] != new_texts[k]]
print(f"\nCommon clause_nos with DIFFERENT text ({len(diffs)}):")
for k in diffs[:10]:
    print(f"  {k}")
    print(f"    OLD: {old_texts[k][:150]}")
    print(f"    NEW: {new_texts[k][:150]}")

print("\n=== Now running validate_nodes() on both ===")
old_valid, old_issues = old_ns["validate_nodes"](old_nodes)
new_valid, new_issues = new_ns["validate_nodes"](new_nodes)
print(f"old valid_nodes: {len(old_valid)}  issues: {len(old_issues)}")
print(f"new valid_nodes: {len(new_valid)}  issues: {len(new_issues)}")
old_valid_set = set(n['clause_no'] for n in old_valid)
new_valid_set = set(n['clause_no'] for n in new_valid)
print("Missing after validate_nodes (in old, not new):", sorted(old_valid_set - new_valid_set))
print("New after validate_nodes (in new, not old):", sorted(new_valid_set - old_valid_set))
