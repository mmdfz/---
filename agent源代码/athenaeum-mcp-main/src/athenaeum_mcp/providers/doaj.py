"""DOAJ provider — Directory of Open Access Journals lookup for source validation."""
from __future__ import annotations

from typing import Any

from ..http_client import HttpError, get_client
from .base import Provider

_BASE = "https://doaj.org/api/v2"


class DOAJProvider(Provider):
    name = "doaj"

    async def lookup_journal(self, issn: str) -> dict[str, Any] | None:
        """Return DOAJ indexing info for an ISSN, or ``None`` if not indexed.

        A result with ``in_doaj=True`` means the journal is a vetted open-access
        journal indexed by DOAJ — a positive legitimacy signal.
        """
        issn = issn.strip()
        if not issn:
            return None
        try:
            data = await get_client().get_json(f"{_BASE}/search/journals/issn:{issn}")
        except HttpError:
            return None
        results = data.get("results") or []
        if not results:
            return {"in_doaj": False}
        bj = (results[0] or {}).get("bibjson") or {}
        licenses = [l.get("type") for l in (bj.get("license") or []) if l.get("type")]
        apc = bj.get("apc") or {}
        return {
            "in_doaj": True,
            "title": bj.get("title"),
            "publisher": (bj.get("publisher") or {}).get("name"),
            "licenses": licenses,
            "has_apc": bool(apc.get("has_apc")),
            "doaj_seal": bool(bj.get("boai")) or bool(bj.get("seal")),
            "oa_start": bj.get("oa_start"),
        }


doaj = DOAJProvider()
