"""Provider registry and singletons.

Exposes one instance per provider plus helpers used by the meta-search to pick
which providers participate by default.
"""
from __future__ import annotations

from .arxiv import arxiv
from .base import Provider
from .biorxiv import biorxiv
from .core import core
from .crossref import crossref
from .dblp import dblp
from .doaj import doaj
from .europepmc import europepmc
from .opencitations import opencitations
from .openalex import openalex
from .pubmed import pubmed
from .semantic_scholar import semantic_scholar
from .unpaywall import unpaywall
from .zotero import zotero

# Providers that can answer a free-text search query.
SEARCH_PROVIDERS: dict[str, Provider] = {
    "openalex": openalex,
    "crossref": crossref,
    "arxiv": arxiv,
    "europepmc": europepmc,
    "pubmed": pubmed,
    "semantic_scholar": semantic_scholar,
    "dblp": dblp,
    "core": core,
}


def default_search_providers() -> list[str]:
    """Provider names included in the meta-search by default.

    The keyless core five plus PubMed always participate. Providers that need a
    key are only added when their key is configured, so they never add latency
    or rate-limit errors when unconfigured:

    * Semantic Scholar — without a key it is heavily rate-limited (HTTP 429).
    * CORE — requires an API key; inactive otherwise.

    DBLP is intentionally *not* a default: it is computer-science-only, so it is
    left for explicit ``providers=["dblp"]`` selection to avoid adding noise and
    latency to general (non-CS) queries.
    """
    names = ["openalex", "crossref", "arxiv", "europepmc", "pubmed"]
    if semantic_scholar.has_key:
        names.append("semantic_scholar")
    if core.available():
        names.append("core")
    return names


__all__ = [
    "Provider",
    "arxiv",
    "biorxiv",
    "core",
    "crossref",
    "dblp",
    "doaj",
    "europepmc",
    "opencitations",
    "openalex",
    "pubmed",
    "semantic_scholar",
    "unpaywall",
    "zotero",
    "SEARCH_PROVIDERS",
    "default_search_providers",
]
