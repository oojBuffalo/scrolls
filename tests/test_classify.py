"""Tests for the rules classification engine (IDEAS.md §8, ADR 0004).

Deterministic, offline: category comes from source defaults, title
patterns, and URL shape — no LLM, no network.
"""

from scrolls.classify import (
    RULESET_FINGERPRINT,
    classification_freshness,
    classify_item,
    is_stale_classification,
    stale_classifications,
)
from scrolls.items import ScrollItem, classification_view


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


def test_biorxiv_and_medrxiv_classify_as_paper():
    # the preprint servers are arXiv's biology/medicine siblings (ADR 0068)
    for source in ("biorxiv", "medrxiv"):
        item = make_item(
            source=source,
            source_id="10.1101/2020.03.20.001008",
            title="A SARS-CoV-2 preprint",
        )
        assert classify_item(item).category == "paper"


def test_pubmed_classifies_as_paper():
    # PubMed indexes biomedical papers — the arXiv/Crossref sibling (ADR 0065)
    item = make_item(
        source="pubmed",
        source_id="22745249",
        title="A programmable dual-RNA-guided DNA endonuclease",
    )
    assert classify_item(item).category == "paper"


def test_rfc_classifies_as_reference():
    # an RFC is a normative spec used as a reference, like a wikipedia article
    # (ADR 0066), not a paper to cite
    item = make_item(
        source="rfc", source_id="9110", title="RFC 9110: HTTP Semantics"
    )
    assert classify_item(item).category == "reference"


def test_github_is_project():
    item = make_item(source="github", source_id="oojBuffalo/scrolls",
                     title="oojBuffalo/scrolls")
    assert classify_item(item).category == "project"


def test_github_issue_and_pr_are_not_projects():
    # A discussion thread (`owner/repo#<n>`) is heterogeneous — bug, feature,
    # question, design — so it stays unclassified like HN/Lobsters/Discourse,
    # not the repo's `project` (ADR 0084). Title rules can still fire below.
    issue = make_item(source="github", source_id="oojBuffalo/scrolls#7",
                      title="FTS5 ranking returns stale results")
    assert classify_item(issue).category is None
    pr = make_item(source="github", source_id="oojBuffalo/scrolls#12",
                   title="Add faceted search")
    assert classify_item(pr).category is None


def test_github_issue_still_obeys_title_rules():
    # the curated `project` no longer pre-empts a "how to" thread title
    item = make_item(source="github", source_id="oojBuffalo/scrolls#9",
                     title="How to rebuild the FTS index")
    assert classify_item(item).category == "tutorial"


def test_gitlab_is_project():
    item = make_item(source="gitlab", source_id="inkscape/inkscape",
                     title="inkscape/inkscape")
    assert classify_item(item).category == "project"


def test_gitlab_issue_and_merge_request_are_not_projects():
    # GitLab mirrors github (ADR 0085): an issue (`group/project#<n>`) or a
    # merge request (`group/project!<n>`) is a heterogeneous discussion thread,
    # so it stays unclassified like the repo's siblings, not `project`. The two
    # markers (#/!) both carve out — GitLab's separate iid sequences.
    issue = make_item(source="gitlab", source_id="gitlab-org/gitlab#7",
                      title="FTS5 ranking returns stale results")
    assert classify_item(issue).category is None
    mr = make_item(source="gitlab", source_id="gitlab-org/gitlab!42",
                   title="Add faceted search")
    assert classify_item(mr).category is None


def test_gitlab_thread_still_obeys_title_rules():
    # the curated `project` no longer pre-empts a "how to" thread title
    item = make_item(source="gitlab", source_id="gitlab-org/gitlab#9",
                     title="How to rebuild the FTS index")
    assert classify_item(item).category == "tutorial"


def test_gitea_is_project():
    item = make_item(source="gitea", source_id="codeberg.org/forgejo/forgejo",
                     title="forgejo/forgejo")
    assert classify_item(item).category == "project"


