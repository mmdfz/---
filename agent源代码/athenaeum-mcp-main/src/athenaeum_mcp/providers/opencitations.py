"""OpenCitations provider — an independent open citation index (free, no key).

OpenCitations (https://opencitations.net) publishes open citation data under a
CC0 waiver. It is used as a *complement and fallback* to the OpenAlex citation
graph: occasionally it knows citations OpenAlex has not yet ingested (and vice
versa), so querying it improves recall for ``get_references`` / ``get_citations``.

The v2 index endpoints are used because each citation record embeds the
participating works' identifiers inline, e.g.::

    "cited": "omid:br/06190834283 doi:10.1186/... openalex:W2120377900 pmid:23958373"

That lets us return resolvable :class:`Work` stubs (DOI + OpenAlex id + PMID)
without a second metadata lookup; the service layer can then enrich them.

An optional ``OPENCITATIONS_ACCESS_TOKEN`` raises rate limits but is not
required.
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..http_client import HttpError, get_client
from ..models import Work
from ..utils import detect_identifier, normalize_doi
from .base import Provider

_INDEX = "https://opencitations.net/index/api/v2"
_META = "https://opencitations.net/meta/api/v1"


def _parse_id_blob(blob: str | None) -> dict[str, str]:
    """Parse a space-separated ``omid:.. doi:.. openalex:.. pmid:..`` field.

    Keeps the *first* value seen for each scheme (a field may list several DOIs).
    """
    out: dict[str, str] = {}
    for token in (blob or "").split():
        scheme, _, value = token.partition(":")
        if not value:
            continue
        scheme = scheme.lower()
        if scheme in out:
            continue
        out[scheme] = value
    return out


def _work_from_blob(blob: str | None) -> Work | None:
    ids = _parse_id_blob(blob)
    doi = normalize_doi(ids.get("doi"))
    openalex_id = ids.get("openalex")
    pmid = ids.get("pmid")
    if not (doi or openalex_id or pmid):
        return None
    return Work(
        doi=doi,
        openalex_id=openalex_id,
        pmid=pmid,
        source_provider="opencitations",
    )


class OpenCitationsProvider(Provider):
    name = "opencitations"

    def _headers(self) -> dict[str, str]:
        token = get_settings().opencitations_token
        return {"authorization": token} if token else {}

    async def _get(self, url: str) -> list[dict[str, Any]]:
        try:
            data = await get_client().get_json(url, headers=self._headers())
        except HttpError:
            return []
        return data if isinstance(data, list) else []

    async def get_references(self, identifier: str, *, limit: int = 50) -> list[Work]:
        """Works that *this* DOI cites, as resolvable stubs."""
        kind, value = detect_identifier(identifier)
        if kind != "doi":
            return []
        rows = await self._get(f"{_INDEX}/references/doi:{value}")
        works: list[Work] = []
        for row in rows[: max(limit, 0)] if limit else rows:
            work = _work_from_blob(row.get("cited"))
            if work:
                works.append(work)
        return works

    async def get_citations(self, identifier: str, *, limit: int = 50) -> list[Work]:
        """Works that cite *this* DOI, as resolvable stubs."""
        kind, value = detect_identifier(identifier)
        if kind != "doi":
            return []
        rows = await self._get(f"{_INDEX}/citations/doi:{value}")
        works: list[Work] = []
        for row in rows[: max(limit, 0)] if limit else rows:
            work = _work_from_blob(row.get("citing"))
            if work:
                works.append(work)
        return works

    async def citation_count(self, identifier: str) -> int | None:
        kind, value = detect_identifier(identifier)
        if kind != "doi":
            return None
        # The v1 count endpoint takes a bare DOI (verified against the live API).
        rows = await self._get(f"https://opencitations.net/index/api/v1/citation-count/{value}")
        if rows and str(rows[0].get("count", "")).isdigit():
            return int(rows[0]["count"])
        return None


opencitations = OpenCitationsProvider()
