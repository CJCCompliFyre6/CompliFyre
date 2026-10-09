"""
Test specification service (Phase 1 of full-population testing).
Generates the test specification for a control right after its test procedure, then runs a deterministic check
(thresholds traceable to the clause, no entity-applicability row filters, financial impact where an amount exists,
internal consistency). Any warning marks the specification "needs_review"; EVE must not execute unverified tests.
"""
import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)
SPEC_VERSION = 10
NO_FINANCIAL_BASIS = "Financial impact could not be computed as no base data was available within the audited dataset."
# messages that record an automatic clean-up (shown, but do not by themselves need a decision)
_FIX_RX = re.compile(r"^(Removed filter on|Removed entity-applicability|Dropped unused attribute|Impact switched to amount|"
                     r"Converted test|Moved test|No amount attribute|Added missing attribute|Corrected type of period date|"
                     r"Dropped presence test on identifier|Turned formula|Removed lookup table|Clarified 'not assessable'|"
                     r"Converted to design-only|Inferred comparator|Frequency rule .* treated as|Added missing attribute)|re-coded .* -> |"
                     r"accepted as a .*-level period|given its own code")

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "fifteen": 15, "eighteen": 18, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45,
          "fifty": 50, "sixty": 60, "seventy": 70, "ninety": 90, "hundred": 100, "half": 0.5, "quarter": 0.25}
_ENTITY_RX = re.compile(r"(entity|company|nbfc|institution)[ _-]?(type|layer|category|class|kind)|asset[ _-]?size|\blayer\b|"
                        r"upper[ _-]?layer|middle[ _-]?layer|base[ _-]?layer", re.I)
_MONEY_RX = re.compile(r"\b(loans?|advances?|exposures?|disburse\w*|repayments?|deposits?|investments?|receivables?|"
                       r"provisions?(?!ing)\b|amounts?|fees?|interest|premium|collateral|NPAs?|credit facilit\w*|securitisation)\b", re.I)


def _clause_numbers(text):
    nums = set()
    for m in re.findall(r"\d+(?:[.,]\d+)?", text or ""):
        try:
            nums.add(float(m.replace(",", "")))
        except ValueError:
            pass
    low = (text or "").lower()
    for w, v in _WORDS.items():
        if re.search(rf"\b{re.escape(w)}\b", low):
            nums.add(float(v))
    out = set()
    for n in nums:   # unit conversions: years<->months, days<->hours, weeks->days, percent<->fraction
        out |= {n, n * 12, n / 12, n * 24, n / 24, n * 7, n * 30, n * 365, n / 100, n * 100,
                n * 1e5, n * 1e7, n * 1e6, n * 1e9}   # lakh, crore, million, billion
    return out


_REF_RX = re.compile(r"\(\s*[0-9ivxlc]+\s*\)|(?<![\w.])\d+\.(?=\s)|\b(paragraphs?|paras?|sections?|sub-sections?|rules?|sub-rules?|clauses?|"
                     r"chapters?|annex(?:ure)?s?|regulations?|circulars?|no\.?)\s*[\dIVXLC]+[A-Z]?(\s*\(\d+\))*|\b(19|20)\d{2}\b", re.I)


def _clause_numbers_clean(text):
    """Like _clause_numbers, but list markers '(7)' / '7.', references 'paragraph 7', 'Rule 9' and years are not numbers."""
    return _clause_numbers(_REF_RX.sub(" ", text or ""))


def _traceable(x, nums):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return True
    return any(abs(x - n) < 1e-6 for n in nums)


_TOK = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


_BODIES = {"CERT-In": r"cert[\s\-_]?in", "RBI": r"\brbi\b|reserve bank", "DAKSH": r"daksh", "NHB": r"\bnhb\b|national housing bank",
           "CERSAI": r"cersai", "SEBI": r"\bsebi\b", "IRDAI": r"\birdai\b", "NABARD": r"nabard", "CIC": r"credit information compan|\bcics?\b"}


def _norm(x):
    return re.sub(r"\s+", " ", re.sub(r"[\u2018\u2019\u201c\u201d'\"]", "", str(x or "").lower())).strip()


def _words(x):
    return re.findall(r"[a-z0-9]+", _norm(x))


_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "by", "at", "be", "is", "are", "as", "its", "it", "with", "any",
         "which", "that", "this", "these", "such", "shall", "should", "from", "their"}
_LABEL_RX = re.compile(r"^\s*(clause|para(graph)?|section|sub-?para(graph)?|article|annex)\s*[\w().\-]*\s*[:\-\u2013\u2014]\s*", re.I)


_LEAD_RX = re.compile(r"^\s*(?:(?:paragraph|para|clause|section|annex)\s+[^:\u2013\u2014]{0,30}?(?:\(continued\))?\s*[:\-\u2013\u2014]\s*|(?:\(\w{1,4}\)\s*)+)", re.I)
_INTERPRET_RX = re.compile(r"interpreted as|reasonable (internal )?(standard|period|timeline)|considered appropriate|is appropriate for|"
                           r"control description|this control|the control requires|for testing|best practice", re.I)