def test_gitea_issue_and_pull_request_are_not_projects():
    # Gitea mirrors github (ADR 0086): an issue or PR (`<host>/<owner>/<repo>#<n>`)
    # is a heterogeneous discussion thread, so it stays unclassified like the
    # repo's siblings, not `project`. Gitea unifies numbering, so one `#` marker
    # carves out (not gitlab's two).
    issue = make_item(source="gitea", source_id="codeberg.org/forgejo/forgejo#7",
                      title="FTS5 ranking returns stale results")
    assert classify_item(issue).category is None
    pr = make_item(source="gitea", source_id="codeberg.org/forgejo/forgejo#12",
                   title="Add faceted search")
    assert classify_item(pr).category is None


def test_gitea_thread_still_obeys_title_rules():
    # the curated `project` no longer pre-empts a "how to" thread title
    item = make_item(source="gitea", source_id="codeberg.org/forgejo/forgejo#9",
                     title="How to rebuild the FTS index")
    assert classify_item(item).category == "tutorial"


def test_bitbucket_is_project():
    item = make_item(source="bitbucket", source_id="atlassian/python-bitbucket",
                     title="atlassian/python-bitbucket")
    assert classify_item(item).category == "project"


def test_bitbucket_issue_and_pull_request_are_not_projects():
    # Bitbucket mirrors gitlab (ADR 0087): an issue (`workspace/repo#<n>`) or a
    # pull request (`workspace/repo!<n>`) is a heterogeneous discussion thread,
    # so it stays unclassified, not `project`. Bitbucket splits numbering, so the
    # two markers (#/!) both carve out.
    issue = make_item(source="bitbucket", source_id="atlassian/aui#7",
                      title="FTS5 ranking returns stale results")
    assert classify_item(issue).category is None
    pr = make_item(source="bitbucket", source_id="atlassian/aui!42",
                   title="Add faceted search")
    assert classify_item(pr).category is None


def test_bitbucket_thread_still_obeys_title_rules():
    # the curated `project` no longer pre-empts a "how to" thread title
    item = make_item(source="bitbucket", source_id="atlassian/aui!9",
                     title="How to rebuild the FTS index")
    assert classify_item(item).category == "tutorial"


def test_crossref_is_paper():
    # A Crossref work is a published paper, arXiv's preprint sibling.
    item = make_item(source="crossref", title="node2vec: Scalable Feature Learning")
    assert classify_item(item).category == "paper"


def _datacite_item(resource_type, **overrides):
    # A `doi.org` item the DataCite adapter answered: source stays `crossref`,
    # the resource type rides in provenance (ADR 0045).
    provenance = {"adapter": "datacite", "resource_type": resource_type}
    return make_item(source="crossref", provenance=provenance, **overrides)


def test_datacite_dataset_is_a_dataset():
    # A DataCite dataset is exactly the IDEAS.md §8 `dataset` category — not a
    # paper, unlike its Crossref sibling.
    item = _datacite_item("Dataset", title="Global Coastal Biodiversity Survey")
    assert classify_item(item).category == "dataset"


def test_datacite_software_is_a_tool():
    item = _datacite_item("Software", title="scrolls")
    assert classify_item(item).category == "tool"


def test_datacite_text_is_a_paper():
    item = _datacite_item("Text", title="A taxonomic treatment")
    assert classify_item(item).category == "paper"


def test_datacite_image_is_media():
    item = _datacite_item("Image", title="Specimen photograph")
    assert classify_item(item).category == "media"


def test_datacite_unmapped_type_stays_unclassified():
    # An ambiguous type (Collection, Other, …) is not guessed.
    item = _datacite_item("Collection", title="A grab bag")
    assert classify_item(item).category is None


def test_datacite_missing_resource_type_stays_unclassified():
    # A DataCite record with no resourceTypeGeneral (the adapter writes "")
    # has no honest category to assign.
    item = _datacite_item("", title="A typeless deposit")
    assert classify_item(item).category is None


def test_datacite_resource_type_beats_title_pattern():
    # A dataset whose title reads like a tutorial is still a dataset.
    item = _datacite_item("Dataset", title="A Practical Guide to Coral Reefs")
    assert classify_item(item).category == "dataset"


