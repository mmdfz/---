#!/usr/bin/env python3
"""Zero-dependency live probe of free academic APIs.

Captures real response schemas so the MCP server is built against reality.
Saves full JSON/XML samples to scripts/_probe_out/ and prints compact key maps.
Run: python scripts/probe_apis.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "_probe_out"
OUT.mkdir(exist_ok=True)

EMAIL = "scholar-mcp@example.com"  # polite-pool placeholder
UA = f"scholar-mcp-probe/0.1 (mailto:{EMAIL})"

# Relevant, stable test fixtures (tied to the user's own research where possible)
DOI_THRIVING = "10.1177/0149206311425615"  # Porath et al. 2012, Thriving at Work
DOI_OA = "10.1371/journal.pone.0000308"     # PLoS ONE, guaranteed OA (Unpaywall)
ISSN_JAP = "0021-9010"                       # Journal of Applied Psychology
TERM = "technostress"


def fetch(url: str, headers: dict | None = None, timeout: int = 30) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "") if e.headers else ""
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode(), ""


def keymap(obj, depth=0, max_depth=3, max_items=6):
    """Compact recursive key/type map for quick schema understanding."""
    pad = "  " * depth
    if depth > max_depth:
        return pad + "...\n"
    out = ""
    if isinstance(obj, dict):
        for i, (k, v) in enumerate(obj.items()):
            if i >= max_items:
                out += pad + f"... (+{len(obj) - max_items} more keys)\n"
                break
            t = type(v).__name__
            if isinstance(v, (dict, list)):
                out += pad + f"{k}: {t}\n" + keymap(v, depth + 1, max_depth, max_items)
            else:
                sample = repr(v)
                if len(sample) > 70:
                    sample = sample[:70] + "..."
                out += pad + f"{k}: {t} = {sample}\n"
    elif isinstance(obj, list):
        out += pad + f"[{len(obj)} items]\n"
        if obj:
            out += keymap(obj[0], depth + 1, max_depth, max_items)
    return out


def save(name: str, data: bytes):
    (OUT / name).write_bytes(data)


def section(title: str):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def probe_json(label: str, url: str, save_as: str, headers=None, dig=None):
    status, body, ctype = fetch(url, headers)
    print(f"\n--- {label}")
    print(f"URL: {url}")
    print(f"HTTP {status}  ({ctype})  {len(body)} bytes")
    if status != 200:
        print("BODY:", body[:300])
        return None
    save(save_as, body)
    try:
        data = json.loads(body)
    except Exception as e:  # noqa: BLE001
        print("JSON parse error:", e)
        print(body[:300])
        return None
    target = data
    if dig:
        for step in dig:
            if isinstance(target, dict):
                target = target.get(step, {})
            elif isinstance(target, list) and isinstance(step, int) and len(target) > step:
                target = target[step]
    print(keymap(target))
    return data


def main():
    section("1. OpenAlex — search works")
    probe_json(
        "OpenAlex works search",
        f"https://api.openalex.org/works?search={TERM}&per-page=2&mailto={EMAIL}",
        "openalex_search.json",
        dig=["results", 0],
    )

    section("2. OpenAlex — single work by DOI (references, OA, concepts)")
    probe_json(
        "OpenAlex single work",
        f"https://api.openalex.org/works/https://doi.org/{DOI_THRIVING}?mailto={EMAIL}",
        "openalex_work.json",
    )

    section("3. OpenAlex — citing works (incoming citations)")
    probe_json(
        "OpenAlex cited_by",
        f"https://api.openalex.org/works?filter=cites:W2150527468&per-page=1&mailto={EMAIL}",
        "openalex_citedby.json",
        dig=["meta"],
    )

    section("4. OpenAlex — source/venue (metrics for validation)")
    probe_json(
        "OpenAlex source",
        f"https://api.openalex.org/sources/issn:{ISSN_JAP}?mailto={EMAIL}",
        "openalex_source.json",
    )

    section("5. OpenAlex — author")
    probe_json(
        "OpenAlex author search",
        f"https://api.openalex.org/authors?search=Christine%20Porath&per-page=1&mailto={EMAIL}",
        "openalex_author.json",
        dig=["results", 0],
    )

    section("6. Crossref — search works")
    probe_json(
        "Crossref works search",
        f"https://api.crossref.org/works?query={TERM}&rows=2&mailto={EMAIL}",
        "crossref_search.json",
        dig=["message", "items", 0],
    )

    section("7. Crossref — single work by DOI (references)")
    probe_json(
        "Crossref single work",
        f"https://api.crossref.org/works/{DOI_THRIVING}?mailto={EMAIL}",
        "crossref_work.json",
        dig=["message"],
    )

    section("8. Crossref — content negotiation (BibTeX + APA)")
    for style, accept, fn in [
        ("BibTeX", "application/x-bibtex", "crossref_bibtex.txt"),
        ("APA", "text/x-bibliography; style=apa", "crossref_apa.txt"),
        ("RIS", "application/x-research-info-systems", "crossref_ris.txt"),
    ]:
        status, body, ctype = fetch(
            f"https://doi.org/{DOI_THRIVING}", headers={"Accept": accept}
        )
        print(f"\n--- Crossref content-negotiation {style}: HTTP {status} ({ctype})")
        if status == 200:
            save(fn, body)
            print(body.decode("utf-8", "replace")[:400])
        else:
            print(body[:200])

    section("9. arXiv — Atom search")
    status, body, ctype = fetch(
        f"http://export.arxiv.org/api/query?search_query=all:{TERM}&max_results=2"
    )
    print(f"HTTP {status} ({ctype}) {len(body)} bytes")
    if status == 200:
        save("arxiv_search.xml", body)
        print(body.decode("utf-8", "replace")[:1200])

    section("10. Semantic Scholar — paper search (+TLDR, fields)")
    probe_json(
        "S2 search",
        "https://api.semanticscholar.org/graph/v1/paper/search?query="
        + TERM
        + "&limit=2&fields=title,abstract,year,authors,citationCount,influentialCitationCount,tldr,externalIds,openAccessPdf,venue,publicationTypes",
        "s2_search.json",
        dig=["data", 0],
    )

    section("11. Semantic Scholar — paper detail w/ references & citations")
    probe_json(
        "S2 paper detail",
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{DOI_THRIVING}"
        "?fields=title,year,citationCount,references.title,references.year,citations.title,citations.year,tldr",
        "s2_paper.json",
    )

    section("12. Europe PMC — search")
    probe_json(
        "Europe PMC search",
        f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={TERM}&format=json&pageSize=2&resultType=core",
        "europepmc_search.json",
        dig=["resultList", "result", 0],
    )

    section("13. Unpaywall — OA status by DOI (email required)")
    probe_json(
        "Unpaywall",
        f"https://api.unpaywall.org/v2/{DOI_OA}?email={EMAIL}",
        "unpaywall.json",
    )

    section("14. DOAJ — journal by ISSN (source validation)")
    probe_json(
        "DOAJ journal",
        f"https://doaj.org/api/v2/search/journals/issn:{ISSN_JAP}",
        "doaj_journal.json",
        dig=["results", 0],
    )

    section("15. OpenCitations COCI — references & citations by DOI")
    for kind in ("references", "citations"):
        probe_json(
            f"OpenCitations {kind}",
            f"https://opencitations.net/index/coci/api/v1/{kind}/{DOI_THRIVING}",
            f"opencitations_{kind}.json",
            dig=[0],
        )

    section("16. Crossref journals — by ISSN (venue validation)")
    probe_json(
        "Crossref journal",
        f"https://api.crossref.org/journals/{ISSN_JAP}?mailto={EMAIL}",
        "crossref_journal.json",
        dig=["message"],
    )

    print("\n\nAll raw samples saved to:", OUT)


if __name__ == "__main__":
    sys.exit(main())
