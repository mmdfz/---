# Semantic Scholar setup guide

**Status: ✅ Actively maintained — last reviewed 2026-06-15**

[Semantic Scholar](https://www.semanticscholar.org) (by Allen Institute for AI)
provides paper metadata, **TLDR** one-sentence summaries, and an
influential-citation signal. Athenaeum uses it to enrich works and as an
optional meta-search provider.

## What it unlocks

- TLDR summaries and influential-citation counts on works.
- Inclusion of `semantic_scholar` in the **default** `athenaeum_search`
  meta-search (only when a key is configured — see below).
- Direct queries via `athenaeum_search_provider` with
  `provider="semantic_scholar"` (works even without a key, but rate-limited).

## Is it required?

**No**, but it is **strongly recommended** if you rely on Semantic Scholar.
Without a key the public endpoint is aggressively rate-limited (frequent
HTTP 429), so Athenaeum treats keyless Semantic Scholar as *best-effort* and
**excludes it from the default meta-search** to avoid adding latency and errors.
Adding a key makes it a reliable default provider.

## Step-by-step (API key)

1. Go to **https://www.semanticscholar.org/product/api#api-key-form**.
2. Fill in the short request form (name, email, intended use).
3. You'll receive an **API key** by email (usually quickly).
4. Add it to your `.env` file in the project root:

   ```ini
   SEMANTIC_SCHOLAR_API_KEY=your-s2-api-key-here
   ```

5. **Restart the MCP server** so the key is applied (sent as the `x-api-key`
   header).

## Verify it works

```python
from athenaeum_mcp.providers import semantic_scholar
print(semantic_scholar.has_key)   # True once the key is set
```

When `has_key` is `True`, `semantic_scholar` automatically joins the default
provider list returned by `default_search_providers()`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Frequent HTTP 429 | No key / shared public quota | Add `SEMANTIC_SCHOLAR_API_KEY` |
| Not appearing in meta-search | No key configured | Expected; add a key to include it by default |
| 403 on a specific paper | Restricted record | Skip; other providers cover it |

## Privacy note

The key is read only from your local environment/`.env` and sent only to
`api.semanticscholar.org` over HTTPS.
