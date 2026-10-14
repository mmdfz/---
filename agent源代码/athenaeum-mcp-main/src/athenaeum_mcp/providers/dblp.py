"""DBLP provider — computer-science bibliography (free, no key).

DBLP (https://dblp.org) is the definitive open bibliography for computer
science and adjacent fields. It has excellent coverage of conference papers and
preprints (including arXiv/CoRR), which complements the journal-centric sources
for the AI / ML / HCI side of a literature search.

Uses the public ``/search/publ/api`` endpoint (JSON). No key required; DBLP
asks callers to be polite, which the shared rate limiter enforces.
"""
from __future__ import annotations

from typing import Any

from ..http_client import HttpError, get_client
from ..models import Author, Work
from ..utils import clean_text, normalize_arxiv_id, normalize_doi
from .base import Provider

_BASE = "https://dblp.org/search/publ/api"

# DBLP "type" -> normalized Work.type.
_TYPE_MAP = {
    "Journal Articles": "article",
    "Conference and Workshop Papers": "conference-paper",
    "Informal and Other Publications": "preprint",
    "Books and Theses": "book",
    "Editorship": "article",
    "Reference Works": "reference",
    "Data and Artifacts": "dataset",
}


def _as_list(value: Any) -> list[Any]:
    """DBLP collapses single-element arrays to a bare object; normalize to a list."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _map_hit(info: dict[str, Any]) -> Work | None:
    title = clean_text(info.get("title"))
    if not title:
        return None

    authors: list[Author] = []
    for a in _as_list((info.get("authors") or {}).get("author")):
        if isinstance(a, dict):
            name = a.get("text")
        else:
            name = a
        if name:
            # DBLP disambiguates homonyms with a trailing number, e.g. "Iftekhar Ahmed 0001".
            authors.append(Author(name=clean_text(str(name).rstrip("0123456789 ")) or str(name)))

    year = None
    if str(info.get("year") or "").isdigit():
        year = int(info["year"])

    dblp_type = info.get("type") or ""
    venue = info.get("venue")
    if isinstance(venue, list):
        venue = ", ".join(str(v) for v in venue if v)

    doi = normalize_doi(info.get("doi"))
    # CoRR entries are arXiv preprints; recover the arXiv id from the volume.
    arxiv_id = None
    volume = info.get("volume")
    if venue == "CoRR" and isinstance(volume, str) and volume.startswith("abs/"):
        arxiv_id = normalize_arxiv_id(volume.split("/", 1)[1])
    if not arxiv_id and doi and doi.startswith("10.48550/arxiv."):
        arxiv_id = normalize_arxiv_id(doi.split("arxiv.", 1)[1])

    pages = info.get("pages")
    landing = info.get("ee") or info.get("url")

    return Work(
        doi=doi,
        arxiv_id=arxiv_id,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        venue_type=("repository" if dblp_type.startswith("Informal") else None),
        type=_TYPE_MAP.get(dblp_type, "article"),
        volume=(volume if venue != "CoRR" else None),
        issue=info.get("number"),
        pages=pages,
        is_oa=(info.get("access") == "open" or None),
        landing_url=landing,
        source_provider="dblp",
    )


class DblpProvider(Provider):
    name = "dblp"

    async def _query(self, query: str, *, limit: int) -> list[Work]:
        params = {"q": query, "format": "json", "h": min(max(limit, 1), 100)}
        try:
            data = await get_client().get_json(_BASE, params=params)
        except HttpError:
            return []
        hits = ((data.get("result") or {}).get("hits") or {}).get("hit") or []
        works: list[Work] = []
        for hit in _as_list(hits):
            info = hit.get("info") if isinstance(hit, dict) else None
            if not info:
                continue
            work = _map_hit(info)
            if work:
                works.append(work)
        return works

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,
    ) -> list[Work]:
        works = await self._query(query, limit=limit)
        if year_from or year_to:
            works = [
                w for w in works
                if w.year is None
                or ((year_from is None or w.year >= year_from) and (year_to is None or w.year <= year_to))
            ]
        if open_access_only:
            works = [w for w in works if w.is_oa or w.arxiv_id]
        return works

    async def get_work(self, identifier: str) -> Work | None:
        """Best-effort lookup: query DBLP for the identifier and match on DOI."""
        from ..utils import detect_identifier

        kind, value = detect_identifier(identifier)
        works = await self._query(value, limit=10)
        if kind == "doi":
            for w in works:
                if w.doi == value:
                    return w
        elif kind == "arxiv":
            for w in works:
                if w.arxiv_id == value:
                    return w
        return works[0] if works else None


dblp = DblpProvider()