def _zenodo_item(resource_type, **overrides):
    # A Zenodo deposit the adapter fetched: the upload type rides in provenance
    # (ADR 0083), the DataCite mechanism with the Zenodo vocabulary.
    provenance = {"adapter": "zenodo", "resource_type": resource_type}
    return make_item(source="zenodo", source_id="7834392", provenance=provenance, **overrides)


def test_zenodo_dataset_is_a_dataset():
    item = _zenodo_item("dataset", title="A large-scale COVID-19 Twitter chatter dataset")
    assert classify_item(item).category == "dataset"


def test_zenodo_software_is_a_tool():
    item = _zenodo_item("software", title="scrolls")
    assert classify_item(item).category == "tool"


def test_zenodo_publication_is_a_paper():
    item = _zenodo_item("publication", title="A taxonomic treatment")
    assert classify_item(item).category == "paper"


def test_zenodo_image_and_video_are_media():
    for resource_type in ("image", "video"):
        item = _zenodo_item(resource_type, title="A figure")
        assert classify_item(item).category == "media"


def test_zenodo_ambiguous_type_stays_unclassified():
    # A poster/presentation/lesson is not guessed — DataCite's honesty rule.
    item = _zenodo_item("poster", title="A conference poster")
    assert classify_item(item).category is None


def test_zenodo_unfetched_deposit_stays_unclassified():
    # Detected but not yet fetched: no resource type is known, so no category.
    item = make_item(source="zenodo", source_id="7834392", provenance=None, title="A deposit")
    assert classify_item(item).category is None


def test_zenodo_resource_type_beats_title_pattern():
    # A dataset whose title reads like a tutorial is still a dataset.
    item = _zenodo_item("dataset", title="Getting Started with the COVID-19 Corpus")
    assert classify_item(item).category == "dataset"


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


def test_maven_artifact_is_a_tool():
    # A Maven Central artifact is a published JVM package you depend on (ADR 0092).
    item = make_item(source="maven", source_id="com.google.guava:guava",
                     title="Guava: Google Core Libraries for Java")
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


def test_huggingface_space_is_a_tool():
    # A Hugging Face Space is a hosted demo/app you use, a tool like a model.
    item = make_item(
        source="huggingface",
        source_id="space:HuggingFaceH4/zephyr-chat",
        title="Zephyr Chat",
    )
    assert classify_item(item).category == "tool"


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


def test_lobsters_stays_unclassified_like_hacker_news():
    # Lobsters is a heterogeneous link aggregator like Hacker News (ADR 0046):
    # a saved story has no single honest category, so — unlike Stack Exchange's
    # weak `reference` default — there is no source default; the title rules
    # and the LLM engine decide.
    item = make_item(source="lobsters", title="German court ruling on AI Overviews")
    assert classify_item(item).category is None


def test_lobsters_tutorial_title_still_wins():
    item = make_item(source="lobsters", title="A guide to writing a SQLite VFS")
    assert classify_item(item).category == "tutorial"


def test_bluesky_stays_unclassified_like_hacker_news():
    # A Bluesky post is a heterogeneous social entry like a Hacker News or
    # Lobsters story (ADR 0048): no single honest category, so no source
    # default — the title rules and the LLM engine decide.
    item = make_item(source="bluesky", title="Alice: shipping a new local-first sync engine today")
    assert classify_item(item).category is None


def test_bluesky_tutorial_title_still_wins():
    item = make_item(source="bluesky", title="Bob: a guide to writing a SQLite VFS, a thread 🧵")
    assert classify_item(item).category == "tutorial"


def test_devto_stays_unclassified_like_hacker_news():
    # dev.to is a heterogeneous blogging platform (ADR 0061): a post can be a
    # tutorial, an opinion, or a show-and-tell, so there is no honest source
    # default — the title rules and the LLM engine decide.
    item = make_item(source="devto", title="What was your win this week?")
    assert classify_item(item).category is None


def test_devto_tutorial_title_still_wins():
    item = make_item(source="devto", title="Getting started with the SEC EDGAR API in Python")
    assert classify_item(item).category == "tutorial"


def test_lemmy_stays_unclassified_like_hacker_news():
    # Lemmy is a federated link aggregator like Hacker News/Lobsters (ADR 0052):
    # a saved post has no single honest category, so no source default — the
    # title rules and the LLM engine decide.
    item = make_item(source="lemmy", title="Rust 2.0 will never happen — and that's fine")
    assert classify_item(item).category is None


