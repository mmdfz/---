"""OpenAlex provider — the backbone of Athenaeum.

OpenAlex (https://openalex.org) is a free, open catalog of ~250M scholarly
works with rich metadata: abstracts (as inverted index), references, citations,
related works, venue and author metrics, open-access locations and retraction
flags. No API key required; an email enables the faster "polite pool".
"""
from __future__ import annotations

import html
from typing import Any

from ..config import get_settings
from ..http_client import HttpError, get_client
from ..models import Author, AuthorProfile, Venue, Work
from ..utils import (
    detect_identifier,
    normalize_openalex_id,
    reconstruct_abstract,
)
from .base import Provider

_BASE = "https://api.openalex.org"

# Fields requested for works (keeps payloads small and fast).
_WORK_SELECT = ",".join(
    [
        "id", "doi", "title", "display_name", "publication_year", "publication_date",
        "type", "cited_by_count", "referenced_works_count", "referenced_works",
        "related_works", "is_retracted", "language", "open_access",
        "primary_location", "best_oa_location", "authorships", "biblio",
        "topics", "keywords", "ids", "abstract_inverted_index", "relevance_score",
    ]
)


def _short_id(url: str | None) -> str | None:
    """'https://openalex.org/W123' -> 'W123' (works for A/S/I ids too)."""
    if not url:
        return None
    return url.rstrip("/").rsplit("/", 1)[-1]


def _unescape(url: str | None) -> str | None:
    """OpenAlex sometimes returns URLs with HTML entities (e.g. &amp;)."""
    return html.unescape(url) if url else None


def _map_work(raw: dict[str, Any]) -> Work:
    ids = raw.get("ids") or {}
    pl = raw.get("primary_location") or {}
    source = pl.get("source") or {}
    best_oa = raw.get("best_oa_location") or {}
    oa = raw.get("open_access") or {}
    biblio = raw.get("biblio") or {}

    authors: list[Author] = []
    for a in raw.get("authorships") or []:
        person = a.get("author") or {}
        insts = a.get("institutions") or []
        authors.append(
            Author(
                name=person.get("display_name") or a.get("raw_author_name") or "Unknown",
                orcid=person.get("orcid"),
                openalex_id=_short_id(person.get("id")),
                affiliation=(insts[0].get("display_name") if insts else None),
            )
        )

    pages = None
    fp, lp = biblio.get("first_page"), biblio.get("last_page")
    if fp and lp:
        pages = f"{fp}-{lp}"
    elif fp:
        pages = str(fp)

    topics = [t.get("display_name") for t in (raw.get("topics") or []) if t.get("display_name")][:4]
    keywords = [k.get("display_name") for k in (raw.get("keywords") or []) if k.get("display_name")][:6]

    pmid = _pubmed_number(ids.get("pmid"))
    pmcid = _short_id(ids.get("pmcid")) if ids.get("pmcid") else None

    return Work(
        doi=raw.get("doi"),
        openalex_id=_short_id(raw.get("id")),
        pmid=pmid,
        pmcid=pmcid,
        mag_id=str(ids["mag"]) if ids.get("mag") else None,
        title=raw.get("title") or raw.get("display_name"),
        abstract=reconstruct_abstract(raw.get("abstract_inverted_index")),
        authors=authors,
        year=raw.get("publication_year"),
        date=raw.get("publication_date"),
        venue=source.get("display_name"),
        venue_issn=[i for i in (source.get("issn") or []) if i],
        venue_type=source.get("type"),
        type=raw.get("type"),
        publisher=source.get("host_organization_name"),
        volume=biblio.get("volume"),
        issue=biblio.get("issue"),
        pages=pages,
        cited_by_count=raw.get("cited_by_count"),
        reference_count=raw.get("referenced_works_count"),
        is_oa=oa.get("is_oa"),
        oa_status=oa.get("oa_status"),
        pdf_url=_unescape(best_oa.get("pdf_url") or pl.get("pdf_url")),
        landing_url=_unescape(pl.get("landing_page_url") or (raw.get("doi"))),
        is_retracted=raw.get("is_retracted"),
        topics=topics,
        keywords=keywords,
        language=raw.get("language"),
        relevance_score=raw.get("relevance_score"),
        source_provider="openalex",
    )


def _pubmed_number(pmid_url: str | None) -> str | None:
    if not pmid_url:
        return None
    return pmid_url.rstrip("/").rsplit("/", 1)[-1]


