"""
CompliFyre — Stage 3: Clause Post Processor
============================================
Rule-based post processing after Stage 2 LLM semantic analysis.

Responsibilities:
1. Apply merge decisions — MERGE_PARENT nodes folded into parent text
2. Resolve applicability — INHERITS filled from parent context
3. Backward correction — fix earlier clauses if later clause updates applicability
4. Validate clause_no uniqueness
5. Check license codes against master list — flag unknowns
6. Save to DB
"""

import json
import logging
from datetime import datetime
from app.models.ai import Clauses, Guidelines, db
from app.models.re import RegulatorLicenses
from sqlalchemy import text

logger = logging.getLogger(__name__)


def get_known_license_codes() -> set:
    """Fetch all active license codes from master table."""
    try:
        licenses = RegulatorLicenses.query.filter_by(is_active=True).all()
        return {l.license_code for l in licenses}
    except Exception as e:
        logger.error(f"Stage 3: Failed to fetch license codes: {e}")
        return set()


def apply_merges(nodes: list, stage2_results: dict) -> list:
    """
    Fold MERGE_PARENT nodes into their parent's text.
    Returns cleaned node list with merged nodes removed.
    
    Args:
        nodes: Stage 1 nodes list
        stage2_results: dict of clause_no -> stage2 LLM output
    """
    # Build lookup
    node_map = {n['clause_no']: n for n in nodes if n['clause_no']}
    
    # Track which nodes to remove after merging
    to_remove = set()
    
    for node in nodes:
        clause_no = node.get('clause_no')
        if not clause_no:
            continue
            
        s2 = stage2_results.get(clause_no, {})
        merge_decision = s2.get('merge_decision', 'STANDALONE')
        node_type = node.get('node_type', '')
        
        # Provisos and explanations always merge into parent
        if node_type in ('proviso', 'explanation'):
            merge_decision = 'MERGE_PARENT'
        
        if merge_decision == 'MERGE_PARENT':
            parent_no = node.get('parent_clause_no')
            if parent_no and parent_no in node_map:
                parent = node_map[parent_no]
                # Append this node's text to parent
                parent['raw_text'] = parent['raw_text'] + ' ' + node['raw_text']
                to_remove.add(clause_no)
                logger.debug(f"Stage 3: Merged {clause_no} into {parent_no}")
            else:
                logger.warning(f"Stage 3: MERGE_PARENT for {clause_no} but parent {parent_no} not found — keeping standalone")
    
    # Remove merged nodes
    result = [n for n in nodes if n.get('clause_no') not in to_remove]
    logger.info(f"Stage 3: {len(to_remove)} nodes merged, {len(result)} nodes remaining")
    return result


def resolve_applicability(nodes: list, stage2_results: dict, guideline_licenses: list) -> list:
    """
    Resolve applicable_to for each node:
    - INHERITS → copy from nearest parent with SPECIFIC applicability, or from guideline
    - SPECIFIC → use as-is, validate against known codes
    - UNKNOWN → flag
    """
    known_codes = get_known_license_codes()
    
    # Build applicability context — section_no → applicable_to list
    applicability_map = {}
    
    # Seed with guideline-level applicability
    applicability_map['__guideline__'] = guideline_licenses
    
    for node in nodes:
        clause_no = node.get('clause_no')
        if not clause_no:
            continue
        
        s2 = stage2_results.get(clause_no, {})
        applicable_to_decision = s2.get('applicable_to', 'INHERITS')
        applicable_to_licenses = s2.get('applicable_to_licenses', [])
        
        if applicable_to_decision == 'SPECIFIC' and applicable_to_licenses:
            # Validate codes against known list
            unknown_codes = [c for c in applicable_to_licenses if c not in known_codes]
            if unknown_codes:
                node['applicable_to'] = applicable_to_licenses
                node['extraction_status'] = 'FLAGGED'
                node['flag_reason'] = f'UNKNOWN_LICENSE: {", ".join(unknown_codes)}'
                logger.warning(f"Stage 3: Unknown license codes for {clause_no}: {unknown_codes}")
            else:
                node['applicable_to'] = applicable_to_licenses
                
            # Update context map for children
            if s2.get('applicability_updates_context') and s2.get('new_context_entry'):
                ctx = s2['new_context_entry']
                scope = ctx.get('scope', clause_no)
                applicability_map[scope] = applicable_to_licenses
                
        elif applicable_to_decision == 'UNKNOWN':
            node['applicable_to'] = None
            node['extraction_status'] = 'FLAGGED'
            unknown_desc = s2.get('applicable_to_unknown', 'Unknown entity type')
            node['flag_reason'] = f'UNKNOWN_APPLICABILITY: {unknown_desc}'
            logger.warning(f"Stage 3: Unknown applicability for {clause_no}: {unknown_desc}")
            
        else:  # INHERITS
            # Find nearest parent with specific applicability
            inherited = _find_inherited_applicability(node, applicability_map, guideline_licenses)
            node['applicable_to'] = inherited if inherited != guideline_licenses else None
            # NULL means inherits from guideline — cleaner in DB
    
    return nodes