def test_lemmy_tutorial_title_still_wins():
    item = make_item(source="lemmy", title="A guide to self-hosting your own Lemmy instance")
    assert classify_item(item).category == "tutorial"


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


# --- re-derivable method: precedence tier + ruleset fingerprint (H20) ------
#
# `classified_by` names the engine; H20 adds the two facts a re-classify needs
# to be reproducible and auditable: which precedence *tier* fired
# (`classified_basis`, closing the H19 gap) and the ruleset fingerprint the run
# used (`classified_ruleset`). Both are deterministic, so a re-classify of an
# unchanged library reproduces them field-for-field.


def test_curated_source_records_the_curated_basis():
    classified = classify_item(make_item(source="wikipedia", title="SQLite"))
    assert classified.category == "reference"
    assert classified.provenance["classified_basis"] == "curated-source"


def test_title_pattern_records_the_title_basis():
    classified = classify_item(make_item(title="A Tutorial on FTS5"))
    assert classified.category == "tutorial"
    assert classified.provenance["classified_basis"] == "title-pattern"


def test_documentation_url_records_the_url_basis():
    classified = classify_item(
        make_item(title="Reference", url="https://docs.python.org/3/library/sqlite3.html")
    )
    assert classified.category == "documentation"
    assert classified.provenance["classified_basis"] == "documentation-url"


def test_weak_source_records_the_weak_basis():
    # a youtube item with no title rule falls through to the weak source default
    classified = classify_item(make_item(source="youtube", title=None))
    assert classified.category == "media"
    assert classified.provenance["classified_basis"] == "weak-source"


def test_every_classified_item_records_the_ruleset_fingerprint():
    classified = classify_item(make_item(source="wikipedia", title="SQLite"))
    assert classified.provenance["classified_ruleset"] == RULESET_FINGERPRINT
    # the fingerprint is a short stable digest, not the whole ruleset
    assert isinstance(RULESET_FINGERPRINT, str) and len(RULESET_FINGERPRINT) == 12


def test_method_fields_are_deterministically_re_derivable():
    # re-running the engine reproduces basis + ruleset field-for-field; a
    # re-classify is a no-op in result (the H19 contract, now with finer method)
    item = make_item(title="A Tutorial on FTS5")
    first = classify_item(item)
    assert classify_item(item) == first
    refed = classify_item(first)
    assert refed.provenance["classified_basis"] == first.provenance["classified_basis"]
    assert refed.provenance["classified_ruleset"] == first.provenance["classified_ruleset"]
    assert list(refed.provenance).count("classified_basis") == 1


def test_unmatched_item_records_no_basis_or_ruleset():
    # honest absence: nothing matched, so no method facts are claimed
    item = make_item(title="An ordinary post")
    classified = classify_item(item)
    assert classified.category is None
    assert "classified_basis" not in (classified.provenance or {})
    assert "classified_ruleset" not in (classified.provenance or {})


# --- the stale-ruleset selector: shared by doctor + `classify --stale` (H27) -
#
# `is_stale_classification` is the one definition behind doctor's
# `custody.enrichment.stale` report and the `scrolls classify --stale` refresh
# pool, so the count doctor shows equals the count a refresh acts on.


def _with_provenance(**stamps):
    base = {"adapter": "web", "fetched_at": "2026-06-12T00:00:00+00:00"}
    return make_item(category="reference", provenance={**base, **stamps})


def test_stale_classification_is_a_superseded_rules_fingerprint():
    item = _with_provenance(classified_by="rules-v1", classified_ruleset="deadbeef0000")
    assert is_stale_classification(item) is True


def test_current_ruleset_classification_is_not_stale():
    item = _with_provenance(
        classified_by="rules-v1", classified_ruleset=RULESET_FINGERPRINT)
    assert is_stale_classification(item) is False


def test_unfingerprinted_classification_is_not_stale():
    # pre-H20: an engine stamp but no ruleset — unknown, not stale
    item = _with_provenance(classified_by="rules-v1")
    assert is_stale_classification(item) is False