_VAGUE_TIME_RX = re.compile(r"\b(immediately|without delay|promptly|forthwith|timely|expeditiously|at the earliest)\b", re.I)


def _prep_quote(q):
    q = _LABEL_RX.sub("", str(q or ""))
    for _ in range(2):
        q = _LEAD_RX.sub("", q)
    return q.strip(" '\"\u2018\u2019\u201c\u201d").replace("%", " per cent ")


def _quote_in_clause(q, clause_text):
    """Quote counts as found when at least 85% of its meaningful words appear in the clause in order (labels like
    'Clause 6(3):' removed, '%' = 'per cent', dashes ignored), within a window of the quote length + 40 words."""
    qw = [w for w in _words(_prep_quote(q)) if w not in _STOP]
    cw = _words(str(clause_text or "").replace("%", " per cent "))
    if not qw:
        return False
    best = 0
    for start in [i for i, w in enumerate(cw) if w == qw[0]] or [0]:
        j, hit = start, 0
        limit = start + len(qw) + 40
        for w in qw:
            k = j
            while k < min(len(cw), limit) and cw[k] != w:
                k += 1
            if k < min(len(cw), limit):
                hit += 1; j = k + 1
        best = max(best, hit)
    return best / len(qw) >= 0.85


_TAIL_RX = re.compile(r"\s+(as per|under|in accordance with|in terms of|pursuant to)\b.*$|\s*\(.*$", re.I)


def _quote_found(q, clause_text):
    if _quote_in_clause(q, clause_text):
        return True
    parts = [x for x in re.split(r"\s*(?:\.\.\.|\u2026)\s*", _prep_quote(q)) if len(_words(x)) >= 4]
    if len(parts) > 1 and all(_quote_in_clause(x, clause_text) for x in parts):
        return True
    for inner in re.findall(r"[\'\"\u2018\u201c]([^\'\"\u2019\u201d]{25,})[\'\"\u2019\u201d]", str(q or "")):
        if _quote_in_clause(inner, clause_text):
            return True
    cut = _TAIL_RX.sub("", str(q or ""))
    return len(_words(cut)) >= 6 and cut != q and _quote_in_clause(cut, clause_text)


def _quote_sentence(q, clause_text):
    qw = set(_words(q))
    sents = re.split(r"(?<=[.;:])\s+", _norm(clause_text))
    return max(sents, key=lambda x: len(qw & set(_words(x))) / (len(qw) or 1)) if sents else ""


def _check_threshold_quote(t, clause_text, warnings):
    """Threshold must quote the clause; the quote must be in the clause and contain the number; and the sentence it comes from
    must not be about a DIFFERENT body than the one the test names (e.g. a CERT-In test using the RBI 'six hours')."""
    name = t.get("attribute_name")
    q = t.get("threshold_source_quote")
    if not q:
        t["unverified"] = True; warnings.append(f"Test '{name}': threshold {t.get('threshold')} has no source quote from the clause - unverified"); return
    nq, nc = _norm(q), _norm(clause_text)
    if _INTERPRET_RX.search(str(q)):
        t["unverified"] = True; t["_move"] = "the number is the generator's own interpretation, not the clause's"
        warnings.append(f"Test '{name}': threshold {t.get('threshold')} is an interpretation, not the clause - unverified"); return
    if _VAGUE_TIME_RX.search(str(q)) and not _traceable(t.get("threshold"), _clause_numbers_clean(q)):
        t["unverified"] = True; t["_move"] = "the clause says it must be done '" + _VAGUE_TIME_RX.search(str(q)).group(1).lower() + "' - no fixed number"
        warnings.append(f"Test '{name}': threshold {t.get('threshold')} turns a non-numeric time limit into a number - unverified"); return
    if not _quote_found(q, clause_text):
        t["unverified"] = True; warnings.append(f"Test '{name}': quoted words not found in the clause - unverified"); return
    if not (_traceable(t.get("threshold"), _clause_numbers(_quote_sentence(_prep_quote(q), clause_text)))
            or _traceable(t.get("threshold"), _clause_numbers(q))):
        t["unverified"] = True; warnings.append(f"Test '{name}': the clause sentence quoted does not contain the threshold {t.get('threshold')} - unverified"); return
    sent = _quote_sentence(_prep_quote(q), clause_text)
    test_txt = " ".join(str(t.get(k) or "") for k in ("attribute_name", "test_attribute", "second_attribute", "reason_code", "pass_criteria", "fail_criteria")).lower()
    named = [b for b, rx in _BODIES.items() if re.search(rx, test_txt, re.I)]
    in_sent = [b for b, rx in _BODIES.items() if re.search(rx, sent, re.I)]
    missing = [b for b in named if b not in in_sent]
    if missing and in_sent:
        t["unverified"] = True; t["_move"] = f"the clause's number for this is stated for {', '.join(in_sent)}, not {', '.join(missing)}"
        warnings.append(f"Test '{name}': threshold comes from a sentence about {', '.join(in_sent)}, not {', '.join(missing)} - unverified")


