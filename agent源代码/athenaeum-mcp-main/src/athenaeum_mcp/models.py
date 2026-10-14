"""Normalized data models shared across providers.

Every provider maps its native response into these models so that results
compose, deduplicate and format uniformly.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .utils import normalize_doi


class Author(BaseModel):
    """A contributor to a work."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., description="Display name, e.g. 'Christine L. Porath'")
    given: str | None = Field(default=None, description="Given/first name(s)")
    family: str | None = Field(default=None, description="Family/last name")
    orcid: str | None = Field(default=None, description="ORCID id or URL")
    affiliation: str | None = Field(default=None, description="Raw affiliation string")
    openalex_id: str | None = None


class Work(BaseModel):
    """A normalized scholarly work (article, preprint, book, …)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    # Identifiers
    doi: str | None = None
    openalex_id: str | None = None
    arxiv_id: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    s2_id: str | None = None
    mag_id: str | None = None

    # Bibliographic core
    title: str | None = None
    abstract: str | None = None
    authors: list[Author] = Field(default_factory=list)
    year: int | None = None
    date: str | None = Field(default=None, description="ISO publication date if known")
    venue: str | None = Field(default=None, description="Journal/conference/repository name")
    venue_issn: list[str] = Field(default_factory=list)
    venue_type: str | None = None
    type: str | None = Field(default=None, description="Work type, e.g. 'article', 'preprint'")
    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None

    # Metrics & status
    cited_by_count: int | None = None
    reference_count: int | None = None
    is_oa: bool | None = None
    oa_status: str | None = Field(default=None, description="gold|green|bronze|hybrid|diamond|closed")
    pdf_url: str | None = None
    landing_url: str | None = None
    is_retracted: bool | None = None

    # Enrichment
    topics: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    language: str | None = None
    tldr: str | None = Field(default=None, description="One-sentence summary (Semantic Scholar)")
    relevance_score: float | None = None

    # Provenance
    source_provider: str | None = Field(default=None, description="Provider that produced this record")
    providers: list[str] = Field(default_factory=list, description="All providers that contributed after merge")

    def model_post_init(self, _ctx: Any) -> None:  # noqa: D401
        if self.doi:
            self.doi = normalize_doi(self.doi) or self.doi
        if self.source_provider and self.source_provider not in self.providers:
            self.providers.append(self.source_provider)

    # ----- helpers ---------------------------------------------------------
    @property
    def best_id(self) -> str:
        """Canonical identifier, preferring DOI."""
        if self.doi:
            return f"doi:{self.doi}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        if self.openalex_id:
            return self.openalex_id
        if self.pmid:
            return f"pmid:{self.pmid}"
        return self.title or "unknown"

    @property
    def author_names(self) -> list[str]:
        return [a.name for a in self.authors]

    def ids(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, val in (
            ("doi", self.doi),
            ("openalex", self.openalex_id),
            ("arxiv", self.arxiv_id),
            ("pmid", self.pmid),
            ("pmcid", self.pmcid),
            ("s2", self.s2_id),
        ):
            if val:
                out[key] = val
        return out

    def compact(self) -> dict[str, Any]:
        """Serialize dropping null/empty fields, with a tidy ``ids`` block."""
        data = self.model_dump(exclude_none=True)
        for empty_key in ("authors", "topics", "keywords", "venue_issn", "providers"):
            if empty_key in data and not data[empty_key]:
                data.pop(empty_key)
        data["ids"] = self.ids()
        data["id"] = self.best_id
        return data


class Venue(BaseModel):
    """A publication venue (journal, conference, repository) with metrics."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str | None = None
    name: str | None = None
    issn_l: str | None = None
    issn: list[str] = Field(default_factory=list)
    type: str | None = None
    publisher: str | None = None
    country: str | None = None
    homepage_url: str | None = None

    is_oa: bool | None = None
    is_in_doaj: bool | None = None
    in_doaj_confirmed: bool | None = Field(default=None, description="Confirmed via a direct DOAJ lookup")
    is_core: bool | None = None

    h_index: int | None = None
    impact_2yr: float | None = Field(default=None, description="OpenAlex 2-year mean citedness (impact-factor-like)")
    i10_index: int | None = None
    works_count: int | None = None
    cited_by_count: int | None = None
    apc_usd: int | None = None

    def compact(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class AuthorProfile(BaseModel):
    """An author/researcher profile with metrics."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str | None = None
    name: str | None = None
    orcid: str | None = None
    affiliation: str | None = None
    works_count: int | None = None
    cited_by_count: int | None = None
    h_index: int | None = None
    i10_index: int | None = None
    topics: list[str] = Field(default_factory=list)

    def compact(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)
