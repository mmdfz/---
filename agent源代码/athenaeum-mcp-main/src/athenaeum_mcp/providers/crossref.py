"""Crossref provider — authoritative DOI metadata and citation export.

Crossref (https://crossref.org) is the primary DOI registration agency. Used
for precise bibliographic metadata, references, journal validation, and
machine-format citation export (BibTeX / RIS) via its ``transform`` endpoint.
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..http_client import HttpError, get_client
from ..models import Author, Work
from ..utils import clean_text, detect_identifier
from .base import Provider

_BASE = "https://api.crossref.org"

_TYPE_MAP = {
    "journal-article": "article",
    "posted-content": "preprint",
    "proceedings-article": "conference-paper",
    "book-chapter": "book-chapter",
    "book": "book",
    "monograph": "book",
    "dissertation": "thesis",
    "report": "report",
    "dataset": "dataset",
}


def _first(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _issued_year_date(msg: dict[str, Any]) -> tuple[int | None, str | None]:
    for key in ("issued", "published", "published-print", "published-online", "created"):
        parts = ((msg.get(key) or {}).get("date-parts") or [[]])[0]
        if parts:
            year = parts[0] if len(parts) >= 1 else None
            if year:
                iso = "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(parts))
                return year, iso
    return None, None


def _map_work(msg: dict[str, Any]) -> Work:
    authors: list[Author] = []
    for a in msg.get("author") or []:
        given, family = a.get("given"), a.get("family")
        name = " ".join(p for p in (given, family) if p) or a.get("name") or "Unknown"
        affil = (a.get("affiliation") or [{}])
        authors.append(
            Author(
                name=name,
                given=given,
                family=family,
                orcid=a.get("ORCID"),
                affiliation=(affil[0].get("name") if affil else None),
            )
        )

    year, date = _issued_year_date(msg)
    raw_type = msg.get("type") or ""
    license_present = bool(msg.get("license"))

    return Work(
        doi=msg.get("DOI"),
        title=clean_text(_first(msg.get("title"))),
        abstract=clean_text(msg.get("abstract")),
        authors=authors,
        year=year,
        date=date,
        venue=_first(msg.get("container-title")),
        venue_issn=[i for i in (msg.get("ISSN") or []) if i],
        type=_TYPE_MAP.get(raw_type, raw_type or None),
        publisher=msg.get("publisher"),
        volume=msg.get("volume"),
        issue=msg.get("issue"),
        pages=msg.get("page"),
        cited_by_count=msg.get("is-referenced-by-count"),
        reference_count=msg.get("reference-count"),
        is_oa=(True if license_present else None),
        landing_url=msg.get("URL"),
        topics=[s for s in (msg.get("subject") or [])][:4],
        language=msg.get("language"),
        source_provider="crossref",
    )


def _map_reference(ref: dict[str, Any]) -> Work | None:
    doi = ref.get("DOI")
    title = ref.get("article-title") or ref.get("volume-title")
    if not doi and not title:
        # Last resort: unstructured citation string as the title.
        title = clean_text(ref.get("unstructured"))
        if not title:
            return None
    year = None
    if ref.get("year"):
        try:
            year = int(str(ref["year"])[:4])
        except ValueError:
            year = None
    authors = []
    if ref.get("author"):
        authors = [Author(name=str(ref["author"]), family=str(ref["author"]))]
    return Work(
        doi=doi,
        title=title,
        authors=authors,
        year=year,
        venue=ref.get("journal-title"),
        source_provider="crossref",
    )


class CrossrefProvider(Provider):
    name = "crossref"

    def _params(self, **extra: Any) -> dict[str, Any]:
        params = {"mailto": get_settings().mailto}
        params.update({k: v for k, v in extra.items() if v is not None})
        return params

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,
    ) -> list[Work]:
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}-01-01")
        if year_to:
            filters.append(f"until-pub-date:{year_to}-12-31")
        params = self._params(rows=min(max(limit, 1), 100))
        # query.bibliographic gives noticeably better topical relevance than the
        # generic `query` parameter and reduces non-article noise.
        params["query.bibliographic"] = query
        if filters:
            params["filter"] = ",".join(filters)
        try:
            data = await get_client().get_json(f"{_BASE}/works", params=params)
        except HttpError:
            return []
        items = (data.get("message") or {}).get("items") or []
        return [_map_work(m) for m in items]

    async def get_work(self, identifier: str) -> Work | None:
        kind, value = detect_identifier(identifier)
        if kind != "doi":
            return None
        try:
            data = await get_client().get_json(f"{_BASE}/works/{value}", params=self._params())
        except HttpError:
            return None
        return _map_work(data.get("message") or {})

    async def get_references(self, identifier: str, *, limit: int = 60) -> list[Work]:
        kind, value = detect_identifier(identifier)
        if kind != "doi":
            return []
        try:
            data = await get_client().get_json(f"{_BASE}/works/{value}", params=self._params())
        except HttpError:
            return []
        refs = (data.get("message") or {}).get("reference") or []
        out: list[Work] = []
        for ref in refs[:limit]:
            mapped = _map_reference(ref)
            if mapped:
                out.append(mapped)
        return out

    async def format(self, doi: str, fmt: str) -> str | None:
        """Return BibTeX or RIS for a DOI via Crossref's transform endpoint."""
        mime = {
            "bibtex": "application/x-bibtex",
            "ris": "application/x-research-info-systems",
        }.get(fmt)
        if mime is None:
            return None
        kind, value = detect_identifier(doi)
        if kind != "doi":
            return None
        try:
            resp = await get_client().get(
                f"{_BASE}/works/{value}/transform/{mime}", accept=mime
            )
        except HttpError:
            return None
        return resp.text if resp.status == 200 else None

    async def get_journal(self, issn: str) -> dict[str, Any] | None:
        """Validation metadata for a journal by ISSN."""
        try:
            data = await get_client().get_json(
                f"{_BASE}/journals/{issn.strip()}", params=self._params()
            )
        except HttpError:
            return None
        msg = data.get("message") or {}
        if not msg:
            return None
        counts = msg.get("counts") or {}
        return {
            "title": msg.get("title"),
            "publisher": msg.get("publisher"),
            "issn": msg.get("ISSN"),
            "total_dois": counts.get("total-dois"),
            "current_dois": counts.get("current-dois"),
            "indexed_in_crossref": True,
        }


crossref = CrossrefProvider()
