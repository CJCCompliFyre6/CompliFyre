# app/config/org_aliases.py
#
# Known organization name aliases for fuzzy org matching (TEST 1 — SS3).
# Used by check_org_match() in eve_step5.py.
#
# Add new aliases when auditor confirms an org match manually.
# No DB change required — just add to this file and restart.
#
# Format:
#   "canonical_short_name": ["alias1", "alias2", ...]
#
# Rules:
#   - All values lowercase
#   - canonical_short_name = shortest recognizable form
#   - aliases = all known full/variant names
#   - Used when fuzzy match score < 80% threshold

ORG_ALIASES = {
    # Indian banks
    "sbi": [
        "state bank of india",
        "state bank",
    ],
    "icici": [
        "icici bank",
        "industrial credit and investment corporation of india",
    ],
    "hdfc": [
        "hdfc bank",
        "housing development finance corporation",
    ],
    "axis": [
        "axis bank",
        "utm bank",
    ],
    "kotak": [
        "kotak mahindra bank",
        "kotak bank",
    ],
    "pnb": [
        "punjab national bank",
    ],
    "bob": [
        "bank of baroda",
    ],
    "canara": [
        "canara bank",
    ],
    "idbi": [
        "idbi bank",
        "industrial development bank of india",
    ],
    "yes": [
        "yes bank",
    ],
    "indusind": [
        "indusind bank",
    ],
    "rbl": [
        "rbl bank",
        "ratnakar bank",
    ],
    "federal": [
        "federal bank",
        "the federal bank",
    ],
    "iob": [
        "indian overseas bank",
    ],
    "uco": [
        "uco bank",
    ],
    "anixo": [
        "anixo bank",
        "anixo bank limited",
    ],
    "jk": [
        "jk bank",
        "jammu and kashmir bank",
        "the jammu and kashmir bank",
        "jammu kashmir bank",
    ],
    # International banks (common in audit context)
    "hsbc": [
        "hongkong and shanghai banking corporation",
        "the hongkong and shanghai banking corporation",
        "hongkong shanghai banking",
        "hsbc bank india",
        "hsbc bank",
    ],
    "citi": [
        "citibank",
        "citibank india",
        "citicorp",
    ],
    "sc": [
        "standard chartered",
        "standard chartered bank",
        "standard chartered bank india",
    ],
    "dbs": [
        "dbs bank",
        "dbs bank india",
        "development bank of singapore",
    ],
    "deutsche": [
        "deutsche bank",
        "deutsche bank india",
    ],
    # NBFCs
    "bajaj": [
        "bajaj finance",
        "bajaj finance limited",
        "bajaj finserv",
    ],
    "muthoot": [
        "muthoot finance",
        "muthoot finance limited",
        "muthoot fincorp",
    ],
    "manappuram": [
        "manappuram finance",
        "manappuram finance limited",
    ],
    "shriram": [
        "shriram finance",
        "shriram transport finance",
        "shriram transport finance company",
    ],
    "lic": [
        "life insurance corporation",
        "life insurance corporation of india",
    ],
    # Regulators (may appear in evidence)
    "rbi": [
        "reserve bank of india",
        "reserve bank",
    ],
    "sebi": [
        "securities and exchange board of india",
    ],
    "irdai": [
        "insurance regulatory and development authority",
        "insurance regulatory and development authority of india",
    ],
}
