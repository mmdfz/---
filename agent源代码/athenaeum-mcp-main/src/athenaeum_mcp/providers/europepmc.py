"""Europe PMC provider — biomedical / life-sciences literature and full text."""
from __future__ import annotations

from typing import Any

from ..http_client import HttpError, get_client
from ..models import Author, Work
from ..utils import clean_text, detect_identifier
from .base import Provider

_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def _map_result(r: dict[str, Any]) -> Work:
    journal = (r.get("journalInfo") or {}).get("journal") or {}
    info = r.get("journalInfo") or {}

    authors: list[Author] = []
    for a in ((r.get("authorList") or {}).get("author") or []):
        name = a.get("fullName") or " ".join(p for p in (a.get("firstName"), a.get("lastName")) if p)
        if name:
            authors.append(Author(name=name, family=a.get("lastName"), given=a.get("firstName")))
    if not authors and r.get("authorString"):
        authors = [Author(name=n.strip()) for n in r["authorString"].split(",") if n.strip()][:25]

    pdf_url = None
    for u in ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or []):
        if (u.get("documentStyle") or "").lower() == "pdf":
            pdf_url = u.get("url")
            break

    pub_types = (r.get("pubTypeList") or {}).get("pubType") or []
    work_type = "article"
    if any("preprint" in str(p).lower() for p in pub_types):
        work_type = "preprint"

    year = None
    if r.get("pubYear") and str(r["pubYear"]).isdigit():
        year = int(r["pubYear"])

    return Work(
        doi=r.get("doi"),
        pmid=r.get("pmid"),
        pmcid=r.get("pmcid"),
        title=clean_text(r.get("title")),
        abstract=clean_text(r.get("abstractText")),
        authors=authors,
        year=year,
        date=r.get("firstPublicationDate"),
        venue=journal.get("title"),
        venue_issn=[i for i in (journal.get("issn"), journal.get("essn")) if i],
        type=work_type,
        volume=info.get("volume"),
        issue=info.get("issue"),
        cited_by_count=r.get("citedByCount"),
        is_oa=(r.get("isOpenAccess") == "Y"),
        oa_status=("green" if r.get("isOpenAccess") == "Y" else None),
        pdf_url=pdf_url,
        source_provider="europepmc",
    )


class EuropePMCProvider(Provider):
    name = "europepmc"

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        open_access_only: bool = False,
    ) -> list[Work]:
        q = query
        if year_from or year_to:
            lo = year_from or 1800
            hi = year_to or 2100
            q += f" AND (PUB_YEAR:[{lo} TO {hi}])"
        if open_access_only:
            q += " AND (OPEN_ACCESS:y)"
        params = {
            "query": q,
            "format": "json",
            "pageSize": min(max(limit, 1), 100),
            "resultType": "core",
        }
        try:
            data = await get_client().get_json(f"{_BASE}/search", params=params)
        except HttpError:
            return []
        results = (data.get("resultList") or {}).get("result") or []
        return [_map_result(r) for r in results]

    async def get_work(self, identifier: str) -> Work | None:
        kind, value = detect_identifier(identifier)
        if kind == "doi":
            q = f'DOI:"{value}"'
        elif kind == "pmid":
            q = f"EXT_ID:{value} AND SRC:MED"
        elif kind == "pmcid":
            q = f"PMCID:{value}"
        else:
            return None
        params = {"query": q, "format": "json", "pageSize": 1, "resultType": "core"}
        try:
            data = await get_client().get_json(f"{_BASE}/search", params=params)
        except HttpError:
            return None
        results = (data.get("resultList") or {}).get("result") or []
        return _map_result(results[0]) if results else None


europepmc = EuropePMCProvider()
