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
    classify_items_llm_batch,
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


def test_llm_errors_share_one_base():
    # The CLI aborts on LLMAuthError and reports other LLMErrors per item;
    # every error an engine can raise must sit under the shared base so
    # one `except LLMError` clause is always enough (scrolls/llm.py).
    from scrolls.llm import LLMError

    assert issubclass(LLMAuthError, LLMError)
    assert issubclass(LLMClassifyError, LLMError)
    assert not issubclass(LLMAuthError, LLMClassifyError)  # siblings since ADR 0025


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


# --- batched classification (ADR 0022) ---


def fake_batch_completer(raw_by_id):
    """A batch completer returning canned raw values, recording its inputs.

    `raw_by_id` maps custom_id -> raw JSON text or LLMClassifyError;
    requested ids absent from the map are simply not answered.
    """
    calls = []

    def complete_batch(system, requests, model):
        calls.append({"system": system, "requests": list(requests), "model": model})
        return {cid: raw_by_id[cid] for cid, _ in requests if cid in raw_by_id}

    complete_batch.calls = calls
    return complete_batch


def test_batch_classifies_every_item_in_order():
    items = [make_item(), make_item(id="web:other", title="Another post")]
    complete_batch = fake_batch_completer(
        {"item-0": json.dumps(GOOD), "item-1": json.dumps({**GOOD, "category": "opinion"})}
    )

    pairs = classify_items_llm_batch(items, complete_batch=complete_batch)

    assert [item.id for item, _ in pairs] == ["web:3f1a2b3c4d5e", "web:other"]
    assert pairs[0][1].category == "tutorial"
    assert pairs[1][1].category == "opinion"
    assert pairs[0][1].provenance["classified_by"] == ENGINE
    # one submission carried both items, with the shared system prompt
    assert len(complete_batch.calls) == 1
    call = complete_batch.calls[0]
    assert call["system"] == SYSTEM_PROMPT
    assert [cid for cid, _ in call["requests"]] == ["item-0", "item-1"]
    assert "Inside SQLite's FTS5 ranking" in call["requests"][0][1]


def test_batch_model_defaults_and_overrides(monkeypatch):
    complete_batch = fake_batch_completer({"item-0": json.dumps(GOOD)})
    classify_items_llm_batch([make_item()], complete_batch=complete_batch)
    assert complete_batch.calls[0]["model"] == DEFAULT_MODEL

    monkeypatch.setenv("SCROLLS_LLM_MODEL", "claude-haiku-4-5")
    classify_items_llm_batch([make_item()], complete_batch=complete_batch)
    assert complete_batch.calls[1]["model"] == "claude-haiku-4-5"


def test_batch_filters_contentless_items_before_submit():
    items = [
        make_item(),
        make_item(id="web:empty", title=None, summary=None, extracted_text=None),
    ]
    complete_batch = fake_batch_completer({"item-0": json.dumps(GOOD)})

    pairs = classify_items_llm_batch(items, complete_batch=complete_batch)

    # only the classifiable item was submitted
    assert [cid for cid, _ in complete_batch.calls[0]["requests"]] == ["item-0"]
    assert pairs[0][1].category == "tutorial"
    assert isinstance(pairs[1][1], LLMClassifyError)
    assert "no content" in str(pairs[1][1])


def test_batch_with_no_classifiable_items_never_submits():
    items = [make_item(title=None, summary=None, extracted_text=None)]
    complete_batch = fake_batch_completer({})

    pairs = classify_items_llm_batch(items, complete_batch=complete_batch)

    assert complete_batch.calls == []
    assert isinstance(pairs[0][1], LLMClassifyError)


def test_batch_per_item_errors_pass_through():
    items = [make_item(), make_item(id="web:other", title="Another post")]
    complete_batch = fake_batch_completer(
        {"item-0": json.dumps(GOOD), "item-1": LLMClassifyError("batch request expired")}
    )

    pairs = classify_items_llm_batch(items, complete_batch=complete_batch)

    assert pairs[0][1].category == "tutorial"
    assert isinstance(pairs[1][1], LLMClassifyError)
    assert "expired" in str(pairs[1][1])


def test_batch_missing_result_is_a_per_item_error():
    pairs = classify_items_llm_batch([make_item()], complete_batch=fake_batch_completer({}))
    assert isinstance(pairs[0][1], LLMClassifyError)
    assert "no result" in str(pairs[0][1])


