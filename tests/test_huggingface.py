"""Tests for the Hugging Face fetch adapter (IDEAS.md §6, ADR 0041).

Both transports are faked: a metadata document recorded (and trimmed) from
the real Hub API (`huggingface.co/api/models|datasets/<id>`) and a card
README recorded from the repo's `raw/main/README.md`. So the model/dataset
field mapping, the card frontmatter stripping, the author-declared
concepts/tags split, the `arxiv:`/`dataset:` tags that become cross-source
links, graceful degradation when no README exists, and error handling are
all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.huggingface import fetch_item


# Recorded (and trimmed) from https://huggingface.co/api/models/google-bert/bert-base-uncased
MODEL_DOC = {
    "id": "google-bert/bert-base-uncased",
    "modelId": "google-bert/bert-base-uncased",
    "author": "google-bert",
    "sha": "86b5e0934494bd15c9632b12f734a8a67f723594",
    "pipeline_tag": "fill-mask",
    "library_name": "transformers",
    "tags": [
        "transformers", "pytorch", "safetensors", "bert", "fill-mask",
        "exbert", "en", "dataset:bookcorpus", "dataset:wikipedia",
        "arxiv:1810.04805", "license:apache-2.0", "endpoints_compatible",
        "region:us",
    ],
    "downloads": 41836153,
    "likes": 2682,
    "private": False,
    "gated": False,
    "createdAt": "2022-03-02T23:29:04.000Z",
    "lastModified": "2024-02-19T11:06:12.000Z",
    "cardData": {
        "language": "en",
        "tags": ["exbert"],
        "license": "apache-2.0",
        "datasets": ["bookcorpus", "wikipedia"],
    },
    # heavy fields the adapter drops from raw_text
    "siblings": [{"rfilename": "README.md"}, {"rfilename": "model.safetensors"}],
    "config": {"architectures": ["BertForMaskedLM"]},
}

# Recorded (and trimmed) from the repo's raw/main/README.md
MODEL_README = """\
---
language: en
tags:
- exbert
license: apache-2.0
datasets:
- bookcorpus
- wikipedia
---

# BERT base model (uncased)

