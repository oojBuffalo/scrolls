"""Shareable custody bundles (ADR 0103, MVP M4).

`scrolls export bundle <query>` writes one self-contained Markdown file an
agent can hand to a person or another library: a readable *briefing* on a
topic — best matches, each with its custody **fidelity** tier (ADR 0100) and
**provenance** — plus an embedded, sentinel-fenced **custody block** holding
the lossless canonical rows. `scrolls import bundle <path>` reads that block
back, reconstructing the index rows losslessly.

The bundle is the shareable complement to `export items` (ADR 0082): where
that is the whole-library/faceted JSONL *backup* (machine-oriented, streamed
to stdout), this is the *scoped, human-and-agent-readable briefing* — same
lossless core (the `item_to_dict` rows), a different envelope and audience. It
is also the re-importable complement to `scrolls context`, which is a lossy
excerpt bundle (no raw, no full provenance) built to drop into a model's
context, not to round-trip.

Two layers in one file:

1. A briefing body (Markdown) — title + scope, a one-line scope **custody
   headline** (N scrolls, fidelity-tier counts, drift-posture counts — how
   custody stands across the whole bundle, roadmap H45; totals equal the entries
   and `doctor`'s `custody` aggregate for the scope by construction), then one
   entry per in-scope scroll naming its id, source, fidelity tier, capture
   timestamp, link, a capped excerpt, its custody **drift posture** from the
   verify ledger
   (`verified`/`unverified`/`drifted`/`rotted`/`error`, roadmap H42 — the same
   `latest_events` doctor's `custody.drift` aggregates, so they cannot disagree),
   and — when an engine classified it — *how the category was derived* (the
   `classification_provenance` view: `by`/`basis`/`confidence`, roadmap H35). A
   `concept`-scoped bundle also carries that concept's synthesized LLM summary
   and its `summary_provenance` (engine + freshness). This is what a human or
   agent *reads*, and it now carries provenance and custody posture without
   anyone parsing the JSONL ("provenance travels with every result").
2. A custody block — the canonical rows as JSON Lines inside a ` ```jsonl `
   code fence, wrapped in the ADR 0102 sentinel (`@generated`…`@end`). This is
   what `import bundle` round-trips against; the JSONL is byte-identical to
   what `export items` writes, so the bundle's losslessness is the same already
   tested by ADR 0082/0099. The sentinel makes the block machine-locatable and
   lets the briefing body above and below it carry hand annotations a
   re-export won't clobber (the refresh-safe contract, ADR 0102).
3. A custody-events block (roadmap H67) — the in-scope items' verify ledger
   (`custody_events`) as a second sibling `@generated` JSONL region, so an
   item's drift *history* travels, not just the exporter's last-seen posture
   frozen in the briefing prose: "lossless round-trip is a guarantee" (custody
   vision) extended from the item to its custody record. `import bundle`
   restores it with an idempotent, content-keyed dedup (`custody.import_events`)
   so a re-import is a custody no-op. The items block stays the first region and
   byte-identical to `export items`, so its round-trip is untouched; a pre-H67
   bundle simply has no second region and imports items only.

Completeness is honest (the M2 contract): the bundle carries *every* scroll in
scope, never a truncated top-N — a take-it-with-you custody artifact must not
silently drop members. Re-import is custody-safe: rows go in with
`INSERT OR IGNORE` (ADR 0082), so importing a bundle never overwrites an item
the target library already holds; derived artifacts (scrolls, media, the
compiled `library/`) rebuild from the rows via `scrolls doctor --fix` / `kb`,
exactly as `import items` relies on.
"""

from __future__ import annotations

import json
from pathlib import Path

from scrolls.custody import (
    CustodyEvent,
    custody_headline,
    drift_posture,
    dump_events_export,
    event_from_dict,
    events_for_items,
    latest_events,
)
from scrolls.generated import GENERATED_END, fence, generated_bodies, generated_body
from scrolls.items import (
    ScrollItem,
    classification_phrase,
    classification_provenance,
    get_fidelity,
    get_item,
    item_from_dict,
    list_items,
)
from scrolls.items_export import dump_items_export
from scrolls.kb import ConceptSummary, group_concepts, load_concept_summaries
from scrolls.kb_llm import members_hash, summary_provenance
from scrolls.render import slugify
from scrolls.search import count_matches, search_items

