"""Runtime configuration for Athenaeum.

All settings are optional. The core providers (OpenAlex, Crossref, arXiv,
Europe PMC, DOAJ) work with zero configuration. Configuration only unlocks
faster "polite pool" rate limits and the optional Unpaywall / Semantic Scholar
/ Zotero integrations.

Settings are read from environment variables, optionally seeded from a ``.env``
file located next to the project root or the current working directory.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:  # python-dotenv ships as a transitive dependency of mcp
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - defensive
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


def _load_env_files() -> None:
    """Load .env from a few likely locations without overriding real env vars."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",  # project root
    ]
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.is_file():
            load_dotenv(path, override=False)


def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# A placeholder address is fine for OpenAlex/Crossref polite pools but is
# rejected by Unpaywall; we therefore only use a real-looking email to enable
# Unpaywall.
def _get_str(name: str) -> str | None:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else None


# A placeholder address is fine for OpenAlex/Crossref polite pools but is
# rejected by Unpaywall; we therefore only use a real-looking email to enable
# Unpaywall.
_PLACEHOLDER_EMAILS = {"", "athenaeum@example.com", "you@example.com", "scholar-mcp@example.com"}


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings."""

    email: str
    semantic_scholar_api_key: str | None
    ncbi_api_key: str | None
    core_api_key: str | None
    opencitations_token: str | None
    enable_unpaywall: bool
    cache_ttl: int
    timeout: float
    cache_dir: Path
    user_agent: str
    zotero_api_key: str | None
    zotero_library_id: str | None
    zotero_library_type: str

    @property
    def has_real_email(self) -> bool:
        return self.email.lower() not in _PLACEHOLDER_EMAILS and "@" in self.email

    @property
    def mailto(self) -> str:
        """Email to advertise to OpenAlex/Crossref polite pools."""
        return self.email if "@" in self.email else "athenaeum@example.com"

    @property
    def unpaywall_enabled(self) -> bool:
        return self.enable_unpaywall and self.has_real_email

    @property
    def zotero_enabled(self) -> bool:
        return bool(self.zotero_api_key and self.zotero_library_id)

    @property
    def core_enabled(self) -> bool:
        return bool(self.core_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Build (and cache) settings from the environment."""
    _load_env_files()

    email = (os.getenv("ATHENAEUM_EMAIL") or "athenaeum@example.com").strip()
    key = _get_str("SEMANTIC_SCHOLAR_API_KEY")
    ncbi_api_key = _get_str("NCBI_API_KEY")
    core_api_key = _get_str("CORE_API_KEY")
    opencitations_token = _get_str("OPENCITATIONS_ACCESS_TOKEN")
    enable_unpaywall = _get_bool("ATHENAEUM_ENABLE_UNPAYWALL", False)
    cache_ttl = _get_int("ATHENAEUM_CACHE_TTL", 86_400)
    timeout = float(_get_int("ATHENAEUM_TIMEOUT", 30))

    cache_dir_raw = os.getenv("ATHENAEUM_CACHE_DIR")
    cache_dir = Path(cache_dir_raw) if cache_dir_raw else Path.cwd() / ".athenaeum_cache"

    zotero_api_key = _get_str("ZOTERO_API_KEY")
    zotero_library_id = _get_str("ZOTERO_LIBRARY_ID")
    zotero_library_type = (_get_str("ZOTERO_LIBRARY_TYPE") or "user").lower()
    if zotero_library_type not in {"user", "group"}:
        zotero_library_type = "user"

    advertised = email if "@" in email else "athenaeum@example.com"
    user_agent = f"athenaeum-mcp/0.1.0 (https://github.com/; mailto:{advertised})"

    return Settings(
        email=email,
        semantic_scholar_api_key=key,
        ncbi_api_key=ncbi_api_key,
        core_api_key=core_api_key,
        opencitations_token=opencitations_token,
        enable_unpaywall=enable_unpaywall,
        cache_ttl=cache_ttl,
        timeout=timeout,
        cache_dir=cache_dir,
        user_agent=user_agent,
        zotero_api_key=zotero_api_key,
        zotero_library_id=zotero_library_id,
        zotero_library_type=zotero_library_type,
    )
