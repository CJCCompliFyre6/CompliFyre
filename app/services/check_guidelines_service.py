"""
Service module for item #133 ("Check for new guidelines"). Split into
two concerns in one file:
  - Pure logic (fetch/clean/detect-block/parse/dedupe) -- independently
    tested before this file was ever written to the server.
  - The Celery task orchestrating them, using the same @shared_task
    pattern already established throughout this codebase.

Deliberately in its own new file rather than appended to the already
very large manual_task.py.
"""
import os
import json
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from celery import shared_task
from celery.utils.log import get_task_logger

from app import db
from app.models.re import (
    RegulatoryBodies, RegulatoryDocuments, DocumentPipelineStatus, set_document_pipeline_status,
)
from app.services.manual_task import get_llm_service

logger = get_task_logger(__name__)


# ============================================================
# JS-rendering detection -- confirmed live against SIDBI's real
# circulars page (2026-07-25): the plain-fetch version showed table
# headers but zero data rows; a real Playwright browser fetch of the
# same URL correctly captured all 14+ real circular entries. This
# heuristic decides WHEN to pay the extra cost of a full browser fetch,
# rather than doing it for every page.
# ============================================================

def looks_like_js_rendered_empty_content(html_raw, cleaned_text, raw_content_length):
    """
    Detect whether a page likely needs JavaScript rendering to show its
    real content, before paying the cost of a full Playwright fetch.
    """
    soup = BeautifulSoup(html_raw, "html.parser")

    for table in soup.find_all("table"):
        has_headers = bool(table.find("th")) or bool(table.find("thead"))
        tbody = table.find("tbody")
        if tbody:
            data_rows = tbody.find_all("tr")
        else:
            all_rows = table.find_all("tr")
            thead = table.find("thead")
            header_rows = thead.find_all("tr") if thead else []
            data_rows = [r for r in all_rows if r not in header_rows]
        if has_headers and len(data_rows) == 0:
            return True, "Table has headers but zero data rows -- likely JS-rendered content not yet loaded"

    if raw_content_length > 50000 and len(cleaned_text) < 1000:
        return True, f"Large raw HTML ({raw_content_length} bytes) but very little visible text ({len(cleaned_text)} chars) -- content likely JS-injected"

    return False, None


def fetch_page_text_with_playwright(url, timeout=30000, wait_ms=3000):
    """
    Fallback fetch using a real headless browser, for pages whose real
    content is injected by JavaScript after the initial page load.
    Returns (success: bool, text_or_error: str).
    """
    # S-SSRF: this fallback previously had NO IP validation at all --
    # it's reached automatically whenever fetch_page_text()'s response
    # looks "blocked" (e.g. short/empty, which is exactly what an SSRF
    # probe URL returns), silently bypassing that function's blocklist
    # check. Validate here too before launching a real browser.
    import ipaddress as _pw_ipaddress
    import socket as _pw_socket
    from urllib.parse import urlparse as _pw_urlparse

    _pw_blocked_nets = [
        _pw_ipaddress.ip_network("127.0.0.0/8"), _pw_ipaddress.ip_network("10.0.0.0/8"),
        _pw_ipaddress.ip_network("172.16.0.0/12"), _pw_ipaddress.ip_network("192.168.0.0/16"),
        _pw_ipaddress.ip_network("169.254.0.0/16"), _pw_ipaddress.ip_network("0.0.0.0/8"),
        _pw_ipaddress.ip_network("100.64.0.0/10"), _pw_ipaddress.ip_network("::1/128"),
        _pw_ipaddress.ip_network("fc00::/7"), _pw_ipaddress.ip_network("fe80::/10"),
    ]
    _pw_parsed = _pw_urlparse(url)
    if _pw_parsed.scheme not in ("http", "https") or not _pw_parsed.hostname:
        return False, "BLOCKED: invalid URL scheme"
    try:
        _pw_addrinfo = _pw_socket.getaddrinfo(_pw_parsed.hostname, None)
        for _, _, _, _, _pw_sockaddr in _pw_addrinfo:
            _pw_addr = _pw_ipaddress.ip_address(_pw_sockaddr[0])
            if any(_pw_addr in _net for _net in _pw_blocked_nets):
                return False, f"BLOCKED: internal address {_pw_addr}"
    except _pw_socket.gaierror:
        return False, "BLOCKED: DNS resolution failed"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, timeout=timeout)
            page.wait_for_timeout(wait_ms)
            rendered_html = page.content()
            browser.close()
        text_with_links = extract_text_with_links(rendered_html)
        return True, text_with_links
    except Exception as e:
        return False, f"PLAYWRIGHT_ERROR: {e}"


