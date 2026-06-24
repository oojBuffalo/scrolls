"""Shareable custody bundles (ADR 0103, MVP M4).

`scrolls export bundle <query>` writes one self-contained Markdown file an
agent can hand to a person or another library: a readable *briefing* on a
topic — best matches, each with its custody **fidelity** tier (ADR 0100) and
**provenance** — plus an embedded, sentinel-fenced **custody block** holding
the lossless canonical rows. `scrolls import bundle <path>` reads that block
back, reconstructing the index rows losslessly.

Two output forms (`--format`, roadmap H39): the **Markdown** bundle
(`build_bundle`) is the canonical, lossless, re-importable artifact this module's
round-trip rests on; the **HTML** bundle (`build_bundle_html`) renders the same
scope and per-scroll custody picture as a self-contained, browser-readable
briefing — the human-facing **read** form, *export-only* (its embedded custody
JSONL is present but `import bundle` consumes the Markdown form; no false
round-trip claim). Both share `_gather_scope` and the custody/provenance
primitives, so they cannot disagree.

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
   and `doctor`'s `custody` aggregate for the scope by construction), then — for a
   *multi-source* scope — a **per-source breakdown** under it (`_By source:_`, one
   bullet per source: fidelity/drift counts, roadmap H141; the same
   `custody_counts_by_source` `doctor`'s `custody.by_source` reports, so it sums to
   the scope headline and names *which* source's custody is weakest within the
   shared scope). Then one entry per in-scope scroll naming its id, source,
   fidelity tier, capture
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
   bundle simply has no second region and imports items only. The restore is also
   honest about **orphan** events (roadmap H217): every event must resolve to a
   held-or-imported item; one whose `item_id` names no such item (a corrupt or
   hand-edited bundle — a well-formed export never desyncs the blocks) is counted
   (`orphaned`) and *not* inserted, never a dangling ledger row for an item the
   library does not hold (`custody.partition_resolvable_events`).

Completeness is honest (the M2 contract): the bundle carries *every* scroll in
scope, never a truncated top-N — a take-it-with-you custody artifact must not
silently drop members. Re-import is custody-safe: rows go in with
`INSERT OR IGNORE` (ADR 0082), so importing a bundle never overwrites an item
the target library already holds; derived artifacts (scrolls, media, the
compiled `library/`) rebuild from the rows via `scrolls doctor --fix` / `kb`,
exactly as `import items` relies on.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from scrolls.classify import stale_classification_counts_by_source
from scrolls.custody import (
    CustodyEvent,
    custody_counts_by_source,
    custody_headline,
    custody_source_breakdown,
    drift_posture,
    dump_events_export,
    event_from_dict,
    events_for_items,
    latest_conflict_events,
    latest_events,
    render_custody_attention,
    render_custody_by_source,
    render_custody_conflicts,
    render_custody_refresh,
    unresolved_conflicts,
    weakest_source,
)
from scrolls.generated import GENERATED_END, fence, generated_bodies, generated_body
from scrolls.items import (
    ArchiveRecord,
    ScrollItem,
    archive_from_dict,
    archive_integrity_block,
    archived_records,
    classification_phrase,
    classification_provenance,
    dump_archive_export,
    get_fidelity,
    get_item,
    item_from_dict,
    list_items,
)
from scrolls.items_export import dump_items_export
from scrolls.maintain import archive_integrity_headline, render_archive_integrity
from scrolls.kb import ConceptSummary, group_concepts, load_concept_summaries
from scrolls.kb_llm import (
    members_hash,
    stale_summary_counts_by_source,
    summary_provenance,
)
from scrolls.render import slugify
from scrolls.search import (
    count_matches,
    render_strength_headline,
    search_items,
    tally_strength,
)
from scrolls.works import at_risk_signal, render_at_risk_works, works_over

_EXCERPT_CHARS = 600
_REGENERATED_BY = "scrolls export bundle"
# the sibling custody-events block's label, so a reader can tell the two
# `@generated` regions apart (roadmap H67 — portable custody)
_EVENTS_REGENERATED_BY = "scrolls export bundle (custody events)"
# the optional third region's label (roadmap H280 — `--with-archive`): the
# prior-content archive's recoverable superseded captures, so a reader can tell
# the three `@generated` regions apart (items, custody events, prior archive)
_ARCHIVE_REGENERATED_BY = "scrolls export bundle (prior-content archive)"

# An item with no id/source/url/saved_at isn't a Scrolls item — mirror the
# items-export validation so a corrupt custody block fails loudly, not silently.
_REQUIRED = ("id", "source", "url", "saved_at")
# A custody event with no item_id/checked_at/status isn't a ledger row — the
# minimal identity an event must carry to be restorable (roadmap H67).
_EVENT_REQUIRED = ("item_id", "checked_at", "status")
# An archive row with no item_id/archived_at/snapshot isn't a restorable prior —
# the minimal identity it must carry (roadmap H280, the H67 events shape).
_ARCHIVE_REQUIRED = ("item_id", "archived_at", "snapshot")

# Inline stylesheet for the HTML briefing (roadmap H39) — kept in the document so
# the file is self-contained and offline (no external CSS/JS, nothing fetched
# from the network). `color-scheme` follows the reader's light/dark preference.
_HTML_STYLE = """\
:root { color-scheme: light dark; }
body { font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui,
       sans-serif; max-width: 48rem; margin: 2rem auto; padding: 0 1rem; }
h1 { font-size: 1.6rem; }
h2 { font-size: 1.15rem; margin-top: 2rem; padding-top: 1rem;
     border-top: 1px solid rgba(127,127,127,.3); }
code { background: rgba(127,127,127,.15); padding: .1em .3em; border-radius: 3px;
       font-size: .9em; }
