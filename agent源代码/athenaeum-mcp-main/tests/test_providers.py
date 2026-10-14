"""Offline unit tests for the provider mapping logic.

These exercise the pure response-mapping functions of each new provider against
fixtures shaped like the real API responses (captured via scripts/probe_apis3).
No network access — deterministic and fast.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from athenaeum_mcp.providers import (
    SEARCH_PROVIDERS,
    core,
    default_search_providers,
)
from athenaeum_mcp.providers.biorxiv import _map_detail, _parse_authors, biorxiv
from athenaeum_mcp.providers.core import _map_work as core_map_work
from athenaeum_mcp.providers.dblp import _as_list, _map_hit
from athenaeum_mcp.providers.opencitations import _parse_id_blob, _work_from_blob
from athenaeum_mcp.providers.pubmed import _parse_article


# --------------------------------------------------------------------------- #
# Registry wiring
# --------------------------------------------------------------------------- #
def test_registry_membership():
    # Free-text search providers.
    assert "pubmed" in SEARCH_PROVIDERS
    assert "dblp" in SEARCH_PROVIDERS
    assert "core" in SEARCH_PROVIDERS
    # Non-search providers must NOT be registered as searchable.
    assert "opencitations" not in SEARCH_PROVIDERS
    assert "biorxiv" not in SEARCH_PROVIDERS


def test_default_providers_includes_pubmed_not_dblp():
    defaults = default_search_providers()
    assert "pubmed" in defaults
    assert "openalex" in defaults
    # DBLP is CS-only; opt-in, not default.
    assert "dblp" not in defaults
    # CORE is gated off without a key.
    assert "core" not in defaults


# --------------------------------------------------------------------------- #
# PubMed XML parsing
# --------------------------------------------------------------------------- #
_PUBMED_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation Status="MEDLINE" Owner="NLM">
    <PMID Version="1">37179875</PMID>
    <Article PubModel="Print">
      <Journal>
        <ISSN IssnType="Print">1664-1078</ISSN>
        <JournalIssue CitedMedium="Print">
          <Volume>14</Volume>
          <Issue>3</Issue>
          <PubDate><Year>2023</Year></PubDate>
        </JournalIssue>
        <Title>Frontiers in psychology</Title>
      </Journal>
      <ArticleTitle>Technostress at work: a <i>systematic</i> review.</ArticleTitle>
      <Pagination><MedlinePgn>1173425</MedlinePgn></Pagination>
      <ELocationID EIdType="doi" ValidYN="Y">10.3389/fpsyg.2023.1173425</ELocationID>
      <Abstract>
        <AbstractText Label="BACKGROUND">Technostress is a phenomenon.</AbstractText>
        <AbstractText Label="METHODS">We did a review.</AbstractText>
      </Abstract>
      <AuthorList>
        <Author><LastName>Smith</LastName><ForeName>Jane A</ForeName></Author>
        <Author><CollectiveName>WHO Working Group</CollectiveName></Author>
      </AuthorList>
      <Language>eng</Language>
      <PublicationTypeList>
        <PublicationType UI="D016428">Journal Article</PublicationType>
        <PublicationType UI="D016454">Review</PublicationType>
      </PublicationTypeList>
    </Article>
    <MeshHeadingList>
      <MeshHeading><DescriptorName UI="D013315">Stress, Psychological</DescriptorName></MeshHeading>
      <MeshHeading><DescriptorName UI="D000071079">Occupational Stress</DescriptorName></MeshHeading>
    </MeshHeadingList>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">37179875</ArticleId>
      <ArticleId IdType="doi">10.3389/fpsyg.2023.1173425</ArticleId>
      <ArticleId IdType="pmc">PMC10123456</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>"""