# ============================================================
# Block detection -- tested against 8 realistic scenarios
# (real listing pages, HTTP 403/429, CAPTCHA pages, Cloudflare
# challenges, short/redirect responses, the exact RBI-style auth
# wall confirmed earlier tonight) before deployment.
# ============================================================

def check_url_not_found(http_status):
    """
    Distinct from detect_fetch_block: a 404/410 means the specific URL
    is wrong or moved, NOT that the site is blocking us. Different
    problem, different fix -- needs the URL corrected in the regulator
    table, not a manual-browser workaround.
    """
    if http_status in (404, 410):
        return True, f"HTTP {http_status} -- this URL no longer exists, the regulator likely moved or renamed this page"
    return False, None


def detect_fetch_block(http_status, content_length, page_text):
    """
    Decide whether a fetched page is a genuine listing page or some kind
    of block/challenge response, BEFORE handing it to the LLM. Returns
    (is_blocked, reason). Deliberately conservative in one direction: a
    false "blocked" just means a page gets flagged for manual review
    that didn't strictly need it; a false "not blocked" means the LLM
    gets fed a challenge page and could return "0 new items found" --
    indistinguishable from a genuine clean check. That asymmetry is why
    detection here errs toward flagging.
    """
    if http_status is not None and http_status in (401, 403, 429, 503):
        return True, f"HTTP {http_status}"

    if content_length is not None and content_length < 500:
        return True, f"Suspiciously short response ({content_length} bytes) -- likely a block/redirect page, not real content"

    if page_text:
        lower = page_text.lower()
        block_phrases = [
            "captcha", "are you a robot", "access denied", "you are not authorized",
            "unusual traffic", "please verify you are human", "blocked due to",
            "rate limit exceeded", "cloudflare", "checking your browser",
        ]
        for phrase in block_phrases:
            if phrase in lower:
                return True, f"Block-indicator phrase found: '{phrase}'"

    return False, None


# ============================================================
# Fetch, clean, resolve, parse, dedupe
# ============================================================

GUIDELINE_LIST_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "guideline_list",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "documents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                        },
                        "required": ["title", "url"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["documents"],
            "additionalProperties": False,
        },
    },
}

EXTRACTION_PROMPT = """You are looking at the text content of a regulatory listing page.
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
"""


def extract_text_with_links(html):
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

    return soup.get_text(separator="\n", strip=True)


def fetch_page_text(url, timeout=15):
    """
    Fetch a URL and return (http_status, content_length, cleaned_text_or_error, raw_html).
    Returns (None, None, error_string, None) on connection failure -- distinct
    from a successful-but-blocked response, which has a real http_status.
    """
    try:
        # S-SSRF: validate URL before making outbound request
        import ipaddress, socket
        from urllib.parse import urlparse
        # S-SSRF (real fix): domain allowlist for the Regulator "Listing Page URL"
