from athenaeum_mcp.utils import (
    detect_identifier,
    normalize_arxiv_id,
    normalize_doi,
    reconstruct_abstract,
    title_key,
)


def test_normalize_doi():
    assert normalize_doi("https://doi.org/10.1234/AbC") == "10.1234/abc"
    assert normalize_doi("10.1177/0149206311425615") == "10.1177/0149206311425615"
    assert normalize_doi("doi:10.1038/NATURE12373") == "10.1038/nature12373"
    assert normalize_doi("there is no doi here") is None
    assert normalize_doi(None) is None


def test_detect_identifier_kinds():
    assert detect_identifier("10.1234/abc")[0] == "doi"
    assert detect_identifier("https://doi.org/10.1234/abc")[0] == "doi"
    assert detect_identifier("arXiv:2311.07072v1")[0] == "arxiv"
    assert detect_identifier("2311.07072")[0] == "arxiv"
    assert detect_identifier("W2150527468")[0] == "openalex"
    assert detect_identifier("https://openalex.org/W2150527468")[0] == "openalex"
    assert detect_identifier("PMC13233700")[0] == "pmcid"
    assert detect_identifier("pmid:8509330")[0] == "pmid"
    assert detect_identifier("8509330")[0] == "pmid"
    assert detect_identifier("just some words")[0] == "unknown"


def test_detect_identifier_values_normalized():
    assert detect_identifier("https://doi.org/10.1234/AbC")[1] == "10.1234/abc"
    assert detect_identifier("W2150527468")[1] == "W2150527468"


def test_normalize_arxiv_id():
    assert normalize_arxiv_id("arXiv:2311.07072v1") == "2311.07072v1"
    assert normalize_arxiv_id("https://arxiv.org/abs/2310.07806") == "2310.07806"
    assert normalize_arxiv_id("not an id") is None


def test_reconstruct_abstract():
    inv = {"Thriving": [0], "at": [1], "work": [2]}
    assert reconstruct_abstract(inv) == "Thriving at work"
    assert reconstruct_abstract(None) is None
    assert reconstruct_abstract({}) is None


def test_reconstruct_abstract_orders_by_position():
    inv = {"world": [1], "Hello": [0], "again": [2, 4], "hello": [3]}
    assert reconstruct_abstract(inv) == "Hello world again hello again"


def test_title_key_strips_punct_and_case():
    assert title_key("Thriving at Work!") == "thriving at work"
    assert title_key("  AI:  Brain-Fry  ") == "ai brain fry"
    assert title_key(None) == ""
