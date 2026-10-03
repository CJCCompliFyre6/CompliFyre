"""
CompliFyre — Stage 1: PDF Structure Parser
==========================================
Algorithmic structure detection for regulatory documents (SEBI, RBI, IRDAI etc.)
"""

import re
import logging
import pdfplumber
import fitz

logger = logging.getLogger(__name__)

LAST_DROPPED_LINES = []  # #128: filled by parse_pdf_structure for diagnostics
LAST_REATTACHED = 0

PATTERNS = {
    'chapter':              re.compile(r'^(CHAPTER|Chapter)\s+([IVXLCDM]+)\b'),
    'schedule':             re.compile(r'^(SCHEDULE|Schedule)\s+([IVXLCDM]+|\d+)\b'),
    'annexure':             re.compile(r'^(ANNEXURE|Annexure|ANNEX|Annex)\s+([A-Z]|\d+)\b'),
    'part':                 re.compile(r'^(PART|Part)\s+([A-Z])\b'),
    'regulation_solo':      re.compile(r'^\s{0,4}(\d{1,3}[A-Z]?)\.\s*$'),
    'regulation_inline':    re.compile(r'^\s{0,4}(\d{1,3}[A-Z]?)\.\s+\S'),
    'regulation_dotless':   re.compile(r'^(\d{1,3})\s+[A-Z\u2018\u201C(]'),
    'regulation_solo_dotless': re.compile(r'^\s{0,4}(\d{1,3})\s*$'),
    'sub_reg':              re.compile(r'^\s{0,8}\((\d+[A-Z]{0,3})\)\s+\S'),
    'clause':               re.compile(r'^\s{3,12}\(([a-z]{1,3})\)\s+\S'),
    'sub_clause':           re.compile(r'^\s{6,16}\(([ivxlcdm]+)\)\s+\S'),
    'capital':              re.compile(r'^\s{10,24}\(([A-Z])\)\s+\S'),
    'numbered_deep':        re.compile(r'^\s{14,28}\((\d+)\)\s+\S'),
    'letter_para':          re.compile(r'^\s{0,4}([A-Z])\.\s+\S'),
    'proviso':              re.compile(r'^\s*Provided\s+(that|further\s+that)', re.IGNORECASE),
    'explanation':          re.compile(r'^\s*Explanation\s*[\(\d\-\u2013]', re.IGNORECASE),
    'footnote_ref_inline':  re.compile(r'\b\d+\[([^\]]+)\]'),
    'footnote_block':       re.compile(r'^\d+\.?\s+(Inserted|Substituted|Omitted|Added|Prior to (?:its |the )?(?:amendment|substitution|insertion|omission|deletion)|Deleted)\s+', re.IGNORECASE),
    'omitted':              re.compile(r'\[\s*\*{2,}\s*\]'),
    'cross_ref_tag':        re.compile(r'\[See\s+[^\]]+\]', re.IGNORECASE),
    'page_number':          re.compile(r'^\s*\d{1,4}\s*$'),
    'gazette_header':       re.compile(r'^(GAZETTE OF INDIA|EXTRAORDINARY|PUBLISHED BY AUTHORITY|THE GAZETTE)', re.IGNORECASE),
    'appendix':             re.compile(r'^(APPENDIX|Appendix|LIST OF CIRCULARS|List of Circulars)', re.IGNORECASE),
    'superscript':          re.compile(r'(?<=\w)\s+\d+(?=\s+[a-z\(\[])'),
}


def empty_position():
    return {
        'chapter': None, 'schedule': None, 'annexure': None, 'part': None,
        'module': None,
        'regulation': None, 'sub_reg': None, 'clause': None,
        'sub_clause': None, 'capital': None, 'numbered_deep': None,
        'proviso_count': 0, 'explanation_count': 0,
        'current_section': None, 'pending_reg': None,
        'letter_para': None,
    }


def build_clause_no(pos):
    parts = []
    if pos['current_section'] == 'chapter' and pos['chapter']:
        parts.append(f"CH {pos['chapter']}")
    elif pos['current_section'] == 'schedule' and pos['schedule']:
        parts.append(f"SCH {pos['schedule']}")
        if pos['part']:
            parts.append(pos['part'])
    elif pos['current_section'] == 'annexure' and pos['annexure']:
        parts.append(f"ANN {pos['annexure']}")
    elif pos['current_section'] == 'module' and pos['module']:
        parts.append(f"MOD {pos['module']}")
    elif pos['current_section'] == 'main_body':
        pass  # no prefix — bare numbers stand alone
    else:
        return None
    if pos['letter_para']:
        parts.append(pos['letter_para'])
        return ' '.join(parts)
    if pos['regulation']:
        parts.append(pos['regulation'])
    if pos['sub_reg']:
        parts.append(f"({pos['sub_reg']})")
    if pos['clause']:
        parts.append(f"({pos['clause']})")
    if pos['sub_clause']:
        parts.append(f"({pos['sub_clause']})")
    if pos['capital']:
        parts.append(f"({pos['capital']})")
    if pos['numbered_deep']:
        parts.append(f"({pos['numbered_deep']})")
    return ' '.join(parts) if parts else None



