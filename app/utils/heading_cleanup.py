import re

# A section heading glued to the end of a clause, e.g.
#   "... is made. C. Origination Standards"
#   "... on an ongoing basis. A.10 Voting and enforcement rights"
#   "... not been repealed. B. Application of other laws not barred"
# The tail must follow sentence-ending punctuation, start with a section marker
# (A. / B.2 / C.15.1 / optional "Chapter IV –"), and must NOT itself end like a sentence.
_TRAIL = re.compile(
    r"""(?<=[.;:)”"’])\s+
        (?P<h>
          (?:Chapter\s+[IVXLC]+\s*[-–—]?\s*        # "Chapter IV –" heading, or
             |[A-Z](?:\.\d{1,2}){0,2}\.?\s+)        # A.  / A.1 / B.2 / C.15.1 marker
          [A-Z(][^.;:!?]{2,120}?                   # heading words, no sentence punctuation
        )\s*$""",
    re.VERBOSE,
)

def _norm(s):
    return re.sub(r"\s+", " ", s or "").strip()

def strip_trailing_heading(text, known_headings=None):
    """Return (clean_text, removed_heading_or_None).

    If known_headings (headings detected for this document) is given, a tail is
    removed only when it matches one of them (whitespace/case-insensitive).
    Without it, the regex alone decides (stricter length/word checks apply).
    """
    if not text:
        return text, None
    m = _TRAIL.search(text)
    if not m:
        return text, None
    head = _norm(m.group("h"))
    if known_headings is not None:
        known = {_norm(h).lower() for h in known_headings if h}
        if head.lower() not in known:
            return text, None
    else:
        words = head.split()
        if len(words) < 2 or len(words) > 14:
            return text, None
    return text[: m.start()].rstrip(), head


def strip_trailing_heading_all(text, known_headings=None, max_passes=3):
    """Strip up to max_passes stacked trailing headings. Returns (clean_text, [removed...])."""
    removed = []
    for _ in range(max_passes):
        text2, h = strip_trailing_heading(text, known_headings)
        if not h:
            break
        removed.insert(0, h); text = text2
    return text, removed
