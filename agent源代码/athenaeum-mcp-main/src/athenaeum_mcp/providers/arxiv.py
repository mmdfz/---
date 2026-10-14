"""arXiv provider — preprints via the Atom export API."""
from __future__ import annotations

from typing import Any

import feedparser

from ..http_client import HttpError, get_client
from ..models import Author, Work
from ..utils import clean_text, normalize_arxiv_id, normalize_doi
from .base import Provider

_BASE = "http://export.arxiv.org/api/query"


def _entry_to_work(entry: Any) -> Work:
    arxiv_id = normalize_arxiv_id(entry.get("id"))
    pdf_url = None
    landing_url = entry.get("link")
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            pdf_url = link.get("href")
        elif link.get("rel") == "alternate":
            landing_url = link.get("href")

    authors = [Author(name=a.get("name", "Unknown")) for a in entry.get("authors", [])]
    published = entry.get("published", "")
    year = int(published[:4]) if published[:4].isdigit() else None

    categories = []
    primary = entry.get("arxiv_primary_category")
    if isinstance(primary, dict) and primary.get("term"):
        categories.append(primary["term"])
    for tag in entry.get("tags", []):
        term = tag.get("term")
        if term and term not in categories:
            categories.append(term)

    return Work(
        doi=normalize_doi(entry.get("arxiv_doi")),
        arxiv_id=arxiv_id,
        title=clean_text(entry.get("title")),
        abstract=clean_text(entry.get("summary")),
        authors=authors,
        year=year,
        date=published[:10] or None,
        venue=entry.get("arxiv_journal_ref") or "arXiv",
        venue_type="repository",
        type="preprint",
        pdf_url=pdf_url,
        landing_url=landing_url,
        is_oa=True,
        oa_status="green",
        topics=categories[:4],
        source_provider="arxiv",
    )


class ArxivProvider(Provider):
    name = "arxiv"

    async def _query(self, params: dict[str, Any]) -> list[Work]:
        try:
            resp = await get_client().get(_BASE, params=params, accept="application/atom+xml")
        except HttpError:
            return []
        if resp.status != 200:
            return []
        feed = feedparser.parse(resp.content)
        return [_entry_to_work(e) for e in feed.entries]

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,  # arXiv is always OA
    ) -> list[Work]:
        works = await self._query(
            {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": min(max(limit, 1), 100),
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
        )
        if year_from or year_to:
            works = [
                w for w in works
                if w.year is None
                or ((year_from is None or w.year >= year_from) and (year_to is None or w.year <= year_to))
            ]
        return works

    async def get_work(self, identifier: str) -> Work | None:
        arxiv_id = normalize_arxiv_id(identifier)
        if not arxiv_id:
            return None
        works = await self._query({"id_list": arxiv_id, "max_results": 1})
        return works[0] if works else None


arxiv = ArxivProvider()
