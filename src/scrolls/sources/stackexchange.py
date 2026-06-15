"""Stack Exchange fetch adapter (IDEAS.md §6, ADR 0033).

A saved Stack Overflow / Stack Exchange question becomes a clean scroll
instead of a `trafilatura` scrape of its HTML page. Metadata and the
question body come from the keyless Stack Exchange API in one GET; the
top answers (sorted by votes, accepted first) are optional enrichment in
a second GET, so the scroll carries the actual solution and not just the
question. The question's tags — `python`, `branch-prediction` — are
curated topical labels, so they become `concepts` the way github repo
topics do (ADR 0007), feeding the KB's concept pages. The raw question
and answer objects are kept in `raw_text` for rebuilds.

The whole Stack Exchange network rides one adapter: the per-site API
slug (`stackoverflow`, `math`, `mathoverflow.net`) is encoded in the
`source_id` as `<site>:<question_id>`, the way Wikipedia encodes its
language edition (`en:SQLite`). Answers are optional like github's
README — a question with no answers, or an answers request that fails,
still produces a question-only scroll.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable

from scrolls.dates import epoch_to_utc_iso
from scrolls.items import ScrollItem
from scrolls.sources import FetchError
from scrolls.sources import discussion
from scrolls.sources import http

API_ROOT = "https://api.stackexchange.com/2.3"
# Top answers to carry, by votes. The accepted answer is reordered first
# but is almost always among the highest-voted, so one small page suffices.
_ANSWER_PAGESIZE = 5

GetJson = Callable[[str], Any]


def fetch_item(item: ScrollItem, *, get_json: GetJson | None = None) -> ScrollItem:
    """Fetch a detected Stack Exchange question; return it at stage 'fetched'.

    Raises FetchError when the source_id is missing/malformed, the request
    fails, or the question does not exist. Answers are optional enrichment:
    a question with none, or an answers request that fails, still produces
    a question-only scroll. The input item is never mutated.
    """
    get_json = get_json or _get_json
    site, question_id = _split_source_id(item)

    question_url = f"{API_ROOT}/questions/{question_id}?site={site}&filter=withbody"
    try:
        data = get_json(question_url)
    except (OSError, ValueError) as exc:
        raise FetchError(f"stack exchange API request failed: {exc}") from exc

    items = data.get("items") if isinstance(data, dict) else None
    if not items:  # a nonexistent question answers 200 with an empty list
        raise FetchError(f"stack exchange question not found: {site}:{question_id}")
    question = items[0]

    answers = _fetch_answers(get_json, site, question_id, question)
    body_text = _html_to_text(question.get("body") or "")
    answers_text = _format_answers(answers, question.get("accepted_answer_id"))
    extracted = "\n\n".join(part for part in (body_text, answers_text) if part) or None

    raw = json.dumps({"question": question, "answers": answers}, ensure_ascii=False)
    hashed = extracted or raw
    method = "stackexchange-api:question+answers" if answers_text else "stackexchange-api:question"
    return replace(
        item,
        title=question.get("title") or item.title,
        author=_owner_name(question),
        published_at=epoch_to_utc_iso(str(question.get("creation_date"))) or item.published_at,
        canonical_url=question.get("link"),
        raw_text=raw,
        extracted_text=extracted,
        summary=_summary(body_text, question),
        concepts=tuple(question.get("tags") or ()),
        content_hash="sha256:" + hashlib.sha256(hashed.encode("utf-8")).hexdigest(),
        provenance={
            "adapter": "stackexchange",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "extraction_method": method,
        },
        stage="fetched",
    )


def _split_source_id(item: ScrollItem) -> tuple[str, str]:
    """`<site>:<question_id>` -> (site, question_id); raises FetchError otherwise.

    Sites never contain a colon and question ids are numeric, so the last
    colon splits them even for dotted slugs like `mathoverflow.net`.
    """
    site, sep, question_id = (item.source_id or "").rpartition(":")
    if not sep or not site or not question_id.isdigit():
        raise FetchError(f"cannot determine stack exchange question for item {item.id!r}")
    return site, question_id


def _fetch_answers(
    get_json: GetJson, site: str, question_id: str, question: dict[str, Any]
) -> list[dict[str, Any]]:
    """Top answers by votes, or [] — a question with none, or a failed request.

    Answers are optional enrichment (like github's README, ADR 0007): they
    never fail an otherwise-identified question, and a question the API
    reports as having no answers skips the request entirely.
    """
    if not question.get("answer_count"):
        return []
    url = (
        f"{API_ROOT}/questions/{question_id}/answers"
        f"?site={site}&order=desc&sort=votes&pagesize={_ANSWER_PAGESIZE}&filter=withbody"
    )
    try:
        data = get_json(url)
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items or []


def _format_answers(answers: list[dict[str, Any]], accepted_id: Any) -> str:
    """The answers as a nested Markdown subsection, accepted answer first.

    Returns "" when there is nothing to show. The accepted answer leads
    (stable sort keeps the rest in their incoming vote order), and each
    answer's byline records who wrote it and its score; the `### Top Answers`
    subsection is assembled by the shared thread renderer (ADR 0093).
    """
    ordered = sorted(answers, key=lambda a: a.get("answer_id") != accepted_id)
    rendered = []
    for answer in ordered:
        text = _html_to_text(answer.get("body") or "")
        if not text:
            continue
        accepted = answer.get("answer_id") == accepted_id
        label = "Accepted answer" if accepted else "Answer"
        who = _owner_name(answer)
        byline = f"{label} by {who}" if who else label
        score = answer.get("score")
        if score is not None:
            byline += f" (score {score})"
        rendered.append(discussion.Comment(byline, text))
    return discussion.format_thread(rendered, heading="Top Answers")


def _summary(body_text: str, question: dict[str, Any]) -> str | None:
    """The question's lead paragraph, else its vote/answer status.

    A question almost always has a body, so the summary leads with its
    first paragraph the way Wikipedia and Hacker News do (ADR 0002,
    ADR 0031). A bodyless stub falls back to the honest status Stack
    Exchange itself reports; with neither, there is nothing to say.
    """
    if body_text:
        return body_text.split("\n\n", 1)[0].strip()
    score, answers = question.get("score"), question.get("answer_count")
    if score is None and answers is None:
        return None
    votes = 0 if score is None else score
    replies = 0 if answers is None else answers
    return (
        f"Stack Exchange question: {votes} {_plural(votes, 'vote')}, "
        f"{replies} {_plural(replies, 'answer')}."
    )


def _owner_name(obj: dict[str, Any]) -> str | None:
    """A question's or answer's author display name; None for deleted users."""
    return (obj.get("owner") or {}).get("display_name") or None


def _plural(count: int, noun: str) -> str:
    return noun if count == 1 else noun + "s"


def _html_to_text(html_text: str) -> str:
    """Stack Exchange's post HTML to readable plain text, stdlib only.

    Block tags (`<p>`, `<pre>`, headings, `<blockquote>`, tables) become
    paragraph breaks, `<li>` becomes a bullet, `<br>` a newline; remaining
    inline tags (`<a>`, `<code>`, `<em>`) are dropped. Markup is stripped
    before entities are unescaped, so escaped angle brackets inside quoted
    code survive as literal text. Newlines inside `<pre><code>` blocks are
    already literal in the payload, so code keeps its shape. No new
    dependency for a small tag grammar (ADR 0001).
    """
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", html_text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?(?:p|div|h[1-6]|ul|ol|pre|blockquote|table|tr|hr)[^>]*>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_get_json = http.get_json
