"""PDF / full-text extraction with multi-source fallback.

Reading a paper's full text from the open web is messy: the "best" PDF link is
often a publisher copy behind a bot block (e.g. Cloudflare), while an accessible
copy sits in a repository. This module therefore takes a *list* of candidate
sources and tries each in turn, with several recovery strategies, returning a
transparent log of every attempt so callers can see exactly what was tried.

Strategies, in priority order per candidate:

1. Download with a realistic browser header set (recovers hosts that merely
   reject bot User-Agents).
2. If the response is HTML rather than a PDF (a landing page or a JS challenge),
   parse it for the ``citation_pdf_url`` meta tag — the de-facto standard
   publishers and repositories embed — and fetch that.
3. Parse the PDF with pypdf and extract text.

Known, disclosed limitations:
- Sites behind a JavaScript challenge (notably some MDPI/Cloudflare configs)
  cannot be fetched by any non-browser client and surface as HTTP 403.
- Scanned/image-only PDFs yield no text (OCR is out of scope).
- Paywalled works without an open-access copy cannot be read.
"""
from __future__ import annotations

import io
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

from .http_client import HttpError, get_client

_MAX_PDF_BYTES = 30 * 1024 * 1024   # 30 MB
_MAX_HTML_BYTES = 4 * 1024 * 1024   # 4 MB for landing pages