class OpenAlexProvider(Provider):
    name = "openalex"

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
        filters: list[str] = []
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if open_access_only:
            filters.append("is_oa:true")

        params = self._params(
            search=query,
            select=_WORK_SELECT,
            per_page=min(max(limit, 1), 200),
        )
        if filters:
            params["filter"] = ",".join(filters)

        data = await get_client().get_json(f"{_BASE}/works", params=params)
        return [_map_work(w) for w in data.get("results", [])]

    async def get_work(self, identifier: str) -> Work | None:
        kind, value = detect_identifier(identifier)
        path = None
        if kind == "doi":
            path = f"doi:{value}"
        elif kind == "openalex":
            path = value
        elif kind == "pmid":
            path = f"pmid:{value}"
        elif kind == "pmcid":
            path = f"pmcid:{value}"
        elif kind == "arxiv":
            base = value.split("v")[0]
            path = f"doi:10.48550/arXiv.{base}"
        if path is None:
            return None
        try:
            data = await get_client().get_json(
                f"{_BASE}/works/{path}", params=self._params(select=_WORK_SELECT)
            )
        except HttpError:
            return None
        return _map_work(data)

    async def get_oa_candidates(self, identifier: str) -> list[dict[str, str]]:
        """Return every open-access PDF / landing-page candidate OpenAlex knows.

        OpenAlex indexes a work across many ``locations`` (publisher, DOAJ,
        institutional repositories, preprint servers …). Each can carry a direct
        ``pdf_url`` or a ``landing_page_url`` from which a PDF link can be
        resolved. Returning all of them lets the reader fall back from a blocked
        publisher copy to an accessible repository copy.

        Each candidate is ``{"source": str, "url": str, "kind": "pdf"|"landing"}``.
        """
        kind, value = detect_identifier(identifier)
        if kind == "doi":
            path = f"doi:{value}"
        elif kind == "openalex":
            path = value
        elif kind == "pmid":
            path = f"pmid:{value}"
        elif kind == "pmcid":
            path = f"pmcid:{value}"
        elif kind == "arxiv":
            path = f"doi:10.48550/arXiv.{value.split('v')[0]}"
        else:
            return []
        try:
            data = await get_client().get_json(
                f"{_BASE}/works/{path}",
                params=self._params(select="locations,best_oa_location,primary_location"),
            )
        except HttpError:
            return []

        candidates: list[dict[str, str]] = []
        seen: set[str] = set()

        def _add(url: str | None, name: str | None, kind_: str) -> None:
            if not url:
                return
            clean = html.unescape(url)
            if clean in seen:
                return
            seen.add(clean)
            candidates.append({"source": name or "openalex", "url": clean, "kind": kind_})

        # Prefer the curated best OA location first, then every other location.
        best = data.get("best_oa_location") or {}
        _add(best.get("pdf_url"), (best.get("source") or {}).get("display_name"), "pdf")
        for loc in data.get("locations") or []:
            src = (loc.get("source") or {}).get("display_name")
            _add(loc.get("pdf_url"), src, "pdf")
        # Landing pages (for citation_pdf_url resolution) come after direct PDFs.
        _add(best.get("landing_page_url"), (best.get("source") or {}).get("display_name"), "landing")
        for loc in data.get("locations") or []:
            if loc.get("is_oa"):
                src = (loc.get("source") or {}).get("display_name")
                _add(loc.get("landing_page_url"), src, "landing")
        return candidates

    async def get_works_by_ids(self, openalex_ids: list[str], *, limit: int = 50) -> list[Work]:
        """Batch-fetch works by OpenAlex IDs (chunked with the pipe-OR filter)."""
        clean = [normalize_openalex_id(i) for i in openalex_ids]
        clean = [i for i in clean if i][:limit]
        if not clean:
            return []
        works: list[Work] = []
        for chunk_start in range(0, len(clean), 50):
            chunk = clean[chunk_start : chunk_start + 50]
            params = self._params(
                filter=f"openalex_id:{'|'.join(chunk)}",
                select=_WORK_SELECT,
                per_page=len(chunk),
            )
            data = await get_client().get_json(f"{_BASE}/works", params=params)
            works.extend(_map_work(w) for w in data.get("results", []))
        return works

    async def get_references(self, identifier: str, *, limit: int = 50) -> list[Work]:
        kind, value = detect_identifier(identifier)
        path = f"doi:{value}" if kind == "doi" else value if kind == "openalex" else None
        if path is None:
            work = await self.get_work(identifier)
            if work is None or not work.openalex_id:
                return []
            path = work.openalex_id
        data = await get_client().get_json(
            f"{_BASE}/works/{path}", params=self._params(select="referenced_works")
        )
        refs = data.get("referenced_works") or []
        return await self.get_works_by_ids(refs, limit=limit)

    async def get_citations(
        self, identifier: str, *, limit: int = 25, sort_by_citations: bool = True
    ) -> list[Work]:
        oa_id = await self._resolve_openalex_id(identifier)
        if not oa_id:
            return []
        params = self._params(
            filter=f"cites:{oa_id}",
            select=_WORK_SELECT,
            per_page=min(max(limit, 1), 200),
            sort="cited_by_count:desc" if sort_by_citations else None,
        )
        data = await get_client().get_json(f"{_BASE}/works", params=params)
        return [_map_work(w) for w in data.get("results", [])]

    async def get_related(self, identifier: str, *, limit: int = 25) -> list[Work]:
        kind, value = detect_identifier(identifier)
        path = f"doi:{value}" if kind == "doi" else value if kind == "openalex" else None
        if path is None:
            work = await self.get_work(identifier)
            if work is None or not work.openalex_id:
                return []
            path = work.openalex_id
        data = await get_client().get_json(
            f"{_BASE}/works/{path}", params=self._params(select="related_works")
        )
        related = data.get("related_works") or []
        return await self.get_works_by_ids(related, limit=limit)

    async def _resolve_openalex_id(self, identifier: str) -> str | None:
        kind, value = detect_identifier(identifier)
        if kind == "openalex":
            return value
        work = await self.get_work(identifier)
        return work.openalex_id if work else None

    # ----- venues & authors ------------------------------------------------
    async def get_source(self, issn_or_id: str) -> Venue | None:
        ident = issn_or_id.strip()
        if ident.upper().startswith("S") and ident[1:].isdigit():
            path = ident
        else:
            path = f"issn:{ident}"
        try:
            raw = await get_client().get_json(
                f"{_BASE}/sources/{path}", params=self._params()
            )
        except HttpError:
            return None
        return _map_source(raw)

    async def search_author(self, name: str) -> AuthorProfile | None:
        data = await get_client().get_json(
            f"{_BASE}/authors", params=self._params(search=name, per_page=1)
        )
        results = data.get("results") or []
        return _map_author(results[0]) if results else None

    async def get_author(self, author_id: str) -> AuthorProfile | None:
        ident = author_id.strip()
        path = ident if ident.upper().startswith("A") else f"orcid:{ident}"
        try:
            raw = await get_client().get_json(
                f"{_BASE}/authors/{path}", params=self._params()
            )
        except HttpError:
            return None
        return _map_author(raw)


