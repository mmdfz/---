from athenaeum_mcp.dedup import merge_works
from athenaeum_mcp.models import Author, Work


def test_merge_by_doi_case_insensitive():
    a = Work(doi="10.1234/abc", title="A study", source_provider="crossref", cited_by_count=5)
    b = Work(doi="10.1234/ABC", title="A study", source_provider="openalex", cited_by_count=12, is_oa=True)
    merged = merge_works([a, b])
    assert len(merged) == 1
    assert set(merged[0].providers) == {"crossref", "openalex"}
    assert merged[0].cited_by_count == 12  # max
    assert merged[0].is_oa is True


def test_merge_fuzzy_title_without_doi():
    a = Work(title="Role shift and the AI overseer", year=2024, source_provider="openalex")
    b = Work(title="Role Shift and the AI Overseer.", year=2024, source_provider="arxiv", arxiv_id="2401.00001")
    merged = merge_works([a, b])
    assert len(merged) == 1
    assert merged[0].arxiv_id == "2401.00001"


def test_no_merge_for_distinct_titles():
    a = Work(title="A paper about cats", source_provider="openalex")
    b = Work(title="A paper about dogs", source_provider="arxiv")
    assert len(merge_works([a, b])) == 2


def test_year_mismatch_blocks_fuzzy_merge():
    a = Work(title="Identical sounding title", year=2001, source_provider="openalex")
    b = Work(title="Identical sounding title", year=2021, source_provider="arxiv")
    assert len(merge_works([a, b])) == 2


def test_abstract_prefers_longer_and_authors_richer():
    short = Work(doi="10.1234/a", title="T", abstract="short", source_provider="crossref",
                 authors=[Author(name="J. Doe", family="Doe", given="J.")])
    rich = Work(doi="10.1234/a", title="T", abstract="a substantially longer abstract text",
                source_provider="openalex",
                authors=[Author(name="Jane Doe"), Author(name="Sam Roe")])
    merged = merge_works([short, rich])
    assert len(merged) == 1
    assert merged[0].abstract == "a substantially longer abstract text"
    # richer author list (2 entries) should win over 1 entry
    assert len(merged[0].authors) == 2


def test_retraction_flag_propagates():
    a = Work(doi="10.1234/r", title="T", source_provider="crossref")
    b = Work(doi="10.1234/r", title="T", source_provider="openalex", is_retracted=True)
    merged = merge_works([a, b])
    assert merged[0].is_retracted is True


def test_topics_union():
    a = Work(doi="10.1234/t", title="T", source_provider="openalex", topics=["A", "B"])
    b = Work(doi="10.1234/t", title="T", source_provider="crossref", topics=["B", "C"])
    merged = merge_works([a, b])
    assert merged[0].topics == ["A", "B", "C"]
