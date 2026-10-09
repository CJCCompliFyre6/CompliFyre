"""
PUBLISH-REQ: after evidence consolidation, (1) make sure no bank evidence item was lost, and (2) publish the consolidated
list as EVE's evidence requirements: guideline_evidence_requirements (one per group, parents included),
raw_evidence_requirements (one per evidence item of a group) and raw_to_grouped_requirement_links (1:1).
Working papers (interview / walkthrough notes ...) are the auditor's own records and are never on the bank's list.
A guideline whose requirements are already used by a project (file mappings, flags, evidence requests ...) is never
republished automatically.
"""
import logging
import re

from sqlalchemy import text

logger = logging.getLogger(__name__)
SOURCE = "backfill_phase5_json"
WP_SQL = "NOT (COALESCE(e.category,'') ILIKE 'working paper%' OR COALESCE(e.category,'') ILIKE 'interview%')"
_SKIP_REF_TABLES = ("raw_to_grouped_requirement_links", "requirement_card_embeddings", "raw_ask_embeddings")


def _ex(q, **p):
    from app import db
    return db.session.execute(text(q), p).fetchall()


def _items(guideline_id, bank_only=False):
    """{evidence_id: (category, item, clause_id, clause_no, activity_id)} for this guideline's current evidence items."""
    rows = _ex(f"""SELECT DISTINCT ON (e.id) e.id, e.category, e.item, c.id, c.clause_no, a.activity_id
        FROM evidence_artifacts e JOIN control_evidences ce ON ce.evidence_id = e.id
        JOIN control_activities ca ON ca.id = ce.control_id JOIN compliance_activities a ON a.id = ca.compliance_activity_id
        JOIN clauses c ON c.id = a.clause_id WHERE c.guideline_id = :g {'AND ' + WP_SQL if bank_only else ''}
        ORDER BY e.id, ca.id""", g=guideline_id)
    return {r[0]: r[1:] for r in rows}


def _ids_in(groups):
    out = set()
    for g in groups or []:
        for e in (g.get("required_by") or {}).get("evidence") or []:
            try:
                out.add(int(e.get("evidence_id")))
            except (TypeError, ValueError):
                pass
    return out


def recover_missing_items(guideline_id, groups):
    """Append a group for every current bank evidence item that no group contains. Returns the number recovered."""
    bank = _items(guideline_id, bank_only=True)
    missing = sorted(set(bank) - _ids_in(groups))
    names = {g.get("evidence_item_name") for g in groups}
    for eid in missing:
        cat, item, cid, cno, aid = bank[eid]
        base = re.split(r"\s*\[", item or "")[0].strip()[:120] or f"Evidence item {eid}"
        name, k = f"{base} ({cno})", 2
        while name in names:
            name, k = f"{base} ({cno}) ({k})", k + 1
        names.add(name)
        groups.append({"evidence_item_name": name, "standard_name": name, "group_key": f"R{eid}", "parent_key": None,
                       "is_parent": False, "covers": [], "doc_class": None, "original_names": [item],
                       "recovered": True,
                       "required_by": {"guideline_ids": [str(guideline_id)], "clause_nos": [cno], "activity_ids": [str(aid)],
                                       "evidence": [{"evidence_id": str(eid), "evidence_item": item}]}})
    if missing:
        logger.warning(f"[PUBLISH-REQ] guideline {guideline_id}: consolidation had lost {len(missing)} bank evidence item(s) - "
                       f"added back as their own groups: {missing[:20]}")
    return len(missing)


def requirements_in_use(guideline_id):
    """Rows in tables (other than links/embeddings) that point at this guideline's requirement rows."""
    used = []
    refs = _ex("""SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name
        JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY' AND ccu.table_name IN ('guideline_evidence_requirements', 'raw_evidence_requirements')""")
    for t, c in refs:
        if t in _SKIP_REF_TABLES:
            continue
        n = _ex(f"""SELECT COUNT(*) FROM "{t}" WHERE "{c}" IN (SELECT id FROM guideline_evidence_requirements WHERE guideline_id = :g
                    UNION ALL SELECT id FROM raw_evidence_requirements WHERE guideline_id = :g)""", g=guideline_id)[0][0]
        if n:
            used.append(f"{t} ({n})")
    return used


