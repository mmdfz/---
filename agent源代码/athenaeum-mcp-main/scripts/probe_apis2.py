#!/usr/bin/env python3
"""Deep probe #2: nail exact field names against verified real IDs."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "_probe_out"
OUT.mkdir(exist_ok=True)
EMAIL = "scholar-mcp@example.com"
UA = f"scholar-mcp-probe/0.1 (mailto:{EMAIL})"


def get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), ""
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode(), ""


def gj(url, headers=None):
    s, b, _ = get(url, headers)
    if s != 200:
        return s, None
    try:
        return s, json.loads(b)
    except Exception:  # noqa: BLE001
        return s, None


print("### 1. OpenAlex work W2150527468 — full top-level keys")
s, work = gj(f"https://api.openalex.org/works/W2150527468?mailto={EMAIL}")
print("HTTP", s)
if work:
    (OUT / "oa_work_full.json").write_text(json.dumps(work, indent=2), encoding="utf-8")
    print("TITLE:", work.get("title"))
    print("DOI:", work.get("doi"))
    print("TOP KEYS:", sorted(work.keys()))
    print("\nopen_access:", json.dumps(work.get("open_access"), indent=2))
    print("\nprimary_location keys:", sorted((work.get("primary_location") or {}).keys()))
    pl = work.get("primary_location") or {}
    print("  source:", json.dumps(pl.get("source"), indent=2)[:500])
    print("  pdf_url:", pl.get("pdf_url"), "| landing:", pl.get("landing_page_url"))
    print("\nbest_oa_location:", json.dumps(work.get("best_oa_location"), indent=2)[:600])
    print("\nauthorships[0]:", json.dumps((work.get("authorships") or [{}])[0], indent=2)[:700])
    print("\nbiblio:", json.dumps(work.get("biblio"), indent=2))
    print("primary_topic:", json.dumps(work.get("primary_topic"), indent=2)[:500])
    print("referenced_works count:", len(work.get("referenced_works") or []))
    print("is_retracted:", work.get("is_retracted"), "| is_paratext:", work.get("is_paratext"))
    print("type:", work.get("type"), "| cited_by_count:", work.get("cited_by_count"))
    print("locations count:", len(work.get("locations") or []))
    print("abstract_inverted_index present:", "abstract_inverted_index" in work)
    print("ids:", json.dumps(work.get("ids"), indent=2))
    real_doi = (work.get("doi") or "").replace("https://doi.org/", "")

    print("\n### 2. OpenAlex single work via doi: prefix")
    s2, w2 = gj(f"https://api.openalex.org/works/doi:{real_doi}?mailto={EMAIL}")
    print("doi: prefix HTTP", s2, "| title:", (w2 or {}).get("title"))

    print("\n### 3. Crossref work for the real DOI")
    sc, cw = gj(f"https://api.crossref.org/works/{real_doi}?mailto={EMAIL}")
    print("Crossref HTTP", sc)
    if cw:
        msg = cw["message"]
        (OUT / "crossref_work_full.json").write_text(json.dumps(msg, indent=2), encoding="utf-8")
        print("Crossref TOP KEYS:", sorted(msg.keys()))
        print("title:", msg.get("title"))
        print("container-title:", msg.get("container-title"))
        print("author[0]:", json.dumps((msg.get("author") or [{}])[0], indent=2))
        print("issued:", json.dumps(msg.get("issued")))
        print("reference-count:", msg.get("reference-count"), "| is-referenced-by-count:", msg.get("is-referenced-by-count"))

    print("\n### 4. Crossref TRANSFORM endpoint (reliable citation formatting)")
    for mime, fn in [
        ("application/x-bibtex", "x_bibtex.txt"),
        ("text/x-bibliography; style=apa", "x_apa.txt"),
        ("text/x-bibliography; style=modern-language-association", "x_mla.txt"),
        ("text/x-bibliography; style=chicago-author-date", "x_chicago.txt"),
        ("text/x-bibliography; style=vancouver", "x_vancouver.txt"),
        ("application/x-research-info-systems", "x_ris.txt"),
    ]:
        st, bd, ct = get(
            f"https://api.crossref.org/works/{real_doi}/transform/{mime.split(';')[0]}",
            headers={"Accept": mime},
        )
        label = mime.split("style=")[-1] if "style=" in mime else mime
        print(f"  [{label}] HTTP {st} ({ct[:40]}): {bd[:120].decode('utf-8','replace').strip()!r}")
        if st == 200:
            (OUT / fn).write_bytes(bd)

print("\n### 5. OpenAlex source summary_stats (venue validation metrics)")
s, src = gj(f"https://api.openalex.org/sources/issn:0021-9010?mailto={EMAIL}")
if src:
    (OUT / "oa_source_full.json").write_text(json.dumps(src, indent=2), encoding="utf-8")
    print("TOP KEYS:", sorted(src.keys()))
    print("summary_stats:", json.dumps(src.get("summary_stats"), indent=2))
    print("is_oa:", src.get("is_oa"), "| is_in_doaj:", src.get("is_in_doaj"), "| type:", src.get("type"))
    print("works_count:", src.get("works_count"), "| host_org:", src.get("host_organization_name"))
    print("apc_usd:", src.get("apc_usd"), "| societies:", src.get("societies"))

print("\n### 6. DOAJ with a real OA journal (PLoS ONE 1932-6203)")
s, doaj = gj("https://doaj.org/api/v2/search/journals/issn:1932-6203")
print("HTTP", s, "| total:", (doaj or {}).get("total"))
if doaj and doaj.get("results"):
    r0 = doaj["results"][0]
    (OUT / "doaj_full.json").write_text(json.dumps(r0, indent=2), encoding="utf-8")
    print("bibjson keys:", sorted((r0.get("bibjson") or {}).keys()))
    bj = r0.get("bibjson", {})
    print("title:", bj.get("title"), "| seal:", bj.get("boai"), bj.get("seal"))

print("\n### 7. Europe PMC core result — full keys + citations endpoint")
s, epmc = gj("https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=technostress&format=json&pageSize=1&resultType=core")
if epmc:
    r0 = epmc["resultList"]["result"][0]
    (OUT / "epmc_full.json").write_text(json.dumps(r0, indent=2), encoding="utf-8")
    print("TOP KEYS:", sorted(r0.keys()))
    print("id/source:", r0.get("id"), r0.get("source"), "| doi:", r0.get("doi"))
    print("isOpenAccess:", r0.get("isOpenAccess"), "| citedByCount:", r0.get("citedByCount"))

print("\nDONE.")
