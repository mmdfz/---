"""Citation formatting in several common styles.

Formats a :class:`Work` into BibTeX, RIS, APA, MLA, Chicago (author-date),
Vancouver, Harvard or IEEE, or exports CSL-JSON (the citeproc format used by
Zotero, Pandoc and most reference managers).

Generation is local (no network), so it works for preprints and records without
a DOI, and is deterministic.

These implementations follow the common, widely-accepted form of each style.
They are intended to give a correct, copy-pasteable starting point; always
sanity-check against your target venue's exact guide.
"""
from __future__ import annotations

import json
import re

from .models import Author, Work
from .utils import slugify

STYLES = ["bibtex", "ris", "apa", "mla", "chicago", "vancouver", "harvard", "ieee"]


# --------------------------------------------------------------------------- #
# Name handling
# --------------------------------------------------------------------------- #
def _split_name(author: Author) -> tuple[str, str]:
    """Return ``(given, family)`` for an author, parsing the display name if needed."""
    if author.family:
        return (author.given or "").strip(), author.family.strip()
    name = (author.name or "").strip()
    if not name:
        return "", ""
    if "," in name:
        family, _, given = name.partition(",")
        return given.strip(), family.strip()
    parts = name.split()
    if len(parts) == 1:
        return "", parts[0]
    return " ".join(parts[:-1]), parts[-1]


def _initials_dotted(given: str) -> str:
    """'Christine L.' -> 'C. L.'"""
    toks = [t for t in re.split(r"[\s.]+", given) if t and t[0].isalpha()]
    return " ".join(f"{t[0].upper()}." for t in toks)


def _initials_compact(given: str) -> str:
    """'Christine L.' -> 'CL' (Vancouver style)."""
    toks = [t for t in re.split(r"[\s.]+", given) if t and t[0].isalpha()]
    return "".join(t[0].upper() for t in toks)


def _year(work: Work) -> str:
    return str(work.year) if work.year else "n.d."


def _container(work: Work) -> str | None:
    return work.venue or (work.publisher if work.type in {"book", "book-chapter"} else None)


def _doi_url(work: Work) -> str | None:
    if work.doi:
        return f"https://doi.org/{work.doi}"
    if work.arxiv_id:
        return f"https://arxiv.org/abs/{work.arxiv_id}"
    return work.landing_url


def _vol_issue_pages(work: Work) -> str:
    out = ""
    if work.volume:
        out += work.volume
    if work.issue:
        out += f"({work.issue})"
    if work.pages:
        out += f", {work.pages}" if out else work.pages
    return out


# --------------------------------------------------------------------------- #
# Author-list renderers per style
# --------------------------------------------------------------------------- #
def _authors_apa(authors: list[Author]) -> str:
    formatted = [f"{fam}, {_initials_dotted(giv)}".strip().rstrip(",") for giv, fam in map(_split_name, authors)]
    formatted = [f for f in formatted if f]
    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) <= 20:
        return ", ".join(formatted[:-1]) + f", & {formatted[-1]}"
    return ", ".join(formatted[:19]) + ", … " + formatted[-1]


def _authors_chicago(authors: list[Author]) -> str:
    names = list(map(_split_name, authors))
    rendered = []
    for i, (giv, fam) in enumerate(names):
        rendered.append(f"{fam}, {giv}".strip().rstrip(",") if i == 0 else f"{giv} {fam}".strip())
    if not rendered:
        return ""
    if len(rendered) == 1:
        return rendered[0]
    if len(rendered) <= 10:
        return ", ".join(rendered[:-1]) + f", and {rendered[-1]}"
    return rendered[0] + " et al."


def _authors_mla(authors: list[Author]) -> str:
    names = list(map(_split_name, authors))
    if not names:
        return ""
    first = f"{names[0][1]}, {names[0][0]}".strip().rstrip(",")
    if len(names) == 1:
        return first
    if len(names) == 2:
        return f"{first}, and {names[1][0]} {names[1][1]}".strip()
    return f"{first}, et al"


def _authors_vancouver(authors: list[Author]) -> str:
    rendered = [f"{fam} {_initials_compact(giv)}".strip() for giv, fam in map(_split_name, authors)]
    rendered = [r for r in rendered if r]
    if len(rendered) > 6:
        return ", ".join(rendered[:6]) + ", et al"
    return ", ".join(rendered)


def _authors_harvard(authors: list[Author]) -> str:
    rendered = [f"{fam}, {_initials_dotted(giv)}".strip().rstrip(",") for giv, fam in map(_split_name, authors)]
    rendered = [r for r in rendered if r]
    if not rendered:
        return ""
    if len(rendered) == 1:
        return rendered[0]
    return ", ".join(rendered[:-1]) + f" and {rendered[-1]}"


def _authors_ieee(authors: list[Author]) -> str:
    rendered = [f"{_initials_dotted(giv)} {fam}".strip() for giv, fam in map(_split_name, authors)]
    rendered = [r for r in rendered if r]
    if not rendered:
        return ""
    if len(rendered) == 1:
        return rendered[0]
    return ", ".join(rendered[:-1]) + f", and {rendered[-1]}"


