"""Deduplicate and merge works coming from multiple providers.

The meta-search fans a query out to several databases; the same paper therefore
appears multiple times with partial, complementary metadata. This module:

1. clusters records that refer to the same work (by normalized DOI, then by
   fuzzy title + year for records lacking a shared DOI), and
2. merges each cluster into one enriched :class:`Work`, taking the best value
   per field and unioning provenance.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from .models import Work
from .utils import title_key

_TITLE_THRESHOLD = 92.0


class _Cluster:
    __slots__ = ("key", "year", "works")

    def __init__(self, key: str, year: int | None) -> None:
        self.key = key
        self.year = year
        self.works: list[Work] = []


def _years_compatible(a: int | None, b: int | None) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= 1


def merge_works(works: list[Work]) -> list[Work]:
    """Cluster and merge a flat list of works from several providers."""
    # Process DOI-bearing records first so DOI-less ones can attach to them.
    ordered = sorted(works, key=lambda w: (w.doi is None,))

    clusters: list[_Cluster] = []
    doi_index: dict[str, _Cluster] = {}

    for work in ordered:
        cluster = None
        if work.doi and work.doi in doi_index:
            cluster = doi_index[work.doi]
        elif not work.doi:
            cluster = _fuzzy_match(work, clusters)

        if cluster is None:
            cluster = _Cluster(title_key(work.title), work.year)
            clusters.append(cluster)
            if work.doi:
                doi_index[work.doi] = cluster
        elif work.doi and work.doi not in doi_index:
            doi_index[work.doi] = cluster

        cluster.works.append(work)

    return [_merge_cluster(c.works) for c in clusters]


def _fuzzy_match(work: Work, clusters: list[_Cluster]) -> _Cluster | None:
    wk = title_key(work.title)
    if not wk:
        return None
    best: _Cluster | None = None
    best_score = 0.0
    for cluster in clusters:
        if not cluster.key or not _years_compatible(work.year, cluster.year):
            continue
        score = fuzz.token_sort_ratio(wk, cluster.key)
        if score > best_score:
            best_score, best = score, cluster
    return best if best_score >= _TITLE_THRESHOLD else None


def _richness(work: Work) -> int:
    score = 0
    score += 3 if work.doi else 0
    score += 2 if work.abstract else 0
    score += len(work.authors)
    score += 1 if work.venue else 0
    score += 1 if work.cited_by_count is not None else 0
    return score


# Providers we trust most for descriptive metadata, in order.
_METADATA_PRIORITY = {"openalex": 3, "crossref": 3, "europepmc": 2, "semantic_scholar": 1, "arxiv": 1}


def _merge_cluster(group: list[Work]) -> Work:
    if len(group) == 1:
        return group[0]

    base = max(group, key=_richness)
    merged = base.model_copy(deep=True)

    for other in group:
        if other is base:
            continue
        _merge_into(merged, other)

    # Union providers in a stable order.
    provs: list[str] = []
    for w in group:
        for p in w.providers:
            if p not in provs:
                provs.append(p)
    merged.providers = provs
    return merged


def _merge_into(dst: Work, src: Work) -> None:
    # Identifiers: fill any that are missing.
    for field in ("doi", "openalex_id", "arxiv_id", "pmid", "pmcid", "s2_id", "mag_id",
                  "venue", "venue_type", "publisher", "type", "volume", "issue", "pages",
                  "date", "year", "language", "landing_url", "oa_status"):
        if getattr(dst, field) is None and getattr(src, field) is not None:
            setattr(dst, field, getattr(src, field))

    # Abstract: keep the longer one.
    if src.abstract and len(src.abstract) > len(dst.abstract or ""):
        dst.abstract = src.abstract

    # TLDR: prefer any (Semantic Scholar).
    if not dst.tldr and src.tldr:
        dst.tldr = src.tldr

    # Authors: prefer the richer list (more entries, or with given/family parts).
    if _author_score(src.authors) > _author_score(dst.authors):
        dst.authors = src.authors

    # Citations / references: take the maximum observed.
    if src.cited_by_count is not None:
        dst.cited_by_count = max(dst.cited_by_count or 0, src.cited_by_count)
    if src.reference_count is not None:
        dst.reference_count = max(dst.reference_count or 0, src.reference_count)

    # Open access: any True wins; keep a PDF link if we don't have one.
    if src.is_oa:
        dst.is_oa = True
    if not dst.pdf_url and src.pdf_url:
        dst.pdf_url = src.pdf_url

    # ISSNs / topics / keywords: union.
    dst.venue_issn = _union(dst.venue_issn, src.venue_issn)
    dst.topics = _union(dst.topics, src.topics)
    dst.keywords = _union(dst.keywords, src.keywords)

    # Retraction: a positive flag anywhere wins.
    if src.is_retracted:
        dst.is_retracted = True

    # Relevance: keep the strongest signal.
    if src.relevance_score is not None:
        dst.relevance_score = max(dst.relevance_score or 0.0, src.relevance_score)


def _author_score(authors: list) -> int:
    if not authors:
        return 0
    has_parts = sum(1 for a in authors if a.family)
    return len(authors) * 2 + has_parts


def _union(a: list[str], b: list[str]) -> list[str]:
    out = list(a)
    for item in b:
        if item not in out:
            out.append(item)
    return out
