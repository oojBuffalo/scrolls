"""Tests for the LLM concept engine (IDEAS.md §9's fancy version, ADR 0025).

Offline: every test injects a fake completer instead of the Anthropic
client, mirroring the classification engine's tests. The contract under
test is everything around the model call — eligibility, the concept
card, incremental regeneration via the members fingerprint, pruning,
and per-concept failure isolation.
"""

import json

import pytest

from scrolls.db import init_db
from scrolls.items import ScrollItem, insert_item, update_item
from scrolls.kb import load_concept_summaries, save_concept_summary
from scrolls.kb_llm import (
    ENGINE,
    MIN_MEMBERS,
    SYSTEM_PROMPT,
    concept_card,
    generate_concept_summaries,
    generate_concept_summaries_batch,
    members_hash,
    summarize_concept_llm,
)
from scrolls.llm import DEFAULT_MODEL, LLMAuthError, LLMError


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "db.sqlite"
    init_db(path)
    return path


def make_rendered(item_id, source, title, *, concepts=(), summary=None,
                  extracted_text=None, content_hash="h1"):
    slug = title.lower().replace(" ", "-")
    return ScrollItem(
        id=item_id,
        source=source,
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-01T00:00:00+00:00",
        title=title,
        summary=summary,
        extracted_text=extracted_text,
        concepts=tuple(concepts),
        content_hash=content_hash,
        markdown_path=f"scrolls/{source}/{slug}.md",
        stage="rendered",
    )


def fake_completer(text="A synthesized concept summary."):
    """A completer returning a fixed summary, recording its inputs."""
    calls = []

    def complete(system, user, model):
        calls.append({"system": system, "user": user, "model": model})
        return json.dumps({"summary": text})

    complete.calls = calls
    return complete


def seed_bm25_concept(db_path):
    insert_item(db_path, make_rendered(
        "wikipedia:en:Okapi_BM25", "wikipedia", "Okapi BM25",
        concepts=("BM25",), summary="A ranking function for search engines."))
    insert_item(db_path, make_rendered(
        "web:fts", "web", "FTS in practice",
        concepts=("bm25",), extracted_text="SQLite FTS5 ranks with BM25..."))


# --- summarize_concept_llm ---------------------------------------------


def test_summarize_returns_the_model_summary_stripped():
    complete = fake_completer("  How BM25 shows up.  ")
    text = summarize_concept_llm("BM25", [], complete=complete)
    assert text == "How BM25 shows up."


def test_summarize_model_defaults_and_env_override(monkeypatch):
    complete = fake_completer()
    summarize_concept_llm("BM25", [], complete=complete)
    assert complete.calls[0]["model"] == DEFAULT_MODEL

    monkeypatch.setenv("SCROLLS_LLM_MODEL", "claude-haiku-4-5-20251001")
    summarize_concept_llm("BM25", [], complete=complete)
    assert complete.calls[1]["model"] == "claude-haiku-4-5-20251001"

    summarize_concept_llm("BM25", [], complete=complete, model="claude-explicit")
    assert complete.calls[2]["model"] == "claude-explicit"


def test_summarize_unparseable_response_is_an_error():
    def complete(system, user, model):
        return "Here's a lovely summary for you!"

    with pytest.raises(LLMError):
        summarize_concept_llm("BM25", [], complete=complete)


def test_summarize_empty_summary_is_an_error():
    def complete(system, user, model):
        return json.dumps({"summary": "   "})

    with pytest.raises(LLMError):
        summarize_concept_llm("BM25", [], complete=complete)


def test_real_completer_maps_missing_credentials_to_auth_error(monkeypatch):
    # Same SDK behavior the classification engine handles: TypeError when
    # no credentials resolve. No network: the stub raises first.
    import anthropic

    from scrolls.kb_llm import _anthropic_complete

    def no_credentials(*args, **kwargs):
        raise TypeError("Could not resolve authentication method.")

    monkeypatch.setattr(anthropic, "Anthropic", no_credentials)
    with pytest.raises(LLMAuthError):
        _anthropic_complete("system", "user", "claude-opus-4-8")


