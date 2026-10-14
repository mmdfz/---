# Zotero setup guide

**Status: ✅ Actively maintained — last reviewed 2026-06-15**

[Zotero](https://www.zotero.org) is a free reference manager. With this
integration, an agent can push resolved works **straight into your Zotero
library** as you research, optionally into a specific collection.

## What it unlocks

- `athenaeum_zotero_add` — add one or more references to your library.
- `athenaeum_zotero_collections` — list your collections (to target one).

These are the only **write** tools in Athenaeum; they are gated and inactive
until configured.

## Is it required?

**No.** It is entirely optional and only needed if you use Zotero.

## Step-by-step

### 1. Create an API key

1. Go to **https://www.zotero.org/settings/keys**.
2. Click **Create new private key**.
3. Give it a name and **enable write access** ("Allow library access" +
   "Allow write access"). For a group library, grant access to that group.
4. Save and **copy the key** (shown once).

### 2. Find your library ID

- **Personal (user) library:** on the same
  [keys page](https://www.zotero.org/settings/keys), your **userID** is shown as
  *"Your userID for use in API calls is NNNNNN"*. Use that number.
- **Group library:** open the group, then **Settings/Library Settings**; the
  group ID is the number in the URL `groups/NNNNNN`.

### 3. Configure `.env`

```ini
ZOTERO_API_KEY=your-zotero-key
ZOTERO_LIBRARY_ID=1234567
ZOTERO_LIBRARY_TYPE=user      # "user" for a personal library, "group" for a group
```

### 4. Restart the MCP server

Restart so the settings are applied.

## Verify it works

```python
from athenaeum_mcp.config import get_settings
print(get_settings().zotero_enabled)   # True once key + library id are set
```

Then, from your agent: *"List my Zotero collections"* (calls
`athenaeum_zotero_collections`). If it returns your collections, writes will work.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `zotero_enabled` is `False` | Missing key or library id | Set both `ZOTERO_API_KEY` and `ZOTERO_LIBRARY_ID` |
| HTTP 403 on add | Key lacks write access | Recreate the key with write permission |
| Items added to wrong library | Wrong `ZOTERO_LIBRARY_TYPE` | Use `user` vs `group` correctly |
| Group writes fail | Key not granted to that group | Grant the group in the key settings |

## Privacy note

Your Zotero key and library id are read only from your local environment/`.env`
and sent only to `api.zotero.org` over HTTPS. Write tools change *your* library
only.