def _rebuild_data_request(p):
    fields = []
    for a in p.get("attributes") or []:
        f = f"{a.get('column_description')} ({a.get('name')})"
        fields.append(f + (" - optional, if available" if a.get("optional") else ""))
    return (f"Full extract (CSV or Excel, not zipped) of {p.get('dataset_name')} for the entire audit period - one row per "
            f"{p.get('one_row_is')}. All rows in the period are needed (no sampling). Fields: " + "; ".join(fields) + ".")


def _clean_population(p, warnings):
    """Issues 2, 3, 4, 5: entity fields removed everywhere, contradiction check, key attributes derived, unused dropped."""
    attrs = {a.get("name"): a for a in p.get("attributes") or []}
    # 2. entity applicability fields are removed from every section
    ent = {n for n, a in attrs.items() if _ENTITY_RX.search(n or "") or _ENTITY_RX.search(str(a.get("column_description", "")))}
    if ent:
        p["attributes"] = [a for a in p["attributes"] if a.get("name") not in ent]
        p["population_filters"] = [f for f in p.get("population_filters") or [] if f.get("attribute") not in ent]
        for k in ("validation_checks", "judgement_items"):
            p[k] = [x for x in p.get(k) or [] if not any(e in x for e in ent)]
        p["analyse_exceptions_by"] = [x for x in p.get("analyse_exceptions_by") or [] if x not in ent]
        warnings.append(f"Removed entity-applicability field(s) everywhere: {', '.join(sorted(ent))}")
        cd = p.get("compliance_definition") or {}
        if re.search(r"housing finance|\bHFC|entity type|company type|layer", json.dumps(cd), re.I):
            warnings.append("Compliance wording still refers to entity applicability - reviewer to correct")
    attrs = {a.get("name"): a for a in p.get("attributes") or []}
    derived = {d.get("name"): d for d in p.get("derived_values") or []}
    def refs(name, seen=None):
        """attributes behind a name (attribute itself, or the attributes in a derived value's formula)"""
        seen = seen or set()
        if name in attrs:
            return {name}
        if name in derived and name not in seen:
            seen.add(name); out = set()
            for tok in _TOK.findall(derived[name].get("formula", "")):
                out |= refs(tok, seen)
            return out
        return set()
    tests = p.get("test_attributes") or []
    # 4. key attributes = what the tests use (directly or through derived values) + period date + identifiers
    key = set()
    for t in tests:
        for k in ("test_attribute", "second_attribute"):
            if t.get(k):
                key |= refs(t[k])
        if t.get("condition"):
            for tok in _TOK.findall(t["condition"]):
                key |= refs(tok)
        if t.get("exception_identifier_attribute") in attrs:
            key.add(t["exception_identifier_attribute"])
    pd_attr = (p.get("period_date") or {}).get("attribute")
    if pd_attr in attrs:
        key.add(pd_attr)
    if set(p.get("key_attributes") or []) != key:
        p["key_attributes"] = sorted(key)
    for n, a in attrs.items():
        a["key"] = n in key
    # 3. a value that a presence test treats as "not done" must not be listed as "not assessable"
    na = str((p.get("compliance_definition") or {}).get("not_assessable", ""))
    segments = re.split(r",\s*or\s+|;|\bor\b|,", na)
    for t in tests:
        if t.get("test_type") == "presence_check":
            for n in refs(t.get("test_attribute") or ""):
                if n == pd_attr:
                    continue
                for seg in segments:   # "present but unreadable" is the allowed case; "missing / blank / absent" contradicts
                    if n in seg and re.search(r"\b(missing|blank|absent|empty|not provided|null)\b", seg, re.I) and not re.search(r"present but", seg, re.I):
                        cd = p.setdefault("compliance_definition", {})
                        cd["not_assessable"] = (str(cd.get("not_assessable") or "").rstrip() +
                            f" Exception: a missing {n} is NOT 'not assessable' - it is non-compliance ({t.get('reason_code')}, not done).")
                        warnings.append(f"Clarified 'not assessable': a missing '{n}' is non-compliance ({t.get('reason_code')})")
                        break
    # 5. attributes no filter / test / derived value / impact / analysis / reconciliation uses are dropped
    used = set(key)
    for f in p.get("population_filters") or []:
        used |= refs(f.get("attribute") or "")
    imp = (p.get("impact") or {}).get("attribute")
    if imp:
        used |= refs(imp)
    for x in p.get("analyse_exceptions_by") or []:
        used |= refs(x)
    for r in p.get("reconciliations") or []:
        for tok in _TOK.findall(r.get("match_on", "")):
            used |= refs(tok)
    optional_kept = [n for n, a in attrs.items() if a.get("optional") and n not in used][:2]
    dropped = [n for n in attrs if n not in used and n not in optional_kept]
    if dropped:
        p["attributes"] = [a for a in p["attributes"] if a.get("name") not in dropped]
        p["judgement_items"] = [x for x in p.get("judgement_items") or [] if not any(d in x for d in dropped)]
        p["validation_checks"] = [x for x in p.get("validation_checks") or [] if not any(d in x for d in dropped)]
        warnings.append(f"Dropped unused attribute(s) from the data request: {', '.join(dropped)}")
    # reconciliations always fail with THIS control's "not done" code (the first presence test)
    not_done = next((t.get("reason_code") for t in sorted(tests, key=lambda x: x.get("testing_sequence") or 0)
                     if t.get("test_type") == "presence_check"), None)
    test_codes = {t.get("reason_code") for t in tests}
    for r in p.get("reconciliations") or []:
        if not_done and r.get("reason_code") != not_done:
            old = r.get("reason_code")
            r["reason_code"] = not_done
            warnings.append(f"Reconciliation against '{r.get('source')}' re-coded {old} -> {not_done} (this control's 'not done')")
            cd = p.get("compliance_definition") or {}
            if old not in test_codes:
                cd["non_compliant"] = [n for n in cd.get("non_compliant") or [] if n.get("reason_code") != old]
        elif not not_done:
            code = "NC0_MISSING_FROM_RECORDS"
            r["reason_code"] = code
            cd = p.setdefault("compliance_definition", {})
            if code not in {n.get("reason_code") for n in cd.get("non_compliant") or []}:
                cd.setdefault("non_compliant", []).append({"reason_code": code,
                    "meaning": "Instance found in a reconciliation source but missing from this control's own records"})
            warnings.append(f"Reconciliation against '{r.get('source')}' given its own code {code}")
    p["data_request"] = _rebuild_data_request(p)


