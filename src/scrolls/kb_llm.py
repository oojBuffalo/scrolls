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
    BatchCompleter,
    Completer,
    LLMAuthError,
    LLMError,
    anthropic_complete,
    anthropic_complete_batch,
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


def eligible_concepts(items: list[ScrollItem]) -> dict[str, dict]:
    """Concepts that qualify for an LLM summary: ≥ `MIN_MEMBERS` rendered members.

    The summarization *denominator*, factored out of the two generators so
    `doctor`'s `custody.summaries` audit (roadmap H29) and the generator agree on
    exactly which concepts a summary is expected for. Cross-item synthesis is the
    value, so a one-item concept never qualifies (the same reason the generators
    skip it).
    """
    return {
        slug: entry
        for slug, entry in group_concepts(items).items()
        if len(entry["items"]) >= MIN_MEMBERS
    }


def summary_freshness(stored: ConceptSummary | None, live_digest: str) -> str:
    """Recency of a stored concept summary against the concept's *live* members.

    The summary-axis counterpart of `classify.classification_freshness`: the one
    primitive shared by the `summary_provenance` view, `doctor`'s
    `custody.summaries` aggregate, and (roadmap H31) `scrolls kb --stale`. One
    home, so the per-concept marker an agent reads, the count doctor reports, and
    the pool a refresh acts on can never disagree.

    Recency here is the *membership fingerprint*, not a wall-clock timestamp —
    the same idempotent-recency choice the classification axis makes. A summary's
    `members_hash` changes exactly when an item joins, leaves, or is refetched
    with different content (`members_hash`), the conditions under which a stored
    summary is regenerable. `live_digest` is `members_hash(...)` over the
    concept's current members. Returns:

    - ``never`` — no stored summary for this concept (eligible but never
      synthesized): unknown, not silently current.
    - ``current`` — stored under this engine with `members_hash == live_digest`:
      a re-synthesis would re-read the same members, so it is a no-op (the
      generators' incremental-skip condition).
    - ``stale`` — stored, but the members changed since synthesis (a different
      `members_hash`) or it was written by a superseded engine: regenerable.
    """
    if stored is None:
        return "never"
    if stored.engine == ENGINE and stored.members_hash == live_digest:
        return "current"
    return "stale"


def summary_provenance(
    stored: ConceptSummary | None, live_digest: str
) -> dict | None:
    """The recorded *how* of a concept summary, or None when never synthesized.

    The summary-axis counterpart of `items.classification_view`: a derived,
    read-only view of an enrichment's provenance — the engine that wrote it
    (`by`), the membership fingerprint it was synthesized from (`members_hash`),
    and its `freshness` against the concept's live members. None when no summary
    is stored — honest absence, no provenance claimed for an enrichment that does
    not exist (the `classification_view`-returns-None posture). A present view's
    freshness is always ``current`` or ``stale``; ``never`` is the absent case
    this returns None for.
    """
    if stored is None:
        return None
    return {
        "by": stored.engine,
        "members_hash": stored.members_hash,
        "freshness": summary_freshness(stored, live_digest),
    }


def is_stale_summary(stored: ConceptSummary | None, live_digest: str) -> bool:
    """True if a stored summary's members changed since synthesis (regenerable).

    The selector behind `doctor`'s `custody.summaries.stale` report and (roadmap
    H31) `scrolls kb --stale`, so the count doctor shows equals the count a
    refresh acts on — mirroring `classify.is_stale_classification` on the
    classification axis. A thin reading of `summary_freshness`, so the view, the
    doctor aggregate, and the refresh pool share one derivation. A *never*-
    summarized concept is not stale (there is nothing to regenerate, only to
    generate); an engine-mismatched or members-changed summary is.
    """
    return summary_freshness(stored, live_digest) == "stale"


