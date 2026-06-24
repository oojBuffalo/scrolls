"""Agent context bundles (IDEAS.md §11, §14 Pass 5).

`scrolls context <query>` answers "what does my library know about X?"
with one compact Markdown document: ranked matches, capped excerpts, and
source links. Agents don't want 100 files — they want a high-signal
bundle they can drop straight into context, so unlike the data commands
this one emits Markdown, not JSON (the bundle *is* the artifact). Each
excerpt carries the item id, source, and scroll path so an agent can
follow up with `scrolls show <id>` or read the full scroll.

Ranking comes from the existing FTS5/BM25 search; excerpts prefer the
stored summary and fall back to the leading extracted text. A
"Synthesized Brief" needs an LLM and is omitted honestly, like LLM
classification (ADR 0004) and LLM concept pages (ADR 0005).

At the `full` budget each excerpt also carries two compact per-source trust
tags beneath its meta line (roadmap H44 + H62 + H90): *how the category was
derived* (the `classification_provenance` view, omitted on honest absence) and
*whether the source has moved, and as of when* (the `custody.drift_posture`
followed by `· last seen <checked_at>` / `· never re-checked`, `unverified`
stated explicitly). They derive from the same views every browse/inspect
surface reads, so an excerpt an agent drops into its window reports the same
provenance `show`/`list`/`search` would — the per-source counterpart of the
scope-level `_Custody:_` headline.

Beyond keyword matches the bundle carries a "Connected scrolls" section:
items linked to or from the matches through the cross-item link graph the
adapters build (a saved model's paper, a preprint's published DOI, a
package's repo — ADR 0044). These are high-precision connections FTS can't
find — the paper a match points at need not share its keywords — so the
graph the adapters spent so many adapters building finally surfaces in the
bundle an agent actually reads, not only in `scrolls related`/`graph`.

Duplicate representations of one scholarly work are collapsed (ADR 0101):
when a query matches both an arXiv preprint and its published Crossref
record — the same work, near-identical content — the bundle keeps the
best-ranked representation, names the folded sibling(s) and the work's
canonical form, and excerpts the work once. A high-signal bundle should not
spend two of its few slots on one work; the `works` membership search hits
now carry makes the collapse a lookup, not a re-derivation.

Each match also explains *why it ranked* (roadmap H315, custody-vision §3.5):
a compact `· <strength>` marker on its Best-Matches line names the strongest
indexed field its query landed in — `strong` (title), `moderate` (summary),
`weak` (body-only), the legible companion to the opaque BM25 order each hit
already carries (`match_strength`, H312). A bundle-level `_Strength:_` headline
beside the Coverage line folds those markers into one rank-confidence summary
(the H313 `tally_strength` histogram on the bundle). Both are ledger-free FTS
facts, so they travel at every budget tier — even the leanest `index` catalog,
where an agent most needs to tell a strong match from a weak one before
spending budget on bodies.

The same rank axis also *scopes* the bundle (roadmap H316): `--strength
{strong|moderate|weak}` keeps only the matches whose query lands at or above a
band (`strong` title hits, `moderate` title-or-summary, `weak` everything),
threaded through `search_items`/`count_matches` beside `--fidelity`/`--drift`
(the same before-cap sieve), so an agent can build context from "only the
excerpts whose query is in the title" and the kept slice re-folds the
`_Strength:_` headline and per-match markers above.
"""

from __future__ import annotations

from pathlib import Path

from scrolls.classify import stale_classification_counts_by_source
from scrolls.custody import (
    CustodyEvent,
    custody_counts,
    custody_counts_by_source,
    custody_headline,
    drift_posture,
    last_checked,
    latest_conflict_events,
    latest_events,
    render_custody_attention,
    render_custody_by_source,
    render_custody_conflicts,
    render_custody_refresh,
    render_fidelity_holdings,
)
from scrolls.graph import build_graph
from scrolls.items import (
    ScrollItem,
    classification_phrase,
    classification_provenance,
    get_item,
)
from scrolls.kb import load_concept_summaries
from scrolls.kb_llm import stale_summary_counts_by_source
from scrolls.search import (
    SearchHit,
    count_matches,
    render_strength_headline,
    search_items,
    tally_strength,
)
from scrolls.works import render_at_risk_works

