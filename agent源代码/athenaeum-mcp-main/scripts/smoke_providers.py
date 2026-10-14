"""Live smoke test of the provider layer. Run: python scripts/smoke_providers.py"""
import asyncio

from athenaeum_mcp.http_client import close_client
from athenaeum_mcp.providers import arxiv, crossref, europepmc, openalex

DOI = "10.1128/jb.175.12.3749-3756.1993"


async def main():
    print("== OpenAlex search ==")
    works = await openalex.search("technostress", limit=3)
    for w in works:
        print(f"  [{w.year}] {w.title[:60]!r} doi={w.doi} oa={w.is_oa} cites={w.cited_by_count} prov={w.providers}")
    print("  authors[0]:", works[0].authors[0].model_dump(exclude_none=True) if works and works[0].authors else None)
    print("  abstract len:", len(works[0].abstract or "") if works else 0)

    print("== OpenAlex get_work ==")
    w = await openalex.get_work(DOI)
    print("  title:", w.title if w else None, "| venue:", w.venue if w else None, "| pages:", w.pages if w else None)

    print("== OpenAlex citations (top by cites) ==")
    cites = await openalex.get_citations(DOI, limit=3)
    for c in cites:
        print(f"  cites: [{c.year}] {c.title[:55]!r} ({c.cited_by_count})")

    print("== OpenAlex references ==")
    refs = await openalex.get_references(DOI, limit=3)
    for r in refs:
        print(f"  ref: [{r.year}] {r.title[:55]!r}")

    print("== Crossref search + bibtex ==")
    cr = await crossref.search("thriving at work measurement", limit=2)
    for c in cr:
        print(f"  [{c.year}] {c.title[:55]!r} doi={c.doi}")
    bib = await crossref.format(DOI, "bibtex")
    print("  bibtex:", (bib or "")[:90].replace("\n", " "))

    print("== arXiv search ==")
    ax = await arxiv.search("technostress", limit=2)
    for a in ax:
        print(f"  [{a.year}] {a.title[:55]!r} arxiv={a.arxiv_id} pdf={bool(a.pdf_url)}")

    print("== Europe PMC search ==")
    ep = await europepmc.search("technostress nurses", limit=2)
    for e in ep:
        print(f"  [{e.year}] {e.title[:55]!r} oa={e.is_oa} pmid={e.pmid}")

    print("== OpenAlex source (venue metrics) ==")
    v = await openalex.get_source("0021-9010")
    if v:
        print(f"  {v.name}: IF2yr={v.impact_2yr:.2f} h={v.h_index} doaj={v.is_in_doaj} works={v.works_count}")

    await close_client()
    print("\nSMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
