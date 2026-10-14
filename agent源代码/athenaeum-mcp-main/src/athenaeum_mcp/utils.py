"""Pure helpers: identifier detection/normalization and text cleaning."""
from __future__ import annotations

import html
import re
import unicodedata

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
_ARXIV_NEW_RE = re.compile(r"\b\d{4}\.\d{4,5}(v\d+)?\b")
_ARXIV_OLD_RE = re.compile(r"\b[a-z-]+(\.[A-Z]{2})?/\d{7}(v\d+)?\b")
_OPENALEX_RE = re.compile(r"\bW\d{5,}\b")
_PMCID_RE = re.compile(r"\bPMC\d+\b", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def normalize_doi(value: str | None) -> str | None:
    """Extract and normalize a DOI to a bare, lowercased form.

    ``https://doi.org/10.1/AbC`` -> ``10.1/abc``. Returns ``None`` if no DOI is
    found in *value*.
    """
    if not value:
        return None
    match = _DOI_RE.search(value.strip())
    if not match:
        return None
    doi = match.group(0).rstrip(".,;)")  # trailing punctuation from prose
    return doi.lower()


def normalize_arxiv_id(value: str | None) -> str | None:
    """Return a bare arXiv id (no ``arXiv:`` prefix, no version suffix removed)."""
    if not value:
        return None
    v = value.strip()
    v = re.sub(r"^arxiv:", "", v, flags=re.IGNORECASE)
    v = v.replace("https://arxiv.org/abs/", "").replace("http://arxiv.org/abs/", "")
    m = _ARXIV_NEW_RE.search(v) or _ARXIV_OLD_RE.search(v)
    return m.group(0) if m else None


def normalize_openalex_id(value: str | None) -> str | None:
    if not value:
        return None
    m = _OPENALEX_RE.search(value.strip())
    return m.group(0).upper() if m else None


def detect_identifier(value: str) -> tuple[str, str]:
    """Classify a free-form identifier.

    Returns ``(kind, normalized_value)`` where *kind* is one of
    ``doi | arxiv | openalex | pmcid | pmid | unknown``.
    """
    v = value.strip()
    low = v.lower()

    doi = normalize_doi(v)
    if doi and ("10." in v):
        return "doi", doi

    if low.startswith("arxiv:") or "arxiv.org/abs/" in low:
        ax = normalize_arxiv_id(v)
        if ax:
            return "arxiv", ax

    oa = normalize_openalex_id(v)
    if oa and (v.upper().startswith("W") or "openalex.org" in low):
        return "openalex", oa

    pmc = _PMCID_RE.search(v)
    if pmc:
        return "pmcid", pmc.group(0).upper()

    if low.startswith("pmid:"):
        digits = re.sub(r"\D", "", v)
        if digits:
            return "pmid", digits

    # Bare arXiv id (e.g. 2311.07072) before bare PMID, since arXiv ids contain a dot.
    ax = normalize_arxiv_id(v)
    if ax and "." in v:
        return "arxiv", ax

    if v.isdigit() and 4 <= len(v) <= 9:
        return "pmid", v

    return "unknown", v


def reconstruct_abstract(inverted_index: dict | None) -> str | None:
    """Rebuild abstract text from OpenAlex ``abstract_inverted_index``.

    OpenAlex stores abstracts as ``{word: [positions...]}``; we invert it back
    to running text.
    """
    if not inverted_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    if not positions:
        return None
    positions.sort(key=lambda p: p[0])
    text = " ".join(word for _, word in positions)
    return clean_text(text)


def clean_text(value: str | None) -> str | None:
    """Strip markup (e.g. JATS in Crossref abstracts), unescape entities, collapse whitespace."""
    if not value:
        return None
    no_tags = _TAG_RE.sub(" ", value)
    unescaped = html.unescape(no_tags)
    collapsed = _WS_RE.sub(" ", unescaped).strip()
    return collapsed or None


def slugify(value: str, max_len: int = 40) -> str:
    """ASCII slug for BibTeX keys etc."""
    norm = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    norm = re.sub(r"[^a-zA-Z0-9]+", "", norm)
    return norm[:max_len]


def title_key(title: str | None) -> str:
    """Normalized title for fuzzy dedup: lowercase alnum words, no punctuation."""
    if not title:
        return ""
    norm = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    norm = norm.lower()
    norm = re.sub(r"[^a-z0-9 ]+", " ", norm)
    return _WS_RE.sub(" ", norm).strip()