def _reg_ok(position, reg_no, max_jump):
    """PARA-SEQ: accept a new paragraph number only if it moves forward in sequence within the current
    chapter/section (27 -> 28, 27 -> 27A, up to max_jump ahead). A different chapter/section allows any number."""
    import re as _r
    tmp = dict(position)
    for _l in ('regulation', 'sub_reg', 'clause', 'sub_clause', 'capital', 'numbered_deep', 'pending_reg'):
        tmp[_l] = None
    try:
        pref = build_clause_no(tmp) or ''
    except Exception:
        pref = ''
    cur = position.get('regulation')
    ok = True
    if cur and position.get('_reg_pref', None) == pref:
        m1, m2 = _r.match(r'(\d+)([A-Z]*)', str(cur)), _r.match(r'(\d+)([A-Z]*)', str(reg_no))
        if m1 and m2:
            c, n = int(m1.group(1)), int(m2.group(1))
            ok = (m2.group(2) > m1.group(2)) if n == c else (c < n <= c + max_jump)
    if ok:
        position['_reg_pref'] = pref
    return ok


def reset_below(pos, level):
    levels = ['regulation', 'sub_reg', 'clause', 'sub_clause', 'capital', 'numbered_deep']
    if level not in levels:
        return pos
    reset_from = levels.index(level) + 1
    for l in levels[reset_from:]:
        pos[l] = None
    pos['proviso_count'] = 0
    pos['explanation_count'] = 0
    pos['pending_reg'] = None
    return pos


def _depth_of(pos):
    levels = ['regulation', 'sub_reg', 'clause', 'sub_clause', 'capital', 'numbered_deep']
    return sum(1 for l in levels if pos.get(l))


def _parent_clause_no(pos, current_level):
    levels = ['regulation', 'sub_reg', 'clause', 'sub_clause', 'capital', 'numbered_deep']
    if current_level not in levels:
        return None
    idx = levels.index(current_level)
    pos_copy = dict(pos)
    for l in levels[idx:]:
        pos_copy[l] = None
    pos_copy['proviso_count'] = 0
    pos_copy['explanation_count'] = 0
    return build_clause_no(pos_copy)


def collect_footnote_numbers(pdf):
    """Scan all pages for footnote-definition lines (e.g. '8 Vide circulars...',
    '3 Inserted by...') and return the set of genuinely-defined footnote numbers.
    Used to gate superscript-stripping so it never touches a number unless it's
    a confirmed real footnote — prevents legitimate inline values (e.g. '100 per
    cent') from being silently deleted by the superscript-cleanup heuristic."""
    footnote_numbers = set()
    footnote_def_pattern = re.compile(
        r'^\s{0,4}(\d{1,3})\.?\s+(Inserted|Substituted|Omitted|Added|Prior to (?:its |the )?(?:amendment|substitution|insertion|omission|deletion)|Deleted|Vide)\b',
        re.IGNORECASE
    )
    for page in pdf.pages:
        text = page.extract_text() or ''
        for line in text.split('\n'):
            m = footnote_def_pattern.match(line.strip())
            if m:
                footnote_numbers.add(m.group(1))
    return footnote_numbers


def get_body_font_size(plumber_page):
    """Compute the page's dominant (body-text) font size from word-level data.
    Returns None if font data is unavailable — callers must treat that as
    'unknown, default to safe/preserve' rather than guessing."""
    try:
        words = plumber_page.extract_words(extra_attrs=["size"])
    except Exception:
        return None
    from collections import Counter
    sizes = [round(w['size'], 1) for w in words if w.get('size')]
    if not sizes:
        return None
    return Counter(sizes).most_common(1)[0][0]


def get_ordered_digit_words(plumber_page):
    """Return, in reading order, (text, size) for every standalone 1-4 digit
    word on the page — candidates for the superscript/content classifier."""
    try:
        words = plumber_page.extract_words(extra_attrs=["size"])
    except Exception:
        return []
    return [(w['text'], round(w['size'], 1)) for w in words if re.match(r'^\d{1,4}$', w['text'])]


def _norm_running(line):
    """#421: normalise a line for running header/footer comparison --
    lowercase, collapse spaces, treat all digit runs as the same ('Page 3' == 'Page 17')."""
    return re.sub(r'\s+', ' ', re.sub(r'\d+', '#', line.strip().lower()))


def detect_running_lines(pdf_fitz, top_n=3, bottom_n=3, min_share=0.4):
    """#421: find lines repeated in the top/bottom few lines of most pages
    (running headers/footers such as the document title or 'Page X of Y').
    Lines with fewer than 4 letters are never treated as running lines, so
    standalone clause numbers (RBI 2025 dotless format) are never touched."""
    from collections import Counter
    counts = Counter()
    pages = len(pdf_fitz)
    for i in range(pages):
        lines = [l for l in (pdf_fitz[i].get_text() or '').split('\n') if l.strip()]
        seen = set()
        for l in lines[:top_n] + lines[-bottom_n:]:
            n = _norm_running(l)
            if sum(ch.isalpha() for ch in n) < 4 or n in seen:
                continue
            seen.add(n)
            counts[n] += 1
    threshold = max(3, int(pages * min_share))
    return {n for n, c in counts.items() if c >= threshold}