_EXCERPT_CHARS = 600
_REGENERATED_BY = "scrolls export bundle"
# the sibling custody-events block's label, so a reader can tell the two
# `@generated` regions apart (roadmap H67 — portable custody)
_EVENTS_REGENERATED_BY = "scrolls export bundle (custody events)"

# An item with no id/source/url/saved_at isn't a Scrolls item — mirror the
# items-export validation so a corrupt custody block fails loudly, not silently.
_REQUIRED = ("id", "source", "url", "saved_at")
# A custody event with no item_id/checked_at/status isn't a ledger row — the
# minimal identity an event must carry to be restorable (roadmap H67).
_EVENT_REQUIRED = ("item_id", "checked_at", "status")


class BundleError(Exception):
    """A file is not a Scrolls custody bundle, or its custody block is corrupt."""


def build_bundle(
    db_path: Path,
    query: str,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
) -> str:
    """Render the self-contained custody bundle for a query (briefing + block).

    Scope is the same query + facets every read surface uses (`search_items`),
    so a bundle covers exactly what a `context`/`search` of the same scope
    would — but with no cap: it carries every matching scroll (`count_matches`
    is the limit), because a custody artifact must be complete about its scope,
    not a top-N (the M2 completeness contract). Raises ValueError on a blank
    query, like `scrolls context`. No matches still yields a valid bundle (an
    empty custody block) so an agent never crashes on an empty scope.
    """
    # the honest denominator past any cap (also validates the query, raising on
    # blank) — used here as the limit so the bundle holds the *whole* scope
    matched = count_matches(
        db_path,
        query,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
    )
    hits = search_items(
        db_path,
        query,
        limit=max(matched, 1),
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
    )
    items = [item for item in (get_item(db_path, hit.id) for hit in hits) if item]
    # one ledger read for the whole scope: the latest custody verdict per item,
    # so each briefing entry can name its drift posture (H42) from the same
    # `latest_events` doctor aggregates — no per-item query, no disagreement.
    # Skipped when there is nothing to brief (no items, incl. a missing library,
    # where the ledger does not exist) so an empty/pre-init bundle stays valid.
    verdicts = latest_events(db_path) if items else {}

    title = f"# Scrolls Custody Bundle: {query}"
    scope = _scope_note(source, category, stage, tag, concept)
    if scope:
        title += f" ({scope})"
    lines = [title, ""]
    # the scope-level custody headline (roadmap H45): one line summarising how
    # custody stands across the *whole* bundle — N scrolls, fidelity tiers, drift
    # postures — so a reader gauges the scope without scanning every entry. Its
    # totals equal the per-scroll entries by construction (same get_fidelity +
    # drift_posture), the H42 convergence at scope level.
    lines += [custody_headline(items, verdicts), ""]
    # a concept-scoped bundle is *about* that concept, so its synthesized
    # summary and how that summary was derived belong in the briefing (H35)
    if concept is not None:
        lines += _concept_summary_block(db_path, concept)

    if not items:
        lines += ["No matching scrolls.", ""]
    else:
        lines += [
            f"_{len(items)} scroll(s), the whole scope — self-contained. "
            "Re-import losslessly with `scrolls import bundle <file>`. Each "
            "scroll's full custody record (raw text, provenance, fidelity) and "
            "its verify-ledger custody events travel in the fenced blocks "
            "below._",
            "",
        ]
        for rank, item in enumerate(items, start=1):
            lines += _briefing_entry(rank, item, verdicts.get(item.id))

    # the lossless custody block: the same JSONL `export items` writes, inside a
    # code fence, inside the ADR 0102 sentinel so it is locatable and the body
    # around it stays hand-annotatable across a re-export
    jsonl = dump_items_export(items)
    block = f"```jsonl\n{jsonl}```"
    lines += [fence(block, _REGENERATED_BY).rstrip("\n")]

    # the sibling custody-events block (roadmap H67): the in-scope items' verify
    # ledger so their drift *history* travels, not just the exporter's last-seen
    # posture frozen in the briefing prose. A second `@generated` region (the
    # items block stays byte-identical to `export items`, so its round-trip is
    # the same already-tested property); `import bundle` restores it deduped. An
    # unverified scope has no events — an empty block, the same shape an empty
    # items block takes — so the bundle's structure is stable.
    events = events_for_items(db_path, [item.id for item in items]) if items else []
    events_jsonl = dump_events_export(events)
    events_block = f"```jsonl\n{events_jsonl}```"
    lines += [fence(events_block, _EVENTS_REGENERATED_BY).rstrip("\n")]
    return "\n".join(lines) + "\n"


