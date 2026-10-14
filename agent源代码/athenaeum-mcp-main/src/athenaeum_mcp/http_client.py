"""Async HTTP layer: polite rate limiting, on-disk caching, and retries.

A single shared :class:`HttpClient` is used by every provider. It:

* advertises a polite User-Agent (with mailto) to the scholarly APIs,
* throttles requests per host to respect each service's limits,
* caches successful GET responses on disk (SQLite) with a TTL, and
* retries transient failures (429/5xx/network) with exponential backoff,
  honouring ``Retry-After``.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from .config import get_settings

# Per-host minimum seconds between requests. Values reflect each API's stated
# etiquette (arXiv asks for one request every ~3s; Semantic Scholar allows ~1/s
# without a key).
_HOST_MIN_INTERVAL: dict[str, float] = {
    "api.openalex.org": 0.12,
    "api.crossref.org": 0.10,
    "export.arxiv.org": 3.0,
    "www.ebi.ac.uk": 0.20,
    "api.semanticscholar.org": 1.10,
    "api.unpaywall.org": 0.20,
    "doaj.org": 0.50,
    "doi.org": 0.20,
    # NCBI E-utilities: 3 req/s without a key, 10 req/s with one. 0.35s is safe
    # for the keyless default; a key simply leaves headroom.
    "eutils.ncbi.nlm.nih.gov": 0.35,
    "dblp.org": 1.50,            # DBLP rate-limits aggressively; be a good citizen
    "opencitations.net": 0.50,
    "api.biorxiv.org": 0.50,
    "api.medrxiv.org": 0.50,
    "api.core.ac.uk": 1.00,     # CORE free tier is token-rate-limited
}
_DEFAULT_MIN_INTERVAL = 0.25

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3

# A realistic desktop-browser header set for file/landing-page downloads. Used
# only for ``download_bytes`` (never for the JSON APIs, which want the polite
# bot User-Agent). Recovers PDFs from hosts that reject non-browser agents.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}


class HttpError(Exception):
    """Raised when an HTTP request ultimately fails."""

    def __init__(self, message: str, *, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


@dataclass
class Response:
    status: int
    content: bytes
    content_type: str
    from_cache: bool = False

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.content)


class _RateLimiter:
    """Per-host minimum-interval throttle."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[host] = lock
        return lock

    async def acquire(self, host: str) -> None:
        interval = _HOST_MIN_INTERVAL.get(host, _DEFAULT_MIN_INTERVAL)
        async with self._lock_for(host):
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            wait = interval - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()


class _DiskCache:
    """Tiny SQLite-backed response cache (thread-safe, TTL-based)."""

    def __init__(self, db_path, ttl: int) -> None:
        self.ttl = ttl
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if ttl > 0:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS cache ("
                " key TEXT PRIMARY KEY, status INTEGER, content_type TEXT,"
                " body BLOB, created_at REAL)"
            )
            self._conn.commit()

    @staticmethod
    def make_key(method: str, url: str, params: Mapping[str, Any] | None, accept: str) -> str:
        norm_params = sorted((params or {}).items())
        raw = json.dumps([method.upper(), url, norm_params, accept], sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> Response | None:
        if self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT status, content_type, body, created_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        status, content_type, body, created_at = row
        if time.time() - created_at > self.ttl:
            return None
        return Response(status=status, content=bytes(body), content_type=content_type, from_cache=True)

    def set(self, key: str, resp: Response) -> None:
        if self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, status, content_type, body, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (key, resp.status, resp.content_type, resp.content, time.time()),
            )
            self._conn.commit()


class HttpClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = httpx.AsyncClient(
            timeout=settings.timeout,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        )
        self._limiter = _RateLimiter()
        self._cache = _DiskCache(settings.cache_dir / "http_cache.sqlite", settings.cache_ttl)

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        accept: str = "application/json",
        use_cache: bool = True,
    ) -> Response:
        """Perform a GET with throttling, caching and retries."""
        merged_headers = {"Accept": accept}
        if headers:
            merged_headers.update(headers)

        cache_key = self._cache.make_key("GET", url, params, accept)
        if use_cache:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        host = httpx.URL(url).host or ""
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            await self._limiter.acquire(host)
            try:
                r = await self._client.get(url, params=params, headers=merged_headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_backoff(attempt))
                    continue
                raise HttpError(f"Network error after retries: {exc}", url=url) from exc

            if r.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES:
                await asyncio.sleep(_retry_delay(r, attempt))
                continue

            resp = Response(
                status=r.status_code,
                content=r.content,
                content_type=r.headers.get("Content-Type", ""),
            )
            if r.status_code == 200 and use_cache:
                self._cache.set(cache_key, resp)
            return resp

        # Should not reach here, but keep type-checkers happy.
        raise HttpError(f"Request failed: {last_exc}", url=url)

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        use_cache: bool = True,
    ) -> Any:
        resp = await self.get(url, params=params, headers=headers, accept="application/json", use_cache=use_cache)
        if resp.status != 200:
            raise HttpError(
                f"HTTP {resp.status} for {url}", status=resp.status, url=url
            )
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise HttpError(f"Invalid JSON from {url}: {exc}", url=url) from exc

    async def post_json(
        self,
        url: str,
        *,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        """POST a JSON body and return the raw response (never cached, not retried)."""
        host = httpx.URL(url).host or ""
        await self._limiter.acquire(host)
        try:
            r = await self._client.post(url, json=json_body, headers=dict(headers or {}))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise HttpError(f"Network error posting to {url}: {exc}", url=url) from exc
        return Response(
            status=r.status_code,
            content=r.content,
            content_type=r.headers.get("Content-Type", ""),
        )

    async def download_bytes(
        self,
        url: str,
        *,
        max_bytes: int = 30 * 1024 * 1024,
        accept: str = "application/pdf",
        browser: bool = True,
    ) -> tuple[bytes, str]:
        """Stream a (potentially large) file with a hard size cap. Never cached.

        Returns ``(content, content_type)``. Raises :class:`HttpError` on
        non-200 responses, oversize downloads, or network failure.

        With ``browser=True`` a realistic desktop-browser header set is sent.
        Many publishers and repositories reject the default polite bot
        User-Agent for file downloads but serve the same file to a browser; the
        browser header set recovers those. (Sites behind a JavaScript challenge,
        e.g. some Cloudflare configurations, still cannot be fetched and will
        surface as an HTTP 403.)
        """
        headers = dict(_BROWSER_HEADERS) if browser else {}
        headers["Accept"] = accept
        host = httpx.URL(url).host or ""
        await self._limiter.acquire(host)
        try:
            async with self._client.stream("GET", url, headers=headers) as r:
                if r.status_code != 200:
                    raise HttpError(f"HTTP {r.status_code} downloading {url}", status=r.status_code, url=url)
                chunks: list[bytes] = []
                total = 0
                async for chunk in r.aiter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise HttpError(
                            f"File exceeds size limit ({max_bytes // (1024 * 1024)} MB): {url}",
                            url=url,
                        )
                    chunks.append(chunk)
                return b"".join(chunks), r.headers.get("Content-Type", "")
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise HttpError(f"Network error downloading {url}: {exc}", url=url) from exc

    async def aclose(self) -> None:
        await self._client.aclose()


def _backoff(attempt: int) -> float:
    return min(8.0, 0.5 * (2 ** attempt))


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return min(30.0, float(retry_after))
        except ValueError:
            pass
    return _backoff(attempt)


_client: HttpClient | None = None
_client_lock = threading.Lock()


def get_client() -> HttpClient:
    """Return the process-wide shared HTTP client."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = HttpClient()
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
