import pytest

from athenaeum_mcp.formatting import STYLES, format_bibliography, format_citation
from athenaeum_mcp.models import Author, Work

WORK = Work(
    doi="10.1177/0149206311425615",
    title="Thriving at work: Toward its measurement, construct validation, and theoretical refinement",
    year=2012,
    authors=[
        Author(name="Christine L. Porath"),
        Author(name="Gretchen Spreitzer"),
        Author(name="Cristina Gibson"),
        Author(name="Flannery G. Garnett"),
    ],
    venue="Journal of Organizational Behavior",
    volume="33",
    issue="2",
    pages="250-275",
    type="article",
)

PREPRINT = Work(
    arxiv_id="2311.07072",
    title="Technostress and Job Performance",
    year=2023,
    authors=[Author(name="Jane Q. Researcher")],
    venue="arXiv",
    type="preprint",
)


def test_all_styles_return_text():
    for style in STYLES:
        out = format_citation(WORK, style)
        assert isinstance(out, str) and len(out) > 10


def test_apa_components():
    out = format_citation(WORK, "apa")
    assert "Porath, C. L." in out
    assert "(2012)" in out
    assert "Journal of Organizational Behavior" in out
    assert "https://doi.org/10.1177/0149206311425615" in out


def test_apa_uses_ampersand_before_last_author():
    out = format_citation(WORK, "apa")
    assert "& Garnett, F. G." in out


def test_bibtex_structure():
    out = format_citation(WORK, "bibtex")
    assert out.startswith("@article{")
    assert "author = {Porath, Christine L." in out
    assert "doi = {10.1177/0149206311425615}" in out
    assert "pages = {250--275}" in out  # en-dash range


def test_ieee_initials_precede_family():
    out = format_citation(WORK, "ieee")
    assert "C. L. Porath" in out


def test_vancouver_compact_initials_and_etal():
    out = format_citation(WORK, "vancouver")
    assert "Porath CL" in out  # compact initials


def test_mla_etal_for_three_plus_authors():
    out = format_citation(WORK, "mla")
    assert "et al" in out


def test_preprint_without_doi_formats():
    out = format_citation(PREPRINT, "apa")
    assert "arxiv.org/abs/2311.07072" in out
    bib = format_citation(PREPRINT, "bibtex")
    assert "arXiv:2311.07072" in bib


def test_unknown_style_raises():
    with pytest.raises(ValueError):
        format_citation(WORK, "nonsense")


def test_numbered_bibliography_for_ieee():
    out = format_bibliography([WORK, PREPRINT], "ieee")
    assert out.startswith("[1]")
    assert "\n[2]" in out


def test_bibtex_bibliography_concatenates_entries():
    out = format_bibliography([WORK, PREPRINT], "bibtex")
    assert out.count("@") == 2