def _map_source(raw: dict[str, Any]) -> Venue:
    stats = raw.get("summary_stats") or {}
    return Venue(
        id=_short_id(raw.get("id")),
        name=raw.get("display_name"),
        issn_l=raw.get("issn_l"),
        issn=[i for i in (raw.get("issn") or []) if i],
        type=raw.get("type"),
        publisher=raw.get("host_organization_name"),
        country=raw.get("country_code"),
        homepage_url=raw.get("homepage_url"),
        is_oa=raw.get("is_oa"),
        is_in_doaj=raw.get("is_in_doaj"),
        is_core=raw.get("is_core"),
        h_index=stats.get("h_index"),
        impact_2yr=stats.get("2yr_mean_citedness"),
        i10_index=stats.get("i10_index"),
        works_count=raw.get("works_count"),
        cited_by_count=raw.get("cited_by_count"),
        apc_usd=raw.get("apc_usd"),
    )


def _map_author(raw: dict[str, Any]) -> AuthorProfile:
    stats = raw.get("summary_stats") or {}
    last_inst = (raw.get("last_known_institutions") or [{}])
    affiliation = last_inst[0].get("display_name") if last_inst else None
    topics = [t.get("display_name") for t in (raw.get("topics") or []) if t.get("display_name")][:6]
    return AuthorProfile(
        id=_short_id(raw.get("id")),
        name=raw.get("display_name"),
        orcid=raw.get("orcid"),
        affiliation=affiliation,
        works_count=raw.get("works_count"),
        cited_by_count=raw.get("cited_by_count"),
        h_index=stats.get("h_index"),
        i10_index=stats.get("i10_index"),
        topics=topics,
    )


openalex = OpenAlexProvider()