# --- the concept card ----------------------------------------------------


def test_concept_card_carries_members_with_capped_excerpts():
    items = [
        make_rendered("web:long", "web", "A long read",
                      extracted_text="x" * 1000),
        make_rendered("wikipedia:en:Okapi_BM25", "wikipedia", "Okapi BM25",
                      summary="A ranking function."),
    ]
    card = concept_card("BM25", items)
    assert card.startswith("concept: BM25")
    # members in page order (title casefold), summary preferred over text
    assert card.index("A long read (web)") < card.index("Okapi BM25 (wikipedia)")
    assert "— A ranking function." in card
    assert "x" * 301 not in card  # capped
    assert "x" * 300 in card


def test_concept_card_truncates_oversized_concepts_honestly():
    items = [
        make_rendered(f"web:{n:03d}", "web", f"Post {n:03d}") for n in range(30)
    ]
    card = concept_card("sprawling", items)
    assert "Post 024" in card
    assert "Post 025" not in card
    assert "(and 5 more items not shown)" in card


# --- the members fingerprint ---------------------------------------------


def test_members_hash_is_order_independent_but_content_sensitive():
    a = make_rendered("web:a", "web", "A", content_hash="h1")
    b = make_rendered("web:b", "web", "B", content_hash="h2")
    assert members_hash([a, b]) == members_hash([b, a])
    assert members_hash([a, b]) != members_hash([a])
    refetched = make_rendered("web:b", "web", "B", content_hash="h3")
    assert members_hash([a, b]) != members_hash([a, refetched])


# --- generate_concept_summaries ------------------------------------------


def test_generate_summarizes_multi_member_concepts_only(db_path):
    seed_bm25_concept(db_path)
    insert_item(db_path, make_rendered(
        "web:solo", "web", "A loner", concepts=("loneliness",)))
    complete = fake_completer()

    counts, results = generate_concept_summaries(db_path, complete=complete)
    assert counts == {"generated": 1, "current": 0, "failed": 0, "pruned": 0}
    assert results == [{"slug": "bm25", "concept": "BM25", "status": "generated"}]
    assert MIN_MEMBERS == 2  # the documented eligibility bar
    assert len(complete.calls) == 1
    assert complete.calls[0]["system"] == SYSTEM_PROMPT
    assert "Okapi BM25" in complete.calls[0]["user"]

    stored = load_concept_summaries(db_path)
    assert set(stored) == {"bm25"}
    assert stored["bm25"].summary == "A synthesized concept summary."
    assert stored["bm25"].engine == ENGINE
    assert stored["bm25"].model == DEFAULT_MODEL
    assert stored["bm25"].display == "BM25"  # smallest spelling, like the page title


def test_generate_skips_unchanged_concepts_on_rerun(db_path):
    seed_bm25_concept(db_path)
    complete = fake_completer()
    generate_concept_summaries(db_path, complete=complete)

    counts, results = generate_concept_summaries(db_path, complete=complete)
    assert counts == {"generated": 0, "current": 1, "failed": 0, "pruned": 0}
    assert results == [{"slug": "bm25", "concept": "BM25", "status": "current"}]
    assert len(complete.calls) == 1  # no second model call


def test_generate_regenerates_when_membership_changes(db_path):
    seed_bm25_concept(db_path)
    complete = fake_completer()
    generate_concept_summaries(db_path, complete=complete)

    insert_item(db_path, make_rendered(
        "web:third", "web", "Another BM25 post", concepts=("BM25",)))
    counts, _ = generate_concept_summaries(db_path, complete=complete)
    assert counts["generated"] == 1
    assert len(complete.calls) == 2


def test_generate_regenerates_when_member_content_changes(db_path):
    seed_bm25_concept(db_path)
    complete = fake_completer()
    generate_concept_summaries(db_path, complete=complete)

    refetched = make_rendered(
        "web:fts", "web", "FTS in practice",
        concepts=("bm25",), content_hash="h2")
    update_item(db_path, refetched)
    counts, _ = generate_concept_summaries(db_path, complete=complete)
    assert counts["generated"] == 1


