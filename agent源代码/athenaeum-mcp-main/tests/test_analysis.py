from athenaeum_mcp.analysis import (
    analyse_corpus,
    classify_work,
    detect_rigor,
    sentiment_lean,
)
from athenaeum_mcp.models import Work


def _w(**kw):
    return Work(**kw)


def test_detect_rigor_meta_analysis():
    w = _w(title="A meta-analysis of technostress", abstract="We pooled effect sizes (Cohen's d) across 40 studies.")
    strengths, caveats = detect_rigor(w)
    assert "meta-analysis" in strengths
    assert "effect size / CI reported" in strengths


def test_detect_rigor_sample_and_validation():
    w = _w(title="Survey study", abstract="Using a sample of 673 participants we validated the instrument (Cronbach's alpha = .9).")
    strengths, _ = detect_rigor(w)
    assert "reported sample size" in strengths
    assert "validated instrument/scale" in strengths


def test_detect_rigor_caveats_cross_sectional():
    w = _w(title="X", abstract="This cross-sectional self-report survey examined ...")
    _, caveats = detect_rigor(w)
    assert "cross-sectional / self-report design" in caveats


def test_detect_rigor_empty_abstract():
    w = _w(title="No abstract here")
    strengths, caveats = detect_rigor(w)
    assert strengths == [] and caveats == []


def test_classify_preprint_by_type():
    w = _w(title="x", type="preprint")
    label, peer = classify_work(w)
    assert peer is False and "preprint" in label


def test_classify_preprint_by_arxiv():
    w = _w(title="x", arxiv_id="2401.00001", venue="arXiv")
    label, peer = classify_work(w)
    assert peer is False


def test_classify_journal_article_peer_reviewed():
    w = _w(title="x", type="article", venue="Journal of Applied Psychology", doi="10.1/x")
    label, peer = classify_work(w)
    assert peer is True and "peer-reviewed" in label


def test_sentiment_supporting():
    w = _w(title="Training significantly improves and enhances performance and benefits workers")
    assert sentiment_lean(w) == "supporting"


def test_sentiment_challenging():
    w = _w(title="Intervention had no significant effect and failed to reduce stress")
    assert sentiment_lean(w) == "challenging"


def test_sentiment_mixed_when_balanced_or_empty():
    assert sentiment_lean(_w(title="A study of things")) == "mixed"


def test_analyse_corpus_shape():
    works = [
        _w(title="Meta-analysis of X", abstract="pooled effect size", type="article",
           venue="J", doi="10.1/a", year=2020, cited_by_count=500),
        _w(title="X improves Y significantly", type="article", venue="J", doi="10.1/b",
           year=2023, cited_by_count=10, is_oa=True),
        _w(title="No effect of X on Y", type="preprint", arxiv_id="2401.1", year=2024),
    ]
    summary = analyse_corpus(works, current_year=2026)
    assert summary["analysed"] == 3
    assert summary["study_types"]["Meta-analyses / systematic reviews"] == 1
    assert summary["study_types"]["Preprints (not peer-reviewed)"] == 1
    assert "overall" in summary["sentiment"]
    assert 0 <= summary["oa_share_pct"] <= 100
    assert isinstance(summary["evidence_strength"], str)
