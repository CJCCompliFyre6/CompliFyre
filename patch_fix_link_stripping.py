#!/usr/bin/env python3
"""
Patch: Fix a real bug found live -- both the simple BeautifulSoup fetch
and the Playwright fallback were stripping all <a href="..."> link
targets before handing text to the LLM, causing 45 real document titles
to be correctly found on SIDBI's page but every single URL to come back
empty (all 45 then silently dropped by the dedup step for lacking a
real URL).

Adds a new extract_text_with_links() function that preserves hyperlinks
inline as "link text [LINK: href]", and rewires both fetch_page_text()
and fetch_page_text_with_playwright() to use it, plus updates
EXTRACTION_PROMPT so the LLM knows how to read the new marker format.

Usage:
    python3 patch_fix_link_stripping.py --dry-run
    python3 patch_fix_link_stripping.py --apply
    python3 patch_fix_link_stripping.py --rollback
"""
import argparse
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "CompliFyre-staging" / "app" / "services" / "check_guidelines_service.py"
BACKUP = TARGET.with_suffix(".py.bak_link_fix")

# --- Anchor 1: Playwright inner_text -> content() + extract_text_with_links ---
ANCHOR_PW = '''            page.wait_for_timeout(wait_ms)
            text = page.inner_text("body")
            browser.close()
        return True, text
    except Exception as e:
        return False, f"PLAYWRIGHT_ERROR: {e}"'''

NEW_PW = '''            page.wait_for_timeout(wait_ms)
            rendered_html = page.content()
            browser.close()
        text_with_links = extract_text_with_links(rendered_html)
        return True, text_with_links
    except Exception as e:
        return False, f"PLAYWRIGHT_ERROR: {e}"'''

# --- Anchor 2: simple-fetch get_text -> extract_text_with_links, plus insert new function ---
ANCHOR_FETCH = '''    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    cleaned_text = soup.get_text(separator="\\n", strip=True)

    return resp.status_code, len(resp.content), cleaned_text, resp.text'''

NEW_FETCH = '''    cleaned_text = extract_text_with_links(resp.text)

    return resp.status_code, len(resp.content), cleaned_text, resp.text'''

NEW_FUNCTION = '''def extract_text_with_links(html):
    """
    Convert HTML into a text representation that preserves hyperlinks
    inline, instead of losing them the way plain get_text() or
    innerText do. Each link becomes "link text [LINK: href]" so the
    LLM can see both the readable title AND its actual URL together.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        link_text = a.get_text(strip=True)
        if href and link_text:
            a.replace_with(f"{link_text} [LINK: {href}]")
        elif href:
            a.replace_with(f"[LINK: {href}]")

    return soup.get_text(separator="\\n", strip=True)


'''

# --- Anchor 3: EXTRACTION_PROMPT wording update ---
ANCHOR_PROMPT = '''EXTRACTION_PROMPT = """You are looking at the text content of a regulatory listing page.
Extract every individual document/circular/notification/guideline listed on
this page, along with its link if one is present.

Rules:
- Only extract actual documents (circulars, notifications, directions,
  guidelines, regulations) -- NOT navigation menu items, NOT page headers/
  footers, NOT unrelated links (social media, login, contact us, etc.)
- If a document's link is a relative URL (starts with / or doesn't include
  a domain), still include it exactly as found -- it will be resolved
  against the page's own domain afterward.
- If you genuinely cannot find any real documents on this page (e.g. it's
  a blocked/error/captcha page, or a page with no listings), return an
  empty documents array. Do NOT invent entries.

PAGE TEXT:
{page_text}
"""'''

NEW_PROMPT = '''EXTRACTION_PROMPT = """You are looking at the text content of a regulatory listing page.
Hyperlinks in this text are marked inline as: some text [LINK: the-actual-url]
immediately after the linked text.

Extract every individual document/circular/notification/guideline listed on
this page, along with its link.

Rules:
- Only extract actual documents (circulars, notifications, directions,
  guidelines, regulations) -- NOT navigation menu items, NOT page headers/
  footers, NOT unrelated links (social media, login, contact us, etc.)
- For the "url" field, use exactly what appears inside the nearest
  [LINK: ...] marker for that document. If a document has no [LINK: ...]
  marker anywhere near it, use an empty string for its url.
- If a document's link is a relative URL (starts with / or doesn't include
  a domain), still include it exactly as found -- it will be resolved
  against the page's own domain afterward.
- If you genuinely cannot find any real documents on this page (e.g. it's
  a blocked/error/captcha page, or a page with no listings), return an
  empty documents array. Do NOT invent entries.

PAGE TEXT:
{page_text}
"""'''


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    args = parser.parse_args()

    if args.rollback:
        if not BACKUP.exists():
            print(f"No backup found at {BACKUP}. Nothing to roll back.")
            sys.exit(1)
        shutil.copy2(BACKUP, TARGET)
        print(f"Rolled back {TARGET} from {BACKUP}.")
        return

    if not TARGET.exists():
        print(f"ERROR: target file not found: {TARGET}")
        sys.exit(1)

    content = TARGET.read_text()

    if "extract_text_with_links" in content:
        print("Patch already applied. Nothing to do.")
        return

    for name, anchor in [("PW", ANCHOR_PW), ("FETCH", ANCHOR_FETCH), ("PROMPT", ANCHOR_PROMPT)]:
        count = content.count(anchor)
        if count != 1:
            print(f"ERROR: anchor '{name}' matched {count} times (expected 1). Aborting.")
            sys.exit(1)

    patched = content.replace(ANCHOR_PW, NEW_PW)
    patched = patched.replace(ANCHOR_FETCH, NEW_FETCH)
    patched = patched.replace(ANCHOR_PROMPT, NEW_PROMPT)
    # Insert the new function right before "def fetch_page_text(url, timeout=15):"
    insertion_point = "def fetch_page_text(url, timeout=15):"
    patched = patched.replace(insertion_point, NEW_FUNCTION + insertion_point)

    if args.dry_run:
        print("All 3 anchors matched exactly once. Would also insert extract_text_with_links()")
        print("right before fetch_page_text().")
        print("(No files written. Re-run with --apply to make the change.)")
        return

    if args.apply:
        shutil.copy2(TARGET, BACKUP)
        TARGET.write_text(patched)
        print(f"Backup written to {BACKUP}")
        print(f"Patched {TARGET}")


if __name__ == "__main__":
    main()