# citation_pdf_url is the Highwire/Google-Scholar meta standard for the canonical
# PDF of a page; both attribute orderings occur in the wild.
_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)
_NAME_RE = re.compile(r'name=["\'](?:citation_pdf_url)["\']', re.I)
_CONTENT_RE = re.compile(r'content=["\']([^"\']+)["\']', re.I)


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Reject non-HTTP(S) URLs and those resolving to private/loopback hosts (SSRF guard)."""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return False, "Malformed URL."
    if parsed.scheme not in {"http", "https"}:
        return False, f"Unsupported URL scheme '{parsed.scheme}'. Only http/https allowed."
    host = parsed.hostname
    if not host:
        return False, "URL has no host."
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Can't resolve here; let the HTTP layer try and fail safely.
        return True, ""
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False, "URL resolves to a private or loopback address; refusing to fetch."
    return True, ""


def _looks_like_pdf(content: bytes, content_type: str) -> bool:
    return "pdf" in content_type.lower() or content[:5] == b"%PDF-"


def _looks_like_html(content: bytes, content_type: str) -> bool:
    if "html" in content_type.lower():
        return True
    head = content[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<head" in head


def _extract_citation_pdf_url(html: str, base_url: str) -> str | None:
    """Pull the ``citation_pdf_url`` meta-tag target from landing-page HTML."""
    for tag in _META_TAG_RE.findall(html):
        if _NAME_RE.search(tag):
            m = _CONTENT_RE.search(tag)
            if m:
                return urljoin(base_url, m.group(1))
    return None


def _parse_pdf(content: bytes, *, max_pages: int, max_chars: int) -> tuple[str, int, int]:
    """Return ``(text, pages_total, pages_read)``; text is "" if unreadable."""
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is declared
        raise HttpError("pypdf is not installed. Run: pip install pypdf")

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            return "", 0, 0

    pages_total = len(reader.pages)
    n = min(pages_total, max(1, max_pages))
    parts: list[str] = []
    for i in range(n):
        try:
            parts.append(reader.pages[i].extract_text() or "")
        except Exception:  # noqa: BLE001 - skip unreadable pages
            continue
    text = "\n\n".join(p.strip() for p in parts if p.strip())
    return text, pages_total, n


async def _try_candidate(
    src: dict, *, max_pages: int, max_chars: int
) -> tuple[dict | None, dict]:
    """Try one candidate. Returns ``(success_or_None, attempt_record)``."""
    url = src["url"]
    name = src.get("source", "source")
    kind = src.get("kind", "pdf")
    attempt = {"source": name, "url": url}

    safe, reason = _is_safe_url(url)
    if not safe:
        attempt["result"] = f"skipped: {reason}"
        return None, attempt

    # Landing pages: fetch HTML and resolve the embedded PDF link first.
    if kind == "landing":
        try:
            html_bytes, ctype = await get_client().download_bytes(
                url, max_bytes=_MAX_HTML_BYTES, accept="text/html,application/xhtml+xml,*/*;q=0.8"
            )
        except HttpError as exc:
            attempt["result"] = f"landing fetch failed: {exc}"
            return None, attempt
        pdf_url = _extract_citation_pdf_url(html_bytes.decode("utf-8", "replace"), url)
        if not pdf_url:
            attempt["result"] = "landing page had no citation_pdf_url meta tag"
            return None, attempt
        attempt["resolved_pdf_url"] = pdf_url
        url = pdf_url  # fall through to PDF download

    # Download the (possibly resolved) PDF URL.
    try:
        content, ctype = await get_client().download_bytes(url, max_bytes=_MAX_PDF_BYTES)
    except HttpError as exc:
        attempt["result"] = str(exc)
        return None, attempt

    # If we got HTML instead of a PDF, try to recover an embedded PDF link once.
    if not _looks_like_pdf(content, ctype) and _looks_like_html(content, ctype):
        pdf_url = _extract_citation_pdf_url(content.decode("utf-8", "replace"), url)
        if pdf_url and pdf_url != url:
            attempt["resolved_pdf_url"] = pdf_url
            try:
                content, ctype = await get_client().download_bytes(pdf_url, max_bytes=_MAX_PDF_BYTES)
                url = pdf_url
            except HttpError as exc:
                attempt["result"] = f"embedded PDF link failed: {exc}"
                return None, attempt
        else:
            attempt["result"] = "got an HTML page (landing page or access block), not a PDF"
            return None, attempt

    if not _looks_like_pdf(content, ctype):
        attempt["result"] = f"downloaded content is not a PDF (type: {ctype or 'unknown'})"
        return None, attempt

    try:
        text, pages_total, pages_read = _parse_pdf(content, max_pages=max_pages, max_chars=max_chars)
    except Exception as exc:  # noqa: BLE001
        attempt["result"] = f"could not parse PDF: {exc}"
        return None, attempt

    if not text:
        attempt["result"] = "no extractable text (likely a scanned/image PDF; OCR not supported)"
        return None, attempt

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n\n[… text truncated …]"
        truncated = True

    attempt["result"] = "ok"
    success = {
        "ok": True,
        "source": name,
        "url": url,
        "content_type": ctype,
        "pages_total": pages_total,
        "pages_read": pages_read,
        "char_count": len(text),
        "truncated": truncated,
        "text": text,
    }
    return success, attempt


async def extract_fulltext(
    sources: list[dict],
    *,
    max_pages: int = 30,
    max_chars: int = 20_000,
) -> dict:
    """Try each candidate source in order until one yields readable text.

    ``sources`` is a list of ``{"source", "url", "kind"}`` dicts (``kind`` is
    ``"pdf"`` or ``"landing"``). Returns a dict with ``ok`` plus, on success,
    the extracted ``text`` and which ``source`` worked, and always an
    ``attempts`` log describing every source tried and why it failed.
    """
    if not sources:
        return {"ok": False, "error": "No candidate full-text sources were found.", "attempts": []}

    attempts: list[dict] = []
    for src in sources:
        success, record = await _try_candidate(src, max_pages=max_pages, max_chars=max_chars)
        attempts.append(record)
        if success is not None:
            success["attempts"] = attempts
            return success

    return {
        "ok": False,
        "error": "Could not retrieve readable full text from any available source.",
        "attempts": attempts,
    }


async def extract_pdf_text(url: str, *, max_pages: int = 30, max_chars: int = 20_000) -> dict:
    """Convenience wrapper to read a single direct PDF URL."""
    return await extract_fulltext(
        [{"source": "url", "url": url, "kind": "pdf"}], max_pages=max_pages, max_chars=max_chars
    )