def strip_page_noise(page_text, footnote_numbers=None, digit_word_queue=None, body_font_size=None, running_lines=None, page_index=None):
    footnote_numbers = footnote_numbers or set()
    digit_word_queue = list(digit_word_queue or [])
    _queue_idx = [0]
    ambiguous_records = []
    lines = page_text.split('\n')
    if running_lines:  # #421: blank running headers/footers before page-number detection
        lines = ['' if _norm_running(l) in running_lines else l for l in lines]
    non_empty = [i for i, l in enumerate(lines) if l.strip()]
    first_ne = non_empty[0] if non_empty else -1
    last_ne = non_empty[-1] if non_empty else -1
    cleaned = []
    in_footnote_block = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            cleaned.append('')
            continue
        if PATTERNS['page_number'].match(stripped):
            # Header/footer position = page number, strip it.
            # Mid-page solo number = dotless clause number (RBI 2025 format), keep it.
            if (idx == first_ne or idx == last_ne) and (page_index is None or abs(int(stripped) - page_index) <= 3):  # PARSER-FIX-2
                continue
            cleaned.append(line)
            continue
        if PATTERNS['gazette_header'].match(stripped):
            continue
        if PATTERNS['footnote_block'].match(stripped):
            in_footnote_block = True
        if in_footnote_block:
            continue
        cleaned.append(line)
    clean_text = '\n'.join(cleaned)
    clean_text = PATTERNS['footnote_ref_inline'].sub(r'\1', clean_text)
    clean_text = PATTERNS['cross_ref_tag'].sub('', clean_text)
    def _strip_superscript(m):
        digit = m.group(0).strip()
        size = None
        idx = _queue_idx[0]
        while idx < len(digit_word_queue):
            wtext, wsize = digit_word_queue[idx]
            if wtext == digit:
                size = wsize
                _queue_idx[0] = idx + 1
                break
            idx += 1
        is_small_font = (body_font_size is not None and size is not None and size < body_font_size * 0.75)
        is_registered_footnote = digit in footnote_numbers
        if is_small_font and is_registered_footnote:
            return ' '                  # both signals agree — confirmed footnote, strip
        elif not is_small_font:
            return m.group(0)           # normal-size — content, preserve regardless of registry
        else:
            # small font but not a known footnote: genuinely ambiguous (could be
            # an exponent/formula, could be an undetected footnote). Text is
            # NEVER altered here — just recorded for a separate, metadata-only
            # flagging pass run after all node-building completes.
            context = m.string[max(0, m.start()-25):m.end()+20].replace('\n', ' ')
            ambiguous_records.append((digit, context))
            return m.group(0)
    clean_text = PATTERNS['superscript'].sub(_strip_superscript, clean_text)
    clean_text = PATTERNS['omitted'].sub('', clean_text)
    return clean_text, ambiguous_records


def _build_table_interpretation_prompt(context_text: str, headers: list, rows_data: list) -> str:
    """Build Sequence #TBD -- table-to-obligation interpretation. Replaces the old
    mechanical '[Table: <3 lines above>] header: value | ...' concatenation, which
    produced garbled, meaningless clause text whenever the raw text preceding a table
    on the PDF page happened to be unrelated to that table (confirmed real cases:
    ANN III ROW 7/10 in guideline 210 -- ANN IV A -- see Build Sequence #TBD).
    """
    rows_block = "\n".join(
        f"  Row {idx}: " + " | ".join(f"{h}: {v}" for h, v in zip(headers, row) if v)
        for idx, row in enumerate(rows_data, start=1)
    )
    return f"""You are analyzing a table extracted from a BFSI regulatory guideline PDF, to decide whether it describes obligations an NBFC must follow.

TASK: First, judge whether this table describes obligations, requirements, or mandatory classifications the NBFC must follow -- as opposed to reference data, historical figures, or a blank worksheet/template with no real instructive content.

Return ONLY valid JSON. No explanation. No markdown.

---

TEXT IMMEDIATELY PRECEDING THIS TABLE IN THE DOCUMENT (for context only -- may or may not describe the table):
{context_text}

---

TABLE HEADERS: {' | '.join(headers)}

TABLE ROWS:
{rows_block}

---

TASK 1 -- IS THIS TABLE ACTIONABLE:
Set is_actionable to true only if the table itself describes something the NBFC must do, classify, or comply with. Set it to false for pure reference data, historical figures, or blank/template worksheets with no real instructive content (e.g. a list of line items with no actual values filled in).

TASK 2 -- IF ACTIONABLE, FRAME EACH ROW AS AN OBLIGATION:
For each row that contains a genuine, distinct requirement, write ONE independent, plain-prose obligation statement -- a complete sentence a compliance officer could read and understand on its own, with no table jargon, no "Row N", no leftover header:value formatting. Frame every row's obligation in a SIMILAR, CONSISTENT sentence structure across all rows -- only the row-specific values (the classification, the item name, the treatment) should differ between them. Skip rows that are blank, header repeats, or carry no real content.

OUTPUT FORMAT (exactly this JSON shape):
{{
  "is_actionable": true | false,
  "obligations": [
    {{
      "row_number": <int, matching the Row N above>,
      "obligation_text": "string -- one complete, standalone obligation sentence"
    }}
  ]
}}

If is_actionable is false, obligations must be an empty array []."""


