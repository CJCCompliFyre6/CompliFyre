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
    'footnote_block':       re.compile(r'^\d+\.?\s+(Inserted|Substituted|Omitted|Added|Prior to|Deleted)\s+', re.IGNORECASE),
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
        r'^\s{0,4}(\d{1,3})\.?\s+(Inserted|Substituted|Omitted|Added|Prior to|Deleted|Vide)\b',
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


def strip_page_noise(page_text, footnote_numbers=None, digit_word_queue=None, body_font_size=None):
    footnote_numbers = footnote_numbers or set()
    digit_word_queue = list(digit_word_queue or [])
    _queue_idx = [0]
    ambiguous_records = []
    lines = page_text.split('\n')
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
            if idx == first_ne or idx == last_ne:
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


def extract_table_clauses(page, page_num, position):
    nodes = []
    cell_texts = set()
    tables = page.extract_tables()
    if not tables:
        return nodes, cell_texts
    page_text = page.extract_text() or ''
    lines_above = [l.strip() for l in page_text.split('\n') if l.strip()]
    table_title = ' | '.join(lines_above[-3:]) if lines_above else f'Table on page {page_num}'
    section_prefix = build_clause_no(position) or 'TABLE'
    for table_idx, table in enumerate(tables):
        if not table or len(table) < 2:
            continue
        headers = [str(cell).strip() if cell else '' for cell in table[0]]
        for row_idx, row in enumerate(table[1:], start=1):
            if not row or all(not cell for cell in row):
                continue
            row_parts = []
            for col_idx, cell in enumerate(row):
                cell_text = str(cell).strip() if cell else ''
                if cell_text:
                    cell_texts.add(cell_text)
                if cell_text and col_idx < len(headers) and headers[col_idx]:
                    row_parts.append(f"{headers[col_idx]}: {cell_text}")
                elif cell_text:
                    row_parts.append(cell_text)
            if not row_parts:
                continue
            clause_text = f"[Table: {table_title}] {' | '.join(row_parts)}"
            clause_no = f"{section_prefix} ROW {row_idx}"
            nodes.append({
                'clause_no': clause_no,
                'raw_text': clause_text.strip(),
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


def parse_pdf_structure(file_path, structure_map=None):
    logger.info(f"Stage 1: Parsing {file_path}")
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

    def flush():
        nonlocal buf_text, buf_clause_no, buf_node_type, buf_page, buf_parent, buf_depth
        if buf_text and buf_clause_no:
            text = ' '.join(' '.join(buf_text).split())
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
        nonlocal buf_text, buf_clause_no, buf_node_type, buf_page, buf_parent, buf_depth
        flush()
        buf_clause_no = clause_no
        buf_node_type = node_type
        buf_page = page
        buf_parent = parent
        buf_depth = depth
        buf_text[:] = [first_text] if first_text.strip() else []

    # Track last known section from structure map to detect changes
    last_section_id = None

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
            clean_text, page_ambiguous = strip_page_noise(raw_text, footnote_numbers, digit_word_queue, body_font_size)
            for digit, ctx in page_ambiguous:
                all_ambiguous_matches.append((page_num + 1, digit, ctx))
            has_tables = bool(plumber_page.extract_tables())
            table_nodes = []
            table_cell_texts = set()
            if has_tables:
                table_nodes, table_cell_texts = extract_table_clauses(plumber_page, page_num + 1, position)
            lines = clean_text.split('\n')
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                # Skip lines already correctly captured as a complete table row above --
                # prevents the same table content being duplicated as a broken,
                # context-free fragment clause (Build Sequence #344).
                if stripped in table_cell_texts:
                    continue

                # Section detection — only in regex fallback mode
                if not structure_map:
                    m = PATTERNS['chapter'].match(stripped)
                    if m:
                        flush(); position = empty_position()
                        position['chapter'] = m.group(2); position['current_section'] = 'chapter'
                        continue
                    m = PATTERNS['schedule'].match(stripped)
                    if m:
                        flush(); position = empty_position()
                        position['schedule'] = m.group(2); position['current_section'] = 'schedule'
                        continue
                    m = PATTERNS['annexure'].match(stripped)
                    if m:
                        flush(); position = empty_position()
                        position['annexure'] = m.group(2); position['current_section'] = 'annexure'
                        continue
                    m = PATTERNS['part'].match(stripped)
                    if m and position['current_section'] == 'schedule':
                        flush(); position['part'] = m.group(2)
                        position = reset_below(position, 'regulation'); continue

                if not position['current_section']:
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
                if m:
                    position['pending_reg'] = m.group(1); continue
                m = PATTERNS['regulation_solo_dotless'].match(line)
                if m:
                    position['pending_reg'] = m.group(1); continue
                m = PATTERNS['regulation_inline'].match(line)
                if m:
                    reg_no = m.group(1); position['regulation'] = reg_no
                    position = reset_below(position, 'regulation')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'regulation')
                    text_after = line[line.index(reg_no + '.') + len(reg_no) + 1:].strip()
                    start_node(clause_no, 'regulation', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['regulation_dotless'].match(line)
                if m:
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
                    idx = line.index(f'({sub})'); text_after = line[idx + len(sub) + 2:].strip()
                    start_node(clause_no, 'sub_reg', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['clause'].match(line)
                if m and position['sub_reg']:
                    cl = m.group(1); position['clause'] = cl
                    position = reset_below(position, 'clause')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'clause')
                    idx = line.index(f'({cl})'); text_after = line[idx + len(cl) + 2:].strip()
                    start_node(clause_no, 'clause', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['sub_clause'].match(line)
                if m and position['clause']:
                    sc = m.group(1); position['sub_clause'] = sc
                    position = reset_below(position, 'sub_clause')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'sub_clause')
                    idx = line.index(f'({sc})'); text_after = line[idx + len(sc) + 2:].strip()
                    start_node(clause_no, 'sub_clause', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['capital'].match(line)
                if m and position['sub_clause']:
                    cap = m.group(1); position['capital'] = cap
                    position = reset_below(position, 'capital')
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'capital')
                    idx = line.index(f'({cap})'); text_after = line[idx + len(cap) + 2:].strip()
                    start_node(clause_no, 'capital', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                m = PATTERNS['numbered_deep'].match(line)
                if m and position['capital']:
                    nd = m.group(1); position['numbered_deep'] = nd
                    clause_no = build_clause_no(position)
                    parent = _parent_clause_no(position, 'numbered_deep')
                    idx = line.index(f'({nd})'); text_after = line[idx + len(nd) + 2:].strip()
                    start_node(clause_no, 'numbered_deep', page_num + 1, parent, _depth_of(position), text_after)
                    continue
                if buf_clause_no:
                    buf_text.append(stripped)
            if has_tables:
                flush()
                nodes.extend(table_nodes)
        flush()
    finally:
        pdf_plumber.close()
        pdf_fitz.close()

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
