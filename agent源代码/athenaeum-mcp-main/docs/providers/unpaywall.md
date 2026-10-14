# Unpaywall setup guide

**Status: ✅ Actively maintained — last reviewed 2026-06-15**

[Unpaywall](https://unpaywall.org) is a best-in-class locator of **legal,
open-access** copies of paywalled papers. Athenaeum uses it to add extra
full-text PDF candidates for `athenaeum_find_pdf` and `athenaeum_read_pdf`.

## What it unlocks

- Additional open-access PDF locations (repository, publisher, etc.) when
  discovering or reading a paper's full text.

## Is it required?

**No.** Athenaeum already finds OA PDFs via OpenAlex, PMC, arXiv, bioRxiv and
repositories. Unpaywall adds extra coverage for tricky DOIs.

## Setup is special: no key, but a **real email**

Unpaywall has **no API key**. Instead it requires you to identify yourself with
a **real email address** — placeholder addresses are rejected with HTTP 422. So
this provider activates only when **both** of these are set:

1. A real `ATHENAEUM_EMAIL` (an address you control), and
2. `ATHENAEUM_ENABLE_UNPAYWALL=true`.

## Step-by-step

1. Edit your `.env` file in the project root:

   ```ini
   ATHENAEUM_EMAIL=you@example.com       # a REAL address you control
   ATHENAEUM_ENABLE_UNPAYWALL=true
   ```

2. **Restart the MCP server** so the settings are applied.

> Setting a real `ATHENAEUM_EMAIL` is good practice anyway: it also puts your
> OpenAlex and Crossref requests in the faster "polite pool".

## Verify it works

```python
from athenaeum_mcp.providers import unpaywall
print(unpaywall.available())   # True only with a real email + the enable flag
```

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `unpaywall.available()` is `False` | Missing email or flag | Set a real `ATHENAEUM_EMAIL` **and** `ATHENAEUM_ENABLE_UNPAYWALL=true` |
| HTTP 422 from Unpaywall | Placeholder email rejected | Use a real address you control |
| No PDF for a DOI | No OA copy exists | Expected for genuinely paywalled, un-deposited works |

## Privacy note

Your email is sent to `api.unpaywall.org` as the required contact parameter (as
the service mandates) and to the OpenAlex/Crossref polite pools. It is not used
anywhere else.