def extract_table_clauses(page, page_num, position):
    nodes = []
    cell_texts = set()
    tables = page.extract_tables()
    if not tables:
        return nodes, cell_texts
    page_text = page.extract_text() or ''
    lines_above = [l.strip() for l in page_text.split('\n') if l.strip()]
    # Real preceding context for the LLM to judge relevance itself -- wider window
    # than the old 3-line heuristic, since the LLM (not string-joining) now decides
    # what's actually relevant.
    context_text = '\n'.join(lines_above[-8:]) if lines_above else f'(no text found before table on page {page_num})'
    section_prefix = build_clause_no(position) or 'TABLE'

    from app import client
    import json as _json

    for table_idx, table in enumerate(tables):
        if not table or len(table) < 2:
            continue
        headers = [str(cell).strip() if cell else '' for cell in table[0]]
        rows_data = []
        row_cell_texts_by_row = {}
        for row_idx, row in enumerate(table[1:], start=1):
            if not row or all(not cell for cell in row):
                continue
            row_values = [str(cell).strip() if cell else '' for cell in row]
            for cell_text in row_values:
                if cell_text:
                    cell_texts.add(cell_text)
            rows_data.append(row_values)
            row_cell_texts_by_row[len(rows_data)] = row_values

        if not rows_data:
            continue

        try:
            prompt = _build_table_interpretation_prompt(context_text, headers, rows_data)
            response = client.chat.completions.create(
                model="gpt-4.1-mini",
                max_tokens=4000,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "You are a compliance classification engine. Return ONLY valid JSON. No explanation. No markdown."},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content
            parsed = _json.loads(raw) if raw else None
        except Exception as e:
            logging.warning(f"[TableInterpretation] LLM call failed for table on page {page_num}: {e} -- table skipped, no clauses created (was previously force-split mechanically)")
            continue

        if not parsed or not isinstance(parsed, dict):
            logging.warning(f"[TableInterpretation] LLM returned no usable output for table on page {page_num} -- table skipped")
            continue

        if not parsed.get("is_actionable"):
            logging.info(f"[TableInterpretation] Table on page {page_num} judged NOT actionable -- no clauses created, matches design decision to skip non-actionable tables cleanly rather than force a fake obligation")
            continue

        obligations = parsed.get("obligations") or []
        if not isinstance(obligations, list):
            obligations = []

        for entry in obligations:
            if not isinstance(entry, dict):
                continue
            row_number = entry.get("row_number")
            obligation_text = (entry.get("obligation_text") or "").strip()
            # Mechanical safeguard: never trust the LLM's row_number claim blindly --
            # only accept it if it corresponds to a real row we actually sent, same
            # never-trust-the-LLM-for-linkage principle used throughout this codebase.
            if not isinstance(row_number, int) or row_number not in row_cell_texts_by_row:
                logging.warning(f"[TableInterpretation] Dropping obligation with invalid row_number={row_number!r} on page {page_num} -- doesn't match any real row sent")
                continue
            if not obligation_text:
                continue

            clause_no = f"{section_prefix} ROW {row_number}"
            nodes.append({
                'clause_no': clause_no,
                'raw_text': obligation_text,
                'node_type': 'table_row',
                'page_number': page_num,
                'depth': 1,
                'parent_clause_no': section_prefix,
                'children': [],
                'is_table_row': True,
            })

    return nodes, cell_texts



def get_page_section(page_num, structure_map):
    """Look up which section a page belongs to from structure map."""
    if not structure_map or not structure_map.get("sections"):
        return None
    for section in structure_map["sections"]:
        start = section.get("start_page", 0)
        end = section.get("end_page", 99999)
        if start <= page_num <= end:
            return section
    return None


def build_prefix_from_section(section):
    """Build clause_no prefix from structure map section."""
    if not section:
        return None
    sec_type = section.get("type", "").lower()
    sec_id = section.get("id", "")
    if sec_type == "chapter":
        return f"CH {sec_id}"
    elif sec_type == "schedule":
        return f"SCH {sec_id}"
    elif sec_type in ("annexure", "annex"):
        return f"ANN {sec_id}"
    elif sec_type == "module":
        return f"MOD {sec_id}"
    elif sec_type == "appendix":
        return f"APP {sec_id}" if sec_id else "APP"
    elif sec_type == "main_body":
        return ""
    return None


def _is_section_heading(line):
    """#422: True for section heading lines that must not be glued onto clause
    text -- chapter/schedule/annexure/part headings, and lettered/numbered
    section headings such as 'B. Applicability' or 'A.1 IT Strategy Committee'.
    Called only after every clause-number pattern has already failed."""
    _sec_m = (PATTERNS['chapter'].match(line) or PATTERNS['schedule'].match(line)
              or PATTERNS['annexure'].match(line) or PATTERNS['part'].match(line))
    if _sec_m:
        # PARSER-FIX-1: a heading, not a sentence that happens to start with 'Chapter II ...' / 'Part A ...'
        _rest = line[_sec_m.end():].strip()
        if _rest and (_rest[0].islower() or re.search(r"\b(shall|should|must|will)\b", _rest)):
            return False
        return True
    m = re.match(r'^([A-Z](?:\.\d{1,2}){0,3})\.?\s+(\S.*)$', line)
    if not m:
        return False
    title = m.group(2).strip()
    if re.search(r'[.;:,]$', title):
        return False
    words = title.split()
    if not (1 <= len(words) <= 14):
        return False
    if re.search(r'\d', m.group(1)):  # numbered marker, e.g. 'B.1' -- sentence case is fine
        return words[0][:1].isupper() or words[0].startswith('(')
    long_words = [w for w in words if len(re.sub(r'[^A-Za-z]', '', w)) > 3]
    if not long_words:
        return False
    caps = sum(1 for w in long_words if w[0].isupper() or w.startswith('('))
    return caps / len(long_words) >= 0.6


