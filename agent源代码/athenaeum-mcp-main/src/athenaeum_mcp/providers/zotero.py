"""Zotero integration via the Zotero Web API.

Lets an agent push resolved works straight into a user's Zotero library so they
build their reference manager as they research. Optional and gated: it activates
only when ``ZOTERO_API_KEY`` and ``ZOTERO_LIBRARY_ID`` are configured.

API docs: https://www.zotero.org/support/dev/web_api/v3/write_requests
"""
from __future__ import annotations

import json
from typing import Any

from ..config import get_settings
from ..formatting import _split_name
from ..http_client import HttpError, get_client
from ..models import Author, Work

_BASE = "https://api.zotero.org"

# Map our normalized work types to Zotero item types.
_ITEM_TYPE = {
    "article": "journalArticle",
    "preprint": "preprint",
    "book": "book",
    "book-chapter": "bookSection",
    "conference-paper": "conferencePaper",
    "thesis": "thesis",
    "report": "report",
    "dataset": "dataset",
}


def _creators(authors: list[Author]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for a in authors:
        given, family = _split_name(a)
        if family:
            out.append({"creatorType": "author", "firstName": given, "lastName": family})
        else:
            out.append({"creatorType": "author", "name": a.name})
    return out


def _date(work: Work) -> str:
    if work.date:
        return work.date
    return str(work.year) if work.year else ""


def work_to_zotero_item(work: Work, collection_key: str | None = None) -> dict[str, Any]:
    """Convert a normalized Work into a Zotero item payload."""
    item_type = _ITEM_TYPE.get(work.type or "article", "journalArticle")
    item: dict[str, Any] = {
        "itemType": item_type,
        "title": work.title or "Untitled",
        "creators": _creators(work.authors),
        "abstractNote": work.abstract or "",
        "date": _date(work),
        "url": (f"https://doi.org/{work.doi}" if work.doi else work.landing_url) or "",
        "DOI": work.doi or "",
        "tags": [],
    }

    if item_type == "journalArticle":
        item.update({
            "publicationTitle": work.venue or "",
            "volume": work.volume or "",
            "issue": work.issue or "",
            "pages": work.pages or "",
            "ISSN": ", ".join(work.venue_issn) if work.venue_issn else "",
        })
    elif item_type == "preprint":
        item.pop("DOI", None)  # preprint uses DOI field too, but keep extra fields tidy
        item.update({
            "repository": work.venue or "",
            "archiveID": f"arXiv:{work.arxiv_id}" if work.arxiv_id else "",
            "DOI": work.doi or "",
        })
    elif item_type in {"book", "bookSection"}:
        item.update({"publisher": work.publisher or "", "ISBN": ""})
    elif item_type == "conferencePaper":
        item.update({"proceedingsTitle": work.venue or "", "pages": work.pages or ""})

    if collection_key:
        item["collections"] = [collection_key]

    # Drop empty-string fields Zotero would reject as unknown for the type.
    return {k: v for k, v in item.items() if v not in ("", None)}


class ZoteroProvider:
    name = "zotero"

    def available(self) -> bool:
        return get_settings().zotero_enabled

    def _headers(self) -> dict[str, str]:
        s = get_settings()
        return {
            "Zotero-API-Key": s.zotero_api_key or "",
            "Zotero-API-Version": "3",
            "Content-Type": "application/json",
        }

    def _library_path(self) -> str:
        s = get_settings()
        kind = "groups" if s.zotero_library_type == "group" else "users"
        return f"{kind}/{s.zotero_library_id}"

    async def list_collections(self) -> list[dict[str, str]]:
        if not self.available():
            return []
        try:
            data = await get_client().get_json(
                f"{_BASE}/{self._library_path()}/collections",
                headers=self._headers(),
                use_cache=False,
            )
        except HttpError:
            return []
        return [
            {"key": c.get("key", ""), "name": (c.get("data") or {}).get("name", "")}
            for c in data
        ]

    async def add_items(self, works: list[Work], collection_key: str | None = None) -> dict[str, Any]:
        """Create Zotero items from works. Returns a summary of successes/failures."""
        if not self.available():
            return {"ok": False, "error": "Zotero is not configured. Set ZOTERO_API_KEY and ZOTERO_LIBRARY_ID."}
        if not works:
            return {"ok": False, "error": "No works to add."}

        created = 0
        failed = 0
        messages: list[str] = []

        # Zotero accepts up to 50 items per write request.
        for start in range(0, len(works), 50):
            batch = works[start : start + 50]
            payload = [work_to_zotero_item(w, collection_key) for w in batch]
            try:
                resp = await get_client().post_json(
                    f"{_BASE}/{self._library_path()}/items",
                    json_body=payload,
                    headers=self._headers(),
                )
            except HttpError as exc:
                failed += len(batch)
                messages.append(str(exc))
                continue

            if resp.status not in (200, 201):
                failed += len(batch)
                snippet = resp.text[:200]
                messages.append(f"HTTP {resp.status}: {snippet}")
                continue

            try:
                body = json.loads(resp.content)
                created += len(body.get("successful", {}))
                fails = body.get("failed", {})
                failed += len(fails)
                for v in fails.values():
                    messages.append(v.get("message", "unknown failure"))
            except Exception:  # noqa: BLE001
                created += len(batch)

        return {
            "ok": created > 0,
            "created": created,
            "failed": failed,
            "library": f"{get_settings().zotero_library_type}:{get_settings().zotero_library_id}",
            "collection": collection_key,
            "messages": messages[:10],
        }


zotero = ZoteroProvider()