def _find_inherited_applicability(node: dict, applicability_map: dict, guideline_licenses: list) -> list:
    """Walk up parent chain to find applicable_to."""
    parent_no = node.get('parent_clause_no')
    
    while parent_no:
        if parent_no in applicability_map:
            return applicability_map[parent_no]
        # Go up one more level — strip last component
        parts = parent_no.rsplit(' ', 1)
        parent_no = parts[0] if len(parts) > 1 else None
    
    return guideline_licenses


def backward_correct(nodes: list, stage2_results: dict) -> list:
    """
    If a later clause updates applicability for a section,
    go back and correct earlier clauses in that section.
    
    Example: clause 11(f) says "all of clause 11 applies to SEBI_LE_EQ only"
    → correct all 11(a) through 11(e) that were tagged INHERITS
    """
    # Build index of clause_no → node
    node_map = {n['clause_no']: n for n in nodes if n['clause_no']}
    
    for node in nodes:
        clause_no = node.get('clause_no')
        s2 = stage2_results.get(clause_no, {})
        
        if not s2.get('applicability_updates_context'):
            continue
            
        ctx = s2.get('new_context_entry', {})
        scope = ctx.get('scope')
        inheritance = ctx.get('inheritance', 'this_clause_only')
        new_applies_to = ctx.get('applies_to', [])
        
        if not scope or not new_applies_to or inheritance == 'this_clause_only':
            continue
        
        # Find all earlier nodes that share the same parent scope
        for earlier_node in nodes:
            en_no = earlier_node.get('clause_no', '')
            if not en_no:
                continue
            # Check if this node is a sibling (same parent prefix)
            if en_no == clause_no:
                continue
            if en_no.startswith(scope) and earlier_node.get('applicable_to') is None:
                earlier_node['applicable_to'] = new_applies_to
                logger.info(f"Stage 3: Backward corrected {en_no} applicability to {new_applies_to}")
    
    return nodes


def resolve_references(nodes: list, stage2_results: dict, guideline_id: int) -> list:
    """
    Attach clause_references from Stage 2 output to each node.
    Flag CROSS_GUIDELINE and EXTERNAL references.
    """
    for node in nodes:
        clause_no = node.get('clause_no')
        if not clause_no:
            continue
        
        s2 = stage2_results.get(clause_no, {})
        refs = s2.get('clause_references', [])
        
        if not refs:
            node['clause_references'] = None
            continue
        
        processed_refs = []
        has_cross_guideline = False
        has_external = False
        
        for ref in refs:
            ref_type = ref.get('type', 'INTERNAL')
            
            if ref_type == 'INTERNAL':
                # Set guideline_id for internal refs
                ref['guideline_id'] = guideline_id
                processed_refs.append(ref)
                
            elif ref_type == 'CROSS_GUIDELINE':
                processed_refs.append(ref)
                has_cross_guideline = True
                
            elif ref_type == 'EXTERNAL':
                processed_refs.append(ref)
                has_external = True
        
        node['clause_references'] = processed_refs if processed_refs else None
        
        # Flag if cross-guideline or external refs need human review
        if has_cross_guideline and node.get('extraction_status') != 'FLAGGED':
            node['extraction_status'] = 'FLAGGED'
            node['flag_reason'] = 'CROSS_GUIDELINE_REF: requires manual linking'
        elif has_external and node.get('extraction_status') != 'FLAGGED':
            existing_flag = node.get('flag_reason', '')
            if not existing_flag:
                node['flag_reason'] = 'EXTERNAL_REF: references external standard'
    
    return nodes


