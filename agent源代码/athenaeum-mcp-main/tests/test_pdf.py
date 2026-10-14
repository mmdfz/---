from athenaeum_mcp.pdf import (
    _extract_citation_pdf_url,
    _is_safe_url,
    _looks_like_html,
    _looks_like_pdf,
)


def test_rejects_non_http_scheme():
    ok, reason = _is_safe_url("file:///etc/passwd")
    assert ok is False
    assert "scheme" in reason.lower()


def test_rejects_ftp():
    ok, _ = _is_safe_url("ftp://example.com/x.pdf")
    assert ok is False


def test_rejects_loopback():
    ok, reason = _is_safe_url("http://127.0.0.1/secret.pdf")
    assert ok is False
    assert "private" in reason.lower() or "loopback" in reason.lower()


def test_rejects_localhost():
    ok, _ = _is_safe_url("http://localhost:8080/x.pdf")
    assert ok is False


def test_allows_public_https():
    ok, _ = _is_safe_url("https://arxiv.org/pdf/2311.07072")
    assert ok is True


def test_extract_citation_pdf_url_resolves_relative():
    html = '<head><meta name="citation_pdf_url" content="/content/pdf/x.pdf"></head>'
    url = _extract_citation_pdf_url(html, "https://link.springer.com/article/10.1/x")
    assert url == "https://link.springer.com/content/pdf/x.pdf"


def test_extract_citation_pdf_url_absolute():
    html = '<meta content="https://ex.com/a.pdf" name="citation_pdf_url" />'
    url = _extract_citation_pdf_url(html, "https://ex.com/landing")
    assert url == "https://ex.com/a.pdf"


def test_extract_citation_pdf_url_absent():
    assert _extract_citation_pdf_url("<html><head></head></html>", "https://x.com") is None


def test_looks_like_pdf_by_magic_bytes():
    assert _looks_like_pdf(b"%PDF-1.7 ...", "")
    assert _looks_like_pdf(b"random", "application/pdf")
    assert not _looks_like_pdf(b"<html>", "text/html")


def test_looks_like_html_detection():
    assert _looks_like_html(b"<!DOCTYPE html><html>", "")
    assert _looks_like_html(b"x", "text/html; charset=utf-8")
    assert not _looks_like_html(b"%PDF-1.7", "application/pdf")

