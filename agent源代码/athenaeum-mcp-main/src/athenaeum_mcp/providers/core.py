"""CORE provider — the largest aggregator of open-access full text (needs a key).

CORE (https://core.ac.uk) harvests tens of millions of open-access papers from
repositories worldwide and, crucially, hosts a directly downloadable full-text
PDF for many of them. That makes it a strong complement to ``find_pdf`` /
``read_pdf`` when a publisher copy is blocked.

The CORE v3 API **requires a free API key**. Per project convention this
provider is therefore *gated*: it is inactive (and excluded from the default
meta-search) unless ``CORE_API_KEY`` is set. Request a key at
https://core.ac.uk/services/api — see ``docs/providers/core.md``.
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..http_client import HttpError, get_client
from ..models import Author, Work
from ..utils import clean_text, detect_identifier, normalize_doi
from .base import Provider

_BASE = "https://api.core.ac.uk/v3"


def _first_url(work: dict[str, Any]) -> str | None:
    download = work.get("downloadUrl")
    if download:
        return download
    sources = work.get("sourceFulltextUrls") or []
    if sources:
        return sources[0]
    for link in work.get("links") or []:
        if isinstance(link, dict) and link.get("url"):
            return link["url"]
    return None


def _venue(work: dict[str, Any]) -> str | None:
    journals = work.get("journals") or []
    if journals and isinstance(journals[0], dict) and journals[0].get("title"):
        return clean_text(journals[0]["title"])
    return clean_text(work.get("publisher"))


def _map_work(work: dict[str, Any]) -> Work | None:
    title = clean_text(work.get("title"))
    if not title:
        return None

    authors: list[Author] = []
    for a in work.get("authors") or []:
        name = a.get("name") if isinstance(a, dict) else a
        if name:
            authors.append(Author(name=clean_text(str(name)) or str(name)))

    year = work.get("yearPublished")
    if isinstance(year, str) and year.isdigit():
        year = int(year)
    elif not isinstance(year, int):
        year = None

    download = _first_url(work)
    lang = work.get("language")
    language = lang.get("code") if isinstance(lang, dict) else (lang if isinstance(lang, str) else None)

    return Work(
        doi=normalize_doi(work.get("doi")),
        title=title,
        abstract=clean_text(work.get("abstract")),
        authors=authors,
        year=year,
        date=work.get("publishedDate") or None,
        venue=_venue(work),
        type=(work.get("documentType") or "article"),
        publisher=clean_text(work.get("publisher")),
        is_oa=(True if download else None),
        oa_status=("green" if download else None),
        pdf_url=download,
        landing_url=download,
        language=language,
        source_provider="core",
    )


class CoreProvider(Provider):
    name = "core"

    def available(self) -> bool:
        return get_settings().core_enabled

    def _headers(self) -> dict[str, str]:
        key = get_settings().core_api_key
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def _search_raw(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        if not self.available():
            return []
        params = {"q": query, "limit": min(max(limit, 1), 100)}
        try:
            data = await get_client().get_json(
                f"{_BASE}/search/works", params=params, headers=self._headers()
            )
        except HttpError:
            return []
        return data.get("results") or []

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,  # CORE is OA-only by nature
    ) -> list[Work]:
        q = query
        if year_from:
            q += f" AND yearPublished>={year_from}"
        if year_to:
            q += f" AND yearPublished<={year_to}"
        results = await self._search_raw(q, limit=limit)
        works = [w for w in (_map_work(r) for r in results) if w]
        return works

    async def get_work(self, identifier: str) -> Work | None:
        if not self.available():
            return None
        kind, value = detect_identifier(identifier)
        if kind != "doi":
            return None
        results = await self._search_raw(f'doi:"{value}"', limit=3)
        for raw in results:
            work = _map_work(raw)
            if work and work.doi == value:
                return work
        return None


core = CoreProvider()