def parse_bundle(text: str) -> list[ScrollItem]:
    """Reconstruct the items from a bundle's custody block; the export inverse.

    Reads the sentinel-fenced custody block (ADR 0102), strips the ` ```jsonl `
    code fence, and parses each record the same way `import items` does
    (`item_from_dict`, required identity fields enforced, unknown keys tolerated
    for forward compatibility). Raises BundleError when the text carries no
    custody block (not a bundle) or a record is malformed, naming the record so
    corruption is locatable rather than silently dropped — losing a record from
    a custody artifact would lose data without telling anyone.
    """
    body = generated_body(text)
    if body is None:
        raise BundleError(
            "not a Scrolls custody bundle: no custody block "
            f"(expected an `@generated`…`{GENERATED_END}` region)"
        )
    items: list[ScrollItem] = []
    record_no = 0
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):  # blank or the code-fence lines
            continue
        record_no += 1
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BundleError(
                f"custody block record {record_no}: not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise BundleError(
                f"custody block record {record_no}: expected a JSON object, "
                f"got {type(data).__name__}"
            )
        missing = [name for name in _REQUIRED if not data.get(name)]
        if missing:
            raise BundleError(
                f"custody block record {record_no}: missing required field(s): "
                + ", ".join(missing)
            )
        items.append(item_from_dict(data))
    return items


def parse_bundle_events(text: str) -> list[CustodyEvent]:
    """Reconstruct the custody events from a bundle's custody-events block.

    The verify-ledger counterpart of `parse_bundle` (roadmap H67): reads the
    *second* `@generated` region (the items block is the first), strips the
    ` ```jsonl ` code fence, and parses each row through `event_from_dict`.
    Returns ``[]`` when the bundle carries no second region — a **pre-H67
    bundle** with only the items block, so its events simply do not travel (the
    prior behavior), or a present-but-empty events block (an unverified scope).
    Raises BundleError on a malformed row, naming the record, so a corrupt
    custody ledger fails loudly rather than silently dropping a check — losing
    drift history from a custody artifact would lose the proof of *when* a source
    was verified.
    """
    bodies = generated_bodies(text)
    if len(bodies) < 2:  # only the items block (a pre-H67 bundle) — no events
        return []
    events: list[CustodyEvent] = []
    record_no = 0
    for raw in bodies[1].splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):  # blank or the code-fence lines
            continue
        record_no += 1
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BundleError(
                f"custody-events block record {record_no}: not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise BundleError(
                f"custody-events block record {record_no}: expected a JSON object, "
                f"got {type(data).__name__}"
            )
        missing = [name for name in _EVENT_REQUIRED if not data.get(name)]
        if missing:
            raise BundleError(
                f"custody-events block record {record_no}: missing required "
                "field(s): " + ", ".join(missing)
            )
        events.append(event_from_dict(data))
    return events


def _briefing_entry(
    rank: int, item: ScrollItem, verdict: CustodyEvent | None
) -> list[str]:
    """The readable per-scroll briefing block: identity, custody facts, excerpt."""
    out = [f"## {rank}. {item.title or item.id} (`{item.id}`)", ""]
    facts = f"- {item.source} · fidelity `{get_fidelity(item)}` · stage `{item.stage}`"
    out.append(facts)
    out.append(f"- captured {item.saved_at}")
    out.append(f"- {item.canonical_url or item.url}")
    if item.content_hash:
        out.append(f"- content-hash `{item.content_hash}`")
    out.append(_drift_line(verdict))
    classification = _classification_line(item)
    if classification:
        out.append(classification)
    excerpt = _excerpt(item)
    if excerpt:
        out += ["", excerpt]
    out.append("")
    return out


# A reader-facing gloss per posture; the bare posture word is the convergence
# token (`custody \`<posture>\``) doctor's `custody.drift` counts agree with.
_POSTURE_GLOSS = {
    "verified": "confirmed unchanged at the last verify",
    "drifted": "source changed since capture — raw preserved, drift is a recorded event",
    "rotted": "source gone upstream — this is the last held copy",
    "error": "last re-check could not reach the source",
}


