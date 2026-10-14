# CORE setup guide

**Status: ✅ Actively maintained — last reviewed 2026-06-15**

[CORE](https://core.ac.uk) is the world's largest aggregator of open-access
research papers, harvesting tens of millions of full-text documents from
repositories worldwide. Many records include a **directly downloadable PDF**,
which makes CORE a strong complement to `athenaeum_find_pdf` and
`athenaeum_read_pdf` when a publisher copy is blocked.

## What it unlocks

- A new searchable provider: `athenaeum_search_provider` with `provider="core"`,
  and inclusion in the default `athenaeum_search` meta-search.
- Extra open-access full-text PDF candidates for reading papers.

## Is it required?

**A free API key is required to use CORE at all.** Per Athenaeum's design, the
CORE provider is *gated*: without `CORE_API_KEY` it stays completely inactive and
is silently excluded from the meta-search (no errors, no latency). Every other
part of Athenaeum keeps working without it.

## Step-by-step

1. Go to **https://core.ac.uk/services/api** and select the API.
2. Click **Register / Get an API key** and create a free account (an email
   address is all that's needed).
3. Open your **dashboard** and copy your **API key** (a long token string).
4. Add it to your `.env` file in the project root:

   ```ini
   CORE_API_KEY=your-core-api-key-here
   ```

5. **Restart the MCP server** (or your MCP client) so the key is picked up.

## Verify it works

```powershell
# Should now list CORE as active.
.\.venv\Scripts\python.exe -m athenaeum_mcp.configurator status

# End-to-end check (prints CORE results when the key is set).
.\.venv\Scripts\python.exe scripts\smoke_new_providers.py
```

In Python:

```python
from athenaeum_mcp.providers import core
print(core.available())          # True once CORE_API_KEY is set
```

## Rate limits & etiquette

The free tier is rate-limited per token. Athenaeum throttles CORE requests
(≈1 request/second) through its shared rate limiter and caches responses on
disk, so normal use stays well within limits. If you run large batch jobs and
see HTTP 429, slow down or request a higher quota from CORE.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `core.available()` is `False` | Key not loaded | Confirm `CORE_API_KEY` is in `.env`; restart the server |
| HTTP 401 | Invalid/expired key | Re-copy the key from the CORE dashboard |
| HTTP 429 | Rate limit hit | Reduce request volume; the disk cache helps on repeats |
| No results for a known paper | Not in CORE's harvest | Expected — CORE indexes repository copies, not everything |

## Privacy note

Your CORE key is read only from your local environment/`.env` and sent only to
`api.core.ac.uk` over HTTPS. It is never logged or transmitted elsewhere.
