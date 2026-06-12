"""LLM classification engine (IDEAS.md §8 layer two, ADR 0015).

The layer the rules engine (ADR 0004) deliberately left a slot for: a
model reads the item's actual content and assigns `category` from the
full IDEAS.md §8 vocabulary plus the fields no rule can honestly invent —
`domain` and `concepts`. Model concepts merge with platform-curated ones
(github topics, wikipedia categories, arXiv taxonomy names) and feed the
same KB concept pages (ADR 0005).

The model call is injectable (`complete`) so tests never touch the
network, mirroring the adapters' injectable fetcher. The real completer
binds this engine's schema onto the LLM tier's shared transport
(`scrolls.llm`), so the response is schema-valid JSON by construction;
the SDK import stays lazy so only `scrolls classify --engine llm` pays
for it.

`classify_items_llm_batch` is the same engine over the Message Batches
API (ADR 0022): one submission for the whole run at half the per-token
price, polled until it ends. Identical prompts, schema, and validation —
only the transport differs.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from typing import Callable

from scrolls.items import ScrollItem

# DEFAULT_MODEL, MODEL_ENV, and LLMAuthError are deliberate re-exports:
# they predate the shared transport and remain part of this engine's
# import surface.
from scrolls.llm import (
    DEFAULT_MODEL,
    MODEL_ENV,
    Completer,
    LLMAuthError,
    LLMError,
    anthropic_complete,
)

ENGINE = "llm-v1"

# The full IDEAS.md §8 extended vocabulary. The rules engine restricts
# itself to the subset it can infer without a model; with the content in
# front of it, the LLM can use all of it responsibly.
CATEGORIES = (
    "tool",
    "research",
    "tutorial",
    "reference",
    "opinion",
    "project",
    "product",
    "media",
    "dataset",
    "paper",
    "documentation",
)

_SUMMARY_CHARS = 500
_EXCERPT_CHARS = 1500
_MAX_TOKENS = 1024

SYSTEM_PROMPT = """\
You classify saved internet artifacts for a personal knowledge library.

Given one item (title, source, URL, and content excerpts), return JSON with:

- "category": exactly one of:
  - tool: software, a library, or a utility the reader could use
  - research: research findings or analysis that is not a formal paper
  - tutorial: teaches how to do something, step by step
  - reference: encyclopedic or lookup material
  - opinion: an argument, essay, or personal viewpoint
  - project: a code repository or maker project
  - product: a commercial product or service page or announcement
  - media: video, audio, or imagery valued as media
  - dataset: a dataset or data catalog
  - paper: a formal academic paper
  - documentation: official documentation for a tool, API, or platform
- "domain": the item's topic area as a short lowercase phrase
  ("databases", "machine learning", "climate policy"), or null if the
  content does not make it clear.
- "concepts": 3-7 short noun phrases naming the specific ideas,
  technologies, or methods the item is about. Prefer canonical spellings
  ("SQLite", "BM25"). Reuse the item's existing concepts when they fit.

Classify from the provided content only; do not guess beyond it.
"""

# Structured-outputs schema: the API guarantees the response parses and
# the category is in vocabulary, so parse failures only arise from
# injected fakes or a misconfigured completer.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "domain": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "concepts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["category", "domain", "concepts"],
    "additionalProperties": False,
}

# A batch completer takes (system_prompt, [(custom_id, user_prompt)...],
# model) and returns each answered request's raw JSON text keyed by
# custom_id; a request that failed individually maps to its
# LLMClassifyError instead of text.
BatchCompleter = Callable[
    [str, "list[tuple[str, str]]", str], "dict[str, str | LLMClassifyError]"
]

_POLL_INITIAL_SECONDS = 5.0
_POLL_MAX_SECONDS = 60.0


class LLMClassifyError(LLMError):
    """The model call or its response could not produce a classification."""


def item_card(item: ScrollItem) -> str:
    """The compact item description the model classifies from.

    Empty fields are omitted; summary and extracted text are capped so a
    full arXiv paper doesn't ride along.
    """
    lines = []
    for label, value in (
        ("title", item.title),
        ("source", item.source),
        ("url", item.url),
        ("author", item.author),
        ("published_at", item.published_at),
        ("existing tags", ", ".join(item.tags)),
        ("existing concepts", ", ".join(item.concepts)),
        ("summary", (item.summary or "")[:_SUMMARY_CHARS]),
    ):
        if value:
            lines.append(f"{label}: {value}")
    if item.extracted_text:
        lines.append(f"content excerpt:\n{item.extracted_text[:_EXCERPT_CHARS]}")
    return "\n".join(lines)


def classify_item_llm(
    item: ScrollItem,
    *,
    complete: Completer | None = None,
    model: str | None = None,
) -> ScrollItem:
    """Return the item with model-assigned category, domain, and concepts.

    The input item is never mutated. Existing concepts are kept first and
    model concepts appended without duplicates, so platform-curated
    spellings stay canonical. Raises LLMClassifyError when the item has no
    classifiable content or the response is unusable.
    """
    if not (item.title or item.summary or item.extracted_text):
        raise LLMClassifyError("item has no content to classify")
    model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    if complete is None:
        complete = _anthropic_complete

    raw = complete(SYSTEM_PROMPT, item_card(item), model)
    return _classified(item, raw, model)


def classify_items_llm_batch(
    items: list[ScrollItem],
    *,
    complete_batch: BatchCompleter | None = None,
    model: str | None = None,
) -> list[tuple[ScrollItem, ScrollItem | LLMClassifyError]]:
    """Classify many items with one Message Batches submission (ADR 0022).

    Returns one (item, outcome) pair per input item in input order, where
    the outcome is the classified item or the LLMClassifyError that item
    hit — per-item failures never abort the batch. Raises LLMAuthError or
    LLMClassifyError only for whole-batch failures (no credentials, the
    submission itself rejected). Items with no classifiable content fail
    locally without being submitted.
    """
    model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    if complete_batch is None:
        complete_batch = _anthropic_complete_batch

    # custom_ids must match [A-Za-z0-9_-]{1,64}, so item ids like
    # 'wikipedia:en:SQLite' can't key the requests — positions do.
    outcomes: list[ScrollItem | LLMClassifyError | None] = [None] * len(items)
    requests: list[tuple[str, str]] = []
    for index, item in enumerate(items):
        if item.title or item.summary or item.extracted_text:
            requests.append((f"item-{index}", item_card(item)))
        else:
            outcomes[index] = LLMClassifyError("item has no content to classify")

    raw_by_id = complete_batch(SYSTEM_PROMPT, requests, model) if requests else {}
    for custom_id, _ in requests:
        index = int(custom_id.split("-", 1)[1])
        raw = raw_by_id.get(custom_id)
        if raw is None:
            outcomes[index] = LLMClassifyError("batch returned no result for this item")
        elif isinstance(raw, LLMClassifyError):
            outcomes[index] = raw
        else:
            try:
                outcomes[index] = _classified(items[index], raw, model)
            except LLMClassifyError as exc:
                outcomes[index] = exc
    return list(zip(items, outcomes))


def _classified(item: ScrollItem, raw: str, model: str) -> ScrollItem:
    """Validate one raw model response and apply it to the item."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMClassifyError(f"model returned unparseable JSON: {exc}") from exc

    category = data.get("category")
    if category not in CATEGORIES:
        raise LLMClassifyError(f"model returned unknown category: {category!r}")
    domain = data.get("domain")
    if domain is not None and not isinstance(domain, str):
        raise LLMClassifyError(f"model returned non-string domain: {domain!r}")
    new_concepts = data.get("concepts")
    if not isinstance(new_concepts, list) or not all(
        isinstance(c, str) for c in new_concepts
    ):
        raise LLMClassifyError(f"model returned malformed concepts: {new_concepts!r}")

    merged = list(item.concepts)
    merged += [c for c in new_concepts if c not in merged]
    return replace(
        item,
        category=category,
        domain=domain,
        concepts=tuple(merged),
        provenance={
            **(item.provenance or {}),
            "classified_by": ENGINE,
            "classified_model": model,
        },
    )