# feature. The internal-IP blocklist below only stops requests to
# private/internal/cloud-metadata addresses -- it does NOT stop the
# server from fetching ANY arbitrary public URL, which is itself the
# SSRF this finding describes (the application making outbound requests
# to an attacker-controlled server on the attacker's behalf). Only
# domains explicitly listed here may be saved or fetched.
#
# NOTE: extend this list as legitimate regulators are onboarded. Add the
# bare registrable domain (e.g. "rbi.org.in") -- subdomains of an
# allowed domain are permitted automatically (see is_domain_allowed()).
ALLOWED_REGULATOR_DOMAINS = {
    "rbi.org.in",
    "sebi.gov.in",
    "irdai.gov.in",
    "cert-in.org.in",
    "pfrda.org.in",
    "nabard.org",
    "ibbi.gov.in",
    "fiu-ind.gov.in",
    "meity.gov.in",
    "mca.gov.in",
}


def is_domain_allowed(url):
    """
    Returns True only if url's hostname is exactly an allowed domain, or
    a subdomain of one (e.g. "notifications.rbi.org.in" is allowed
    because "rbi.org.in" is on the list; "rbi.org.in.evil.com" is NOT
    allowed -- it does not end with ".rbi.org.in" or equal "rbi.org.in").
    """
    from urllib.parse import urlparse
    try:
        hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return False
    if not hostname:
        return False
    for allowed in ALLOWED_REGULATOR_DOMAINS:
        if hostname == allowed or hostname.endswith("." + allowed):
            return True
    return False


_BLOCKED = [
            ipaddress.ip_network("127.0.0.0/8"), ipaddress.ip_network("10.0.0.0/8"),
            ipaddress.ip_network("172.16.0.0/12"), ipaddress.ip_network("192.168.0.0/16"),
            ipaddress.ip_network("169.254.0.0/16"), ipaddress.ip_network("0.0.0.0/8"),
            ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("::1/128"),
            ipaddress.ip_network("fc00::/7"), ipaddress.ip_network("fe80::/10"),
        ]
        _parsed = urlparse(url)
        if _parsed.scheme not in ("http", "https") or not _parsed.hostname:
            return None, None, "BLOCKED: invalid URL scheme", None
        # S-SSRF (real fix): domain allowlist, defense in depth. Save-time
        # validation in add_regulator/edit_regulator should already have
        # rejected anything not on this list, but this check is enforced
        # here too so that fetch_page_text() itself can never be pointed
        # at an arbitrary attacker-controlled domain, no matter how the
        # URL arrived (legacy row, direct DB edit, other call sites).
        if not is_domain_allowed(url):
            return None, None, f"BLOCKED: domain not in regulator allowlist ({_parsed.hostname})", None
        _validated_ip = None
        try:
            _addrinfo = socket.getaddrinfo(_parsed.hostname, None)
            for _, _, _, _, _sockaddr in _addrinfo:
                _addr = ipaddress.ip_address(_sockaddr[0])
                if any(_addr in _net for _net in _BLOCKED):
                    return None, None, f"BLOCKED: internal address {_addr}", None
                if _validated_ip is None:
                    _validated_ip = _sockaddr[0]
        except socket.gaierror:
            return None, None, "BLOCKED: DNS resolution failed", None

        if not _validated_ip:
            return None, None, "BLOCKED: could not resolve host", None

        # S-SSRF (rebinding fix, thread-safe): pin THIS thread's connection
        # to the already-validated IP, without rewriting the URL, so TLS
        # SNI/certificate checks still run against the real hostname.
        # requests.get() would otherwise re-resolve the hostname itself
        # right before connecting, and a rebinding DNS server could hand
        # back a different (internal) IP on that second lookup -- bypassing
        # the blocklist check above. threading.local() ensures concurrent
        # requests (e.g. multiple Gunicorn worker threads) each pin their
        # own host/IP pair without clobbering one another. Helper function
        # is defined at the bottom of this file (_ssrf_safe_get).
        resp = _ssrf_safe_get(
            url,
            _parsed.hostname,
            _validated_ip,
            timeout=timeout,
        )
    except requests.exceptions.RequestException as e:
        return None, None, f"CONNECTION_ERROR: {e}", None

    cleaned_text = extract_text_with_links(resp.text)

    return resp.status_code, len(resp.content), cleaned_text, resp.text