def test_generate_prunes_summaries_for_disqualified_concepts(db_path):
    seed_bm25_concept(db_path)
    complete = fake_completer()
    generate_concept_summaries(db_path, complete=complete)

    # the concept drops below MIN_MEMBERS: its summary is stale prose
    lone = make_rendered("web:fts", "web", "FTS in practice", concepts=())
    update_item(db_path, lone)
    counts, results = generate_concept_summaries(db_path, complete=complete)
    assert counts == {"generated": 0, "current": 0, "failed": 0, "pruned": 1}
    assert {"slug": "bm25", "status": "pruned"} in results
    assert load_concept_summaries(db_path) == {}


def test_generate_isolates_per_concept_failures(db_path):
    seed_bm25_concept(db_path)
    insert_item(db_path, make_rendered(
        "web:a", "web", "Post A", concepts=("SQLite",)))
    insert_item(db_path, make_rendered(
        "web:b", "web", "Post B", concepts=("SQLite",)))

    def flaky(system, user, model):
        if "SQLite" in user.splitlines()[0]:
            raise LLMError("Anthropic API error: overloaded")
        return json.dumps({"summary": "Fine."})

    counts, results = generate_concept_summaries(db_path, complete=flaky)
    assert counts["generated"] == 1
    assert counts["failed"] == 1
    failed = [r for r in results if r["status"] == "failed"]
    assert failed == [{"slug": "sqlite", "concept": "SQLite",
                       "status": "failed", "error": "Anthropic API error: overloaded"}]
    assert set(load_concept_summaries(db_path)) == {"bm25"}


def test_generate_auth_error_aborts_but_keeps_earlier_summaries(db_path):
    seed_bm25_concept(db_path)
    insert_item(db_path, make_rendered(
        "web:a", "web", "Post A", concepts=("SQLite",)))
    insert_item(db_path, make_rendered(
        "web:b", "web", "Post B", concepts=("SQLite",)))

    calls = []

    def auth_dies_second(system, user, model):
        calls.append(user)
        if len(calls) > 1:
            raise LLMAuthError("llm engine needs Anthropic credentials")
        return json.dumps({"summary": "Saved before the abort."})

    with pytest.raises(LLMAuthError):
        generate_concept_summaries(db_path, complete=auth_dies_second)
    # bm25 sorts first, was saved, and survives the abort
    assert set(load_concept_summaries(db_path)) == {"bm25"}


def test_generate_regenerates_when_engine_version_changes(db_path):
    from scrolls.kb import ConceptSummary

    seed_bm25_concept(db_path)
    complete = fake_completer()
    counts, _ = generate_concept_summaries(db_path, complete=complete)
    assert counts["generated"] == 1

    # simulate a summary written by an older engine: same members, old tag
    old = load_concept_summaries(db_path)["bm25"]
    save_concept_summary(db_path, ConceptSummary(
        slug=old.slug, display=old.display, summary=old.summary,
        members_hash=old.members_hash, engine="kb-llm-v0",
        model=old.model, generated_at=old.generated_at))

    counts, _ = generate_concept_summaries(db_path, complete=complete)
    assert counts["generated"] == 1  # vocabulary change ⇒ regenerate


def test_generate_on_empty_library_does_nothing(db_path):
    complete = fake_completer()
    counts, results = generate_concept_summaries(db_path, complete=complete)
    assert counts == {"generated": 0, "current": 0, "failed": 0, "pruned": 0}
    assert results == []
    assert complete.calls == []


# --- generate_concept_summaries_batch (ADR 0032) -------------------------
#
# The batch transport mirrors the per-call engine above: identical
# eligibility, incremental skipping, pruning, result shape, and
# per-concept failure isolation — only the submission differs.