Pretrained model on English language using a masked language modeling (MLM)
objective. It was introduced in [this paper](https://arxiv.org/abs/1810.04805)
and first released in [this repository](https://github.com/google-research/bert).

## Model description

BERT is a transformers model pretrained on a large corpus of English data.
"""

# Recorded (and trimmed) from https://huggingface.co/api/datasets/rajpurkar/squad
DATASET_DOC = {
    "id": "rajpurkar/squad",
    "author": "rajpurkar",
    "sha": "7b6d24c440a36b6815f21b70d25016731768db1f",
    "description": "Stanford Question Answering Dataset (SQuAD) is a reading "
    "comprehension dataset, consisting of questions posed by crowdworkers on a "
    "set of Wikipedia articles.",
    "tags": [
        "task_categories:question-answering", "task_ids:extractive-qa",
        "language:en", "license:cc-by-sa-4.0", "size_categories:10K<n<100K",
        "arxiv:1606.05250", "region:us",
    ],
    "downloads": 147602,
    "likes": 367,
    "createdAt": "2022-03-02T23:29:22.000Z",
    "lastModified": "2024-03-04T13:54:37.000Z",
    "cardData": {
        "license": "cc-by-sa-4.0",
        "language": ["en"],
        "task_categories": ["question-answering"],
        "task_ids": ["extractive-qa"],
        "pretty_name": "SQuAD",
        "tags": ["wikipedia-derived"],
    },
}

DATASET_README = """\
---
license: cc-by-sa-4.0
pretty_name: SQuAD
---

# Dataset Card for SQuAD

SQuAD is a reading comprehension dataset.
"""


def make_model(**overrides):
    base = dict(
        id="huggingface:model:google-bert/bert-base-uncased",
        source="huggingface",
        source_id="model:google-bert/bert-base-uncased",
        url="https://huggingface.co/google-bert/bert-base-uncased",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def make_dataset(**overrides):
    base = dict(
        id="huggingface:dataset:rajpurkar/squad",
        source="huggingface",
        source_id="dataset:rajpurkar/squad",
        url="https://huggingface.co/datasets/rajpurkar/squad",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_json(doc):
    def get_json(url):
        return json.loads(json.dumps(doc))  # deep copy

    return get_json


def fake_text(readme):
    def get_text(url):
        return readme

    return get_text


def fetch_model(doc=MODEL_DOC, readme=MODEL_README, item=None):
    return fetch_item(
        item or make_model(), get_json=fake_json(doc), get_text=fake_text(readme)
    )


def fetch_dataset(doc=DATASET_DOC, readme=DATASET_README, item=None):
    return fetch_item(
        item or make_dataset(), get_json=fake_json(doc), get_text=fake_text(readme)
    )


# --- models -------------------------------------------------------------


def test_fetch_model_maps_metadata():
    fetched = fetch_model()

    assert fetched.title == "google-bert/bert-base-uncased"
    assert fetched.author == "google-bert"
    # createdAt (the repo's publication) normalizes to UTC ISO 8601
    assert fetched.published_at == "2022-03-02T23:29:04+00:00"
    assert fetched.canonical_url == "https://huggingface.co/google-bert/bert-base-uncased"
    assert fetched.provenance["adapter"] == "huggingface"
    assert fetched.provenance["extraction_method"] == "huggingface-api:json+card"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_model_card_is_extracted_text_with_frontmatter_stripped():
    fetched = fetch_model()
    # the YAML frontmatter block is dropped; the prose card is the body
    assert fetched.extracted_text.startswith("# BERT base model (uncased)")
    assert "language: en" not in fetched.extracted_text
    assert "BERT is a transformers model" in fetched.extracted_text


def test_model_summary_is_the_card_lead_paragraph():
    # models have no description field; the card's first prose paragraph
    # (after the heading) becomes the summary, soft-wraps collapsed
    summary = fetch_model().summary
    assert summary.startswith("Pretrained model on English language")
    assert "\n" not in summary


def test_model_concepts_are_task_plus_card_tags():
    # the pipeline_tag (the task) and the author's cardData.tags feed the
    # concept graph (the github-topics parallel); the noisy flat tag soup
    # (frameworks, region, file formats) is deliberately not mined
    assert fetch_model().concepts == ("fill-mask", "exbert")


def test_model_tags_are_library_and_license():
    assert fetch_model().tags == ("transformers", "apache-2.0")


def test_model_arxiv_and_dataset_tags_become_links():
    links = fetch_model().links
    # the headline cross-source edge: an arxiv: tag -> arxiv.org/abs link,
    # which `scrolls related` resolves to the saved arXiv paper (ADR 0038 kin)
    assert "https://arxiv.org/abs/1810.04805" in links
    # dataset: tags -> the dataset's Hub page (the model<->dataset edge)
    assert "https://huggingface.co/datasets/bookcorpus" in links
    assert "https://huggingface.co/datasets/wikipedia" in links


def test_base_model_tag_becomes_a_lineage_link():
    # a fine-tune declares its base model both bare and with a relation;
    # both forms resolve to one model<->base-model lineage link
    doc = json.loads(json.dumps(MODEL_DOC))
    doc["tags"] += [
        "base_model:meta-llama/Llama-3.1-8B",
        "base_model:finetune:meta-llama/Llama-3.1-8B",
    ]
    links = fetch_model(doc).links
    assert links.count("https://huggingface.co/meta-llama/Llama-3.1-8B") == 1


def test_base_model_relation_only_fragment_is_dropped():
    # a malformed base_model: tag with no org/name is not turned into junk
    doc = json.loads(json.dumps(MODEL_DOC))
    doc["tags"] += ["base_model:finetune"]
    assert not any(link.endswith("/finetune") for link in fetch_model(doc).links)


def test_model_without_a_readme_degrades_to_metadata_only():
    def no_card(url):
        raise OSError("HTTP Error 404: Not Found")

    fetched = fetch_item(
        make_model(), get_json=fake_json(MODEL_DOC), get_text=no_card
    )
    assert fetched.extracted_text is None
    assert fetched.summary is None  # no description, no card to lead from
    assert fetched.provenance["extraction_method"] == "huggingface-api:json"
    assert fetched.stage == "fetched"  # still a valid scroll
    assert fetched.concepts == ("fill-mask", "exbert")  # metadata still maps


def test_model_raw_text_drops_heavy_fields():
    raw = json.loads(fetch_model().raw_text)
    assert raw["id"] == "google-bert/bert-base-uncased"
    assert raw["cardData"]["license"] == "apache-2.0"
    # siblings/config are large and useless in the index
    assert "siblings" not in raw
    assert "config" not in raw


# --- datasets -----------------------------------------------------------


def test_fetch_dataset_maps_metadata():
    fetched = fetch_dataset()

    # a dataset prefers its human pretty_name as the title
    assert fetched.title == "SQuAD"
    assert fetched.author == "rajpurkar"
    # the card's lead paragraph is the summary (cleaner than the Hub's
    # crudely-derived `description` field)
    assert fetched.summary == "SQuAD is a reading comprehension dataset."
    assert fetched.canonical_url == "https://huggingface.co/datasets/rajpurkar/squad"
    assert fetched.published_at == "2022-03-02T23:29:22+00:00"
    assert fetched.stage == "fetched"


def test_dataset_concepts_are_tasks_plus_card_tags():
    # task_categories + task_ids + cardData.tags feed the concept graph
    assert fetch_dataset().concepts == (
        "question-answering", "extractive-qa", "wikipedia-derived")


def test_dataset_tags_are_the_license():
    # datasets have no library_name, so only the license fills the facet slot
    assert fetch_dataset().tags == ("cc-by-sa-4.0",)


def test_dataset_arxiv_tag_becomes_a_link():
    assert "https://arxiv.org/abs/1606.05250" in fetch_dataset().links


def test_dataset_title_falls_back_to_repo_id_without_pretty_name():
    doc = json.loads(json.dumps(DATASET_DOC))
    doc["cardData"].pop("pretty_name")
    assert fetch_dataset(doc).title == "rajpurkar/squad"


def test_dataset_summary_prefers_card_lead_over_description():
    # even with both present, the clean card paragraph wins over the Hub's
    # auto-derived description field
    assert fetch_dataset().summary == "SQuAD is a reading comprehension dataset."


def test_dataset_summary_falls_back_to_description_without_a_card():
    # no card README -> the description field, with its crude whitespace
    # (tabs, heading fragments) collapsed to single spaces
    messy = "Dataset Card\n\t\n\tStanford Question Answering Dataset (SQuAD)\tis a dataset."
    doc = json.loads(json.dumps(DATASET_DOC))
    doc["description"] = messy
    fetched = fetch_item(make_dataset(), get_json=fake_json(doc), get_text=fake_text(""))
    assert fetched.extracted_text is None  # empty card -> metadata-only
    assert fetched.summary == "Dataset Card Stanford Question Answering Dataset (SQuAD) is a dataset."


# --- requests, identity, errors -----------------------------------------


def test_requests_the_expected_model_api_and_card_urls():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(MODEL_DOC))

    def get_text(url):
        seen.append(url)
        return MODEL_README

    fetch_item(make_model(), get_json=get_json, get_text=get_text)
    assert seen == [
        "https://huggingface.co/api/models/google-bert/bert-base-uncased",
        "https://huggingface.co/google-bert/bert-base-uncased/raw/main/README.md",
    ]


def test_requests_the_expected_dataset_api_and_card_urls():
    seen = []

    def get_json(url):
        seen.append(url)
        return json.loads(json.dumps(DATASET_DOC))

    def get_text(url):
        seen.append(url)
        return DATASET_README

    fetch_item(make_dataset(), get_json=get_json, get_text=get_text)
    assert seen == [
        "https://huggingface.co/api/datasets/rajpurkar/squad",
        "https://huggingface.co/datasets/rajpurkar/squad/raw/main/README.md",
    ]


def test_repo_id_case_is_preserved_in_the_request():
    seen = []

    def get_json(url):
        seen.append(url)
        return {"id": "Qwen/Qwen2.5-7B-Instruct"}

    item = make_model(
        id="huggingface:model:Qwen/Qwen2.5-7B-Instruct",
        source_id="model:Qwen/Qwen2.5-7B-Instruct",
    )
    fetch_item(item, get_json=get_json, get_text=lambda url: "")
    assert seen == ["https://huggingface.co/api/models/Qwen/Qwen2.5-7B-Instruct"]


def test_preserves_identity_and_the_saved_url():
    item = make_model(url="https://huggingface.co/google-bert/bert-base-uncased/tree/main")
    fetched = fetch_model(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id)
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_published_at_falls_back_to_seed():
    doc = json.loads(json.dumps(MODEL_DOC))
    doc.pop("createdAt")
    item = make_model(published_at="2026-06-01T00:00:00+00:00")
    assert fetch_model(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_non_string_created_at_does_not_crash():
    # a malformed (non-string) createdAt in the untrusted response degrades
    # to the seed rather than raising — the sibling registry adapters' guard
    doc = json.loads(json.dumps(MODEL_DOC))
    doc["createdAt"] = 1700000000
    item = make_model(published_at="2026-06-01T00:00:00+00:00")
    assert fetch_model(doc, item=item).published_at == "2026-06-01T00:00:00+00:00"


def test_setext_heading_is_not_mistaken_for_the_summary():
    # a card opening with a setext (underlined) heading skips to the prose
    readme = "Cool Model\n==========\n\nThe real description goes here.\n"
    assert fetch_model(readme=readme).summary == "The real description goes here."


@pytest.mark.parametrize("source_id", [None, "", "model:", "garbage", "space:foo/bar"])
def test_requires_a_valid_repo(source_id):
    item = make_model(id="huggingface:bad", source_id=source_id)
    with pytest.raises(FetchError, match="huggingface repo"):
        fetch_item(item, get_json=fake_json(MODEL_DOC), get_text=fake_text(""))


def test_missing_repo_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(
            make_model(),
            get_json=lambda url: {"error": "Repo not found"},
            get_text=fake_text(""),
        )


def test_wraps_api_errors():
    def boom(url):
        raise OSError("HTTP Error 404: Not Found")

    with pytest.raises(FetchError, match="404"):
        fetch_item(make_model(), get_json=boom, get_text=fake_text(""))


def test_huggingface_adapter_is_registered():
    assert FETCH_ADAPTERS["huggingface"] is fetch_item