def validate_uniqueness(nodes: list) -> tuple:
    """Check for duplicate clause_nos. Returns (valid_nodes, duplicate_issues)."""
    seen = {}
    valid = []
    issues = []
    
    for node in nodes:
        clause_no = node.get('clause_no')
        if not clause_no:
            continue
        if clause_no in seen:
            issues.append(f"Duplicate: {clause_no} on pages {seen[clause_no]} and {node['page_number']}")
            # Keep first occurrence
            continue
        seen[clause_no] = node['page_number']
        valid.append(node)
    
    if issues:
        logger.warning(f"Stage 3: {len(issues)} duplicate clause_nos found")
    
    return valid, issues


def save_to_db(nodes: list, stage2_results: dict, guideline_id: int) -> dict:
    """
    Save all processed nodes to clauses table.
    Returns summary dict.
    """
    saved = 0
    flagged = 0
    errors = []
    
    for node in nodes:
        clause_no = node.get('clause_no')
        raw_text = node.get('raw_text', '').strip()
        
        if not clause_no or not raw_text:
            continue
        
        s2 = stage2_results.get(clause_no, {})
        clause_type = s2.get('clause_type', 'OBLIGATION')
        extraction_status = node.get('extraction_status', 'EXTRACTED')
        flag_reason = node.get('flag_reason')
        
        if flag_reason and extraction_status != 'FLAGGED':
            extraction_status = 'FLAGGED'
        
        if extraction_status == 'FLAGGED':
            flagged += 1
        
        try:
            clause = Clauses(
                clause_no=clause_no,
                clause_text=raw_text,
                guideline_id=guideline_id,
                page_number=node.get('page_number'),
                clause_type=clause_type,
                applicable_to=node.get('applicable_to'),
                clause_references=node.get('clause_references'),
                extraction_status=extraction_status,
                flag_reason=flag_reason,
            )
            db.session.add(clause)
            saved += 1
            
        except Exception as e:
            errors.append(f"Failed to save {clause_no}: {str(e)}")
            logger.error(f"Stage 3: DB save failed for {clause_no}: {e}")
    
    try:
        db.session.commit()
        logger.info(f"Stage 3: Saved {saved} clauses ({flagged} flagged)")
    except Exception as e:
        db.session.rollback()
        logger.error(f"Stage 3: DB commit failed: {e}")
        raise
    
    return {
        'saved': saved,
        'flagged': flagged,
        'errors': errors,
    }


def post_process_nodes(
    nodes: list,
    stage2_results: dict,
    guideline_id: int,
    guideline_licenses: list
) -> dict:
    """
    Main entry point for Stage 3.
    
    Args:
        nodes: Stage 1 nodes
        stage2_results: dict of clause_no -> Stage 2 LLM output
        guideline_id: DB id of guideline
        guideline_licenses: list of license codes for this guideline
    
    Returns:
        summary dict with counts and issues
    """
    logger.info(f"Stage 3: Post-processing {len(nodes)} nodes for guideline {guideline_id}")
    
    # Step 1: Apply merge decisions
    nodes = apply_merges(nodes, stage2_results)
    
    # Step 2: Resolve applicability
    nodes = resolve_applicability(nodes, stage2_results, guideline_licenses)
    
    # Step 3: Backward correction
    nodes = backward_correct(nodes, stage2_results)
    
    # Step 4: Resolve references
    nodes = resolve_references(nodes, stage2_results, guideline_id)
    
    # Step 5: Validate uniqueness
    nodes, duplicate_issues = validate_uniqueness(nodes)
    
    # Step 6: Save to DB
    save_summary = save_to_db(nodes, stage2_results, guideline_id)
    
    summary = {
        'total_nodes_after_merge': len(nodes),
        'saved': save_summary['saved'],
        'flagged': save_summary['flagged'],
        'duplicate_issues': duplicate_issues,
        'save_errors': save_summary['errors'],
    }
    
    logger.info(f"Stage 3 complete: {summary}")
    return summary
