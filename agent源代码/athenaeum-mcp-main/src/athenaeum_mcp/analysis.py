"""Lightweight bibliometric analysis: methodological rigor cues and a coarse
directional-sentiment heuristic for a corpus of works.

Everything here is deliberately transparent and rule-based rather than a black
box. Two honest caveats apply and are surfaced to the user:

* **Rigor cues** are detected from the *abstract text only*. Their presence is a
  positive signal (the authors mention a sample size, a pre-registration, a
  recognised design); their absence is NOT evidence of poor rigor — many sound
  papers simply don't put these words in the abstract.
* **Directional sentiment** ("supporting" vs "challenging" a hypothesis) is a
  lexical heuristic over titles/abstracts. It cannot understand nuance, irony or
  framing and will misclassify some works. It is meant only to flag whether a
  field looks broadly settled or contested, as a starting hypothesis.
"""
from __future__ import annotations

import re
from statistics import median

from .models import Work

# --------------------------------------------------------------------------- #
# Methodological rigor cues (detected in abstract / title text)
# --------------------------------------------------------------------------- #
_RIGOR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("meta-analysis", re.compile(r"\bmeta[- ]?anal", re.I)),
    ("systematic review", re.compile(r"\bsystematic review\b|\bPRISMA\b", re.I)),
    ("randomized/controlled trial", re.compile(r"\brandomi[sz]ed\b|\bRCT\b|\bcontrol(?:led)? (?:group|trial|condition)\b", re.I)),
    ("longitudinal/panel design", re.compile(r"\blongitudinal\b|\bpanel data\b|\bover time\b|\b(?:two|three|multi)[- ]wave\b", re.I)),
    ("pre-registration", re.compile(r"\bpre[- ]?regist", re.I)),
    ("reported sample size", re.compile(r"\bn\s*=\s*\d{2,}|\b\d{3,}\s+(?:participants|respondents|patients|subjects|students|employees|samples)\b", re.I)),
    ("validated instrument/scale", re.compile(r"\bvalidat(?:ed|ion)\b|\bcronbach|\breliability\b|\bpsychometr", re.I)),
    ("stated limitations", re.compile(r"\blimitation", re.I)),
    ("causal/quasi-experimental design", re.compile(r"\bquasi[- ]experiment|\bdifference[- ]in[- ]differences\b|\binstrumental variable|\bregression discontinuity\b|\bcausal\b", re.I)),
    ("effect size / CI reported", re.compile(r"\beffect size|\bcohen'?s d\b|\bodds ratio\b|\b95%\s*(?:CI|confidence)\b", re.I)),
]

# Designs that are weaker evidence (disclosed as caveats, not penalties).
_WEAK_DESIGN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cross-sectional / self-report design", re.compile(r"\bcross[- ]sectional\b|\bself[- ]report", re.I)),
    ("single case study", re.compile(r"\bcase study\b|\bcase report\b", re.I)),
    ("small/convenience sample", re.compile(r"\bconvenience sampl|\bpilot study\b", re.I)),
]


def detect_rigor(work: Work) -> tuple[list[str], list[str]]:
    """Return ``(strength_cues, caveat_cues)`` mined from title + abstract."""
    text = " ".join(filter(None, [work.title, work.abstract]))
    if not text.strip():
        return [], []
    strengths = [label for label, rx in _RIGOR_PATTERNS if rx.search(text)]
    caveats = [label for label, rx in _WEAK_DESIGN_PATTERNS if rx.search(text)]
    return strengths, caveats


# --------------------------------------------------------------------------- #
# Work-type classification (peer-reviewed vs preprint vs review …)
# --------------------------------------------------------------------------- #
_PREPRINT_VENUES = ("arxiv", "biorxiv", "medrxiv", "ssrn", "preprints", "research square", "osf")


def classify_work(work: Work) -> tuple[str, bool | None]:
    """Return ``(work_type_label, peer_reviewed)``.

    ``peer_reviewed`` is True for journal/conference articles, False for
    preprints, and None when it can't be determined.
    """
    t = (work.type or "").lower()
    venue = (work.venue or "").lower()
    is_preprint = t == "preprint" or any(p in venue for p in _PREPRINT_VENUES) or bool(work.arxiv_id and not work.doi)

    if is_preprint:
        return "preprint (not yet peer-reviewed)", False
    if "review" in t or t == "review":
        return "review article", True
    if t in {"book", "book-chapter"}:
        return t.replace("-", " "), None
    if t in {"article", "journal-article", "conference-paper", "proceedings-article"}:
        return "peer-reviewed article", True
    if t in {"dataset", "report", "thesis"}:
        return t, None
    return (work.type or "unknown"), None


# --------------------------------------------------------------------------- #
# Directional sentiment heuristic
# --------------------------------------------------------------------------- #
_SUPPORT_RE = re.compile(
    r"\b(support|confirm|positive(?:ly)?|significant(?:ly)? (?:increase|improv|enhanc|benefit)|"
    r"improv|enhanc|increase[sd]?|benefit|effective|efficac|associated with (?:higher|greater|better)|"
    r"promot|facilitat|strengthen)\w*", re.I,
)
_CHALLENGE_RE = re.compile(
    r"\b(no (?:significant )?(?:effect|association|difference|impact)|"
    r"fail(?:ed|s)? to|not (?:significant|associated|supported|effective)|"
    r"negative(?:ly)?|decreas|reduc|impair|harm|detrimental|adverse|undermin|"
    r"contrary to|challenge[sd]?|refut|inconsistent|mixed (?:results|findings|evidence)|"
    r"weak(?:en)?|null (?:result|finding))\w*", re.I,
)


