"""
Lightweight, read-only regression check for the superscript-fix.
No DB writes, no LLM calls, no Celery — just re-reads each PDF's raw text
and runs the new strip_page_noise()/collect_footnote_numbers() against it,
to confirm: (a) numeric content isn't being silently dropped, and
(b) genuine footnote markers still get detected/stripped where they exist.
"""
import re
from run import app
from app.models.ai import Guidelines
from app.models.download import File
from app.services.pdf_structure_parser import PATTERNS, strip_page_noise, collect_footnote_numbers
import pdfplumber

CANDIDATES_SKIPPED = [
    (158, "Credit Facilities (Commercial Banks) 2025 - Updated Apr 2026"),
    (187, "Credit Facilities (NBFC) 2025"),
    (148, "KYC Master Direction 2016"),
    (176, "MNBC Directions 2016"),
    (173, "Public Deposits Acceptance MNBC 2016"),
    (169, "Outsourcing IT Directions 2023"),
    (168, "IT Governance Directions 2023"),
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
    (188, "SEBI LODR 2015"),
]

digit_percent_pattern = re.compile(r'\d+\s*per\s*cent', re.IGNORECASE)

with app.app_context():
    for gid, label in CANDIDATES_SKIPPED:
        g = Guidelines.query.get(gid)
        if not g or not g.file_id:
            print(f"{gid} | {label} | SKIP - no file_id on guideline")
            continue
        f = File.query.get(g.file_id)
        if not f or not f.path:
            print(f"{gid} | {label} | SKIP - no path on file record")
            continue
        try:
            pdf = pdfplumber.open(f.path)
        except Exception as e:
            print(f"{gid} | {label} | ERROR opening PDF ({f.path}): {e}")
            continue

        footnote_numbers = collect_footnote_numbers(pdf)

        raw_digit_pct = 0
        clean_digit_pct = 0
        stripped_examples = []
        preserved_examples = []

        for page in pdf.pages:
            raw_text = page.extract_text() or ''
            raw_digit_pct += len(digit_percent_pattern.findall(raw_text))

            clean_text = strip_page_noise(raw_text, footnote_numbers)
            clean_digit_pct += len(digit_percent_pattern.findall(clean_text))

            for m in PATTERNS['superscript'].finditer(raw_text):
                digit = m.group(0).strip()
                ctx = raw_text[max(0, m.start()-20):m.end()+15].replace('\n', ' ')
                if digit in footnote_numbers and len(stripped_examples) < 3:
                    stripped_examples.append(ctx)
                elif digit not in footnote_numbers and len(preserved_examples) < 3:
                    preserved_examples.append(ctx)

        status = "OK" if clean_digit_pct >= raw_digit_pct else "!! NUMBER LOSS DETECTED !!"
        print(f"\n=== {gid} | {label} ===")
        print(f"  footnotes_detected={len(footnote_numbers)} {sorted(footnote_numbers)[:15]}")
        print(f"  raw 'digit per cent' count={raw_digit_pct}  clean count={clean_digit_pct}  -> {status}")
        print(f"  sample STRIPPED (confirmed footnote): {stripped_examples}")
        print(f"  sample PRESERVED (content, left alone): {preserved_examples}")
        pdf.close()
