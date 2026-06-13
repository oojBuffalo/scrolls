"""Tests for the rules classification engine (IDEAS.md §8, ADR 0004).

Deterministic, offline: category comes from source defaults, title
patterns, and URL shape — no LLM, no network.
"""

from scrolls.classify import classify_item
from scrolls.items import ScrollItem


def make_item(**overrides):
    base = dict(
        id="web:3f1a2b3c4d5e",
        source="web",
        source_id=None,
        url="https://blog.example.com/post",
        saved_at="2026-06-12T00:00:00+00:00",
        title="An ordinary post",
        stage="fetched",
        provenance={"adapter": "web", "fetched_at": "2026-06-12T00:00:00+00:00"},
    )
    base.update(overrides)
    return ScrollItem(**base)


def test_wikipedia_is_reference():
    item = make_item(source="wikipedia", title="SQLite")
    assert classify_item(item).category == "reference"


def test_arxiv_is_paper():
    item = make_item(source="arxiv", title="Attention Is All You Need")
    assert classify_item(item).category == "paper"


def test_github_is_project():
    item = make_item(source="github", title="oojBuffalo/scrolls")
    assert classify_item(item).category == "project"


def test_crossref_is_paper():
    # A Crossref work is a published paper, arXiv's preprint sibling.
    item = make_item(source="crossref", title="node2vec: Scalable Feature Learning")
    assert classify_item(item).category == "paper"


def test_pypi_is_a_tool():
    # A published package is something you install and use, not a repo to read.
    item = make_item(source="pypi", title="rich")
    assert classify_item(item).category == "tool"


def test_npm_is_a_tool():
    # An npm package is a published thing you install and use, like a PyPI one.
    item = make_item(source="npm", title="express")
    assert classify_item(item).category == "tool"


def test_crates_is_a_tool():
    # A crates.io crate is a published package you install, like PyPI and npm.
    item = make_item(source="crates", title="serde")
    assert classify_item(item).category == "tool"


def test_packagist_is_a_tool():
    # A Composer package is a published thing you install, like PyPI/npm/crates.
    item = make_item(source="packagist", title="monolog/monolog")
    assert classify_item(item).category == "tool"


def test_rubygems_is_a_tool():
    # A gem is a published thing you install, like PyPI/npm/crates/Packagist.
    item = make_item(source="rubygems", title="rails")
    assert classify_item(item).category == "tool"


def test_go_module_is_a_tool():
    # A Go module is a published package you import and use, like the others.
    item = make_item(source="go", source_id="github.com/gin-gonic/gin",
                     title="github.com/gin-gonic/gin")
    assert classify_item(item).category == "tool"


def test_huggingface_model_is_a_tool():
    # A Hugging Face model is a published artifact you install and use,
    # like a package; the repo kind rides in the source id.
    item = make_item(
        source="huggingface",
        source_id="model:google-bert/bert-base-uncased",
        title="google-bert/bert-base-uncased",
    )
    assert classify_item(item).category == "tool"


def test_huggingface_dataset_is_a_dataset():
    # A Hugging Face dataset is exactly the IDEAS.md §8 `dataset` category.
    item = make_item(
        source="huggingface",
        source_id="dataset:rajpurkar/squad",
        title="SQuAD",
    )
    assert classify_item(item).category == "dataset"


def test_huggingface_repo_kind_beats_title_pattern():
    # A model card titled like a tutorial is still a tool, not a tutorial.
    item = make_item(
        source="huggingface",
        source_id="model:org/getting-started-with-llms",
        title="Getting Started with LLMs",
    )
    assert classify_item(item).category == "tool"


def test_curated_platform_default_beats_title_pattern():
    # A wikipedia page titled like a tutorial is still an encyclopedia entry.
    item = make_item(source="wikipedia", title="How to Solve It")
    assert classify_item(item).category == "reference"


def test_tutorial_title_pattern():
    for title in (
        "How to build a CLI in Python",
        "Getting started with SQLite FTS5",
        "A Practical Guide to BM25",
        "FTS5 tutorial for beginners",
    ):
        assert classify_item(make_item(title=title)).category == "tutorial", title


def test_opinion_title_pattern():
    item = make_item(title="Why I left my job to build local-first tools")
    assert classify_item(item).category == "opinion"


def test_show_hn_title_is_a_project():
    item = make_item(
        source="hackernews",
        title="Show HN: A local-first knowledge library for agents",
    )
    assert classify_item(item).category == "project"


def test_ask_hn_stays_unclassified():
    # Ask HN is a question, not a category the rules can honestly name.
    item = make_item(source="hackernews", title="Ask HN: how do you take notes?")
    assert classify_item(item).category is None


def test_docs_url_is_documentation():
    for url in (
        "https://docs.python.org/3/library/sqlite3.html",
        "https://example.com/docs/getting-started",  # /docs/ path, generic title
        "https://trafilatura.readthedocs.io/en/latest/",
    ):
        item = make_item(url=url, title="sqlite3 module reference")
        assert classify_item(item).category == "documentation", url


def test_tutorial_title_beats_docs_url():
    # Title is more specific than URL shape.
    item = make_item(
        url="https://docs.python.org/3/tutorial/index.html",
        title="The Python Tutorial",
    )
    assert classify_item(item).category == "tutorial"


def test_youtube_defaults_to_media_but_title_wins():
    video = make_item(source="youtube", title="Me at the zoo")
    assert classify_item(video).category == "media"

    howto = make_item(source="youtube", title="How to use SQLite FTS5")
    assert classify_item(howto).category == "tutorial"


def test_stackexchange_defaults_to_reference_but_title_wins():
    question = make_item(source="stackexchange", title="Why is a sorted array faster?")
    assert classify_item(question).category == "reference"

    howto = make_item(source="stackexchange", title="How to merge two dicts in Python")
    assert classify_item(howto).category == "tutorial"


def test_unmatched_web_item_stays_unclassified():
    item = make_item(title="An ordinary post")
    classified = classify_item(item)
    assert classified.category is None
    # nothing matched, so the engine leaves no provenance stamp either
    assert classified == item


def test_classification_is_stamped_in_provenance():
    classified = classify_item(make_item(source="wikipedia", title="SQLite"))
    assert classified.provenance["classified_by"] == "rules-v1"
    # fetch provenance is preserved, not replaced
    assert classified.provenance["adapter"] == "web"


def test_input_item_is_never_mutated():
    item = make_item(source="wikipedia", title="SQLite")
    classify_item(item)
    assert item.category is None
    assert "classified_by" not in item.provenance


def test_titleless_item_falls_back_to_source_rules():
    item = make_item(source="youtube", title=None)
    assert classify_item(item).category == "media"
