"""
BATCH1-PROMPT-CONTEXT: context every generation prompt receives about the clause it works on.
  - abbreviations the guideline itself defines ("IT Strategy Committee (ITSC)") so they are never guessed
  - the human reviewer's notes for this clause, as guidance
  - a rule that a lead-in carried over from an earlier split part is context only
All lookups are by the exact clause text the prompt builders already receive; if the clause
cannot be found (e.g. text was modified by a caller) the block is simply empty.
"""
import re

_STOP = {"of", "the", "and", "for", "on", "in", "to", "a", "an", "&"}
_DEF = re.compile(r"((?:[A-Z][\w&/\-]*|of|the|and|for|on|in|to|&)(?:\s+(?:[A-Z][\w&/\-]*|of|the|and|for|on|in|to|&)){0,9})\s*\(\s*([A-Z][A-Za-z0-9&\-]{1,9})\s*\)")


def _letters(words):
    out = ""
    for w in words:
        if w.lower() in _STOP:
            continue
        out += w if (w.isupper() and len(w) <= 5) else w[0]
    return out.lower()


def _is_subseq(short, long):
    it = iter(long)
    return all(ch in it for ch in short)


def build_glossary(texts):
    """Return {ABBR: full name} for definitions of the form 'Full Name (ABBR)' found in texts."""
    found = {}
    for t in texts:
        for m in _DEF.finditer(t or ""):
            abbr = m.group(2)
            if sum(1 for c in abbr if c.isupper()) < 2:
                continue
            words = m.group(1).split()
            best = None
            for k in range(1, len(words) + 1):
                cand = words[-k:]
                if cand[0].lower() in _STOP:
                    continue
                lt = _letters(cand)
                if lt and lt[0] == abbr[0].lower() and _is_subseq(abbr.lower().rstrip("s"), lt):
                    best = " ".join(cand)
                    break
            if best and abbr not in found:
                found[abbr] = best
    return found


_ALIASES = {}  # BATCH2B: modified prompt text -> original clause text


def register_alias(modified_text, original_text):
    _ALIASES[modified_text] = original_text


def _clause_for_text(clause_text):
    clause_text = _ALIASES.get(clause_text, clause_text)
    try:
        from app.models.ai import Clauses
        if not clause_text:
            return None
        return Clauses.query.filter(Clauses.clause_text == clause_text).order_by(Clauses.id.desc()).first()
    except Exception:
        return None


def block_for_text(clause_text, include_split_rule=False):
    """Context block to append to a prompt, or '' if the clause cannot be identified."""
    clause = _clause_for_text(clause_text)
    if clause is None:
        return ""
    parts = []
    try:
        from app.models.ai import Clauses
        texts = [r[0] for r in Clauses.query.with_entities(Clauses.clause_text).filter_by(guideline_id=clause.guideline_id).all()]
        gl = build_glossary(texts)
        if gl:
            items = "; ".join(f"{k} = {v}" for k, v in sorted(gl.items())[:60])
            parts.append("ABBREVIATIONS DEFINED IN THIS GUIDELINE (write them exactly as the clause does; "
                         "never expand or substitute them differently): " + items)
    except Exception:
        pass
    notes = (getattr(clause, "clause_type_review_notes", None) or "").strip()
    if notes:
        parts.append("REVIEWER GUIDANCE FOR THIS CLAUSE (from the human reviewer - follow it): " + notes)
    if include_split_rule:
        parts.append("SPLIT CLAUSES: if this clause text begins with a lead-in sentence carried over from an earlier "
                     "part of the same paragraph (for example marked 'continued'), treat that lead-in as context only - "
                     "extract obligations only from the sub-items in THIS part, unless it adds something new.")
    # SIBLING-CONTEXT: a split part (e.g. "CH II 30B") gets the text of the other parts of its paragraph as context
    try:
        import re as _sc_re
        from app.models.ai import Clauses as _SC
        _m = _sc_re.match(r"^(.*?\d+)([A-Z]{1,3}|-\d+|_P\d+)$", (clause.clause_no or "").strip())
        if _m:
            _base = _m.group(1)
            _sibs = [c for c in _SC.query.filter(_SC.guideline_id == clause.guideline_id, _SC.id != clause.id).all()
                     if _sc_re.match(r"^" + _sc_re.escape(_base) + r"([A-Z]{1,3}|-\d+|_P\d+)?$", (c.clause_no or "").strip())]
            if _sibs:
                _sibs.sort(key=lambda c: c.clause_no or "")
                _txt, _used = [], 0
                for c in _sibs:
                    piece = "[" + str(c.clause_no) + "] " + (c.clause_text or "")
                    if _used + len(piece) > 4500:
                        _txt.append("[" + str(c.clause_no) + "] ... (truncated)")
                        break
                    _txt.append(piece)
                    _used += len(piece)
                parts.append("OTHER PARTS OF THE SAME PARAGRAPH (context only - their obligations are covered in those parts; "
                             "use them only to understand references such as 'the above' or '(3)(ii)'; do NOT create activities, "
                             "tests or checklist items for them): " + " || ".join(_txt))
    except Exception:
        pass
    if not parts:
        return ""
    return ("\n\n[CONTEXT FOR THIS TASK - NOT PART OF THE REGULATORY TEXT; do not extract obligations from it]\n- "
            + "\n- ".join(parts))
