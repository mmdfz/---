# PubMed / NCBI E-utilities setup guide

**Status: ✅ Actively maintained — last reviewed 2026-06-15**

[PubMed](https://pubmed.ncbi.nlm.nih.gov) (via the NCBI **E-utilities** API) is
the authoritative index for biomedical, psychology and behavioral-science
literature. Athenaeum uses it for search and metadata, contributing abstracts,
DOIs and **MeSH** subject terms, and an independent relevance signal to the
meta-search rank fusion.

## What it unlocks

- PubMed is a **default** provider in `athenaeum_search` and available via
  `athenaeum_search_provider` with `provider="pubmed"` — **no key needed**.
- An optional `NCBI_API_KEY` simply **raises the request rate limit** from
  3 requests/second to 10 requests/second.

## Is it required?

**No.** PubMed works fully without any credential. Add a key only if you run
high-volume queries and want extra rate headroom.

## Step-by-step (optional API key)

1. Create a free **NCBI account** at https://account.ncbi.nlm.nih.gov/ (you can
   sign in with an institutional or Google/ORCID identity).
2. Open **Account settings** → scroll to **API Key Management**.
3. Click **Create an API Key** and copy the generated key.
4. Add it to your `.env` file in the project root:

   ```ini
   NCBI_API_KEY=your-ncbi-api-key-here
   ```

5. **Restart the MCP server** so the key is applied.

> Tip: NCBI also asks callers to identify themselves with a tool name and email.
> Athenaeum sends `tool=athenaeum-mcp` automatically and uses your
> `ATHENAEUM_EMAIL` if set — another good reason to set a real email.

## Verify it works

```powershell
.\.venv\Scripts\python.exe scripts\smoke_new_providers.py
```

In Python:

```python
import asyncio
from athenaeum_mcp.providers import pubmed
print(asyncio.run(pubmed.search("technostress", limit=2)))
```

The key is optional, so there is no `available()` flag — PubMed is always on.

## Rate limits & etiquette

- Without a key: **3 requests/second** per host (NCBI's stated limit).
- With a key: **10 requests/second**.

Athenaeum throttles NCBI calls (≈0.35 s between requests) and caches responses,
which keeps keyless use safely under the limit. Heavy users should set a key and
run during off-peak hours per NCBI's usage guidelines.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| HTTP 429 from NCBI | Too many requests without a key | Add `NCBI_API_KEY`, or reduce volume |
| Empty `keywords` (MeSH) | Article not yet MEDLINE-indexed | Expected for very recent/"not-MEDLINE" records |
| No abstract | Record genuinely has none | Confirmed via EFetch; nothing to fix |

## Privacy note

The optional key is read only from your local environment/`.env` and sent only
to `eutils.ncbi.nlm.nih.gov` over HTTPS.