def fake_batch_completer(summary="A synthesized concept summary."):
    """A batch completer answering every request with a fixed summary."""
    calls = []

    def complete_batch(system, requests, model):
        calls.append({"system": system, "requests": list(requests), "model": model})
        return {cid: json.dumps({"summary": summary}) for cid, _ in requests}

    complete_batch.calls = calls
    return complete_batch


def test_batch_summarizes_multi_member_concepts_in_one_submission(db_path):
    seed_bm25_concept(db_path)
    insert_item(db_path, make_rendered(
        "web:solo", "web", "A loner", concepts=("loneliness",)))
    complete_batch = fake_batch_completer()

    counts, results = generate_concept_summaries_batch(
        db_path, complete_batch=complete_batch)
    assert counts == {"generated": 1, "current": 0, "failed": 0, "pruned": 0}
    assert results == [{"slug": "bm25", "concept": "BM25", "status": "generated"}]

    assert len(complete_batch.calls) == 1  # one submission for the whole run
    call = complete_batch.calls[0]
    assert call["system"] == SYSTEM_PROMPT
    assert [cid for cid, _ in call["requests"]] == ["concept-0"]  # positional id
    assert "Okapi BM25" in call["requests"][0][1]

    stored = load_concept_summaries(db_path)
    assert set(stored) == {"bm25"}
    assert stored["bm25"].summary == "A synthesized concept summary."
    assert stored["bm25"].engine == ENGINE
    assert stored["bm25"].model == DEFAULT_MODEL


def test_batch_model_env_override(db_path, monkeypatch):
    monkeypatch.setenv("SCROLLS_LLM_MODEL", "claude-haiku-4-5-20251001")
    seed_bm25_concept(db_path)
    complete_batch = fake_batch_completer()

    generate_concept_summaries_batch(db_path, complete_batch=complete_batch)
    assert complete_batch.calls[0]["model"] == "claude-haiku-4-5-20251001"
    assert load_concept_summaries(db_path)["bm25"].model == "claude-haiku-4-5-20251001"


def test_batch_skips_unchanged_concepts_and_submits_nothing(db_path):
    seed_bm25_concept(db_path)
    generate_concept_summaries_batch(db_path, complete_batch=fake_batch_completer())

    complete_batch = fake_batch_completer()
    counts, results = generate_concept_summaries_batch(
        db_path, complete_batch=complete_batch)
    assert counts == {"generated": 0, "current": 1, "failed": 0, "pruned": 0}
    assert results == [{"slug": "bm25", "concept": "BM25", "status": "current"}]
    assert complete_batch.calls == []  # nothing to submit


def test_batch_isolates_per_concept_failures(db_path):
    seed_bm25_concept(db_path)
    insert_item(db_path, make_rendered("web:a", "web", "Post A", concepts=("SQLite",)))
    insert_item(db_path, make_rendered("web:b", "web", "Post B", concepts=("SQLite",)))

    def complete_batch(system, requests, model):
        outcomes = {}
        for cid, card in requests:
            if "SQLite" in card.splitlines()[0]:
                outcomes[cid] = LLMError("batch request errored: overloaded")
            else:
                outcomes[cid] = json.dumps({"summary": "Fine."})
        return outcomes

    counts, results = generate_concept_summaries_batch(
        db_path, complete_batch=complete_batch)
    assert counts["generated"] == 1
    assert counts["failed"] == 1
    failed = [r for r in results if r["status"] == "failed"]
    assert failed == [{"slug": "sqlite", "concept": "SQLite",
                       "status": "failed", "error": "batch request errored: overloaded"}]
    assert set(load_concept_summaries(db_path)) == {"bm25"}


def test_batch_missing_result_is_a_per_concept_error(db_path):
    seed_bm25_concept(db_path)

    def complete_batch(system, requests, model):
        return {}  # the batch answered no entry for this request

    counts, results = generate_concept_summaries_batch(
        db_path, complete_batch=complete_batch)
    assert counts["failed"] == 1
    assert results[0]["status"] == "failed"
    assert "no result" in results[0]["error"]
    assert load_concept_summaries(db_path) == {}


