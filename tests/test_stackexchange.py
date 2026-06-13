"""Tests for the Stack Exchange fetch adapter (IDEAS.md §6, ADR 0033).

The JSON transport is faked with payloads recorded (and trimmed) from the
real Stack Exchange API, so the question/answer merge, accepted-first
ordering, HTML-to-text conversion, tags→concepts mapping, optional-answer
degradation, and error handling are all covered offline (ADR 0001).
"""

import json

import pytest

from scrolls.dates import epoch_to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FETCH_ADAPTERS, FetchError
from scrolls.sources.stackexchange import fetch_item

# Recorded from https://api.stackexchange.com/2.3/questions/<id>?site=stackoverflow&filter=withbody
QUESTION = {
    "tags": ["java", "c++", "performance", "branch-prediction"],
    "owner": {"display_name": "GManNickG", "user_id": 87234},
    "is_answered": True,
    "answer_count": 26,
    "accepted_answer_id": 11227902,
    "score": 27535,
    "creation_date": 1340805096,
    "question_id": 11227809,
    "link": "https://stackoverflow.com/questions/11227809/why-is-it-faster",
    "title": "Why is processing a sorted array faster than an unsorted array?",
    "body": "<p>In this C++ code, sorting the data makes the loop ~6x faster:</p>\n"
    "<pre class=\"lang-cpp\"><code>if (data[c] &gt;= 128)\n    sum += data[c];\n</code></pre>\n"
    "<ul>\n<li>Without the sort, the code runs in 11.54 seconds.</li>\n"
    "<li>With the sorted data, it runs in 1.93 seconds.</li>\n</ul>\n"
    "<p>What is going on? Why is a sorted array faster?</p>\n",
}

# Recorded from .../questions/<id>/answers?...&sort=votes&filter=withbody
ANSWERS = [
    {  # highest-voted, but NOT the accepted one
        "owner": {"display_name": "Daniel Fischer"},
        "is_accepted": False,
        "score": 4768,
        "answer_id": 11227877,
        "body": "<p>You are a victim of <strong>branch prediction</strong> fail.</p>",
    },
    {  # the accepted answer
        "owner": {"display_name": "Mysticial"},
        "is_accepted": True,
        "score": 35287,
        "answer_id": 11227902,
        "body": "<p>The branch predictor cannot guess the random branch, so the "
        "CPU stalls.</p>\n<p>Sorting makes the branch predictable.</p>",
    },
]


def make_item(**overrides):
    base = dict(
        id="stackexchange:stackoverflow:11227809",
        source="stackexchange",
        source_id="stackoverflow:11227809",
        url="https://stackoverflow.com/questions/11227809/why-is-it-faster",
        saved_at="2026-06-13T00:00:00+00:00",
    )
    base.update(overrides)
    return ScrollItem(**base)


def fake_get_json(question=QUESTION, answers=ANSWERS):
    """A get_json that routes the question and answers URLs to fixtures."""

    def get_json(url):
        if "/answers" in url:
            return {"items": [dict(a) for a in answers]}
        return {"items": [dict(question)]}

    return get_json


def fetch(question=QUESTION, answers=ANSWERS, item=None):
    return fetch_item(item or make_item(), get_json=fake_get_json(question, answers))


def test_fetch_merges_question_and_answers():
    fetched = fetch()

    assert fetched.title == "Why is processing a sorted array faster than an unsorted array?"
    assert fetched.author == "GManNickG"
    assert fetched.published_at == "2012-06-27T13:51:36+00:00"
    assert fetched.canonical_url == "https://stackoverflow.com/questions/11227809/why-is-it-faster"
    # tags become concepts, the way github topics do (ADR 0007)
    assert fetched.concepts == ("java", "c++", "performance", "branch-prediction")
    # the question body and the answers are both in the extracted text
    assert "Why is a sorted array faster?" in fetched.extracted_text
    assert "branch predictor cannot guess" in fetched.extracted_text
    assert fetched.provenance["adapter"] == "stackexchange"
    assert fetched.provenance["extraction_method"] == "stackexchange-api:question+answers"
    assert fetched.content_hash.startswith("sha256:")
    assert fetched.stage == "fetched"


def test_accepted_answer_leads_even_when_not_top_voted():
    text = fetch().extracted_text
    accepted = text.index("#### Accepted answer by Mysticial (score 35287)")
    other = text.index("#### Answer by Daniel Fischer (score 4768)")
    # accepted is reordered ahead of the higher-voted non-accepted answer
    assert accepted < other
    assert "### Top Answers" in text


def test_summary_is_the_question_lead_paragraph():
    # the way wikipedia and hacker news lead (ADR 0002, ADR 0031)
    assert fetch().summary == "In this C++ code, sorting the data makes the loop ~6x faster:"


def test_html_to_text_converts_blocks_lists_and_entities():
    text = fetch().extracted_text
    # <li> -> bullets
    assert "- Without the sort, the code runs in 11.54 seconds." in text
    # <pre><code> kept as text, &gt; entity decoded, internal newline preserved
    assert "if (data[c] >= 128)\n    sum += data[c];" in text
    # no raw markup survives
    assert "<p>" not in text and "<li>" not in text and "<code>" not in text
    assert "&gt;" not in text