# --------------------------------------------------------------------------- #
# Full reference renderers
# --------------------------------------------------------------------------- #
def _apa(work: Work) -> str:
    parts = [f"{_authors_apa(work.authors)} ({_year(work)}). {work.title or 'Untitled'}."]
    container = _container(work)
    if container:
        vip = _vol_issue_pages(work)
        parts.append(f"{container}, {vip}." if vip else f"{container}.")
    url = _doi_url(work)
    if url:
        parts.append(url)
    return " ".join(p for p in parts if p).strip()


def _mla(work: Work) -> str:
    out = []
    authors = _authors_mla(work.authors)
    if authors:
        out.append(f"{authors}.")
    out.append(f'"{work.title or "Untitled"}."')
    container = _container(work)
    bits = []
    if container:
        bits.append(container)
    if work.volume:
        bits.append(f"vol. {work.volume}")
    if work.issue:
        bits.append(f"no. {work.issue}")
    if work.year:
        bits.append(str(work.year))
    if work.pages:
        bits.append(f"pp. {work.pages}")
    if bits:
        out.append(", ".join(bits) + ".")
    url = _doi_url(work)
    if url:
        out.append(f"{url}.")
    return " ".join(out).strip()


def _chicago(work: Work) -> str:
    parts = [f"{_authors_chicago(work.authors)}. {_year(work)}. \"{work.title or 'Untitled'}.\""]
    container = _container(work)
    if container:
        seg = container
        if work.volume:
            seg += f" {work.volume}"
        if work.issue:
            seg += f" ({work.issue})"
        if work.pages:
            seg += f": {work.pages}"
        parts.append(seg + ".")
    url = _doi_url(work)
    if url:
        parts.append(url + ".")
    return " ".join(p for p in parts if p).strip()


def _vancouver(work: Work) -> str:
    parts = [f"{_authors_vancouver(work.authors)}. {work.title or 'Untitled'}."]
    container = work.venue or work.publisher
    tail = ""
    if container:
        tail = f"{container}. "
    tail += f"{work.year};" if work.year else ""
    tail += _vol_issue_pages(work).replace(", ", ":")
    if tail.strip():
        parts.append(tail.strip() + ".")
    if work.doi:
        parts.append(f"doi:{work.doi}.")
    return " ".join(p for p in parts if p).strip()


def _harvard(work: Work) -> str:
    parts = [f"{_authors_harvard(work.authors)} ({_year(work)}) '{work.title or 'Untitled'}'"]
    container = _container(work)
    if container:
        seg = container
        vip = _vol_issue_pages(work)
        if vip:
            seg += f", {vip}"
        parts[0] += f", {seg}"
    parts[0] += "."
    url = _doi_url(work)
    if url:
        parts.append(f"Available at: {url}.")
    return " ".join(parts).strip()


def _ieee(work: Work) -> str:
    out = [f"{_authors_ieee(work.authors)},"] if work.authors else []
    out.append(f'"{work.title or "Untitled"},"')
    container = _container(work)
    if container:
        out.append(f"{container},")
    if work.volume:
        out.append(f"vol. {work.volume},")
    if work.issue:
        out.append(f"no. {work.issue},")
    if work.pages:
        out.append(f"pp. {work.pages},")
    if work.year:
        out.append(f"{work.year}.")
    url = _doi_url(work)
    if url:
        out.append(f"doi: {work.doi}." if work.doi else url)
    return " ".join(out).strip()


# --------------------------------------------------------------------------- #
# Machine formats
# --------------------------------------------------------------------------- #
_BIBTEX_TYPE = {
    "article": "article", "preprint": "article", "conference-paper": "inproceedings",
    "book": "book", "book-chapter": "incollection", "thesis": "phdthesis", "report": "techreport",
}
_RIS_TYPE = {
    "article": "JOUR", "preprint": "JOUR", "conference-paper": "CONF", "book": "BOOK",
    "book-chapter": "CHAP", "thesis": "THES", "report": "RPRT", "dataset": "DATA",
}


def _bibtex_key(work: Work) -> str:
    fam = _split_name(work.authors[0])[1] if work.authors else "anon"
    first_word = re.sub(r"[^A-Za-z]", "", (work.title or "untitled").split(" ")[0]) or "untitled"
    return f"{slugify(fam) or 'anon'}{work.year or 'nd'}{first_word.lower()}"


