"""Live smoke test of the NEW providers. Run: python scripts/smoke_new_providers.py

Hits real APIs (PubMed, DBLP, OpenCitations, bioRxiv) and prints human-readable
output. CORE is exercised only if CORE_API_KEY is set. Use to verify the
provider layer against live services after changes.
"""
import asyncio

from athenaeum_mcp import service
from athenaeum_mcp.http_client import close_client
from athenaeum_mcp.providers import biorxiv, core, dblp, opencitations, pubmed

# Stable-ish fixtures.
TERM = "technostress"
COCI_DOI = "10.1186/1756-8722-6-59"   # well covered by OpenCitations
BIORXIV_DOI = "10.1101/2020.12.30.424878"


async def main():
    print("== PubMed search ==")
    pm = await pubmed.search(TERM, limit=3)
    for w in pm:
        print(f"  [{w.year}] {(w.title or '')[:60]!r} pmid={w.pmid} doi={w.doi} "
              f"mesh={w.keywords[:2]} abs={'yes' if w.abstract else 'no'}")
    print(f"  -> {len(pm)} results; first has {len(pm[0].authors) if pm else 0} authors")

    print("\n== PubMed get_work by PMID ==")
    if pm and pm[0].pmid:
        one = await pubmed.get_work(f"pmid:{pm[0].pmid}")
        print("  resolved:", (one.title or "")[:60] if one else None)

    print("\n== DBLP search (CS) ==")
    db = await dblp.search("attention is all you need", limit=3)
    for w in db:
        print(f"  [{w.year}] {(w.title or '')[:55]!r} type={w.type} venue={w.venue} "
              f"doi={w.doi} arxiv={w.arxiv_id}")

    print("\n== OpenCitations references / citations ==")
    refs = await opencitations.get_references(COCI_DOI, limit=5)
    cites = await opencitations.get_citations(COCI_DOI, limit=5)
    count = await opencitations.citation_count(COCI_DOI)
    print(f"  references: {len(refs)} (first doi={refs[0].doi if refs else None}, "
          f"openalex={refs[0].openalex_id if refs else None})")
    print(f"  citations:  {len(cites)} (citation_count reports {count})")

    print("\n== Service citation fallback (resolves OC stubs via OpenAlex) ==")
    svc_refs = await service.get_references(COCI_DOI, limit=5)
    print(f"  service.get_references -> {len(svc_refs)}; "
          f"first title: {(svc_refs[0].title or '')[:50] if svc_refs else None!r}")

    print("\n== bioRxiv get_work ==")
    bio = await biorxiv.get_work(BIORXIV_DOI)
    if bio:
        print(f"  {bio.venue}: {(bio.title or '')[:55]!r}")
        print(f"  pdf_url: {bio.pdf_url}")
        print(f"  abstract: {'yes' if bio.abstract else 'no'}  authors: {len(bio.authors)}")

    print("\n== Meta-search includes PubMed by default ==")
    works = await service.meta_search(TERM + " nurses", limit=6)
    provs = sorted({p for w in works for p in w.providers})
    print(f"  {len(works)} merged results; providers seen: {provs}")

    print("\n== CORE (gated) ==")
    if core.available():
        cr = await core.search(TERM, limit=2)
        for w in cr:
            print(f"  [{w.year}] {(w.title or '')[:55]!r} pdf={bool(w.pdf_url)}")
    else:
        print("  CORE_API_KEY not set -> provider inactive (expected). See docs/providers/core.md")

    await close_client()
    print("\nSMOKE OK")


if __name__ == "__main__":
    asyncio.run(main())
