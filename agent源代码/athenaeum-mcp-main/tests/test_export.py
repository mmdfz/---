import json

from athenaeum_mcp.formatting import csl_json_string, to_csl_json
from athenaeum_mcp.models import Author, Work
from athenaeum_mcp.providers.zotero import work_to_zotero_item

WORK = Work(
    doi="10.1177/0149206311425615",
    title="Thriving at work",
    year=2012,
    authors=[Author(name="Christine L. Porath"), Author(name="Gretchen Spreitzer")],
    venue="Journal of Organizational Behavior",
    volume="33",
    issue="2",
    pages="250-275",
    type="article",
    venue_issn=["1099-1379"],
)

PREPRINT = Work(
    arxiv_id="2311.07072",
    title="Technostress and Job Performance",
    year=2023,
    authors=[Author(name="Jane Q. Researcher")],
    type="preprint",
)


def test_csl_json_basic_fields():
    items = to_csl_json([WORK])
    assert len(items) == 1
    item = items[0]
    assert item["type"] == "article-journal"
    assert item["title"] == "Thriving at work"
    assert item["DOI"] == "10.1177/0149206311425615"
    assert item["issued"]["date-parts"] == [[2012]]
    assert item["author"][0]["family"] == "Porath"
    assert item["author"][0]["given"] == "Christine L."


def test_csl_json_string_is_valid_json():
    parsed = json.loads(csl_json_string([WORK, PREPRINT]))
    assert isinstance(parsed, list) and len(parsed) == 2


def test_zotero_journal_item():
    item = work_to_zotero_item(WORK)
    assert item["itemType"] == "journalArticle"
    assert item["publicationTitle"] == "Journal of Organizational Behavior"
    assert item["volume"] == "33"
    assert item["DOI"] == "10.1177/0149206311425615"
    creators = item["creators"]
    assert creators[0]["lastName"] == "Porath"
    assert creators[0]["firstName"] == "Christine L."
    assert creators[0]["creatorType"] == "author"


def test_zotero_preprint_item():
    item = work_to_zotero_item(PREPRINT)
    assert item["itemType"] == "preprint"
    assert item["archiveID"] == "arXiv:2311.07072"


def test_zotero_collection_assignment():
    item = work_to_zotero_item(WORK, collection_key="ABC123")
    assert item["collections"] == ["ABC123"]


def test_zotero_drops_empty_fields():
    bare = Work(title="No metadata", type="article")
    item = work_to_zotero_item(bare)
    # Empty strings should be stripped so Zotero doesn't choke.
    assert "DOI" not in item
    assert item["title"] == "No metadata"