def test_pubmed_parse_article():
    root = ET.fromstring(_PUBMED_XML)
    work = _parse_article(root.find("PubmedArticle"))
    assert work is not None
    assert work.pmid == "37179875"
    assert work.doi == "10.3389/fpsyg.2023.1173425"
    assert work.pmcid == "PMC10123456"
    # Inline <i> markup is stripped; whitespace collapsed.
    assert work.title == "Technostress at work: a systematic review."
    # Structured abstract sections are labelled and concatenated.
    assert "BACKGROUND: Technostress is a phenomenon." in work.abstract
    assert "METHODS: We did a review." in work.abstract
    assert work.year == 2023
    assert work.venue == "Frontiers in psychology"
    assert work.venue_issn == ["1664-1078"]
    assert work.volume == "14"
    assert work.issue == "3"
    assert work.pages == "1173425"
    # Collective + personal authors both captured.
    names = work.author_names
    assert "Jane A Smith" in names
    assert "WHO Working Group" in names
    assert work.authors[0].family == "Smith"
    # MeSH terms become keywords.
    assert "Occupational Stress" in work.keywords
    # PMCID implies free full text.
    assert work.is_oa is True
    assert work.oa_status == "green"
    assert work.source_provider == "pubmed"
    assert "pubmed" in work.providers


# --------------------------------------------------------------------------- #
# DBLP mapping
# --------------------------------------------------------------------------- #
def test_dblp_as_list_normalizes():
    assert _as_list(None) == []
    assert _as_list({"a": 1}) == [{"a": 1}]
    assert _as_list([1, 2]) == [1, 2]


def test_dblp_map_hit_conference_list_authors():
    info = {
        "authors": {"author": [
            {"@pid": "1", "text": "Jane Smith"},
            {"@pid": "2", "text": "Iftekhar Ahmed 0001"},
        ]},
        "title": "Attention Is All You Need.",
        "venue": "NeurIPS",
        "year": "2017",
        "type": "Conference and Workshop Papers",
        "access": "open",
        "doi": "10.5555/3295222.3295349",
        "ee": "https://example.org/paper",
        "pages": "5998-6008",
    }
    work = _map_hit(info)
    assert work is not None
    assert work.type == "conference-paper"
    assert work.year == 2017
    assert work.venue == "NeurIPS"
    assert work.is_oa is True
    assert work.landing_url == "https://example.org/paper"
    assert work.doi == "10.5555/3295222.3295349"
    # Trailing DBLP homonym disambiguator is stripped from author names.
    assert work.author_names == ["Jane Smith", "Iftekhar Ahmed"]


def test_dblp_map_hit_corr_preprint_single_author():
    info = {
        "authors": {"author": {"@pid": "3", "text": "Solo Author"}},
        "title": "A Preprint.",
        "venue": "CoRR",
        "volume": "abs/2402.16790",
        "year": "2024",
        "type": "Informal and Other Publications",
        "access": "open",
        "doi": "10.48550/ARXIV.2402.16790",
        "ee": "https://doi.org/10.48550/arXiv.2402.16790",
    }
    work = _map_hit(info)
    assert work is not None
    assert work.type == "preprint"
    assert work.venue_type == "repository"
    # arXiv id recovered from the CoRR volume; volume itself suppressed.
    assert work.arxiv_id == "2402.16790"
    assert work.volume is None
    assert work.author_names == ["Solo Author"]


def test_dblp_map_hit_requires_title():
    assert _map_hit({"title": ""}) is None


# --------------------------------------------------------------------------- #
# OpenCitations identifier-blob parsing
# --------------------------------------------------------------------------- #
def test_opencitations_parse_id_blob_first_wins():
    blob = "omid:br/06190834283 doi:10.1186/First doi:10.1/second openalex:W123 pmid:999"
    ids = _parse_id_blob(blob)
    assert ids["omid"] == "br/06190834283"
    assert ids["doi"] == "10.1186/First"  # first DOI kept
    assert ids["openalex"] == "W123"
    assert ids["pmid"] == "999"


def test_opencitations_work_from_blob():
    work = _work_from_blob("omid:br/x doi:10.1186/ABC openalex:W2120377900 pmid:23958373")
    assert work is not None
    assert work.doi == "10.1186/abc"  # normalized lowercase
    assert work.openalex_id == "W2120377900"
    assert work.pmid == "23958373"
    assert work.source_provider == "opencitations"