def stale_summary_counts_by_source(
    items: list[ScrollItem], stored: dict[str, ConceptSummary]
) -> dict[str, int]:
    """Per-source stale-summary debt over an item set: ``{source: count}``.

    The one builder behind both `doctor`'s ``custody.summaries.by_source`` (roadmap
    H171) and the readable ``_Refresh:_`` briefing line (roadmap H178), so the count
    the audit reports and the sources the briefing names can never disagree — the
    summary-axis counterpart of `classify.stale_classification_counts_by_source`.
    Offending sources only (a source with nothing stale is omitted), keys sorted.

    **The H171 attribution, carried through.** A concept summary spans a *cluster*
    whose members may come from several sources, and the stored fingerprint records
    only the members digest, not which member moved — so a stale summary is
    attributed to **every source present among its live members** (a summary is
    "stale for source S" if S participates in the concept), exactly the offenders
    `kb --stale --source S` acts on. The consequence: one multi-source stale concept
    counts toward >1 source, so this map **need not sum to the stale-concept count**
    (``sum(values) >= stale`` concepts) — unlike the classification/drift maps where
    each item has one source.

    Pure over whatever item set it is given: `doctor` passes the whole-library (or
    `--source`-scoped) held items; the briefing passes its query scope. Eligibility
    is computed over the *given* rendered members (`eligible_concepts`), so a
    multi-source concept dropping below `MIN_MEMBERS` under a narrow scope is no
    longer eligible there — the briefing's per-source debt reflects exactly the scope
    it covers (the scope-consistent posture the readable drift line takes). `stored`
    is the `load_concept_summaries` map the caller already holds; nothing stored or
    nothing eligible is the honest empty map — a network-free no-op.
    """
    rendered = [item for item in items if item.markdown_path]
    eligible = eligible_concepts(rendered)
    counts: dict[str, int] = {}
    for slug, entry in eligible.items():
        members = entry["items"]
        if is_stale_summary(stored.get(slug), members_hash(members)):
            for source in {item.source for item in members}:
                counts[source] = counts.get(source, 0) + 1
    return {source: counts[source] for source in sorted(counts)}


def stale_summary_members(
    items: list[ScrollItem], stored: dict[str, ConceptSummary]
) -> list[ScrollItem]:
    """Held items that belong to a concept whose stored summary is stale.

    The read-side *enumeration* behind `scrolls list --stale-summary` (roadmap
    H189), the summary-axis counterpart of `classify.stale_classifications`
    (the *classification*-axis stale set). Finds the eligible concepts whose
    stored summary the live members no longer reproduce — `is_stale_summary`,
    the one predicate `doctor`'s `custody.summaries` and `kb --stale`
    (`is_stale_summary`/`_summary_targets`) share — then returns the union of
    those concepts' live members: exactly the scrolls a `kb --stale` refresh's
    clusters span (`stale_summary_counts_by_source` *counts* the same clusters
    per source; this *lists* their members).

    Eligibility is computed over the *given* rendered members
    (`eligible_concepts`), so the caller controls the scope. `list_items` passes
    the **whole library**, so a multi-source cluster stays eligible over its
    full membership (the H171 attribution — a stale cluster is stale for every
    source it spans); the per-source narrowing rides `list_items`' post-SQL
    intersection (a member appears under its own source), so
    `--stale-summary --source S` returns S's members of the clusters S
    participates in. A member belonging to several stale concepts appears once
    (deduped by id), in slug-sorted concept order — but `list_items` re-imposes
    its `saved_at, id` ordering by intersecting ids, so that order only matters
    to a direct caller. Nothing eligible or nothing stale is the honest empty
    list — a network-free, item-only computation (no model call, no ledger).
    """
    rendered = [item for item in items if item.markdown_path]
    eligible = eligible_concepts(rendered)
    seen: set[str] = set()
    members: list[ScrollItem] = []
    for slug in sorted(eligible):
        cluster = eligible[slug]["items"]
        if not is_stale_summary(stored.get(slug), members_hash(cluster)):
            continue
        for item in cluster:
            if item.id not in seen:
                seen.add(item.id)
                members.append(item)
    return members


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
    return _parse_summary(raw)