def publish_requirements(guideline_id, consolidated=None, dry_run=False):
    """Build EVE's evidence requirements from the guideline's consolidated list. Returns a summary dict."""
    from app import db
    if consolidated is None:
        rec = _ex("SELECT consolidate_evidence FROM complifyre_consolidated_evidence WHERE guideline_id = :g", g=guideline_id)
        consolidated = rec[0][0] if rec else None
    groups = (consolidated or {}).get("grouped_evidences") or []
    if not groups:
        return {"status": "skipped", "reason": "no consolidated list"}
    existing = _ex("SELECT COUNT(*) FROM guideline_evidence_requirements WHERE guideline_id = :g", g=guideline_id)[0][0]
    if existing:
        used = requirements_in_use(guideline_id)
        if used:
            return {"status": "skipped", "reason": f"requirements in use by a project: {', '.join(used)}"}
    info = _items(guideline_id)
    # one requirement per name (the table allows a name once per guideline)
    by_name = {}
    for g in groups:
        n = g.get("evidence_item_name")
        if not n:
            continue
        if n in by_name:
            by_name[n]["_ev"] += (g.get("required_by") or {}).get("evidence") or []
            by_name[n]["_wp"] = by_name[n]["_wp"] or g.get("doc_class") == "interview_notes"
        else:
            by_name[n] = {"_ev": list((g.get("required_by") or {}).get("evidence") or []),
                          "_wp": g.get("doc_class") == "interview_notes" or n.lower().startswith(("interview notes", "walkthrough", "walk-through"))}
    plan, unknown = [], 0
    for n, g in by_name.items():
        seen, items = set(), []
        for e in g["_ev"]:
            try:
                eid = int(e.get("evidence_id"))
            except (TypeError, ValueError):
                unknown += 1
                continue
            if eid in seen:
                continue
            seen.add(eid)
            if eid in info:
                items.append(eid)
            else:
                unknown += 1
        plan.append((n, g["_wp"], items))
    summary = {"status": "dry_run" if dry_run else "published", "grouped": len(plan), "raw": sum(len(i) for _, _, i in plan),
               "replaced_existing": existing, "unknown_evidence_ids_skipped": unknown}
    if dry_run:
        return summary
    if existing:
        gq = "SELECT id FROM guideline_evidence_requirements WHERE guideline_id = :g"
        rq = "SELECT id FROM raw_evidence_requirements WHERE guideline_id = :g"
        for q in (f"DELETE FROM requirement_card_embeddings WHERE guideline_evidence_requirement_id IN ({gq})",
                  f"DELETE FROM raw_ask_embeddings WHERE raw_evidence_requirement_id IN ({rq})",
                  f"DELETE FROM raw_to_grouped_requirement_links WHERE guideline_evidence_requirement_id IN ({gq})",
                  "DELETE FROM raw_evidence_requirements WHERE guideline_id = :g",
                  "DELETE FROM guideline_evidence_requirements WHERE guideline_id = :g"):
            db.session.execute(text(q), {"g": guideline_id})
    for n, wp, items in plan:
        gid = db.session.execute(text("""INSERT INTO guideline_evidence_requirements (guideline_id, evidence_item_name, consolidation_source, created_at, is_working_paper)
                                         VALUES (:g, :n, :s, NOW(), :w) RETURNING id"""), {"g": guideline_id, "n": n, "s": SOURCE, "w": wp}).scalar()
        for eid in items:
            cat, item, cid, cno, _aid = info[eid]
            rid = db.session.execute(text("""INSERT INTO raw_evidence_requirements (guideline_id, clause_id, clause_no, category, evidence_item, evidence_artifact_id, created_at)
                                             VALUES (:g, :c, :n, :cat, :it, :e, NOW()) RETURNING id"""),
                                     {"g": guideline_id, "c": cid, "n": cno, "cat": cat, "it": item, "e": eid}).scalar()
            db.session.execute(text("""INSERT INTO raw_to_grouped_requirement_links (raw_evidence_requirement_id, guideline_evidence_requirement_id, merge_mechanism, created_at)
                                       VALUES (:r, :q, :s, NOW())"""), {"r": rid, "q": gid, "s": SOURCE})
    db.session.commit()
    logger.info(f"[PUBLISH-REQ] guideline {guideline_id}: {summary}")
    return summary