_EXCERPT_CHARS = 700
DEFAULT_LIMIT = 8

# Progressive context budget tiers (MVP M3, obsidian L0–L3 adaptation). A
# bundle is a *budgeted boot sequence*: identity/index first, deep bodies on
# demand. The tiers are strictly nested — each is a superset of the one before
# — so `--budget` bounds depth predictably:
#   index     — the catalog: Best Matches + Links (ids, titles, source URLs).
#               No bodies, and no link-graph build at all (the cheapest boot).
#   connected — index + the Connected scrolls link graph. Still no bodies.
#   full      — connected + Excerpts (the deep bodies). The default, the
#               current flat bundle, unchanged.
# A tier below `full` discloses the reduced depth in a `_Budget:_` note so an
# agent never reads a catalog-only bundle as "this is all there is to read" —
# the same anti-fabrication / honest-scope discipline the Coverage line applies
# to the match *set* (completeness contract G2), here applied to depth *per
# match*. The two are orthogonal and both always hold.
BUDGET_TIERS = ("index", "connected", "full")
DEFAULT_BUDGET = "full"


def _tier_at_least(budget: str, required: str) -> bool:
    """Whether `budget` includes everything tier `required` includes (nested)."""
    return BUDGET_TIERS.index(budget) >= BUDGET_TIERS.index(required)