def _parse_summary(raw: str) -> str:
    """Validate one raw model response into a usable summary string.

    Shared by the per-call and batch transports so a schema or validation
    change lands in both (the same posture as classification's
    `_classified`, ADR 0022). Raises LLMError when the response is unusable.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model returned unparseable JSON: {exc}") from exc
    summary = data.get("summary") if isinstance(data, dict) else None
    if not isinstance(summary, str) or not summary.strip():
        raise LLMError(f"model returned no usable summary: {raw[:200]!r}")
    return summary.strip()


def _summary_targets(
    eligible: dict, stored: dict, stale_only: bool, source: str | None = None
) -> dict:
    """The eligible concepts a generation run should consider.

    Normally every eligible concept (the loop short-circuits current ones to a
    no-op, the rest are generated). With `stale_only` (roadmap H31, `scrolls kb
    --stale`), exactly the concepts `doctor` flags stale in `custody.summaries`
    — a stored summary whose members changed since synthesis (`is_stale_summary`,
    the one shared predicate with doctor) — so the targeted refresh touches the
    same set doctor reports and nothing else: never-summarized eligible concepts
    are left for a full `kb --engine llm` (generation, not refresh) and current
    ones are already a no-op. The shared predicate makes the count doctor shows
    equal the count `--stale` regenerates (the H27 convergence, on the summary
    axis).

    With `source` (roadmap H172, `scrolls kb --stale --source <S>`), the stale
    set is narrowed to the concepts source `<S>` participates in — `<S>` among a
    concept's live members — the same attribution `doctor`'s
    `custody.summaries.by_source` uses (H171). A stale summary records only the
    members digest, not which member moved, so a multi-source cluster is refreshed
    under *any* of its sources (it shares the cluster). The concepts returned then
    equal doctor's `summaries.by_source[<S>]` offenders, so refreshing clears that
    source's entry from the map (the H154/H27 signal-clears property, summary
    axis). `source` only narrows the stale refresh — a full run ignores it.
    """
    if not stale_only:
        return eligible
    targets = {
        slug: entry
        for slug, entry in eligible.items()
        if is_stale_summary(stored.get(slug), members_hash(entry["items"]))
    }
    if source is None:
        return targets
    return {
        slug: entry
        for slug, entry in targets.items()
        if any(item.source == source for item in entry["items"])
    }


def generate_concept_summaries(
    db_path: Path,
    *,
    complete: Completer | None = None,
    model: str | None = None,
    stale_only: bool = False,
    source: str | None = None,
) -> tuple[dict[str, int], list[dict]]:
    """Bring the summary store up to date with the library's concepts.

    Returns (counts, per-concept results). Concepts whose stored summary
    matches the current members fingerprint (and engine) are reported
    `current` without a model call; the rest are generated and saved.
    Per-concept failures are reported, never raised — except
    LLMAuthError, which propagates because every remaining concept would
    fail the same way (summaries already saved stay saved).

    With `stale_only` (`scrolls kb --stale`, roadmap H31), the run is the
    *targeted refresh* of exactly the concepts doctor flags stale — members
    changed since synthesis — and nothing else: never-summarized eligible
    concepts and orphan pruning are left to a full `kb --engine llm`. A
    current/fresh library is then a network-free no-op (no targets → no model
    call), the way `classify --stale` is on the classification axis. With
    `source` (`scrolls kb --stale --source <S>`, roadmap H172), that refresh is
    narrowed to the concepts source `<S>` participates in (see `_summary_targets`);
    an unknown source has no targets, so it is the network-free no-op too.
    """
    model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    items = [item for item in list_items(db_path) if item.markdown_path]
    eligible = eligible_concepts(items)
    stored = load_concept_summaries(db_path)
    targets = _summary_targets(eligible, stored, stale_only, source)

    counts = {"generated": 0, "current": 0, "failed": 0, "pruned": 0}
    results: list[dict] = []
    for slug in sorted(targets):
        entry = targets[slug]
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
        _store_summary(db_path, slug, entry["display"], text, digest, model)
        counts["generated"] += 1
        results.append({"slug": slug, "concept": entry["display"], "status": "generated"})

    if not stale_only:
        # pruning is a full-compile concern, not part of a targeted refresh
        _prune_orphans(db_path, stored, eligible, counts, results)
    return counts, results


def generate_concept_summaries_batch(
    db_path: Path,
    *,
    complete_batch: BatchCompleter | None = None,
    model: str | None = None,
    stale_only: bool = False,
    source: str | None = None,
) -> tuple[dict[str, int], list[dict]]:
    """Bring the summary store up to date with one Message Batches run.

    The batch transport of `generate_concept_summaries` (ADR 0022, 0032):
    every concept that needs (re)generation is sent in one submission at
    half the per-token price, instead of one API call each. Eligibility,
    incremental skipping, `stale_only`/`source` targeting, pruning, the JSON
    result shape, and per-concept failure isolation are identical — only the
    transport differs. A whole-batch failure (no credentials, the submission
    itself rejected) raises, since every concept would fail identically;
    summaries already saved stay saved.
    """
    model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
    if complete_batch is None:
        complete_batch = _anthropic_complete_batch
    items = [item for item in list_items(db_path) if item.markdown_path]
    eligible = eligible_concepts(items)
    stored = load_concept_summaries(db_path)
    targets = _summary_targets(eligible, stored, stale_only, source)

    # One pass in page order (sorted slug) settles which concepts are
    # current and which need a request; positional custom_ids key the
    # batch because a concept slug can run to 80 chars (render._MAX_SLUG_LENGTH)
    # while a Batches custom_id must be <=64 — and positions decouple the
    # keying from the slug charset, the same reason classification uses them.
    plan: list[tuple[str, dict, str, str | None]] = []
    requests: list[tuple[str, str]] = []
    for slug in sorted(targets):
        entry = targets[slug]
        digest = members_hash(entry["items"])
        prior = stored.get(slug)
        if prior and prior.members_hash == digest and prior.engine == ENGINE:
            plan.append((slug, entry, digest, None))
        else:
            custom_id = f"concept-{len(requests)}"
            requests.append((custom_id, concept_card(entry["display"], entry["items"])))
            plan.append((slug, entry, digest, custom_id))

    raw_by_id = complete_batch(SYSTEM_PROMPT, requests, model) if requests else {}

    counts = {"generated": 0, "current": 0, "failed": 0, "pruned": 0}
    results: list[dict] = []
    for slug, entry, digest, custom_id in plan:
        if custom_id is None:
            counts["current"] += 1
            results.append({"slug": slug, "concept": entry["display"], "status": "current"})
            continue
        raw = raw_by_id.get(custom_id)
        error = None
        if raw is None:
            error = "batch returned no result for this concept"
        elif isinstance(raw, LLMError):
            error = str(raw)
        else:
            try:
                text = _parse_summary(raw)
            except LLMError as exc:
                error = str(exc)
        if error is not None:
            counts["failed"] += 1
            results.append(
                {"slug": slug, "concept": entry["display"],
                 "status": "failed", "error": error}
            )
            continue
        _store_summary(db_path, slug, entry["display"], text, digest, model)
        counts["generated"] += 1
        results.append({"slug": slug, "concept": entry["display"], "status": "generated"})

    if not stale_only:
        # pruning is a full-compile concern, not part of a targeted refresh
        _prune_orphans(db_path, stored, eligible, counts, results)
    return counts, results


def _store_summary(
    db_path: Path, slug: str, display: str, text: str, digest: str, model: str
) -> None:
    """Persist one synthesized summary; shared by both transports."""
    save_concept_summary(
        db_path,
        ConceptSummary(
            slug=slug,
            display=display,
            summary=text,
            members_hash=digest,
            engine=ENGINE,
            model=model,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )


def _prune_orphans(
    db_path: Path,
    stored: dict,
    eligible: dict,
    counts: dict[str, int],
    results: list[dict],
) -> None:
    """Drop summaries whose concept no longer qualifies; record the count."""
    orphans = sorted(set(stored) - set(eligible))
    delete_concept_summaries(db_path, orphans)
    counts["pruned"] = len(orphans)
    results += [{"slug": slug, "status": "pruned"} for slug in orphans]


def _anthropic_complete(system: str, user: str, model: str) -> str:
    """The real completer: this engine's schema on the shared transport."""
    return anthropic_complete(
        system, user, model, schema=RESPONSE_SCHEMA, max_tokens=_MAX_TOKENS
    )


def _anthropic_complete_batch(
    system: str, requests: list[tuple[str, str]], model: str
) -> dict[str, str | LLMError]:
    """This engine's schema on the shared batch transport (ADR 0022, 0032)."""
    return anthropic_complete_batch(
        system, requests, model, schema=RESPONSE_SCHEMA, max_tokens=_MAX_TOKENS
    )
