# AGENTS.md — Athenaeum

Guidance for AI coding agents working **on the Athenaeum codebase** (not the
end-user docs — that's [README.md](README.md)). Read this first if you open
`athenaeum-mcp/` as the workspace root.

## What this project is

Athenaeum is a **Model Context Protocol (MCP) server** that gives AI agents a
unified, 100% free toolbox for academic research: meta-search across scholarly
databases, metadata, citation graphs, source/rigor validation, PDF full-text
reading, bibliography export, and Zotero integration. It is built only on free,
open APIs and needs no API key to run.

## Environment & commands

- **Python ≥ 3.10.** A self-contained virtualenv lives in `.venv/`.
- Use the venv interpreter directly (do not assume an activated shell):
  - Windows: `.\.venv\Scripts\python.exe`
  - macOS/Linux: `./.venv/bin/python`

```powershell
# Install (editable) + dev deps
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# Offline tests (fast; no network) — run these for almost every change
.\.venv\Scripts\python.exe -m pytest -m "not live"

# Live tests (hit real APIs; slower, network-dependent)
.\.venv\Scripts\python.exe -m pytest -m live

# Run the server over stdio
.\.venv\Scripts\python.exe -m athenaeum_mcp.server

# Configure/remove the server in MCP clients
.\.venv\Scripts\python.exe -m athenaeum_mcp.configurator status
.\.venv\Scripts\python.exe -m athenaeum_mcp.configurator install --dry-run
```

Always run `-m "not live"` before declaring a change done. Run the matching
`scripts/smoke_*.py` when you touch a subsystem (they hit live APIs and print
human-readable output).

## Architecture (layers, top to bottom)

```
server.py        MCP tool definitions (Pydantic inputs, docstrings, annotations).
                 Thin — delegates to service.py. Tool names are athenaeum_*.
service.py       Business logic. Returns plain Work/Venue/dict objects.
                 Orchestrates providers, dedup, analysis. No MCP/Pydantic here.
providers/       One module per data source. Each maps a raw API response to the
                 normalized models. base.Provider is the shared interface.
dedup.py         Cluster + merge multi-provider results (DOI then fuzzy title),
                 RRF ranking lives in service.meta_search.
analysis.py      Rule-based rigor cues + directional-sentiment heuristic +
                 corpus consensus. Pure functions, no I/O.
formatting.py    8 citation styles + CSL-JSON. Pure, local, deterministic.
pdf.py           Multi-source full-text fetch + extraction (SSRF-guarded).
render.py        Markdown/JSON output helpers.
models.py        Normalized Work / Venue / AuthorProfile (Pydantic v2).
http_client.py   Shared async HTTP: per-host rate limiting, disk cache, retries,
                 browser-header downloads. All network goes through here.
config.py        Env-based settings (all optional). Cached singleton.
utils.py         Identifier detection/normalization, text cleaning.
configurator.py  Client detection + install/uninstall wizard (separate concern).
```

Data flow for a tool call: `server.athenaeum_x` → `service.x` →
`providers.*` (via `http_client`) → `dedup`/`analysis`/`formatting` → `render` →
string back to the client.

## Conventions (match the existing code)

- **Tool naming:** every MCP tool is `athenaeum_<verb>[_<noun>]` (snake_case).
  Keep the service-layer function names short (`meta_search`, `get_work`).
- **Normalized schema:** every provider must map into `models.Work`. Never leak a
  raw provider dict above the provider layer.
- **All network calls go through `http_client.get_client()`** so they share rate
  limiting and caching. Don't use `httpx`/`urllib` directly in providers.
- **Graceful degradation:** a provider failing must never sink a whole operation.
  Wrap optional-provider calls so they return empty/None on error (see
  `service.meta_search._safe`).
- **Response formats:** data tools accept `response_format: "markdown" | "json"`.
  Markdown is the human default; JSON is complete/machine-readable.
- **Tool annotations:** read-only tools use `_READ_ONLY`; tools that write
  (Zotero, file export) use `_WRITE`.
- **Async everywhere** for I/O. Use `asyncio.gather` for independent calls.
- **Pydantic v2 idioms** (`model_config`, `field_validator`, `model_dump`).
- Type hints throughout; docstrings on every tool (they become the MCP
  description the model reads — keep them accurate and example-rich).

## Honesty & transparency (a core value here)

This project deliberately reports *evidence and caveats*, never verdicts.
Preserve this when editing:

- `validate_source` and `research_consensus` must keep their **disclaimers** and
  describe heuristics as heuristics. Rigor cues come from the **abstract only**;
  their absence is **not** evidence of poor quality — say so.
- `read_pdf` must keep its **per-source `attempts` log** and disclose known hard
  limits (JS/Cloudflare blocks like some MDPI hosts → HTTP 403; scanned PDFs need
  OCR; paywalled-with-no-repo can't be read). Don't silently swallow failures.
- Don't add scraping of sources whose ToS forbid it (e.g. Google Scholar). Use
  the open APIs.

## Adding things

**A new provider:** create `providers/<name>.py` with a `Provider` subclass that
maps responses to `Work`; register it in `providers/__init__.py`; add it to
`SEARCH_PROVIDERS` only if it does free-text search; gate it in
`default_search_providers()` if it needs a key. Probe the real API first (see
`scripts/probe_apis*.py`) — build against captured schemas, not assumptions. If
the provider needs a key, token or email, read it via `config.py`, expose an
`available()`/`has_key` gate, and **write a maintained setup guide** at
`docs/providers/<name>.md` and list it in `docs/providers/README.md` (every
auth/setup provider must have one).

The current roster: OpenAlex, Crossref, arXiv, Europe PMC, PubMed, DBLP and CORE
are search providers (CORE gated on `CORE_API_KEY`, DBLP opt-in only);
OpenCitations (citation fallback) and bioRxiv/medRxiv (preprint full text) are
non-search providers wired into `service.py`; DOAJ/Unpaywall/Zotero are
special-purpose.

**A new tool:** add a thin `@mcp.tool`-decorated `athenaeum_*` function in
`server.py` that delegates to a new `service.py` function; write the heuristics/
logic in `service.py` or a pure module; add offline tests; add a `scripts/smoke_*`
check if it hits the network.

## Testing notes

- Offline tests (`-m "not live"`) must stay deterministic and network-free.
- Live tests are marked `@pytest.mark.live`; pick **stable** fixtures (old,
  well-cited DOIs) so answers don't drift.
- The configurator is fully covered offline (`tests/test_configurator.py`) using
  temp dirs — never write to real user config in tests.

## Gotchas (learned the hard way)

- **Windows file locks:** a lingering server process can lock `.venv` files
  during reinstall (`WinError 5`). Kill stray `python.exe` under this path first.
- **Console encoding:** the configurator forces UTF-8 stdout and uses ASCII
  status markers because piped Windows consoles default to cp1252.
- **JSON with BOM/comments:** client configs may have a UTF-8 BOM or JSONC
  comments. Read with `utf-8-sig` and the `_strip_jsonc` helper; never assume
  strict JSON.
- **MDPI/Cloudflare:** genuinely unfetchable server-side; this is disclosed, not
  a bug to "fix" by force.
- **OpenAlex inverted-index abstracts:** reconstruct with `utils.reconstruct_abstract`.

## Safety

- The PDF reader has an **SSRF guard** (`pdf._is_safe_url`) rejecting non-HTTP(S)
  and private/loopback hosts, plus a download size cap. Keep both if you touch it.
- The setup wizard **backs up every file** before editing and is reversible via
  `uninstall`. Preserve that guarantee.