def sentiment_lean(work: Work) -> str:
    """Classify a work as 'supporting' | 'challenging' | 'mixed' (coarse heuristic)."""
    text = " ".join(filter(None, [work.title, work.abstract]))
    if not text.strip():
        return "mixed"
    s = len(_SUPPORT_RE.findall(text))
    c = len(_CHALLENGE_RE.findall(text))
    if s == 0 and c == 0:
        return "mixed"
    if s >= c * 2 and s > 0:
        return "supporting"
    if c >= s * 2 and c > 0:
        return "challenging"
    return "mixed"


# --------------------------------------------------------------------------- #
# Corpus-level consensus / landscape
# --------------------------------------------------------------------------- #
def analyse_corpus(works: list[Work], current_year: int) -> dict:
    """Summarise a corpus: evidence strength, study-type mix, sentiment lean."""
    n = len(works)
    years = [w.year for w in works if w.year]
    citations = [w.cited_by_count or 0 for w in works]
    median_year = int(median(years)) if years else None
    recent = sum(1 for y in years if y >= current_year - 3)
    oa = sum(1 for w in works if w.is_oa)
    retracted = sum(1 for w in works if w.is_retracted)

    # Study-type mix.
    types = {
        "Meta-analyses / systematic reviews": 0,
        "Review articles": 0,
        "Peer-reviewed empirical articles": 0,
        "Preprints (not peer-reviewed)": 0,
        "Books / chapters": 0,
        "Other": 0,
    }
    rigor_hits = 0
    for w in works:
        strengths, _ = detect_rigor(w)
        if any(s in strengths for s in ("meta-analysis", "systematic review")):
            types["Meta-analyses / systematic reviews"] += 1
        elif (w.type or "").lower() == "review":
            types["Review articles"] += 1
        else:
            label, _ = classify_work(w)
            if label.startswith("preprint"):
                types["Preprints (not peer-reviewed)"] += 1
            elif label in {"book", "book chapter"}:
                types["Books / chapters"] += 1
            elif label == "peer-reviewed article":
                types["Peer-reviewed empirical articles"] += 1
            else:
                types["Other"] += 1
        if strengths:
            rigor_hits += 1

    # Sentiment lean.
    leans = {"supporting": 0, "challenging": 0, "mixed": 0}
    for w in works:
        leans[sentiment_lean(w)] += 1
    overall = _overall_lean(leans)

    # Evidence strength: a transparent composite.
    total_citations = sum(citations)
    has_synthesis = types["Meta-analyses / systematic reviews"] > 0
    strength = _evidence_strength(n, total_citations, has_synthesis, rigor_hits)
    maturity = _maturity(n, median_year, current_year)

    return {
        "analysed": n,
        "year_range": f"{min(years)}–{max(years)}" if years else "unknown",
        "median_year": median_year,
        "recent_share_pct": round(100 * recent / n) if n else 0,
        "oa_share_pct": round(100 * oa / n) if n else 0,
        "retracted_count": retracted,
        "total_citations": total_citations,
        "study_types": types,
        "rigor_coverage_pct": round(100 * rigor_hits / n) if n else 0,
        "sentiment": {**leans, "overall": overall},
        "evidence_strength": strength,
        "maturity": maturity,
    }


def _overall_lean(leans: dict[str, int]) -> str:
    total = sum(leans.values()) or 1
    sup = leans["supporting"] / total
    chal = leans["challenging"] / total
    if sup >= 0.55 and sup > chal:
        return "predominantly supporting (findings tend to confirm the effect)"
    if chal >= 0.55 and chal > sup:
        return "predominantly challenging (findings tend to question the effect)"
    if abs(sup - chal) < 0.15:
        return "contested / mixed (the literature does not clearly agree)"
    return "leaning supporting" if sup > chal else "leaning challenging"


def _evidence_strength(n: int, total_citations: int, has_synthesis: bool, rigor_hits: int) -> str:
    score = 0
    score += 2 if n >= 40 else 1 if n >= 15 else 0
    score += 2 if total_citations >= 2000 else 1 if total_citations >= 300 else 0
    score += 2 if has_synthesis else 0
    score += 1 if rigor_hits >= max(3, n // 5) else 0
    if score >= 6:
        return "strong — a sizeable, well-cited body including evidence synthesis"
    if score >= 4:
        return "moderate — a reasonable evidence base, some high-quality work"
    if score >= 2:
        return "emerging — limited or early-stage evidence"
    return "sparse — very little published evidence; treat conclusions cautiously"


def _maturity(n: int, median_year: int | None, current_year: int) -> str:
    if median_year is None:
        return "unknown"
    age = current_year - median_year
    if n >= 40 and age >= 5:
        return "established field with an accumulated literature"
    if age <= 3:
        return "fast-moving / recent area"
    return "developing area"