def build_context(
    db_path: Path,
    query: str,
    limit: int = DEFAULT_LIMIT,
    source: str | None = None,
    category: str | None = None,
    stage: str | None = None,
    tag: str | None = None,
    concept: str | None = None,
    fidelity: str | None = None,
    drift: str | None = None,
    strength: str | None = None,
    budget: str = DEFAULT_BUDGET,
) -> str:
    """Render the Markdown bundle for a query; raises ValueError on a blank one.

    The optional `source`/`category`/`stage` facets (ADR 0058) and the
    `tag`/`concept` membership facets (ADR 0059) scope the bundle the same
    way they scope `scrolls search` — they narrow the underlying ranked
    match (and so the connected-scrolls graph that hangs off it), letting an
    agent ask "what do the *papers* tagged efficient say about X" rather than
    "anything about X". When any facet is set the title carries a scope note
    so the bundle is self-documenting; the empty-string `category` selects
    the unclassified pool and reads as `category=unclassified`.

    `fidelity` and `drift` (roadmap H257) are the two per-item *custody* scopes
    — the custody-filter family on the agent context bundle, the one progressive
    read surface it had not reached. `fidelity` (the holdings axis, ADR 0097)
    keeps only the matches the library holds at one custody tier
    (`full`/`partial`/`reference`), so an agent on a tight budget can build its
    working context from "only the full-fidelity sources I can re-derive
    offline". `drift` (the ledger-claim axis, H58) keeps only the matches at one
    verify-ledger posture (`verified`/…/`drifted`), so it can "exclude the ones
    that have moved". Both fold the *same* primitives the `list`/`search`
    custody filters use (`scrolls_fidelity`/`scrolls_drift` UDFs), passed
    straight to `search_items`/`count_matches`, so they AND with the facets and
    — crucially — scope the candidate set **before** the `limit` cap (the
    `list`-sieve shape, like `search`/`related`): the bundle keeps the top-k *at
    that custody value*, not the top-k then sieved. Everything downstream — the
    work-collapse, the budget tiers' depth, the `_Custody:_`/`_Fidelity:_`
    headline, and the per-excerpt drift tags — therefore reads the kept set, so
    the rendered headline describes exactly what the bundle contains. An unknown
    tier/posture raises ValueError (`search_items`, a closed vocabulary; the CLI
    also rejects it via argparse `choices`).

    `strength` (roadmap H316) is the *rank-axis* third custody-style scope — the
    same before-cap threshold band `scrolls search --strength` adds (H314), here
    lifted to the context bundle. It keeps only the matches whose query lands at
    or above one rank-strength band: `strong` keeps title hits, `moderate`
    title-or-summary hits, `weak` every match (the threshold semantics, not an
    exact-band equality — a hit reads `match_strength == band` exactly when its
    query lands in that band's column or a stronger one). So an agent can build
    its working context from "only the excerpts whose query is in the title". It
    threads straight into `search_items`/`count_matches` beside `fidelity`/`drift`
    (the same before-cap sieve), so it ANDs with them and the facets, scopes the
    candidate set *before* the `limit` cap, and the kept set re-folds the
    `_Strength:_` headline and per-match markers (H315) — so a `--strength strong`
    bundle's headline is a `strong`-only summary describing exactly what it
    contains. An unknown band raises ValueError (closed vocabulary; the CLI also
    rejects it via argparse `choices`).

    `budget` (MVP M3) bounds the bundle's *depth* through the nested
    `index`/`connected`/`full` tiers (`BUDGET_TIERS`): `index` is the catalog
    alone (matches + links), `connected` adds the link graph, `full` (default)
    adds the deep-body excerpts. A tier below `full` carries a `_Budget:_` note
    disclosing what it omitted, so a budgeted bundle stays honest about depth
    the way the Coverage line stays honest about scope. An unknown tier raises
    ValueError (the CLI also rejects it via argparse `choices`).

    From `connected` up the bundle also carries a one-line `_Custody:_` headline
    (roadmap H47) — fidelity-tier and drift-posture counts over the in-bundle
    scrolls, the same `custody_headline` the shareable bundle and `scrolls
    status` render — so an agent sees how much of what it is about to read is
    full-fidelity and how much has drifted. A *multi-source* bundle follows it
    with a `_By source:_` breakdown (roadmap H149) naming which source in the
    bundle is weakest, through the same `render_custody_by_source` the `export
    bundle` briefing (H141) and the compiled `library/index.md` (H145) use, so
    the line reads byte-identical across surfaces and sums to the headline. Both
    are gated off `index` so the leanest tier stays a bare catalog.

    No matches (or no library yet) still yields a valid bundle saying so,
    because agents shouldn't crash on an empty library.
    """
    if budget not in BUDGET_TIERS:
        raise ValueError(
            f"unknown budget {budget!r}; choose one of {', '.join(BUDGET_TIERS)}"
        )
    hits = search_items(
        db_path,
        query,
        limit=limit,
        source=source,
        category=category,
        stage=stage,
        tag=tag,
        concept=concept,
        fidelity=fidelity,
        drift=drift,
        strength=strength,
    )
    kept, folded = _collapse_by_work(hits)
    # Fetch every matched row once (kept + folded). `items` (the bundle's kept,
    # collapsed scrolls) drive the headline/excerpts; `scope_items` (the whole
    # uncollapsed matched set) drive the work-level at-risk signal — a work's
    # representations are folded into one canonical in `items`, so clustering the
    # collapsed set would never see a multi-representation work, and a work's
    # at-risk verdict depends on *all* its representations (a folded full+verified
    # sibling makes the work safely held even when the kept canonical is a bare
    # reference). The lean-scope decision (H264): the at-risk line describes the
    # works the bundle's *matched set* touches, the same raw-match scope Coverage
    # counts.
    fetched = {hit.id: get_item(db_path, hit.id) for hit in hits}
    pairs = [(hit, fetched[hit.id]) for hit in kept if fetched[hit.id]]
    items = [item for _, item in pairs]
    scope_items = [item for hit in hits if (item := fetched[hit.id])]

    title = f"# Scrolls Context Bundle: {query}"
    scope = _scope_note(
        source, category, stage, tag, concept, fidelity, drift, strength
    )
    if scope:
        title += f" ({scope})"
    lines = [title, ""]
    if not items:
        lines.append("No matching scrolls.")
        return "\n".join(lines) + "\n"

    # How much of the library this bundle saw: every match under the cap, or
    # the top-ranked slice of more (completeness contract G2). `count_matches`
    # is the same past-the-cap denominator `scrolls search --stats` uses, under
    # the same facets, so the bundle's coverage claim and a `--stats` search
    # over the same scope agree. The query is already validated by the
    # search_items call above, so this never raises on a blank query.
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
    lines += [_coverage_line(matched, len(hits)), ""]
    # The bundle-level rank-confidence headline (roadmap H315): one `_Strength:_`
    # line summarising how strongly the kept matches ranked — strong (title hits),
    # moderate (summary), weak (body-only) — beside the Coverage line, the readable
    # bundle-level fold of the per-match `· <strength>` markers below (the H313
    # `tally_strength` histogram, the explainable-ranking surface lifted to the
    # context bundle, custody-vision §3.5). Folded over the kept `pairs` (the bundle's
    # ranked representations, the same set the Best-Matches markers and `_Custody:_`
    # headline describe), *not* the raw `matched` denominator: the bundle collapses
    # same-work duplicates (ADR 0101), so a folded sibling's strength would double-count
    # the one work — the kept-set tally counts each work once, converging with the
    # markers it summarises by construction. Ledger-free (a pure FTS-rank fact like
    # fidelity), so it renders at every budget tier, including the leanest `index`.
    lines += [
        render_strength_headline(tally_strength(hit.match_strength for hit, _ in pairs)),
        "",
    ]
    budget_note = _budget_line(budget)
    if budget_note:
        lines += [budget_note, ""]

    # One `latest_events` ledger read for the whole scope, shared by the scope
    # custody headline (`connected`+) and the per-excerpt drift tags (`full`).
    # Skipped at `index`, where neither renders (the leanest tier touches no
    # ledger). `{}` there keeps `drift_posture(None)` → `unverified` honest.
    verdicts: dict[str, CustodyEvent] = (
        latest_events(db_path) if _tier_at_least(budget, "connected") else {}
    )

    # The scope custody headline (roadmap H47): how much of what the agent is
    # about to read is full-fidelity, and how much has drifted — the same
    # `custody_headline` the shareable bundle briefing (H45) and `scrolls status`
    # (H38) render, over the in-bundle scrolls (the kept representations the
    # Coverage line counts). Gated to `connected`/`full` like the depth-bearing
    # sections (H44): the leanest `index` tier stays a bare catalog.
    if _tier_at_least(budget, "connected"):
        lines += [custody_headline(items, verdicts), ""]
        by_source = custody_counts_by_source(items, verdicts)
        # the readable weakest-source pointer (roadmap H159): one `_Attention:_`
        # line naming the single source with the most actionable loss and the
        # exact recheck command, so an agent reads "this one source needs
        # attention" before scanning the per-source map below. Distilled by the
        # shared `weakest_source` over the same `by_source` the breakdown folds, so
        # it converges field-for-field with `status`/`maintain`'s JSON `attention`;
        # honest no-op when no source carries actionable loss (single-source /
        # clean / empty scope — [] lines).
        lines += render_custody_attention(by_source)
        # the readable work-level at-risk pointer (roadmap H264): one `_At-risk
        # work:_` line naming the single work no representation safely holds (the
        # H263 alarm's `most_at_risk`) — the *consolidation*-level counterpart of
        # the per-source `_Attention:_` line above. Distilled by the shared
        # `at_risk_signal` over the bundle scope's own clustered works (the
        # lean-scope decision: the *gathered* item set, the same scope the headline
        # and `_By source:_` map describe), so it names the same work as `doctor`'s
        # `custody.works`/MCP `get_library_health` by construction. Gated to
        # `connected`+ with the headline (the `index` tier reads no ledger, so it
        # makes no drift-bearing claim); honest no-op when no multi-representation
        # work in scope is at risk ([] lines). Computed over the *uncollapsed*
        # `scope_items` (not the collapsed `items`): a work's representations are
        # folded into one canonical in `items`, so its full custody picture — and
        # whether any representation is safely held — lives in the whole matched set.
        lines += render_at_risk_works(scope_items, verdicts)
        # the readable import-conflict pointer (roadmap H277): one `_Conflicts:_`
        # line naming how many held items in scope carry an *unresolved import
        # conflict* (a peer's capture disagreed with the held copy at merge time,
        # ADR 0104, still open) — the readable completion of H275's JSON
        # `custody.conflicts` aggregate, beside the drift `_Attention:_` and
        # consolidation `_At-risk work:_` divergence lines above. Folds the *same*
        # `unresolved_conflicts` over the same `latest_conflict_events` map `doctor`'s
        # `custody.conflicts` reads, so the count converges with the JSON block for
        # the same scope by construction. Gated to `connected`+ with the headline
        # (the `index` tier reads no ledger, so it makes no conflict claim); folded
        # over the per-*item* `items` (the collapsed kept set the headline/`_Attention:_`
        # use — a conflict is a per-item custody fact, not a work-consolidation one);
        # names no command (the `reconcile` act is H276, the at-risk orphan-command
        # discipline); honest no-op when no held item in scope carries an unresolved
        # conflict ([] lines).
        lines += render_custody_conflicts(items, latest_conflict_events(db_path))
        # the readable per-source refresh pointer (roadmap H178): one `_Refresh:_`
        # line naming the source(s) whose classifications/summaries are stale and
        # the exact `classify --stale`/`kb --stale --source <S>` refresh — the
        # enrichment/summary-axis counterpart of the drift `_Attention:_` line above.
        # Computed over the bundle's own scope items by the same
        # `stale_*_counts_by_source` builders `doctor`'s `custody.enrichment
        # .by_source`/`summaries.by_source` fold, so the named sources converge with
        # the audit maps by construction. Gated to `connected`+ like the headline;
        # honest no-op when no source carries refresh debt ([] lines).
        enrichment_by_source = stale_classification_counts_by_source(items)
        summary_by_source = stale_summary_counts_by_source(
            items, load_concept_summaries(db_path)
        )
        lines += render_custody_refresh(enrichment_by_source, summary_by_source)
        # the per-source custody breakdown under the scope headline (roadmap
        # H149): a multi-source bundle names *which* source's custody is weakest
        # within the scope, so an agent gauges the weak source without
        # re-deriving it. Folds the same `custody_counts_by_source` the scope
        # headline already covers (one ledger read), so it sums to the headline
        # by construction and equals `doctor`'s `custody.by_source` for the same
        # scope. The renderer's `<2`-source no-op omits the split for a
        # single-source bundle ([] lines), where the headline says everything.
        lines += render_custody_by_source(by_source)
    else:
        # The leanest `index` tier reads no ledger, so it carries no *drift* claim
        # (a `verified`/`unverified` verdict over an unread ledger would be the M2
        # anti-fabrication violation the headline gate above avoids). But fidelity
        # is a ledger-free *holdings* fact (`get_fidelity` over stored fields), so it
        # still travels even here — *fidelity travels with every result* (vision
        # principle 3, roadmap H212): one `_Fidelity:_` line names how much of the
        # matched set the agent holds in full before it spends budget on a deeper
        # tier. The counts fold the same `custody_counts` the `connected`+ headline
        # does (with `{}` verdicts — no ledger read), so the tier counts converge
        # with the headline's `fidelity` section by construction (H213).
        tiers = custody_counts(items, {})["tiers"]
        lines += [render_fidelity_holdings(tiers, len(items)), ""]

    lines += ["## Best Matches", ""]
    for rank, (hit, item) in enumerate(pairs, start=1):
        line = f"{rank}. {item.title or item.id} (`{item.id}`)"
        if item.category:
            line += f" — {item.category}"
        # the per-match rank explanation (roadmap H315): a compact `· <strength>`
        # marker naming *why* this match ranked — title hit (`strong`), summary
        # (`moderate`), or body-only (`weak`) — the legible companion to the opaque
        # BM25 order, in the same `· ` marker idiom the browse list-row carries its
        # `· <fidelity> · <drift>` custody markers (H89). It rides each hit's own
        # `match_strength` (H312, already on every `search_items` hit), so the per-line
        # marker and the `_Strength:_` headline above fold the same value. On the
        # ranked list (shown at every budget tier), so the explanation travels even on
        # a lean `index`/`connected` boot, where an agent most needs to tell a strong
        # match from a weak one before spending budget on bodies.
        line += f" · {hit.match_strength}"
        note = _work_note(hit, folded.get(hit.id, []))
        if note:
            line += f" · {note}"
        lines.append(line)

    # Deep bodies only at the `full` budget — the index/connected tiers boot an
    # agent on the catalog (and, for `connected`, the graph) and let it pull
    # bodies on demand with `scrolls show <id>` or a `--budget full` re-run.
    if _tier_at_least(budget, "full"):
        lines += ["", "## Excerpts"]
        for item in items:
            lines += ["", f"### {item.title or item.id}", "", _meta_line(item)]
            lines += _provenance_tags(item, verdicts.get(item.id))
            excerpt = _excerpt(item)
            if excerpt:
                lines += ["", excerpt]

    # The link graph from the `connected` tier up; `index` skips the graph build
    # entirely. Folded representations are the same work as a kept match, so
    # they must not resurface as "connected" neighbours (the preprint links to
    # the published DOI record it just absorbed) — exclude them too.
    if _tier_at_least(budget, "connected"):
        folded_ids = {item_id for ids in folded.values() for item_id in ids}
        connected = _connected_lines(db_path, [item.id for item in items], folded_ids)
        if connected:
            lines += ["", "## Connected scrolls", ""] + connected

    lines += ["", "## Links", ""]
    lines += [
        f"- [{item.title or item.id}]({item.canonical_url or item.url})"
        for item in items
    ]
    return "\n".join(lines) + "\n"


