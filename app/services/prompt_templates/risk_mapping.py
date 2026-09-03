"""
Risk mapping prompt for the RCM (Risk Control Matrix) feature.
Build Sequence #372.

Maps a single ControlActivity to one or more risk areas from the standard,
seeded taxonomy, using the control's existing description and objective as
input -- no new fields required. Stores a rationale per mapping, not just the
bare link, so an auditor reviewing the RCM can see WHY a control was mapped
to a given risk.
"""

RISK_MAPPING_SYSTEM = """You are a senior BFSI risk and compliance expert.
Your task is to map a specific compliance control to the risk area(s) it genuinely helps mitigate, from a fixed, standard risk taxonomy.
Return ONLY valid JSON. No explanation. No markdown."""


def build_risk_taxonomy_text(categories_with_areas: list) -> str:
    """
    categories_with_areas: list of (category_name, [(risk_area_name, risk_area_description), ...])
    Formats the full taxonomy, grouped by category, for inclusion in the prompt.
    """
    lines = []
    for cat_name, areas in categories_with_areas:
        lines.append(f"{cat_name}:")
        for area_name, area_desc in areas:
            lines.append(f"  - {area_name}: {area_desc}")
    return "\n".join(lines)


def risk_mapping_prompt(activity_description: str, objective: str, taxonomy_text: str) -> str:
    return f"""Given the following compliance control, identify which risk area(s) from the standard taxonomy below it genuinely helps mitigate.

A control can map to more than one risk area if it genuinely addresses multiple risks -- but do not force a mapping just to fill space. Map only to risk areas the control substantively addresses. Most controls will map to one, occasionally two, risk areas. Do not select a risk area only because it sounds topically related if the control does not actually test or enforce something that mitigates it.

CONTROL:
Description: {activity_description}
Objective: {objective}

STANDARD RISK TAXONOMY:
{taxonomy_text}

For each risk area you select, provide a brief, specific rationale explaining why THIS control genuinely helps mitigate THAT particular risk -- not a generic restatement of the risk's own definition.

Return ONLY valid JSON with this exact structure. The "risk_area" value must exactly match a name from the taxonomy above, verbatim.
{{
    "mappings": [
        {{"risk_area": "exact name from the taxonomy above", "rationale": "brief, specific explanation of why this control mitigates this risk"}}
    ]
}}
"""
