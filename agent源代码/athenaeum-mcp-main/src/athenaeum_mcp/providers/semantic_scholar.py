"""Semantic Scholar provider — TLDR summaries and influential-citation signal.

Without an API key, Semantic Scholar is aggressively rate-limited (HTTP 429),
so it is treated as *best-effort*: it is only included in the meta-search when a
key is configured, but remains available for explicit single-provider calls and
for enriching individual works with a TLDR summary.
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..http_client import HttpError, get_client
from ..models import Author, Work
from ..utils import detect_identifier
from .base import Provider

_BASE = "https://api.semanticscholar.org/graph/v1"
_FIELDS = (
    "title,abstract,year,publicationDate,authors,venue,citationCount,"
    "influentialCitationCount,tldr,externalIds,openAccessPdf,publicationTypes"
)


def _map_paper(p: dict[str, Any]) -> Work:
    ext = p.get("externalIds") or {}
    oa_pdf = p.get("openAccessPdf") or {}
    tldr = p.get("tldr") or {}
    types = p.get("publicationTypes") or []
    work_type = "preprint" if any("preprint" in str(t).lower() for t in types) else "article"

    return Work(
        doi=ext.get("DOI"),
        arxiv_id=ext.get("ArXiv"),
        pmid=str(ext["PubMed"]) if ext.get("PubMed") else None,
        s2_id=p.get("paperId"),
        title=p.get("title"),
        abstract=p.get("abstract"),
        authors=[Author(name=a.get("name", "Unknown")) for a in (p.get("authors") or [])],
        year=p.get("year"),
        date=p.get("publicationDate"),
        venue=p.get("venue") or None,
        type=work_type,
        cited_by_count=p.get("citationCount"),
        is_oa=bool(oa_pdf.get("url")) or None,
        pdf_url=oa_pdf.get("url"),
        tldr=tldr.get("text"),
        source_provider="semantic_scholar",
    )


class SemanticScholarProvider(Provider):
    name = "semantic_scholar"

    def _headers(self) -> dict[str, str]:
        key = get_settings().semantic_scholar_api_key
        return {"x-api-key": key} if key else {}

    @property
    def has_key(self) -> bool:
        return get_settings().semantic_scholar_api_key is not None

    def available(self) -> bool:
        # Always usable for explicit calls; meta-search inclusion is decided by
        # the registry based on whether a key is present.
        return True

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,
    ) -> list[Work]:
        params: dict[str, Any] = {
            "query": query,
            "limit": min(max(limit, 1), 100),
            "fields": _FIELDS,
        }
        if year_from or year_to:
            params["year"] = f"{year_from or ''}-{year_to or ''}"
        if open_access_only:
            params["openAccessPdf"] = ""
        try:
            data = await get_client().get_json(
                f"{_BASE}/paper/search", params=params, headers=self._headers()
            )
        except HttpError:
            return []
        return [_map_paper(p) for p in (data.get("data") or [])]

    async def get_work(self, identifier: str) -> Work | None:
        kind, value = detect_identifier(identifier)
        id_map = {
            "doi": f"DOI:{value}",
            "arxiv": f"ARXIV:{value}",
            "pmid": f"PMID:{value}",
            "pmcid": f"PMCID:{value}",
        }
        s2_id = id_map.get(kind, value)
        try:
            data = await get_client().get_json(
                f"{_BASE}/paper/{s2_id}", params={"fields": _FIELDS}, headers=self._headers()
            )
        except HttpError:
            return None
        return _map_paper(data) if data else None

    async def get_tldr(self, identifier: str) -> str | None:
        """Lightweight enrichment: fetch just the TLDR for a work."""
        kind, value = detect_identifier(identifier)
        prefix = {"doi": "DOI:", "arxiv": "ARXIV:", "pmid": "PMID:"}.get(kind, "")
        try:
            data = await get_client().get_json(
                f"{_BASE}/paper/{prefix}{value}",
                params={"fields": "tldr"},
                headers=self._headers(),
            )
        except HttpError:
            return None
        return (data.get("tldr") or {}).get("text") if data else None


semantic_scholar = SemanticScholarProvider()