def test_batch_invalid_payload_is_a_per_item_error():
    items = [make_item(), make_item(id="web:other", title="Another post")]
    complete_batch = fake_batch_completer(
        {"item-0": json.dumps({**GOOD, "category": "shitpost"}), "item-1": json.dumps(GOOD)}
    )

    pairs = classify_items_llm_batch(items, complete_batch=complete_batch)

    assert isinstance(pairs[0][1], LLMClassifyError)
    assert pairs[1][1].category == "tutorial"  # one bad payload never aborts the rest


# --- the real batch transport, with the SDK stubbed ---


def _fake_succeeded(custom_id, payload=GOOD, stop_reason="end_turn"):
    from types import SimpleNamespace

    content = [SimpleNamespace(type="text", text=json.dumps(payload))]
    return SimpleNamespace(
        custom_id=custom_id,
        result=SimpleNamespace(
            type="succeeded",
            message=SimpleNamespace(stop_reason=stop_reason, content=content),
        ),
    )


def _fake_failed(custom_id, type_, **extra):
    from types import SimpleNamespace

    return SimpleNamespace(
        custom_id=custom_id, result=SimpleNamespace(type=type_, **extra)
    )


class _FakeBatchClient:
    """Stub of the SDK surface `_anthropic_complete_batch` touches."""

    def __init__(self, entries, polls_until_ended=0):
        from types import SimpleNamespace

        self.created_with = None
        self.retrieves = 0
        self._polls_until_ended = polls_until_ended
        self._entries = entries
        batches = SimpleNamespace(
            create=self._create, retrieve=self._retrieve, results=self._results
        )
        self.messages = SimpleNamespace(batches=batches)

    def _status(self):
        return "ended" if self._polls_until_ended <= 0 else "in_progress"

    def _create(self, *, requests):
        from types import SimpleNamespace

        self.created_with = requests
        return SimpleNamespace(id="batch-1", processing_status=self._status())

    def _retrieve(self, batch_id):
        from types import SimpleNamespace

        assert batch_id == "batch-1"
        self.retrieves += 1
        self._polls_until_ended -= 1
        return SimpleNamespace(id="batch-1", processing_status=self._status())

    def _results(self, batch_id):
        assert batch_id == "batch-1"
        return iter(self._entries)


def test_real_batch_submits_polls_and_collects_results(monkeypatch):
    import anthropic

    import scrolls.classify_llm as classify_llm
    import scrolls.llm as llm

    client = _FakeBatchClient(
        entries=[
            _fake_succeeded("item-0"),
            _fake_failed("item-1", "errored", error="overloaded"),
            _fake_failed("item-2", "expired"),
            _fake_succeeded("item-3", stop_reason="refusal"),
        ],
        polls_until_ended=2,
    )
    sleeps = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda: client)
    # the submission, poll loop, and result mapping now live in scrolls.llm;
    # the classify wrapper binds the schema and re-tags per-request errors
    monkeypatch.setattr(llm, "_sleep", sleeps.append)

    outcomes = classify_llm._anthropic_complete_batch(
        SYSTEM_PROMPT, [("item-0", "card 0"), ("item-1", "card 1")], "claude-opus-4-8"
    )

    # the submission carries the same request shape as the per-item path
    first = client.created_with[0]
    assert first["custom_id"] == "item-0"
    assert first["params"]["model"] == "claude-opus-4-8"
    assert first["params"]["system"] == SYSTEM_PROMPT
    assert first["params"]["messages"] == [{"role": "user", "content": "card 0"}]
    assert first["params"]["output_config"]["format"]["type"] == "json_schema"
    # polled until the batch ended, sleeping between polls
    assert client.retrieves == 2
    assert len(sleeps) == 2
    # outcome mapping: text, errored, expired, refusal
    assert json.loads(outcomes["item-0"])["category"] == "tutorial"
    assert isinstance(outcomes["item-1"], LLMClassifyError)
    assert "overloaded" in str(outcomes["item-1"])
    assert isinstance(outcomes["item-2"], LLMClassifyError)
    assert "expired" in str(outcomes["item-2"])
    assert isinstance(outcomes["item-3"], LLMClassifyError)
    assert "declined" in str(outcomes["item-3"])


def test_real_batch_maps_missing_credentials_to_auth_error(monkeypatch):
    import anthropic

    from scrolls.classify_llm import _anthropic_complete_batch

    def no_credentials(*args, **kwargs):
        raise TypeError("Could not resolve authentication method.")

    monkeypatch.setattr(anthropic, "Anthropic", no_credentials)
    with pytest.raises(LLMAuthError):
        _anthropic_complete_batch(SYSTEM_PROMPT, [("item-0", "card")], "claude-opus-4-8")