def resolve_relative_url(base_url, maybe_relative):
    """Resolve a possibly-relative URL against the listing page's own domain."""
    return urljoin(base_url, maybe_relative)


def safe_json_loads(raw):
    """
    Parse JSON that may contain invalid \\u escape sequences -- the LLM
    occasionally copies raw, malformed backslash-u text straight from a
    source page into its JSON output without properly escaping it,
    producing JSON that Python correctly refuses to parse as-is.
    Repairs this by escaping any backslash-u NOT followed by exactly
    4 valid hex digits, turning it into a literal string instead of
    an (invalid) attempted unicode escape. Genuinely valid unicode
    escapes (e.g. \\u00e9) are left untouched and still parse correctly.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        repaired = re.sub(r"\\u(?![0-9a-fA-F]{4})", r"\\\\u", raw)
        return json.loads(repaired)


def parse_documents_with_llm(page_text, llm_client, max_chars=60000):
    """
    Send cleaned page text to the LLM using a strict JSON schema --
    deliberately NOT the weak response_format={"type": "json_object"}
    mode that caused item #121's field-dropping bug earlier tonight.
    """
    truncated = page_text[:max_chars]
    prompt = EXTRACTION_PROMPT.format(page_text=truncated)

    response = llm_client.chat.completions.create(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        response_format=GUIDELINE_LIST_SCHEMA,
    )
    result = safe_json_loads(response.choices[0].message.content)
    return result.get("documents", [])


def process_check_results(extracted_docs, base_url, existing_urls_for_regulator):
    """
    Dedupe against both already-tracked URLs and duplicates within the
    same LLM response, returning only genuinely new documents.
    """
    new_docs = []
    seen_in_this_batch = set()
    for doc in extracted_docs:
        title = (doc.get("title") or "").replace("\x00", " ").strip()
        url = (doc.get("url") or "").replace("\x00", " ").strip()
        if not title or not url:
            continue
        resolved_url = resolve_relative_url(base_url, url)
        if resolved_url in existing_urls_for_regulator:
            continue
        if resolved_url in seen_in_this_batch:
            continue
        seen_in_this_batch.add(resolved_url)
        new_docs.append({"title": title, "url": resolved_url})
    return new_docs


# ============================================================
# The Celery task
# ============================================================

@shared_task(bind=True)
def check_regulator_for_new_guidelines(self, regulator_body_id):
    """
    Core task for item #133. Fetches a regulator's listing page, detects
    blocks BEFORE ever involving the LLM, and if not blocked, asks the
    LLM to extract document titles + links. New documents get created as
    RegulatoryDocuments rows with pipeline_status=PENDING_DOWNLOAD.
    Always updates last_check_status/last_checked_at/last_check_notes --
    a block or failure is recorded with its specific reason, never
    silently reported as "0 new items found".
    """
    regulator = RegulatoryBodies.query.get(regulator_body_id)
    if not regulator:
        logger.error(f"[CheckGuidelines] Regulator body_id={regulator_body_id} not found")
        return {"status": "ERROR", "reason": "Regulator not found"}

    logger.info(f"[CheckGuidelines] Checking {regulator.name} / {regulator.description} ({regulator.website_url})")

    http_status, content_length, page_text_or_error, raw_html = fetch_page_text(regulator.website_url)

    if http_status is None:
        regulator.last_check_status = "FAILED"
        regulator.last_checked_at = datetime.now(timezone.utc)
        regulator.last_check_notes = page_text_or_error
        db.session.commit()
        logger.warning(f"[CheckGuidelines] {regulator.name}: connection failure -- {page_text_or_error}")
        return {"status": "FAILED", "reason": page_text_or_error}

    url_not_found, not_found_reason = check_url_not_found(http_status)
    if url_not_found:
        regulator.last_check_status = "URL_NOT_FOUND"
        regulator.last_checked_at = datetime.now(timezone.utc)
        regulator.last_check_notes = not_found_reason
        db.session.commit()
        logger.warning(f"[CheckGuidelines] {regulator.name}: URL_NOT_FOUND -- {not_found_reason}")
        return {"status": "URL_NOT_FOUND", "reason": not_found_reason}

    is_blocked, block_reason = detect_fetch_block(http_status, content_length, page_text_or_error)
    if is_blocked:
        regulator.last_check_status = "BLOCKED"
        regulator.last_checked_at = datetime.now(timezone.utc)
        regulator.last_check_notes = block_reason
        db.session.commit()
        logger.warning(f"[CheckGuidelines] {regulator.name}: BLOCKED -- {block_reason}")
        return {"status": "BLOCKED", "reason": block_reason}

    # Not blocked -- but might still need JS rendering to see real content.
    needs_js, js_reason = looks_like_js_rendered_empty_content(raw_html, page_text_or_error, content_length)
    used_playwright = False
    if needs_js:
        logger.info(f"[CheckGuidelines] {regulator.name}: {js_reason} -- retrying with Playwright")
        pw_success, pw_text_or_error = fetch_page_text_with_playwright(regulator.website_url)
        if pw_success:
            page_text_or_error = pw_text_or_error
            used_playwright = True
        else:
            regulator.last_check_status = "FAILED"
            regulator.last_checked_at = datetime.now(timezone.utc)
            regulator.last_check_notes = f"JS-rendered page, Playwright fallback also failed: {pw_text_or_error}"
            db.session.commit()
            logger.error(f"[CheckGuidelines] {regulator.name}: Playwright fallback failed -- {pw_text_or_error}")
            return {"status": "FAILED", "reason": regulator.last_check_notes}

    try:
        client = get_llm_service()
        extracted_docs = parse_documents_with_llm(page_text_or_error, client)
    except Exception as e:
        regulator.last_check_status = "FAILED"
        regulator.last_checked_at = datetime.now(timezone.utc)
        regulator.last_check_notes = f"LLM extraction error: {e}"
        db.session.commit()
        logger.error(f"[CheckGuidelines] {regulator.name}: LLM extraction failed -- {e}")
        return {"status": "FAILED", "reason": f"LLM extraction error: {e}"}

    existing_docs = RegulatoryDocuments.query.filter_by(body_id=regulator_body_id).all()
    existing_urls = {d.source_url for d in existing_docs if d.source_url}

    new_docs = process_check_results(extracted_docs, regulator.website_url, existing_urls)

    for doc in new_docs:
        record = RegulatoryDocuments(
            title=doc["title"],
            body_id=regulator_body_id,
            source_url=doc["url"],
            pipeline_status=DocumentPipelineStatus.PENDING_DOWNLOAD,
        )
        db.session.add(record)
        db.session.flush()
        set_document_pipeline_status(
            record, DocumentPipelineStatus.PENDING_DOWNLOAD,
            notes="Discovered via Check for new guidelines"
        )

    regulator.last_check_status = "SUCCESS"
    regulator.last_checked_at = datetime.now(timezone.utc)
    playwright_note = " (required Playwright/JS rendering)" if used_playwright else ""
    regulator.last_check_notes = f"{len(new_docs)} new document(s) found, {len(extracted_docs)} total on page{playwright_note}"
    db.session.commit()

    logger.info(f"[CheckGuidelines] {regulator.name}: SUCCESS -- {len(new_docs)} new, {len(extracted_docs)} total found{playwright_note}")
    return {"status": "SUCCESS", "new_count": len(new_docs), "total_found": len(extracted_docs), "used_playwright": used_playwright}


# ============================================================
# Title matching for linking Tracked Guidelines (discovered
# documents) to the real Guidelines table once uploaded.
# ============================================================

def normalize_title(title):
    """
    Strip common noise words/punctuation that differ between a
    discovery-time title (e.g. "RBI releases draft Master Direction --
    Reserve Bank of India (Credit Derivatives) Directions, 2026") and
    the eventual uploaded document's own DocumentName, so word-overlap
    comparison isn't thrown off by these.
    """
    noise_phrases = [
        "rbi releases draft", "rbi issues draft", "rbi invites public comments on the draft",
        "rbi invites comments on the draft", "rbi invites comments on",
        "master direction -", "master direction \u2013", "master direction --",
        "draft", "amendment directions", "directions,", "directions",
    ]
    t = title.lower()
    for phrase in noise_phrases:
        t = t.replace(phrase, " ")
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_similarity(title_a, title_b):
    """
    Word-overlap (Jaccard) similarity between two normalized titles --
    robust to prefix/suffix differences (draft vs final wording), since
    it only cares about which significant words are shared.
    """
    words_a = set(normalize_title(title_a).split())
    words_b = set(normalize_title(title_b).split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def try_link_tracked_guideline(guideline_id, document_name, threshold=0.6):
    """
    After a new Guidelines row is created, check whether its document
    name matches a still-pending Tracked Guidelines (RegulatoryDocuments)
    entry, and if so, link them: set guideline_id and flip the pipeline
    status to IMPORTED. Deliberately conservative threshold -- a missed
    match just leaves the Tracked Guidelines entry "Pending" a bit
    longer (safe); a wrong match would silently link two unrelated
    documents (worse). Returns the linked RegulatoryDocuments row, or
    None if nothing matched confidently enough.
    """
    if not document_name:
        return None

    pending = RegulatoryDocuments.query.filter_by(guideline_id=None).all()
    if not pending:
        return None

    best_doc = None
    best_score = 0.0
    for doc in pending:
        score = title_similarity(document_name, doc.title)
        if score > best_score:
            best_score = score
            best_doc = doc

    if best_doc and best_score >= threshold:
        best_doc.guideline_id = guideline_id
        set_document_pipeline_status(
            best_doc, DocumentPipelineStatus.IMPORTED,
            notes=f"Auto-linked to guideline_id={guideline_id} on upload (title similarity {best_score:.2f})"
        )
        return best_doc
    return None


# --- S-SSRF: thread-safe IP-pinned GET helper -------------------------------
# Prevents DNS-rebinding SSRF: pins the TCP connection for this request to
# the IP address that was already validated against the internal-IP
# blocklist, while keeping the original hostname in the URL so TLS SNI and
# certificate validation still succeed. Thread-local so concurrent requests
# (e.g. separate Gunicorn worker threads) never share or clobber each
# other's pinned IP. Appended at end of file; used by fetch_page_text()
# above, which is safe because Python resolves the call at runtime, after
# the whole module (including this block) has finished loading.
import threading as _ssrf_threading
import urllib3.util.connection as _ssrf_urllib3_conn_module
from urllib3.util.connection import create_connection as _ssrf_original_create_connection

_ssrf_thread_local = _ssrf_threading.local()


def _ssrf_patched_create_connection(address, *args, **kwargs):
    host, port = address
    pin = getattr(_ssrf_thread_local, "pinned_host_ip", None)
    if pin is not None and pin[0] == host:
        address = (pin[1], port)
    return _ssrf_original_create_connection(address, *args, **kwargs)


_ssrf_urllib3_conn_module.create_connection = _ssrf_patched_create_connection


def _ssrf_safe_get(url, hostname, validated_ip, timeout=15):
    """
    Perform a GET request where the TCP connection is guaranteed to go to
    validated_ip for `hostname`, closing the DNS-rebinding window, while
    preserving normal TLS/SNI/certificate validation against `hostname`.
    """
    _ssrf_thread_local.pinned_host_ip = (hostname, validated_ip)
    try:
        with requests.Session() as _session:
            return _session.get(
                url,
                timeout=timeout,
                allow_redirects=False,  # S-SSRF: prevent redirect to internal IPs
                headers={"User-Agent": "Mozilla/5.0 (compatible; CompliFyre-checker/1.0)"},
            )
    finally:
        _ssrf_thread_local.pinned_host_ip = None
# --- end S-SSRF helper ------------------------------------------------------