def test_llm_classification_is_never_stale():
    # the ruleset fingerprint is a rules-engine concept; the LLM axis is out
    item = _with_provenance(classified_by="llm-v1", classified_ruleset="deadbeef0000")
    assert is_stale_classification(item) is False


def test_user_set_category_carrying_no_stamp_is_not_stale():
    # a hand-set category has no engine stamp (overrides), so it never qualifies
    item = make_item(category="tool", provenance={"adapter": "web"})
    assert is_stale_classification(item) is False
    assert is_stale_classification(make_item(category="tool", provenance=None)) is False


# --- `stale_classifications`: the (optionally per-source) refresh pool (H154) --
#
# The one selector behind `scrolls classify --stale` (whole-library) and its
# per-source narrowing `classify --stale --source <S>`. Whole-library it is
# exactly `is_stale_classification` filtered nowhere; per-source it intersects
# with one source, so its count equals doctor's `custody.enrichment.by_source[S]`
# by construction. A pure selector, so it can re-derive that count independently.


def _stale(item_id, source, *, ruleset="deadbeef0000"):
    return make_item(
        id=item_id, source=source, category="reference",
        provenance={"classified_by": "rules-v1", "classified_ruleset": ruleset},
    )


def test_stale_classifications_whole_library_is_exactly_the_stale_set():
    items = [
        _stale("web:1", "web"),
        _stale("web:2", "web", ruleset=RULESET_FINGERPRINT),  # current — excluded
        _stale("arxiv:1", "arxiv"),
        make_item(id="web:plain", category="tool", provenance={"adapter": "web"}),
    ]
    selected = stale_classifications(items)
    assert [item.id for item in selected] == ["web:1", "arxiv:1"]
    # exactly the `is_stale_classification` set, order preserved
    assert selected == [item for item in items if is_stale_classification(item)]


def test_stale_classifications_per_source_intersects_one_source():
    items = [
        _stale("web:1", "web"),
        _stale("web:2", "web"),
        _stale("arxiv:1", "arxiv"),
    ]
    assert [item.id for item in stale_classifications(items, source="web")] == [
        "web:1", "web:2"
    ]
    assert [item.id for item in stale_classifications(items, source="arxiv")] == [
        "arxiv:1"
    ]


def test_stale_classifications_per_source_count_matches_a_grouped_re_derivation():
    # the H154 convergence at the pure layer: the per-source count equals an
    # independent re-derivation via `is_stale_classification` grouped by source
    # (the predicate doctor's `enrichment.by_source` is built from).
    items = [
        _stale("web:1", "web"),
        _stale("web:2", "web"),
        _stale("web:cur", "web", ruleset=RULESET_FINGERPRINT),  # current
        _stale("arxiv:1", "arxiv"),
    ]
    by_source: dict[str, int] = {}
    for item in items:
        if is_stale_classification(item):
            by_source[item.source] = by_source.get(item.source, 0) + 1
    for source, count in by_source.items():
        assert len(stale_classifications(items, source=source)) == count
    assert by_source == {"web": 2, "arxiv": 1}


def test_stale_classifications_unknown_source_is_an_empty_no_op():
    # sources are open-ended: one nothing stale is held for selects nothing,
    # never an error (the honest no-op `--source` gives the CLI)
    items = [_stale("web:1", "web"), _stale("arxiv:1", "arxiv")]
    assert stale_classifications(items, source="reddit") == []


def test_stale_classifications_excludes_current_unfingerprinted_llm_and_override():
    # each non-stale shape stays out, whether or not a source is named
    items = [
        _stale("web:cur", "web", ruleset=RULESET_FINGERPRINT),  # current
        make_item(id="web:unf", source="web", category="reference",
                  provenance={"classified_by": "rules-v1"}),  # unfingerprinted
        make_item(id="web:llm", source="web", category="reference",
                  provenance={"classified_by": "llm-v1",
                              "classified_ruleset": "deadbeef0000"}),  # llm axis
        make_item(id="web:override", source="web", category="tool",
                  provenance={"adapter": "web"}),  # hand-set, no engine stamp
    ]
    assert stale_classifications(items) == []
    assert stale_classifications(items, source="web") == []


