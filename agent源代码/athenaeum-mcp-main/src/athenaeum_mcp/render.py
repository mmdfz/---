"""Render works/venues/authors as Markdown (human) or JSON (machine)."""
from __future__ import annotations

from typing import Any

from .models import AuthorProfile, Venue, Work


def _authors_inline(work: Work, limit: int = 4) -> str:
    names = work.author_names
    if not names:
        return "—"
    shown = names[:limit]
    suffix = f" (+{len(names) - limit} more)" if len(names) > limit else ""
    return ", ".join(shown) + suffix


def _oa_label(work: Work) -> str:
    if work.is_oa:
        status = f" {work.oa_status}" if work.oa_status else ""
        pdf = " · PDF available" if work.pdf_url else ""
        return f"Open access{status}{pdf}"
    if work.is_oa is False:
        return "Closed / paywalled"
    return "OA status unknown"


def render_work_md(work: Work, index: int | None = None, show_abstract: bool = False) -> str:
    head = f"{index}. {work.title or 'Untitled'}" if index is not None else (work.title or "Untitled")
    lines = [f"### {head}"]
    lines.append(f"- **Authors:** {_authors_inline(work)}")

    meta = []
    if work.year:
        meta.append(str(work.year))
    if work.venue:
        meta.append(work.venue)
    if work.type:
        meta.append(work.type)
    if meta:
        lines.append(f"- **Published:** {' · '.join(meta)}")

    stat = []
    if work.cited_by_count is not None:
        stat.append(f"cited by {work.cited_by_count}")
    stat.append(_oa_label(work))
    if work.is_retracted:
        stat.append("⚠️ RETRACTED")
    lines.append(f"- **Status:** {' · '.join(stat)}")

    if work.providers:
        lines.append(f"- **Found in:** {', '.join(work.providers)}")

    ids = work.ids()
    if ids:
        lines.append("- **IDs:** " + " · ".join(f"{k}:{v}" for k, v in ids.items()))

    if work.tldr:
        lines.append(f"- **TLDR:** {work.tldr}")

    links = []
    if work.doi:
        links.append(f"[DOI](https://doi.org/{work.doi})")
    if work.pdf_url:
        links.append(f"[PDF]({work.pdf_url})")
    elif work.landing_url:
        links.append(f"[Link]({work.landing_url})")
    if links:
        lines.append(f"- **Links:** {' · '.join(links)}")

    if show_abstract and work.abstract:
        abstract = work.abstract if len(work.abstract) <= 900 else work.abstract[:900] + "…"
        lines.append(f"- **Abstract:** {abstract}")

    return "\n".join(lines)


def render_works_md(works: list[Work], header: str, show_abstract: bool = False) -> str:
    if not works:
        return f"# {header}\n\n_No results._"
    parts = [f"# {header}", f"\n_{len(works)} result(s)._\n"]
    for i, w in enumerate(works, 1):
        parts.append(render_work_md(w, index=i, show_abstract=show_abstract))
        parts.append("")
    return "\n".join(parts).strip()


def works_to_json(works: list[Work]) -> list[dict[str, Any]]:
    return [w.compact() for w in works]


def render_venue_md(v: Venue) -> str:
    lines = [f"### {v.name or 'Unknown venue'}"]
    if v.publisher:
        lines.append(f"- **Publisher:** {v.publisher}")
    if v.type:
        lines.append(f"- **Type:** {v.type}")
    if v.issn:
        lines.append(f"- **ISSN:** {', '.join(v.issn)}")
    metrics = []
    if v.impact_2yr is not None:
        metrics.append(f"2-yr mean citedness {v.impact_2yr:.2f}")
    if v.h_index is not None:
        metrics.append(f"h-index {v.h_index}")
    if v.works_count is not None:
        metrics.append(f"{v.works_count:,} works")
    if metrics:
        lines.append(f"- **Metrics:** {' · '.join(metrics)}")
    oa = []
    if v.is_oa is not None:
        oa.append("fully OA" if v.is_oa else "not fully OA")
    if v.is_in_doaj or v.in_doaj_confirmed:
        oa.append("indexed in DOAJ")
    if v.apc_usd is not None:
        oa.append(f"APC ${v.apc_usd}")
    if oa:
        lines.append(f"- **Open access:** {' · '.join(oa)}")
    return "\n".join(lines)


def render_author_md(a: AuthorProfile) -> str:
    lines = [f"### {a.name or 'Unknown author'}"]
    if a.affiliation:
        lines.append(f"- **Affiliation:** {a.affiliation}")
    if a.orcid:
        lines.append(f"- **ORCID:** {a.orcid}")
    metrics = []
    if a.works_count is not None:
        metrics.append(f"{a.works_count:,} works")
    if a.cited_by_count is not None:
        metrics.append(f"{a.cited_by_count:,} citations")
    if a.h_index is not None:
        metrics.append(f"h-index {a.h_index}")
    if metrics:
        lines.append(f"- **Metrics:** {' · '.join(metrics)}")
    if a.topics:
        lines.append(f"- **Topics:** {', '.join(a.topics)}")
    return "\n".join(lines)