def _bibtex(work: Work) -> str:
    entry_type = _BIBTEX_TYPE.get(work.type or "article", "article")
    fields: list[tuple[str, str]] = []
    if work.authors:
        fields.append(("author", " and ".join(
            f"{fam}, {giv}".strip().rstrip(",") for giv, fam in map(_split_name, work.authors)
        )))
    if work.title:
        fields.append(("title", work.title))
    if work.year:
        fields.append(("year", str(work.year)))
    container_key = "journal" if entry_type == "article" else "booktitle" if entry_type in {"inproceedings", "incollection"} else "journal"
    if work.venue:
        fields.append((container_key, work.venue))
    if work.publisher:
        fields.append(("publisher", work.publisher))
    if work.volume:
        fields.append(("volume", work.volume))
    if work.issue:
        fields.append(("number", work.issue))
    if work.pages:
        fields.append(("pages", work.pages.replace("-", "--")))
    if work.doi:
        fields.append(("doi", work.doi))
    url = _doi_url(work)
    if url:
        fields.append(("url", url))
    if work.arxiv_id:
        fields.append(("note", f"arXiv:{work.arxiv_id}"))
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields)
    return f"@{entry_type}{{{_bibtex_key(work)},\n{body}\n}}"


def _ris(work: Work) -> str:
    lines = [f"TY  - {_RIS_TYPE.get(work.type or 'article', 'GEN')}"]
    for giv, fam in map(_split_name, work.authors):
        lines.append(f"AU  - {fam}, {giv}".rstrip(", "))
    if work.title:
        lines.append(f"TI  - {work.title}")
    if work.venue:
        lines.append(f"T2  - {work.venue}")
    if work.year:
        lines.append(f"PY  - {work.year}")
    if work.volume:
        lines.append(f"VL  - {work.volume}")
    if work.issue:
        lines.append(f"IS  - {work.issue}")
    if work.pages:
        sp, _, ep = work.pages.partition("-")
        lines.append(f"SP  - {sp.strip()}")
        if ep:
            lines.append(f"EP  - {ep.strip()}")
    if work.doi:
        lines.append(f"DO  - {work.doi}")
    url = _doi_url(work)
    if url:
        lines.append(f"UR  - {url}")
    if work.abstract:
        lines.append(f"AB  - {work.abstract}")
    if work.publisher:
        lines.append(f"PB  - {work.publisher}")
    lines.append("ER  - ")
    return "\n".join(lines)


_RENDERERS = {
    "apa": _apa, "mla": _mla, "chicago": _chicago, "vancouver": _vancouver,
    "harvard": _harvard, "ieee": _ieee, "bibtex": _bibtex, "ris": _ris,
}


def format_citation(work: Work, style: str) -> str:
    """Format a single work in the requested style (see :data:`STYLES`)."""
    renderer = _RENDERERS.get(style.lower())
    if renderer is None:
        raise ValueError(f"Unknown style '{style}'. Choose from: {', '.join(STYLES)}")
    return renderer(work)


def format_bibliography(works: list[Work], style: str) -> str:
    """Format many works. BibTeX/RIS are concatenated; prose styles are listed."""
    style = style.lower()
    if style in {"bibtex", "ris"}:
        sep = "\n\n" if style == "bibtex" else "\n"
        return sep.join(format_citation(w, style) for w in works)
    if style in {"vancouver", "ieee"}:  # numbered styles
        return "\n".join(f"[{i}] {format_citation(w, style)}" for i, w in enumerate(works, 1))
    # author-date styles: sort alphabetically by first author family / title
    ordered = sorted(works, key=lambda w: (_split_name(w.authors[0])[1].lower() if w.authors else (w.title or "").lower()))
    return "\n".join(format_citation(w, style) for w in ordered)


# --------------------------------------------------------------------------- #
# CSL-JSON (citeproc) export — consumed by Zotero, Pandoc, etc.
# --------------------------------------------------------------------------- #
_CSL_TYPE = {
    "article": "article-journal",
    "preprint": "article-journal",
    "conference-paper": "paper-conference",
    "book": "book",
    "book-chapter": "chapter",
    "thesis": "thesis",
    "report": "report",
    "dataset": "dataset",
}


def to_csl_json(works: list[Work]) -> list[dict]:
    """Return a list of CSL-JSON item dicts."""
    items = []
    for w in works:
        item: dict = {
            "id": w.best_id,
            "type": _CSL_TYPE.get(w.type or "article", "article-journal"),
            "title": w.title or "Untitled",
        }
        if w.authors:
            item["author"] = [
                ({"family": fam, "given": giv} if giv else {"literal": a.name})
                for a, (giv, fam) in ((a, _split_name(a)) for a in w.authors)
            ]
        if w.year:
            item["issued"] = {"date-parts": [[w.year]]}
        if w.venue:
            item["container-title"] = w.venue
        if w.volume:
            item["volume"] = w.volume
        if w.issue:
            item["issue"] = w.issue
        if w.pages:
            item["page"] = w.pages
        if w.doi:
            item["DOI"] = w.doi
        if w.venue_issn:
            item["ISSN"] = w.venue_issn
        if w.publisher:
            item["publisher"] = w.publisher
        url = _doi_url(w)
        if url:
            item["URL"] = url
        if w.abstract:
            item["abstract"] = w.abstract
        items.append(item)
    return items


def csl_json_string(works: list[Work]) -> str:
    return json.dumps(to_csl_json(works), indent=2, ensure_ascii=False)
