"""Live tests that hit external APIs. Run with: pytest -m live"""
import pytest

from athenaeum_mcp import service
from athenaeum_mcp.http_client import close_client
from athenaeum_mcp.providers import biorxiv, dblp, opencitations, pubmed

pytestmark = pytest.mark.live


async def test_meta_search_live():
    works = await service.meta_search("technostress workplace", limit=6)
    assert len(works) >= 1
    assert any(w.doi for w in works)
    assert all(w.title for w in works)
    await close_client()


async def test_get_work_live_enriched():
    work = await service.get_work("10.1128/jb.175.12.3749-3756.1993")
    assert work is not None
    assert work.title and "Spo0A" in work.title
    assert work.cited_by_count is not None
    await close_client()


async def test_citations_and_references_live():
    doi = "10.1128/jb.175.12.3749-3756.1993"
    cites = await service.get_citations(doi, limit=3)
    refs = await service.get_references(doi, limit=3)
    assert len(cites) >= 1
    assert len(refs) >= 1
    await close_client()


async def test_validate_source_live():
    result = await service.validate_source("10.1128/jb.175.12.3749-3756.1993")
    assert result["resolves"] is True
    assert 0 <= result["credibility_score"] <= 100
    await close_client()


async def test_pubmed_live():
    # A frozen, published 2020 article — metadata won't drift.
    work = await pubmed.get_work("pmid:32324623")
    assert work is not None
    assert work.pmid == "32324623"
    assert work.title and "echnostress" in work.title
    assert work.abstract  # efetch supplies the abstract
    await close_client()


async def test_dblp_live():
    works = await dblp.search("attention is all you need", limit=5)
    assert len(works) >= 1
    assert all(w.title for w in works)
    # DBLP is CS-centric and should surface at least one preprint/conference item.
    assert any(w.type in {"preprint", "conference-paper", "article"} for w in works)
    await close_client()


async def test_opencitations_live():
    doi = "10.1186/1756-8722-6-59"  # well covered by OpenCitations
    refs = await opencitations.get_references(doi, limit=10)
    cites = await opencitations.get_citations(doi, limit=10)
    assert len(refs) >= 1
    assert len(cites) >= 1
    # Stubs embed resolvable identifiers.
    assert any(r.doi or r.openalex_id for r in refs)
    await close_client()


async def test_biorxiv_live():
    work = await biorxiv.get_work("10.1101/2020.12.30.424878")
    assert work is not None
    assert work.venue == "bioRxiv"
    assert work.pdf_url and work.pdf_url.endswith(".full.pdf")
    assert work.abstract
    await close_client()