def _collapse_by_work(
    hits: list[SearchHit],
) -> tuple[list[SearchHit], dict[str, list[str]]]:
    """Fold same-work duplicate hits into their best-ranked representation.

    Walks the ranked hits keeping the first representation seen of each work
    (ADR 0101): a later hit whose every work already has a kept representative
    is folded under the earliest keeper it shares a work with — the published
    record folded under the preprint that out-ranked it, or vice versa. A hit
    that brings a *new* work (even while sharing an already-seen one) is kept,
    so a multi-work item is never dropped. Returns the kept hits in rank order
    and `{kept hit id: [folded hit id, …]}`. Hits with no work membership never
    fold — they are not duplicates of anything.
    """
    seen_dois: set[str] = set()
    owner: dict[str, str] = {}  # work DOI → the kept hit that represents it
    kept: list[SearchHit] = []
    folded: dict[str, list[str]] = {}
    for hit in hits:
        hit_dois = {ref.doi for ref in hit.works}
        if hit_dois and hit_dois <= seen_dois:
            keeper = next(owner[doi] for doi in hit_dois if doi in owner)
            folded.setdefault(keeper, []).append(hit.id)
            continue
        kept.append(hit)
        for doi in hit_dois - seen_dois:
            owner[doi] = hit.id
        seen_dois |= hit_dois
    return kept, folded


