"""Unpaywall provider — optional open-access PDF discovery.

Unpaywall requires a *real* email address (placeholder addresses are rejected
with HTTP 422), so this provider is only active when both
``ATHENAEUM_ENABLE_UNPAYWALL=true`` and a real ``ATHENAEUM_EMAIL`` are set.
"""
from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..http_client import HttpError, get_client
from ..utils import detect_identifier
from .base import Provider

_BASE = "https://api.unpaywall.org/v2"


class UnpaywallProvider(Provider):
    name = "unpaywall"

    def available(self) -> bool:
        return get_settings().unpaywall_enabled

    async def lookup(self, doi: str) -> dict[str, Any] | None:
        """Return OA status and a free PDF link for a DOI, or ``None``."""
        if not self.available():
            return None
        kind, value = detect_identifier(doi)
        if kind != "doi":
            return None
        try:
            data = await get_client().get_json(
                f"{_BASE}/{value}", params={"email": get_settings().email}
            )
        except HttpError:
            return None
        best = data.get("best_oa_location") or {}
        return {
            "is_oa": data.get("is_oa"),
            "oa_status": data.get("oa_status"),
            "pdf_url": best.get("url_for_pdf") or best.get("url"),
            "license": best.get("license"),
            "host_type": best.get("host_type"),
            "version": best.get("version"),
        }


unpaywall = UnpaywallProvider()
