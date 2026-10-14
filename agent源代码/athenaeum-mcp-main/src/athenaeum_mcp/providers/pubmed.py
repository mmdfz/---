"""PubMed provider — NCBI E-utilities (biomedical, psychology, behavioral science).

PubMed/MEDLINE is the authoritative index for the life and behavioral sciences.
It is **100% free and needs no API key**; an optional ``NCBI_API_KEY`` only
raises the request ceiling from 3 to 10 requests/second.

Coverage overlaps Europe PMC (which mirrors MEDLINE), but PubMed is an
*independent* index with its own relevance ranking and MeSH controlled
vocabulary, so it strengthens the meta-search rank fusion and contributes
subject keywords other providers lack.

Search uses ESearch (PMIDs) followed by EFetch (full records as XML), so each
result carries an abstract, authors, DOI and MeSH terms — not just a summary.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ..config import get_settings
from ..http_client import HttpError, get_client
from ..models import Author, Work
from ..utils import clean_text, detect_identifier, normalize_doi
from .base import Provider

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
_TOOL = "athenaeum-mcp"

# PublicationType values that mark a record as something other than a primary
# research article (used to set ``Work.type``).
_PREPRINT_TYPES = {"preprint"}


def _node_text(node: ET.Element | None) -> str | None:
    """Concatenate all descendant text of *node* (handles inline tags like <i>)."""
    if node is None:
        return None
    return clean_text("".join(node.itertext()))


def _eutils_params(**extra: Any) -> dict[str, Any]:
    settings = get_settings()
    params: dict[str, Any] = {"tool": _TOOL, "email": settings.mailto}
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    params.update({k: v for k, v in extra.items() if v is not None})
    return params


def _extract_doi(article: ET.Element, pubmed_data: ET.Element | None) -> str | None:
    for el in article.findall(".//ELocationID"):
        if (el.get("EIdType") or "").lower() == "doi" and el.text:
            return normalize_doi(el.text)
    if pubmed_data is not None:
        for el in pubmed_data.findall(".//ArticleId"):
            if (el.get("IdType") or "").lower() == "doi" and el.text:
                return normalize_doi(el.text)
    return None


def _extract_article_id(pubmed_data: ET.Element | None, id_type: str) -> str | None:
    if pubmed_data is None:
        return None
    for el in pubmed_data.findall(".//ArticleId"):
        if (el.get("IdType") or "").lower() == id_type and el.text:
            return el.text.strip()
    return None


def _parse_authors(article: ET.Element) -> list[Author]:
    authors: list[Author] = []
    for a in article.findall(".//AuthorList/Author"):
        collective = a.findtext("CollectiveName")
        if collective:
            authors.append(Author(name=clean_text(collective) or collective))
            continue
        last = a.findtext("LastName")
        fore = a.findtext("ForeName") or a.findtext("Initials")
        if not last and not fore:
            continue
        name = " ".join(p for p in (fore, last) if p)
        authors.append(Author(name=name, family=last, given=fore))
    return authors


def _parse_abstract(article: ET.Element) -> str | None:
    parts: list[str] = []
    for node in article.findall(".//Abstract/AbstractText"):
        text = _node_text(node)
        if not text:
            continue
        label = node.get("Label")
        parts.append(f"{label}: {text}" if label else text)
    return " ".join(parts) if parts else None


def _parse_year(article: ET.Element) -> int | None:
    pub_date = article.find(".//Journal/JournalIssue/PubDate")
    if pub_date is not None:
        year = pub_date.findtext("Year")
        if year and year.isdigit():
            return int(year)
        medline = pub_date.findtext("MedlineDate")  # e.g. "2020 Jan-Feb"
        if medline:
            for token in medline.split():
                if token[:4].isdigit():
                    return int(token[:4])
    return None


def _work_type(article: ET.Element) -> str:
    types = [(_node_text(t) or "").lower() for t in article.findall(".//PublicationTypeList/PublicationType")]
    if any(t in _PREPRINT_TYPES for t in types):
        return "preprint"
    return "article"


def _parse_article(elem: ET.Element) -> Work | None:
    medline = elem.find("MedlineCitation")
    if medline is None:
        return None
    article = medline.find("Article")
    if article is None:
        return None
    pubmed_data = elem.find("PubmedData")

    pmid = medline.findtext("PMID")
    title = _node_text(article.find("ArticleTitle"))
    journal = article.find("Journal")
    venue = _node_text(journal.find("Title")) if journal is not None else None
    issns = [i.text for i in (journal.findall("ISSN") if journal is not None else []) if i.text]

    biblio = article.find(".//Journal/JournalIssue")
    volume = biblio.findtext("Volume") if biblio is not None else None
    issue = biblio.findtext("Issue") if biblio is not None else None
    pages = article.findtext(".//Pagination/MedlinePgn") or article.findtext(".//Pagination/StartPage")

    mesh = [
        _node_text(d)
        for d in medline.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
        if _node_text(d)
    ]

    pmcid = _extract_article_id(pubmed_data, "pmc")

    return Work(
        doi=_extract_doi(article, pubmed_data),
        pmid=pmid.strip() if pmid else None,
        pmcid=pmcid,
        title=title,
        abstract=_parse_abstract(article),
        authors=_parse_authors(article),
        year=_parse_year(article),
        venue=venue,
        venue_issn=issns,
        type=_work_type(article),
        volume=volume,
        issue=issue,
        pages=pages,
        is_oa=(True if pmcid else None),
        oa_status=("green" if pmcid else None),
        keywords=mesh[:8],
        language=article.findtext(".//Language"),
        source_provider="pubmed",
    )


class PubMedProvider(Provider):
    name = "pubmed"

    async def _esearch(
        self,
        query: str,
        *,
        limit: int,
        year_from: int | None,
        year_to: int | None,
        open_access_only: bool,
    ) -> list[str]:
        term = query
        if open_access_only:
            term += ' AND "free full text"[Filter]'
        params = _eutils_params(
            db="pubmed",
            term=term,
            retmode="json",
            retmax=min(max(limit, 1), 100),
            sort="relevance",
        )
        if year_from or year_to:
            params["mindate"] = f"{year_from or 1800}"
            params["maxdate"] = f"{year_to or 2100}"
            params["datetype"] = "pdat"
        try:
            data = await get_client().get_json(f"{_BASE}/esearch.fcgi", params=params)
        except HttpError:
            return []
        return (data.get("esearchresult") or {}).get("idlist") or []

    async def _efetch(self, pmids: list[str]) -> list[Work]:
        if not pmids:
            return []
        params = _eutils_params(db="pubmed", id=",".join(pmids), retmode="xml")
        try:
            resp = await get_client().get(f"{_BASE}/efetch.fcgi", params=params, accept="application/xml")
        except HttpError:
            return []
        if resp.status != 200:
            return []
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError:
            return []
        works: list[Work] = []
        for elem in root.findall("PubmedArticle"):
            work = _parse_article(elem)
            if work:
                works.append(work)
        # Preserve PubMed's relevance ordering (efetch returns input order).
        order = {pmid: i for i, pmid in enumerate(pmids)}
        works.sort(key=lambda w: order.get(w.pmid or "", 1_000_000))
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
        pmids = await self._esearch(
            query, limit=limit, year_from=year_from, year_to=year_to, open_access_only=open_access_only
        )
        return await self._efetch(pmids)

    async def get_work(self, identifier: str) -> Work | None:
        kind, value = detect_identifier(identifier)
        if kind == "pmid":
            pmids = [value]
        elif kind == "pmcid":
            pmids = await self._esearch(f"{value}[PMCID]", limit=1, year_from=None, year_to=None, open_access_only=False)
        elif kind == "doi":
            pmids = await self._esearch(f'"{value}"[AID]', limit=1, year_from=None, year_to=None, open_access_only=False)
        else:
            return None
        works = await self._efetch(pmids[:1])
        return works[0] if works else None


pubmed = PubMedProvider()
