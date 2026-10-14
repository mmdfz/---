# Provider setup guides

Athenaeum runs **100% free with no API key**. The core providers — OpenAlex,
Crossref, arXiv, Europe PMC, **PubMed**, **DBLP**, **OpenCitations** and
**bioRxiv/medRxiv** — need no credentials at all.

A few providers offer (or require) an API key, token, or other setup to unlock
additional capability or higher rate limits. **Every provider that needs
authentication or setup has a maintained guide below.** Each guide is kept up to
date with the live service; if a provider changes its signup flow or endpoints,
the corresponding guide is revised.

## Status

| Provider | Setup | Requirement | Env var(s) | Guide | Status |
|---|---|---|---|---|---|
| [CORE](core.md) | API key | **Required** to enable | `CORE_API_KEY` | [core.md](core.md) | ✅ Actively maintained |
| [PubMed / NCBI](pubmed.md) | API key | Optional (higher rate) | `NCBI_API_KEY` | [pubmed.md](pubmed.md) | ✅ Actively maintained |
| [OpenCitations](opencitations.md) | Access token | Optional (higher rate) | `OPENCITATIONS_ACCESS_TOKEN` | [opencitations.md](opencitations.md) | ✅ Actively maintained |
| [Semantic Scholar](semantic-scholar.md) | API key | Optional (lifts 429s) | `SEMANTIC_SCHOLAR_API_KEY` | [semantic-scholar.md](semantic-scholar.md) | ✅ Actively maintained |
| [Unpaywall](unpaywall.md) | Real email + flag | Optional (extra OA PDFs) | `ATHENAEUM_EMAIL`, `ATHENAEUM_ENABLE_UNPAYWALL` | [unpaywall.md](unpaywall.md) | ✅ Actively maintained |
| [Zotero](zotero.md) | API key + library | Optional (push refs) | `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, `ZOTERO_LIBRARY_TYPE` | [zotero.md](zotero.md) | ✅ Actively maintained |

> **Providers needing _no_ setup** (no guide required): OpenAlex, Crossref,
> arXiv, Europe PMC, PubMed*, DBLP, OpenCitations*, bioRxiv/medRxiv, DOAJ.
> *PubMed and OpenCitations work fully without a key; the optional credential
> only raises rate limits.*

## How configuration works

All credentials are read from environment variables, which Athenaeum also loads
from a `.env` file in the project root or current working directory (see
[`.env.example`](../../.env.example)). After editing `.env`, restart the MCP
server so the settings are re-read.

Verify what is currently active:

```powershell
.\.venv\Scripts\python.exe -m athenaeum_mcp.configurator status
```

## Maintenance

These guides are **actively maintained**. Last reviewed: **2026-06-15**.
If you hit a step that no longer matches a provider's website or API, please open
an issue — keeping these accurate is part of the project's support commitment.
