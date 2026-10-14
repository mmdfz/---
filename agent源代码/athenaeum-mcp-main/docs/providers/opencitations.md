# OpenCitations setup guide

**Status: ✅ Actively maintained — last reviewed 2026-06-15**

[OpenCitations](https://opencitations.net) is an independent, open citation
index published under a CC0 waiver. Athenaeum uses it as a **complement and
fallback** to the OpenAlex citation graph: when OpenAlex has no references or
citations for a DOI, Athenaeum queries OpenCitations, which sometimes knows
citations OpenAlex has not yet ingested (and vice versa).

## What it unlocks

- Improved recall for `athenaeum_get_references` and `athenaeum_get_citations`
  (used automatically as a fallback — no tool changes needed).
- OpenCitations records embed each work's DOI, OpenAlex id and PMID, so the
  results resolve to full metadata via OpenAlex.

## Is it required?

**No.** OpenCitations works fully without any credential. An optional
**access token** only raises your rate limits with the service.

## Step-by-step (optional access token)

1. Go to **https://opencitations.net/accesstoken**.
2. Enter your email and request a token (free).
3. Copy the **access token** from the confirmation/email.
4. Add it to your `.env` file in the project root:

   ```ini
   OPENCITATIONS_ACCESS_TOKEN=your-token-here
   ```

5. **Restart the MCP server** so the token is applied. Athenaeum sends it as the
   `authorization` header on OpenCitations requests.

## Verify it works

```powershell
.\.venv\Scripts\python.exe scripts\smoke_new_providers.py
```

In Python:

```python
import asyncio
from athenaeum_mcp.providers import opencitations
doi = "10.1186/1756-8722-6-59"   # well covered by OpenCitations
print(asyncio.run(opencitations.citation_count(doi)))
```

## Coverage note (honesty)

OpenCitations does **not** cover every DOI — some works return an empty list
even when they are genuinely cited elsewhere. This is a known coverage gap, not
a bug. That is exactly why Athenaeum uses OpenCitations as a *fallback* behind
OpenAlex/Crossref rather than a primary source.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Empty references/citations | DOI not in OpenCitations' index | Expected; OpenAlex remains the primary source |
| Slow response for highly cited works | Large result set, no server-side paging | Athenaeum slices to your `limit`; the disk cache speeds repeats |
| HTTP 429 | Rate limit without a token | Add `OPENCITATIONS_ACCESS_TOKEN` |

## Privacy note

The optional token is read only from your local environment/`.env` and sent only
to `opencitations.net` over HTTPS.
