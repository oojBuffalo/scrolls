"""Tests for the LLM classification engine (IDEAS.md §8 layer two, ADR 0015).

Offline: every test injects a fake completer instead of the Anthropic
client, mirroring how adapter tests inject a fake fetcher. The contract
under test is everything around the model call — prompt content, response
validation, concept merging, provenance, and immutability.
"""

import json

import pytest

from scrolls.classify_llm import (
    CATEGORIES,
    DEFAULT_MODEL,
    ENGINE,
    LLMAuthError,
    LLMClassifyError,
    SYSTEM_PROMPT,
    classify_item_llm,
    item_card,
)
from scrolls.items import ScrollItem


def make_item(**overrides):
    base = dict(
        id="web:3f1a2b3c4d5e",
        source="web",
        source_id=None,
        url="https://blog.example.com/post",
        saved_at="2026-06-12T00:00:00+00:00",
        title="Inside SQLite's FTS5 ranking",
        summary="How BM25 scoring works inside SQLite FTS5.",
        extracted_text="SQLite's FTS5 extension ranks matches with BM25...",
        stage="fetched",
        provenance={"adapter": "web", "fetched_at": "2026-06-12T00:00:00+00:00"},
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_completer(payload):
    """A completer returning a fixed JSON payload, recording its inputs."""
    calls = []

    def complete(system, user, model):
        calls.append({"system": system, "user": user, "model": model})
        return json.dumps(payload)

    complete.calls = calls
    return complete


GOOD = {
    "category": "tutorial",
    "domain": "databases",
    "concepts": ["SQLite", "BM25", "full-text search"],
}


def test_classifies_category_domain_and_concepts():
    item = make_item()
    classified = classify_item_llm(item, complete=fake_completer(GOOD))
    assert classified.category == "tutorial"
    assert classified.domain == "databases"
    assert set(GOOD["concepts"]) <= set(classified.concepts)


def test_null_domain_is_accepted():
    payload = {**GOOD, "domain": None}
    classified = classify_item_llm(make_item(), complete=fake_completer(payload))
    assert classified.domain is None
    assert classified.category == "tutorial"


def test_existing_concepts_are_merged_not_replaced():
    item = make_item(concepts=("Database software", "SQLite"))
    classified = classify_item_llm(item, complete=fake_completer(GOOD))
    # platform-curated concepts come first, model concepts appended, no dupes
    assert classified.concepts[:2] == ("Database software", "SQLite")
    assert classified.concepts.count("SQLite") == 1
    assert "BM25" in classified.concepts


def test_provenance_stamps_engine_and_model():
    classified = classify_item_llm(
        make_item(), complete=fake_completer(GOOD), model="claude-haiku-4-5"
    )
    assert classified.provenance["classified_by"] == ENGINE
    assert classified.provenance["classified_model"] == "claude-haiku-4-5"
    # fetch provenance is preserved, not replaced
    assert classified.provenance["adapter"] == "web"


def test_model_defaults_and_env_override(monkeypatch):
    complete = fake_completer(GOOD)
    classify_item_llm(make_item(), complete=complete)
    assert complete.calls[0]["model"] == DEFAULT_MODEL

    monkeypatch.setenv("SCROLLS_LLM_MODEL", "claude-haiku-4-5")
    classify_item_llm(make_item(), complete=complete)
    assert complete.calls[1]["model"] == "claude-haiku-4-5"


def test_input_item_is_never_mutated():
    item = make_item(concepts=("SQLite",))
    classify_item_llm(item, complete=fake_completer(GOOD))
    assert item.category is None
    assert item.domain is None
    assert item.concepts == ("SQLite",)
    assert "classified_by" not in item.provenance


def test_category_outside_vocabulary_is_an_error():
    payload = {**GOOD, "category": "shitpost"}
    with pytest.raises(LLMClassifyError):
        classify_item_llm(make_item(), complete=fake_completer(payload))


def test_unparseable_response_is_an_error():
    def complete(system, user, model):
        return "I'd be happy to classify that for you!"

    with pytest.raises(LLMClassifyError):
        classify_item_llm(make_item(), complete=complete)


def test_auth_error_is_a_classify_error_subclass():
    # the CLI distinguishes them; one must imply the other
    assert issubclass(LLMAuthError, LLMClassifyError)


def test_real_completer_maps_missing_credentials_to_auth_error(monkeypatch):
    # The SDK raises TypeError when no credentials resolve (at client
    # construction or request build, depending on version). No network:
    # the stub raises before any request could be made.
    import anthropic

    from scrolls.classify_llm import _anthropic_complete

    def no_credentials(*args, **kwargs):
        raise TypeError("Could not resolve authentication method.")

    monkeypatch.setattr(anthropic, "Anthropic", no_credentials)
    with pytest.raises(LLMAuthError):
        _anthropic_complete("system", "user", "claude-opus-4-8")


def test_real_completer_lets_programming_errors_surface(monkeypatch):
    # A TypeError that isn't about credentials is a real bug, not an
    # auth problem — it must not be swallowed into LLMAuthError.
    import anthropic

    from scrolls.classify_llm import _anthropic_complete

    def bad_kwarg(*args, **kwargs):
        raise TypeError("got an unexpected keyword argument 'output_config'")

    monkeypatch.setattr(anthropic, "Anthropic", bad_kwarg)
    with pytest.raises(TypeError):
        _anthropic_complete("system", "user", "claude-opus-4-8")


def test_system_prompt_names_every_category():
    for category in CATEGORIES:
        assert category in SYSTEM_PROMPT, category


def test_item_card_carries_content_and_existing_signals():
    item = make_item(
        author="Jane Hacker",
        tags=("cs.CL",),
        concepts=("Database software",),
    )
    card = item_card(item)
    assert "Inside SQLite's FTS5 ranking" in card
    assert "https://blog.example.com/post" in card
    assert "Jane Hacker" in card
    assert "cs.CL" in card
    assert "Database software" in card
    assert "BM25 scoring" in card  # summary
    assert "ranks matches with BM25" in card  # extracted text


def test_item_card_omits_empty_fields_and_caps_excerpts():
    item = make_item(author=None, summary=None, extracted_text="x" * 50_000)
    card = item_card(item)
    assert "author" not in card
    assert "summary" not in card
    assert len(card) < 5_000


def test_item_without_content_is_an_error():
    item = make_item(title=None, summary=None, extracted_text=None)
    with pytest.raises(LLMClassifyError):
        classify_item_llm(item, complete=fake_completer(GOOD))