.custody-headline { font-weight: 600; }
.rank-strength { font-weight: 600; }
.custody-attention { font-weight: 600; color: #b3261e; }
.custody-at-risk { font-weight: 600; color: #b3261e; }
.custody-conflicts { font-weight: 600; color: #b3261e; }
.custody-archive { font-weight: 600; color: #b3261e; }
.custody-refresh { font-weight: 600; color: #9a6700; }
.note { color: #6a6a6a; font-size: .85rem; }
.custody-facts { list-style: none; padding-left: 0; }
.custody-facts li { margin: .15rem 0; }
.excerpt { border-left: 3px solid rgba(127,127,127,.4); margin: .5rem 0;
           padding: .25rem 0 .25rem 1rem; }
details.custody-data { margin-top: 2rem; }
details.custody-data pre { overflow-x: auto; padding: 1rem; border-radius: 4px;
                           background: rgba(127,127,127,.1); font-size: .8rem; }
"""


class BundleError(Exception):
    """A file is not a Scrolls custody bundle, or its custody block is corrupt."""


def _gather_scope(
    db_path: Path,
    query: str,
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
) -> tuple[
    list[ScrollItem], dict[str, CustodyEvent], list[CustodyEvent], dict[str, str]
]:
    """Resolve the bundle scope once, for both the Markdown and HTML renderers.

    Returns the in-scope items (every match, no cap — `count_matches` is the
    limit, the M2 completeness contract), the latest custody verdict per item
    (`latest_events`, one read for the whole scope, the drift-posture source),
    the in-scope verify ledger (`events_for_items`, the portable custody
    events, roadmap H67), and the per-id **rank strength** map
    (`{id: match_strength}`, roadmap H317) — each ranked hit's
    `strong`/`moderate`/`weak` band (the field-weight explanation behind the
    BM25 `score`, H312), which both forms fold into a `_Strength:_` headline and
    a per-scroll marker so the portable briefing explains *how strongly* each
    match ranked, not just *what* matched. The strength rides the hit (already
    on every `search_items` result), so threading it out costs no extra read.
    `count_matches` also validates the query, raising ValueError on a blank one.
    The ledger reads are skipped when there is nothing to brief (no items, incl. a
    missing library) so an empty/pre-init bundle stays valid in either format.

    `fidelity`/`drift` (roadmap H258) are the two per-item *custody* scopes — the
    custody-filter family on the portable shareable bundle. They thread straight
    to `count_matches`/`search_items`, which apply the `scrolls_fidelity`/
    `scrolls_drift` UDFs in SQL (the `search --fidelity`/`--drift` primitives,
    H251/H253), so the *whole* gathered set — the items, their ledger verdicts,
    and the portable events block — is sieved by custody value at the source.
    Every fold downstream (the briefing prose, the lossless custody block, the
    events block) therefore describes exactly the exported slice, and the lossless
    round-trip holds over it (`import bundle` re-holds exactly the kept rows, the
    H216 mixed-fidelity round-trip under a custody scope). An unknown tier/posture
    raises ValueError (a closed vocabulary; the CLI also rejects it via argparse
    `choices`). The bundle carries no cap, so unlike `search`/`context` there is
    no before-/after-cap distinction — the sieve simply narrows the complete set.

    `strength` (roadmap H318) is the rank-axis third scope beside the two custody
    axes — the act companion of the `_Strength:_` explanation (H317). It threads to
    the same `search_items`/`count_matches` column-restricted sub-match
    `search --strength` (H314) built, keeping only the matches whose query lands at
    or above a field-weight band (`strong` title hits, `moderate` title-or-summary,
    `weak` everything), so an operator ships "only the strong matches about X" as a
    portable briefing. The narrowed set's `strengths` map re-folds H317's
    `_Strength:_` headline over exactly the kept slice. ANDs with the facets and the
    custody axes; an unknown band raises ValueError (the same closed vocabulary).
    """
    matched = count_matches(
        db_path,
        query,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
        fidelity=fidelity,
        drift=drift,
        strength=strength,
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
        fidelity=fidelity,
        drift=drift,
        strength=strength,
    )
    items = [item for item in (get_item(db_path, hit.id) for hit in hits) if item]
    verdicts = latest_events(db_path) if items else {}
    events = events_for_items(db_path, [item.id for item in items]) if items else []
    # the per-id rank-strength explanation (roadmap H317), keyed by id so it
    # survives the `get_item`-None filter above — every kept item is a query
    # match, so its id is present.
    strengths = {hit.id: hit.match_strength for hit in hits}
    return items, verdicts, events, strengths


def _refresh_debt_by_source(
    db_path: Path, items: list[ScrollItem]
) -> tuple[dict[str, int], dict[str, int]]:
    """The per-source stale-classification / stale-summary debt over the scope (H178).

    The shared core behind the Markdown `_Refresh:_` line (`render_custody_refresh`)
    and its HTML twin (`_refresh_html`), so the two forms name the same sources.
    Both maps are computed over the bundle's *own* scope items by the one shared
    builder each axis uses — `classify.stale_classification_counts_by_source` and
    `kb_llm.stale_summary_counts_by_source` (the same builders `doctor`'s
    `custody.enrichment.by_source`/`custody.summaries.by_source` fold) — so the
    briefing's refresh debt converges with the audit's maps for the same scope by
    construction. The summary axis needs the stored summaries (`load_concept_summaries`,
    the one read the bundle would not otherwise make); an empty scope holds nothing
    eligible, so both maps are the honest empty no-op. Returns
    ``(enrichment_by_source, summary_by_source)``.
    """
    if not items:
        return {}, {}
    enrichment = stale_classification_counts_by_source(items)
    summary = stale_summary_counts_by_source(items, load_concept_summaries(db_path))
    return enrichment, summary


def _strength_headline(items: list[ScrollItem], strengths: dict[str, str]) -> str:
    """The bundle-level `_Strength:_` rank-confidence headline (roadmap H317).

    The shared fold both bundle forms render so they cannot disagree: tally each
    in-scope item's own `match_strength` (`strengths`, the `_gather_scope` map)
    into the `{strong, moderate, weak}` histogram and distil it through the shared
    `search.render_strength_headline` — the same primitive the `scrolls context`
    bundle's `_Strength:_` headline uses (H315). The tally is over the *raw matched
    set* (the export bundle has no cap and no same-work collapse, unlike `context`),
    so the count sums to the entry count. A `weak` default keeps the fold total
    over the structurally-impossible missing-id case (every kept item is a match).
    """
    return render_strength_headline(
        tally_strength(strengths.get(item.id, "weak") for item in items)
    )


def build_bundle(
    db_path: Path,
    query: str,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
    with_archive: bool = False,
) -> str:
    """Render the self-contained custody bundle for a query (briefing + block).

    Scope is the same query + facets every read surface uses (`search_items`),
    so a bundle covers exactly what a `context`/`search` of the same scope
    would — but with no cap: it carries every matching scroll (`count_matches`
    is the limit), because a custody artifact must be complete about its scope,
    not a top-N (the M2 completeness contract). Raises ValueError on a blank
    query, like `scrolls context`. No matches still yields a valid bundle (an
    empty custody block) so an agent never crashes on an empty scope.

    `fidelity`/`drift` (roadmap H258) add the two per-item *custody* scopes — the
    custody-filter family on the portable shareable bundle, the export twin of
    `context --fidelity`/`--drift` (H257). They narrow the bundle to one holdings
    tier (`full`/`partial`/`reference`, ADR 0097) or one verify-ledger posture
    (`verified`/…/`drifted`, H58) so an agent can "share only my full-fidelity
    holdings on this topic" or "export only the drifted ones for a recapture
    handoff". Both AND with the facets, are sieved in SQL by `_gather_scope`, and
    are echoed in the title scope note (provenance of *what slice* was shared), so
    the briefing prose (`custody_headline`, the per-source breakdown, the
    `_Attention:_`/`_Refresh:_` pointers) and the embedded lossless custody +
    events blocks all describe exactly the exported set — and `import bundle` of
    it re-holds exactly those rows (the H216 round-trip under a custody scope). An
    unknown tier/posture raises ValueError (closed vocabulary; the CLI also
    rejects it via argparse `choices`).

    `strength` (roadmap H318) is the rank-axis third scope — the act companion of
    H317's `_Strength:_` explanation. It narrows the bundle to one rank-strength
    band (threshold semantics: `strong` keeps title hits, `moderate`
    title-or-summary, `weak` everything — the `search --strength` band, H314) so an
    operator ships "only the strong (title-hit) matches about X". ANDs with the
    facets and the custody axes, is echoed in the title scope note, and re-folds the
    `_Strength:_` headline over exactly the kept slice; an unknown band raises
    ValueError (the same closed vocabulary; the CLI also rejects via argparse
    `choices`).

    `with_archive` (roadmap H280) appends a *third* sentinel-fenced region — the
    in-scope items' prior-content archive (`item_archive`, ADR 0106): the
    recoverable superseded captures, so "take it with me" includes the recovery
    store and `scrolls archive show` works on the rebuilt library. It is **opt-in**
    because the archive can be large (a model-complete prior body per adoption) and
    the `superseded` event already travels in the events block documenting *that*
    an adoption happened; without the flag the bundle carries only the items + events
    blocks (byte-identical to a pre-H280 bundle). `import bundle` restores whatever
    archive block is present **unconditionally** (deduped) — the flag is an export
    concern only.

    This is the **canonical, lossless re-import unit**: the Markdown form
    `scrolls import bundle` round-trips against. The browser-readable HTML form
    (`build_bundle_html`, roadmap H39) is export-only.
    """
    # one ledger read for the whole scope: the latest custody verdict per item,
    # so each briefing entry can name its drift posture (H42) from the same
    # `latest_events` doctor aggregates — no per-item query, no disagreement.
    items, verdicts, events, strengths = _gather_scope(
        db_path, query, source, category, stage, tag, concept, fidelity, drift,
        strength,
    )

    title = f"# Scrolls Custody Bundle: {query}"
    scope = _scope_note(
        source, category, stage, tag, concept, fidelity, drift, strength
    )
    if scope:
        title += f" ({scope})"
    lines = [title, ""]
    # the scope-level custody headline (roadmap H45): one line summarising how
    # custody stands across the *whole* bundle — N scrolls, fidelity tiers, drift
    # postures — so a reader gauges the scope without scanning every entry. Its
    # totals equal the per-scroll entries by construction (same get_fidelity +
    # drift_posture), the H42 convergence at scope level.
    lines += [custody_headline(items, verdicts), ""]
    # the bundle-level rank-confidence headline (roadmap H317): one `_Strength:_`
    # line summarising how strongly the matches ranked — strong (title hits),
    # moderate (summary), weak (body-only) — beside the custody headline, the
    # explainable-ranking surface (H315) lifted to the portable briefing. Unlike
    # the `context` bundle, the export bundle carries no cap and does **not**
    # collapse same-work duplicates (every match is its own entry), so the tally
    # is over the *raw matched set* (`strengths` per kept item) — and the shared
    # `render_strength_headline(tally_strength(...))` the HTML form folds over the
    # same map renders byte-convergent counts by construction (the H39/H271 twin).
    # Ledger-free (a pure FTS-rank fact like fidelity); honest no-op on an empty
    # scope (nothing matched → no rank confidence to report).
    if items:
        lines += [_strength_headline(items, strengths), ""]
    # the readable weakest-source pointer (roadmap H159): one `_Attention:_` line
    # naming the single source with the most actionable loss and the exact recheck
    # command, so a reader skims "this one source needs attention" before scanning
    # the per-source map below. Distilled by the shared `weakest_source` over the
    # same `by_source` the breakdown folds, so it converges field-for-field with
    # `status`/`maintain`'s JSON `attention`; honest no-op when no source carries
    # actionable loss (single-source / clean / empty scope — [] lines).
    by_source = custody_counts_by_source(items, verdicts)
    lines += render_custody_attention(by_source)
    # the readable work-level at-risk pointer (roadmap H264): one `_At-risk work:_`
    # line naming the single work no representation safely holds (the H263 at-risk
    # alarm's `most_at_risk`) — the *consolidation*-level counterpart of the
    # per-source `_Attention:_` line above. Distilled by the shared
    # `at_risk_signal` over the bundle scope's own clustered works (the lean-scope
    # decision: cluster the *gathered* item set, the same scope the source line and
    # the `_By source:_` map describe), so it names the same work as `doctor`'s
    # `custody.works`/`maintain`'s `at_risk_works`/MCP `get_library_health` by
    # construction; honest no-op when no multi-representation work in scope is at
    # risk ([] lines).
    lines += render_at_risk_works(items, verdicts)
    # the readable import-conflict pointer (roadmap H277): one `_Conflicts:_` line
    # naming how many held items in scope carry an *unresolved import conflict* (a
    # peer's capture disagreed with the held copy at merge time, ADR 0104, still
    # open — raw is never auto-overwritten) — the readable completion of H275's JSON
    # `custody.conflicts` aggregate, beside the drift `_Attention:_` and
    # consolidation `_At-risk work:_` divergence lines above. Folds the *same*
    # `unresolved_conflicts` over the *same* `latest_conflict_events` map `doctor`'s
    # `custody.conflicts` reads, so the count converges with the JSON block for the
    # same scope by construction; names no command (the `reconcile` act is H276,
    # the at-risk orphan-command discipline); honest no-op when no held item in
    # scope carries an unresolved conflict ([] lines).
    conflicts = latest_conflict_events(db_path) if items else {}
    lines += render_custody_conflicts(items, conflicts)
    # the readable archive-integrity pointer (roadmap H319): one `_Archive:_` line
    # when any in-scope item's archived prior is corrupt — its advertised
    # `prior_hash` no longer equals its snapshot's `content_hash`, a custody-honesty
    # bug invisible until restore (`archive restore --hash` would adopt content with
    # a different hash than advertised). The archive-axis sibling of the `_Conflicts:_`
    # divergence line above, the readable completion of `doctor`'s `custody.archive`
    # (H293). **In-scope** (the in-scope items' archive, like `_Conflicts:_` and the
    # `--with-archive` block) and rendered **unconditionally** — independent of
    # `--with-archive`: the flag governs whether the archive *data* travels, not
    # whether custody honesty about it does (§2.4). Folds the *same*
    # `archive_integrity_block` over the *same* in-scope `archived_records` `doctor`
    # reads whole-library, rendered by the *same* `archive_integrity_headline` the
    # `maintain` line uses, so the readable line, the JSON audit, and the maintenance
    # summary converge by construction; honest no-op on a clean/empty scope ([] lines).
    lines += _archive_integrity_lines(db_path, items)
    # the readable per-source refresh pointer (roadmap H178): one `_Refresh:_` line
    # naming the source(s) whose classifications/summaries are stale and the exact
    # `classify --stale`/`kb --stale --source <S>` refresh — the enrichment/summary-
    # axis counterpart of the drift `_Attention:_` line above. Computed over the
    # bundle's own scope items by the same `stale_*_counts_by_source` builders
    # `doctor`'s `custody.enrichment.by_source`/`summaries.by_source` fold, so the
    # named sources converge with the audit maps by construction; honest no-op when
    # no source carries refresh debt on either axis ([] lines).
    enrichment_by_source, summary_by_source = _refresh_debt_by_source(db_path, items)
    lines += render_custody_refresh(enrichment_by_source, summary_by_source)
    # the per-source custody breakdown under the scope headline (roadmap H141):
    # a multi-source shared briefing names *which* source's custody is weakest
    # within the scope. Folds the same `custody_counts_by_source` the per-scroll
    # entries and the scope headline already cover, so it sums to the headline by
    # construction; a single-source/empty scope is the honest no-op ([] lines).
    lines += render_custody_by_source(by_source)
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
            lines += _briefing_entry(
                rank, item, verdicts.get(item.id), strengths.get(item.id)
            )

    # the lossless custody block + the sibling custody-events block — the same
    # sentinel-fenced JSONL the HTML form embeds, so the two formats carry
    # byte-identical custody data (the round-trip stays a Markdown property)
    lines += [_items_block(items)]
    lines += [_events_block(events)]
    # the optional third region (roadmap H280, `--with-archive`): the in-scope
    # items' prior-content archive, so the recovery store travels. Emitted *only*
    # under the flag, so a default bundle stays byte-identical to a pre-H280 one
    # (the items+events two-region shape the round-trip / byte-identity tests pin).
    if with_archive:
        archive = archived_records(db_path, [item.id for item in items]) if items else []
        lines += [_archive_block(archive)]
    return "\n".join(lines) + "\n"


def _items_block(items: list[ScrollItem]) -> str:
    """The lossless custody block: the same JSONL `export items` writes, inside a
    code fence, inside the ADR 0102 sentinel so it is locatable and the body
    around it stays hand-annotatable across a re-export."""
    block = f"```jsonl\n{dump_items_export(items)}```"
    return fence(block, _REGENERATED_BY).rstrip("\n")


def _events_block(events: list[CustodyEvent]) -> str:
    """The sibling custody-events block (roadmap H67): the in-scope items' verify
    ledger so their drift *history* travels, not just the exporter's last-seen
    posture frozen in the briefing prose. A second `@generated` region (the items
    block stays byte-identical to `export items`, so its round-trip is the same
    already-tested property); `import bundle` restores it deduped. An unverified
    scope has no events — an empty block, the same shape an empty items block
    takes — so the bundle's structure is stable."""
    block = f"```jsonl\n{dump_events_export(events)}```"
    return fence(block, _EVENTS_REGENERATED_BY).rstrip("\n")


def _archive_block(records: list[ArchiveRecord]) -> str:
    """The optional third region (roadmap H280): the in-scope items' prior-content
    archive (`item_archive`, ADR 0106) as the same JSONL `export archive` writes,
    inside a code fence, inside the ADR 0102 sentinel.

    Carries the recoverable superseded captures so "take it with me" includes the
    recovery store — the `superseded` event in the events block above documents
    *that* an adoption happened, this carries the prior *bytes* so `archive show`
    works on a rebuilt library. A third `@generated` region (items=0, events=1,
    archive=2); `import bundle` restores it deduped by `(item_id, prior_hash)`. An
    archive with nothing in scope is an empty block — the same shape an empty
    items/events block takes, so the structure stays stable under `--with-archive`."""
    block = f"```jsonl\n{dump_archive_export(records)}```"
    return fence(block, _ARCHIVE_REGENERATED_BY).rstrip("\n")


def build_bundle_html(
    db_path: Path,
    query: str,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
    with_archive: bool = False,
) -> str:
    """Render the scoped custody bundle as a self-contained, offline HTML briefing.

    The browser-readable, human-facing **read** counterpart of `build_bundle`
    (roadmap H39): the same scope (every match, no cap — `_gather_scope`) and the
    same per-scroll custody picture — fidelity tier, drift posture, classification
    provenance, and (for a `--concept` bundle) the synthesized summary — rendered
    into one self-contained HTML file (inline CSS, no scripts, nothing fetched
    from the network). All dynamic content is HTML-escaped, so a tag-bearing
    title or body can never inject markup.

    `fidelity`/`drift` (roadmap H258) scope the briefing to one holdings tier or
    drift posture, exactly as in `build_bundle` — both share `_gather_scope`, so
    the two forms cannot disagree about what the custody scope selects. `strength`
    (roadmap H318) is the rank-axis third scope, threaded identically.

    **Export-only — not a re-import unit.** The canonical lossless round-trip
    stays a property of the Markdown form (`build_bundle`/`import bundle`); the
    HTML embeds the *same* sentinel-fenced custody + custody-events JSONL (the
    shared `_items_block`/`_events_block`) in `<details>`/`<pre>` so the data is
    *present* for a reader, but `import bundle` consumes the Markdown bundle. The
    briefing says so, to make no false round-trip claim. Raises ValueError on a
    blank query, like `build_bundle`.
    """
    items, verdicts, events, strengths = _gather_scope(
        db_path, query, source, category, stage, tag, concept, fidelity, drift,
        strength,
    )

    scope = _scope_note(
        source, category, stage, tag, concept, fidelity, drift, strength
    )
    heading = f"Scrolls Custody Bundle: {query}"
    title = heading + (f" ({scope})" if scope else "")

    body = [f"<h1>{html.escape(title)}</h1>"]
    # the scope custody headline, from the shared `custody_headline` primitive
    # (sans the markdown `_` emphasis) — so the HTML headline content is identical
    # to the Markdown briefing's and to `status`/`context`/`doctor` (H45/H47)
    headline = custody_headline(items, verdicts).strip("_")
    body.append(f'<p class="custody-headline">{html.escape(headline)}</p>')
    # the bundle-level rank-confidence headline (roadmap H317), the HTML twin of
    # the Markdown `_Strength:_` line — the *same* `_strength_headline` fold (sans
    # the markdown `_` emphasis), so the two forms render byte-convergent strength
    # counts by construction (the H39/H271 two-form-parity precedent). Honest no-op
    # on an empty scope (nothing matched → no rank confidence to report).
    if items:
        strength_line = _strength_headline(items, strengths).strip("_")
        body.append(f'<p class="rank-strength">{html.escape(strength_line)}</p>')
    # the readable weakest-source pointer (roadmap H159), the HTML twin of the
    # Markdown `_Attention:_` line — distilled by the *same* `weakest_source` over
    # the same per-source map, so the two forms (and the JSON `attention` flag)
    # cannot desync; honest no-op when no source carries actionable loss
    body += _attention_html(items, verdicts)
    # the readable work-level at-risk pointer (roadmap H271), the HTML twin of the
    # Markdown `_At-risk work:_` line (H264) — distilled by the *same*
    # `at_risk_signal` over the same lean-scope clustered works, grouped with the
    # source `_attention_html` line and above `_refresh_html` (the Markdown order),
    # so the two forms (and `doctor`'s `custody.works`) name the same work; honest
    # no-op when no multi-representation work in scope is at risk
    body += _at_risk_html(items, verdicts)
    # the readable import-conflict pointer (roadmap H277), the HTML twin of the
    # Markdown `_Conflicts:_` line — distilled by the *same* `unresolved_conflicts`
    # over the same `latest_conflict_events` map, so the two forms (and `doctor`'s
    # `custody.conflicts`) report the same count; grouped with the divergence lines
    # above and below `_refresh_html` (the Markdown order); honest no-op when no held
    # item in scope carries an unresolved conflict
    body += _conflicts_html(db_path, items)
    # the readable archive-integrity pointer (roadmap H319), the HTML twin of the
    # Markdown `_Archive:_` line — folds the *same* `archive_integrity_block` over the
    # same in-scope `archived_records` and renders via the same
    # `archive_integrity_headline` (sans the markdown `_` emphasis), so the two forms
    # (and `doctor`'s `custody.archive`) report the same mismatch count; grouped with
    # the divergence lines above; honest no-op on a clean/empty scope
    body += _archive_integrity_html(db_path, items)
    # the readable per-source refresh pointer (roadmap H178), the HTML twin of the
    # Markdown `_Refresh:_` line — over the *same* `_refresh_debt_by_source` maps, so
    # the two forms name the same sources; honest no-op when no source carries
    # refresh debt on either axis
    body += _refresh_html(db_path, items)
    # the per-source custody breakdown (roadmap H141), from the *same* structured
    # `custody_source_breakdown` the Markdown form renders, so the two forms cannot
    # desync — a single-source/empty scope omits it (the [] no-op)
    body += _by_source_html(items, verdicts)
    body.append(
        '<p class="note">Read-only briefing. The canonical lossless re-import '
        "unit is the <strong>Markdown</strong> bundle (<code>scrolls export "
        "bundle … --format markdown</code>); the custody rows below are embedded "
        "for reference and re-imported via the Markdown form with <code>scrolls "
        "import bundle</code>.</p>"
    )
    # a concept-scoped bundle is *about* that concept, so its synthesized summary
    # and how it was derived belong in the briefing (H35), same as the Markdown
    if concept is not None:
        body += _concept_summary_html(db_path, concept)

    if not items:
        body.append("<p>No matching scrolls.</p>")
    else:
        body.append(
            f"<p>{len(items)} scroll(s), the whole scope — self-contained.</p>"
        )
        for rank, item in enumerate(items, start=1):
            body += _briefing_entry_html(
                rank, item, verdicts.get(item.id), strengths.get(item.id)
            )

    # the same sentinel-fenced custody blocks the Markdown form carries, embedded
    # (escaped) so the lossless data travels in the HTML too — but it is not a
    # re-import unit (the round-trip stays a Markdown property)
    body.append(_custody_details_html("Custody block", _items_block(items), len(items)))
    body.append(
        _custody_details_html("Custody events", _events_block(events), len(events))
    )
    # the optional third block (roadmap H280, `--with-archive`): the in-scope items'
    # prior-content archive, embedded for parity with the Markdown form so the
    # recovery store is *present* in the HTML too (export-only — re-import via the
    # Markdown bundle). Omitted without the flag, keeping the default HTML lean.
    if with_archive:
        archive = archived_records(db_path, [item.id for item in items]) if items else []
        body.append(
            _custody_details_html(
                "Prior-content archive", _archive_block(archive), len(archive)
            )
        )
    return _html_document(title, body)


def _html_document(title: str, body: list[str]) -> str:
    """Wrap the briefing body in a self-contained HTML5 document with inline CSS."""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>\n{_HTML_STYLE}</style>\n"
        "</head>\n<body>\n<main>\n"
        + "\n".join(body)
        + "\n</main>\n</body>\n</html>\n"
    )


def _attention_html(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> list[str]:
    """The HTML twin of the Markdown weakest-source `_Attention:_` line (roadmap H159).

    Distilled by the *same* `weakest_source` over the *same* `custody_counts_by_source`
    the Markdown `render_custody_attention` and the JSON `status`/`maintain` flag read,
    so the three surfaces name the same source, reason, and recheck command by
    construction. Returns [] on honest absence — exactly when `weakest_source` is
    `None` (empty, single-source, or fully-clean scope) — like the Markdown no-op. The
    source/command are controlled tokens (a source slug, a fixed command form);
    escaped for safety regardless.
    """
    flagged = weakest_source(custody_counts_by_source(items, verdicts))
    if flagged is None:
        return []
    return [
        '<p class="custody-attention">Attention: source '
        f"<code>{html.escape(flagged['source'])}</code> carries the most drift "
        f"({html.escape(flagged['reason'])}) — recheck with "
        f"<code>{html.escape(flagged['command'])}</code>.</p>"
    ]


def _at_risk_html(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> list[str]:
    """The HTML twin of the Markdown work-level `_At-risk work:_` line (roadmap H271/H264).

    The *consolidation*-level counterpart of the per-source `_attention_html` line:
    where that names the single source carrying the most actionable per-*item* loss,
    this names the single **work** no representation safely holds — no copy is both
    `full` *and* unmoved anywhere in its cluster (the H261 `safely_held == False`), a
    real custody loss (the only copies are degraded or moved). Distilled by the *same*
    `at_risk_signal` over the *same* lean-scope clustered works (`works_over` over the
    gathered item set) the Markdown `render_at_risk_works` folds, so the two readable
    forms name the same work, reason, and `at_risk` count — and converge with
    `doctor`'s `custody.works`/`maintain`'s `at_risk_works`/MCP `get_library_health`
    by construction. Returns [] on honest absence — exactly when `at_risk_signal`'s
    `most_at_risk` is `None` (no multi-representation work in scope is at risk: a
    clean, single-representation, or empty scope) — like the `_attention_html` no-op.
    The doi/reason are controlled tokens (a doi slug, a fixed reason form); escaped
    for safety regardless, like `_attention_html`.
    """
    signal = at_risk_signal(works_over(items), verdicts)
    entry = signal["most_at_risk"]
    if entry is None:
        return []
    return [
        '<p class="custody-at-risk">At-risk work: '
        f"<code>{html.escape(entry['doi'])}</code> — "
        f"{html.escape(entry['reason'])}; "
        f"{signal['at_risk']} work(s) at risk.</p>"
    ]


def _conflicts_html(db_path: Path, items: list[ScrollItem]) -> list[str]:
    """The HTML twin of the Markdown `_Conflicts:_` line (roadmap H277).

    Over the *same* `unresolved_conflicts` predicate against the same
    `latest_conflict_events` map the Markdown `render_custody_conflicts` and the JSON
    `doctor`'s `custody.conflicts` read, so the three surfaces report the same count
    of held items carrying an unresolved import conflict by construction. Returns []
    on honest absence — exactly when no held item in scope carries an unresolved
    conflict — like the Markdown no-op. The count is an integer, but the static text
    is escaped for safety regardless, like `_attention_html`. Names no command (the
    `reconcile` act is roadmap H276, the at-risk orphan-command discipline).
    """
    if not items:
        return []
    count = len(unresolved_conflicts(items, latest_conflict_events(db_path)))
    if count == 0:
        return []
    return [
        f'<p class="custody-conflicts">Conflicts: {count} '
        "item(s) carry an unresolved import conflict.</p>"
    ]


def _in_scope_archive_audit(db_path: Path, items: list[ScrollItem]) -> dict:
    """The archive-integrity audit over the bundle's in-scope items (roadmap H319).

    Folds the shared `archive_integrity_block` over the same in-scope
    `archived_records` the `--with-archive` block ships — the in-scope counterpart of
    `doctor`'s whole-library `custody.archive` audit. Both bundle forms read it, so
    the Markdown `_Archive:_` line and its HTML twin cannot desync. An empty scope is
    the honest empty audit (no records → 0 mismatched).
    """
    records = archived_records(db_path, [item.id for item in items]) if items else []
    return archive_integrity_block(records)


def _archive_integrity_lines(db_path: Path, items: list[ScrollItem]) -> list[str]:
    """The Markdown `_Archive:_` line for any corrupt in-scope prior (roadmap H319).

    Delegates to the shared `maintain.render_archive_integrity` — the *same* fold
    (`archive_integrity_block`) + render (`archive_integrity_headline`) the agent
    `context` briefing (H320) and the scheduled `maintain` summary use — so the two
    readable briefing surfaces and the JSON audit converge by construction. Returns
    [] on honest absence — a clean or empty scope — like the sibling divergence lines
    (the omit-when-clean briefing posture).
    """
    return render_archive_integrity(db_path, [item.id for item in items])


def _archive_integrity_html(db_path: Path, items: list[ScrollItem]) -> list[str]:
    """The HTML twin of the Markdown `_Archive:_` line (roadmap H319).

    The *same* `archive_integrity_headline` over the *same* in-scope audit, sans the
    markdown `_` emphasis, so the two readable forms (and `doctor`'s JSON) report the
    same mismatch count. Returns [] on honest absence — like the Markdown no-op. The
    line is controlled text but escaped for safety regardless, like `_conflicts_html`.
    """
    line = archive_integrity_headline(_in_scope_archive_audit(db_path, items))
    if not line:
        return []
    return [f'<p class="custody-archive">{html.escape(line.strip("_"))}</p>']


def _refresh_html(db_path: Path, items: list[ScrollItem]) -> list[str]:
    """The HTML twin of the Markdown weakest-source `_Refresh:_` line (roadmap H178).

    Over the *same* `_refresh_debt_by_source` maps the Markdown
    `render_custody_refresh` folds, so the two forms name the same source(s) and the
    same refresh commands by construction. Returns [] on honest absence — exactly
    when both maps are empty (no refresh debt on either axis) — like the Markdown
    no-op. Source names are escaped; the command/axis strings are controlled tokens,
    escaped for safety regardless.
    """
    enrichment_by_source, summary_by_source = _refresh_debt_by_source(db_path, items)
    clauses = []
    if enrichment_by_source:
        sources = ", ".join(
            f"<code>{html.escape(s)}</code>" for s in enrichment_by_source
        )
        clauses.append(
            f"classifications stale in {sources} — refresh with "
            "<code>scrolls classify --stale --source &lt;S&gt;</code>"
        )
    if summary_by_source:
        sources = ", ".join(
            f"<code>{html.escape(s)}</code>" for s in summary_by_source
        )
        clauses.append(
            f"summaries stale in {sources} — refresh with "
            "<code>scrolls kb --stale --source &lt;S&gt;</code>"
        )
    if not clauses:
        return []
    return [f'<p class="custody-refresh">Refresh: {"; ".join(clauses)}.</p>']


def _by_source_html(
    items: list[ScrollItem], verdicts: dict[str, CustodyEvent]
) -> list[str]:
    """The HTML twin of the Markdown per-source custody breakdown (roadmap H141).

    Renders the *same* structured `custody_source_breakdown` the Markdown
    `render_custody_by_source` does — one `<li>` per source, the same non-zero
    fidelity/drift sections — so the two forms cannot desync. Returns [] for fewer
    than two sources (the breakdown no-op), so a single-source/empty briefing omits
    the split, like the Markdown form. The source name is escaped; the section
    strings are controlled count tokens (no user content), escaped for safety.
    """
    breakdown = custody_source_breakdown(custody_counts_by_source(items, verdicts))
    if not breakdown:
        return []
    out = [
        '<p class="custody-headline">By source:</p>',
        '<ul class="custody-by-source">',
    ]
    for source, n, sections in breakdown:
        suffix = (" · " + " · ".join(sections)) if sections else ""
        out.append(
            f"<li><code>{html.escape(source)}</code> — "
            f"{n} scroll(s){html.escape(suffix)}</li>"
        )
    out.append("</ul>")
    return out


def _briefing_entry_html(
    rank: int,
    item: ScrollItem,
    verdict: CustodyEvent | None,
    strength: str | None = None,
) -> list[str]:
    """The HTML twin of `_briefing_entry`: identity, custody facts, excerpt."""
    out = [
        '<section class="scroll">',
        f"<h2>{rank}. {html.escape(item.title or item.id)} "
        f"(<code>{html.escape(item.id)}</code>)</h2>",
        '<ul class="custody-facts">',
        f"<li>{html.escape(item.source)} · fidelity "
        f"<code>{html.escape(get_fidelity(item))}</code> · stage "
        f"<code>{html.escape(item.stage)}</code></li>",
        f"<li>captured {html.escape(item.saved_at)}</li>",
    ]
    url = item.canonical_url or item.url
    out.append(
        f'<li><a href="{html.escape(url, quote=True)}">{html.escape(url)}</a></li>'
    )
    if item.content_hash:
        out.append(f"<li>content-hash <code>{html.escape(item.content_hash)}</code></li>")
    out.append(f"<li>{_drift_html(verdict, strength)}</li>")
    classification = _classification_html(item)
    if classification:
        out.append(f"<li>{classification}</li>")
    out.append("</ul>")
    excerpt = _excerpt(item)
    if excerpt:
        out.append(f'<blockquote class="excerpt">{html.escape(excerpt)}</blockquote>')
    out.append("</section>")
    return out


def _drift_html(verdict: CustodyEvent | None, strength: str | None = None) -> str:
    """The per-scroll drift posture as HTML — the twin of `_drift_line` (H42).

    Reads the same `custody.drift_posture` + `_POSTURE_GLOSS` the Markdown line
    does, so the HTML posture word and `doctor`'s `custody.drift` cannot disagree;
    ``unverified`` is stated explicitly, never silently "clean". `strength`
    (roadmap H317) appends the same ``· rank <code><strength></code>`` per-match
    rank marker the Markdown `_drift_line` does, escaped, so the two forms name the
    same band; `None` omits it.
    """
    posture = drift_posture(verdict)
    if verdict is None:
        body = "custody <code>unverified</code> — never re-checked against its source"
    else:
        body = (
            f"custody <code>{html.escape(posture)}</code> "
            f"({html.escape(_POSTURE_GLOSS[posture])}) "
            f"as of {html.escape(verdict.checked_at)}"
        )
    if strength is not None:
        body += f" · rank <code>{html.escape(strength)}</code>"
    return body


def _classification_html(item: ScrollItem) -> str | None:
    """How the category was derived, as HTML — the twin of `_classification_line`.

    Renders the *same* shared `classification_phrase` the Markdown briefing and
    every structured surface use (H35/H44), with its backtick `code` spans turned
    into `<code>` (`_inline_code`), so the method/confidence reads identically.
    Returns None for an unclassified or user-set category — the same honest
    absence (no method claimed for a category no engine produced).
    """
    view = classification_provenance(item)
    if view is None:
        return None
    return (
        f"classified <code>{html.escape(item.category)}</code> "
        f"{_inline_code(classification_phrase(view))}"
    )


def _inline_code(text: str) -> str:
    """Escape HTML and render markdown `code` spans as `<code>`.

    Used only on the controlled `classification_phrase` — its backtick spans are
    engine/basis/confidence tokens, never user content — so the HTML reads the
    same method/confidence as every other surface without a markdown renderer.
    """
    return "".join(
        f"<code>{html.escape(part)}</code>" if i % 2 else html.escape(part)
        for i, part in enumerate(text.split("`"))
    )


def _custody_details_html(label: str, fenced_block: str, count: int) -> str:
    """A collapsible `<details>` holding one sentinel-fenced custody block (escaped).

    The lossless JSONL is *present* in the HTML (so a reader can extract it), but
    the block is the Markdown form's content embedded verbatim and escaped — not a
    re-import surface; `import bundle` consumes the Markdown bundle (H39).
    """
    return (
        f'<details class="custody-data"><summary>{html.escape(label)} — '
        f"{count} row(s)</summary>\n<pre>{html.escape(fenced_block)}</pre>\n</details>"
    )


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


def parse_bundle_archive(text: str) -> list[ArchiveRecord]:
    """Reconstruct the prior-content archive from a bundle's *third* region (H280).

    The recovery-store counterpart of `parse_bundle_events`: reads the **third**
    `@generated` region (items=0, events=1, archive=2), strips the ` ```jsonl `
    code fence, and parses each row through `archive_from_dict`. Returns ``[]``
    when the bundle carries fewer than three regions — a bundle exported *without*
    `--with-archive` (the lean default, only items + events), so its archive simply
    does not travel — the same forward/backward-compatible shape `parse_bundle_events`
    gives a pre-H67 bundle. Raises BundleError on a malformed row, naming the record,
    so a corrupt recovery store fails loudly rather than silently dropping a prior —
    losing a superseded capture would lose the only copy of a replaced artifact.
    """
    bodies = generated_bodies(text)
    if len(bodies) < 3:  # items + events only — no archive block travelled
        return []
    records: list[ArchiveRecord] = []
    record_no = 0
    for raw in bodies[2].splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):  # blank or the code-fence lines
            continue
        record_no += 1
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BundleError(
                f"archive block record {record_no}: not valid JSON ({exc.msg})"
            ) from exc
        if not isinstance(data, dict):
            raise BundleError(
                f"archive block record {record_no}: expected a JSON object, "
                f"got {type(data).__name__}"
            )
        missing = [name for name in _ARCHIVE_REQUIRED if not data.get(name)]
        if missing:
            raise BundleError(
                f"archive block record {record_no}: missing required field(s): "
                + ", ".join(missing)
            )
        records.append(archive_from_dict(data))
    return records


def _briefing_entry(
    rank: int,
    item: ScrollItem,
    verdict: CustodyEvent | None,
    strength: str | None = None,
) -> list[str]:
    """The readable per-scroll briefing block: identity, custody facts, excerpt."""
    out = [f"## {rank}. {item.title or item.id} (`{item.id}`)", ""]
    facts = f"- {item.source} · fidelity `{get_fidelity(item)}` · stage `{item.stage}`"
    out.append(facts)
    out.append(f"- captured {item.saved_at}")
    out.append(f"- {item.canonical_url or item.url}")
    if item.content_hash:
        out.append(f"- content-hash `{item.content_hash}`")
    out.append(_drift_line(verdict, strength))
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


def _drift_line(verdict: CustodyEvent | None, strength: str | None = None) -> str:
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

    `strength` (roadmap H317) appends the per-match rank marker — ``· rank
    `<strength>` `` — naming *why* this scroll ranked (title hit `strong`, summary
    `moderate`, body-only `weak`, the H312 `match_strength`), the per-scroll
    counterpart of the bundle-level `_Strength:_` headline, in the `· ` marker
    idiom the browse list-row carries its custody markers (H89). Labeled `rank`
    (unlike `context`'s bare `· <strength>` on its match list) because the bundle's
    per-scroll facts are all labeled, so a bare band word beside a timestamp would
    be ambiguous. `None` (a caller with no rank context) omits it.
    """
    posture = drift_posture(verdict)
    if verdict is None:
        line = "- custody `unverified` — never re-checked against its source"
    else:
        line = (
            f"- custody `{posture}` ({_POSTURE_GLOSS[posture]}) "
            f"as of {verdict.checked_at}"
        )
    if strength is not None:
        line += f" · rank `{strength}`"
    return line


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
    result = _concept_summary_view(db_path, concept)
    if result is None:
        return []
    stored, view = result
    return [
        f"**Concept summary** — {stored.summary}",
        "",
        f"_Summary by `{view['by']}`, {view['freshness']} "
        f"(members fingerprint `{view['members_hash'][:12]}`)._",
        "",
    ]


def _concept_summary_html(db_path: Path, concept: str) -> list[str]:
    """The HTML twin of `_concept_summary_block` — the concept's summary + provenance."""
    result = _concept_summary_view(db_path, concept)
    if result is None:
        return []
    stored, view = result
    return [
        '<section class="concept-summary">',
        f"<p><strong>Concept summary</strong> — {html.escape(stored.summary)}</p>",
        f'<p class="note">Summary by <code>{html.escape(view["by"])}</code>, '
        f"{html.escape(view['freshness'])} (members fingerprint "
        f"<code>{html.escape(view['members_hash'][:12])}</code>).</p>",
        "</section>",
    ]


def _concept_summary_view(
    db_path: Path, concept: str
) -> tuple[ConceptSummary, dict] | None:
    """The bundled concept's stored summary + its `summary_provenance` view, or None.

    Shared by the Markdown (`_concept_summary_block`) and HTML
    (`_concept_summary_html`) renderers so both report the same synthesis and
    freshness. Freshness is computed against the concept's *whole* live membership
    (not the bundle's query-filtered subset), because a summary is a synthesis of
    the entire concept. Returns None for an unknown concept, no stored summary, or
    an empty slug — the honest absence both renderers turn into [].
    """
    slug = slugify(concept)
    if not slug:
        return None
    stored: ConceptSummary | None = load_concept_summaries(db_path).get(slug)
    if stored is None:
        return None
    rendered = [item for item in list_items(db_path) if item.markdown_path]
    entry = group_concepts(rendered).get(slug)
    live = members_hash(entry["items"]) if entry else ""
    view = summary_provenance(stored, live)
    if view is None:  # unreachable while `stored` is set, but keeps the contract local
        return None
    return stored, view


def _scope_note(
    source: str | None,
    category: str | None,
    stage: str | None,
    tag: str | None,
    concept: str | None,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
) -> str:
    """A `source=…, category=…` summary of the active facets, else '' (as `context`).

    `fidelity`/`drift` (roadmap H258, the per-item custody scopes) report their
    value verbatim, so a custody-scoped bundle's title names which holdings tier /
    drift posture it covers — the provenance of *what slice* was shared, beside
    the existing query/facet echo. `strength` (roadmap H318, the rank-axis scope)
    reports likewise, so a rank-scoped bundle names which strength band it covers.
    """
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
    if fidelity is not None:
        parts.append(f"fidelity={fidelity}")
    if drift is not None:
        parts.append(f"drift={drift}")
    if strength is not None:
        parts.append(f"strength={strength}")
    return ", ".join(parts)


def _excerpt(item: ScrollItem) -> str:
    text = " ".join((item.summary or item.extracted_text or "").split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    return text[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
