"""LLM classification engine (IDEAS.md §8 layer two, ADR 0015).

The layer the rules engine (ADR 0004) deliberately left a slot for: a
model reads the item's actual content and assigns `category` from the
full IDEAS.md §8 vocabulary plus the fields no rule can honestly invent —
`domain` and `concepts`. Model concepts merge with platform-curated ones
(github topics, wikipedia categories, arXiv taxonomy names) and feed the
same KB concept pages (ADR 0005).

The model call is injectable (`complete`) so tests never touch the
network, mirroring the adapters' injectable fetcher. The real completer
uses the official Anthropic SDK with structured outputs, so the response
is schema-valid JSON by construction; it is imported lazily so only
`scrolls classify --engine llm` pays for it.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Callable

from scrolls.items import ScrollItem

ENGINE = "llm-v1"
DEFAULT_MODEL = "claude-opus-4-8"
MODEL_ENV = "SCROLLS_LLM_MODEL"

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

# A completer takes (system_prompt, user_prompt, model) and returns the
# model's JSON text.
Completer = Callable[[str, str, str], str]


class LLMClassifyError(Exception):
    """The model call or its response could not produce a classification."""


class LLMAuthError(LLMClassifyError):
    """No usable Anthropic credentials; retrying other items is pointless."""


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
    """The real completer: one Messages API call with structured outputs."""
    import anthropic  # lazy: only `classify --engine llm` pays the import

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": user}],
        )
    except TypeError as exc:
        # The SDK raises TypeError when no credentials resolve — at client
        # construction in some versions, while building the request in
        # others. Any other TypeError is a real bug and must surface.
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

    if response.stop_reason == "refusal":
        raise LLMClassifyError("model declined to classify this item")
    text = next((b.text for b in response.content if b.type == "text"), "")
    if not text:
        raise LLMClassifyError(
            f"model returned no text (stop_reason: {response.stop_reason})"
        )
    return text
