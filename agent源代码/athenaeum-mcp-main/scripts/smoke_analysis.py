"""Smoke-test the new analysis features against live data."""
import asyncio

from athenaeum_mcp import service
from athenaeum_mcp.http_client import close_client


async def main():
    print("=== research_consensus: technostress and job performance ===")
    r = await service.research_consensus("technostress and job performance", limit=25)
    print("  found:", r.get("found"), "| analysed:", r.get("analysed"))
    print("  evidence_strength:", r.get("evidence_strength"))
    print("  maturity:", r.get("maturity"))
    print("  year_range:", r.get("year_range"), "| recent%:", r.get("recent_share_pct"), "| oa%:", r.get("oa_share_pct"))
    print("  study_types:", {k: v for k, v in r.get("study_types", {}).items() if v})
    print("  sentiment:", r.get("sentiment"))
    print("  top_venues:", [v["venue"] for v in r.get("top_venues", [])][:3])

    print("\n=== validate_source w/ rigor: meta-analysis paper ===")
    # Nastjuk et al. 2023 technostress meta-analysis
    v = await service.validate_source("10.1080/0960085x.2022.2154712")
    print("  score:", v.get("credibility_score"), v.get("credibility_label"))
    print("  work_type:", v.get("work_type"), "| peer_reviewed:", v.get("peer_reviewed"))
    print("  rigor_signals:")
    for s in v.get("rigor_signals", []):
        print("    -", s)

    print("\n=== validate_source: arXiv preprint (should flag preprint) ===")
    v2 = await service.validate_source("arXiv:2311.07072")
    print("  work_type:", v2.get("work_type"), "| peer_reviewed:", v2.get("peer_reviewed"))
    print("  caution:", [s for s in v2.get("caution_signals", []) if "preprint" in s.lower()])

    await close_client()
    print("\nDONE")


if __name__ == "__main__":
    asyncio.run(main())