def _coverage_line(matched: int, returned: int) -> str:
    """The bundle's scope-honest coverage note (completeness contract G2).

    States whether the bundle was built from every matching scroll or only the
    top-ranked slice of more, so a reader holding *only* the bundle can tell
    "this is everything my library knows about X" from "the top N — there is
    more" and never reads a capped bundle as library-wide absence. `matched`
    is the past-the-cap match total (`search.count_matches`); `returned` is
    how many the cap let the bundle see (`<= matched`); the bundle is truncated
    exactly when `matched > returned`, the same arithmetic the `--stats`
    envelope pins (`src/scrolls/scope.py`). The count is of matching *scrolls*
    (raw matches): a same-work duplicate folded into its best-ranked sibling
    (ADR 0101) is still covered — it is named in that sibling's note — so a
    collapsed bundle is complete, not truncated.
    """
    if matched > returned:
        return (
            f"_Coverage: the top {returned} of {matched} matching scrolls — "
            "raise `--limit` or narrow the query to see the rest._"
        )
    return f"_Coverage: all {matched} matching scrolls._"


def _budget_line(budget: str) -> str:
    """The bundle's depth-honesty note for a tier below `full` (MVP M3), else ''.

    Discloses what the budget held back and names the lever to get it, so a
    catalog-only bundle is never mistaken for "all there is to read" — the
    depth-axis counterpart to the Coverage line's scope honesty. `full` omits
    nothing, so it carries no note and the default bundle is unchanged.
    """
    if budget == "index":
        return (
            "_Budget: index — the catalog only (best matches and source "
            "links). Re-run with `--budget connected` for the link graph or "
            "`--budget full` for excerpts; `scrolls show <id>` reads a body._"
        )
    if budget == "connected":
        return (
            "_Budget: connected — best matches, the link graph, and source "
            "links, no excerpts. Re-run with `--budget full` for excerpts; "
            "`scrolls show <id>` reads a body._"
        )
    return ""


