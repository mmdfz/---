"""bioRxiv / medRxiv provider — preprint metadata + full text (free, no key).

The bioRxiv API (https://api.biorxiv.org) serves metadata for bioRxiv and
medRxiv preprints, including the abstract and a link to the full-text JATS XML
and PDF. Both servers mint DOIs under the ``10.1101/`` prefix, so a DOI alone
does not say which server a preprint lives on; this provider tries bioRxiv then
medRxiv.

There is no free-text search endpoint, so this provider only resolves a known
preprint DOI (``get_work``). Its value is completing the picture for preprints —
giving the agent a readable abstract/PDF and flagging any published journal
version — which complements ``read_pdf`` and ``get_work`` enrichment.
"""
from __future__ import annotations

from typing import Any

from ..http_client import HttpError, get_client
from ..models import Author, Work
from ..utils import clean_text, normalize_doi
from .base import Provider

_BASE = "https://api.biorxiv.org/details"
_SERVERS = ("biorxiv", "medrxiv")
_PREPRINT_DOI_PREFIX = "10.1101/"


def _parse_authors(raw: str | None) -> list[Author]:
    """bioRxiv lists authors as 'Last, F. M.; Last2, G.; ...'."""
    if not raw:
        return []
    authors: list[Author] = []
    for chunk in raw.split(";"):
        name = clean_text(chunk)
        if not name:
            continue
        family = name.split(",", 1)[0].strip() if "," in name else None
        authors.append(Author(name=name, family=family))
    return authors[:50]


def _map_detail(detail: dict[str, Any], server: str) -> Work:
    doi = normalize_doi(detail.get("doi"))
    version = str(detail.get("version") or "1")
    date = detail.get("date")
    year = int(date[:4]) if date and date[:4].isdigit() else None
    server_name = "medRxiv" if server == "medrxiv" else "bioRxiv"

    pdf_url = None
    if doi:
        pdf_url = f"https://www.{server}.org/content/{doi}v{version}.full.pdf"

    category = detail.get("category")
    topics = [category] if category else []

    # ``published`` is the DOI of the peer-reviewed version, if one exists.
    published_doi = detail.get("published")
    if isinstance(published_doi, str) and published_doi.upper() in {"NA", ""}:
        published_doi = None

    return Work(
        doi=doi,
        title=clean_text(detail.get("title")),
        abstract=clean_text(detail.get("abstract")),
        authors=_parse_authors(detail.get("authors")),
        year=year,
        date=date,
        venue=server_name,
        venue_type="repository",
        type="preprint",
        is_oa=True,
        oa_status="green",
        pdf_url=pdf_url,
        landing_url=(f"https://www.{server}.org/content/{doi}v{version}" if doi else None),
        topics=topics,
        source_provider="biorxiv",
    )


class BiorxivProvider(Provider):
    name = "biorxiv"

    async def _fetch(self, server: str, doi: str) -> Work | None:
        try:
            data = await get_client().get_json(f"{_BASE}/{server}/{doi}")
        except HttpError:
            return None
        collection = data.get("collection") or []
        if not collection:
            return None
        # The API returns one record per version; the last is the most recent.
        return _map_detail(collection[-1], server)

    async def get_work(self, identifier: str) -> Work | None:
        doi = normalize_doi(identifier)
        if not doi or not doi.startswith(_PREPRINT_DOI_PREFIX):
            return None
        for server in _SERVERS:
            work = await self._fetch(server, doi)
            if work and work.title:
                return work
        return None


biorxiv = BiorxivProvider()
