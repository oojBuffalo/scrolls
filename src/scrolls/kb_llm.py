"""LLM concept engine for KB pages (IDEAS.md §9's fancy version, ADR 0025).

The deterministic compiler (ADR 0005) groups scrolls by concept; this
engine writes the prose those pages can't derive — a short synthesis of
how each concept shows up across its member scrolls. Summaries land in
the `concept_summaries` store (`kb.py`), so the compiler includes them
on every later run without a model, key, or network.

Generation is incremental: each summary records a fingerprint of the
member scrolls it was written from, and a concept whose members haven't
changed is skipped — re-running `scrolls kb --engine llm` on an
unchanged library costs nothing (the same posture as feed HTTP caching,
ADR 0019). Only concepts with at least `MIN_MEMBERS` scrolls qualify:
cross-item synthesis is the value, and a one-item page has nothing to
synthesize. Summaries for concepts that no longer qualify are pruned.

The model call is injectable (`complete`) like every engine's, so tests
never touch the network; the real completer binds this engine's schema
onto the LLM tier's shared transport (`scrolls.llm`).
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scrolls.items import ScrollItem, list_items
from scrolls.kb import (
    ConceptSummary,
    delete_concept_summaries,
    group_concepts,
    load_concept_summaries,
    save_concept_summary,
)
from scrolls.llm import (
    DEFAULT_MODEL,
    MODEL_ENV,
    Completer,
    LLMAuthError,
    LLMError,
    anthropic_complete,
)

ENGINE = "kb-llm-v1"
MIN_MEMBERS = 2

_MEMBER_CHARS = 300
_MAX_MEMBERS = 25
_MAX_TOKENS = 1024

SYSTEM_PROMPT = """\
You write the lead summary for a concept page in a personal knowledge
library of saved internet artifacts.

Given one concept and the saved items that share it (each with title,
source, and a short excerpt), return JSON with:

- "summary": 2-4 sentences of plain prose describing how the concept
  shows up across these items — what they collectively cover and what a
  reader would find by following them. Mention items by title when it
  helps. Write from the provided content only; never invent items,
  facts, or connections the excerpts do not support.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}},
    "required": ["summary"],
    "additionalProperties": False,
}


def members_hash(items: list[ScrollItem]) -> str:
    """Fingerprint of a concept's membership and content.

    Changes exactly when an item joins, leaves, or is refetched with
    different content — the conditions under which a stored summary is
    stale. Order-independent.
    """
    lines = sorted(f"{item.id}\t{item.content_hash or ''}" for item in items)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def concept_card(display: str, items: list[ScrollItem]) -> str:
    """The compact concept description the model synthesizes from.

    One line per member scroll — title, source, capped excerpt — in the
    concept page's own ordering. Oversized concepts are truncated with
    an honest count so the prompt stays bounded.
    """
    ordered = sorted(items, key=lambda i: ((i.title or i.id).casefold(), i.id))
    lines = [f"concept: {display}", "", "items:"]
    for item in ordered[:_MAX_MEMBERS]:
        line = f"- {item.title or item.id} ({item.source})"
        excerpt = (item.summary or item.extracted_text or "").strip()
        if excerpt:
            line += f" — {excerpt[:_MEMBER_CHARS]}"
        lines.append(line)
    if len(ordered) > _MAX_MEMBERS:
        lines.append(f"(and {len(ordered) - _MAX_MEMBERS} more items not shown)")
    return "\n".join(lines)


def summarize_concept_llm(
    display: str,
    items: list[ScrollItem],
    *,
    complete: Completer | None = None,
    model: str | None = None,
) -> str:
    """One synthesized summary paragraph for a concept page.

    Raises LLMError when the response is unusable (LLMAuthError from the
    real completer when no credentials resolve).
    """
    model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    if complete is None:
        complete = _anthropic_complete

    raw = complete(SYSTEM_PROMPT, concept_card(display, items), model)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model returned unparseable JSON: {exc}") from exc
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        raise LLMError(f"model returned no usable summary: {raw[:200]!r}")
    return summary.strip()


def generate_concept_summaries(
    db_path: Path,
    *,
    complete: Completer | None = None,
    model: str | None = None,
) -> tuple[dict[str, int], list[dict]]:
    """Bring the summary store up to date with the library's concepts.

    Returns (counts, per-concept results). Concepts whose stored summary
    matches the current members fingerprint (and engine) are reported
    `current` without a model call; the rest are generated and saved.
    Per-concept failures are reported, never raised — except
    LLMAuthError, which propagates because every remaining concept would
    fail the same way (summaries already saved stay saved).
    """
    model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    items = [item for item in list_items(db_path) if item.markdown_path]
    eligible = {
        slug: entry
        for slug, entry in group_concepts(items).items()
        if len(entry["items"]) >= MIN_MEMBERS
    }
    stored = load_concept_summaries(db_path)

    counts = {"generated": 0, "current": 0, "failed": 0, "pruned": 0}
    results: list[dict] = []
    for slug in sorted(eligible):
        entry = eligible[slug]
        digest = members_hash(entry["items"])
        prior = stored.get(slug)
        if prior and prior.members_hash == digest and prior.engine == ENGINE:
            counts["current"] += 1
            results.append({"slug": slug, "concept": entry["display"], "status": "current"})
            continue
        try:
            text = summarize_concept_llm(
                entry["display"], entry["items"], complete=complete, model=model
            )
        except LLMAuthError:
            raise  # summaries saved so far stay saved; the CLI reports the abort
        except LLMError as exc:
            counts["failed"] += 1
            results.append(
                {"slug": slug, "concept": entry["display"],
                 "status": "failed", "error": str(exc)}
            )
            continue
        save_concept_summary(
            db_path,
            ConceptSummary(
                slug=slug,
                display=entry["display"],
                summary=text,
                members_hash=digest,
                engine=ENGINE,
                model=model,
                generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        counts["generated"] += 1
        results.append({"slug": slug, "concept": entry["display"], "status": "generated"})

    orphans = sorted(set(stored) - set(eligible))
    delete_concept_summaries(db_path, orphans)
    counts["pruned"] = len(orphans)
    results += [{"slug": slug, "status": "pruned"} for slug in orphans]
    return counts, results


def _anthropic_complete(system: str, user: str, model: str) -> str:
    """The real completer: this engine's schema on the shared transport."""
    return anthropic_complete(
        system, user, model, schema=RESPONSE_SCHEMA, max_tokens=_MAX_TOKENS
    )