def _work_note(hit: SearchHit, folded_ids: list[str]) -> str:
    """The Best-Matches annotation for a hit that absorbed same-work siblings.

    Empty unless siblings were folded into this hit, so the note appears only
    where the bundle actually collapsed a duplicate. Names the folded
    representation(s) and the work's canonical form (ADR 0095) — which may be a
    folded sibling, this very hit, or a representation that did not match at all
    — so an agent sees the preferred form even though the bundle kept the
    best-ranked one.
    """
    if not folded_ids:
        return ""
    note = "same work as " + ", ".join(f"`{item_id}`" for item_id in folded_ids)
    canonical = hit.works[0].canonical if hit.works else None
    if canonical == hit.id:
        note += " (this is the canonical form)"
    elif canonical:
        note += f"; canonical `{canonical}`"
    return note


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
    """A `source=…, category=…, …` summary of the active facets, else ''.

    The empty-string `category` (the unclassified pool, mirroring `scrolls
    search`/`list`) reads as `category=unclassified` so the title is honest
    about what an empty value selects. `tag`/`concept` (ADR 0059) carry no
    such overload — they report their value verbatim. `fidelity`/`drift`
    (roadmap H257, the per-item custody scopes) report their value verbatim
    too, so a custody-scoped bundle's title names which holdings tier / drift
    posture it covers. `strength` (roadmap H316, the rank-axis scope) reads
    verbatim as well, so a rank-scoped bundle names which strength band it
    covers.
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


def _connected_lines(
    db_path: Path, ranked_ids: list[str], exclude: set[str] = frozenset()
) -> list[str]:
    """Bullet lines for scrolls linked to/from the matches but not matched.

    Resolves the whole-library link graph (`graph.build_graph`, the same
    edges `scrolls graph` reports) and keeps the items on the far end of an
    edge whose near end is a match. A match itself is never listed — it is
    already a keyword hit — nor is any id in `exclude` (the representations
    folded into a kept match, ADR 0101: the same work, already shown).
    Neighbors are ranked by how many distinct matches they connect to
    (centrality), then by the best match's rank, then by id, and capped at the
    match count so the bundle stays compact. Each line names the strongest
    match that pulled the neighbor in, the direction of the edge ("links to" /
    "linked from"), and how many further matches it touches.
    """
    ranks = {item_id: rank for rank, item_id in enumerate(ranked_ids)}
    graph = build_graph(db_path)
    nodes = {node.id: node for node in graph.nodes}

    # neighbor id → {match id: direction}; the neighbor is the non-match end.
    connections: dict[str, dict[str, str]] = {}
    for edge in graph.edges:
        from_match = edge.from_id in ranks
        to_match = edge.to_id in ranks
        if from_match == to_match:  # both matched, or neither — not a bridge
            continue
        if from_match:
            match_id, neighbor_id, direction = edge.from_id, edge.to_id, "linked from"
        else:
            match_id, neighbor_id, direction = edge.to_id, edge.from_id, "links to"
        if neighbor_id in exclude:  # a folded same-work representation
            continue
        connections.setdefault(neighbor_id, {}).setdefault(match_id, direction)

    def order_key(neighbor_id: str) -> tuple:
        matches = connections[neighbor_id]
        return (-len(matches), min(ranks[m] for m in matches), neighbor_id)

    lines = []
    for neighbor_id in sorted(connections, key=order_key)[: len(ranked_ids)]:
        node = nodes.get(neighbor_id)
        if node is None:  # defensive: a connected neighbor is always a node
            continue
        matches = connections[neighbor_id]
        best_match = min(matches, key=lambda m: ranks[m])
        match_node = nodes.get(best_match)
        match_label = (match_node.title if match_node else None) or best_match
        reason = f"{matches[best_match]} {match_label}"
        if len(matches) > 1:
            reason += f" (+{len(matches) - 1} more)"
        line = f"- {node.title or node.id} (`{node.id}`)"
        if node.source:
            line += f" · {node.source}"
        lines.append(f"{line} — {reason}")
    return lines


def _meta_line(item: ScrollItem) -> str:
    parts = [f"`{item.id}`", item.source]
    if item.markdown_path:
        parts.append(item.markdown_path)
    return " · ".join(parts)


def _provenance_tags(item: ScrollItem, verdict: CustodyEvent | None) -> list[str]:
    """The per-excerpt custody/provenance tags at the `full` budget (H44 + H62).

    The model-facing bundle drops excerpts straight into an agent's window, so
    each excerpt names the two trust signals cap 8 ("an agent knows what to
    trust") asks for, beneath the id/source/path meta line:

    - **Classification** (roadmap H44) — *how the category was derived*: the same
      `classification_provenance` view `show`/`list`/`search` and the shareable
      bundle briefing carry, rendered through the shared `classification_phrase`
      so the method/confidence reads byte-identical across surfaces. Omitted on
      honest absence — an unclassified or user-set item claims no method, so the
      line is simply dropped (the excerpt's shape stays stable).
    - **Drift** (roadmap H62) — *whether the source has moved*, and *as of when*
      (roadmap H90): the `custody.drift_posture` over the item's latest
      verify-ledger verdict, followed by `· last seen <checked_at>` (the
      `custody.last_checked` of the same verdict) — or `· never re-checked` when
      the ledger holds no verdict, the honest-absence counterpart of the
      `unverified` posture. The per-source counterpart of the scope `_Custody:_`
      headline (H47). Always shown, with `unverified` stated explicitly — never
      silently "clean", the drift block's honesty on the per-excerpt axis. So an
      agent reads not just whether each excerpt's source moved but as of when,
      and can pick a `verify --stale-before <ISO>` boundary by inspection.

    Both derive from the views every other surface reads (the same `verdicts`
    `latest_events` read the headline shares), so an excerpt reads the same
    provenance an agent would see on `show`/`list`/`search` for that item. Gated
    to `full` by the caller — `index`/`connected` stay lean catalogs (the H10
    depth honesty); the two tags are a `full`-only deepening, like the excerpts.
    """
    tags = []
    view = classification_provenance(item)
    if view is not None:
        tags.append(f"_classified {classification_phrase(view)}_")
    checked = last_checked(verdict)
    when = f"last seen {checked}" if checked else "never re-checked"
    tags.append(f"_drift `{drift_posture(verdict)}` · {when}_")
    return tags


def _excerpt(item: ScrollItem) -> str:
    # collapse whitespace so stray markdown in extracted text can't break
    # the bundle's own structure
    text = " ".join((item.summary or item.extracted_text or "").split())
    if len(text) <= _EXCERPT_CHARS:
        return text
    return text[:_EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"