def test_opencitations_work_from_blob_unresolvable():
    # Only an OMID — nothing we can resolve against, so no Work.
    assert _work_from_blob("omid:br/06190834283") is None
    assert _work_from_blob("") is None


# --------------------------------------------------------------------------- #
# bioRxiv / medRxiv mapping
# --------------------------------------------------------------------------- #
def test_biorxiv_parse_authors():
    authors = _parse_authors("Liu, R.; Americo, J. L.; Moss, B.")
    assert [a.name for a in authors] == ["Liu, R.", "Americo, J. L.", "Moss, B."]
    assert authors[0].family == "Liu"


def test_biorxiv_map_detail():
    detail = {
        "title": "MVA Vector Vaccines Inhibit SARS CoV-2 Replication",
        "authors": "Liu, R.; Americo, J. L.; Moss, B.",
        "doi": "10.1101/2020.12.30.424878",
        "date": "2021-01-01",
        "version": "1",
        "type": "new results",
        "category": "microbiology",
        "abstract": "Replication-restricted modified vaccinia virus Ankara.",
        "published": "10.1126/science.abc1234",
    }
    work = _map_detail(detail, "biorxiv")
    assert work.doi == "10.1101/2020.12.30.424878"
    assert work.venue == "bioRxiv"
    assert work.venue_type == "repository"
    assert work.type == "preprint"
    assert work.is_oa is True
    assert work.oa_status == "green"
    assert work.year == 2021
    assert work.topics == ["microbiology"]
    assert work.pdf_url == (
        "https://www.biorxiv.org/content/10.1101/2020.12.30.424878v1.full.pdf"
    )


def test_biorxiv_map_detail_medrxiv_server():
    detail = {"title": "A medRxiv study", "doi": "10.1101/2021.01.01.21249000",
              "date": "2021-02-02", "version": "2", "abstract": "x"}
    work = _map_detail(detail, "medrxiv")
    assert work.venue == "medRxiv"
    assert "medrxiv.org" in work.pdf_url
    assert "v2.full.pdf" in work.pdf_url


async def test_biorxiv_get_work_rejects_non_preprint_doi():
    # No network: non-10.1101 DOIs are rejected before any request.
    assert await biorxiv.get_work("10.1177/0149206311425615") is None
    assert await biorxiv.get_work("not-a-doi") is None


# --------------------------------------------------------------------------- #
# CORE mapping + gating
# --------------------------------------------------------------------------- #
def test_core_map_work():
    raw = {
        "title": "Sharing Research Data",
        "abstract": "Abstract body.",
        "authors": [{"name": "Jane Smith"}, {"name": "John Doe"}],
        "yearPublished": 2020,
        "publishedDate": "2020-05-01T00:00:00",
        "doi": "10.1371/journal.pone.0000308",
        "downloadUrl": "https://core.ac.uk/download/123.pdf",
        "publisher": "Public Library of Science",
        "journals": [{"title": "PLoS ONE"}],
        "documentType": "research",
        "language": {"code": "en"},
    }
    work = core_map_work(raw)
    assert work is not None
    assert work.title == "Sharing Research Data"
    assert work.year == 2020
    assert work.doi == "10.1371/journal.pone.0000308"
    assert work.pdf_url == "https://core.ac.uk/download/123.pdf"
    assert work.is_oa is True
    assert work.venue == "PLoS ONE"
    assert work.language == "en"
    assert work.author_names == ["Jane Smith", "John Doe"]


def test_core_map_work_requires_title():
    assert core_map_work({"title": None}) is None


def test_core_gated_without_key():
    # With no CORE_API_KEY in the test environment, the provider is inactive.
    assert core.available() is False


async def test_core_search_returns_empty_when_unavailable():
    # Unavailable provider short-circuits before any network call.
    assert await core.search("technostress") == []
    assert await core.get_work("10.1/abc") is None