def test_batch_unparseable_response_is_a_per_concept_error(db_path):
    seed_bm25_concept(db_path)

    def complete_batch(system, requests, model):
        return {cid: "not json at all" for cid, _ in requests}

    counts, results = generate_concept_summaries_batch(
        db_path, complete_batch=complete_batch)
    assert counts["failed"] == 1
    assert results[0]["status"] == "failed"
    assert load_concept_summaries(db_path) == {}


def test_batch_prunes_disqualified_concepts(db_path):
    seed_bm25_concept(db_path)
    generate_concept_summaries_batch(db_path, complete_batch=fake_batch_completer())

    lone = make_rendered("web:fts", "web", "FTS in practice", concepts=())
    update_item(db_path, lone)
    complete_batch = fake_batch_completer()
    counts, results = generate_concept_summaries_batch(
        db_path, complete_batch=complete_batch)
    assert counts == {"generated": 0, "current": 0, "failed": 0, "pruned": 1}
    assert {"slug": "bm25", "status": "pruned"} in results
    assert load_concept_summaries(db_path) == {}
    assert complete_batch.calls == []  # nothing eligible to submit


def test_batch_on_empty_library_never_submits(db_path):
    complete_batch = fake_batch_completer()
    counts, results = generate_concept_summaries_batch(
        db_path, complete_batch=complete_batch)
    assert counts == {"generated": 0, "current": 0, "failed": 0, "pruned": 0}
    assert results == []
    assert complete_batch.calls == []


def test_batch_matches_per_call_results_for_a_mixed_library(tmp_path):
    # The two transports must produce the same store and result shape from
    # the same library — the whole point of sharing validation and save.
    def fresh_db():
        path = tmp_path / f"db-{len(list(tmp_path.iterdir()))}.sqlite"
        init_db(path)
        seed_bm25_concept(path)
        insert_item(path, make_rendered("web:a", "web", "Post A", concepts=("SQLite",)))
        insert_item(path, make_rendered("web:b", "web", "Post B", concepts=("SQLite",)))
        return path

    serial = fresh_db()
    counts_s, results_s = generate_concept_summaries(
        serial, complete=fake_completer("X"))
    batched = fresh_db()
    counts_b, results_b = generate_concept_summaries_batch(
        batched, complete_batch=fake_batch_completer("X"))

    assert counts_s == counts_b
    assert results_s == results_b
    assert {s: v.summary for s, v in load_concept_summaries(serial).items()} == {
        s: v.summary for s, v in load_concept_summaries(batched).items()
    }


def test_real_batch_completer_binds_this_engines_schema(monkeypatch):
    # The thin wrapper passes this engine's schema and token cap into the
    # shared transport (whose poll loop is covered in test_classify_llm).
    import scrolls.kb_llm as kb_llm

    captured = {}

    def fake_transport(system, requests, model, *, schema, max_tokens):
        captured["schema"] = schema
        captured["max_tokens"] = max_tokens
        return {cid: json.dumps({"summary": "ok"}) for cid, _ in requests}

    monkeypatch.setattr(kb_llm, "anthropic_complete_batch", fake_transport)
    out = kb_llm._anthropic_complete_batch(
        SYSTEM_PROMPT, [("concept-0", "card")], "claude-opus-4-8")
    assert captured["schema"] == kb_llm.RESPONSE_SCHEMA
    assert captured["max_tokens"] == kb_llm._MAX_TOKENS
    assert json.loads(out["concept-0"])["summary"] == "ok"


def test_real_batch_completer_maps_missing_credentials_to_auth_error(monkeypatch):
    import anthropic

    from scrolls.kb_llm import _anthropic_complete_batch

    def no_credentials(*args, **kwargs):
        raise TypeError("Could not resolve authentication method.")

    monkeypatch.setattr(anthropic, "Anthropic", no_credentials)
    with pytest.raises(LLMAuthError):
        _anthropic_complete_batch(
            SYSTEM_PROMPT, [("concept-0", "card")], "claude-opus-4-8")