def test_answers_are_optional_when_the_request_fails():
    def get_json(url):
        if "/answers" in url:
            raise OSError("HTTP Error 502: Bad Gateway")
        return {"items": [dict(QUESTION)]}

    fetched = fetch_item(make_item(), get_json=get_json)
    # a failed answers request degrades to a question-only scroll
    assert fetched.provenance["extraction_method"] == "stackexchange-api:question"
    assert "branch predictor" not in (fetched.extracted_text or "")
    assert "What is going on?" in fetched.extracted_text


def test_no_answers_skips_the_answers_request():
    seen = []

    def get_json(url):
        seen.append(url)
        return {"items": [{**QUESTION, "answer_count": 0}]}

    fetched = fetch_item(make_item(), get_json=get_json)
    assert all("/answers" not in url for url in seen)
    assert fetched.provenance["extraction_method"] == "stackexchange-api:question"


def test_requests_the_expected_api_urls():
    seen = []

    def get_json(url):
        seen.append(url)
        return {"items": [dict(QUESTION)]} if "/answers" not in url else {"items": []}

    fetch_item(make_item(), get_json=get_json)
    assert seen[0] == (
        "https://api.stackexchange.com/2.3/questions/11227809"
        "?site=stackoverflow&filter=withbody"
    )
    assert seen[1] == (
        "https://api.stackexchange.com/2.3/questions/11227809/answers"
        "?site=stackoverflow&order=desc&sort=votes&pagesize=5&filter=withbody"
    )


def test_dotted_site_slug_round_trips():
    item = make_item(
        id="stackexchange:mathoverflow.net:42",
        source_id="mathoverflow.net:42",
        url="https://mathoverflow.net/questions/42/a-question",
    )
    seen = []

    def get_json(url):
        seen.append(url)
        return {"items": [dict(QUESTION)]} if "/answers" not in url else {"items": []}

    fetch_item(item, get_json=get_json)
    # the last colon splits site from id, so a dotted slug survives intact
    assert "site=mathoverflow.net" in seen[0]
    assert "/questions/42?" in seen[0]


def test_concepts_empty_when_question_has_no_tags():
    assert fetch(question={**QUESTION, "tags": []}).concepts == ()


def test_summary_degrades_to_status_when_body_is_empty():
    bodyless = {**QUESTION, "body": ""}
    fetched = fetch(question=bodyless, answers=[])
    assert fetched.summary == "Stack Exchange question: 27535 votes, 26 answers."


def test_status_summary_uses_singular_units():
    bodyless = {**QUESTION, "body": "", "score": 1, "answer_count": 1}
    assert fetch(question=bodyless, answers=[]).summary == (
        "Stack Exchange question: 1 vote, 1 answer."
    )


def test_deleted_owner_has_no_author():
    assert fetch(question={**QUESTION, "owner": {"user_type": "does_not_exist"}}).author is None


def test_keeps_raw_records_for_rebuilds():
    raw = json.loads(fetch().raw_text)
    assert raw["question"]["question_id"] == 11227809
    assert [a["answer_id"] for a in raw["answers"]] == [11227877, 11227902]


def test_preserves_identity_and_the_saved_url():
    item = make_item(url="https://stackoverflow.com/questions/11227809/why?utm_source=x")
    fetched = fetch(item=item)
    assert (fetched.id, fetched.source, fetched.source_id) == (
        item.id, item.source, item.source_id,
    )
    assert fetched.url == item.url  # the saved URL, not the canonical one
    assert fetched.saved_at == item.saved_at


def test_keeps_seeded_published_at_when_question_has_no_date():
    question = {key: value for key, value in QUESTION.items() if key != "creation_date"}
    item = make_item(published_at="2026-06-01T00:00:00+00:00")
    assert fetch(question=question, item=item).published_at == "2026-06-01T00:00:00+00:00"
    assert epoch_to_utc_iso(str(question.get("creation_date"))) is None


@pytest.mark.parametrize("source_id", [None, "", "stackoverflow", "stackoverflow:", ":11227809", "stackoverflow:abc"])
def test_requires_a_site_and_numeric_question_id(source_id):
    item = make_item(id="stackexchange:bad", source_id=source_id)
    with pytest.raises(FetchError, match="cannot determine stack exchange question"):
        fetch_item(item, get_json=fake_get_json())


def test_missing_question_is_a_fetch_error():
    with pytest.raises(FetchError, match="not found"):
        fetch_item(make_item(), get_json=lambda url: {"items": []})


def test_wraps_question_api_errors():
    def boom(url):
        raise OSError("HTTP Error 503: Service Unavailable")

    with pytest.raises(FetchError, match="503"):
        fetch_item(make_item(), get_json=boom)


def test_stackexchange_adapter_is_registered():
    assert FETCH_ADAPTERS["stackexchange"] is fetch_item