def parse_pdf_structure(file_path, structure_map=None):
    logger.info(f"Stage 1: Parsing {file_path}")
    global LAST_DROPPED_LINES, LAST_REATTACHED
    dropped_lines = []  # #128: lines the parser discards -- measured, not guessed
    nodes = []
    position = empty_position()
    skip_to_end = False
    try:
        pdf_plumber = pdfplumber.open(file_path)
        pdf_fitz = fitz.open(file_path)
        total_pages = len(pdf_fitz)
        logger.info(f"Stage 1: {total_pages} pages")
        footnote_numbers = collect_footnote_numbers(pdf_plumber)
        logger.info(f"Stage 1: {len(footnote_numbers)} confirmed footnote markers detected: {sorted(footnote_numbers)}")
        try:
            running_lines = detect_running_lines(pdf_fitz)
        except Exception as _e421:
            logger.warning(f"Stage 1: running header/footer detection failed, continuing without it: {_e421}")
            running_lines = set()
        logger.info(f"Stage 1: {len(running_lines)} running header/footer line(s) detected: {sorted(running_lines)[:5]}")
    except Exception as e:
        logger.error(f"Stage 1: Cannot open PDF: {e}")
        raise

    buf_text = []
    buf_clause_no = None
    buf_node_type = None
    buf_page = None
    buf_parent = None
    buf_depth = 0
    all_ambiguous_matches = []
    resume_idx = None     # #128: clause closed by a table page, may continue on the next page
    reattached_lines = 0
    annex_text_counts = {}  # #128: numbering for unstructured annex/schedule text pieces

    def flush():
        nonlocal buf_text, buf_clause_no, buf_node_type, buf_page, buf_parent, buf_depth
        if buf_text and buf_clause_no:
            # #424: 'well-' + 'defined' -> 'well-defined' (line-break hyphen, keep the hyphen)
            _out = ''
            for _piece in buf_text:
                _piece = _piece.strip()
                if not _piece:
                    continue
                if len(_out) > 1 and _out.endswith('-') and _out[-2].isalpha() and _piece[:1].islower():
                    _out += _piece
                else:
                    _out += (' ' if _out else '') + _piece
            text = ' '.join(_out.split())
            if text.strip():
                nodes.append({
                    'clause_no': buf_clause_no, 'raw_text': text.strip(),
                    'node_type': buf_node_type or 'unknown', 'page_number': buf_page,
                    'depth': buf_depth, 'parent_clause_no': buf_parent,
                    'children': [], 'is_table_row': False,
                })
        buf_text.clear()
        buf_clause_no = None

    def start_node(clause_no, node_type, page, parent, depth, first_text=''):
        nonlocal buf_text, buf_clause_no, buf_node_type, buf_page, buf_parent, buf_depth, resume_idx
        flush()
        resume_idx = None  # #128: a new clause has started
        buf_clause_no = clause_no
        buf_node_type = node_type
        buf_page = page
        buf_parent = parent
        buf_depth = depth
        buf_text[:] = [first_text] if first_text.strip() else []

    # Track last known section from structure map to detect changes
    last_section_id = None
    expect_title = False  # #422: next non-empty line may be a chapter's title

    try:
        for page_num in range(total_pages):
            if skip_to_end:
                continue
            fitz_page = pdf_fitz[page_num]
            raw_text = fitz_page.get_text()

            # --- STRUCTURE MAP MODE ---
            if structure_map:
                section = get_page_section(page_num + 1, structure_map)

                # Skip pages not in any section or marked extract:false
                if not section:
                    continue
                if not section.get("extract", True):
                    continue

                # If section changed — reset position and set new context from map
                section_id = f"{section.get('type')}_{section.get('id')}"
                if section_id != last_section_id:
                    flush()
                    resume_idx = None  # #128: never carry text across a section change
                    position = empty_position()
                    sec_type = section.get("type", "").lower()
                    sec_id = section.get("id", "")
                    if sec_type == "chapter":
                        position["chapter"] = sec_id
                        position["current_section"] = "chapter"
                    elif sec_type == "schedule":
                        position["schedule"] = sec_id
                        position["current_section"] = "schedule"
                    elif sec_type in ("annexure", "annex"):
                        position["annexure"] = sec_id
                        position["current_section"] = "annexure"
                    elif sec_type == "module":
                        position["module"] = sec_id
                        position["current_section"] = "module"
                    elif sec_type == "appendix":
                        position["annexure"] = sec_id or "APP"
                        position["current_section"] = "annexure"
                    elif sec_type == "main_body":
                        position["current_section"] = "main_body"
                    last_section_id = section_id
                    logger.debug(f"Stage 1: Page {page_num+1} → {section_id}")

            # --- REGEX FALLBACK MODE (no structure map) ---
            else:
                if PATTERNS['appendix'].search(raw_text[:500]):
                    logger.info(f"Stage 1: Appendix at page {page_num+1} — stopping")
                    skip_to_end = True
                    flush()
                    continue

            plumber_page = pdf_plumber.pages[page_num]
            body_font_size = get_body_font_size(plumber_page)
            digit_word_queue = get_ordered_digit_words(plumber_page)
            clean_text, page_ambiguous = strip_page_noise(raw_text, footnote_numbers, digit_word_queue, body_font_size, running_lines, page_index=page_num + 1)
            for digit, ctx in page_ambiguous:
                all_ambiguous_matches.append((page_num + 1, digit, ctx))
            has_tables = bool(plumber_page.extract_tables())
            table_nodes = []
            table_cell_texts = set()
            if False:  # TABLE-VERBATIM: tables stay verbatim in their own paragraph (no AI rewrite, no ROW clauses)
                table_nodes, table_cell_texts = extract_table_clauses(plumber_page, page_num + 1, position)
            lines = clean_text.split('\n')
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                stripped = re.sub(r'^\d{0,2}\[(?=\d{1,3}[A-Z]{0,2}\.)', '', stripped)  # TABLE-VERBATIM: '2[27A.' -> '27A.'
                # Skip lines already correctly captured as a complete table row above --
                # prevents the same table content being duplicated as a broken,
                # context-free fragment clause (Build Sequence #344).
                if stripped in table_cell_texts:
                    continue
                _title_slot = expect_title  # #422
                expect_title = False

                # Section detection — only in regex fallback mode
                if not structure_map:
                    m = PATTERNS['chapter'].match(stripped)
                    if m and _is_section_heading(stripped):  # PARSER-FIX-1
                        flush(); position = empty_position()
                        position['chapter'] = m.group(2); position['current_section'] = 'chapter'
                        expect_title = True  # #422
                        continue
                    m = PATTERNS['schedule'].match(stripped)
                    if m and _is_section_heading(stripped):  # PARSER-FIX-1
                        flush(); position = empty_position()
                        position['schedule'] = m.group(2); position['current_section'] = 'schedule'
                        continue
                    m = PATTERNS['annexure'].match(stripped)
                    if m and _is_section_heading(stripped):  # PARSER-FIX-1
                        flush(); position = empty_position()
                        position['annexure'] = m.group(2); position['current_section'] = 'annexure'
                        continue
                    m = PATTERNS['part'].match(stripped)
                    if m and position['current_section'] == 'schedule':
                        flush(); position['part'] = m.group(2)
                        position = reset_below(position, 'regulation'); continue

                if not position['current_section']:
                    if buf_clause_no == 'PREAMBLE':
                        buf_text.append(stripped)
                    elif not nodes and not buf_clause_no and stripped.lower().startswith('in exercise of'):
                        start_node('PREAMBLE', 'regulation', page_num + 1, None, 0, stripped)  # #128
                    else:
                        dropped_lines.append((page_num + 1, 'before first section', stripped))
                    continue

                # --- Annexure/Appendix lettered-paragraph format: "A. text", "B. text" ---
                # These documents don't use the regulation-numbered hierarchy at all,
                # so we treat each top-level letter as its own clause directly.
                if position['current_section'] == 'annexure':
                    m_lp = PATTERNS['letter_para'].match(line)
                    if m_lp:
                        letter = m_lp.group(1)
                        position['letter_para'] = letter
                        clause_no = build_clause_no(position)
                        _ld_used = {n.get('clause_no') for n in nodes} | ({buf_clause_no} if buf_clause_no else set())  # LETTER-DUP
                        if clause_no in _ld_used:
                            _ld_k = 2
                            while f"{clause_no} ({_ld_k})" in _ld_used:
                                _ld_k += 1
                            clause_no = f"{clause_no} ({_ld_k})"
                        parent_base = []
                        if position['chapter']:
                            parent_base.append(f"CH {position['chapter']}")
                        elif position['schedule']:
                            parent_base.append(f"SCH {position['schedule']}")
                        elif position['annexure']:
                            parent_base.append(f"ANN {position['annexure']}")
                        parent = ' '.join(parent_base) if parent_base else None
                        idx = line.index(letter + '.')
                        text_after = line[idx + len(letter) + 1:].strip()
                        start_node(clause_no, 'letter_para', page_num + 1, parent, 1, text_after)
                        continue
                    elif position['letter_para'] and stripped:
                        # Continuation of the current lettered paragraph (wrapped text)
                        buf_text.append(stripped)
                        continue

                m = PATTERNS['regulation_solo'].match(line)
                if m and _reg_ok(position, m.group(1), 30):  # PARA-SEQ
                    position['pending_reg'] = m.group(1); continue
                m = PATTERNS['regulation_solo_dotless'].match(line)  # PARA-SEQ-2: next paragraph only
                if m and _reg_ok(position, m.group(1), 1):  # PARA-SEQ
                    position['pending_reg'] = m.group(1); continue
                m = PATTERNS['regulation_inline'].match(line)
                if m and _reg_ok(position, m.group(1), 30):  # PARA-SEQ
                    reg_no = m.group(1); position['regulation'] = reg_no
                    position = reset_below(position, 'regulation')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'regulation')
                    text_after = line[line.index(reg_no + '.') + len(reg_no) + 1:].strip()
                    start_node(clause_no, 'regulation', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['regulation_dotless'].match(line)
                if m and _reg_ok(position, m.group(1), 2):  # PARA-SEQ PARA-SEQ-2
                    reg_no = m.group(1); position['regulation'] = reg_no
                    position = reset_below(position, 'regulation')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'regulation')
                    text_after = line[m.end(1):].strip()
                    start_node(clause_no, 'regulation', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                if position.get('pending_reg') and stripped:
                    if not PATTERNS['sub_reg'].match(line):
                        reg_no = position['pending_reg']; position['regulation'] = reg_no
                        position = reset_below(position, 'regulation')
                        clause_no = build_clause_no(position)
                        parent = _parent_clause_no(position, 'regulation')
                        start_node(clause_no, 'regulation', page_num + 1, parent, _depth_of(position), stripped)
                        position['pending_reg'] = None; continue
                    else:
                        reg_no = position['pending_reg']; position['regulation'] = reg_no
                        position = reset_below(position, 'regulation'); position['pending_reg'] = None
                if PATTERNS['proviso'].match(stripped):
                    position['proviso_count'] += 1
                    base = build_clause_no(position)
                    clause_no = f"{base}_PRV{position['proviso_count']}" if base else None
                    if clause_no:
                        start_node(clause_no, 'proviso', page_num + 1, base, _depth_of(position) + 1, stripped)
                    continue
                if PATTERNS['explanation'].match(stripped):
                    position['explanation_count'] += 1
                    base = build_clause_no(position)
                    clause_no = f"{base}_EXP{position['explanation_count']}" if base else None
                    if clause_no:
                        start_node(clause_no, 'explanation', page_num + 1, base, _depth_of(position) + 1, stripped)
                    continue
                m = PATTERNS['sub_reg'].match(line)
                if m and position['regulation']:
                    sub = m.group(1); position['sub_reg'] = sub
                    position = reset_below(position, 'sub_reg')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'sub_reg')
                    idx = line.index(f'({sub})'); text_after = line[idx:].strip()  # PARSER-FIX-1: keep the marker
                    start_node(clause_no, 'sub_reg', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['clause'].match(line)
                if m and position['sub_reg']:
                    cl = m.group(1); position['clause'] = cl
                    position = reset_below(position, 'clause')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'clause')
                    idx = line.index(f'({cl})'); text_after = line[idx:].strip()  # PARSER-FIX-1: keep the marker
                    start_node(clause_no, 'clause', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['sub_clause'].match(line)
                if m and position['clause']:
                    sc = m.group(1); position['sub_clause'] = sc
                    position = reset_below(position, 'sub_clause')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'sub_clause')
                    idx = line.index(f'({sc})'); text_after = line[idx:].strip()  # PARSER-FIX-1: keep the marker
                    start_node(clause_no, 'sub_clause', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['capital'].match(line)
                if m and position['sub_clause']:
                    cap = m.group(1); position['capital'] = cap
                    position = reset_below(position, 'capital')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'capital')
                    idx = line.index(f'({cap})'); text_after = line[idx:].strip()  # PARSER-FIX-1: keep the marker
                    start_node(clause_no, 'capital', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['numbered_deep'].match(line)
                if m and position['capital']:
                    nd = m.group(1); position['numbered_deep'] = nd
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'numbered_deep')
                    idx = line.index(f'({nd})'); text_after = line[idx:].strip()  # PARSER-FIX-1: keep the marker
                    start_node(clause_no, 'numbered_deep', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                # #422: never glue section headings onto clause text
                if re.match(r'^[A-Z]((?:\.\d{1,2}){1,3}\.?|\.)$', stripped):
                    expect_title = True  # #422: marker alone on its line ('B.'); title follows
                    continue
                if _is_section_heading(stripped):
                    expect_title = (bool(PATTERNS['chapter'].match(stripped) or PATTERNS['schedule'].match(stripped)
                                         or PATTERNS['annexure'].match(stripped)) and len(stripped.split()) <= 4) \
                                   or stripped.count('(') > stripped.count(')')  # #422: wrapped title
                    continue
                if _title_slot and len(stripped.split()) <= 10 and not re.search(r'[.;:,]$', stripped):
                    continue  # #422: stand-alone title line under a chapter heading
                if buf_clause_no:
                    buf_text.append(stripped)
                elif resume_idx is not None and resume_idx < len(nodes):
                    _t = nodes[resume_idx]['raw_text']  # #128: continuation after a table page
                    if len(_t) > 1 and _t.endswith('-') and _t[-2].isalpha() and stripped[:1].islower():
                        nodes[resume_idx]['raw_text'] = _t + stripped
                    else:
                        nodes[resume_idx]['raw_text'] = _t + ' ' + stripped
                    reattached_lines += 1
                elif not nodes and stripped.lower().startswith('in exercise of'):
                    start_node('PREAMBLE', 'regulation', page_num + 1, None, 0, stripped)  # #128
                elif position['current_section'] in ('annexure', 'schedule'):
                    _sec = f"ANN {position['annexure']}" if position['current_section'] == 'annexure' else f"SCH {position['schedule']}"
                    annex_text_counts[_sec] = annex_text_counts.get(_sec, 0) + 1
                    _id = f'{_sec} TEXT' if annex_text_counts[_sec] == 1 else f'{_sec} TEXT {annex_text_counts[_sec]}'
                    start_node(_id, 'regulation', page_num + 1, _sec, 1, stripped)  # #128: keep annex forms/declarations
                elif position.get('chapter') and re.search(r'\b(shall|should|may|must|will|apply|applies|applicable|exempt)\b', stripped, re.I):  # CHAPTER-INTRO
                    _ci_no = f"CH {position['chapter']} INTRO"
                    if _ci_no in {n.get('clause_no') for n in nodes}:
                        _ci_no = f"{_ci_no} (2)"
                    start_node(_ci_no, 'regulation', page_num + 1, f"CH {position['chapter']}", 1, stripped)
                else:
                    dropped_lines.append((page_num + 1, 'no open clause', stripped))
            if has_tables and table_nodes:  # TABLE-VERBATIM: no table nodes, so the page flows normally
                _had_open = bool(buf_clause_no)
                flush()
                if _had_open and nodes and not nodes[-1].get('is_table_row'):
                    resume_idx = len(nodes) - 1  # #128: next page may continue this clause
                nodes.extend(table_nodes)
        flush()
    finally:
        pdf_plumber.close()
        pdf_fitz.close()

    for _n in nodes:  # #128: flag unstructured annex/schedule text for human review
        if re.search(r' TEXT( \d+)?$', _n.get('clause_no') or ''):
            _n['extraction_status'] = 'FLAGGED'
            _n['flag_reason'] = ('UNSTRUCTURED_SECTION_TEXT: annex/schedule text with no clause numbering '
                                 '(forms, declarations, notes) -- kept for completeness; review how it should be treated')
    LAST_DROPPED_LINES = dropped_lines
    LAST_REATTACHED = reattached_lines
    if reattached_lines:
        logger.info(f"Stage 1: {reattached_lines} line(s) re-attached to a clause continuing after a table page")
    if dropped_lines:
        logger.warning(f"Stage 1: {len(dropped_lines)} line(s) discarded (no clause to attach to) -- first: {dropped_lines[:3]}")
    nodes = _assign_parents(nodes)
    if all_ambiguous_matches:
        logger.warning(f"Stage 1: {len(all_ambiguous_matches)} ambiguous digit(s) found (not stripped, not deleted) - flagging matching nodes")
        for pg, digit, ctx in all_ambiguous_matches:
            snippet = ctx[:30].strip()
            candidates = [n for n in nodes if n.get('page_number') == pg and snippet and snippet in n.get('raw_text', '')]
            if not candidates:
                candidates = [n for n in nodes if n.get('page_number') == pg]
            for n in candidates:
                n['extraction_status'] = 'FLAGGED'
                existing = n.get('flag_reason') or ''
                reason = f'AMBIGUOUS_TEXT_FORMAT: possible superscript/formula digit "{digit}" on page {pg} - verify (context: {ctx.strip()[:60]})'
                n['flag_reason'] = (existing + '; ' + reason).strip('; ') if existing else reason
    logger.info(f"Stage 1: {len(nodes)} nodes extracted")
    return nodes


def _assign_parents(nodes):
    clause_map = {n['clause_no']: n for n in nodes if n['clause_no']}
    for node in nodes:
        parent_no = node.get('parent_clause_no')
        if parent_no and parent_no in clause_map:
            if node['clause_no'] not in clause_map[parent_no]['children']:
                clause_map[parent_no]['children'].append(node['clause_no'])
    return nodes


def validate_nodes(nodes):
    issues = []
    seen = {}
    valid = []
    for node in nodes:
        if not node.get('clause_no'):
            issues.append(f"Missing clause_no: {node.get('raw_text','')[:50]}")
            continue
        text = node.get('raw_text', '').strip()
        if not text:
            issues.append(f"Empty text: {node['clause_no']}")
            continue
        if len(text) < 10:
            issues.append(f"Too short/omitted: {node['clause_no']} = {repr(text)}")
            continue
        if re.match(r'^[\*\s\d]+$', text):
            issues.append(f"Junk text: {node['clause_no']} = {repr(text)}")
            continue
        if node['clause_no'] in seen:
            issues.append(f"Duplicate clause_no: {node['clause_no']} (pages {seen[node['clause_no']]} and {node['page_number']})")
            continue
        seen[node['clause_no']] = node['page_number']

        # Flag suspicious regulation numbers
        # e.g. CH IV 2013 — 4-digit year-like numbers are almost always parsing errors
        clause_no = node['clause_no']
        parts = clause_no.split(' ')
        if len(parts) >= 3:
            reg_part = parts[2]  # e.g. "2013", "490", "1996"
            # Flag if regulation number looks like a year (1900-2099)
            if re.match(r'^(19|20)\d{2}$', reg_part):
                node['extraction_status'] = 'FLAGGED'
                node['flag_reason'] = f'SUSPICIOUS_REGULATION_NUMBER: {reg_part} looks like a year reference, not a regulation number. Verify on page {node["page_number"]}'
            # Flag if regulation number is unusually large (>200 for most regulators)
            elif re.match(r'^\d+$', reg_part) and int(reg_part) > 200:
                node['extraction_status'] = 'FLAGGED'
                node['flag_reason'] = f'SUSPICIOUS_REGULATION_NUMBER: {reg_part} is unusually large. Verify on page {node["page_number"]}'

        # Flag short text clauses
        if len(text) < 50 and not node.get('flag_reason'):
            node['extraction_status'] = 'FLAGGED'
            node['flag_reason'] = f'SHORT_TEXT: Clause text is only {len(text)} characters. May be incomplete or a parsing error. Verify on page {node["page_number"]}'

        valid.append(node)
    return valid, issues


def get_parser_stats(nodes):
    type_counts = {}
    for node in nodes:
        t = node.get('node_type', 'unknown')
        type_counts[t] = type_counts.get(t, 0) + 1
    return {
        'total_nodes': len(nodes),
        'by_type': type_counts,
        'pages_covered': len(set(n['page_number'] for n in nodes)),
        'max_depth': max((n['depth'] for n in nodes), default=0),
    }
