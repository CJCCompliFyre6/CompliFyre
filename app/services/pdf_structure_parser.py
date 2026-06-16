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
    'regulation_solo':      re.compile(r'^\s{0,4}(\d+[A-Z]?)\.\s*$'),
    'regulation_inline':    re.compile(r'^\s{0,4}(\d+[A-Z]?)\.\s+\S'),
    'sub_reg':              re.compile(r'^\s{0,8}\((\d+[A-Z]{0,3})\)\s+\S'),
    'clause':               re.compile(r'^\s{3,12}\(([a-z]{1,3})\)\s+\S'),
    'sub_clause':           re.compile(r'^\s{6,16}\(([ivxlcdm]+)\)\s+\S'),
    'capital':              re.compile(r'^\s{10,24}\(([A-Z])\)\s+\S'),
    'numbered_deep':        re.compile(r'^\s{14,28}\((\d+)\)\s+\S'),
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
        'regulation': None, 'sub_reg': None, 'clause': None,
        'sub_clause': None, 'capital': None, 'numbered_deep': None,
        'proviso_count': 0, 'explanation_count': 0,
        'current_section': None, 'pending_reg': None,
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
    else:
        return None
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


def strip_page_noise(page_text):
    lines = page_text.split('\n')
    cleaned = []
    in_footnote_block = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append('')
            continue
        if PATTERNS['page_number'].match(stripped):
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
    clean_text = PATTERNS['superscript'].sub(' ', clean_text)
    clean_text = PATTERNS['omitted'].sub('', clean_text)
    return clean_text


def extract_table_clauses(page, page_num, position):
    nodes = []
    tables = page.extract_tables()
    if not tables:
        return nodes
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
    return nodes


def parse_pdf_structure(file_path):
    logger.info(f"Stage 1: Parsing {file_path}")
    nodes = []
    position = empty_position()
    skip_to_end = False
    try:
        pdf_plumber = pdfplumber.open(file_path)
        pdf_fitz = fitz.open(file_path)
        total_pages = len(pdf_fitz)
        logger.info(f"Stage 1: {total_pages} pages")
    except Exception as e:
        logger.error(f"Stage 1: Cannot open PDF: {e}")
        raise

    buf_text = []
    buf_clause_no = None
    buf_node_type = None
    buf_page = None
    buf_parent = None
    buf_depth = 0

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

    try:
        for page_num in range(total_pages):
            if skip_to_end:
                continue
            fitz_page = pdf_fitz[page_num]
            raw_text = fitz_page.get_text()
            if PATTERNS['appendix'].search(raw_text[:500]):
                logger.info(f"Stage 1: Appendix at page {page_num+1} — stopping")
                skip_to_end = True
                flush()
                continue
            clean_text = strip_page_noise(raw_text)
            plumber_page = pdf_plumber.pages[page_num]
            has_tables = bool(plumber_page.extract_tables())
            table_nodes = []
            if has_tables:
                table_nodes = extract_table_clauses(plumber_page, page_num + 1, position)
            lines = clean_text.split('\n')
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
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
                m = PATTERNS['regulation_solo'].match(line)
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
        if not node.get('raw_text', '').strip():
            issues.append(f"Empty text: {node['clause_no']}")
            continue
        if node['clause_no'] in seen:
            issues.append(f"Duplicate clause_no: {node['clause_no']} (pages {seen[node['clause_no']]} and {node['page_number']})")
            continue
        seen[node['clause_no']] = node['page_number']
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