def validate_spec(spec: dict, clause_text: str):
    """Returns (spec, warnings). Mutates spec: removes entity filters, marks unverified tests, fixes impact."""
    warnings = []
    mode = spec.get("test_mode")
    nums = _clause_numbers(clause_text)
    if mode == "population_data":
        p = spec.get("population_data") or {}
        attrs = {a.get("name"): a for a in p.get("attributes") or []}
        names = set(attrs) | {d.get("name") for d in p.get("derived_values") or []}
        # 1. entity applicability is never a row filter
        kept = []
        for f in p.get("population_filters") or []:
            a = attrs.get(f.get("attribute"), {})
            if _ENTITY_RX.search(str(f.get("attribute"))) or _ENTITY_RX.search(str(a.get("column_description", ""))):
                warnings.append(f"Removed filter on '{f.get('attribute')}': entity applicability is not a row filter")
            else:
                kept.append(f)
        p["population_filters"] = kept
        # 2-. a formula written where a field name belongs becomes a derived value
        for i, t in enumerate(p.get("test_attributes") or []):
            for k in ("test_attribute", "second_attribute"):
                v = str(t.get(k) or "")
                if v and re.search(r"[+\-*/()]", v) and " " in v.strip():
                    dn = f"derived_{k.split('_')[0]}_{i + 1}"
                    p.setdefault("derived_values", []).append({"name": dn, "formula": v, "unit": None})
                    t[k] = dn; names.add(dn)
                    warnings.append(f"Turned formula '{v[:60]}' into derived value '{dn}'")
        # 2a. a zero threshold on a time difference is a sequence test: convert to on_or_before (no number)
        derived = {d.get("name"): d for d in p.get("derived_values") or []}
        for t in p.get("test_attributes") or []:
            if t.get("threshold") is None or float(t.get("threshold") or 0) != 0.0 or t.get("test_type") not in ("date_difference", "numeric_threshold"):
                continue
            a = b = None
            if t["test_type"] == "date_difference":
                a, b = t.get("test_attribute"), t.get("second_attribute")
            else:
                m = re.match(r"\s*(hours|days|months|minutes)_between\(\s*(\w+)\s*,\s*(\w+)\s*\)", (derived.get(t.get("test_attribute")) or {}).get("formula", ""))
                if m:
                    a, b = m.group(2), m.group(3)
            if a and b and t.get("comparator") in ("<=", "<", ">=", ">"):
                first, second = (b, a) if t["comparator"] in ("<=", "<") else (a, b)   # diff = b - a
                t.update({"test_type": "on_or_before", "test_attribute": first, "second_attribute": second,
                          "threshold": None, "threshold_unit": None, "comparator": None, "threshold_source_quote": None})
                warnings.append(f"Converted test '{t.get('attribute_name')}' to a sequence check: {first} on or before {second} (no number needed)")
        # 2b-. ">= 0" is only "a value exists": a presence check; "> 0" / ">= 1" are technical and need no clause number
        for t in p.get("test_attributes") or []:
            if t.get("test_type") == "numeric_threshold" and t.get("threshold") is not None:
                thr = float(t.get("threshold") or 0)
                if thr == 0.0 and t.get("comparator") in (">=", None):
                    t.update({"test_type": "presence_check", "threshold": None, "threshold_unit": None, "comparator": None,
                              "threshold_source_quote": None})
                    warnings.append(f"Converted test '{t.get('attribute_name')}' (>= 0) to a presence check")
                elif (thr == 0.0 and t.get("comparator") in (">", "!=")) or (thr == 1.0 and t.get("comparator") == ">="):
                    t["_technical"] = True
            if t.get("test_type") == "compare_fields" and not t.get("comparator"):
                crit = str(t.get("pass_criteria") or "").lower()
                cmp_ = ("<=" if re.search(r"not exceed|no more than|at most|within|less than or equal|does not exceed", crit) else
                        ">=" if re.search(r"at least|not less than|greater than or equal|no less than", crit) else
                        "<" if re.search(r"less than|lower than|below", crit) else
                        ">" if re.search(r"greater than|more than|exceed|above", crit) else
                        "=" if re.search(r"equal|same|consistent|match|identical|no change|unchanged|agree", crit) else None)
                if cmp_:
                    t["comparator"] = cmp_
                    warnings.append(f"Inferred comparator '{cmp_}' for test '{t.get('attribute_name')}' from its pass criteria")
            for k in ("test_attribute", "second_attribute"):
                fa = t.get(k)
                if fa and fa not in names and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(fa)):
                    p.setdefault("attributes", []).append({"name": fa, "column_description": fa.replace("_", " "),
                        "type": "date" if re.search(r"date|time", fa, re.I) else
                                "amount" if re.search(r"amount|balance|outstanding|principal|exposure|value_inr|_inr$", fa, re.I) else
                                "number" if re.search(r"_days$|_count$|_percent|_ratio|_rate$|_score$|_number$", fa, re.I) else "text",
                        "key": True})
                    attrs[fa] = p["attributes"][-1]; names.add(fa)
                    warnings.append(f"Added missing attribute '{fa}' used by test '{t.get('attribute_name')}'")
        if p.get("lookup_tables"):
            vals = re.findall(r"\d+(?:\.\d+)?", p["lookup_tables"])
            bad = [v for v in vals if not any(_traceable(float(v) + d, nums) for d in (0, -1, 1))]
            if bad and len(bad) >= max(1, len(vals) // 3):
                drop_d = {d.get("name") for d in p.get("derived_values") or [] if "lookup" in str(d.get("formula", "")).lower()}
                p["derived_values"] = [d for d in p.get("derived_values") or [] if d.get("name") not in drop_d]
                p["lookup_tables"] = None
                for t in p.get("test_attributes") or []:
                    if t.get("test_attribute") in drop_d or t.get("second_attribute") in drop_d:
                        t["_move"] = "the rate / threshold table it relies on is not stated in the clause"
                warnings.append(f"Removed lookup table not in the clause ({len(bad)} of {len(vals)} values not found)")
        clean_nums = _clause_numbers_clean(clause_text)
        # 2. thresholds and filter values traceable to the clause
        for t in p.get("test_attributes") or []:
            if t.pop("_technical", False):
                continue
            if t.get("reviewer_verified"):   # v10.1: confirmed by a reviewer against the clause
                continue
            if t.get("threshold") is not None and not _traceable(t["threshold"], clean_nums):
                t["unverified"] = True; t["_move"] = "the clause states no such number"
                warnings.append(f"Test '{t.get('attribute_name')}': threshold {t['threshold']} {t.get('threshold_unit') or ''} not found in the clause - unverified")
            elif t.get("threshold") is not None and t.get("test_type") in ("numeric_threshold", "date_difference"):
                _check_threshold_quote(t, clause_text, warnings)
            if t.get("test_type") in ("numeric_threshold", "date_difference", "compare_fields") and not t.get("comparator"):
                t["unverified"] = True
                warnings.append(f"Test '{t.get('attribute_name')}': no comparator - direction ambiguous")
            for k in ("test_attribute", "second_attribute", "exception_identifier_attribute"):
                if t.get(k) and t[k] not in names:
                    warnings.append(f"Test '{t.get('attribute_name')}': {k} '{t[k]}' is not a defined attribute or derived value")
        for f in kept:
            v = f.get("filter_value")
            technical = str(v).strip() in ("0", "1", "0.0", "1.0")
            if f.get("filter_type") in ("greater_than", "greater_or_equal", "less_than", "less_or_equal") and not technical and not _traceable(v, nums):
                warnings.append(f"Filter on '{f.get('attribute')}': value {v} not found in the clause")
            fa = f.get("attribute")
            if fa and fa not in names:
                p.setdefault("attributes", []).append({"name": fa, "column_description": fa.replace("_", " "),
                                                       "type": "date" if re.search(r"date|time", fa, re.I) else
                                                               "amount" if re.search(r"amount|balance|outstanding|principal|exposure|value_inr|_inr$", fa, re.I) else "text",
                                                       "key": False})
                attrs[fa] = p["attributes"][-1]; names.add(fa)
                warnings.append(f"Added missing attribute '{fa}' used by a filter")
        # 3. period date
        pd_attr = (p.get("period_date") or {}).get("attribute")
        datey = bool(re.search(r"date|time|_on$|_at$", str(pd_attr or ""), re.I))
        yearly = bool(re.search(r"^(year|fy|financial_year|fiscal_year|reporting_year)$", str(pd_attr or ""), re.I))
        gran = "year" if yearly else ("quarter" if re.search(r"quarter", str(pd_attr or ""), re.I) else
                                      "month" if re.search(r"month", str(pd_attr or ""), re.I) else None)
        if gran and not datey and (pd_attr not in attrs or attrs[pd_attr].get("type") not in ("date", "datetime")):
            if pd_attr not in attrs:
                p.setdefault("attributes", []).append({"name": pd_attr, "column_description": pd_attr.replace("_", " "), "type": "text", "key": True})
                attrs[pd_attr] = p["attributes"][-1]; names.add(pd_attr)
            p["period_date"]["granularity"] = gran
            warnings.append(f"Period date '{pd_attr}' accepted as a {gran}-level period")
        elif yearly:
            if pd_attr not in attrs:
                p.setdefault("attributes", []).append({"name": pd_attr, "column_description": pd_attr.replace("_", " "), "type": "number", "key": True})
                attrs[pd_attr] = p["attributes"][-1]; names.add(pd_attr)
            p["period_date"]["granularity"] = "year"
            warnings.append(f"Period date '{pd_attr}' accepted as a year-level period")
        elif pd_attr not in attrs:
            if datey:
                p.setdefault("attributes", []).append({"name": pd_attr, "column_description": pd_attr.replace("_", " "), "type": "date", "key": True})
                attrs[pd_attr] = p["attributes"][-1]; names.add(pd_attr)
                warnings.append(f"Added missing attribute '{pd_attr}' used as the period date")
            else:
                warnings.append(f"Period date '{pd_attr}' is not a defined attribute")
        elif attrs[pd_attr].get("type") not in ("date", "datetime"):
            if datey:
                attrs[pd_attr]["type"] = "datetime" if re.search(r"time", pd_attr, re.I) else "date"
                warnings.append(f"Corrected type of period date '{pd_attr}' to {attrs[pd_attr]['type']}")
            else:
                warnings.append(f"Period date '{pd_attr}' is not a date attribute")
        # 4. financial impact where an amount exists
        imp = p.get("impact") or {}
        amounts = [a for a, d in attrs.items() if d.get("type") == "amount"]
        if amounts and not imp.get("financial"):
            p["impact"] = {"attribute": amounts[0], "measure": f"sum of {amounts[0]} for non-compliant instances (INR)",
                           "financial": True, "fallback": imp.get("measure")}
            warnings.append(f"Impact switched to amount attribute '{amounts[0]}'")
        elif not amounts and _MONEY_RX.search(f"{p.get('dataset_name', '')} {p.get('one_row_is', '')}"):
            p["impact"] = dict(p.get("impact") or {}, financial=False, no_financial_basis=NO_FINANCIAL_BASIS)
            warnings.append("No amount attribute for these financial records - impact will state: " + NO_FINANCIAL_BASIS)
        if amounts and (p.get("impact") or {}).get("financial"):
            # used by EVE (Phase 2) when the bank's file turns out to have no such column
            p["impact"]["if_amount_column_missing"] = NO_FINANCIAL_BASIS
        # 2b. clearly invented deadlines leave the tests and become judgement items
        kept_tests = []
        for t in p.get("test_attributes") or []:
            why = t.pop("_move", None)
            if why:
                warnings[:] = [w for w in warnings if not w.startswith(f"Test '{t.get('attribute_name')}': threshold")]
                p.setdefault("judgement_items", []).append(
                    f"{t.get('attribute_name')}: {why} - assess against the bank's own SLA / policy, if any")
                warnings.append(f"Moved test '{t.get('attribute_name')}' ({t.get('threshold')} {t.get('threshold_unit') or ''}) to judgement items: {why}")
            else:
                kept_tests.append(t)
        if len(kept_tests) != len(p.get("test_attributes") or []):
            used_codes = {t.get("reason_code") for t in kept_tests}
            cd = p.get("compliance_definition") or {}
            gone = {t.get("reason_code") for t in p["test_attributes"]} - used_codes
            cd["non_compliant"] = [n for n in cd.get("non_compliant") or [] if n.get("reason_code") not in gone]
            p["test_attributes"] = kept_tests
        ids = {t.get("exception_identifier_attribute") for t in p.get("test_attributes") or []}
        keep = []
        for t in p.get("test_attributes") or []:
            if t.get("test_type") == "presence_check" and t.get("test_attribute") in ids:
                warnings.append(f"Dropped presence test on identifier '{t.get('test_attribute')}' (a missing identifier is not assessable)")
            else:
                keep.append(t)
        if len(keep) != len(p.get("test_attributes") or []):
            gone = {t.get("reason_code") for t in p["test_attributes"]} - {t.get("reason_code") for t in keep}
            cd = p.get("compliance_definition") or {}
            cd["non_compliant"] = [n for n in cd.get("non_compliant") or [] if n.get("reason_code") not in gone]
            p["test_attributes"] = keep
        if not p.get("test_attributes"):
            checks = list(p.get("judgement_items") or []) + [
                "Operating effectiveness: the clause states no per-instance rule that can be tested on data - assess by auditor judgement"]
            spec["design_only"] = {"documents_required": [p.get("data_request") or p.get("dataset_name") or "Records of the control's operation"],
                                   "checks": checks}
            spec["test_mode"] = "design_only"
            spec["population_data"] = None
            warnings.append("Converted to design-only: no per-instance test left after removing invented thresholds")
            return spec, warnings
        from app.services.prompt_templates.test_spec import FILTER_TYPES, TEST_TYPES, COMPARATORS
        for f in p.get("population_filters") or []:
            if f.get("filter_type") not in FILTER_TYPES:
                warnings.append(f"Filter on '{f.get('attribute')}': unknown filter type '{f.get('filter_type')}' - reviewer to set")
        for t in p.get("test_attributes") or []:
            if t.get("test_type") not in TEST_TYPES:
                t["unverified"] = True
                warnings.append(f"Test '{t.get('attribute_name')}': unknown test type '{t.get('test_type')}' - unverified")
            if t.get("comparator") and t["comparator"] not in COMPARATORS:
                t["unverified"] = True
                warnings.append(f"Test '{t.get('attribute_name')}': unknown comparator '{t.get('comparator')}' - unverified")
        _clean_population(p, warnings)
    elif mode == "document_review":
        d = spec.get("document_review") or {}
        for r in d.get("rules") or []:
            if r.get("rule_type") == "frequency" and (not r.get("period") or not r.get("min_count_per_period")):
                req = str(r.get("requirement") or "").lower()
                per = ("monthly" if re.search(r"month", req) else "quarterly" if re.search(r"quarter", req) else
                       "half_yearly" if re.search(r"half|six month", req) else "annually" if re.search(r"annual|year", req) else None)
                if per:
                    r["period"] = r.get("period") or per; r["min_count_per_period"] = r.get("min_count_per_period") or 1
                    warnings.append(f"Frequency rule '{req[:50]}' treated as at least 1 per {per} (from its wording)")
                else:
                    r["rule_type"] = "other"; r["source"] = "tor_or_charter"
                    r["requirement"] = str(r.get("requirement") or "") + " (no fixed period in the clause - verify against the NBFC's own policy / each event)"
                    warnings.append(f"Frequency rule '{req[:50]}' treated as policy- or event-based (no fixed period in the clause)")
        if not d.get("rules"):
            warnings.append("No rules")
    elif mode != "design_only":
        warnings.append(f"Unknown test mode '{mode}'")
    return spec, warnings


def _llm(prompt):
    from app.services.prompt_templates.test_spec import TestSpec
    try:
        from app.services.model_response import extract_structured_info_2
        r = extract_structured_info_2(prompt, TestSpec)
        if r is not None:
            return r.model_dump() if hasattr(r, "model_dump") else dict(r)
    except Exception as e:
        logger.warning(f"[TEST-SPEC] structured call failed, falling back: {str(e)[:150]}")
    from app.services.model_response import _call_llm_json_raw
    raw = _call_llm_json_raw(system_msg="Return ONLY valid JSON. No markdown.",
                             user_msg=prompt + "\n\nJSON schema:\n" + json.dumps(TestSpec.model_json_schema()))
    return TestSpec.model_validate(raw).model_dump()


def _evidence_items(control):
    out = []
    for e in (control.evidences or []):
        cat, item = getattr(e, "category", "") or "", getattr(e, "item", "") or str(e)
        if "working paper" in cat.lower() or re.search(r"\b(interview|walkthrough)\b", item, re.I):
            continue
        out.append(f"[{cat}] {item}" if cat else item)
    return out


def generate_test_spec_for_control(control_id: int) -> dict:
    """Generate, check and store the test specification for one control. Returns a small summary."""
    from app import db
    from app.models.ai import ControlActivity, ComplianceActivities, Clauses
    from app.services.prompt_templates.test_spec import test_spec_prompt
    c = db.session.get(ControlActivity, control_id)
    if not c:
        return {"control_id": control_id, "status": "missing"}
    act = db.session.get(ComplianceActivities, c.compliance_activity_id)
    cl = db.session.get(Clauses, act.clause_id) if act else None
    clause_text = cl.clause_text if cl else ""
    ev = _evidence_items(c)
    if not c.dimension_operating:
        tp = c.test_procedure
        spec = {"test_mode": "design_only",
                "rationale": "Operating effectiveness is not tested for this control (design / implementation only).",
                "design_only": {"documents_required": ev,
                                "checks": [s for s in re.split(r"(?<=[.;])\s+", getattr(tp, "walkthrough", "") or "") if s][:8]}}
        warnings = []
    else:
        tp = c.test_procedure
        control = {k: getattr(c, k, None) for k in ("activity_name", "activity_description", "frequency", "control_type",
                                                   "dimension_design", "dimension_implementation", "dimension_operating")}
        others = [f"[{o.activity_id}] {o.activity_description}" for o in
                  db.session.query(ComplianceActivities).filter(ComplianceActivities.clause_id == act.clause_id,
                                                               ComplianceActivities.id != act.id).all()] if act else []
        prompt = test_spec_prompt(clause_text, control, {"walkthrough": getattr(tp, "walkthrough", ""), "sampling": getattr(tp, "sampling", "")}, ev[:25], others)
        try:
            from app.services.prompt_context import block_for_text
            ctx = block_for_text(clause_text)
            if ctx:
                prompt += "\n\n" + ctx
        except Exception:
            pass
        spec = _llm(prompt)
        if (spec or {}).get("test_mode") not in ("population_data", "document_review", "design_only"):
            logger.warning(f"[TEST-SPEC] control {control_id}: no test mode returned - retrying once")
            spec = _llm(prompt)
            if (spec or {}).get("test_mode") not in ("population_data", "document_review", "design_only"):
                raise ValueError("model returned no test_mode twice")
        spec, warnings = validate_spec(spec, clause_text)
    fixes = [w for w in warnings if _FIX_RX.search(w)]
    warnings = [w for w in warnings if not _FIX_RX.search(w)]
    spec["_review"] = {"status": "needs_review" if warnings else "ok", "warnings": warnings, "auto_fixes": fixes,
                       "generated_at": datetime.utcnow().isoformat(timespec="seconds"), "version": SPEC_VERSION}
    c.test_mode = spec["test_mode"]
    c.test_spec = spec
    db.session.commit()
    logger.info(f"[TEST-SPEC] control {control_id}: {spec['test_mode']} | {spec['_review']['status']} | {len(warnings)} warning(s)")
    return {"control_id": control_id, "mode": spec["test_mode"], "status": spec["_review"]["status"], "warnings": warnings, "auto_fixes": fixes}


def generate_test_spec_for_activity(comp_id: int):
    from app import db
    from app.models.ai import ControlActivity
    c = db.session.query(ControlActivity).filter_by(compliance_activity_id=comp_id).first()
    return generate_test_spec_for_control(c.id) if c else None



def recheck_test_spec(control_id: int) -> dict:
    """Re-apply the CURRENT check to a stored specification - no AI call. Earlier automatic fixes are kept."""
    from app import db
    from app.models.ai import ControlActivity, ComplianceActivities, Clauses
    import copy
    c = db.session.get(ControlActivity, control_id)
    if not c or not isinstance(c.test_spec, dict):
        return {"control_id": control_id, "status": "no specification"}
    spec = copy.deepcopy(c.test_spec)
    old = spec.pop("_review", {}) or {}
    if spec.get("test_mode") == "design_only":
        warnings = []
    else:
        for t in (spec.get("population_data") or {}).get("test_attributes") or []:
            t.pop("unverified", None)
        act = db.session.get(ComplianceActivities, c.compliance_activity_id)
        cl = db.session.get(Clauses, act.clause_id) if act else None
        spec, warnings = validate_spec(spec, cl.clause_text if cl else "")
    fixes = list(dict.fromkeys((old.get("auto_fixes") or []) + [w for w in warnings if _FIX_RX.search(w)]))
    warnings = [w for w in warnings if not _FIX_RX.search(w)]
    spec["_review"] = {"status": "needs_review" if warnings else "ok", "warnings": warnings, "auto_fixes": fixes,
                       "generated_at": old.get("generated_at"), "rechecked_at": datetime.utcnow().isoformat(timespec="seconds"),
                       "version": SPEC_VERSION}
    c.test_spec = spec
    if spec.get("test_mode") and getattr(c, "test_mode", None) != spec["test_mode"]:
        c.test_mode = spec["test_mode"]
    db.session.commit()
    return {"control_id": control_id, "mode": spec.get("test_mode"), "status": spec["_review"]["status"], "warnings": warnings}
