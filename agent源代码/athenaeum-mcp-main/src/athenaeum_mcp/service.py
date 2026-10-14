"""Service layer: the business logic behind the MCP tools.

Kept separate from ``server.py`` so it can be unit/smoke-tested without an MCP
client. Functions return plain Python objects (``Work``/``Venue``/dicts); the
server layer adds input validation and Markdown/JSON rendering.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from .analysis import analyse_corpus, classify_work, detect_rigor
from .dedup import merge_works
from .models import AuthorProfile, Venue, Work
from .providers import (
    SEARCH_PROVIDERS,
    arxiv,
    biorxiv,
    crossref,
    default_search_providers,
    doaj,
    europepmc,
    opencitations,
    openalex,
    pubmed,
    semantic_scholar,
    unpaywall,
    zotero,
)
from .utils import detect_identifier, title_key

_RRF_K = 60
_GRAPH_MAX_NODES = 60


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def _rrf_key(work: Work) -> str:
    return work.doi or title_key(work.title)


def _rrf_scores(batches: list[list[Work]]) -> dict[str, float]:
    """Reciprocal Rank Fusion across provider result lists (SearXNG-style)."""
    scores: dict[str, float] = {}
    for batch in batches:
        for rank, work in enumerate(batch):
            key = _rrf_key(work)
            if not key:
                continue
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
    return scores


async def meta_search(
    query: str,
    *,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
    open_access_only: bool = False,
    providers: list[str] | None = None,
    sort: str = "relevance",
) -> list[Work]:
    """Fan a query out to several providers, deduplicate, merge and rank."""
    names = providers or default_search_providers()
    chosen = [(n, SEARCH_PROVIDERS[n]) for n in names if n in SEARCH_PROVIDERS]

    async def _safe(name: str, prov: Any) -> list[Work]:
        try:
            return await prov.search(
                query,
                limit=limit,
                year_from=year_from,
                year_to=year_to,
                open_access_only=open_access_only,
            )
        except Exception:  # noqa: BLE001 - a provider failing must not sink the search
            return []

    batches = await asyncio.gather(*(_safe(n, p) for n, p in chosen))
    rrf = _rrf_scores(batches)

    flat = [w for batch in batches for w in batch]
    merged = merge_works(flat)

    if open_access_only:
        merged = [w for w in merged if w.is_oa is not False or w.pdf_url]

    if sort == "citations":
        merged.sort(key=lambda w: (w.cited_by_count or 0), reverse=True)
    else:  # relevance via RRF, tie-broken by provider count then citations
        merged.sort(
            key=lambda w: (rrf.get(_rrf_key(w), 0.0), len(w.providers), w.cited_by_count or 0),
            reverse=True,
        )

    return merged[:limit]


async def search_provider(
    provider: str,
    query: str,
    *,
    limit: int = 20,
    year_from: int | None = None,
    year_to: int | None = None,
    open_access_only: bool = False,
) -> list[Work]:
    prov = SEARCH_PROVIDERS.get(provider)
    if prov is None:
        raise ValueError(f"Unknown provider '{provider}'. Choose from: {', '.join(SEARCH_PROVIDERS)}")
    return await prov.search(
        query, limit=limit, year_from=year_from, year_to=year_to, open_access_only=open_access_only
    )


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
async def get_work(identifier: str, *, enrich: bool = True) -> Work | None:
    """Resolve a work by any identifier, optionally merging across providers."""
    kind, ident_value = detect_identifier(identifier)

    # Primary resolver depends on the id kind.
    primary = await openalex.get_work(identifier)

    if not enrich:
        if primary:
            return primary
        # fall through to alternates below

    candidates: list[Work] = [primary] if primary else []

    # Gather complementary records (best-effort, in parallel).
    tasks = []
    if kind == "doi":
        tasks = [crossref.get_work(identifier), europepmc.get_work(identifier),
                 pubmed.get_work(identifier), semantic_scholar.get_work(identifier)]
        # bioRxiv/medRxiv preprints share the 10.1101 DOI prefix.
        if ident_value.startswith("10.1101/"):
            tasks.append(biorxiv.get_work(identifier))
    elif kind == "arxiv":
        tasks = [arxiv.get_work(identifier), semantic_scholar.get_work(identifier)]
    elif kind in {"pmid", "pmcid"}:
        tasks = [europepmc.get_work(identifier), pubmed.get_work(identifier),
                 semantic_scholar.get_work(identifier)]

    if tasks:
        extra = await asyncio.gather(*tasks, return_exceptions=True)
        for item in extra:
            if isinstance(item, Work):
                candidates.append(item)

    if not candidates:
        # last resort: arXiv direct
        ax = await arxiv.get_work(identifier)
        if ax:
            candidates.append(ax)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    merged = merge_works(candidates)
    return merged[0] if merged else candidates[0]


# --------------------------------------------------------------------------- #
# Citation graph
# --------------------------------------------------------------------------- #
async def get_references(identifier: str, *, limit: int = 40) -> list[Work]:
    refs = await openalex.get_references(identifier, limit=limit)
    if refs:
        return refs
    refs = await crossref.get_references(identifier, limit=limit)
    if refs:
        return refs
    # Last resort: OpenCitations' independent open index.
    return await _opencitations_resolved("references", identifier, limit=limit)


async def get_citations(identifier: str, *, limit: int = 25) -> list[Work]:
    cites = await openalex.get_citations(identifier, limit=limit)
    if cites:
        return cites
    # OpenAlex had nothing — fall back to OpenCitations (it sometimes has
    # citations OpenAlex has not yet ingested).
    return await _opencitations_resolved("citations", identifier, limit=limit)


async def _opencitations_resolved(
    direction: str, identifier: str, *, limit: int
) -> list[Work]:
    """Fetch OpenCitations stubs and enrich them via OpenAlex when possible.

    OpenCitations records embed the OpenAlex id of each participating work, so
    we can batch-resolve full metadata; if that fails we return the bare stubs
    (which still carry a DOI) rather than nothing.
    """
    if direction == "references":
        stubs = await opencitations.get_references(identifier, limit=limit)
    else:
        stubs = await opencitations.get_citations(identifier, limit=limit)
    if not stubs:
        return []
    oa_ids = [s.openalex_id for s in stubs if s.openalex_id]
    if oa_ids:
        resolved = await openalex.get_works_by_ids(oa_ids, limit=limit)
        if resolved:
            return resolved
    return stubs


async def get_related(identifier: str, *, limit: int = 20) -> list[Work]:
    return await openalex.get_related(identifier, limit=limit)


def _node(work: Work) -> dict[str, Any]:
    return {
        "id": work.best_id,
        "title": work.title,
        "year": work.year,
        "cited_by_count": work.cited_by_count,
        "doi": work.doi,
    }


async def citation_graph(
    identifier: str,
    *,
    depth: int = 1,
    per_node: int = 8,
    direction: str = "citations",
) -> dict[str, Any]:
    """Breadth-first traversal of the citation network around a seed work."""
    depth = max(1, min(depth, 2))
    per_node = max(1, min(per_node, 15))

    seed = await get_work(identifier, enrich=False)
    if seed is None:
        return {"seed": identifier, "found": False, "nodes": [], "edges": []}

    nodes: dict[str, dict[str, Any]] = {seed.best_id: _node(seed)}
    edges: list[dict[str, str]] = []
    frontier = [seed]

    for _ in range(depth):
        next_frontier: list[Work] = []
        for node in frontier:
            node_ref = node.doi or node.openalex_id or node.best_id
            neighbors: list[tuple[Work, str, str]] = []  # (work, from_id, to_id)

            if direction in {"references", "both"}:
                for r in await openalex.get_references(node_ref, limit=per_node):
                    neighbors.append((r, node.best_id, r.best_id))
            if direction in {"citations", "both"}:
                for c in await openalex.get_citations(node_ref, limit=per_node):
                    neighbors.append((c, c.best_id, node.best_id))

            for work, from_id, to_id in neighbors:
                edges.append({"from": from_id, "to": to_id})
                if work.best_id not in nodes and len(nodes) < _GRAPH_MAX_NODES:
                    nodes[work.best_id] = _node(work)
                    next_frontier.append(work)
            if len(nodes) >= _GRAPH_MAX_NODES:
                break
        frontier = next_frontier
        if not frontier or len(nodes) >= _GRAPH_MAX_NODES:
            break

    return {
        "seed": seed.best_id,
        "seed_title": seed.title,
        "found": True,
        "direction": direction,
        "depth": depth,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": list(nodes.values()),
        "edges": edges,
    }


# --------------------------------------------------------------------------- #
# Authors & venues
# --------------------------------------------------------------------------- #
async def get_author(name_or_id: str) -> AuthorProfile | None:
    kind, value = detect_identifier(name_or_id)
    if name_or_id.strip().upper().startswith("A") and name_or_id.strip()[1:].isdigit():
        return await openalex.get_author(name_or_id)
    if "orcid.org" in name_or_id.lower() or _looks_like_orcid(name_or_id):
        return await openalex.get_author(name_or_id)
    return await openalex.search_author(name_or_id)


def _looks_like_orcid(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dxX]", value.strip()))


async def get_venue(issn_or_name: str) -> Venue | None:
    ident = issn_or_name.strip()
    venue = await openalex.get_source(ident)
    if venue is None:
        return None
    # Confirm OA legitimacy directly with DOAJ when we have an ISSN.
    issn = venue.issn_l or (venue.issn[0] if venue.issn else None)
    if issn:
        info = await doaj.lookup_journal(issn)
        if info is not None:
            venue.in_doaj_confirmed = bool(info.get("in_doaj"))
    return venue


# --------------------------------------------------------------------------- #
# Open access / PDF
# --------------------------------------------------------------------------- #
async def _gather_pdf_candidates(identifier: str) -> tuple[Work | None, list[dict[str, Any]]]:
    """Collect every plausible open-access full-text source for a work.

    Pulls direct PDF links and landing pages from OpenAlex's many locations,
    arXiv, Europe PMC and (if configured) Unpaywall, ordered most-accessible
    first. Repository/preprint copies are prioritised over publisher copies,
    which are more likely to be behind bot blocks.
    """
    work = await get_work(identifier, enrich=True)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(url: str | None, source: str, kind: str) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        candidates.append({"source": source, "url": url, "kind": kind})

    # arXiv first — always openly accessible.
    if work and work.arxiv_id:
        _add(f"https://arxiv.org/pdf/{work.arxiv_id}", "arXiv", "pdf")

    # bioRxiv / medRxiv preprints expose a direct full-text PDF.
    if work and work.doi and work.doi.startswith("10.1101/"):
        bio = await biorxiv.get_work(work.doi)
        if bio and bio.pdf_url:
            _add(bio.pdf_url, bio.venue or "bioRxiv", "pdf")

    # Europe PMC full-text PDF (reliable for biomedical OA).
    if work and (work.pmcid or work.pmid):
        epmc = await europepmc.get_work(work.pmcid or f"pmid:{work.pmid}")
        if epmc and epmc.pdf_url:
            _add(epmc.pdf_url, "Europe PMC", "pdf")
        if work.pmcid:
            _add(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{work.pmcid}/", "PMC", "landing")

    # Every OpenAlex open-access location (repositories before publisher).
    oa_candidates = await openalex.get_oa_candidates(identifier)
    # Put repository PDFs ahead of the publisher's by simple heuristic ordering:
    repo_pdfs = [c for c in oa_candidates if c["kind"] == "pdf" and not _is_publisher_host(c["url"])]
    pub_pdfs = [c for c in oa_candidates if c["kind"] == "pdf" and _is_publisher_host(c["url"])]
    landings = [c for c in oa_candidates if c["kind"] == "landing"]
    for c in repo_pdfs + pub_pdfs + landings:
        _add(c["url"], c["source"], c["kind"])

    # Unpaywall (best-in-class OA locator) when a real email is configured.
    doi = work.doi if work else None
    if not doi and detect_identifier(identifier)[0] == "doi":
        doi = detect_identifier(identifier)[1]
    if doi and unpaywall.available():
        up = await unpaywall.lookup(doi)
        if up and up.get("pdf_url"):
            _add(up["pdf_url"], "Unpaywall", "pdf")

    # DOI landing page as a last resort for citation_pdf_url resolution.
    if doi:
        _add(f"https://doi.org/{doi}", "DOI landing", "landing")

    return work, candidates


_PUBLISHER_HOSTS = (
    "mdpi.com", "sciencedirect.com", "springer.com", "link.springer.com",
    "onlinelibrary.wiley.com", "tandfonline.com", "sagepub.com", "ieee.org",
    "acm.org", "nature.com", "science.org", "cell.com", "oup.com",
    "cambridge.org", "emerald.com",
)


def _is_publisher_host(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return any(host.endswith(h) or host == h for h in _PUBLISHER_HOSTS)


async def find_pdf(identifier: str) -> dict[str, Any]:
    """Locate free full-text PDF candidates for a work (no download)."""
    work, candidates = await _gather_pdf_candidates(identifier)
    pdf_sources = [c for c in candidates if c["kind"] == "pdf"]
    return {
        "identifier": identifier,
        "title": work.title if work else None,
        "found": bool(candidates),
        "best_pdf_url": (pdf_sources[0]["url"] if pdf_sources else None),
        "is_oa": work.is_oa if work else None,
        "candidate_count": len(candidates),
        "sources": candidates,
    }


# --------------------------------------------------------------------------- #
# Source validation
# --------------------------------------------------------------------------- #
async def validate_source(identifier: str) -> dict[str, Any]:
    """Assemble credibility signals for a DOI/work and a transparent score."""
    work = await get_work(identifier, enrich=True)
    if work is None:
        return {
            "identifier": identifier,
            "resolves": False,
            "credibility_score": 0,
            "credibility_label": "unverifiable",
            "reasons": ["Could not resolve this identifier in any database."],
        }

    signals: list[str] = []
    positives: list[str] = []
    score = 50  # neutral baseline

    # Cross-provider agreement.
    n_providers = len(work.providers)
    if n_providers >= 2:
        score += 10
        positives.append(f"Indexed in {n_providers} independent databases ({', '.join(work.providers)}).")
    else:
        signals.append("Found in only one database.")

    # Retraction.
    if work.is_retracted:
        score -= 60
        signals.append("⚠️ This work is flagged as RETRACTED.")
    else:
        positives.append("No retraction flag found.")

    # Citations.
    if work.cited_by_count is not None:
        if work.cited_by_count >= 50:
            score += 15
            positives.append(f"Well cited ({work.cited_by_count} citations).")
        elif work.cited_by_count >= 5:
            score += 8
            positives.append(f"Cited {work.cited_by_count} times.")
        else:
            signals.append(f"Few citations ({work.cited_by_count}). May be recent or low-impact.")

        # Citations-per-year contextualises raw counts for older vs newer work.
        current_year = datetime.now(timezone.utc).year
        if work.year and work.year <= current_year:
            age = max(1, current_year - work.year)
            per_year = work.cited_by_count / age
            if age >= 2 and per_year >= 20:
                positives.append(f"High citation rate (~{per_year:.0f}/year over {age} years).")
            elif age >= 5 and per_year < 1:
                signals.append(f"Low citation rate (~{per_year:.1f}/year) despite age — limited uptake.")

    # Peer-review vs preprint status.
    work_type, peer_reviewed = classify_work(work)
    if peer_reviewed is True:
        score += 5
        positives.append(f"Appears peer-reviewed ({work_type}).")
    elif peer_reviewed is False:
        signals.append("This is a preprint — not yet peer-reviewed; interpret with extra caution.")

    # Methodological rigor cues mined from the abstract.
    rigor_strengths, rigor_caveats = detect_rigor(work)
    rigor_lines: list[str] = []
    if rigor_strengths:
        score += min(10, 2 * len(rigor_strengths))
        rigor_lines.append("Abstract mentions: " + ", ".join(rigor_strengths) + ".")
    if rigor_caveats:
        rigor_lines.append("Design caveats noted: " + ", ".join(rigor_caveats) +
                           " (weaker for causal claims — not a flaw, just a limit on inference).")
    if not work.abstract:
        rigor_lines.append("No abstract was available, so methodological cues could not be assessed.")
    elif not rigor_strengths and not rigor_caveats:
        rigor_lines.append("No explicit methodology cues found in the abstract (this is common and "
                           "does not imply weak methods — read the paper to judge).")

    # Venue checks.
    venue_block: dict[str, Any] = {}
    issn = work.venue_issn[0] if work.venue_issn else None
    if issn:
        venue = await openalex.get_source(issn)
        doaj_info, cr_journal = await asyncio.gather(
            doaj.lookup_journal(issn), crossref.get_journal(issn)
        )
        if venue:
            venue_block = venue.compact()
            if venue.h_index and venue.h_index >= 20:
                score += 10
                positives.append(f"Venue has an established h-index ({venue.h_index}).")
            elif venue.h_index is not None and venue.h_index < 5:
                signals.append(f"Venue h-index is very low ({venue.h_index}).")
            if venue.impact_2yr is not None:
                positives.append(f"Venue 2-yr mean citedness: {venue.impact_2yr:.2f}.")
        if doaj_info and doaj_info.get("in_doaj"):
            score += 8
            positives.append("Venue is indexed in DOAJ (vetted open-access journal).")
            venue_block["doaj"] = doaj_info
        if cr_journal and cr_journal.get("indexed_in_crossref"):
            positives.append("Venue is registered with Crossref.")
            venue_block.setdefault("crossref", cr_journal)
        if not venue and not (doaj_info and doaj_info.get("in_doaj")) and not cr_journal:
            score -= 10
            signals.append("Venue could not be found in OpenAlex, DOAJ or Crossref — verify it is legitimate.")
    else:
        signals.append("No ISSN available for venue verification.")

    score = max(0, min(100, score))
    label = (
        "high" if score >= 75 else
        "moderate" if score >= 50 else
        "low" if score >= 25 else "very low"
    )

    return {
        "identifier": identifier,
        "resolves": True,
        "title": work.title,
        "doi": work.doi,
        "year": work.year,
        "venue": work.venue,
        "is_retracted": bool(work.is_retracted),
        "is_oa": work.is_oa,
        "cited_by_count": work.cited_by_count,
        "work_type": work_type,
        "peer_reviewed": peer_reviewed,
        "providers": work.providers,
        "venue_metrics": venue_block or None,
        "rigor_signals": rigor_lines,
        "credibility_score": score,
        "credibility_label": label,
        "positive_signals": positives,
        "caution_signals": signals,
        "disclaimer": "Signals describe indexing, metrics, peer-review status and abstract-level "
                      "methodology cues — not whether the findings are correct. Rigor cues come from "
                      "the abstract only; their absence is not evidence of poor quality. Use scholarly judgement.",
    }


# --------------------------------------------------------------------------- #
# Literature review (workflow)
# --------------------------------------------------------------------------- #
async def literature_review(topic: str, *, limit: int = 30) -> dict[str, Any]:
    works = await meta_search(topic, limit=limit, sort="relevance")
    if not works:
        return {"topic": topic, "found": 0, "seminal": [], "recent": [], "top_venues": [], "top_authors": []}

    current_year = datetime.now(timezone.utc).year

    seminal = sorted(works, key=lambda w: (w.cited_by_count or 0), reverse=True)[:8]
    recent = sorted(
        [w for w in works if w.year and w.year >= current_year - 3],
        key=lambda w: (w.year or 0, w.cited_by_count or 0),
        reverse=True,
    )[:8]

    venue_counts: dict[str, int] = {}
    author_counts: dict[str, int] = {}
    for w in works:
        if w.venue:
            venue_counts[w.venue] = venue_counts.get(w.venue, 0) + 1
        for name in w.author_names:
            author_counts[name] = author_counts.get(name, 0) + 1

    top_venues = sorted(venue_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_authors = sorted(author_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "topic": topic,
        "found": len(works),
        "all_results": works,
        "seminal": seminal,
        "recent": recent,
        "top_venues": [{"venue": v, "count": c} for v, c in top_venues],
        "top_authors": [{"author": a, "count": c} for a, c in top_authors],
    }


# --------------------------------------------------------------------------- #
# Research consensus / landscape analysis
# --------------------------------------------------------------------------- #
async def research_consensus(topic: str, *, limit: int = 40) -> dict[str, Any]:
    """Analyse a meta-search corpus for evidence strength, study-type mix and
    directional lean. See :mod:`analysis` for the (disclosed) heuristics."""
    works = await meta_search(topic, limit=limit, sort="relevance")
    if not works:
        return {"topic": topic, "found": False}

    current_year = datetime.now(timezone.utc).year
    summary = analyse_corpus(works, current_year)

    venue_counts: dict[str, int] = {}
    for w in works:
        if w.venue:
            venue_counts[w.venue] = venue_counts.get(w.venue, 0) + 1
    top_venues = sorted(venue_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]

    summary.update({
        "topic": topic,
        "found": True,
        "top_venues": [{"venue": v, "count": c} for v, c in top_venues],
        "disclaimer": "This is a bibliometric overview, not a meta-analysis. The directional 'lean' "
                      "is a coarse keyword heuristic over titles/abstracts and can misclassify nuanced "
                      "work; study-type and rigor counts are abstract-level approximations. Read the "
                      "papers before drawing conclusions.",
    })
    return summary


# --------------------------------------------------------------------------- #
# Citation export
# --------------------------------------------------------------------------- #
async def resolve_works(identifiers: list[str]) -> list[Work]:
    results = await asyncio.gather(*(get_work(i, enrich=False) for i in identifiers))
    return [w for w in results if w is not None]


# --------------------------------------------------------------------------- #
# PDF full-text reading
# --------------------------------------------------------------------------- #
async def read_pdf(identifier_or_url: str, *, max_pages: int = 30, max_chars: int = 20_000) -> dict[str, Any]:
    """Read a paper's full text.

    Accepts a direct PDF URL, or an identifier (DOI/arXiv/OpenAlex/PMID) which is
    resolved to *all* candidate open-access sources; each is tried in turn until
    one yields readable text. The result includes a transparent ``attempts`` log.
    """
    from .pdf import extract_fulltext

    raw = identifier_or_url.strip()
    is_direct_url = raw.lower().startswith("http")

    title = None
    if is_direct_url:
        sources = [{"source": "url", "url": raw, "kind": "pdf"}]
    else:
        work, sources = await _gather_pdf_candidates(raw)
        title = work.title if work else None
        if not sources:
            return {
                "identifier": identifier_or_url, "ok": False, "title": title,
                "error": "No open-access full-text source could be located for this identifier. "
                         "The work may be paywalled with no repository copy.",
                "attempts": [],
            }

    result = await extract_fulltext(sources, max_pages=max_pages, max_chars=max_chars)
    result["identifier"] = identifier_or_url
    if title:
        result["title"] = title
    return result


# --------------------------------------------------------------------------- #
# Zotero export
# --------------------------------------------------------------------------- #
async def zotero_add(identifiers: list[str], *, collection_key: str | None = None) -> dict[str, Any]:
    """Resolve identifiers and push them into the configured Zotero library."""
    if not zotero.available():
        return {"ok": False, "error": "Zotero is not configured. Set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID (and optionally ZOTERO_LIBRARY_TYPE)."}
    works = await resolve_works(identifiers)
    if not works:
        return {"ok": False, "error": "None of the supplied identifiers could be resolved."}
    summary = await zotero.add_items(works, collection_key=collection_key)
    summary["requested"] = len(identifiers)
    summary["resolved"] = len(works)
    return summary


async def zotero_collections() -> list[dict[str, str]]:
    return await zotero.list_collections()
