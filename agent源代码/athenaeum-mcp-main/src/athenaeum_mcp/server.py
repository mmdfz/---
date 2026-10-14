"""Athenaeum MCP server: tool definitions over the service layer.

Run as a stdio MCP server:  ``python -m athenaeum_mcp.server``

All tools are prefixed ``athenaeum_`` so they namespace cleanly alongside other
MCP servers a client may load.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import service
from .formatting import csl_json_string, format_bibliography, format_citation
from .providers import crossref
from .render import (
    render_author_md,
    render_venue_md,
    render_work_md,
    render_works_md,
    works_to_json,
)

mcp = FastMCP("athenaeum")

ResponseFormat = Literal["markdown", "json"]
ProviderName = Literal[
    "openalex", "crossref", "arxiv", "europepmc", "pubmed",
    "semantic_scholar", "dblp", "core",
]
SortOrder = Literal["relevance", "citations"]
CitationStyle = Literal["bibtex", "ris", "apa", "mla", "chicago", "vancouver", "harvard", "ieee", "csl-json"]

_READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

# Tools that change external state (e.g. write to a Zotero library or disk).
_WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}


def _dumps(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


def _out_works(works, header: str, response_format: str, show_abstract: bool = False) -> str:
    if response_format == "json":
        return _dumps({"count": len(works), "results": works_to_json(works)})
    return render_works_md(works, header, show_abstract=show_abstract)


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"title": "Search scholarly literature (meta-search)", **_READ_ONLY})
async def athenaeum_search(
    query: Annotated[str, Field(description="Free-text topic or phrase, e.g. 'technostress and thriving at work'", min_length=2)],
    limit: Annotated[int, Field(description="Max merged results to return", ge=1, le=100)] = 20,
    year_from: Annotated[int | None, Field(description="Earliest publication year (inclusive)")] = None,
    year_to: Annotated[int | None, Field(description="Latest publication year (inclusive)")] = None,
    open_access_only: Annotated[bool, Field(description="Only return works with an open-access/free full text")] = False,
    providers: Annotated[list[ProviderName] | None, Field(description="Subset of providers to query; default uses OpenAlex, Crossref, arXiv, Europe PMC and PubMed (plus CORE/Semantic Scholar when their key is set). Pass [\"dblp\"] to add the computer-science index")] = None,
    sort: Annotated[SortOrder, Field(description="'relevance' (rank fusion across providers) or 'citations'")] = "relevance",
    show_abstract: Annotated[bool, Field(description="Include abstracts in markdown output")] = False,
    response_format: ResponseFormat = "markdown",
) -> str:
    """Search several scholarly databases at once and return one deduplicated,
    ranked list of works.

    This is the flagship tool. It queries OpenAlex, Crossref, arXiv, Europe
    PMC and PubMed (plus CORE and Semantic Scholar when their key is
    configured) in parallel, merges records that refer to the same paper (by
    DOI then fuzzy title), and ranks them with reciprocal rank fusion so papers
    found by multiple databases rise to the top. Each result lists which
    databases it was ``Found in``. Add the computer-science index explicitly
    with ``providers=["dblp"]``.

    Use for: literature discovery, "what's been written about X", finding the
    most-cited or most recent work on a topic. For a single database's native
    behaviour use ``athenaeum_search_provider``; to look up one known paper use
    ``athenaeum_get_work``.
    """
    works = await service.meta_search(
        query, limit=limit, year_from=year_from, year_to=year_to,
        open_access_only=open_access_only, providers=providers, sort=sort,
    )
    return _out_works(works, f"Search results for: {query}", response_format, show_abstract)


@mcp.tool(annotations={"title": "Search a single provider", **_READ_ONLY})
async def athenaeum_search_provider(
    provider: Annotated[ProviderName, Field(description="Which database to query directly")],
    query: Annotated[str, Field(description="Free-text query", min_length=2)],
    limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 20,
    year_from: Annotated[int | None, Field(description="Earliest year")] = None,
    year_to: Annotated[int | None, Field(description="Latest year")] = None,
    open_access_only: Annotated[bool, Field(description="Only open-access works")] = False,
    show_abstract: Annotated[bool, Field(description="Include abstracts")] = False,
    response_format: ResponseFormat = "markdown",
) -> str:
    """Query one named provider directly (openalex | crossref | arxiv |
    europepmc | pubmed | semantic_scholar | dblp | core).

    Use when you want a specific database's native ranking/coverage — e.g.
    arXiv or DBLP for the latest CS/ML preprints, Europe PMC or PubMed for
    biomedical work, CORE for open-access full text. For broad coverage prefer
    ``athenaeum_search``.
    """
    works = await service.search_provider(
        provider, query, limit=limit, year_from=year_from, year_to=year_to,
        open_access_only=open_access_only,
    )
    return _out_works(works, f"{provider} results for: {query}", response_format, show_abstract)


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"title": "Get full metadata for a work", **_READ_ONLY})
async def athenaeum_get_work(
    identifier: Annotated[str, Field(description="DOI, OpenAlex ID (W...), arXiv ID, or PMID", min_length=2)],
    enrich: Annotated[bool, Field(description="Merge metadata across multiple databases for completeness")] = True,
    show_abstract: Annotated[bool, Field(description="Include the abstract")] = True,
    response_format: ResponseFormat = "markdown",
) -> str:
    """Resolve one paper by any identifier (DOI, OpenAlex ID, arXiv ID, PMID)
    and return its full normalized metadata.

    With ``enrich=True`` it combines records from several databases so missing
    fields (abstract, citations, open-access PDF, …) are filled in. Use this
    when you already know which paper you want.
    """
    work = await service.get_work(identifier, enrich=enrich)
    if work is None:
        return f"No work found for identifier: {identifier}"
    if response_format == "json":
        return _dumps(work.compact())
    return render_work_md(work, show_abstract=show_abstract)


@mcp.tool(annotations={"title": "Find a free PDF", **_READ_ONLY})
async def athenaeum_find_pdf(
    identifier: Annotated[str, Field(description="DOI, OpenAlex ID, arXiv ID or PMID", min_length=2)],
    response_format: ResponseFormat = "markdown",
) -> str:
    """Locate free, legal full-text PDF candidates for a work (without downloading).

    Gathers every open-access location Athenaeum knows — arXiv, Europe PMC / PMC,
    each of OpenAlex's repository and publisher locations, and Unpaywall (if
    configured) — ordered most-accessible first. To actually read the text, use
    ``athenaeum_read_pdf``, which tries these sources in turn.
    """
    result = await service.find_pdf(identifier)
    if response_format == "json":
        return _dumps(result)
    if not result["found"]:
        return f"No free PDF candidate found for {identifier}. The work may be paywalled with no repository copy."
    lines = [f"# Free full-text candidates for: {result.get('title') or identifier}", ""]
    if result.get("best_pdf_url"):
        lines.append(f"**Best direct PDF:** {result['best_pdf_url']}")
    lines.append(f"\n**All candidates ({result.get('candidate_count', 0)}):**")
    for s in result["sources"]:
        kind = s.get("kind", "pdf")
        tag = "PDF" if kind == "pdf" else "landing page"
        lines.append(f"- [{tag}] {s['source']}: {s['url']}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Citation graph
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"title": "Get references (works cited by)", **_READ_ONLY})
async def athenaeum_get_references(
    identifier: Annotated[str, Field(description="DOI or OpenAlex ID of the citing work", min_length=2)],
    limit: Annotated[int, Field(description="Max references to return", ge=1, le=100)] = 40,
    response_format: ResponseFormat = "markdown",
) -> str:
    """List the works **cited by** a paper (its reference list / outgoing edges).

    Use to mine a paper's foundations or snowball backwards through the
    literature.
    """
    works = await service.get_references(identifier, limit=limit)
    return _out_works(works, f"References of {identifier}", response_format)


@mcp.tool(annotations={"title": "Get citations (works citing this)", **_READ_ONLY})
async def athenaeum_get_citations(
    identifier: Annotated[str, Field(description="DOI or OpenAlex ID of the cited work", min_length=2)],
    limit: Annotated[int, Field(description="Max citing works (sorted by their own citations)", ge=1, le=100)] = 25,
    response_format: ResponseFormat = "markdown",
) -> str:
    """List the works that **cite** a paper (incoming edges), most-cited first.

    Use for forward citation search — finding newer work that builds on a paper.
    """
    works = await service.get_citations(identifier, limit=limit)
    return _out_works(works, f"Works citing {identifier}", response_format)


@mcp.tool(annotations={"title": "Get related works", **_READ_ONLY})
async def athenaeum_get_related(
    identifier: Annotated[str, Field(description="DOI or OpenAlex ID", min_length=2)],
    limit: Annotated[int, Field(description="Max related works", ge=1, le=100)] = 20,
    response_format: ResponseFormat = "markdown",
) -> str:
    """List works related to a paper (OpenAlex's precomputed related works).

    Use to broaden a search sideways from a known relevant paper.
    """
    works = await service.get_related(identifier, limit=limit)
    return _out_works(works, f"Works related to {identifier}", response_format)


@mcp.tool(annotations={"title": "Traverse the citation network", **_READ_ONLY})
async def athenaeum_citation_graph(
    identifier: Annotated[str, Field(description="Seed paper DOI or OpenAlex ID", min_length=2)],
    depth: Annotated[int, Field(description="Hops from the seed (1 or 2)", ge=1, le=2)] = 1,
    per_node: Annotated[int, Field(description="Neighbours to expand per node", ge=1, le=15)] = 8,
    direction: Annotated[Literal["references", "citations", "both"], Field(description="Follow references (backward), citations (forward), or both")] = "citations",
    response_format: ResponseFormat = "markdown",
) -> str:
    """Build an N-hop citation network around a seed paper and return its nodes
    and edges.

    Use to map a research area's structure, spot hubs, or assemble a connected
    reading set. Depth is capped at 2 and the graph at 60 nodes to stay fast.
    """
    graph = await service.citation_graph(
        identifier, depth=depth, per_node=per_node, direction=direction
    )
    if response_format == "json":
        return _dumps(graph)
    if not graph["found"]:
        return f"Could not resolve seed work: {identifier}"
    lines = [
        f"# Citation graph for: {graph['seed_title']}",
        "",
        f"- **Seed:** {graph['seed']}",
        f"- **Direction:** {graph['direction']} · **Depth:** {graph['depth']}",
        f"- **Nodes:** {graph['node_count']} · **Edges:** {graph['edge_count']}",
        "",
        "## Nodes (by citations)",
    ]
    for n in sorted(graph["nodes"], key=lambda x: (x.get("cited_by_count") or 0), reverse=True):
        cites = n.get("cited_by_count")
        cstr = f" · cited by {cites}" if cites is not None else ""
        lines.append(f"- [{n.get('year')}] {n.get('title')}{cstr} ({n['id']})")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Authors & venues
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"title": "Get author profile & metrics", **_READ_ONLY})
async def athenaeum_get_author(
    name_or_id: Annotated[str, Field(description="Author name, ORCID, or OpenAlex author ID (A...)", min_length=2)],
    response_format: ResponseFormat = "markdown",
) -> str:
    """Look up a researcher's profile: affiliation, works count, total
    citations, h-index and main topics.

    Accepts a name (best match is returned), an ORCID, or an OpenAlex author ID.
    """
    author = await service.get_author(name_or_id)
    if author is None:
        return f"No author found for: {name_or_id}"
    if response_format == "json":
        return _dumps(author.compact())
    return render_author_md(author)


@mcp.tool(annotations={"title": "Get venue profile & metrics", **_READ_ONLY})
async def athenaeum_get_venue(
    issn_or_name: Annotated[str, Field(description="Journal ISSN (preferred) or name", min_length=2)],
    response_format: ResponseFormat = "markdown",
) -> str:
    """Look up a journal/venue: publisher, metrics (2-year mean citedness,
    h-index), open-access and DOAJ status.

    Prefer an ISSN for an exact match. Use to gauge where a paper was published.
    """
    venue = await service.get_venue(issn_or_name)
    if venue is None:
        return f"No venue found for: {issn_or_name}"
    if response_format == "json":
        return _dumps(venue.compact())
    return render_venue_md(venue)


# --------------------------------------------------------------------------- #
# Citation export
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"title": "Format a citation", **_READ_ONLY})
async def athenaeum_format_citation(
    identifier: Annotated[str, Field(description="DOI, OpenAlex ID, arXiv ID or PMID", min_length=2)],
    style: Annotated[Literal["bibtex", "ris", "apa", "mla", "chicago", "vancouver", "harvard", "ieee"], Field(description="Citation style")] = "apa",
) -> str:
    """Format one work as a citation in the requested style.

    Styles: bibtex, ris, apa, mla, chicago, vancouver, harvard, ieee. BibTeX/RIS
    use Crossref's authoritative export when a DOI is available, otherwise a
    local generator (which also works for preprints without a DOI).
    Returns the raw citation text, ready to paste.
    """
    work = await service.get_work(identifier, enrich=True)
    if work is None:
        return f"No work found for identifier: {identifier}"
    style = style.lower()
    if style in {"bibtex", "ris"} and work.doi:
        authoritative = await crossref.format(work.doi, style)
        if authoritative:
            return authoritative.strip()
    return format_citation(work, style)


@mcp.tool(annotations={"title": "Build a bibliography", **_READ_ONLY})
async def athenaeum_build_bibliography(
    identifiers: Annotated[list[str], Field(description="List of DOIs / OpenAlex IDs / arXiv IDs / PMIDs", min_length=1, max_length=100)],
    style: Annotated[Literal["bibtex", "ris", "apa", "mla", "chicago", "vancouver", "harvard", "ieee"], Field(description="Citation style")] = "bibtex",
    response_format: ResponseFormat = "markdown",
) -> str:
    """Resolve many identifiers and produce a combined bibliography.

    BibTeX/RIS are concatenated into one importable file; prose styles are
    returned as an ordered reference list. Use to assemble a reference section
    or a ``.bib`` file from a set of papers.
    """
    works = await service.resolve_works(identifiers)
    if not works:
        return "No works could be resolved from the supplied identifiers."
    bibliography = format_bibliography(works, style.lower())
    missing = len(identifiers) - len(works)
    if response_format == "json":
        return _dumps({"requested": len(identifiers), "resolved": len(works), "missing": missing,
                       "style": style, "bibliography": bibliography})
    note = f"\n\n> Resolved {len(works)}/{len(identifiers)} identifiers." if missing else ""
    return f"```\n{bibliography}\n```{note}"


@mcp.tool(annotations={"title": "Export references to a file", **_WRITE})
async def athenaeum_export(
    identifiers: Annotated[list[str], Field(description="List of DOIs / OpenAlex IDs / arXiv IDs / PMIDs", min_length=1, max_length=200)],
    format: Annotated[CitationStyle, Field(description="Export format. Use 'bibtex'/'ris'/'csl-json' for reference managers (Zotero, Mendeley, EndNote)")] = "bibtex",
    file_path: Annotated[str | None, Field(description="Absolute path to write to. If omitted, the content is returned inline. Extension is auto-added if missing.")] = None,
) -> str:
    """Resolve identifiers and export them as a reference-manager file.

    Supports BibTeX (.bib), RIS (.ris) and CSL-JSON (.json) — the formats Zotero,
    Mendeley, EndNote and Pandoc import. If ``file_path`` is given the file is
    written to disk; otherwise the content is returned inline for the agent to
    save. This is the local-file alternative to pushing directly into Zotero
    with ``athenaeum_zotero_add``.
    """
    works = await service.resolve_works(identifiers)
    if not works:
        return "No works could be resolved from the supplied identifiers."

    fmt = format.lower()
    if fmt == "csl-json":
        content = csl_json_string(works)
        ext = ".json"
    else:
        content = format_bibliography(works, fmt)
        ext = ".bib" if fmt == "bibtex" else ".ris" if fmt == "ris" else ".txt"

    if not file_path:
        fence = "json" if fmt == "csl-json" else ""
        return f"Resolved {len(works)}/{len(identifiers)} works.\n\n```{fence}\n{content}\n```"

    from pathlib import Path

    target = Path(file_path)
    if target.suffix.lower() != ext:
        target = target.with_suffix(ext)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"Error writing file: {exc}"
    return f"Exported {len(works)}/{len(identifiers)} works ({fmt}) to: {target}"


@mcp.tool(annotations={"title": "Read a paper's full text (PDF)", **_READ_ONLY})
async def athenaeum_read_pdf(
    identifier_or_url: Annotated[str, Field(description="A direct PDF URL, or a DOI/arXiv/OpenAlex/PMID to auto-locate a free PDF", min_length=4)],
    max_pages: Annotated[int, Field(description="Maximum pages to extract", ge=1, le=100)] = 30,
    max_chars: Annotated[int, Field(description="Maximum characters of text to return", ge=1000, le=80_000)] = 20_000,
    show_attempts: Annotated[bool, Field(description="Append the per-source attempt log (useful when no source works)")] = False,
) -> str:
    """Download an open-access PDF and extract its full text.

    Accepts a direct PDF URL or any identifier. For an identifier it gathers
    *all* open-access candidates (arXiv, Europe PMC/PMC, OpenAlex repository and
    publisher locations, Unpaywall) and tries each in turn, recovering PDFs from
    landing pages via the ``citation_pdf_url`` standard. Use this to read a
    paper's actual content — methods, results, specific claims — beyond the
    abstract.

    Known limits (disclosed): sites behind a JavaScript/Cloudflare challenge
    (notably some MDPI hosts) return HTTP 403 to any non-browser client and
    cannot be read; scanned/image-only PDFs yield no text (OCR is out of scope);
    paywalled works without a repository copy cannot be read. On failure the
    response explains what was tried — pass ``show_attempts=true`` for the full
    per-source log.
    """
    result = await service.read_pdf(identifier_or_url, max_pages=max_pages, max_chars=max_chars)
    if not result.get("ok"):
        msg = f"Could not read full text for '{identifier_or_url}': {result.get('error', 'unknown error')}"
        attempts = result.get("attempts") or []
        if attempts and (show_attempts or len(attempts) <= 8):
            msg += "\n\n**Sources tried:**"
            for a in attempts:
                resolved = f" → {a['resolved_pdf_url']}" if a.get("resolved_pdf_url") else ""
                msg += f"\n- [{a['source']}] {a['result']}{resolved}"
            msg += ("\n\n_Tip: the paper may still be readable from the publisher's website in a "
                    "browser, or via your institution's access._")
        return msg
    header = result.get("title") or identifier_or_url
    src = result.get("source")
    meta = f"_Read {result['pages_read']}/{result['pages_total']} pages · {result['char_count']} chars"
    meta += f" · source: {src}" if src else ""
    meta += " (truncated)_" if result.get("truncated") else "_"
    return f"# Full text: {header}\n\n{meta}\n\n{result['text']}"


# --------------------------------------------------------------------------- #
# Zotero
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"title": "Add references to Zotero", **_WRITE})
async def athenaeum_zotero_add(
    identifiers: Annotated[list[str], Field(description="DOIs / OpenAlex IDs / arXiv IDs / PMIDs to add to Zotero", min_length=1, max_length=200)],
    collection_key: Annotated[str | None, Field(description="Optional Zotero collection key to file the items under (see athenaeum_zotero_collections)")] = None,
) -> str:
    """Add resolved works directly into the user's Zotero library.

    Requires Zotero to be configured (ZOTERO_API_KEY + ZOTERO_LIBRARY_ID). Each
    identifier is resolved to full metadata and created as a Zotero item, so the
    user's reference manager fills up as they research. Optionally file items
    into a specific collection.
    """
    result = await service.zotero_add(identifiers, collection_key=collection_key)
    if not result.get("ok"):
        return f"Zotero add failed: {result.get('error', 'unknown error')}"
    msg = (f"Added {result['created']} item(s) to Zotero "
           f"({result['library']}). Resolved {result.get('resolved')}/{result.get('requested')} identifiers.")
    if result.get("failed"):
        msg += f" {result['failed']} failed."
    if result.get("messages"):
        msg += "\n\nNotes:\n" + "\n".join(f"- {m}" for m in result["messages"])
    return msg


@mcp.tool(annotations={"title": "List Zotero collections", **_READ_ONLY})
async def athenaeum_zotero_collections(
    response_format: ResponseFormat = "markdown",
) -> str:
    """List the collections in the configured Zotero library.

    Use to discover a ``collection_key`` for ``athenaeum_zotero_add``. Requires
    Zotero to be configured.
    """
    collections = await service.zotero_collections()
    if response_format == "json":
        return _dumps({"count": len(collections), "collections": collections})
    if not collections:
        return "No Zotero collections found (or Zotero is not configured)."
    lines = ["# Zotero collections", ""]
    lines += [f"- **{c['name']}** — `{c['key']}`" for c in collections]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"title": "Validate a source's credibility & rigor", **_READ_ONLY})
async def athenaeum_validate_source(
    identifier: Annotated[str, Field(description="DOI (preferred), OpenAlex ID, arXiv ID or PMID", min_length=2)],
    response_format: ResponseFormat = "markdown",
) -> str:
    """Assemble credibility & rigor signals for a work and a transparent 0–100 score.

    Checks: resolution across databases, retraction flags, citation counts and
    rate, venue metrics (h-index, mean citedness), DOAJ indexing and Crossref
    registration, peer-review vs preprint status, open-access transparency, and
    study-design rigor cues mined from the abstract (sample size, methodology,
    pre-registration, meta-analysis, limitations). It reports *evidence and
    caveats*, not a verdict on whether the findings are true — use scholarly
    judgement.
    """
    result = await service.validate_source(identifier)
    if response_format == "json":
        return _dumps(result)
    if not result["resolves"]:
        return f"# Validation: {identifier}\n\n**Could not resolve** this identifier in any database.\n\n" + \
               "\n".join(f"- {r}" for r in result["reasons"])
    lines = [
        f"# Credibility & rigor check: {result.get('title') or identifier}",
        "",
        f"**Score: {result['credibility_score']}/100 ({result['credibility_label']})**",
        "",
        f"- DOI: {result.get('doi')}  ·  Year: {result.get('year')}  ·  Venue: {result.get('venue')}",
        f"- Type: {result.get('work_type') or 'unknown'}  ·  Peer-reviewed: {result.get('peer_reviewed')}",
        f"- Open access: {result.get('is_oa')}  ·  Cited by: {result.get('cited_by_count')}",
        f"- Indexed in: {', '.join(result.get('providers') or []) or '—'}",
    ]
    if result.get("is_retracted"):
        lines.append("- ⚠️ **RETRACTED**")
    if result.get("rigor_signals"):
        lines.append("\n## Methodological rigor cues")
        lines += [f"- 🔬 {s}" for s in result["rigor_signals"]]
    if result.get("positive_signals"):
        lines.append("\n## Positive signals")
        lines += [f"- ✅ {s}" for s in result["positive_signals"]]
    if result.get("caution_signals"):
        lines.append("\n## Caution signals")
        lines += [f"- ⚠️ {s}" for s in result["caution_signals"]]
    lines.append(f"\n_{result['disclaimer']}_")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Workflow
# --------------------------------------------------------------------------- #
@mcp.tool(annotations={"title": "Literature review starter", **_READ_ONLY})
async def athenaeum_literature_review(
    topic: Annotated[str, Field(description="Research topic or question", min_length=2)],
    limit: Annotated[int, Field(description="Breadth of the underlying search", ge=5, le=60)] = 30,
    response_format: ResponseFormat = "markdown",
) -> str:
    """Assemble a starter literature landscape for a topic.

    Runs a broad meta-search, then surfaces seminal works (most cited), recent
    works (last 3 years), and the most frequent venues and authors — a fast way
    to orient yourself in a new area and pick a seed reading set. For how
    consistent the field's findings appear, use ``athenaeum_research_consensus``.
    """
    review = await service.literature_review(topic, limit=limit)
    if response_format == "json":
        payload = {
            "topic": review["topic"],
            "found": review["found"],
            "seminal": works_to_json(review.get("seminal", [])),
            "recent": works_to_json(review.get("recent", [])),
            "top_venues": review.get("top_venues", []),
            "top_authors": review.get("top_authors", []),
        }
        return _dumps(payload)
    if not review["found"]:
        return f"No results found for topic: {topic}"
    lines = [f"# Literature landscape: {topic}", "", f"_Based on {review['found']} works._", ""]
    lines.append("## Seminal works (most cited)")
    for w in review["seminal"]:
        lines.append(f"- [{w.year}] **{w.title}** — cited by {w.cited_by_count or 0}. {', '.join(w.author_names[:3])}. ({w.best_id})")
    lines.append("\n## Recent works (last 3 years)")
    for w in review["recent"]:
        lines.append(f"- [{w.year}] {w.title} — cited by {w.cited_by_count or 0}. ({w.best_id})")
    if review["top_venues"]:
        lines.append("\n## Frequent venues")
        lines += [f"- {v['venue']} ({v['count']})" for v in review["top_venues"]]
    if review["top_authors"]:
        lines.append("\n## Frequent authors")
        lines += [f"- {a['author']} ({a['count']})" for a in review["top_authors"]]
    return "\n".join(lines)


@mcp.tool(annotations={"title": "Assess research consensus & rigor of a field", **_READ_ONLY})
async def athenaeum_research_consensus(
    topic: Annotated[str, Field(description="Research question or topic, e.g. 'does remote work reduce productivity'", min_length=3)],
    limit: Annotated[int, Field(description="How many works to analyse", ge=10, le=80)] = 40,
    response_format: ResponseFormat = "markdown",
) -> str:
    """Gauge the maturity, methodological rigor and directional leaning of a
    body of research on a topic.

    Analyses a meta-search corpus and reports: evidence base size and recency,
    the mix of study types (meta-analyses, reviews, empirical studies,
    preprints), venue quality, an evidence-strength rating, and a lightweight
    sentiment lean (supporting / mixed / challenging) inferred from titles and
    abstracts.

    This is a *bibliometric* summary to orient you, NOT a substitute for reading
    the papers: the directional lean is a coarse lexical heuristic and can be
    wrong on nuanced or ironically-phrased work. Treat it as a starting hypothesis.
    """
    result = await service.research_consensus(topic, limit=limit)
    if response_format == "json":
        return _dumps(result)
    if not result.get("found"):
        return f"No results found for topic: {topic}"
    s = result
    lines = [
        f"# Research landscape & consensus: {topic}",
        "",
        f"_Analysed {s['analysed']} works ({s['year_range']})._",
        "",
        "## Evidence base",
        f"- **Strength:** {s['evidence_strength']}",
        f"- **Maturity:** {s['maturity']}",
        f"- **Total citations across corpus:** {s['total_citations']:,}",
        f"- **Median year:** {s['median_year']}  ·  **Recent (≤3y) share:** {s['recent_share_pct']}%",
        f"- **Open-access share:** {s['oa_share_pct']}%",
    ]
    if s.get("retracted_count"):
        lines.append(f"- ⚠️ **{s['retracted_count']} retracted work(s)** in the corpus")
    lines.append("\n## Study types")
    for label, n in s["study_types"].items():
        if n:
            lines.append(f"- {label}: {n}")
    lines.append("\n## Directional lean (lexical heuristic)")
    lean = s["sentiment"]
    lines.append(f"- Supporting: {lean['supporting']} · Mixed/neutral: {lean['mixed']} · Challenging: {lean['challenging']}")
    lines.append(f"- **Overall lean:** {lean['overall']}")
    if s.get("top_venues"):
        lines.append("\n## Where this is published")
        lines += [f"- {v['venue']} ({v['count']})" for v in s["top_venues"]]
    lines.append(f"\n_{s['disclaimer']}_")
    return "\n".join(lines)


def main() -> None:
    """Console entry point: run the stdio MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
