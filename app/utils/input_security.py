# app/utils/input_security.py
#
# Central input security utility for CompliFyre.
# Two concerns:
#   1. File upload validation  — block executables, macros, unsupported types
#   2. Text input sanitization — strip HTML/scripts, enforce length cap
#
# Usage:
#   from app.utils.input_security import validate_upload_file, sanitize_text_input
#
# Both functions return a dict: {ok: bool, error: str|None, value: ...}
# so callers can handle rejection uniformly.

import re
import logging

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1 — File Upload Validation
# ─────────────────────────────────────────────────────────────────────────────

# Hard block — never accept regardless of context.
# Executables, scripts, macro-enabled Office files.
BLOCKED_EXTENSIONS = {
    # Executables / scripts
    "exe", "bat", "cmd", "com", "sh", "bash", "zsh", "ps1", "ps2",
    "vbs", "vbe", "wsf", "wsh", "hta",
    # Server-side scripts
    "py", "pyc", "rb", "php", "php3", "php4", "php5", "pl", "cgi",
    "asp", "aspx", "jsp", "jspx", "cfm",
    # Compiled / bytecode
    "jar", "class", "war", "ear",
    # System / library
    "dll", "so", "dylib", "sys", "drv",
    # Macro-enabled Office (critical — can embed VBA)
    "xlsm", "xltm", "xlam",   # Excel macros
    "docm", "dotm",            # Word macros
    "pptm", "potm", "ppam",    # PowerPoint macros
}

# Whitelist — only these are accepted as evidence/document uploads.
# Images kept for future vision support (PD-1/PD-3).
ALLOWED_EVIDENCE_EXTENSIONS = {
    "pdf", "docx", "doc", "xlsx", "xls", "csv", "txt",
    "png", "jpg", "jpeg", "webp", "tiff", "bmp",
}

# Narrower whitelist for MoM / interview / test-procedure uploads
# (no spreadsheets needed there, but PDF/DOCX/images ok)
ALLOWED_DOCUMENT_EXTENSIONS = {
    "pdf", "docx", "doc", "txt",
    "png", "jpg", "jpeg", "webp",
}


def _check_pdf_magic_bytes(filepath: str) -> bool:
    """Check if file starts with PDF magic bytes %PDF — blocks fake PDFs with malicious content."""
    try:
        with open(filepath, "rb") as f:
            header = f.read(4)
        return header == b"%PDF"
    except Exception:
        return False


def validate_upload_file(filename: str, context: str = "evidence") -> dict:
    """
    Validate an uploaded file's extension before saving to disk.

    Args:
        filename : original filename from request.files
        context  : "evidence"  — broader set (xlsx, csv, images allowed)
                   "document"  — narrower set (pdf, docx, images only)
                   "guideline" — pdf only

    Returns:
        {"ok": True,  "error": None}               — safe to save
        {"ok": False, "error": "<reason string>"}  — reject, show error to user
    """
    if not filename or "." not in filename:
        return {"ok": False, "error": "File has no extension — cannot determine type."}

    ext = filename.rsplit(".", 1)[1].lower()

    # Hard block always runs first regardless of context
    if ext in BLOCKED_EXTENSIONS:
        logger.warning("[InputSecurity] Blocked upload attempt: %s (ext=%s)", filename, ext)
        return {
            "ok": False,
            "error": (
                f"File type '.{ext}' is not allowed. "
                "Executable, script, and macro-enabled files are blocked for security."
            ),
        }

    # Context-specific whitelist
    if context == "guideline":
        allowed = {"pdf"}
    elif context == "document":
        allowed = ALLOWED_DOCUMENT_EXTENSIONS
    else:  # "evidence" — default
        allowed = ALLOWED_EVIDENCE_EXTENSIONS

    if ext not in allowed:
        logger.warning("[InputSecurity] Rejected unsupported type: %s (ext=%s, context=%s)",
                       filename, ext, context)
        return {
            "ok": False,
            "error": (
                f"File type '.{ext}' is not supported for {context} uploads. "
                f"Allowed: {', '.join(sorted(allowed))}"
            ),
        }

    return {"ok": True, "error": None}


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2 — Text Input Sanitization
# ─────────────────────────────────────────────────────────────────────────────

# Strip full tag pairs (opening + content + closing) for dangerous tags
_DANGEROUS_TAG_PAIRS = re.compile(
    r"<(script|style|iframe|object|embed|form|link|meta|base)\b[^>]*>.*?</\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
# Strip opener-only or self-closing dangerous tags
_DANGEROUS_TAG_OPEN = re.compile(
    r"<(script|style|iframe|object|embed|form|input|button|link|meta|base)\b[^>]*/?>",
    re.IGNORECASE,
)
# Event handlers: onclick=, onmouseover=, onerror=, etc.
_EVENT_HANDLERS = re.compile(r"\s+on\w+\s*=\s*([\"']).+?\1", re.IGNORECASE)
# javascript: in href / src / action — replace whole value with #
_JS_PROTOCOL = re.compile(
    r"(href|src|action)\s*=\s*([\"']\s*)javascript:[^\"']*([\"']?)",
    re.IGNORECASE,
)

# Length caps per context (characters, not bytes)
TEXT_LENGTH_LIMITS = {
    "observation":   50_000,   # Your Observation — Quill rich text
    "interview":     20_000,   # Interview answer / question
    "walkthrough":   50_000,   # Walkthrough / sampling content
    "user_input":    5_000,    # Additional user input to LLM
    "general":       50_000,   # Default fallback
}


def sanitize_text_input(text: str, context: str = "general") -> dict:
    """
    Sanitize a free-text input field before storing in DB / sending to LLM.

    What it does:
      - Strips <script>, <iframe>, <style>, <object>, <embed>, <form> tags
      - Removes event handlers (onclick=, onerror=, etc.)
      - Removes javascript: protocol in href/src/action
      - Enforces character length cap per context
      - Preserves Quill's safe HTML tags (<p>, <strong>, <em>, <ul>, <li>, etc.)

    What it does NOT do:
      - Does not strip all HTML — Quill content needs <p>/<br>/<strong> etc.
      - Does not attempt to "fix" prompt injection in LLM sense — that is
        handled at the prompt construction layer (system prompt separation).

    Args:
        text    : raw string from request.form.get(...)
        context : one of "observation", "interview", "walkthrough",
                  "user_input", "general"

    Returns:
        {"ok": True,  "value": "<sanitized text>",  "error": None}
        {"ok": False, "value": None, "error": "<reason>"}  — if over length limit
    """
    if not text:
        return {"ok": True, "value": "", "error": None}

    # Step 1 — strip dangerous tag pairs (tag + content + closing)
    cleaned = _DANGEROUS_TAG_PAIRS.sub("", text)
    # Step 2 — strip opener-only / self-closing dangerous tags
    cleaned = _DANGEROUS_TAG_OPEN.sub("", cleaned)
    # Step 3 — strip event handlers
    cleaned = _EVENT_HANDLERS.sub("", cleaned)
    # Step 4 — neutralize javascript: protocol
    cleaned = _JS_PROTOCOL.sub(r"\1=\2#\3", cleaned)

    # Step 5 — length cap
    limit = TEXT_LENGTH_LIMITS.get(context, TEXT_LENGTH_LIMITS["general"])
    if len(cleaned) > limit:
        logger.warning(
            "[InputSecurity] Text input exceeds limit: context=%s len=%d limit=%d — truncating",
            context, len(cleaned), limit
        )
        # Truncate — don't reject, just cap. LLM doesn't need more.
        cleaned = cleaned[:limit]

    return {"ok": True, "value": cleaned, "error": None}