def _drift_line(verdict: CustodyEvent | None) -> str:
    """The per-scroll custody drift posture, from the verify ledger (roadmap H42).

    The posture an agent reading a shared briefing most needs to weigh: was this
    scroll confirmed unchanged, never re-checked, or has its source drifted/rotted
    since capture? Derived through the one shared `custody.drift_posture`, so the
    briefing posture and `doctor`'s `custody.drift` aggregate read the same ledger
    and cannot disagree. ``unverified`` is stated explicitly (never silently
    omitted) — "absent from the drift counts" must never be read as "confirmed
    unchanged" (the drift block's honesty, on the per-scroll axis). A drifted or
    rotted scroll is still carried losslessly in the custody block below: raw is
    sacred, drift is a *recorded posture*, never a reason to drop the scroll.
    """
    posture = drift_posture(verdict)
    if verdict is None:
        return "- custody `unverified` — never re-checked against its source"
    return (
        f"- custody `{posture}` ({_POSTURE_GLOSS[posture]}) "
        f"as of {verdict.checked_at}"
    )


def _classification_line(item: ScrollItem) -> str | None:
    """How the item's category was derived — the classification view, made readable.

    Renders the same derived `classification_provenance` view `list`/`show`/
    `search` carry (roadmap H20/H21/H26) into one briefing line, so a reader of
    the bundle sees *how the category was produced* (`by`/`basis`/`confidence`)
    without parsing the embedded JSONL — "provenance travels with every result"
    on the readable side too (roadmap H35). Returns None when no engine stamped
    the category — an unclassified or user-set item — the same honest absence the
    structured surfaces keep: no method is claimed for a category no engine
    produced, so the line is simply omitted (the row's shape stays stable).

    The ruleset *fingerprint* the view also carries (`ruleset`) is deliberately
    left out: it is the re-derivation key (in the JSONL block for that), not
    reading material, and `confidence.freshness` already reports what it implies.
    The method/confidence rendering is the shared `classification_phrase`, so this
    briefing line and the `scrolls context` per-excerpt tag (H44) read identically.
    """
    view = classification_provenance(item)
    if view is None:
        return None
    return f"- classified `{item.category}` {classification_phrase(view)}"


def _concept_summary_block(db_path: Path, concept: str) -> list[str]:
    """The bundled concept's synthesized summary + its provenance, when one exists.

    The summary-axis counterpart of `_classification_line` (roadmap H35): for a
    `concept`-scoped bundle the bundle is *about* that concept, so its stored LLM
    concept summary (ADR 0025) — and how that summary was derived — belongs in
    the readable briefing. Freshness is computed against the concept's *whole*
    live membership (`summary_provenance`/`summary_freshness`), not the bundle's
    query-filtered subset, because a summary is a synthesis of the entire concept;
    filtering the members for a bundle does not change whether a re-synthesis
    would reproduce the stored summary.

    Returns [] when the concept has no stored summary — honest absence
    (`summary_provenance` returns None), no synthesis claimed for one that does
    not exist. The summary text here is a *readable derived view*, not part of
    the lossless custody block: only the item rows in the `@generated` JSONL
    round-trip through `import bundle` (the round-trip invariant H35 leaves
    untouched).
    """
    slug = slugify(concept)
    if not slug:
        return []
    stored: ConceptSummary | None = load_concept_summaries(db_path).get(slug)
    if stored is None:
        return []
    rendered = [item for item in list_items(db_path) if item.markdown_path]
    entry = group_concepts(rendered).get(slug)
    live = members_hash(entry["items"]) if entry else ""
    view = summary_provenance(stored, live)
    if view is None:  # unreachable while `stored` is set, but keeps the contract local
        return []
    return [
        f"**Concept summary** — {stored.summary}",
        "",
        f"_Summary by `{view['by']}`, {view['freshness']} "
        f"(members fingerprint `{view['members_hash'][:12]}`)._",
        "",
    ]


def _scope_note(
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
) -> str:
    """A `source=…, category=…` summary of the active facets, else '' (as `context`)."""
    parts = []
    if source is not None:
        parts.append(f"source={source}")
    if category is not None:
        parts.append(f"category={category or 'unclassified'}")
    if stage is not None:
        parts.append(f"stage={stage}")
    if tag is not None:
        parts.append(f"tag={tag}")
    if concept is not None:
        parts.append(f"concept={concept}")
    return ", ".join(parts)


def _excerpt(item: ScrollItem) -> str:
    text = " ".join((item.summary or item.extracted_text or "").split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    return text[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
