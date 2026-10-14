#!/usr/bin/env python3
"""Zero-dependency live probe of the NEW academic APIs being added.

Captures real response schemas for PubMed (NCBI E-utilities), DBLP,
OpenCitations, bioRxiv/medRxiv and CORE so the providers are built against
reality rather than assumptions (per AGENTS.md). Saves samples to
scripts/_probe_out/ and prints compact key maps.

Run: python scripts/probe_apis3.py
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "_probe_out"
OUT.mkdir(exist_ok=True)

EMAIL = "scholar-mcp@example.com"
UA = f"athenaeum-mcp-probe/0.1 (mailto:{EMAIL})"

DOI_THRIVING = "10.1177/0149206311425615"  # Porath et al. 2012 (well cited, in COCI)
TERM = "technostress"


def fetch(url: str, headers: dict | None = None, timeout: int = 40) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "") if e.headers else ""
    except Exception as e:  # noqa: BLE001
        return -1, str(e).encode(), ""


def keymap(obj, depth=0, max_depth=3, max_items=10):
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
                if len(sample) > 80:
                    sample = sample[:80] + "..."
                out += pad + f"{k}: {t} = {sample}\n"
    elif isinstance(obj, list):
        out += pad + f"[{len(obj)} items]\n"
        if obj:
            out += keymap(obj[0], depth + 1, max_depth, max_items)
    return out


def section(title: str):
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def probe_json(label: str, url: str, save_as: str, headers=None):
    status, body, ctype = fetch(url, headers)
    print(f"\n--- {label}")
    print(f"URL: {url}")
    print(f"HTTP {status}  ({ctype})  {len(body)} bytes")
    if status != 200:
        print("BODY:", body[:400])
        return None
    (OUT / save_as).write_bytes(body)
    try:
        data = json.loads(body)
    except Exception as e:  # noqa: BLE001
        print("JSON parse error:", e)
        print(body[:400])
        return None
    print(keymap(data))
    return data


def probe_raw(label: str, url: str, save_as: str, headers=None, show=600):
    status, body, ctype = fetch(url, headers)
    print(f"\n--- {label}")
    print(f"URL: {url}")
    print(f"HTTP {status}  ({ctype})  {len(body)} bytes")
    if status == 200:
        (OUT / save_as).write_bytes(body)
    print("HEAD:", body[:show])
    return status, body


# --------------------------------------------------------------------------- #
# 1. PubMed (NCBI E-utilities)
# --------------------------------------------------------------------------- #
section("1. PubMed / NCBI E-utilities")
eutils = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
esearch = probe_json(
    "esearch (json)",
    f"{eutils}/esearch.fcgi?db=pubmed&term={urllib.parse.quote(TERM)}&retmode=json&retmax=5&sort=relevance",
    "pubmed_esearch.json",
)
pmids = []
if esearch:
    pmids = (esearch.get("esearchresult") or {}).get("idlist") or []
    print("PMIDs:", pmids)

if pmids:
    ids = ",".join(pmids[:3])
    probe_json(
        "esummary (json)",
        f"{eutils}/esummary.fcgi?db=pubmed&id={ids}&retmode=json",
        "pubmed_esummary.json",
    )
    probe_raw(
        "efetch (xml, abstract)",
        f"{eutils}/efetch.fcgi?db=pubmed&id={ids}&retmode=xml&rettype=abstract",
        "pubmed_efetch.xml",
        show=1500,
    )

# --------------------------------------------------------------------------- #
# 2. DBLP
# --------------------------------------------------------------------------- #
section("2. DBLP")
probe_json(
    "DBLP publ search (json)",
    f"https://dblp.org/search/publ/api?q={urllib.parse.quote('transformer attention')}&format=json&h=5",
    "dblp_search.json",
)

# --------------------------------------------------------------------------- #
# 3. OpenCitations
# --------------------------------------------------------------------------- #
section("3. OpenCitations")
probe_json(
    "COCI references (works this DOI cites)",
    f"https://opencitations.net/index/api/v1/references/{DOI_THRIVING}",
    "oc_references.json",
)
probe_json(
    "COCI citations (works citing this DOI)",
    f"https://opencitations.net/index/api/v1/citations/{DOI_THRIVING}",
    "oc_citations.json",
)
probe_json(
    "Meta metadata (title/authors/venue)",
    f"https://opencitations.net/meta/api/v1/metadata/doi:{DOI_THRIVING}",
    "oc_meta.json",
)
probe_json(
    "Index citation-count",
    f"https://opencitations.net/index/api/v1/citation-count/{DOI_THRIVING}",
    "oc_count.json",
)

# --------------------------------------------------------------------------- #
# 4. bioRxiv / medRxiv
# --------------------------------------------------------------------------- #
section("4. bioRxiv / medRxiv")
recent = probe_json(
    "biorxiv recent (discover a real DOI)",
    "https://api.biorxiv.org/details/biorxiv/2021-01-01/2021-01-05/0",
    "biorxiv_recent.json",
)
bio_doi = None
if recent:
    coll = recent.get("collection") or []
    if coll:
        bio_doi = coll[0].get("doi")
        print("discovered bioRxiv DOI:", bio_doi)
if bio_doi:
    probe_json(
        "biorxiv details by DOI",
        f"https://api.biorxiv.org/details/biorxiv/{bio_doi}",
        "biorxiv_details.json",
    )

# --------------------------------------------------------------------------- #
# 5. CORE (expected 401 without a key)
# --------------------------------------------------------------------------- #
section("5. CORE v3 (expect 401 without key)")
probe_raw(
    "CORE search without key",
    f"https://api.core.ac.uk/v3/search/works?q={urllib.parse.quote(TERM)}&limit=2",
    "core_nokey.json",
    show=400,
)

print("\nPROBE DONE. Samples saved under scripts/_probe_out/")
