"""Smoke test: dedup/merge + citation formatting. Run after providers smoke."""
import asyncio

from athenaeum_mcp.dedup import merge_works
from athenaeum_mcp.formatting import STYLES, format_citation
from athenaeum_mcp.http_client import close_client
from athenaeum_mcp.models import Author, Work
from athenaeum_mcp.providers import arxiv, crossref, europepmc, openalex
from athenaeum_mcp.render import render_work_md


async def main():
    # --- live multi-provider fan-out + merge ---
    q = "technostress workplace wellbeing"
    batches = await asyncio.gather(
        openalex.search(q, limit=15),
        crossref.search(q, limit=15),
        arxiv.search(q, limit=10),
        europepmc.search(q, limit=10),
    )
    print("per-provider counts:", {p: len(b) for p, b in zip(["openalex", "crossref", "arxiv", "europepmc"], batches)})
    oa_dois = {w.doi for w in batches[0] if w.doi}
    cr_dois = {w.doi for w in batches[1] if w.doi}
    print("openalex DOIs:", len(oa_dois), "| crossref DOIs:", len(cr_dois), "| shared:", len(oa_dois & cr_dois))
    flat = [w for b in batches for w in b]
    merged = merge_works(flat)
    multi = [w for w in merged if len(w.providers) > 1]
    print(f"raw={len(flat)}  merged={len(merged)}  multi-source={len(multi)}")
    print("dedup removed", len(flat) - len(merged), "duplicate records")

    # --- controlled DOI merge: same paper from two providers ---
    DOI = "10.1128/jb.175.12.3749-3756.1993"
    same = await asyncio.gather(openalex.get_work(DOI), crossref.get_work(DOI))
    cm = merge_works([w for w in same if w])
    print("\ncontrolled same-paper merge (openalex+crossref) ->", len(cm), "record, providers:", cm[0].providers if cm else None)
    assert len(cm) == 1, f"expected 1 merged from same DOI, got {len(cm)}"

    # --- synthetic merge correctness (valid DOIs, case-insensitive) ---
    a = Work(doi="10.1234/abc", title="Role Shift and AI", authors=[Author(name="Jane Doe")], source_provider="crossref", cited_by_count=5)
    b = Work(doi="10.1234/ABC", title="Role shift and AI", abstract="Long abstract here", source_provider="openalex", cited_by_count=12, is_oa=True)
    c = Work(title="Role shift and AI", source_provider="arxiv", arxiv_id="2401.00001")
    m = merge_works([a, b, c])
    assert len(m) == 1, f"expected 1 merged, got {len(m)}"
    only = m[0]
    print("synthetic merge -> providers:", only.providers, "| cites:", only.cited_by_count, "| oa:", only.is_oa, "| arxiv:", only.arxiv_id)
    assert only.cited_by_count == 12 and only.is_oa and only.arxiv_id == "2401.00001"

    # --- citation formatting across all styles ---
    work = await openalex.get_work("10.1128/jb.175.12.3749-3756.1993")
    print("\n=== Citation styles for:", work.title[:50], "===")
    for style in STYLES:
        print(f"\n[{style}]")
        print(format_citation(work, style))

    print("\n=== Markdown render ===")
    print(render_work_md(work, index=1, show_abstract=False))

    await close_client()
    print("\nDEDUP+FORMAT OK")


if __name__ == "__main__":
    asyncio.run(main())
