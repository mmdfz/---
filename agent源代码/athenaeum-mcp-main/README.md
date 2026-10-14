# Athenaeum

**A unified, 100% free Model Context Protocol (MCP) server for academic research.**

Athenaeum gives any MCP-capable AI agent (VS Code GitHub Copilot, Claude
Desktop/Code, Cursor, Windsurf, OpenAI Codex, OpenCode, Gemini CLI…) one
effortless, vendor-neutral toolbox for literature work: meta-search across many
scholarly databases at once, metadata retrieval, citation-graph traversal,
source/credibility validation, open-access PDF discovery **and full-text
reading**, bibliography generation, and one-click export to **Zotero** or a
`.bib`/`.ris`/CSL-JSON file — inspired by Crossref and the meta-search
philosophy of SearXNG.

It is built entirely on **free, open scholarly APIs** and needs **no API key and
no signup** to run. An email (and optional keys) only unlock faster "polite
pool" rate limits and a couple of optional integrations.

> *An athenaeum is a temple of Athena — historically, a library and institution
> of learning. This one lives in your editor.*

---

## One-step setup

Athenaeum ships with a wizard that builds a self-contained Python environment
**and writes the correct MCP configuration into every AI client you have** — no
manual JSON editing.

### Windows

Double-click **`setup.bat`** (or run it in a terminal). That's it.

```powershell
# or, explicitly:
.\install.ps1                     # project scope (default), auto-detected clients
.\install.ps1 -Clients vscode cursor
.\install.ps1 -Scope user         # global config instead
.\install.ps1 -DryRun             # preview without writing
```

### macOS / Linux

```bash
chmod +x install.sh
./install.sh                      # project scope (default), auto-detected clients
./install.sh --clients vscode cursor
./install.sh --scope user
./install.sh --dry-run
```

The installer is **idempotent** (safe to re-run) and **non-destructive** (it
merges into existing config and backs up every file it touches).

### Uninstall (embedded in the same scripts)

```powershell
.\install.ps1 -Uninstall          # remove Athenaeum from all client configs
.\install.ps1 -Uninstall -Purge   # …and delete the virtual environment too
.\uninstall.bat                   # convenience wrapper
```
```bash
./install.sh --uninstall
./install.sh --uninstall --purge
```

Backups are created before any change, so removal is always reversible.

### Supported clients & scope

