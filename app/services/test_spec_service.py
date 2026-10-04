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
SPEC_VERSION = 1

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
          "eleven": 11, "twelve": 12, "fifteen": 15, "eighteen": 18, "twenty": 20, "thirty": 30, "forty": 40, "forty-five": 45,
          "fifty": 50, "sixty": 60, "seventy": 70, "ninety": 90, "hundred": 100, "half": 0.5, "quarter": 0.25}
_ENTITY_RX = re.compile(r"(entity|company|nbfc|institution)[ _-]?(type|layer|category|class|kind)|asset[ _-]?size|\blayer\b|"
                        r"upper[ _-]?layer|middle[ _-]?layer|base[ _-]?layer", re.I)
_MONEY_RX = re.compile(r"\b(loan|advance|exposure|transaction|payment|transfer|disburse|deposit|investment|provision|amount|"
                       r"credit facilit|receivable|claim)", re.I)


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
        out |= {n, n * 12, n / 12, n * 24, n / 24, n * 7, n * 30, n * 365, n / 100, n * 100}
    return out


def _traceable(x, nums):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return True
    return any(abs(x - n) < 1e-6 for n in nums)


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
        # 2. thresholds and filter values traceable to the clause
        for t in p.get("test_attributes") or []:
            if t.get("threshold") is not None and not _traceable(t["threshold"], nums):
                t["unverified"] = True
                warnings.append(f"Test '{t.get('attribute_name')}': threshold {t['threshold']} {t.get('threshold_unit') or ''} not found in the clause - unverified")
            if t.get("test_type") in ("numeric_threshold", "date_difference", "compare_fields") and not t.get("comparator"):
                t["unverified"] = True
                warnings.append(f"Test '{t.get('attribute_name')}': no comparator - direction ambiguous")
            for k in ("test_attribute", "second_attribute", "exception_identifier_attribute"):
                if t.get(k) and t[k] not in names:
                    warnings.append(f"Test '{t.get('attribute_name')}': {k} '{t[k]}' is not a defined attribute or derived value")
        for f in kept:
            v = f.get("filter_value")
            if f.get("filter_type") in ("greater_than", "greater_or_equal", "less_than", "less_or_equal") and not _traceable(v, nums):
                warnings.append(f"Filter on '{f.get('attribute')}': value {v} not found in the clause")
            if f.get("attribute") not in names:
                warnings.append(f"Filter attribute '{f.get('attribute')}' is not defined")
        if p.get("lookup_tables"):
            for n in re.findall(r"\d+(?:\.\d+)?", p["lookup_tables"]):
                if not _traceable(n, nums):
                    warnings.append(f"Lookup table value {n} not found in the clause")
        # 3. period date
        pd_attr = (p.get("period_date") or {}).get("attribute")
        if pd_attr not in attrs:
            warnings.append(f"Period date '{pd_attr}' is not a defined attribute")
        elif attrs[pd_attr].get("type") not in ("date", "datetime"):
            warnings.append(f"Period date '{pd_attr}' is not a date attribute")
        # 4. financial impact where an amount exists
        imp = p.get("impact") or {}
        amounts = [a for a, d in attrs.items() if d.get("type") == "amount"]
        if amounts and not imp.get("financial"):
            p["impact"] = {"attribute": amounts[0], "measure": f"sum of {amounts[0]} for non-compliant instances (INR)",
                           "financial": True, "fallback": imp.get("measure")}
            warnings.append(f"Impact switched to amount attribute '{amounts[0]}'")
        elif not amounts and _MONEY_RX.search(f"{p.get('dataset_name', '')} {p.get('one_row_is', '')}"):
            warnings.append("Instances appear to carry a money value but no amount attribute was requested - add one for INR impact")
        if not p.get("test_attributes"):
            warnings.append("No test attributes")
    elif mode == "document_review":
        d = spec.get("document_review") or {}
        for r in d.get("rules") or []:
            if r.get("rule_type") == "frequency" and (not r.get("period") or not r.get("min_count_per_period")):
                warnings.append(f"Frequency rule '{r.get('requirement', '')[:60]}' has no period / count per period")
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
        prompt = test_spec_prompt(clause_text, control, {"walkthrough": getattr(tp, "walkthrough", ""), "sampling": getattr(tp, "sampling", "")}, ev[:25])
        try:
            from app.services.prompt_context import block_for_text
            ctx = block_for_text(clause_text)
            if ctx:
                prompt += "\n\n" + ctx
        except Exception:
            pass
        spec = _llm(prompt)
        spec, warnings = validate_spec(spec, clause_text)
    spec["_review"] = {"status": "needs_review" if warnings else "ok", "warnings": warnings,
                       "generated_at": datetime.utcnow().isoformat(timespec="seconds"), "version": SPEC_VERSION}
    c.test_mode = spec["test_mode"]
    c.test_spec = spec
    db.session.commit()
    logger.info(f"[TEST-SPEC] control {control_id}: {spec['test_mode']} | {spec['_review']['status']} | {len(warnings)} warning(s)")
    return {"control_id": control_id, "mode": spec["test_mode"], "status": spec["_review"]["status"], "warnings": warnings}


def generate_test_spec_for_activity(comp_id: int):
    from app import db
    from app.models.ai import ControlActivity
    c = db.session.query(ControlActivity).filter_by(compliance_activity_id=comp_id).first()
    return generate_test_spec_for_control(c.id) if c else None