def _anthropic_complete(system: str, user: str, model: str) -> str:
    """The real completer: this engine's schema on the shared transport."""
    return anthropic_complete(
        system, user, model, schema=RESPONSE_SCHEMA, max_tokens=_MAX_TOKENS
    )


_sleep = time.sleep  # module-level so tests can observe the poll loop


def _anthropic_complete_batch(
    system: str, requests: list[tuple[str, str]], model: str
) -> dict[str, str | LLMClassifyError]:
    """The real batch completer: one Message Batches submission, polled.

    Each request carries exactly the params of `_anthropic_complete`'s
    call, so the model sees identical prompts and the same structured
    output schema — the Batches API just halves the per-token price.
    Polling blocks until the batch ends (typically minutes, bounded by
    the API at 24h); Ctrl-C loses only the mapping, and re-running
    resubmits. Per-request failures map to LLMClassifyError values;
    whole-batch failures raise, with the same auth handling as the
    per-item completer.
    """
    import anthropic  # lazy: only `classify --engine llm --batch` pays the import

    try:
        client = anthropic.Anthropic()
        batch = client.messages.batches.create(
            requests=[
                {
                    "custom_id": custom_id,
                    "params": {
                        "model": model,
                        "max_tokens": _MAX_TOKENS,
                        "system": system,
                        "output_config": {
                            "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}
                        },
                        "messages": [{"role": "user", "content": user}],
                    },
                }
                for custom_id, user in requests
            ]
        )
        delay = _POLL_INITIAL_SECONDS
        while batch.processing_status != "ended":
            _sleep(delay)
            delay = min(delay * 2, _POLL_MAX_SECONDS)
            batch = client.messages.batches.retrieve(batch.id)
        return {
            entry.custom_id: _batch_entry_outcome(entry)
            for entry in client.messages.batches.results(batch.id)
        }
    except TypeError as exc:
        # see _anthropic_complete: the SDK's no-credentials TypeError
        if "authentication" not in str(exc).lower():
            raise
        raise LLMAuthError(
            "llm engine needs Anthropic credentials: set ANTHROPIC_API_KEY "
            f"({exc})"
        ) from exc
    except anthropic.AuthenticationError as exc:
        raise LLMAuthError(f"Anthropic rejected the credentials: {exc}") from exc
    except anthropic.APIError as exc:
        raise LLMClassifyError(f"Anthropic API error: {exc}") from exc


def _batch_entry_outcome(entry) -> str | LLMClassifyError:
    """One batch result entry's raw text, or its per-request error."""
    result = entry.result
    if result.type == "succeeded":
        message = result.message
        if message.stop_reason == "refusal":
            return LLMClassifyError("model declined to classify this item")
        text = next((b.text for b in message.content if b.type == "text"), "")
        if not text:
            return LLMClassifyError(
                f"model returned no text (stop_reason: {message.stop_reason})"
            )
        return text
    if result.type == "errored":
        return LLMClassifyError(f"batch request errored: {result.error}")
    return LLMClassifyError(f"batch request {result.type}")  # canceled / expired