# --- the freshness primitive: one home behind doctor + the H21 marker ---------
#
# `classification_freshness` is the single derivation `is_stale_classification`,
# `doctor`'s `custody.enrichment` aggregate, and the per-item confidence marker
# all read, so the recency signal an agent sees on a hit can never disagree with
# the count doctor reports or the pool a refresh acts on.


def test_freshness_current_under_the_live_ruleset():
    prov = {"classified_by": "rules-v1", "classified_ruleset": RULESET_FINGERPRINT}
    assert classification_freshness(prov) == "current"


def test_freshness_stale_under_a_superseded_ruleset():
    prov = {"classified_by": "rules-v1", "classified_ruleset": "deadbeef0000"}
    assert classification_freshness(prov) == "stale"


def test_freshness_unknown_when_unfingerprinted():
    # pre-H20: a rules stamp but no fingerprint — we cannot tell, so not "current"
    assert classification_freshness({"classified_by": "rules-v1"}) == "unknown"


def test_freshness_is_none_for_a_non_rules_classification():
    # an LLM category has no rules ruleset to compare against — no claim is made
    assert classification_freshness({"classified_by": "llm-v1"}) is None
    # a hand-set or unclassified item carries no engine stamp at all
    assert classification_freshness({"adapter": "web"}) is None
    assert classification_freshness(None) is None


def test_is_stale_agrees_with_freshness():
    # the selector is exactly freshness == "stale", so the two never diverge
    for prov in (
        {"classified_by": "rules-v1", "classified_ruleset": "deadbeef0000"},
        {"classified_by": "rules-v1", "classified_ruleset": RULESET_FINGERPRINT},
        {"classified_by": "rules-v1"},
        {"classified_by": "llm-v1", "classified_ruleset": "deadbeef0000"},
        None,
    ):
        item = make_item(category="reference", provenance=prov)
        assert is_stale_classification(item) == (classification_freshness(prov) == "stale")


# --- the per-item confidence marker rides the classification view (H21) -------
#
# Every present `classification_view` carries a derived `confidence` marker so an
# agent reading a category knows how much to trust it: `level` (deterministic
# rule vs inferred LLM) and, where it can be answered, `freshness` against the
# live ruleset. Derived in one home, so it travels every surface identically.


def test_view_confidence_is_deterministic_and_current_for_a_live_rules_match():
    view = classification_view(
        {"classified_by": "rules-v1", "classified_basis": "curated-source",
         "classified_ruleset": RULESET_FINGERPRINT}
    )
    assert view["confidence"] == {"level": "deterministic", "freshness": "current"}


def test_view_confidence_marks_a_superseded_rules_match_stale():
    view = classification_view(
        {"classified_by": "rules-v1", "classified_ruleset": "deadbeef0000"}
    )
    assert view["confidence"] == {"level": "deterministic", "freshness": "stale"}


def test_view_confidence_marks_an_unfingerprinted_rules_match_unknown():
    view = classification_view({"classified_by": "rules-v1"})
    assert view["confidence"] == {"level": "deterministic", "freshness": "unknown"}


def test_view_confidence_for_the_llm_engine_is_inferred_with_no_freshness():
    # honest absence: no ruleset to compare, and a timestamp would break the
    # idempotence contract — so no freshness is claimed for an LLM category
    view = classification_view(
        {"classified_by": "llm-v1", "classified_model": "claude-x"}
    )
    assert view["confidence"] == {"level": "inferred"}
    assert "freshness" not in view["confidence"]


def test_a_freshly_classified_item_carries_a_current_confidence_marker():
    # the end-to-end path: classify_item stamps under the live ruleset, so the
    # derived marker reads current — the marker and the engine agree by construction
    classified = classify_item(make_item(source="wikipedia", title="SQLite"))
    view = classification_view(classified.provenance)
    assert view["confidence"] == {"level": "deterministic", "freshness": "current"}


def test_unclassified_and_user_set_items_carry_no_view_and_no_marker():
    # no engine stamp → no view at all, so no confidence is claimed (honest absence)
    assert classification_view(None) is None
    assert classification_view({"adapter": "web"}) is None