By default the wizard installs at **project scope** (config lives in your
workspace, so the server is available exactly where you're researching) and
targets the clients it detects. Use `--scope user` for global config.

| Client | Project scope | User scope | Config written |
|---|:---:|:---:|---|
| VS Code (Copilot) | ✓ | ✓ | `.vscode/mcp.json` |
| Claude Code | ✓ | ✓ | `.mcp.json` |
| Cursor | ✓ | ✓ | `.cursor/mcp.json` |
| OpenCode | ✓ | ✓ | `opencode.json` |
| Gemini CLI | ✓ | ✓ | `.gemini/settings.json` |
| Claude Desktop | — | ✓ | `claude_desktop_config.json` |
| Windsurf | — | ✓ | `mcp_config.json` |
| OpenAI Codex | — | ✓ | `~/.codex/config.toml` |

Check what's detected and where Athenaeum is installed:

```
python -m athenaeum_mcp.configurator status
```

---

## Tools

All tools are namespaced `athenaeum_*` so they sit cleanly alongside other MCP
servers.

### Search
- **`athenaeum_search`** — the flagship. Fans a query out to several providers in
  parallel (OpenAlex, Crossref, arXiv, Europe PMC and PubMed by default),
  deduplicates by DOI + fuzzy title, merges records, and ranks them with
  reciprocal rank fusion. Filters: year range, open-access-only, provider
  subset (add `dblp` for computer science), sort by relevance or citations.
- **`athenaeum_search_provider`** — query a single provider directly
  (`openalex` | `crossref` | `arxiv` | `europepmc` | `pubmed` |
  `semantic_scholar` | `dblp` | `core`).

### Metadata & full text
- **`athenaeum_get_work`** — full normalized metadata for any identifier
  (DOI, OpenAlex ID, arXiv ID, PMID), enriched across providers.
- **`athenaeum_find_pdf`** — list every free full-text candidate (repositories,
  PMC, publisher, Unpaywall), most-accessible first.
- **`athenaeum_read_pdf`** — **download an open-access PDF and extract its text**,
  so the agent can read a paper's actual content, not just the abstract. Tries
  *all* candidate sources with browser headers and `citation_pdf_url` recovery,
  and returns a transparent per-source attempt log on failure.

### Citation graph
- **`athenaeum_get_references`** — works **cited by** a paper.
- **`athenaeum_get_citations`** — works **that cite** a paper.
- **`athenaeum_get_related`** — related / recommended works.
- **`athenaeum_citation_graph`** — traverse an *N*-hop citation network.

### Authors & venues
- **`athenaeum_get_author`** — author profile and metrics (h-index, citations).
- **`athenaeum_get_venue`** — venue profile, metrics, OA & DOAJ status.

### Citations, export & Zotero
- **`athenaeum_format_citation`** — one work → `bibtex` | `ris` | `apa` | `mla` |
  `chicago` | `vancouver` | `harvard` | `ieee`.
- **`athenaeum_build_bibliography`** — many identifiers → a combined bibliography.
- **`athenaeum_export`** — write a set of references to a **`.bib` / `.ris` /
  CSL-JSON** file (the formats Zotero, Mendeley, EndNote and Pandoc import).
- **`athenaeum_zotero_add`** — push references straight into your **Zotero**
  library (optional; needs a Zotero key).
- **`athenaeum_zotero_collections`** — list your Zotero collections.

### Validation & analysis
- **`athenaeum_validate_source`** — credibility **and rigor** check for a work:
  retraction status, venue metrics, DOAJ/Crossref indexing, cross-database
  agreement, peer-review vs preprint status, citation rate, and methodology cues
  mined from the abstract — with a transparent 0–100 score and explicit caveats.
- **`athenaeum_research_consensus`** — gauge a field's evidence strength,
  study-type mix (meta-analyses, reviews, empirical, preprints), venue quality,
  and a coarse directional lean (supporting / mixed / challenging).
- **`athenaeum_literature_review`** — assemble a starter landscape for a topic:
  seminal works, recent works, key venues and authors.

Every data tool supports `response_format: "markdown"` (default) or `"json"`.

---

## Honesty by design

Athenaeum reports **evidence and caveats, never verdicts**:

- **Validation** surfaces *signals* (metrics, indexing, retraction flags,
  peer-review status, abstract-level methodology cues) and a transparent score.
  It never claims a paper is "true" or a venue is "good". Rigor cues are read
  from the **abstract only** — their absence is *not* evidence of weak methods.
- **Consensus** is a *bibliometric* overview; its directional "lean" is a coarse
  keyword heuristic over titles/abstracts and can misclassify nuanced work.
- **PDF reading** discloses what it tried. Known hard limits: sites behind a
  JavaScript/Cloudflare challenge (notably some **MDPI** hosts) return HTTP 403
  to any non-browser client and cannot be read; scanned/image-only PDFs need OCR
  (out of scope); paywalled works without a repository copy can't be read.
- No ToS-violating scraping (e.g. Google Scholar) — only open APIs.

---

## Data sources

Every provider that needs a key or other setup has a **step-by-step, actively
maintained guide** in [`docs/providers/`](docs/providers/README.md).

| Provider | Used for | Key needed? |
|---|---|---|
| **OpenAlex** | Backbone: search, metadata, abstracts, references, citations, related works, venue & author metrics, OA locations, retraction flags | No |
| **Crossref** | DOI metadata, references, BibTeX/RIS export, journal validation | No |
| **arXiv** | Preprint search & metadata | No |
| **Europe PMC** | Biomedical / life-sciences search, abstracts, full text | No |
| **PubMed** | Biomedical & psychology search, abstracts, MeSH terms (independent index) | No (optional key lifts rate limit) |
| **DBLP** | Computer-science search (conferences, journals, arXiv/CoRR preprints) | No |
| **OpenCitations** | Independent open citation index — references/citations fallback | No (optional token) |
| **bioRxiv / medRxiv** | Preprint metadata + full-text PDF for `10.1101/…` DOIs | No |
| **DOAJ** | Open-access journal legitimacy (used in validation) | No |
| **CORE** | Largest open-access full-text aggregator (extra readable PDFs) | **Yes — free key** |
| **Semantic Scholar** | TLDR summaries, influential-citation counts *(best-effort)* | Optional key |
| **Unpaywall** | Extra open-access PDF discovery *(optional)* | Real email |
| **Zotero** | Push references into your library *(optional)* | Zotero key |

The meta-search uses OpenAlex, Crossref, arXiv, Europe PMC and PubMed by
default; CORE and Semantic Scholar join automatically once their key is set, and
DBLP is available on request with `providers=["dblp"]`. OpenCitations and
bioRxiv/medRxiv power citation-graph and full-text fallbacks behind the scenes.

---

## Example prompts to your agent

- *"Find the most-cited papers on technostress and thriving at work since 2018."*
- *"Get the metadata and read the full PDF for arXiv:2311.07072."*
- *"Give me an APA citation for DOI 10.1177/0149206311425615, and a BibTeX entry."*
- *"Export these five DOIs to a BibTeX file in my project."*
- *"Add this paper to my Zotero library under the 'AI stress' collection."*
- *"Is this journal legitimate? Validate the source for DOI 10.xxxx/yyyy."*
- *"How settled is the research on whether remote work reduces productivity?"*
- *"Map the citation graph two hops out from this paper."*
- *"Do a literature landscape for 'AI role shift and cognitive weariness'."*

---

## Optional configuration

Copy `.env.example` to `.env` and fill in what you want. **Everything is
optional** — the core providers work with no configuration at all. The installer
creates `.env` for you automatically. Every credential below has a maintained
setup guide in [`docs/providers/`](docs/providers/README.md).

```ini
ATHENAEUM_EMAIL=you@example.com     # polite pool (faster) + enables Unpaywall
NCBI_API_KEY=...                    # optional: PubMed 3→10 req/s (works without)
CORE_API_KEY=...                    # enables the CORE full-text provider
OPENCITATIONS_ACCESS_TOKEN=...      # optional: higher OpenCitations rate limit
SEMANTIC_SCHOLAR_API_KEY=...        # lifts Semantic Scholar rate limits
ATHENAEUM_ENABLE_UNPAYWALL=true     # needs a real email above
ZOTERO_API_KEY=...                  # enables athenaeum_zotero_add
ZOTERO_LIBRARY_ID=123456
```

The `.env` is discovered automatically regardless of which directory the client
launches the server from.

---

## Manual run / test

```powershell
# Start the server (stdio)
.\.venv\Scripts\python.exe -m athenaeum_mcp.server

# Unit tests (offline)
.\.venv\Scripts\python.exe -m pytest -m "not live"

# Include live API smoke tests
.\.venv\Scripts\python.exe -m pytest
```

---

## Project layout

```
athenaeum-mcp/
├── setup.bat / install.ps1 / install.sh   # one-step install (+ embedded uninstall)
├── uninstall.bat                          # convenience uninstall wrapper
├── AGENTS.md                              # guide for agents working ON the code
├── docs/providers/                        # maintained setup guides (keys/auth)
├── src/athenaeum_mcp/
│   ├── server.py          # FastMCP server: the athenaeum_* tools
│   ├── service.py         # business logic (meta-search, graph, validation…)
│   ├── configurator.py    # client detection + install/uninstall wizard
│   ├── providers/         # one module per data source (+ zotero)
│   ├── pdf.py             # multi-source PDF fetch + extraction (SSRF-guarded)
│   ├── analysis.py        # rigor cues + sentiment/consensus heuristics
│   ├── dedup.py           # cluster + merge (DOI + fuzzy title, RRF ranking)
│   ├── formatting.py      # 8 citation styles + CSL-JSON
│   ├── render.py          # Markdown / JSON output
│   ├── models.py          # normalized Work / Venue / Author
│   ├── http_client.py     # rate limiting + disk cache + retries
│   ├── config.py          # env-based settings
│   └── utils.py           # identifier + text helpers
├── tests/                 # offline unit tests + marked live tests
└── scripts/               # API probes + smoke tests (dev utilities)
```

---

## Design notes

- **Normalized schema.** Every provider's records map to one `Work` model so
  results compose cleanly. Merged records keep a `providers` provenance list.
- **Politeness & caching.** Per-host rate limiting and a local on-disk cache keep
  the server fast and a good citizen of these free services.
- **Graceful degradation.** If an optional provider is unconfigured or
  rate-limited, the meta-search simply proceeds with the rest.
- **Safety.** The PDF reader refuses non-HTTP(S) and private/loopback URLs
  (SSRF guard) and caps download size. The setup wizard backs up every file it
  edits.
- **Association, not magic.** Validation surfaces *signals* (metrics, indexing,
  retraction flags) and a transparent score — it never claims a paper is "true"
  or a venue is "good"; it shows you the evidence.

## License

MIT. Scholarly data is provided by the respective APIs under their own terms
(OpenAlex CC0, Crossref, arXiv, Europe PMC, DOAJ, etc.).
