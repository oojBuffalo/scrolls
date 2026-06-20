"""The custody-convergence cross-surface invariant (roadmap H50).

The custody picture an agent reads is now surfaced in seven places — `scrolls
status` (H38), the shareable bundle briefing (H45), the `scrolls context` bundle
(H47), `scrolls facets fidelity`/`drift` (H48), the `scrolls graph` stats block
(H52), the MCP `get_library_health` tool (H161 — the whole-library custody read
over MCP, `run_doctor`'s custody block plus the distilled `attention`/`headline`
`status` adds), and `doctor`'s `custody` block — each *claimed* to converge for a
given scope because they all derive from one
custody tally (`custody.custody_counts`/`custody_headline` over `get_fidelity` +
`drift_posture`/`latest_events`). That claim is pinned per-surface in scattered
tests; this module pins it *once*, the way `tests/test_completeness.py` pins the
anti-fabrication contract across every read surface.

Over one seeded fidelity/drift fixture it asserts that every surface reports the
*same* fidelity-tier counts and the *same* drift-posture counts for the whole-
library scope, with the one documented vocabulary mapping: the posture
``verified`` is the ledger status ``unchanged`` (`doctor`/`status` keep the
ledger word; the headlines and `facets drift` read the posture word). It also
pins the *enumeration* drilled from those counts — `scrolls list --drift
<posture>` (roadmap H54) returns rows that total each posture's canonical count,
so the browse filter and the aggregate can never disagree. A future change that
desyncs any one surface fails here, in one obvious place.

The **human-readable compiled** surface carries that scope picture too (roadmap
H97): the KB compiler writes the shared `custody.custody_headline` under each
compiled `library/` group list page's count line (H95, over the page's members)
and in the landing `index.md` header (H96, over the rendered library). That
scope-level headline is parsed back off a compiled page (`_library_headline`) and
asserted to total `custody_counts` for that page's scope *and* `facets
fidelity`/`facets drift` for the same `--source` filter — and the `index.md`
headline to equal `custody_counts` over the whole rendered library *and*
`doctor`'s `custody` aggregate. So the compiled library's *scope* custody summary
reads the same as the agent aggregates — the scope-level counterpart of H91's
per-item compiled-page tie, completing the compiled-surface custody theme. The
landing `index.md` also follows that headline with a `_By source:_` breakdown
(roadmap H145), the compiled-surface counterpart of the JSON `status` `by_source`
(H133) and the `export bundle` briefing (H141): its bullets equal
`custody.render_custody_by_source` over both `doctor`'s `custody.by_source` and
`custody_counts_by_source`, so the per-source line reads byte-identical across the
status / bundle / compiled surfaces. A multi-source **group list page**
(`categories/`/`concepts/`/`tags/` spanning sources) carries the *same* breakdown
under its own scope headline (roadmap H152), pinned the same way over the page's
members; a single-source page — including every `sources/*.md` — omits it (the
helper's `<2`-source no-op). The model-facing `scrolls context` bundle
carries the *same* breakdown (roadmap H149) for a multi-source scope, pinned the
same way — so a per-source line reads identically whichever readable surface
(briefing / compiled index or group page / context bundle) an agent reaches. That
"reads identically" claim is itself pinned *once* (roadmap H151): over a single
multi-source seed every readable surface — the briefing **and its HTML form**, the
`context` bundle, the compiled `index.md`, and a multi-source group page — renders
**byte-identical** per-source bullets, all equal to `render_custody_by_source` over
both `doctor`'s `custody.by_source` and `custody_counts_by_source`, and each
surface's bullets sum to its own scope headline — the readable-line analogue of the
JSON `by_source` convergence below. Each readable bullet now also trails a
``coverage V/T`` section (roadmap H158); its *value* is pinned to the JSON
`by_source[S].coverage` (`doctor`'s map and the shared tally's) once, the
readable-coverage counterpart of the per-source coverage tie (H121). The **JSON**
`by_source` map (the structured ``{source: {tiers, drift, coverage}}`` the
readable lines render from) rides `scrolls status` (H133), the `scrolls graph`
stats block (`stats.custody.by_source`, H150), and the browse-stats `--stats`
envelopes (`list`/`search`, H155 — the lean `{tiers, drift}` axes, no per-source
coverage); each is asserted to equal `doctor`'s `custody.by_source` and
`custody_counts_by_source` over the held items, and to sum to its own whole
`custody`/`stats.custody` block beside it. Those per-surface ties are pinned
scattered (the H133/H150/H155 tests); the consolidating property is pinned *once*
(roadmap H157), the JSON-surface sibling of H151's byte-identical readable test:
over one multi-source seed every JSON `by_source`-bearing surface — `status`, the
`graph` block, and the `list`/`search --stats` envelopes — reads the *same*
per-source picture (equal to `custody_counts_by_source` and `doctor`'s map on the
tiers/drift axes the lean browse family carries, coverage tied where present), and
each surface sums to its own whole block — so the per-source split reads as one
number across every JSON surface, mutation-checked non-vacuous.

The two **MCP object-twins** that carry `stats.custody.by_source` — `get_link_graph`
and `get_works` — close the same `by_source` content tie on the agent-facing read,
reached through the object entrypoint rather than the CLI (roadmap H195). They tie
to `doctor` differently because their custody *scopes* differ, and the tests pin
each honestly rather than asserting a uniform "⊂ doctor". The **graph** twin folds
its tally over the *whole* `stats.items` scope (`graph.items`, not the connected
`nodes` — H52/H150), so its `by_source` equals `doctor`'s full map field-for-field
(coverage included) *independent of `include_isolated`*: excluding an isolated item
from the rendered `nodes` does **not** drop it from the custody tally (nodes ≠
custody scope), so the graph twin is never a *subset* of doctor — pinned positively
over a connected ring plus an added isolate. The **works** twin is the genuinely
scope-restricted one: its lean `{tiers, drift}` tally folds over the reported works'
*representations* (H100/H155), so it equals `doctor`'s tiers/drift projection
*exactly when* every item is a representation, and over a seed with an
*unrepresented* item it is a strict subset of doctor's — the dropped source is
exactly the unrepresented item's, the honest scope difference, never a
disagreement. Both are non-vacuous (≥2 sources, differing per-source mixes) and
mutation-checked.

The distilled **weakest-source `attention` flag** the two object-twins carry
(`stats.custody.attention`, H164/H174) *inherits* that scope split, and the works
twin's representation-only scope can make its flag **honestly disagree** with the
whole-library audit (roadmap H211). The **graph** flag distils its whole-library
`by_source` (the coverage-bearing `weakest_source`), so it equals
`weakest_source(doctor.custody.by_source)` ≡ `status` ≡ `maintain` field-for-field
and *sees the loss even on an isolated node* (the custody scope is whole-library, not
the connected `nodes`). The **works** flag distils only the represented scope (the
lean `weakest_source`, no coverage), so over a clean two-rep work plus an
*unrepresented* drifted item it is honestly `null` — "all clear within the
consolidatable scope" — while the whole-library flag names the drifted source: the
scope boundary an agent relying on `get_works().stats.custody.attention` needs, never
a silent disagreement. Mutation-checked: bringing the same loss *into* the represented
scope (the drifted item gains the work's DOI link) makes the works flag fire and
re-converge with the whole-library flag on every shared field (`source`/`tiers`/
`drift`/`reason`/`command`), coverage staying the whole-library flag's alone.

The **`stats.custody` family** (roadmap H101) is pinned the same way. Every
browse-surface envelope carries a `stats.custody` member built by folding the
shared `custody.tally_custody` over its matched scope — the `search`/`list`/
`related --stats` envelopes (H98/H99), the always-on `scrolls works` stats block
(H100), and the `scrolls graph` stats block (H52). Each is asserted to equal
`tally_custody` over *its own* returned per-item `fidelity`/`drift` fields (the
H56/H58/H64 per-item axes), so the envelope aggregate can never desync from the
per-item fields it sums — the `related` case pins the anchor is excluded, the
`works` case its reported representations, the `graph --all` case node ≡ item
scope — and, for the stored-facet scopes (`list`/`search`), to equal `facets
fidelity`/`drift` for the same filters.

This module also pins the **per-item** counterpart of that scope-level invariant
(roadmap H59). After H56/H58/H61/H64 the per-item `drift` posture rides every
browse/landing/inspect surface — `list` rows, `search` hits, `related` hits,
`graph` nodes, the shareable bundle briefing, `show`/`get_scroll`, and the
`works` representation shape — each claimed to read the same
`custody.drift_posture` over `latest_events`. The per-item section asserts that
over one seeded fixture a given item reads the *same* `drift` on every surface
that carries it, and that each whole-library-enumerating surface's per-item
posture counts total `facets drift`'s count for that posture — tying the
per-item axis back to the aggregate the scope-level invariant pins. (`works`
needs a DOI-sharing fixture — the ring seed forms no work — so it carries its
own seed in `test_works_representation_agrees_on_an_items_drift_posture`.) The
**human-readable** surface those JSON rows previously skipped is folded in too
(roadmap H91): the `· <fidelity> · <drift>` marker the KB compiler writes on the
compiled `library/` list-page rows (H89) is parsed back off a compiled page and
asserted to equal the canonical `(get_fidelity, drift_posture)` and the JSON
`list` surface — so the compiled library reads the same per-item custody picture
an agent does.

The **model-facing `scrolls context` bundle** is folded in the same way (roadmap
H94). At the `full` budget each excerpt carries a per-source `_drift <posture> ·
last seen <checked_at>_` tag (H62/H90) — the bundle an agent actually drops into
its window — claimed to read the same `drift`/`last_checked` the inspect surface
(`show`) does. The per-item section parses that tag back off the excerpt
(`_context_excerpt_tags`, the way `_bundle_postures` parses the briefing) and
asserts the `(posture, as-of-when)` an agent reads in each excerpt equals what
`scrolls show` reports for that item — and `never re-checked` ⇔ the
`unverified`/`null` honest absence — so the model-facing bundle's per-source
custody can never silently desync from the inspect surface.

Those surfaces all carry only the *latest* posture; `scrolls history` (roadmap
H66) reads the *full* per-item ledger back. The per-item section also pins the
tie (roadmap H70): the posture the head of the ledger `history` returns implies
— `drift_posture` of its newest event — equals the `drift` every latest-posture
surface shows for that item (and `[]` ⇒ `unverified`), so the full-timeline
surface can never silently disagree with the postures that summarize it. The
time-axis counterpart (roadmap H84) is pinned the same way: the `last_checked`
timestamp `list`/`search`/`show` carry beside `drift` equals the `checked_at` of
that `history` head (and `None` ⇔ the empty timeline ⇔ never re-checked).

Finally, the **portable-custody** section (roadmap H73) lifts the per-item
invariant *across libraries*: H67/H72 make the verify ledger travel (in the
shareable bundle, and as the whole-library `export events` stream), so the
posture an item reads after an export→import must equal the posture it read
before — custody travels losslessly, not just the item. It seeds the four-posture
fixture in library A, round-trips it into a fresh library B (via `export
bundle`→`import bundle`, and via `export items`+`export events`→`import`), and
asserts B reproduces A's per-item posture on every surface and A's `facets drift`
aggregate — the convergence invariant holding by construction of the deduped
restore. The **incremental-backup** case (roadmap H78) extends that to the
windowed path: a full `export events` plus an *overlapping* `export events
--since` incremental backup (a staggered ledger so `--since` partitions with
real overlap), restored as their union in one import, is as lossless for custody
as the whole-ledger path — the union dedups (no double count) and B still
reproduces A's posture and facets.

Finally, the **verify-selection** section (roadmap H81) pins the *act* side of
the same custody picture the read surfaces enumerate. `scrolls verify` carries
four batch selections over one shared trio of `custody` selectors —
`--unverified` (`unverified_items`), `--stale-before` (`items_checked_before`),
`--drift` (`items_in_posture`), plus `--all`. It asserts they relate as
documented: `verify --drift <posture>` re-captures exactly the rows `list
--drift <posture>` enumerates, and `verify --stale-before <ISO>` exactly those
`list --stale-before <ISO>` enumerates (the shared `items_in_posture` /
`items_checked_before` selectors back each read↔act pair, roadmap H85); `verify
--stale-before <future>` subsumes `--unverified` and clears the same
`doctor custody.drift.unverified` bucket; and every batch selection skips
reference-only items identically — so the recheck set can never desync from the
read enumeration.

That section closes with the **scheduled** face of the same selector (roadmap
H111): a default `scrolls maintain` pass stale-bounds its recheck to the held
items not seen since the last run (H83), the boundary being the last recorded
snapshot's `recorded_at` (`maintain.last_run_boundary`) and the set
`items_checked_before` at it — the *same* selector `verify --stale-before <ISO>`
(H79) uses explicitly. So the load-bearing tie: the set a default maintain pass
re-verifies is exactly the set `verify --stale-before <last-run recorded_at>`
would, captured by a recording recapture stub (the set each pass actually
touches) over one mixed-staleness fixture. It also pins that the never-checked
`--unverified` bucket is subsumed by that stale set (trivially stale at any
boundary) and that `maintain --all` ignores the boundary and rechecks the whole
hash-bearing set — so the scheduled recheck is the recurring, self-timestamping
member of the verify-selection family, not a parallel-implementation coincidence.

The **per-source scheduled** face of the per-source aggregate is pinned the same
way (roadmap H127/H129). H123 threads `doctor`'s `custody.by_source` map (the
whole-library fidelity/drift aggregate split per source, H104) into the `maintain`
report, and H119 distils it to the single weakest-source `attention` flag — each
*claimed* to agree with the standalone audit because the report member is a pure
read of the same `run_doctor` map. This pins both ties as first-class entries
beside the H104 per-source-tally invariant: over the multi-source seed a `maintain
--no-recheck` pass's report `by_source` equals `doctor`'s `custody.by_source` for
the same post-maintenance library, `custody_counts_by_source` over the held items,
and (per source) `facets fidelity`/`drift --source <name>` (H127); and its
`attention.source` equals the source maximizing `drifted + rotted` in that map,
with `attention` honestly `null` exactly when no source carries actionable loss
(H129). `--no-recheck` keeps the pass network-free and the ledger pristine, so the
maintain audit and a fresh `doctor` read the identical state — the scheduled
worker's per-source picture can never silently desync from the audit it reads.

The **scoped audit** is the read-side sibling (roadmap H162): `scrolls doctor
--source S` scopes the *whole* audit to one source's held items, so a worker
triaging the weakest source reads its full custody picture (drift, enrichment,
coverage, the offending-id lists) directly instead of slicing it out of the
whole-library report. This pins the convergence by construction — a `--source S`
audit's `custody.tiers`/`drift`/`coverage` equals the whole-library audit's
`by_source[S]` slice, `by_source` collapses to the present-and-singleton
`{S: that slice}`, and `enrichment.stale` equals the whole-library
`enrichment.by_source[S]` (0 + omitted for a clean source) — over the same
multi-source loss seed, non-vacuous (the two sources differ on every axis) and
mutation-checked (a perturbed slice never matches the scoped audit). An unknown
source is the honest empty audit (`score: 100`, empty `by_source`), never an
error — the per-source-scope counterpart of the per-source-aggregate tie above.
The **same** `run_doctor(source=)` pre-filter backs the rest of the per-source
read family: `status --source S` (roadmap H166), `maintain --source S` (H165, the
scheduled pass), and MCP `get_library_health(source=S)` (H167, the agent-over-MCP
read). Each is pinned to equal the others and the `by_source[S]` slice over the
loss seed, with `attention` honestly `null` on every single-source scope (the
`weakest_source` gate has nothing to rank across) — so the scoped custody picture
is one number whichever of the four surfaces a worker or agent reaches. Those
ties are pinned scattered (the four scoped-read tests above); the consolidating
property is pinned *once* (roadmap H169, the capstone — the scoped-read sibling of
H157's whole-library JSON `by_source` consolidation): over the loss seed all four
`--source S` reads agree key-for-key (the snapshot-shaped pair `status`/`maintain`
== the distilled scoped audit; the raw-block MCP read == the scoped `doctor`
block) and each lines up with the `by_source[S]` slice, the rendered headline is
identical across the three that render one, and `attention` is `null` on each —
mutation-checked non-vacuous, so a future scoped surface has one contract to
satisfy.

The **`status` surface** carries the same per-source breakdown (roadmap H133): a
faithful read (`report_by_source`) of the `run_doctor` map `status` already makes
for its custody headline. This pins it beside the maintain tie — over the
multi-source seed, `status`'s `by_source` equals `maintain --no-recheck`'s
`by_source`, `doctor`'s `custody.by_source`, and `custody_counts_by_source` over
the held items, and sums to `status`'s own `custody` block — so the three places a
human/worker reads the per-source picture are one number. `status` also distils
that map to the single weakest-source `attention` flag (roadmap H139) via the same
`weakest_source` primitive `maintain`'s `attention` uses, so the `attention`-axis
tie is pinned here too: over the loss seed `status`'s `attention` equals `maintain
--no-recheck`'s, names `doctor`'s max-loss source, and is honestly `null` exactly
when no source carries actionable loss — the status-surface counterpart of the
H129 maintain↔doctor `attention` tie. The `graph` `stats.custody.attention`
(roadmap H164) is folded in beside it: distilled by the *same* `weakest_source`
over the graph's own `by_source` (which equals `doctor`'s for the whole-library
scope), so over the loss seed the graph flag equals `status`'s, `maintain`'s, and
`weakest_source(doctor.by_source)`, and is honestly `null` on the same gate.

The **readable `_Attention:_` line** (roadmap H159) the `export bundle`/`scrolls
context` briefings carry above their `_By source:_` map is folded in too: H159 pins
its parsed `{source, reason, command}` to the same `weakest_source` primitive and the
JSON flag; the **full field-for-field** invariant (roadmap H160) sharpens that to the
shape the JSON `status`/`maintain` flags carry. Over a seed whose weakest source
carries both a drifted *and* a rotted item over a partial `2/3` coverage (so every
field is non-trivial), the readable surface distilled — the line's source / loss
reason **decomposed into `{drifted, rotted}`** / recheck command, *plus* the flagged
source's `_By source:_` `coverage V/T` section (H158) — equals the JSON `status` and
`maintain` flags field-for-field, all equal `weakest_source(doctor.custody.by_source)`,
and mutation-checked (perturbing any one field of any surface's distillation breaks the
tie). So the single weakest-source pointer reads one number across the readable line
and both JSON surfaces — the `attention`-axis counterpart of H151's byte-identical
readable `_By source:_` tie.

Both the drift `_Attention:_` line **and** the refresh `_Refresh:_` line (H178) are
then pinned **byte-identical across every readable surface** (roadmap H188) — the
action-line extension of H151's byte-identical `_By source:_` invariant. Over a scope
identical across the bundle query, the `scrolls context` query, the compiled
`index.md` and a compiled group page, each rendered line is character-for-character the
same string and equals `render_custody_attention`/`render_custody_refresh` over the
shared scope, so the one shared renderer is the sole source of the wording and no
surface can drift in punctuation or phrasing (the honest-*absence* counterpart — a
compiled page never fabricating an action line with no JSON basis — is pinned in the
completeness contract, `tests/test_completeness.py`, roadmap H190). The **HTML
bundle form** renders the same pointers as `<p class="custody-attention">`/`<p
class="custody-refresh">`, so it cannot be *string*-identical to the Markdown — but
its **content** must not diverge (roadmap H192): over the same `_seed_action_line_
fixture` scope, the HTML attention line's parsed `{source, reason, command}` equals
the Markdown line's and the canonical primitive, and the HTML refresh line's per-axis
source list equals the Markdown's per axis — the action-line analogue of H151's
`_html_by_source_bullets` content tie, mutation-checked so perturbing the data moves
both forms together.

The **single-source `sources/<S>.md` pages** carry the positive companion of that
honest-absence posture (roadmap H193). Unlike `_Attention:_` and `_By source:_` (the
`<2`-source no-ops a single-source page always omits), the `_Refresh:_` line has *no*
single-source gate, so a `sources/<S>.md` page shows it exactly when source `<S>`
carries stale enrichment/summary debt — naming the same axes `doctor --source <S>`'s
`enrichment.by_source`/`summaries.by_source` keys do, computed over the page's own
member scope. The load-bearing subtlety pinned positively: a multi-source concept's
stale summary attributes to every member source at the whole-library scope (the H171
attribution), but narrows below `MIN_MEMBERS` under a single-source scope and drops
out — so a `sources/<S>.md` page's summary axis reflects only the within-source
clusters, exactly as the scoped audit does, and a source whose *only* summary
participation was a multi-source cluster shows the honest-clean page (no `_Refresh:_`).

The **act side of the per-source enrichment debt** is pinned the way the
verify-selection section pins the drift act side. `classify --stale --source S`
(roadmap H154) and `kb --stale --source S` (roadmap H176) each regenerate exactly
the offenders `doctor`'s `custody.enrichment.by_source[S]` / `custody.summaries.
by_source[S]` report — the count refreshed equals doctor's per-source number (the
shared `is_stale_classification` / `is_stale_summary` predicate the audit builds
its map from), and refreshing clears that source's entry from the offenders-only
map. The two axes differ in attribution: a classification belongs to one source, so
a refresh clears exactly that source's entry; a summary spans a *cluster* whose
members may come from several sources, so refreshing under one of a cluster's
sources clears **all** of them (the H171 attribution) while an unrelated
single-source concept is left whole. Both are mutation-checked non-vacuous
(perturbing the refresh scope breaks the count tie), completing the per-source
*refresh* convergence on both enrichment axes beside the per-source *report* ties
above.

The **suggestion side** of that act is pinned the same way (roadmap H183). When a
refresh axis's stale debt is confined to a strict subset of the held sources,
`maintain`'s `suggested` block names the minimal scoped act per offending source
(`classify --stale --source S` / `kb --stale --source S`, roadmap H181) rather than
the whole-library sweep. The convergence: the *set of sources the scoped suggestions
name* ≡ the keys of the very debt maps the same report carries
(`enrichment_by_source` / `summary_by_source`), which the H179 tie above already pins
≡ `doctor`'s `custody.{enrichment,summaries}.by_source` — so the act a worker is told
to run targets exactly the sources the report says carry debt. The H171 attribution
carries through to the suggestion: a multi-source stale cluster names each of its
sources, so the summary suggestion can name more sources than there are stale clusters
(every member earns its own scoped command). The boundary case is the complement —
when **every** held source is stale the offenders are not a strict subset, so the
suggestion collapses to the single un-scoped whole-library command per axis. Both are
mutation-checked non-vacuous (a `kb --stale --source` refresh drops that source from
the summary suggestions in lockstep with the debt map, while the enrichment-axis
suggestions stay put); it is the action-pointer sibling of H179's read convergence,
on the per-source axis.

Finally, the **trend layer** is pinned to the per-run history the same way
(roadmap H143). `maintain.compute_trend` (H46/H115/H131) reports the net
first→last movement on `drift_change`/`coverage_change`/`stale_change` (and the
scalar `score.change`) by reading only the window's *endpoints*, while
`maintain.compute_delta` (H34) records the per-run before/after/change between
consecutive snapshots — the step-by-step history `maintain --history` reads back.
The load-bearing property neither layer pins alone is that the trend's net change
equals the **telescoped sum** of the per-run deltas across the window, so the
endpoint-only trajectory can never silently disagree with the recorded history a
worker also reads. The trend section asserts that identity on every axis over a
non-monotone multi-run window (drift up then down, score down then up), both
recomputing `compute_delta` over consecutive snapshots and telescoping the
*recorded* `delta` member each entry carries through the real
`append_log_entry`/`read_log` path; covers the honest-absence edges (a
`None`-score endpoint → a null trend `score.change` while the count axes still
telescope, a `<2`-run window has no trajectory to telescope); and is
mutation-checked non-vacuous (perturbing one endpoint moves the trend and the
telescoped sum together). It is the trend-layer analogue of the per-surface
convergence invariants above.
"""

import html
import json
import re

import pytest

import scrolls.cli as cli
from scrolls.cli import main
from scrolls.custody import (
    CustodyEvent,
    custody_counts,
    custody_counts_by_source,
    custody_headline,
    drift_posture,
    items_checked_before,
    last_checked,
    latest_events,
    parse_since,
    recheck_coverage,
    record_events,
    render_custody_attention,
    render_custody_by_source,
    render_custody_refresh,
    tally_custody,
    tally_custody_by_source,
    unverified_items,
)
from scrolls.doctor import run_doctor
from scrolls.facets import compute_facets
from scrolls.items import ScrollItem, get_fidelity, insert_item, list_items, update_item
from scrolls.maintain import (
    append_log_entry,
    compute_delta,
    compute_trend,
    custody_snapshot,
    last_run_boundary,
    load_snapshot,
    log_path,
    read_log,
    report_by_source,
    report_enrichment_by_source,
    report_summary_by_source,
    save_snapshot,
    snapshot_headline,
    snapshot_path,
    suggest_repairs,
    weakest_source,
)
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _item(item_id, title, **overrides):
    base = dict(
        id=item_id,
        source="web",
        url=f"https://example.com/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=title,
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _seed_mixed_custody(db):
    """Four held scrolls spanning the fidelity tiers and drift postures.

    Every title carries "topic" so a `topic` query matches the whole library
    (the bundle/context surfaces are query-scoped). Fidelity: two `full`
    (raw_text + content_hash, captured), one `partial` (extracted text only,
    no hash), one `reference` (a detected pointer, no content). Drift: one
    re-checked unchanged (→ `verified`), one drifted, two never re-checked
    (→ `unverified`).
    """
    insert_item(db, _item(
        "web:full1", "Topic full one",
        extracted_text="topic one body", raw_text="<raw>topic one</raw>",
        content_hash="sha256:full1",
    ))
    insert_item(db, _item(
        "web:full2", "Topic full two",
        extracted_text="topic two body", raw_text="<raw>topic two</raw>",
        content_hash="sha256:full2",
    ))
    insert_item(db, _item(
        "web:partial", "Topic partial",
        extracted_text="topic partial body",  # no hash/raw → partial
    ))
    insert_item(db, _item(
        "web:ref", "Topic reference pointer", stage="detected",  # no content → reference
    ))
    record_events(db, [
        CustodyEvent("web:full1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:full1", "sha256:full1", None),
        CustodyEvent("web:full2", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:full2", "sha256:changed", None),
        # web:partial, web:ref left unverified
    ])


def _posture_from_ledger_counts(drift):
    """Normalise a `doctor`/`status` drift block to the posture vocabulary.

    The only vocabulary difference across the surfaces: the ledger-status word
    ``unchanged`` is the posture ``verified``; everything else shares its name.
    """
    return {
        "verified": drift["unchanged"],
        "unverified": drift["unverified"],
        "drifted": drift["drifted"],
        "rotted": drift["rotted"],
        "error": drift["error"],
    }


def _nonzero(counts):
    return {key: value for key, value in counts.items() if value}


def _facet_map(entries):
    return {entry["value"]: entry["count"] for entry in entries}


def test_every_custody_surface_converges_on_one_picture(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)
    capsys.readouterr()

    # The canonical picture: the shared tally over the whole library + ledger.
    items = list_items(db)
    verdicts = latest_events(db)
    canonical = custody_counts(items, verdicts)
    # sanity: the fixture is the non-trivial mix the surfaces must all reproduce
    assert canonical["tiers"] == {"full": 2, "partial": 1, "reference": 1}
    assert _nonzero(canonical["drift"]) == {"verified": 1, "unverified": 2, "drifted": 1}

    # 1. doctor — the custody aggregate every other surface is measured against
    custody = run_doctor(get_paths())["custody"]
    assert custody["tiers"] == canonical["tiers"]
    assert _posture_from_ledger_counts(custody["drift"]) == canonical["drift"]

    # 2. status — the headline block is custody_snapshot(run_doctor), so it
    #    carries doctor's tiers/drift verbatim
    assert main(["status"]) == 0
    status_custody = json.loads(capsys.readouterr().out)["custody"]
    assert status_custody["tiers"] == canonical["tiers"]
    assert _posture_from_ledger_counts(status_custody["drift"]) == canonical["drift"]

    # 3. facets — the browse aggregates of the same two axes
    fidelity = _facet_map(compute_facets(db, field="fidelity")["facets"]["fidelity"])
    drift = _facet_map(compute_facets(db, field="drift")["facets"]["drift"])
    assert fidelity == _nonzero(canonical["tiers"])
    assert drift == _nonzero(canonical["drift"])

    # 4. the bundle briefing + context bundle headlines — the *rendered* line is
    #    the shared custody_headline over the whole (uncapped, uncollapsed) scope
    headline = custody_headline(items, verdicts)
    assert "fidelity full 2, partial 1, reference 1" in headline  # canonical, rendered
    assert "drift verified 1, unverified 2, drifted 1" in headline

    assert main(["export", "bundle", "topic"]) == 0
    bundle_out = capsys.readouterr().out
    assert headline in bundle_out

    assert main(["context", "topic"]) == 0
    context_out = capsys.readouterr().out
    assert headline in context_out

    # 5. the graph stats block — the JSON custody counts (posture words, like
    #    custody_counts) over the whole stats.items scope (roadmap H52)
    assert main(["graph", "--all"]) == 0
    graph_custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    assert graph_custody["tiers"] == canonical["tiers"]
    assert graph_custody["drift"] == canonical["drift"]

    # 6. `list --drift <posture>` — the row enumeration drilled from the count.
    #    The rows for each posture *total* that posture's canonical count, so the
    #    browse filter and the aggregate can never disagree (roadmap H54).
    for posture, count in canonical["drift"].items():
        assert main(["list", "--drift", posture]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == count, f"list --drift {posture}: {len(rows)} != {count}"


def test_convergence_holds_under_a_scope_filter(scrolls_home, capsys):
    # the surfaces converge for *any* shared scope, not only the whole library:
    # the same `--source` filter narrows doctor-free surfaces identically
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)
    # add an out-of-scope item so a source filter actually excludes something
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # canonical picture for the web-only scope
    web_items = [item for item in list_items(db) if item.source == "web"]
    verdicts = latest_events(db)
    canonical = custody_counts(web_items, verdicts)

    # facets drift/fidelity scoped to source=web agree with the scoped tally
    fidelity = _facet_map(
        compute_facets(db, field="fidelity", source="web")["facets"]["fidelity"]
    )
    drift = _facet_map(compute_facets(db, field="drift", source="web")["facets"]["drift"])
    assert fidelity == _nonzero(canonical["tiers"])
    assert drift == _nonzero(canonical["drift"])

    # the context bundle scoped to source=web carries the same scoped headline
    assert main(["context", "topic", "--source", "web"]) == 0
    assert custody_headline(web_items, verdicts) in capsys.readouterr().out


# --- cross-tier fidelity convergence (roadmap H213) ------------------------
#
# The budget/tier-honesty sibling of this module's spine. `scrolls context`
# surfaces fidelity at *every* budget tier, but through two different lines: the
# leanest `index` tier (which reads no custody ledger) carries the ledger-free
# `_Fidelity:_` holdings line (H212), while `connected`/`full` carry the full
# `_Custody:_` headline whose `fidelity` section folds the same counts. Both, and
# `doctor`'s `custody.tiers`, are reads of one ledger-free fact (`get_fidelity`
# per item) over one scope — so a tier may never disagree with another tier, or
# with the audit, on *what fraction is held in full*. The spine ties the whole
# *headline* across surfaces; this ties the *fidelity counts* across the context
# budget tiers and the audit.

_FIDELITY_TIER_TOKEN = re.compile(r"\b(full|partial|reference) (\d+)\b")


def _rendered_fidelity_counts(line):
    """Non-zero fidelity-tier counts parsed back from a rendered custody line.

    Reads either the `index` tier's `_Fidelity: full 2, partial 1 (of N)._`
    holdings line *or* the `connected`/`full` `_Custody:` headline's `fidelity
    full 2, partial 1` section: the tier words (full/partial/reference) never
    collide with the drift-posture words, so one parse reads either line and the
    `N scroll(s)`/`(of N)` scalars are never mistaken for a tier count.
    """
    return {tier: int(n) for tier, n in _FIDELITY_TIER_TOKEN.findall(line)}


def _line_with(out, prefix):
    return next(line for line in out.splitlines() if line.startswith(prefix))


def _context_out(capsys, *args):
    assert main(["context", *args]) == 0
    return capsys.readouterr().out


def test_index_fidelity_line_ties_to_the_headline_and_doctor_tiers(scrolls_home, capsys):
    # roadmap H213 — the cross-*tier* fidelity convergence. The `index` budget's
    # `_Fidelity:_` holdings line, both the `connected` and `full` `_Custody:_`
    # headlines' `fidelity` section, and `doctor`'s `custody.tiers` are four reads
    # of one ledger-free fact over one scope; none may disagree on the fidelity mix.
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # full 2, partial 1, reference 1 — ≥2 tiers, non-vacuous
    capsys.readouterr()

    def picture():
        index = _rendered_fidelity_counts(
            _line_with(_context_out(capsys, "topic", "--budget", "index"), "_Fidelity:")
        )
        connected = _rendered_fidelity_counts(
            _line_with(_context_out(capsys, "topic", "--budget", "connected"), "_Custody:")
        )
        full = _rendered_fidelity_counts(
            _line_with(_context_out(capsys, "topic", "--budget", "full"), "_Custody:")
        )
        tiers = _nonzero(run_doctor(get_paths())["custody"]["tiers"])
        return index, connected, full, tiers

    index, connected, full, tiers = picture()
    # non-vacuous: a genuine multi-tier mix, not an all-`full` or empty scope
    assert tiers == {"full": 2, "partial": 1, "reference": 1}
    # the tie: the index holdings line ≡ both headlines' fidelity section ≡ the audit
    assert index == connected == full == tiers

    # mutation in lockstep — drop `web:full1`'s re-derivable body (raw_text + hash)
    # so it falls `full` → `partial`. The shift must register identically on every
    # surface, proving each recomputes `get_fidelity` rather than echoing a cached count.
    import dataclasses

    full1 = next(it for it in list_items(db) if it.id == "web:full1")
    assert update_item(db, dataclasses.replace(full1, raw_text=None, content_hash=None))
    mutated = next(it for it in list_items(db) if it.id == "web:full1")
    assert get_fidelity(mutated) == "partial"  # the dropped body cost it a tier
    capsys.readouterr()

    index, connected, full, tiers = picture()
    assert tiers == {"full": 1, "partial": 2, "reference": 1}  # the shift, on the audit
    assert index == connected == full == tiers  # and in lockstep on every tier


def test_doctor_by_source_converges_with_the_per_source_tally_and_facets(scrolls_home, capsys):
    # roadmap H104: doctor's `custody.by_source` splits the whole-library custody
    # aggregate per source. Each per-source tally must equal `custody_counts` over
    # that source's items *and* `facets fidelity`/`drift --source X`, and the
    # per-source tallies must sum to the whole-library `custody` block — the
    # per-source sibling of the whole-library convergence (this module's spine).
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # four `web` scrolls spanning the tiers/postures
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}

    # 1. each per-source tally's tiers/drift == custody_counts over that source's
    #    items, and == facets fidelity/drift scoped to that source (the browse
    #    aggregate); the per-source coverage == recheck_coverage over that source's
    #    hash-bearing items (the coverage-axis counterpart, roadmap H121).
    for source in ("web", "arxiv"):
        members = [item for item in items if item.source == source]
        canonical = custody_counts(members, verdicts)
        assert by_source[source]["tiers"] == canonical["tiers"]
        assert by_source[source]["drift"] == canonical["drift"]
        hash_bearing = [item for item in members if item.content_hash]
        assert by_source[source]["coverage"] == recheck_coverage(hash_bearing, verdicts)
        fidelity = _facet_map(
            compute_facets(db, field="fidelity", source=source)["facets"]["fidelity"])
        drift = _facet_map(
            compute_facets(db, field="drift", source=source)["facets"]["drift"])
        assert fidelity == _nonzero(by_source[source]["tiers"])
        assert drift == _nonzero(by_source[source]["drift"])

    # 2. the per-source tallies sum to the whole-library `custody` block (H50, per
    #    source): summing the groups re-counts the whole library.
    whole = custody_counts(items, verdicts)
    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in by_source.values():
        for tier, n in counts["tiers"].items():
            summed_tiers[tier] += n
        for posture, n in counts["drift"].items():
            summed_drift[posture] += n
    assert summed_tiers == whole["tiers"]
    assert summed_drift == whole["drift"]
    # and the whole-library tally == doctor's own block (the module's spine tie)
    custody = run_doctor(get_paths())["custody"]
    assert summed_tiers == custody["tiers"]
    assert summed_drift == _posture_from_ledger_counts(custody["drift"])
    # 3. the per-source coverage sums to the whole-library `drift.coverage` (H121,
    #    the coverage-axis sibling of the tiers/drift sum-to-whole above).
    summed_coverage = {"verified": 0, "total": 0}
    for counts in by_source.values():
        summed_coverage["verified"] += counts["coverage"]["verified"]
        summed_coverage["total"] += counts["coverage"]["total"]
    assert summed_coverage == custody["drift"]["coverage"]


def _seed_two_source_loss(db):
    """A multi-source seed whose two sources differ on every custody axis.

    web: a verified+stale-classified full item, a drifted full item, a
    reference-only pointer. arxiv: a never-checked full item with a *current*
    classification, and a partial item. So web and arxiv differ on tiers
    (full 2/ref 1 vs full 1/partial 1), drift (1 verified + 1 drifted vs 2
    unverified), coverage (2/2 vs 0/1), and enrichment stale (1 vs 0) — every
    leg of the scoped-audit convergence is non-vacuous.
    """
    from scrolls.classify import RULESET_FINGERPRINT

    insert_item(db, _item(
        "web:full", "Topic web full", category="tutorial",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:wf",
        provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": "deadbeef0000"}))  # stale ruleset
    insert_item(db, _item(
        "web:drift", "Topic web drift",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:wd"))
    insert_item(db, _item("web:ref", "Topic web pointer", stage="detected"))
    insert_item(db, _item(
        "arxiv:full", "Topic arxiv full", source="arxiv",
        url="https://arxiv.org/abs/full", category="tutorial",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:af",
        provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": RULESET_FINGERPRINT}))  # current
    insert_item(db, _item(
        "arxiv:partial", "Topic arxiv partial", source="arxiv",
        url="https://arxiv.org/abs/partial", extracted_text="topic"))  # no hash
    record_events(db, [
        CustodyEvent("web:full", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:wf", "sha256:wf", None),
        CustodyEvent("web:drift", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:wd", "sha256:changed", None),
    ])


def test_doctor_source_scope_converges_with_the_whole_library_by_source(scrolls_home, capsys):
    # roadmap H162: `scrolls doctor --source S` scopes the whole audit to one
    # source's held items — the audit-side counterpart of the per-source act
    # commands (`verify --source`, H125). The convergence it guarantees, the
    # per-source-scope sibling of H104's `by_source` tie: a `--source S` audit's
    # `custody.tiers`/`drift`/`coverage` equals the whole-library audit's
    # `by_source[S]` slice (same held subset, same tally), and its
    # `enrichment.stale` equals the whole-library `enrichment.by_source[S]` — so
    # the scoped read and the per-source slice of the whole report can never
    # disagree.
    main(["init"])
    db = get_paths().db_path
    _seed_two_source_loss(db)
    capsys.readouterr()

    whole = run_doctor(get_paths())["custody"]
    by_source = whole["by_source"]
    enrichment_by_source = whole["enrichment"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}
    # non-vacuous: the two sources genuinely differ on every axis the scope reads
    assert by_source["web"]["tiers"] != by_source["arxiv"]["tiers"]
    assert by_source["web"]["drift"] != by_source["arxiv"]["drift"]
    assert by_source["web"]["coverage"] != by_source["arxiv"]["coverage"]
    assert enrichment_by_source == {"web": 1}  # only web carries stale debt

    for source in ("web", "arxiv"):
        scoped = run_doctor(get_paths(), source=source)["custody"]
        slice_ = by_source[source]
        # 1. the scoped custody view == the whole-library by_source[S] slice
        assert scoped["tiers"] == slice_["tiers"]
        assert _posture_from_ledger_counts(scoped["drift"]) == slice_["drift"]
        assert scoped["drift"]["coverage"] == slice_["coverage"]
        # 2. by_source collapses to the present-and-singleton {S: that same slice}
        assert scoped["by_source"] == {source: slice_}
        # 3. the enrichment offending count == the whole-library by_source entry
        #    (0 — and omitted from the offenders map — for a clean source)
        assert scoped["enrichment"]["stale"] == enrichment_by_source.get(source, 0)
        assert scoped["enrichment"]["by_source"] == (
            {source: enrichment_by_source[source]} if source in enrichment_by_source else {}
        )

    # 4. teeth: the equality is not vacuous — a perturbed slice would not match the
    #    scoped audit (so a real desync between the scope and the by_source split
    #    fails this test), and the cross-source slice never matches either.
    web_scoped = run_doctor(get_paths(), source="web")["custody"]
    perturbed = {**by_source["web"]["tiers"], "full": by_source["web"]["tiers"]["full"] + 1}
    assert web_scoped["tiers"] != perturbed
    assert web_scoped["tiers"] != by_source["arxiv"]["tiers"]


def test_doctor_source_scope_unknown_source_is_the_honest_empty_audit(scrolls_home, capsys):
    # the honest-absence gate (H162): an unknown source holds nothing, so the
    # scoped audit is the empty-but-healthy report (score 100, zeroed counts, empty
    # by_source) — never an error, exactly like the whole-library empty audit.
    main(["init"])
    db = get_paths().db_path
    _seed_two_source_loss(db)
    capsys.readouterr()

    report = run_doctor(get_paths(), source="ghost")
    assert report["custody"]["score"] == 100
    assert report["custody"]["by_source"] == {}
    assert report["custody"]["enrichment"]["by_source"] == {}
    assert report["issues"] == 0
    assert main(["doctor", "--source", "ghost"]) == 0


def test_status_source_scope_converges_with_the_whole_library_by_source(scrolls_home, capsys):
    # roadmap H166: `scrolls status --source S` scopes the status read to one
    # source's held items — the status-surface counterpart of `doctor --source`
    # (H162). The convergence pinned here, the status sibling of the doctor-scope
    # tie above: a `--source S` status's `custody` block equals the whole-library
    # audit's `by_source[S]` slice *and* a `doctor --source S` audit distilled
    # (`custody_snapshot`), so the scoped status and the per-source slice of the
    # whole report can never disagree; `by_source` collapses to the singleton, and
    # `attention` is honestly `null` (a single source has nothing to flag across).
    main(["init"])
    db = get_paths().db_path
    _seed_two_source_loss(db)
    capsys.readouterr()

    whole = run_doctor(get_paths())["custody"]["by_source"]
    assert set(whole) == {"web", "arxiv"}
    # non-vacuous: the two sources differ on every axis the scoped status reads
    assert whole["web"]["tiers"] != whole["arxiv"]["tiers"]
    assert whole["web"]["drift"] != whole["arxiv"]["drift"]
    assert whole["web"]["coverage"] != whole["arxiv"]["coverage"]

    for source in ("web", "arxiv"):
        assert main(["status", "--source", source]) == 0
        payload = json.loads(capsys.readouterr().out)
        slice_ = whole[source]
        custody = payload["custody"]
        # 1. the scoped status custody view == the whole-library by_source[S] slice
        assert custody["tiers"] == slice_["tiers"]
        assert _posture_from_ledger_counts(custody["drift"]) == slice_["drift"]
        assert custody["coverage"] == slice_["coverage"]
        # 2. == the scoped `doctor --source S` audit distilled (the snapshot shape)
        assert custody == custody_snapshot(run_doctor(get_paths(), source=source))
        # 3. by_source collapses to the present-and-singleton {S: that same slice}
        assert payload["by_source"] == {source: slice_}
        # 4. the rendered headline is the scoped block rendered (parity with maintain)
        assert payload["headline"] == snapshot_headline(custody)
        # 5. attention is null under a single-source scope (nothing stands out)
        assert payload["attention"] is None

    # teeth: the equality is not vacuous — the cross-source slice never matches the
    # scoped status, so a real desync between the scope and the by_source split fails.
    assert main(["status", "--source", "web"]) == 0
    web_status = json.loads(capsys.readouterr().out)["custody"]
    assert web_status["tiers"] != whole["arxiv"]["tiers"]


def test_status_source_unknown_is_the_honest_empty_headline(scrolls_home, capsys):
    # the honest-absence gate (H166, mirroring the doctor-scope unknown-source
    # gate): an unknown source holds nothing, so the scoped status is the empty
    # headline (`_Custody: 0 scroll(s)._`, score 100 over an initialized library,
    # empty by_source, null attention) — never an error.
    main(["init"])
    _seed_two_source_loss(get_paths().db_path)
    capsys.readouterr()

    assert main(["status", "--source", "ghost"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["custody"]["score"] == 100
    assert payload["by_source"] == {}
    assert payload["headline"] == "_Custody: 0 scroll(s)._"
    assert payload["attention"] is None
    assert payload["items"]["total"] == 0


def test_maintain_source_scope_converges_with_the_whole_library_by_source(
    scrolls_home, capsys
):
    # roadmap H165: `scrolls maintain --source S` scopes the scheduled pass to one
    # source's held items — the maintenance-surface counterpart of `doctor --source`
    # (H162) and `status --source` (H166), reusing the same `run_doctor(source=)`
    # pre-filter. The convergence pinned here, the third leg of the per-source-scope
    # triad (the capstone H169 ties all four scoped reads + MCP together once H167
    # lands): a `--source S` pass's `custody`/`by_source`/`headline` equals the
    # whole-library audit's `by_source[S]` slice, a `doctor --source S` audit
    # distilled, AND a `status --source S` payload — `--no-recheck` keeps the ledger
    # pristine so the maintain audit and the fresh doctor/status reads see the same
    # state. `attention` is null on a single-source scope.
    main(["init"])
    db = get_paths().db_path
    _seed_two_source_loss(db)
    capsys.readouterr()

    whole = run_doctor(get_paths())["custody"]["by_source"]
    assert set(whole) == {"web", "arxiv"}
    # non-vacuous: the two sources differ on every axis the scoped pass reads
    assert whole["web"]["tiers"] != whole["arxiv"]["tiers"]
    assert whole["web"]["drift"] != whole["arxiv"]["drift"]
    assert whole["web"]["coverage"] != whole["arxiv"]["coverage"]

    for source in ("web", "arxiv"):
        assert main(["maintain", "--no-recheck", "--source", source]) == 0
        report = json.loads(capsys.readouterr().out)
        slice_ = whole[source]
        custody = report["custody"]
        # 1. the scoped maintain custody view == the whole-library by_source[S] slice
        assert custody["tiers"] == slice_["tiers"]
        assert _posture_from_ledger_counts(custody["drift"]) == slice_["drift"]
        assert custody["coverage"] == slice_["coverage"]
        # 2. == the scoped `doctor --source S` audit distilled (the snapshot shape)
        assert custody == custody_snapshot(run_doctor(get_paths(), source=source))
        # 3. == a `status --source S` payload's custody/by_source/headline
        assert main(["status", "--source", source]) == 0
        status = json.loads(capsys.readouterr().out)
        assert custody == status["custody"]
        assert report["by_source"] == status["by_source"] == {source: slice_}
        assert report["headline"] == status["headline"] == snapshot_headline(custody)
        # 4. attention null + delta null (scoped, non-persisting — keeps no baseline)
        assert report["attention"] is None
        assert report["delta"] is None

    # teeth: the equality is not vacuous — the cross-source slice never matches the
    # scoped pass, so a real desync between the scope and the by_source split fails.
    assert main(["maintain", "--no-recheck", "--source", "web"]) == 0
    web_maintain = json.loads(capsys.readouterr().out)["custody"]
    assert web_maintain["tiers"] != whole["arxiv"]["tiers"]


def test_maintain_source_scope_unknown_source_is_the_honest_empty_pass(
    scrolls_home, capsys
):
    # the honest-absence gate (H165, mirroring the doctor/status unknown-source
    # gates): an unknown source holds nothing, so the scoped pass is the empty
    # headline (`_Custody: 0 scroll(s)._`, empty by_source, null attention/delta) —
    # never an error, and it agrees with `doctor --source ghost` distilled.
    main(["init"])
    _seed_two_source_loss(get_paths().db_path)
    capsys.readouterr()

    assert main(["maintain", "--no-recheck", "--source", "ghost"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["custody"] == custody_snapshot(run_doctor(get_paths(), source="ghost"))
    assert report["by_source"] == {}
    assert report["headline"] == "_Custody: 0 scroll(s)._"
    assert report["attention"] is None
    assert report["delta"] is None


def test_mcp_library_health_source_scope_converges_with_doctor_and_status_source(
    scrolls_home, capsys
):
    # roadmap H167: MCP `get_library_health(source=S)` scopes the whole custody read
    # to one source's held items — the MCP sibling of `doctor --source` (H162) /
    # `status --source` (H166), reusing the same `run_doctor(source=)` pre-filter.
    # The MCP leg of the per-source-scope family (the H169 capstone folds it beside
    # the three CLI ties): a `get_library_health(source=S)` block equals the
    # whole-library audit's `by_source[S]` slice, a `doctor --source S` audit, AND a
    # `status --source S` payload's custody — and `attention` is honestly null on a
    # single source (the cross-source gate has nothing to rank).
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    _seed_two_source_loss(db)
    capsys.readouterr()

    whole = run_doctor(get_paths())["custody"]["by_source"]
    assert set(whole) == {"web", "arxiv"}
    # non-vacuous: the two sources differ on every axis the scoped read covers
    assert whole["web"]["tiers"] != whole["arxiv"]["tiers"]
    assert whole["web"]["drift"] != whole["arxiv"]["drift"]
    assert whole["web"]["coverage"] != whole["arxiv"]["coverage"]

    for source in ("web", "arxiv"):
        health = mcp_server.get_library_health(source=source)
        slice_ = whole[source]
        scoped_doctor = run_doctor(get_paths(), source=source)["custody"]
        # 1. == the scoped `doctor --source S` custody block, key for key (the tool
        #    *is* that block plus the two distilled members)
        for key in scoped_doctor:
            assert health[key] == scoped_doctor[key]
        # 2. the scoped custody view == the whole-library by_source[S] slice
        assert health["tiers"] == slice_["tiers"]
        assert _posture_from_ledger_counts(health["drift"]) == slice_["drift"]
        assert health["drift"]["coverage"] == slice_["coverage"]
        # 3. by_source collapses to the present-and-singleton {S: that same slice}
        assert health["by_source"] == {source: slice_}
        # 4. == a `status --source S` payload's custody/by_source/headline
        assert main(["status", "--source", source]) == 0
        status = json.loads(capsys.readouterr().out)
        assert custody_snapshot(run_doctor(get_paths(), source=source)) == status["custody"]
        assert health["by_source"] == status["by_source"]
        assert health["headline"] == status["headline"]
        # 5. attention null under a single-source scope (nothing to rank across)
        assert health["attention"] is None

    # teeth: the equality is not vacuous — the cross-source slice never matches the
    # scoped read, so a real desync between the scope and the by_source split fails.
    web_health = mcp_server.get_library_health(source="web")
    assert web_health["tiers"] != whole["arxiv"]["tiers"]


def test_mcp_library_health_source_scope_unknown_source_is_the_honest_empty_block(
    scrolls_home, capsys
):
    # the honest-absence gate (H167, mirroring the doctor/status/maintain
    # unknown-source gates): an unknown source holds nothing, so the scoped MCP read
    # is the empty-but-healthy block (score 100, empty by_source, null attention) —
    # never an error, and it agrees with `doctor --source ghost` key for key.
    from scrolls import mcp_server

    main(["init"])
    _seed_two_source_loss(get_paths().db_path)
    capsys.readouterr()

    health = mcp_server.get_library_health(source="ghost")
    assert health["score"] == 100
    assert health["by_source"] == {}
    assert health["attention"] is None
    scoped = run_doctor(get_paths(), source="ghost")["custody"]
    for key in scoped:
        assert health[key] == scoped[key]


def test_per_source_scope_capstone_all_four_scoped_reads_agree(scrolls_home, capsys):
    """roadmap H169 — the capstone of the per-source-scope triad.

    `doctor --source S` (H162), `status --source S` (H166), `maintain --source S`
    (H165), and MCP `get_library_health(source=S)` (H167) each scope the *whole*
    custody read to one source's held items through the **same** `run_doctor(source=)`
    pre-filter. The three CLI ties + the MCP tie are each pinned in their own test
    above (and the maintain/MCP tests already fold in their neighbours); this folds
    all four into one obvious place — the scoped-read sibling of H157's whole-library
    JSON `by_source` consolidation — so a future scoped surface has a single contract
    to satisfy. Over the multi-source loss seed every `--source S` read's custody view
    equals every other's **and** the whole-library audit's `by_source[S]` slice, the
    rendered headline is identical, and `attention` is honestly `null` on each (the
    single-source gate has nothing to rank across). Non-vacuous (the two sources
    differ on every axis) and mutation-checked (perturbing one surface's scope tally
    breaks the four-way tie).
    """
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    _seed_two_source_loss(db)
    capsys.readouterr()

    whole = run_doctor(get_paths())["custody"]["by_source"]
    assert set(whole) == {"web", "arxiv"}
    # non-vacuous: the two sources genuinely differ on every axis a scope reads
    assert whole["web"]["tiers"] != whole["arxiv"]["tiers"]
    assert whole["web"]["drift"] != whole["arxiv"]["drift"]
    assert whole["web"]["coverage"] != whole["arxiv"]["coverage"]

    for source in ("web", "arxiv"):
        slice_ = whole[source]

        # the four scoped reads, all over the same pristine state
        scoped_doctor = run_doctor(get_paths(), source=source)["custody"]
        snap = custody_snapshot(run_doctor(get_paths(), source=source))
        assert main(["status", "--source", source]) == 0
        status = json.loads(capsys.readouterr().out)
        assert main(["maintain", "--no-recheck", "--source", source]) == 0
        report = json.loads(capsys.readouterr().out)
        health = mcp_server.get_library_health(source=source)

        # 1. the snapshot-shaped pair (status/maintain carry custody_snapshot(...))
        #    are byte-identical to the distilled scoped audit and to each other.
        assert status["custody"] == report["custody"] == snap

        # 2. the raw-block MCP read equals the scoped doctor block key for key (the
        #    tool *is* that block plus the two distilled members), so the snapshot
        #    trio and the raw pair are two shapes of the one scoped audit.
        for key in scoped_doctor:
            assert health[key] == scoped_doctor[key]

        # 3. every scoped read lines up with the whole-library by_source[S] slice on
        #    the three custody axes (snapshot flattens coverage; the raw block nests
        #    it under drift — both equal the slice).
        assert snap["tiers"] == slice_["tiers"]
        assert _posture_from_ledger_counts(snap["drift"]) == slice_["drift"]
        assert snap["coverage"] == slice_["coverage"]
        assert health["tiers"] == slice_["tiers"]
        assert _posture_from_ledger_counts(health["drift"]) == slice_["drift"]
        assert health["drift"]["coverage"] == slice_["coverage"]

        # 4. by_source collapses to the present-and-singleton on every surface.
        assert (
            scoped_doctor["by_source"]
            == status["by_source"]
            == report["by_source"]
            == health["by_source"]
            == {source: slice_}
        )

        # 5. the rendered headline is the one snapshot rendered, identical on every
        #    surface that renders one (the raw doctor block carries no headline).
        headline = snapshot_headline(snap)
        assert status["headline"] == report["headline"] == health["headline"] == headline

        # 6. attention is honestly null under a single-source scope (the
        #    weakest_source gate has nothing to rank across).
        assert status["attention"] is report["attention"] is health["attention"] is None

    # teeth: the four-way equality is not vacuous — the cross-source slice never
    # matches any scoped read, and a perturbed tally never matches either, so a real
    # desync between a surface's scope and the by_source split fails here.
    other = whole["arxiv"]["tiers"]
    perturbed = {**whole["web"]["tiers"], "full": whole["web"]["tiers"]["full"] + 1}
    web_doctor = custody_snapshot(run_doctor(get_paths(), source="web"))
    web_health = mcp_server.get_library_health(source="web")
    assert main(["status", "--source", "web"]) == 0
    web_status = json.loads(capsys.readouterr().out)["custody"]
    assert main(["maintain", "--no-recheck", "--source", "web"]) == 0
    web_maintain = json.loads(capsys.readouterr().out)["custody"]
    for view in (web_doctor, web_status, web_maintain, web_health):
        assert view["tiers"] != other
        assert view["tiers"] != perturbed


def test_bundle_per_source_breakdown_converges_with_doctor_by_source(scrolls_home, capsys):
    # roadmap H141: the export-bundle briefing's `_By source:_` breakdown is a
    # derived read view of the same per-source picture doctor reports. Over the
    # multi-source seed the rendered lines equal `render_custody_by_source` over
    # *both* `doctor.custody.by_source` and `custody_counts_by_source`, appear in
    # the bundle, and the scope headline (whole-scope sum) is present too — the
    # bundle-surface counterpart of the JSON `by_source` ties above.
    from scrolls.bundle import build_bundle
    from scrolls.custody import render_custody_by_source

    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # four `web` scrolls spanning tiers/postures
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}

    # the rendered breakdown is a faithful read of doctor's map and of the tally
    expected = render_custody_by_source(by_source)
    assert expected == render_custody_by_source(custody_counts_by_source(items, verdicts))
    assert expected  # the seed is genuinely multi-source (non-vacuous)

    bundle = build_bundle(db, "topic")
    for line in expected:
        assert line in bundle
    # the scope headline (the whole-scope sum the per-source lines total) is present
    assert custody_headline(items, verdicts) in bundle


def test_context_per_source_breakdown_converges_with_doctor_by_source(scrolls_home, capsys):
    # roadmap H149: the model-facing `scrolls context` bundle carries the same
    # `_By source:_` breakdown the `export bundle` briefing (H141) and compiled
    # `index.md` (H145) do — a derived read view of doctor's per-source picture.
    # Over the multi-source seed the rendered lines equal `render_custody_by_source`
    # over *both* `doctor.custody.by_source` and `custody_counts_by_source`, appear
    # in the context bundle, and the scope headline (whole-scope sum) is present —
    # the context-surface counterpart of the bundle tie above.
    from scrolls.context import build_context
    from scrolls.custody import render_custody_by_source

    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # four `web` scrolls spanning tiers/postures
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}

    # the rendered breakdown is a faithful read of doctor's map and of the tally
    expected = render_custody_by_source(by_source)
    assert expected == render_custody_by_source(custody_counts_by_source(items, verdicts))
    assert expected  # the seed is genuinely multi-source (non-vacuous)

    bundle = build_context(db, "topic")
    for line in expected:
        assert line in bundle
    # the scope headline (the whole-scope sum the per-source lines total) is present
    assert custody_headline(items, verdicts) in bundle


def test_enrichment_by_source_converges_with_the_per_source_stale_classifications(
    scrolls_home, capsys
):
    # roadmap H135: doctor's `custody.enrichment.by_source` splits the stale-ruleset
    # count per source — the re-derivability counterpart of H121's per-source
    # coverage. Each per-source stale count must equal an independent re-derivation
    # via `is_stale_classification` grouped by source, the per-source values must
    # sum to the whole-library `enrichment.stale`, and a clean source must be
    # omitted (the offenders-only map) — the enrichment-axis sibling of the
    # tiers/drift/coverage per-source convergence above.
    from scrolls.classify import RULESET_FINGERPRINT, is_stale_classification

    main(["init"])
    db = get_paths().db_path

    def _classified(item_id, source, *, ruleset, **overrides):
        overrides.setdefault("url", f"https://example.com/{item_id}")
        return _item(
            item_id, "Topic classified", source=source, category="tutorial",
            provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                        "classified_ruleset": ruleset},
            **overrides,
        )

    # two stale web items + one stale arxiv item, and one *current* arxiv item
    # (so arxiv carries both a stale and a clean classification — the per-source
    # count must reflect only the stale one) and one current web item.
    insert_item(db, _classified("web:s1", "web", ruleset="deadbeef0000"))
    insert_item(db, _classified("web:s2", "web", ruleset="deadbeef0000"))
    insert_item(db, _classified("web:cur", "web", ruleset=RULESET_FINGERPRINT))
    insert_item(db, _classified("arxiv:s1", "arxiv", ruleset="cafe00000000",
                                url="https://arxiv.org/abs/s1"))
    insert_item(db, _classified("arxiv:cur", "arxiv", ruleset=RULESET_FINGERPRINT,
                                url="https://arxiv.org/abs/cur"))
    # a clean source: only a current classification, so it must be *omitted*
    insert_item(db, _classified("reddit:cur", "reddit", ruleset=RULESET_FINGERPRINT,
                                url="https://reddit.com/r/cur"))
    capsys.readouterr()

    items = list_items(db)
    enrichment = run_doctor(get_paths())["custody"]["enrichment"]

    # 1. each per-source count == the independent per-source re-derivation via the
    #    `classify --stale` selector (`is_stale_classification`), grouped by source.
    expected: dict[str, int] = {}
    for item in items:
        if is_stale_classification(item):
            expected[item.source] = expected.get(item.source, 0) + 1
    expected = {source: expected[source] for source in sorted(expected)}
    assert enrichment["by_source"] == expected == {"arxiv": 1, "web": 2}
    # the clean source (only a current classification) is omitted, not a 0 entry
    assert "reddit" not in enrichment["by_source"]

    # 2. the per-source counts sum to the whole-library `stale` by construction
    #    (every stale item has exactly one source — the H104/H121 sum-to-whole
    #    posture, on the enrichment axis).
    assert sum(enrichment["by_source"].values()) == enrichment["stale"] == 3

    # 3. roadmap H147: the `maintain` report surfaces the same per-source map (a
    #    faithful read via `report_enrichment_by_source`), so the scheduled worker's
    #    enrichment-by-source picture, a fresh `doctor` read, and the pure-layer read
    #    are one number — the maintain↔doctor sibling of the H127 drift `by_source`
    #    tie, on the enrichment axis. `--no-recheck` keeps the pass network-free and
    #    the ledger pristine, so the maintain audit and a fresh `doctor` agree.
    assert main(["maintain", "--no-recheck"]) == 0
    maintain_enrichment_by_source = json.loads(capsys.readouterr().out)["enrichment_by_source"]
    assert maintain_enrichment_by_source == enrichment["by_source"]
    assert maintain_enrichment_by_source == report_enrichment_by_source(
        run_doctor(get_paths())
    )


def _stored_summary(db, slug, members_hash, *, engine="kb-llm-v1"):
    from scrolls.kb import ConceptSummary, save_concept_summary

    save_concept_summary(db, ConceptSummary(
        slug=slug, display=slug.upper(), summary="How it shows up.",
        members_hash=members_hash, engine=engine, model="claude-opus-4-8",
        generated_at="2026-06-16T00:00:00+00:00"))


def _concept_member(item_id, concept, source, content_hash):
    return _item(
        item_id, item_id, source=source, url=f"https://{source}.example.com/{item_id}",
        stage="rendered", markdown_path=f"scrolls/{source}/{item_id}.md",
        extracted_text="body", raw_text="<raw>body</raw>",
        content_hash=content_hash, concepts=(concept,))


def _seed_refresh_debt_both_axes(db):
    """The combined refresh-debt seed shared by the H179/H183/H208 ties.

    Both refresh axes carry per-source stale debt over a held universe with one
    source (reddit) clean on **both**, so each axis's offenders are a strict subset
    of the held sources (the scoping rule fires) and the two axes name different
    source sets (so a test cannot pass by conflating them).

    Enrichment axis — stale classifications, each item exactly one source (so the
    map sums to the whole): ``web`` two stale + one current, ``arxiv`` one stale +
    one current, ``reddit`` a current-only (clean) source omitted from the offenders
    map. Summary axis — stale concept summaries over clusters (unclassified members,
    so the axes stay independent): ``Bm25`` spans web+arxiv (a stale Bm25 summary
    double-attributes), ``Vector`` is wikipedia-only (2 members ≥ ``MIN_MEMBERS``, so
    it survives a ``--source wikipedia`` scope), ``Clean`` spans reddit+web but is
    current → omitted.

    Returns the canonical whole-library debt maps every surface must reproduce:
    ``({"arxiv": 1, "web": 2}, {"arxiv": 1, "web": 1, "wikipedia": 1})`` — the
    ``(enrichment_by_source, summary_by_source)`` pair, carrying the H171
    non-sum-to-whole asymmetry (the summary map double-attributes Bm25).
    """
    from scrolls.classify import RULESET_FINGERPRINT
    from scrolls.kb_llm import eligible_concepts, members_hash

    def _classified(item_id, source, *, ruleset, **overrides):
        overrides.setdefault("url", f"https://example.com/{item_id}")
        return _item(
            item_id, "Topic classified", source=source, category="tutorial",
            provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                        "classified_ruleset": ruleset},
            **overrides,
        )

    insert_item(db, _classified("web:s1", "web", ruleset="deadbeef0000"))
    insert_item(db, _classified("web:s2", "web", ruleset="deadbeef0000"))
    insert_item(db, _classified("web:cur", "web", ruleset=RULESET_FINGERPRINT))
    insert_item(db, _classified("arxiv:s1", "arxiv", ruleset="cafe00000000",
                                url="https://arxiv.org/abs/s1"))
    insert_item(db, _classified("arxiv:cur", "arxiv", ruleset=RULESET_FINGERPRINT,
                                url="https://arxiv.org/abs/cur"))
    insert_item(db, _classified("reddit:cur", "reddit", ruleset=RULESET_FINGERPRINT,
                                url="https://reddit.com/r/cur"))

    insert_item(db, _concept_member("b1", "Bm25", "web", "h1"))
    insert_item(db, _concept_member("b2", "Bm25", "arxiv", "h2"))
    insert_item(db, _concept_member("v1", "Vector", "wikipedia", "h3"))
    insert_item(db, _concept_member("v2", "Vector", "wikipedia", "h4"))
    insert_item(db, _concept_member("c1", "Clean", "reddit", "h5"))
    insert_item(db, _concept_member("c2", "Clean", "web", "h6"))
    _stored_summary(db, "bm25", "stale-old-1")
    _stored_summary(db, "vector", "stale-old-2")
    eligible = eligible_concepts(list_items(db))
    _stored_summary(db, "clean", members_hash(eligible["clean"]["items"]))

    return {"arxiv": 1, "web": 2}, {"arxiv": 1, "web": 1, "wikipedia": 1}


@pytest.fixture
def fake_summary_llm(monkeypatch):
    """Canned concept-summary completer, so `kb --stale` runs network-free.

    The summary-axis refresh actually calls the model; a local copy of
    `test_kb.py`'s fixture keeps the convergence test offline (mirrors the
    `cli.live_recapture` seam every other custody flow scripts behind).
    """
    import scrolls.kb_llm as kb_llm

    calls = []

    def complete(system, user, model):
        calls.append({"system": system, "user": user, "model": model})
        return json.dumps({"summary": "How this concept shows up across scrolls."})

    monkeypatch.setattr(kb_llm, "_anthropic_complete", complete)
    return calls


def test_summaries_by_source_converges_with_the_per_source_stale_summaries(
    scrolls_home, capsys
):
    # roadmap H171: doctor's `custody.summaries.by_source` splits the stale-summary
    # count per source — the summary-axis sibling of H135's `enrichment.by_source`.
    # Unlike the enrichment/drift maps, a concept summary spans a *cluster* whose
    # members can come from several sources and the stored fingerprint records only
    # the digest (not which member moved), so a stale summary is attributed to
    # *every* source among its live members and the map need NOT sum to `stale`
    # (the documented H171 asymmetry). Pin it against an independent re-derivation
    # via the `kb --stale` selector (`is_stale_summary`), grouped by source — the
    # convergence the future `kb --stale --source` (H172) will act on.
    from scrolls.kb import load_concept_summaries
    from scrolls.kb_llm import eligible_concepts, is_stale_summary, members_hash

    main(["init"])
    db = get_paths().db_path

    # Bm25: a stale summary over a web + arxiv cluster → attributes to BOTH.
    insert_item(db, _concept_member("b1", "Bm25", "web", "h1"))
    insert_item(db, _concept_member("b2", "Bm25", "arxiv", "h2"))
    # Vector: a stale summary over a web-only cluster → attributes to web.
    insert_item(db, _concept_member("v1", "Vector", "web", "h3"))
    insert_item(db, _concept_member("v2", "Vector", "web", "h4"))
    # Clean: a *current* summary over a reddit + web cluster → no stale debt, so
    # both reddit and web's clean participation is omitted from the map.
    insert_item(db, _concept_member("c1", "Clean", "reddit", "h5"))
    insert_item(db, _concept_member("c2", "Clean", "web", "h6"))

    _stored_summary(db, "bm25", "stale-old-1")
    _stored_summary(db, "vector", "stale-old-2")
    eligible = eligible_concepts(list_items(db))
    _stored_summary(db, "clean", members_hash(eligible["clean"]["items"]))

    summaries = run_doctor(get_paths())["custody"]["summaries"]

    # 1. each per-source count == an independent per-source re-derivation via the
    #    `kb --stale` selector (`is_stale_summary`), grouped by every source among
    #    a stale concept's live members.
    stored = load_concept_summaries(db)
    expected: dict[str, int] = {}
    for slug, entry in eligible.items():
        if is_stale_summary(stored.get(slug), members_hash(entry["items"])):
            for source in {item.source for item in entry["items"]}:
                expected[source] = expected.get(source, 0) + 1
    expected = {source: expected[source] for source in sorted(expected)}
    assert summaries["by_source"] == expected == {"arxiv": 1, "web": 2}

    # 2. the clean concept's sources (reddit, and web's clean participation) carry
    #    no stale debt — reddit, which appears only in the current cluster, is
    #    omitted entirely (the offenders-only map).
    assert "reddit" not in summaries["by_source"]

    # 3. the H171 asymmetry: the Bm25 summary is double-attributed (web + arxiv),
    #    so the per-source values sum to MORE than `stale` — non-vacuous, and the
    #    reason this map deliberately does not claim the sum-to-whole convergence
    #    the drift/enrichment maps rest on.
    assert summaries["stale"] == 2
    assert sum(summaries["by_source"].values()) == 3 > summaries["stale"]

    # 4. roadmap H175: the `maintain` report surfaces the same per-source map (a
    #    faithful read via `report_summary_by_source`), so the scheduled worker's
    #    summary-by-source picture, a fresh `doctor` read, and the pure-layer read are
    #    one map — the maintain↔doctor sibling of the H147 enrichment tie (step 3 of
    #    `test_enrichment_by_source_converges_…`), on the summary axis. Because the
    #    map need not sum to the whole (the H171 asymmetry above), this tie is
    #    faithful-read *equality*, not a sum-to-whole check. `--no-recheck` keeps the
    #    pass network-free and the ledger pristine, so the maintain audit and a fresh
    #    `doctor` agree. (This fixture's rendered members carry markdown_paths but write
    #    no scroll files, so the audit flags `missing_scrolls` and the pass exits 1 — a
    #    fixture artifact on the structural axis, orthogonal to the summary tie below.)
    capsys.readouterr()  # drain the `init` output buffered since the start
    main(["maintain", "--no-recheck"])
    maintain_summary_by_source = json.loads(capsys.readouterr().out)["summary_by_source"]
    assert maintain_summary_by_source == summaries["by_source"]
    assert maintain_summary_by_source == report_summary_by_source(
        run_doctor(get_paths())
    )


def test_kb_stale_source_refreshes_exactly_the_doctor_per_source_summaries(
    scrolls_home, fake_summary_llm, capsys
):
    # roadmap H176: `kb --stale --source <S>` regenerates exactly the stale concept
    # summaries source <S> participates in — the offenders doctor reports in
    # `custody.summaries.by_source[<S>]` (H171). The summary-axis sibling of H154's
    # enrichment-axis `classify --stale --source` convergence above; together they
    # complete the per-source *refresh* convergence on BOTH enrichment axes in this
    # one suite (the per-source *report* ties live just above for both axes).
    #
    # The load-bearing summary-axis difference (vs the classification axis, where each
    # item has one source): a summary spans a *cluster* whose members come from several
    # sources and the stored fingerprint records only the digest, not which member
    # moved — so a stale summary is "stale for" EVERY source it spans, and refreshing
    # under one of a cluster's sources clears ALL of them (the H171 attribution).
    from scrolls.kb import load_concept_summaries
    from scrolls.kb_llm import (
        _summary_targets,
        eligible_concepts,
        members_hash,
    )

    main(["init"])
    db = get_paths().db_path

    # Bm25: a stale summary over a web + arxiv cluster → attributes to BOTH.
    insert_item(db, _concept_member("b1", "Bm25", "web", "h1"))
    insert_item(db, _concept_member("b2", "Bm25", "arxiv", "h2"))
    # Vector: a stale summary over a wikipedia-only cluster → attributes to wikipedia
    #   (a *different*, single-source concept, so refreshing Bm25 must leave it whole).
    insert_item(db, _concept_member("v1", "Vector", "wikipedia", "h3"))
    insert_item(db, _concept_member("v2", "Vector", "wikipedia", "h4"))
    # Clean: a *current* summary over a reddit + web cluster → no stale debt.
    insert_item(db, _concept_member("c1", "Clean", "reddit", "h5"))
    insert_item(db, _concept_member("c2", "Clean", "web", "h6"))

    _stored_summary(db, "bm25", "stale-old-1")
    _stored_summary(db, "vector", "stale-old-2")
    eligible = eligible_concepts(list_items(db))
    _stored_summary(db, "clean", members_hash(eligible["clean"]["items"]))
    capsys.readouterr()

    # the report side: doctor's per-source stale-summary offenders. Bm25 double-counts
    # (web + arxiv), Vector counts wikipedia; the current Clean concept is omitted.
    by_source = run_doctor(get_paths())["custody"]["summaries"]["by_source"]
    assert by_source == {"arxiv": 1, "web": 1, "wikipedia": 1}

    # 1. the act-side pool == the report-side count, per source. `_summary_targets`
    #    (the `kb --stale --source S` selector) narrows the stale set to the concepts
    #    S participates in; its size equals doctor's per-source number by construction
    #    (the same `is_stale_summary` predicate, the H27/H154 signal-clears tie).
    stored = load_concept_summaries(db)
    targets_by_source = {
        source: set(_summary_targets(eligible, stored, stale_only=True, source=source))
        for source in by_source
    }
    for source, count in by_source.items():
        assert len(targets_by_source[source]) == count
    #    arxiv touches only the multi-source Bm25; web likewise (it shares that cluster);
    #    wikipedia touches only its own single-source Vector.
    assert targets_by_source == {
        "arxiv": {"bm25"},
        "web": {"bm25"},
        "wikipedia": {"vector"},
    }

    # 2. the CLI regenerates exactly that source's offenders. `--source arxiv` touches
    #    only Bm25 — NOT Vector, even though Vector is also stale: the scope genuinely
    #    narrows the refresh (the mutation check — were the scope ignored, Vector would
    #    refresh too and step 3's `wikipedia` entry would wrongly clear).
    assert main(["kb", "--stale", "--source", "arxiv"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {result["slug"] for result in payload["results"]} == targets_by_source["arxiv"]
    assert payload["generated"] == by_source["arxiv"] == 1

    # 3. refreshing under arxiv clears arxiv's entry from the map AND — because Bm25 is
    #    a multi-source cluster — its `web` attribution too (clears ALL the cluster's
    #    sources, the H171/H172 attribution); the unrelated single-source `wikipedia`
    #    concept (Vector) is left whole.
    after = run_doctor(get_paths())["custody"]["summaries"]["by_source"]
    assert after == {"wikipedia": 1}


def test_classify_stale_source_refreshes_exactly_the_doctor_per_source_count(
    scrolls_home, capsys
):
    # roadmap H154: `classify --stale --source <S>` refreshes exactly the stale
    # classifications of one source — the slice doctor reports in
    # `custody.enrichment.by_source[S]`. The per-source act↔report convergence
    # (the enrichment-axis sibling of H125's per-source verify): the count it
    # refreshes equals doctor's per-source number and the pure `stale_classifications`
    # selector, and refreshing clears that source's entry from the offenders-only map.
    from scrolls.classify import RULESET_FINGERPRINT, stale_classifications

    main(["init"])
    db = get_paths().db_path

    def _stale(item_id, source, *, ruleset="deadbeef0000"):
        # source defaults the live ruleset still matches (wikipedia → reference,
        # arxiv → paper), so a refresh restamps `current` rather than dropping to
        # `unmatched` — the refresh actually clears the stale signal.
        return _item(
            item_id, "Topic classified", source=source, stage="rendered",
            url=f"https://example.com/{item_id}", category=None,
            provenance={"classified_by": "rules-v1", "classified_basis": "curated-source",
                        "classified_ruleset": ruleset},
        )

    insert_item(db, _stale("wikipedia:SQLite", "wikipedia"))
    insert_item(db, _stale("wikipedia:Redis", "wikipedia"))
    insert_item(db, _stale("arxiv:s1", "arxiv", ruleset="cafe00000000"))
    # a *current* arxiv classification: arxiv carries both a stale and a clean
    # one, so the per-source count must reflect only the stale member.
    insert_item(db, _stale("arxiv:cur", "arxiv", ruleset=RULESET_FINGERPRINT))
    capsys.readouterr()

    by_source = run_doctor(get_paths())["custody"]["enrichment"]["by_source"]
    assert by_source == {"arxiv": 1, "wikipedia": 2}

    # 1. the pure selector re-derives each per-source count (the predicate doctor
    #    builds its map from), so the act-side pool == the report-side count.
    items = list_items(db)
    for source, count in by_source.items():
        assert len(stale_classifications(items, source=source)) == count

    # 2. the CLI refreshes exactly that many for the chosen source ...
    assert main(["classify", "--stale", "--source", "wikipedia"]) == 0
    assert json.loads(capsys.readouterr().out)["classified"] == by_source["wikipedia"]

    # 3. ... and that source drops from the offenders-only map, the other intact.
    after = run_doctor(get_paths())["custody"]["enrichment"]["by_source"]
    assert after == {"arxiv": 1}


def test_recheck_coverage_converges_across_doctor_and_maintain(scrolls_home, capsys):
    # roadmap H113: the recheck `coverage` figure (`{verified, total}` over the
    # verifiable held set) reads the same on the standalone audit (`doctor`) and
    # the maintenance surface (`maintain`), both delegating to the one shared
    # `custody.recheck_coverage` primitive — so the audit reports coverage as a
    # fraction at parity with maintain (H109), and `verified` ≡ the block's own
    # `checked` count by construction.
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)
    capsys.readouterr()

    # the canonical figure: of the hash-bearing held items, how many carry a verdict
    hash_bearing = [item for item in list_items(db) if item.content_hash]
    canonical = recheck_coverage(hash_bearing, latest_events(db))
    assert canonical == {"verified": 2, "total": 2}  # full1+full2 verified, both hash-bearing

    # doctor — the coverage member on the drift block, with `verified` ≡ `checked`
    drift = run_doctor(get_paths())["custody"]["drift"]
    assert drift["coverage"] == canonical
    assert drift["coverage"]["verified"] == drift["checked"]

    # maintain --no-recheck — the same figure on the recheck report (a pure read,
    # no live edge), so the scheduled worker and the standalone audit agree
    assert main(["maintain", "--no-recheck"]) == 0
    recheck = json.loads(capsys.readouterr().out)["recheck"]
    assert recheck["coverage"] == canonical


def test_maintain_by_source_converges_with_doctor_by_source(scrolls_home, capsys):
    # roadmap H127: H123 threads `doctor`'s `custody.by_source` map into the
    # `maintain` report (the report member is a pure read of the audit's map) and
    # *claims* the two agree, but that tie is pinned only obliquely in
    # `test_maintain.py` (the maintain member == a *re-run* doctor's map). Pin it as
    # a first-class entry here, the home for per-source convergence (beside the H104
    # `test_doctor_by_source_converges_with_the_per_source_tally_and_facets`): over
    # the multi-source fidelity/drift seed, a `maintain --no-recheck` pass's report
    # `by_source` equals `doctor`'s `custody.by_source` for the *same* post-maintenance
    # library **and** `custody_counts_by_source` over the held items **and** (per
    # source) `facets fidelity`/`drift --source <name>` — so the scheduled worker's
    # per-source picture, the standalone audit, the canonical tally, and the browse
    # facets are one number, asserted in one place. `--no-recheck` keeps the pass
    # network-free and the ledger pristine, so the maintain audit and a fresh `doctor`
    # read the identical state. The per-source-maintenance sibling of how H101 pinned
    # the `stats.custody` family and H111 the stale-recheck convergence.
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # four `web` scrolls spanning the tiers/postures
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # the maintain report's per-source breakdown — a faithful read of its own audit
    assert main(["maintain", "--no-recheck"]) == 0
    maintain_by_source = json.loads(capsys.readouterr().out)["by_source"]
    assert set(maintain_by_source) == {"web", "arxiv"}

    # 1. == doctor's own `custody.by_source` over the same post-maintenance library
    doctor_by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert maintain_by_source == doctor_by_source

    # 2. == the canonical `custody_counts_by_source` tally over the held items
    items = list_items(db)
    verdicts = latest_events(db)
    assert maintain_by_source == custody_counts_by_source(items, verdicts)

    # 3. per source, the tiers/drift == `facets fidelity`/`drift --source <name>`
    #    (the browse aggregate scoped to that source)
    for source in ("web", "arxiv"):
        fidelity = _facet_map(
            compute_facets(db, field="fidelity", source=source)["facets"]["fidelity"])
        drift = _facet_map(
            compute_facets(db, field="drift", source=source)["facets"]["drift"])
        assert fidelity == _nonzero(maintain_by_source[source]["tiers"])
        assert drift == _nonzero(maintain_by_source[source]["drift"])


def _max_loss_source(by_source):
    """The source `weakest_source` flags, computed straight off doctor's per-source
    map: the most `drifted` + `rotted` loss, tie-broken by most `reference`-only then
    name — the documented ranking key (roadmap H119), re-derived from doctor's map so
    the convergence is to the *audit's* picture, not maintain's own.
    """
    def _loss(tally):
        drift = tally["drift"]
        return drift["drifted"] + drift["rotted"]

    return min(
        by_source,
        key=lambda s: (-_loss(by_source[s]), -by_source[s]["tiers"]["reference"], s),
    )


def test_maintain_attention_converges_with_doctors_max_loss_source(scrolls_home, capsys):
    # roadmap H129: H119 distils `maintain`'s `attention` from the per-source
    # `by_source` map and *claims* it flags the source doctor's audit would call
    # weakest; H127 pins `maintain by_source ≡ doctor by_source`, but the
    # *distillation* (which source `weakest_source` picks) is pinned only in
    # `test_maintain.py` against the report's own map. Pin it as a first-class entry
    # here, beside H127: a `maintain --no-recheck` pass's `attention.source` equals
    # the source maximizing `drifted + rotted` in `doctor`'s `custody.by_source`
    # (with the documented `reference`-then-name tie-break) — so the scheduled
    # worker's single-source flag can never disagree with the standalone audit's
    # per-source map. The `attention`-axis sibling of H127 (`by_source`).
    main(["init"])
    db = get_paths().db_path
    # web carries the only actionable loss (web:full2 drifted); arxiv is clean,
    # so `web` is the unambiguous max-loss source the flag must name.
    _seed_mixed_custody(db)
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    assert main(["maintain", "--no-recheck"]) == 0
    attention = json.loads(capsys.readouterr().out)["attention"]

    by_source = run_doctor(get_paths())["custody"]["by_source"]
    # sanity: the seed makes `web` the unambiguous max-loss source (1 drifted vs 0)
    assert by_source["web"]["drift"]["drifted"] == 1
    assert by_source["arxiv"]["drift"]["drifted"] == 0
    assert by_source["arxiv"]["drift"]["rotted"] == 0

    # the flag names exactly doctor's max-loss source (a literal pick, not a
    # tautology — `weakest_source` ranking by *least* loss would name `arxiv`)
    assert attention is not None
    assert attention["source"] == _max_loss_source(by_source) == "web"
    # and the flagged source's own tally rides along, == doctor's entry for it
    assert attention["tiers"] == by_source["web"]["tiers"]
    assert attention["drift"] == by_source["web"]["drift"]
    # roadmap H153: the per-source recheck coverage rides the flag too — == doctor's
    # `custody.by_source[<source>].coverage` for the flagged source by construction
    # (the same tally `weakest_source` distils), so the flag names the source, the
    # loss, the act, *and* how much of the weak source is even checked, in one place.
    assert attention["coverage"] == by_source["web"]["coverage"]
    # roadmap H137: the recheck command names exactly doctor's max-loss source —
    # so the act `maintain` points at re-verifies the source the audit flagged.
    assert attention["command"] == f"scrolls verify --source {attention['source']}"


def test_maintain_attention_is_null_when_no_source_carries_loss(scrolls_home, capsys):
    # the honest-null gate (roadmap H129/H119): with ≥2 sources but no `drifted`/
    # `rotted` item anywhere, `attention` is `null` — exactly when doctor's
    # per-source map carries zero actionable loss across every source. Reference-only
    # captures and never-checked items are the normal posture, never a trigger on
    # their own — so a clean multi-source library flags nothing, converging with the
    # audit that would.
    main(["init"])
    db = get_paths().db_path
    # web: one verified + one never-checked; arxiv: one never-checked — no drift/rot
    insert_item(db, _item("web:1", "Topic one", extracted_text="b1",
                          raw_text="<raw>1</raw>", content_hash="sha256:1"))
    insert_item(db, _item("web:2", "Topic two", extracted_text="b2",
                          raw_text="<raw>2</raw>", content_hash="sha256:2"))
    insert_item(db, _item("arxiv:1", "Topic arxiv", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="a",
                          raw_text="<raw>a</raw>", content_hash="sha256:a"))
    record_events(db, [
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),
        # web:2, arxiv:1 left unverified
    ])
    capsys.readouterr()

    assert main(["maintain", "--no-recheck"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None

    # converges with doctor: no source in the per-source map carries any loss
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}  # ≥2 sources, so the gate is the loss, not the count
    assert all(
        tally["drift"]["drifted"] + tally["drift"]["rotted"] == 0
        for tally in by_source.values()
    )


def test_status_by_source_converges_with_maintain_and_doctor(scrolls_home, capsys):
    # roadmap H133: `scrolls status` now carries the per-source custody breakdown
    # (`by_source`) — the status-surface counterpart of the `maintain` report member
    # (H123). It is a faithful read of the same `run_doctor` map (`report_by_source`),
    # so it *claims* to agree with the standalone audit and the scheduled worker's
    # report. Pin it as a first-class entry beside H127's `maintain by_source ≡
    # doctor by_source`: over the multi-source fidelity/drift seed, `status`'s
    # `by_source` equals `maintain --no-recheck`'s `by_source`, `doctor`'s
    # `custody.by_source`, and `custody_counts_by_source` over the held items — so the
    # three surfaces a human/worker reads the per-source picture from are one number.
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # four `web` scrolls spanning the tiers/postures
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # status's per-source breakdown — a faithful read of the audit it already makes
    assert main(["status"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    status_by_source = status_payload["by_source"]
    assert set(status_by_source) == {"web", "arxiv"}

    # 1. == doctor's own `custody.by_source` over the same library
    doctor_by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert status_by_source == doctor_by_source
    # and == report_by_source over that report (the primitive status threads)
    assert status_by_source == report_by_source(run_doctor(get_paths()))

    # 2. == the `maintain --no-recheck` report's `by_source` (the scheduled sibling,
    #    H123) — `--no-recheck` keeps the ledger pristine so both read one state
    assert main(["maintain", "--no-recheck"]) == 0
    maintain_by_source = json.loads(capsys.readouterr().out)["by_source"]
    assert status_by_source == maintain_by_source

    # 3. == the canonical `custody_counts_by_source` tally over the held items
    items = list_items(db)
    verdicts = latest_events(db)
    assert status_by_source == custody_counts_by_source(items, verdicts)

    # 4. the per-source tallies sum to status's own `custody` block beside them
    #    (H104 sum-to-whole, per source — status's two members can never disagree)
    whole = custody_counts(items, verdicts)
    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in status_by_source.values():
        for tier, n in counts["tiers"].items():
            summed_tiers[tier] += n
        for posture, n in counts["drift"].items():
            summed_drift[posture] += n
    assert summed_tiers == whole["tiers"] == status_payload["custody"]["tiers"]
    assert summed_drift == whole["drift"]


def test_status_refresh_debt_by_source_converges_with_maintain_and_doctor(
    scrolls_home, capsys, fake_summary_llm
):
    # roadmap H179: `status` carries the per-source *refresh-debt* maps
    # `enrichment_by_source` (stale classifications) and `summary_by_source` (stale
    # concept summaries) — the read-surface counterpart (H177) of the `maintain`
    # report members (H147/H175), each a faithful read of the same `run_doctor`
    # audit via `report_enrichment_by_source` / `report_summary_by_source`. The drift
    # `by_source` tie above (H133) pins the fidelity/posture axis across
    # status≡maintain≡doctor; this folds in the **refresh-debt axes** beside it, so
    # "which source to refresh" reads one number on every surface an agent/worker
    # asks. Both the whole-library tie and the `--source`-scoped slice are pinned,
    # carrying the two axes' opposite sum-to-whole postures (enrichment sums to the
    # whole; a multi-source stale summary double-attributes, so summaries need not).
    from scrolls.classify import is_stale_classification
    from scrolls.kb import load_concept_summaries
    from scrolls.kb_llm import eligible_concepts, is_stale_summary, members_hash

    main(["init"])
    db = get_paths().db_path
    seed_enrichment, seed_summary = _seed_refresh_debt_both_axes(db)
    capsys.readouterr()

    # The three surfaces, each reading the same `run_doctor` audit. `maintain` may
    # exit 1 on the concept fixture's `missing_scrolls` (markdown_paths with no files,
    # a structural-axis artifact orthogonal to the refresh-debt maps below) but still
    # prints its report; `status` always exits 0.
    def status_maps(source=None):
        scope = ["--source", source] if source else []
        assert main(["status", *scope]) == 0
        payload = json.loads(capsys.readouterr().out)
        return payload["enrichment_by_source"], payload["summary_by_source"]

    def maintain_maps(source=None):
        scope = ["--source", source] if source else []
        main(["maintain", "--no-recheck", *scope])
        report = json.loads(capsys.readouterr().out)
        return report["enrichment_by_source"], report["summary_by_source"]

    def doctor_maps(source=None):
        custody = run_doctor(get_paths(), source=source)["custody"]
        return custody["enrichment"]["by_source"], custody["summaries"]["by_source"]

    # --- whole-library three-way tie ------------------------------------------
    # An independent re-derivation of each map from its own selector, grouped by
    # source — the canonical picture status/maintain/doctor must all reproduce.
    items = list_items(db)
    expected_enrichment: dict[str, int] = {}
    for item in items:
        if is_stale_classification(item):
            expected_enrichment[item.source] = expected_enrichment.get(item.source, 0) + 1
    expected_enrichment = {s: expected_enrichment[s] for s in sorted(expected_enrichment)}

    stored = load_concept_summaries(db)
    expected_summary: dict[str, int] = {}
    for slug, entry in eligible_concepts(items).items():
        if is_stale_summary(stored.get(slug), members_hash(entry["items"])):
            for src in {member.source for member in entry["items"]}:
                expected_summary[src] = expected_summary.get(src, 0) + 1
    expected_summary = {s: expected_summary[s] for s in sorted(expected_summary)}

    # non-vacuous: both axes name ≥2 sources, and the two axes differ (so the test
    # cannot pass by conflating them). The independent re-derivation must also equal
    # the canonical maps the shared seed helper promises (its return value).
    assert expected_enrichment == seed_enrichment == {"arxiv": 1, "web": 2}
    assert expected_summary == seed_summary == {"arxiv": 1, "web": 1, "wikipedia": 1}

    status_enrichment, status_summary = status_maps()
    maintain_enrichment, maintain_summary = maintain_maps()
    doctor_enrichment, doctor_summary = doctor_maps()

    # status ≡ maintain ≡ doctor ≡ the independent re-derivation, on BOTH axes.
    assert status_enrichment == maintain_enrichment == doctor_enrichment == expected_enrichment
    assert status_summary == maintain_summary == doctor_summary == expected_summary

    # the opposite sum-to-whole postures (H171 asymmetry): enrichment sums to the
    # whole-library stale count (each item one source); a multi-source stale summary
    # double-attributes, so the summary map sums to MORE than its `stale` count.
    enrichment_block = run_doctor(get_paths())["custody"]["enrichment"]
    summaries_block = run_doctor(get_paths())["custody"]["summaries"]
    assert sum(status_enrichment.values()) == enrichment_block["stale"] == 3
    assert sum(status_summary.values()) == 3 > summaries_block["stale"] == 2

    # --- per-source scoped three-way tie --------------------------------------
    # Each `--source S` read scopes the *whole* audit to S's held items through the
    # same `run_doctor(source=)` pre-filter, so the three scoped surfaces agree on
    # both maps by construction — pinned here as a contract over a real seed.
    for source in ("web", "arxiv", "reddit", "wikipedia"):
        s_enrichment, s_summary = status_maps(source)
        m_enrichment, m_summary = maintain_maps(source)
        d_enrichment, d_summary = doctor_maps(source)
        assert s_enrichment == m_enrichment == d_enrichment
        assert s_summary == m_summary == d_summary
        # the scoped enrichment map collapses cleanly to S's whole-library debt
        # (each classified item has exactly one source — no cluster to fracture).
        assert d_enrichment == (
            {source: expected_enrichment[source]} if source in expected_enrichment else {}
        )

    # the non-vacuous scoped slices, and the load-bearing cluster subtlety: a
    # single-source stale cluster survives its own `--source` scope, but a
    # multi-source one fractures below MIN_MEMBERS and reads as the honest empty map.
    assert status_maps("web")[0] == {"web": 2}            # enrichment slice, non-empty
    assert status_maps("wikipedia")[1] == {"wikipedia": 1}  # Vector survives the scope
    assert status_maps("web")[1] == {}                    # Bm25's lone web member < MIN_MEMBERS
    assert status_maps("arxiv")[1] == {}                  # Bm25's lone arxiv member < MIN_MEMBERS

    # --- mutation check: refreshing one source moves all three surfaces together --
    # `kb --stale --source wikipedia` (the documented summary-axis refresh, H172/H176;
    # offline via `fake_summary_llm`) regenerates the wikipedia-only Vector summary,
    # clearing wikipedia's stale-summary debt. The refresh-debt maps on status,
    # maintain, AND doctor must all drop wikipedia's `summary_by_source` entry in
    # lockstep, while the *enrichment* axis is untouched (the summary refresh never
    # re-classifies) — proving the convergence is causal, not a coincidence of the
    # seed, and that the two refresh axes move independently.
    assert main(["kb", "--stale", "--source", "wikipedia"]) == 0
    capsys.readouterr()
    after_status = status_maps()
    after_maintain = maintain_maps()
    after_doctor = doctor_maps()
    assert after_status[1] == after_maintain[1] == after_doctor[1] == {"arxiv": 1, "web": 1}
    assert after_status[0] == after_maintain[0] == after_doctor[0] == expected_enrichment


def test_mcp_library_health_refresh_debt_by_source_converges_with_status_and_doctor(
    scrolls_home, capsys, fake_summary_llm
):
    # roadmap H208: the agent-facing MCP read joins the H179 refresh-debt-map tie.
    # H179 pinned the *flat* maps (`enrichment_by_source`/`summary_by_source`) ≡
    # across CLI `status`≡`maintain`≡`doctor`; `get_library_health` deliberately keeps
    # the *nested* form (`enrichment.by_source`/`summaries.by_source`) — being exactly
    # `run_doctor`'s custody block, not a flattened projection (the H180 flat≡nested
    # posture). H180 already ties the MCP nested map ≡ CLI `status` flat map over a
    # *simpler* seed (`test_get_library_health_refresh_debt_equals_cli_status_flat_maps`,
    # `…_source_scopes_the_refresh_debt`); this folds the nested MCP read into the
    # **full H179 picture** over the SAME combined seed — a three-way tie (MCP ≡
    # `status` ≡ `doctor`) on BOTH axes, whole-library AND scoped, carrying the H171
    # non-sum-to-whole asymmetry and the single-source-cluster scope-collapse subtlety,
    # plus a causal mutation check. So "which source to refresh" reads one number on
    # the agent's MCP read just as it does on every CLI surface.
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    expected_enrichment, expected_summary = _seed_refresh_debt_both_axes(db)
    capsys.readouterr()

    # the three read surfaces, each a faithful read of the same `run_doctor` audit.
    # `status` prints + reads capsys; the MCP tool and `run_doctor` return dicts and
    # touch neither, so capsys carries only the `status` payload at read time.
    def mcp_maps(source=None):
        health = mcp_server.get_library_health(source=source)
        return health["enrichment"]["by_source"], health["summaries"]["by_source"]

    def status_maps(source=None):
        scope = ["--source", source] if source else []
        assert main(["status", *scope]) == 0
        payload = json.loads(capsys.readouterr().out)
        return payload["enrichment_by_source"], payload["summary_by_source"]

    def doctor_maps(source=None):
        custody = run_doctor(get_paths(), source=source)["custody"]
        return custody["enrichment"]["by_source"], custody["summaries"]["by_source"]

    # --- whole-library three-way tie: MCP ≡ status ≡ doctor, BOTH axes ------------
    # non-vacuous: both axes name ≥2 sources and the two axes differ, so the tie
    # cannot pass by conflating the maps.
    assert expected_enrichment == {"arxiv": 1, "web": 2}
    assert expected_summary == {"arxiv": 1, "web": 1, "wikipedia": 1}

    mcp_enrichment, mcp_summary = mcp_maps()
    status_enrichment, status_summary = status_maps()
    doctor_enrichment, doctor_summary = doctor_maps()
    assert mcp_enrichment == status_enrichment == doctor_enrichment == expected_enrichment
    assert mcp_summary == status_summary == doctor_summary == expected_summary

    # the H171 non-sum-to-whole asymmetry survives on the nested MCP read: enrichment
    # sums to the whole-library `stale` (each item one source); a multi-source stale
    # summary (Bm25 spans web+arxiv) double-attributes, so the summary map sums to MORE
    # than its `stale` count. The MCP twin carries the fuller block (the `stale` scalar
    # the flat CLI map drops) — read it off the same audit and tie the asymmetry here.
    health = mcp_server.get_library_health()
    assert sum(mcp_enrichment.values()) == health["enrichment"]["stale"] == 3
    assert sum(mcp_summary.values()) == 3 > health["summaries"]["stale"] == 2

    # --- per-source scoped three-way tie -----------------------------------------
    # `get_library_health(source=S)` scopes the *whole* read through the same
    # `run_doctor(source=)` pre-filter `status --source`/`doctor --source` use, so the
    # three scoped surfaces agree on both nested/flat maps by construction.
    for source in ("web", "arxiv", "reddit", "wikipedia"):
        m_enrichment, m_summary = mcp_maps(source)
        s_enrichment, s_summary = status_maps(source)
        d_enrichment, d_summary = doctor_maps(source)
        assert m_enrichment == s_enrichment == d_enrichment
        assert m_summary == s_summary == d_summary
        # the scoped enrichment map collapses cleanly to S's whole-library debt
        # (each classified item has exactly one source — no cluster to fracture).
        assert m_enrichment == (
            {source: expected_enrichment[source]} if source in expected_enrichment else {}
        )

    # the load-bearing cluster subtlety reads identically over MCP: a single-source
    # stale cluster survives its own `--source` scope, but a multi-source one fractures
    # below MIN_MEMBERS and reads as the honest empty map.
    assert mcp_maps("web")[0] == {"web": 2}              # enrichment slice, non-empty
    assert mcp_maps("wikipedia")[1] == {"wikipedia": 1}  # Vector (2 members) survives
    assert mcp_maps("web")[1] == {}                      # Bm25's lone web member < MIN_MEMBERS
    assert mcp_maps("arxiv")[1] == {}                    # Bm25's lone arxiv member < MIN_MEMBERS

    # --- mutation check: refreshing one source moves all three surfaces together --
    # `kb --stale --source wikipedia` (the documented summary-axis refresh, H172/H176;
    # offline via `fake_summary_llm`) regenerates the wikipedia-only Vector summary,
    # clearing wikipedia's stale-summary debt. The nested MCP map, status's flat map,
    # AND doctor must all drop wikipedia's `summaries.by_source` entry in lockstep,
    # while the *enrichment* axis stays put (a summary refresh never re-classifies) —
    # proving the convergence is causal, not a seed coincidence, and that the two
    # refresh axes move independently over MCP too.
    assert main(["kb", "--stale", "--source", "wikipedia"]) == 0
    capsys.readouterr()
    after_mcp = mcp_maps()
    after_status = status_maps()
    after_doctor = doctor_maps()
    assert after_mcp[1] == after_status[1] == after_doctor[1] == {"arxiv": 1, "web": 1}
    assert after_mcp[0] == after_status[0] == after_doctor[0] == expected_enrichment


def _scoped_refresh_sources(suggested, command):
    """The sources named by the scoped ``<command> --source <S>`` suggestions (H181).

    `suggest_repairs` emits one ``{command, addresses}`` entry per offending source
    when a refresh axis's debt is confined; this pulls the ``<S>`` out of each scoped
    command for the given base command, so a test can compare the *set of sources the
    suggestion names* to the debt map's keys. The un-scoped whole-library command
    (`<command>` with no trailing `` --source ``) is deliberately excluded.
    """
    prefix = f"{command} --source "
    return {
        entry["command"][len(prefix):]
        for entry in suggested
        if entry["command"].startswith(prefix)
    }


def _suggests_whole_library(suggested, command):
    """Whether the un-scoped whole-library ``<command>`` suggestion is present."""
    return any(entry["command"] == command for entry in suggested)


def test_maintain_scoped_suggestions_name_exactly_the_refresh_debt_sources(
    scrolls_home, capsys, fake_summary_llm
):
    # roadmap H183: when a refresh axis's stale debt is confined to a strict subset
    # of the held sources, `maintain`'s `suggested` block names the minimal scoped
    # act per offending source — `classify --stale --source <S>` (H154) /
    # `kb --stale --source <S>` (H172) — instead of the whole-library sweep (H181).
    # H181 pins that *behaviour* in test_maintain.py; this folds the **convergence**
    # into the suite beside the H179 refresh-debt-map tie: the set of sources the
    # scoped suggestions name ≡ the keys of the very debt maps the same report carries
    # (`enrichment_by_source` / `summary_by_source`), which H179 already pins ≡
    # `doctor`'s `custody.{enrichment,summaries}.by_source`. So the *act* a worker is
    # told to run targets exactly the sources the *report* says carry debt — the
    # action-pointer sibling of H179's read convergence, on the per-source axis.
    main(["init"])
    db = get_paths().db_path
    # The H179 seed: both refresh axes, with one held source (reddit) clean on BOTH
    # so each axis's offenders are a *strict* subset of the held universe and the
    # scoping rule fires.
    expected_enrichment, expected_summary = _seed_refresh_debt_both_axes(db)
    capsys.readouterr()

    # the whole-library maintain pass (`source=None` → H181 strict-subset rule). It
    # may exit 1 on the concept fixture's `missing_scrolls` (markdown_paths with no
    # files, a structural artifact orthogonal to the refresh-debt suggestions) but
    # still prints its report.
    main(["maintain", "--no-recheck"])
    report = json.loads(capsys.readouterr().out)
    suggested = report["suggested"]
    enrichment_by_source = report["enrichment_by_source"]
    summary_by_source = report["summary_by_source"]

    # the debt maps name ≥2 sources each; reddit is held but clean on BOTH axes, so
    # both offenders sets are strict subsets and scoping fires (non-vacuous). They
    # equal the canonical maps the shared seed promises.
    assert enrichment_by_source == expected_enrichment == {"arxiv": 1, "web": 2}
    assert summary_by_source == expected_summary == {"arxiv": 1, "web": 1, "wikipedia": 1}
    held_sources = set(run_doctor(get_paths())["custody"]["by_source"])
    assert held_sources == {"arxiv", "reddit", "web", "wikipedia"}
    assert "reddit" not in enrichment_by_source
    assert "reddit" not in summary_by_source

    # THE TIE: the scoped suggestions name exactly the debt-map sources, per axis.
    classify_sources = _scoped_refresh_sources(suggested, "scrolls classify --stale")
    kb_sources = _scoped_refresh_sources(suggested, "scrolls kb --stale")
    assert classify_sources == set(enrichment_by_source) == {"arxiv", "web"}
    # the H171 attribution carries through: the Bm25 cluster spans web+arxiv, so the
    # summary suggestion names BOTH (plus wikipedia for the Vector cluster) — every
    # source of a stale cluster earns its own scoped `kb --stale --source <S>`.
    assert kb_sources == set(summary_by_source) == {"arxiv", "web", "wikipedia"}

    # because scoping fired, the un-scoped whole-library sweep is NOT suggested on
    # either axis (it would needlessly re-run the clean reddit source).
    assert not _suggests_whole_library(suggested, "scrolls classify --stale")
    assert not _suggests_whole_library(suggested, "scrolls kb --stale")

    # and the report's suggestions are a faithful read of the audit — equal to the
    # pure `suggest_repairs` over a fresh whole-library `doctor`, whose scoped sources
    # in turn are exactly doctor's debt-map keys. So the tie is the audit's, not
    # maintain-specific, and closes the suggestion↔debt-map↔doctor triangle.
    doctor_report = run_doctor(get_paths())
    pure = suggest_repairs(doctor_report)
    assert _scoped_refresh_sources(pure, "scrolls classify --stale") == classify_sources
    assert _scoped_refresh_sources(pure, "scrolls kb --stale") == kb_sources
    assert classify_sources == set(doctor_report["custody"]["enrichment"]["by_source"])
    assert kb_sources == set(doctor_report["custody"]["summaries"]["by_source"])

    # --- mutation: refreshing one source moves the suggestions in lockstep -------
    # `kb --stale --source wikipedia` (offline via `fake_summary_llm`) clears the
    # wikipedia-only Vector summary, dropping wikipedia from `summary_by_source`. The
    # scoped `kb --stale --source <S>` suggestions must drop wikipedia too — in
    # lockstep with the debt map — while the enrichment-axis suggestions stay put (a
    # summary refresh never re-classifies). Proves the tie is causal, not a seed
    # coincidence, and that the two axes move independently.
    assert main(["kb", "--stale", "--source", "wikipedia"]) == 0
    capsys.readouterr()
    main(["maintain", "--no-recheck"])
    after = json.loads(capsys.readouterr().out)
    after_suggested = after["suggested"]
    assert after["summary_by_source"] == {"arxiv": 1, "web": 1}
    assert (
        _scoped_refresh_sources(after_suggested, "scrolls kb --stale")
        == set(after["summary_by_source"])
        == {"arxiv", "web"}
    )
    assert after["enrichment_by_source"] == {"arxiv": 1, "web": 2}
    assert (
        _scoped_refresh_sources(after_suggested, "scrolls classify --stale")
        == set(after["enrichment_by_source"])
        == {"arxiv", "web"}
    )


def test_maintain_suggestions_fall_back_to_whole_library_when_every_source_is_stale(
    scrolls_home, capsys
):
    # roadmap H183 (the boundary case): when EVERY held source carries an axis's
    # stale debt, the offenders are not a *strict* subset of the held universe, so
    # scoping buys nothing and `maintain` suggests the single whole-library sweep
    # (`classify --stale` / `kb --stale`, no `--source`) — already the minimal act.
    # The complement of the scoped tie above: the debt-map keys still name every
    # source, but the suggestion collapses to one un-scoped command per axis. (The
    # universe-unknown / single-source degradations are pinned pure in test_maintain.)
    main(["init"])
    db = get_paths().db_path

    def _classified(item_id, source, ruleset):
        return _item(
            item_id, "Topic classified", source=source, category="tutorial",
            url=f"https://{source}.example.com/{item_id}",
            provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                        "classified_ruleset": ruleset},
        )

    # two sources, BOTH stale on enrichment (no clean source) ...
    insert_item(db, _classified("web:e1", "web", "deadbeef0000"))
    insert_item(db, _classified("arxiv:e1", "arxiv", "cafe00000000"))
    # ... and BOTH spanned by one stale concept-summary cluster (Bm25: web+arxiv),
    # so the summary offenders also equal the held universe {web, arxiv}.
    insert_item(db, _concept_member("b1", "Bm25", "web", "h1"))
    insert_item(db, _concept_member("b2", "Bm25", "arxiv", "h2"))
    _stored_summary(db, "bm25", "stale-old-1")
    capsys.readouterr()

    main(["maintain", "--no-recheck"])  # may exit 1 on the concept fixture's missing_scrolls
    report = json.loads(capsys.readouterr().out)
    suggested = report["suggested"]

    # every held source is stale on each axis → offenders == universe (not strict).
    held_sources = set(run_doctor(get_paths())["custody"]["by_source"])
    assert held_sources == {"arxiv", "web"}
    assert set(report["enrichment_by_source"]) == held_sources == {"arxiv", "web"}
    assert set(report["summary_by_source"]) == held_sources == {"arxiv", "web"}

    # so the suggestion is the whole-library sweep, no `--source`, and no scoped
    # per-source variant is emitted on either axis.
    assert _suggests_whole_library(suggested, "scrolls classify --stale")
    assert _suggests_whole_library(suggested, "scrolls kb --stale")
    assert _scoped_refresh_sources(suggested, "scrolls classify --stale") == set()
    assert _scoped_refresh_sources(suggested, "scrolls kb --stale") == set()


def test_mcp_run_maintenance_scoped_suggestions_name_exactly_the_refresh_debt_sources(
    scrolls_home, capsys, fake_summary_llm
):
    # roadmap H209: the agent-facing MCP `run_maintenance` tool (H196) returns the
    # SAME assembled report shape the CLI `maintain` prints — `assemble_report`
    # composed identically, the `suggested` block from the same `suggest_repairs`.
    # H183 pinned, on the *CLI* surface, that the scoped `suggested` refresh commands
    # name exactly the debt-map sources (`enrichment_by_source` / `summary_by_source`).
    # This folds the *MCP* read into that tie, closing the suggestion↔debt-map
    # convergence over BOTH surfaces. Over the same combined H179/H183 seed: the
    # whole-library `run_maintenance()` tool's scoped `classify --stale --source <S>`
    # suggestion sources ≡ its `enrichment_by_source` keys, the `kb --stale --source
    # <S>` sources ≡ its `summary_by_source` keys (the H171 double-attribution
    # carried), the MCP report converges field-for-field with CLI `maintain
    # --no-recheck` (H183's surface) and the pure `suggest_repairs(run_doctor())`, and
    # a *scoped* `run_maintenance(source=S)` short-circuits to `<command> --source S`
    # per present axis (the H182 collapsed-universe path). Mutation-checked: a `kb
    # --stale --source` refresh moves the MCP suggestions in lockstep with the debt map.
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    # The H179 seed: both refresh axes, with one held source (reddit) clean on BOTH,
    # so each axis's offenders are a *strict* subset of the held universe (scoping
    # fires) and the two axes name different source sets.
    expected_enrichment, expected_summary = _seed_refresh_debt_both_axes(db)
    capsys.readouterr()  # drain the `init` output

    def _audit_fields(report):
        # Both surfaces compose `assemble_report` identically: only the trend-position
        # bookkeeping differs by run order — `recorded_at` (the timestamp) and `delta`
        # (a whole-library pass records a snapshot, so the second run sees the first's
        # as its baseline; ADR 0082). Everything else is the deterministic audit.
        return {k: v for k, v in report.items() if k not in ("recorded_at", "delta")}

    # --- the whole-library MCP pass: its OWN suggestions ≡ its OWN debt maps -------
    # The MCP tool returns a dict (no print/capsys), so capsys stays clean for the
    # CLI comparison below. It records the whole-library snapshot/log baseline (H196).
    mcp_report = mcp_server.run_maintenance()
    mcp_suggested = mcp_report["suggested"]
    mcp_enrichment = mcp_report["enrichment_by_source"]
    mcp_summary = mcp_report["summary_by_source"]

    # the debt maps are the canonical combined seed: ≥2 sources each, reddit held but
    # clean on BOTH axes (a strict subset → scoping fires), the two axes differing.
    assert mcp_enrichment == expected_enrichment == {"arxiv": 1, "web": 2}
    assert mcp_summary == expected_summary == {"arxiv": 1, "web": 1, "wikipedia": 1}
    held_sources = set(run_doctor(get_paths())["custody"]["by_source"])
    assert held_sources == {"arxiv", "reddit", "web", "wikipedia"}
    assert "reddit" not in mcp_enrichment and "reddit" not in mcp_summary

    # THE TIE over MCP: the scoped suggestions name exactly the debt-map sources, per
    # axis. The H171 attribution carries — Bm25 spans web+arxiv, so the summary
    # suggestion names BOTH (plus wikipedia for the Vector cluster).
    mcp_classify = _scoped_refresh_sources(mcp_suggested, "scrolls classify --stale")
    mcp_kb = _scoped_refresh_sources(mcp_suggested, "scrolls kb --stale")
    assert mcp_classify == set(mcp_enrichment) == {"arxiv", "web"}
    assert mcp_kb == set(mcp_summary) == {"arxiv", "web", "wikipedia"}
    # scoping fired on both axes, so the un-scoped whole-library sweep is NOT named.
    assert not _suggests_whole_library(mcp_suggested, "scrolls classify --stale")
    assert not _suggests_whole_library(mcp_suggested, "scrolls kb --stale")

    # --- the MCP report converges field-for-field with the CLI `maintain` ----------
    # Both pass a `skipped_recheck_report` (the MCP tool always, CLI on `--no-recheck`)
    # into the same `assemble_report`, so every audit-derived field is byte-equal; only
    # the run-position bookkeeping (`recorded_at`/`delta`) differs (see `_audit_fields`).
    assert main(["maintain", "--no-recheck"]) in (0, 1)  # 1 on the fixture missing_scrolls
    cli_report = json.loads(capsys.readouterr().out)
    assert _audit_fields(mcp_report) == _audit_fields(cli_report)
    # the suggestion↔debt-map fields specifically agree across the two surfaces.
    assert cli_report["suggested"] == mcp_suggested
    assert cli_report["enrichment_by_source"] == mcp_enrichment
    assert cli_report["summary_by_source"] == mcp_summary

    # ... and the MCP `suggested` is a faithful read of the pure audit: equal to
    # `suggest_repairs` over a fresh whole-library `doctor`, whose scoped sources are
    # exactly doctor's debt-map keys — so the tie is the audit's, not maintain- or
    # transport-specific, closing the suggestion↔debt-map↔doctor triangle over MCP.
    doctor_report = run_doctor(get_paths())
    pure = suggest_repairs(doctor_report)
    assert _scoped_refresh_sources(pure, "scrolls classify --stale") == mcp_classify
    assert _scoped_refresh_sources(pure, "scrolls kb --stale") == mcp_kb
    assert mcp_classify == set(doctor_report["custody"]["enrichment"]["by_source"])
    assert mcp_kb == set(doctor_report["custody"]["summaries"]["by_source"])

    # --- the H182 short-circuit over MCP: a scoped pass names `<command> --source S`
    # per present axis (the collapsed-universe path) --------------------------------
    # Under `source=S` the audit is pre-filtered to <S>, so its held universe collapses
    # to {S} and the H181 strict-subset rule would (wrongly) emit the whole-library
    # sweep; H182 short-circuits to the scoped `<command> --source S` for each axis S
    # carries debt on. web carries ONLY enrichment debt under its own scope (Bm25's
    # lone web member fractures below MIN_MEMBERS → no summary debt); wikipedia carries
    # ONLY summary debt (its Vector cluster, 2 members, survives) and no classifications
    # — so each scoped pass names exactly one axis. A scoped pass is non-persisting (ADR
    # 0082), so it cannot clobber the whole-library baseline recorded above.
    scoped_expect = {  # source -> (classify sources, kb sources)
        "web": ({"web"}, set()),
        "wikipedia": (set(), {"wikipedia"}),
    }
    for source, (want_classify, want_kb) in scoped_expect.items():
        m = mcp_server.run_maintenance(source=source)
        m_suggested = m["suggested"]
        # the scoped pass's OWN debt maps (the audit pre-filtered to S): exactly the
        # axis S carries under its own scope, the other axis the honest empty map.
        assert set(m["enrichment_by_source"]) == want_classify
        assert set(m["summary_by_source"]) == want_kb
        # the short-circuit: each present axis names exactly `<command> --source S`,
        # the absent axis names nothing — never the whole-library sweep.
        assert _scoped_refresh_sources(m_suggested, "scrolls classify --stale") == want_classify
        assert _scoped_refresh_sources(m_suggested, "scrolls kb --stale") == want_kb
        assert not _suggests_whole_library(m_suggested, "scrolls classify --stale")
        assert not _suggests_whole_library(m_suggested, "scrolls kb --stale")
        # a scoped pass keeps no per-source baseline: null delta, null attention.
        assert m["delta"] is None and m["attention"] is None
        # field-for-field with CLI `maintain --source S` and the pure scoped audit.
        assert main(["maintain", "--source", source, "--no-recheck"]) in (0, 1)
        cli_scoped = json.loads(capsys.readouterr().out)
        assert _audit_fields(m) == _audit_fields(cli_scoped)
        assert cli_scoped["suggested"] == m_suggested
        pure_scoped = suggest_repairs(run_doctor(get_paths(), source=source), source=source)
        assert _scoped_refresh_sources(pure_scoped, "scrolls classify --stale") == want_classify
        assert _scoped_refresh_sources(pure_scoped, "scrolls kb --stale") == want_kb

    # --- mutation check: a scoped refresh moves the MCP suggestions in lockstep -----
    # `kb --stale --source wikipedia` (offline via fake_summary_llm) regenerates the
    # wikipedia-only Vector summary, clearing wikipedia's stale-summary debt. The next
    # whole-library `run_maintenance()` must drop wikipedia from BOTH `summary_by_source`
    # and the `kb --stale --source <S>` suggestion sources, in lockstep — while the
    # enrichment axis stays put (a summary refresh never re-classifies). Proves the MCP
    # tie is causal, not a seed coincidence, and that the two axes move independently.
    assert main(["kb", "--stale", "--source", "wikipedia"]) == 0
    capsys.readouterr()
    after = mcp_server.run_maintenance()
    assert after["summary_by_source"] == {"arxiv": 1, "web": 1}
    assert (
        _scoped_refresh_sources(after["suggested"], "scrolls kb --stale")
        == set(after["summary_by_source"])
        == {"arxiv", "web"}
    )
    assert after["enrichment_by_source"] == {"arxiv": 1, "web": 2}
    assert (
        _scoped_refresh_sources(after["suggested"], "scrolls classify --stale")
        == set(after["enrichment_by_source"])
        == {"arxiv", "web"}
    )


def test_graph_by_source_converges_with_doctor_and_the_per_source_tally(scrolls_home, capsys):
    # roadmap H150: the `scrolls graph` stats block now carries the per-source
    # custody split (`stats.custody.by_source`) — the graph-surface counterpart of
    # the JSON `status` `by_source` (H133). It folds the same
    # `custody_counts_by_source` over the whole `stats.items` scope, so it claims to
    # agree with the standalone audit and the shared tally. Pin it beside the H133
    # status tie: over the multi-source seed, the graph block equals `doctor`'s
    # `custody.by_source`, `status`'s `by_source`, and `custody_counts_by_source`
    # over the held items, and its per-source entries sum to the whole `stats.custody`
    # tiers/drift beside them.
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # four `web` scrolls spanning the tiers/postures
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # the graph's per-source split — over the whole library, independent of --all
    assert main(["graph", "--all"]) == 0
    graph_custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    graph_by_source = graph_custody["by_source"]
    assert set(graph_by_source) == {"web", "arxiv"}

    # 1. == doctor's own `custody.by_source` over the same library
    assert graph_by_source == run_doctor(get_paths())["custody"]["by_source"]

    # 2. == the JSON `status` `by_source` (the H133 sibling surface)
    assert main(["status"]) == 0
    assert graph_by_source == json.loads(capsys.readouterr().out)["by_source"]

    # 3. == the canonical `custody_counts_by_source` tally over the held items
    items = list_items(db)
    verdicts = latest_events(db)
    assert graph_by_source == custody_counts_by_source(items, verdicts)

    # 4. the per-source tallies sum to the graph's own whole `custody` block beside
    #    them (H104 sum-to-whole, per source — the two members can never disagree)
    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for counts in graph_by_source.values():
        for tier, n in counts["tiers"].items():
            summed_tiers[tier] += n
        for posture, n in counts["drift"].items():
            summed_drift[posture] += n
    assert summed_tiers == graph_custody["tiers"]
    assert summed_drift == graph_custody["drift"]


def test_status_attention_converges_with_maintain_and_doctor(scrolls_home, capsys):
    # roadmap H139: `scrolls status` now carries the single weakest-source
    # `attention` flag — the status-surface counterpart of `maintain`'s `attention`
    # (H119). It is distilled (`weakest_source`) from the same `run_doctor` per-source
    # map `status` already reads for its `by_source` member, so it *claims* to name the
    # same source the scheduled worker's report and the standalone audit would. Pin it
    # as a first-class entry beside H129 (`maintain attention ≡ doctor's max-loss
    # source`): over the multi-source loss seed, `status`'s `attention` equals
    # `maintain --no-recheck`'s `attention`, and its `.source` equals doctor's max-loss
    # source — so the single-flag the three surfaces show can never disagree. The
    # `attention`-axis sibling of H133 (`by_source`) on the status surface.
    main(["init"])
    db = get_paths().db_path
    # web carries the only actionable loss (web:full2 drifted); arxiv is clean, so
    # `web` is the unambiguous max-loss source the flag must name (the H129 seed).
    _seed_mixed_custody(db)
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # status's weakest-source flag — distilled from the audit it already makes
    assert main(["status"]) == 0
    status_attention = json.loads(capsys.readouterr().out)["attention"]

    by_source = run_doctor(get_paths())["custody"]["by_source"]
    # sanity: the seed makes `web` the unambiguous max-loss source (1 drifted vs 0)
    assert by_source["web"]["drift"]["drifted"] == 1
    assert by_source["arxiv"]["drift"]["drifted"] == 0

    # 1. the flag names exactly doctor's max-loss source (a literal pick, not a
    #    tautology — ranking by *least* loss would name `arxiv`)
    assert status_attention is not None
    assert status_attention["source"] == _max_loss_source(by_source) == "web"
    # 2. == `weakest_source` over doctor's own per-source map (the primitive status threads)
    assert status_attention == weakest_source(by_source)
    # roadmap H153: the per-source recheck coverage rides the flag — == doctor's
    # `custody.by_source[<source>].coverage` for the flagged source by construction,
    # so `status`'s `attention` carries how much of the weak source is checked.
    assert status_attention["coverage"] == by_source["web"]["coverage"]

    # 3. == the `maintain --no-recheck` report's `attention` (the scheduled sibling,
    #    H119) — `--no-recheck` keeps the ledger pristine so both read one state
    assert main(["maintain", "--no-recheck"]) == 0
    maintain_attention = json.loads(capsys.readouterr().out)["attention"]
    assert status_attention == maintain_attention

    # 4. the recheck command names exactly that source (H137) — the bridge to the act
    assert status_attention["command"] == f"scrolls verify --source {status_attention['source']}"


def test_status_attention_is_null_with_no_cross_source_loss(scrolls_home, capsys):
    # the honest-null gate on the status surface (H139/H119): with ≥2 sources but no
    # `drifted`/`rotted` anywhere, `status`'s `attention` is `null` — exactly when
    # `maintain`'s is and when doctor's per-source map carries zero actionable loss.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item("web:1", "Topic one", extracted_text="b1",
                          raw_text="<raw>1</raw>", content_hash="sha256:1"))
    insert_item(db, _item("arxiv:1", "Topic arxiv", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="a",
                          raw_text="<raw>a</raw>", content_hash="sha256:a"))
    record_events(db, [
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),
        # arxiv:1 left unverified — no source carries loss
    ])
    capsys.readouterr()

    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None

    # converges with doctor (no source carries loss) and with maintain (both null)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}  # ≥2 sources, so the gate is the loss
    assert weakest_source(by_source) is None
    assert main(["maintain", "--no-recheck"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None


def test_graph_attention_converges_with_status_maintain_and_doctor(scrolls_home, capsys):
    # roadmap H164: the `graph` `stats.custody` block now carries the same weakest-
    # source `attention` flag JSON `status` (H139) and `maintain` (H119) do —
    # distilled by the shared `weakest_source` over the graph's own `by_source`,
    # which equals `doctor`'s for the whole-library scope (pinned in test_graph.py).
    # Fold the graph leg into the attention convergence beside the status tie: over
    # the loss seed the graph's `attention` equals `status`'s, `maintain
    # --no-recheck`'s, and `weakest_source(doctor.by_source)`, all naming doctor's
    # max-loss source — so the single flag the four surfaces show can never disagree.
    main(["init"])
    db = get_paths().db_path
    # web carries the only actionable loss (web:full2 drifted); arxiv is clean, so
    # `web` is the unambiguous max-loss source the flag must name (the H139 seed).
    _seed_mixed_custody(db)
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # the graph's weakest-source flag — distilled from its own by_source
    assert main(["graph", "--all"]) == 0
    graph_attention = json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"]

    by_source = run_doctor(get_paths())["custody"]["by_source"]
    # sanity: the seed makes `web` the unambiguous max-loss source (1 drifted vs 0)
    assert by_source["web"]["drift"]["drifted"] == 1
    assert by_source["arxiv"]["drift"]["drifted"] == 0

    # 1. names exactly doctor's max-loss source (a literal pick — least-loss is arxiv)
    assert graph_attention is not None
    assert graph_attention["source"] == _max_loss_source(by_source) == "web"
    # 2. == `weakest_source` over doctor's own per-source map (the primitive graph threads)
    assert graph_attention == weakest_source(by_source)
    # H153: the per-source recheck coverage rides the flag
    assert graph_attention["coverage"] == by_source["web"]["coverage"]

    # 3. == `status`'s and `maintain --no-recheck`'s flags — the three JSON surfaces
    #    read one weak source (all distil the same map via the same primitive)
    assert main(["status"]) == 0
    status_attention = json.loads(capsys.readouterr().out)["attention"]
    assert main(["maintain", "--no-recheck"]) == 0
    maintain_attention = json.loads(capsys.readouterr().out)["attention"]
    assert graph_attention == status_attention == maintain_attention

    # 4. the recheck command names exactly that source (H137) — the bridge to the act
    assert graph_attention["command"] == f"scrolls verify --source {graph_attention['source']}"


def test_graph_attention_is_null_with_no_cross_source_loss(scrolls_home, capsys):
    # the honest-null gate on the graph surface (H164/H139): with ≥2 sources but no
    # `drifted`/`rotted` anywhere, the graph's `attention` is `null` — exactly when
    # `status`/`maintain` are and when doctor's per-source map carries zero loss.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item("web:1", "Topic one", extracted_text="b1",
                          raw_text="<raw>1</raw>", content_hash="sha256:1"))
    insert_item(db, _item("arxiv:1", "Topic arxiv", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="a",
                          raw_text="<raw>a</raw>", content_hash="sha256:a"))
    record_events(db, [
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),
        # arxiv:1 left unverified — no source carries loss
    ])
    capsys.readouterr()

    assert main(["graph", "--all"]) == 0
    assert json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"] is None
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}  # ≥2 sources, so the gate is the loss
    assert weakest_source(by_source) is None


def test_browse_stats_attention_converges_with_status_graph_and_doctor(scrolls_home, capsys):
    # roadmap H174: the browse `search`/`list --stats` envelopes now carry the same
    # weakest-source `attention` flag the `graph` (H164), JSON `status` (H139), and
    # `maintain` (H119) surfaces do — distilled by the shared `weakest_source` over
    # the matched scope's own `by_source`. For an uncapped whole-library `list`, that
    # scope IS the whole library, so the flag names doctor's max-loss source. The one
    # difference: the browse `by_source` is the *lean* projection (no per-source
    # coverage, H155), so the browse flag carries no `coverage` — it is the coverage-
    # bearing flag (`status`/`graph`) projected to its shared fields. Pin the leg
    # beside the graph tie so the browse flag can never disagree with the others.
    main(["init"])
    db = get_paths().db_path
    # web carries the only actionable loss (web:full2 drifted); arxiv is clean, so
    # `web` is the unambiguous max-loss source the flag must name (the H139 seed).
    _seed_mixed_custody(db)
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # the browse-stats weakest-source flag — distilled from the matched scope's by_source
    assert main(["list", "--stats"]) == 0
    list_attention = json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"]

    by_source = run_doctor(get_paths())["custody"]["by_source"]
    # sanity: the seed makes `web` the unambiguous max-loss source (1 drifted vs 0)
    assert by_source["web"]["drift"]["drifted"] == 1
    assert by_source["arxiv"]["drift"]["drifted"] == 0

    # 1. names exactly doctor's max-loss source (a literal pick — least-loss is arxiv)
    assert list_attention is not None
    assert list_attention["source"] == _max_loss_source(by_source) == "web"
    # 2. == the *lean* `weakest_source` over doctor's own per-source map: the browse
    #    flag is the coverage-bearing flag projected to its shared fields (no coverage)
    assert list_attention == weakest_source(by_source, include_coverage=False)
    assert "coverage" not in list_attention  # the lean projection (H174)

    # 3. == `status`'s and `graph`'s flags on every shared field — the coverage-
    #    bearing flag minus its `coverage` member is exactly the browse flag, so the
    #    four surfaces read one weak source (all distil the same map, same primitive)
    assert main(["status"]) == 0
    status_attention = json.loads(capsys.readouterr().out)["attention"]
    assert main(["graph", "--all"]) == 0
    graph_attention = json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"]
    assert {k: v for k, v in status_attention.items() if k != "coverage"} == list_attention
    assert {k: v for k, v in graph_attention.items() if k != "coverage"} == list_attention

    # 4. `search --stats` names the same weakest source (both web loss items are
    #    full-content, so the query-matched scope still flags `web`)
    assert main(["search", "topic", "--stats"]) == 0
    search_attention = json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"]
    assert search_attention is not None
    assert search_attention["source"] == "web"
    assert "coverage" not in search_attention

    # 5. the recheck command names exactly that source (H137) — the bridge to the act
    assert list_attention["command"] == "scrolls verify --source web"


def test_browse_stats_attention_is_null_with_no_cross_source_loss(scrolls_home, capsys):
    # the honest-null gate on the browse surface (H174/H139): with ≥2 sources but no
    # `drifted`/`rotted` anywhere, `list`/`search --stats` `attention` is `null` —
    # exactly when `status`/`graph` are and when doctor's per-source map carries zero
    # actionable loss.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item("web:1", "Topic one", extracted_text="b1",
                          raw_text="<raw>1</raw>", content_hash="sha256:1"))
    insert_item(db, _item("arxiv:1", "Topic arxiv", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="a",
                          raw_text="<raw>a</raw>", content_hash="sha256:a"))
    record_events(db, [
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),
        # arxiv:1 left unverified — no source carries loss
    ])
    capsys.readouterr()

    assert main(["list", "--stats"]) == 0
    assert json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"] is None
    assert main(["search", "topic", "--stats"]) == 0
    assert json.loads(capsys.readouterr().out)["stats"]["custody"]["attention"] is None
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}  # ≥2 sources, so the gate is the loss
    assert weakest_source(by_source, include_coverage=False) is None


def test_mcp_library_health_converges_with_status_and_doctor(scrolls_home, capsys):
    # roadmap H161: the MCP-surface sibling of the JSON `by_source`/`attention`
    # convergence (H157/H139). `get_library_health` returns `run_doctor`'s custody
    # block plus the two distilled members `status` adds (`attention`/`headline`),
    # via the same shared primitives — so an agent reading custody purely over MCP
    # sees the same picture the CLI `status`/`doctor` show. Over the multi-source
    # loss seed, pin that the MCP read, `status`, and `doctor` are one number on
    # every axis they share.
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    # web carries the only actionable loss (web:full2 drifted); arxiv is clean, so
    # `web` is the unambiguous max-loss source the flag must name (the H139 seed).
    _seed_mixed_custody(db)
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    health = mcp_server.get_library_health()

    # 1. == doctor's custody block on every shared axis (it *is* that block + 2 members)
    custody = run_doctor(get_paths())["custody"]
    assert health["score"] == custody["score"]
    assert health["tiers"] == custody["tiers"]
    assert health["drift"] == custody["drift"]
    assert health["by_source"] == custody["by_source"]
    assert health["enrichment"] == custody["enrichment"]
    # the distilled flag names doctor's max-loss source (a literal pick, not a
    # tautology — ranking by *least* loss would name `arxiv`)
    assert health["attention"] == weakest_source(custody["by_source"])
    assert health["attention"]["source"] == _max_loss_source(custody["by_source"]) == "web"

    # 2. == the CLI `status` surface field-for-field (the H139 status seed picture)
    assert main(["status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert health["by_source"] == status["by_source"]
    assert health["attention"] == status["attention"]
    assert health["headline"] == status["headline"]
    assert health["score"] == status["custody"]["score"]
    assert health["tiers"] == status["custody"]["tiers"]


def test_mcp_library_health_attention_is_null_with_no_cross_source_loss(scrolls_home, capsys):
    # the honest-null gate on the MCP surface (H161/H139): with ≥2 sources but no
    # actionable loss, `get_library_health`'s `attention` is `null` — exactly when
    # `status`'s and `maintain`'s are, and when doctor's per-source map is clean.
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item("web:1", "Topic one", extracted_text="b1",
                          raw_text="<raw>1</raw>", content_hash="sha256:1"))
    insert_item(db, _item("arxiv:1", "Topic arxiv", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="a",
                          raw_text="<raw>a</raw>", content_hash="sha256:a"))
    record_events(db, [
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),
    ])
    capsys.readouterr()

    health = mcp_server.get_library_health()
    assert health["attention"] is None
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}  # ≥2 sources, so the gate is the loss
    assert weakest_source(by_source) is None


def test_list_stats_custody_member_converges_with_facets(scrolls_home, capsys):
    # roadmap H98: the `list --stats` envelope's `stats.custody` is the
    # browse-surface counterpart of the `graph` stats.custody block — built from the
    # same shared `custody_counts` tally, so it converges with `facets
    # fidelity`/`drift` for the same scope by construction. `list` is filter-only
    # (no free-text query), so its *matched* scope is exactly the `facets` scope —
    # pin it whole-library and under a shared `--source` filter, and pin that the
    # custody totals equal `stats.matched` (the full matched scope, not the page).
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    # whole library: the custody member equals the whole-library facets
    assert main(["list", "--stats"]) == 0
    stats = json.loads(capsys.readouterr().out)["stats"]
    assert _nonzero(stats["custody"]["tiers"]) == _facet_map(
        compute_facets(db, field="fidelity")["facets"]["fidelity"])
    assert _nonzero(stats["custody"]["drift"]) == _facet_map(
        compute_facets(db, field="drift")["facets"]["drift"])
    # the totals cover the matched scope (every scroll has one tier and one posture)
    assert sum(stats["custody"]["tiers"].values()) == stats["matched"]
    assert sum(stats["custody"]["drift"].values()) == stats["matched"]

    # under --source web: the custody member narrows with the listing, still == facets
    assert main(["list", "--source", "web", "--stats"]) == 0
    web_stats = json.loads(capsys.readouterr().out)["stats"]
    assert _nonzero(web_stats["custody"]["tiers"]) == _facet_map(
        compute_facets(db, field="fidelity", source="web")["facets"]["fidelity"])
    assert _nonzero(web_stats["custody"]["drift"]) == _facet_map(
        compute_facets(db, field="drift", source="web")["facets"]["drift"])
    # and it equals the canonical tally over the web-scoped held items — including
    # the per-source `by_source` split (roadmap H155): a single-source scope folds to
    # one `{web: {tiers, drift}}` entry that re-states the whole-scope tally.
    web_items = [item for item in list_items(db) if item.source == "web"]
    expected = custody_counts(web_items, latest_events(db))
    expected["by_source"] = {"web": {"tiers": expected["tiers"], "drift": expected["drift"]}}
    # a single-source scope flags nothing — the honest-null weakest-source flag (H174)
    expected["attention"] = None
    assert web_stats["custody"] == expected


# --- the stats.custody family invariant (roadmap H101) -----------------------


def _tally_rows(rows):
    """Fold a browse call's own per-item rows into the shared custody tally.

    Each row — a `list`/`search`/`related` result, a `graph` node, a `works`
    representation — carries the per-item `fidelity` + `drift` fields
    (H56/H58/H64); `tally_custody` over those pairs is exactly what the *same*
    call's `stats.custody` member claims to be. Comparing the two pins that the
    envelope aggregate can never desync from the per-item fields it sums
    (roadmap H101). The `by_source` split (roadmap H155) is the same fold grouped
    by each row's own `source`, so the per-source member rides along too — pinning
    that the browse-stats `stats.custody.by_source` is the per-item fold split per
    source (the `graph` block adds a heavier `coverage`-bearing `by_source`, so its
    tie compares the tiers/drift axes this fold produces). The weakest-source
    `attention` flag (roadmap H174) is the *lean* distillation of that per-source
    fold (`include_coverage=False`, no fabricated coverage), so it rides along too —
    pinning that the lean browse-stats `attention` is the lean flag over the per-item
    fold (the `graph` block carries the heavier coverage-bearing flag, so its tie
    again compares only the tiers/drift axes).
    """
    tally = tally_custody((row["fidelity"], row["drift"]) for row in rows)
    tally["by_source"] = tally_custody_by_source(
        (row["source"], row["fidelity"], row["drift"]) for row in rows
    )
    tally["attention"] = weakest_source(tally["by_source"], include_coverage=False)
    return tally


def test_stats_custody_family_agrees_with_its_own_per_item_fields(scrolls_home, capsys):
    # roadmap H101: every browse-surface `stats.custody` member (the `search`/
    # `list`/`related --stats` envelopes H98/H99 and the `graph` stats block H52)
    # is built by folding the *same* `custody.tally_custody` over its matched
    # scope. The per-surface convergence is pinned scattered (e.g. the list↔facets
    # test above); pin here, once, that each equals the tally over *its own*
    # returned per-item fidelity/drift — so the envelope aggregate and the per-item
    # axis (H56/H58) can never desync — and, for the stored-facet scopes
    # (list/search), equals `facets`. No truncation in this fixture, so returned ==
    # matched and the tally over the returned rows is the whole matched scope.
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)  # four items, all four postures, all match "topic"
    capsys.readouterr()

    facet_fidelity = _facet_map(compute_facets(db, field="fidelity")["facets"]["fidelity"])
    facet_drift = _facet_map(compute_facets(db, field="drift")["facets"]["drift"])
    # sanity: the fixture exercises all four drift postures (a non-trivial drift mix)
    assert facet_drift == {"verified": 1, "drifted": 1, "rotted": 1, "unverified": 1}

    # list --stats: the envelope custody == the tally over its own rows == facets
    assert main(["list", "--stats"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stats"]["custody"] == _tally_rows(payload["results"])
    assert _nonzero(payload["stats"]["custody"]["tiers"]) == facet_fidelity
    assert _nonzero(payload["stats"]["custody"]["drift"]) == facet_drift

    # search --stats: the same tie, over the query-matched hits
    assert main(["search", "topic", "--stats"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stats"]["custody"] == _tally_rows(payload["results"])
    assert _nonzero(payload["stats"]["custody"]["tiers"]) == facet_fidelity
    assert _nonzero(payload["stats"]["custody"]["drift"]) == facet_drift

    # related <anchor> --stats: the neighbourhood tally == the tally over its hits.
    # No facets analogue (the scope is the anchor's related set, excluding it), so
    # the tie is to the call's own per-hit fields — the anchor must not appear.
    assert main(["related", "web:1", "--stats"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "web:1" not in {row["id"] for row in payload["results"]}
    assert payload["stats"]["custody"] == _tally_rows(payload["results"])

    # graph --all: the stats block custody tiers/drift == the tally over its nodes.
    # `--all` so every item is a node, matching the whole stats.items scope the tally
    # covers (H52). The graph block also carries a per-source `by_source` split (H150),
    # tied separately in test_graph_by_source_converges_with_doctor_…, so compare the
    # tiers/drift axes the per-item fold produces.
    assert main(["graph", "--all"]) == 0
    payload = json.loads(capsys.readouterr().out)
    graph_custody, node_tally = payload["stats"]["custody"], _tally_rows(payload["nodes"])
    assert graph_custody["tiers"] == node_tally["tiers"]
    assert graph_custody["drift"] == node_tally["drift"]


def test_works_stats_custody_agrees_with_its_representations(scrolls_home, capsys):
    # roadmap H101: the works-surface member of the stats.custody family (H100).
    # `works` has no `--stats` flag (its `stats` block is always on) and no facets
    # analogue (the scope is the reported works' representations), so pin the tie to
    # its own per-rep fidelity/drift. Needs a DOI-sharing seed — the ring above
    # links by URL and forms no work — with a mixed fidelity (the ring is all-full):
    # a full preprint + a bare-reference published record.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item(
        "arxiv:1706.03762", "Attention Is All You Need", source="arxiv",
        source_id="1706.03762", url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",), stage="rendered",
        raw_text="<raw>preprint body</raw>", content_hash="sha256:a",
    ))
    insert_item(db, _item(
        "crossref:10.5555/3295222", "Attention Is All You Need", source="crossref",
        source_id="10.5555/3295222", url="https://doi.org/10.5555/3295222",
        stage="rendered",  # no raw_text/hash → a bare reference
    ))
    record_events(db, [
        CustodyEvent("arxiv:1706.03762", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:a", "sha256:x", None),
        # crossref left unverified
    ])
    capsys.readouterr()

    assert main(["works"]) == 0
    payload = json.loads(capsys.readouterr().out)
    reps = [rep for work in payload["works"] for rep in work["representations"]]
    # the envelope tally == the tally over the reported reps' own fidelity/drift
    assert payload["stats"]["custody"] == _tally_rows(reps)
    # the concrete mix the seed produces: one full+drifted preprint, one
    # reference+unverified published record
    assert payload["stats"]["custody"]["tiers"] == {"full": 1, "partial": 0, "reference": 1}
    assert payload["stats"]["custody"]["drift"] == {
        "verified": 0, "unverified": 1, "drifted": 1, "rotted": 0, "error": 0}


def test_browse_stats_by_source_converges_with_doctor_for_the_whole_library(scrolls_home, capsys):
    # roadmap H155: the browse-stats `stats.custody.by_source` (the per-source split
    # on the `search`/`list --stats` envelopes) is the browse counterpart of the
    # per-source `by_source` on JSON `status` (H133), the `graph` stats block (H150),
    # and `doctor` (H104). For an uncapped whole-library scope each must equal
    # `doctor`'s `custody.by_source` and `custody_counts_by_source` over the held
    # items on the tiers/drift axes the lean browse family carries (the H101
    # stats.custody invariant, split per source).
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # four `web` scrolls spanning the tiers/postures
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    verdicts = latest_events(db)
    canonical = custody_counts_by_source(list_items(db), verdicts)
    doctor_by_source = run_doctor(get_paths())["custody"]["by_source"]
    # non-vacuous: the seed is genuinely multi-source
    assert set(canonical) == {"arxiv", "web"}

    # both uncapped browse envelopes split the whole library the same way
    for argv in (["list", "--stats"], ["search", "topic", "--stats"]):
        assert main(argv) == 0
        custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
        by_source = custody["by_source"]
        assert set(by_source) == {"arxiv", "web"}
        for source, entry in by_source.items():
            # == doctor's per-source tally and the canonical per-source tally, on
            # the tiers/drift axes (doctor/canonical also carry `coverage`, the
            # heavier axis the lean browse family omits)
            assert entry["tiers"] == doctor_by_source[source]["tiers"] == \
                canonical[source]["tiers"]
            assert entry["drift"] == doctor_by_source[source]["drift"] == \
                canonical[source]["drift"]
        # each surface's per-source entries sum to its own whole `stats.custody`
        summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
        summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
        for entry in by_source.values():
            for tier, n in entry["tiers"].items():
                summed_tiers[tier] += n
            for posture, n in entry["drift"].items():
                summed_drift[posture] += n
        assert summed_tiers == custody["tiers"]
        assert summed_drift == custody["drift"]


def _lean_by_source(by_source):
    """Project a per-source custody map to the tiers/drift axes *every* JSON
    `by_source` surface carries.

    The lean browse family (`list`/`search --stats`) omits the heavier
    `coverage` axis `doctor`/`status`/`graph` keep (a `(fidelity, drift)` pair
    cannot recover `content_hash` presence, roadmap H155), so the cross-surface
    tie is on tiers/drift here, with coverage asserted separately on the surfaces
    that carry it.
    """
    return {
        source: {"tiers": entry["tiers"], "drift": entry["drift"]}
        for source, entry in by_source.items()
    }


def _sum_tiers_drift(by_source):
    """Sum a per-source map's tiers/drift into whole-scope counts (posture vocab)."""
    summed_tiers = {tier: 0 for tier in ("full", "partial", "reference")}
    summed_drift = {p: 0 for p in ("verified", "unverified", "drifted", "rotted", "error")}
    for entry in by_source.values():
        for tier, n in entry["tiers"].items():
            summed_tiers[tier] += n
        for posture, n in entry["drift"].items():
            summed_drift[posture] += n
    return summed_tiers, summed_drift


def test_every_json_by_source_surface_converges_on_one_map(scrolls_home, capsys):
    # roadmap H157: the three tests above each tie *one* JSON `by_source`-bearing
    # surface to `doctor`'s map — JSON `status` (H133), the `graph`
    # `stats.custody.by_source` (H150), and the browse-stats `--stats` envelopes
    # (H155). This pins the consolidating property *once*, the JSON-surface sibling
    # of H151 (which pins the readable `_By source:_` line byte-identical across
    # surfaces): over one multi-source seed every structured `by_source` map —
    # JSON `status`, the `graph` block, and the `list`/`search --stats` envelopes —
    # reads the *same* per-source picture, all equal to `custody_counts_by_source`
    # over the held items and to `doctor`'s `custody.by_source` on the tiers/drift
    # axes the lean browse family carries (coverage, the heavier axis only
    # doctor/status/graph keep, is tied separately below), and each surface's
    # per-source entries sum to its own whole `custody`/`stats.custody` block (the
    # H104 sum-to-whole, per surface). A future change that desyncs any one JSON
    # surface's fold fails here, in one obvious place.
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_custody(db)  # four `web` scrolls spanning the tiers/postures
    insert_item(db, _item("arxiv:1", "Topic arxiv paper", source="arxiv",
                          url="https://arxiv.org/abs/1", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:arxiv"))
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    canonical = custody_counts_by_source(items, verdicts)
    doctor_by_source = run_doctor(get_paths())["custody"]["by_source"]
    expected_lean = _lean_by_source(canonical)
    # non-vacuous: genuinely multi-source, and the two sources' mixes differ — so a
    # fold that merged or mislabeled sources would break the cross-surface equality
    assert set(canonical) == {"arxiv", "web"}
    assert expected_lean["web"] != expected_lean["arxiv"]
    # the audit and the pure tally already agree on the full map (the module spine)
    assert doctor_by_source == canonical

    # collect every JSON `by_source` surface from one seeded library ...
    assert main(["status"]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert main(["graph", "--all"]) == 0
    graph_custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    assert main(["list", "--stats"]) == 0
    list_custody = json.loads(capsys.readouterr().out)["stats"]["custody"]
    assert main(["search", "topic", "--stats"]) == 0
    search_custody = json.loads(capsys.readouterr().out)["stats"]["custody"]

    # status/graph carry the full {tiers, drift, coverage} map (like doctor); the
    # lean browse surfaces carry {tiers, drift} only
    coverage_bearing = {"status": status_payload["by_source"], "graph": graph_custody["by_source"]}
    lean_only = {"list --stats": list_custody["by_source"],
                 "search --stats": search_custody["by_source"]}

    # 1. every surface's tiers/drift map == the canonical tally == doctor's map
    #    (compared on the lean axes, so the browse family is held to the same
    #    picture as doctor/status/graph — the consolidating cross-surface tie)
    for name, by_source in {**coverage_bearing, **lean_only}.items():
        assert set(by_source) == {"arxiv", "web"}, f"{name} source set diverged"
        assert _lean_by_source(by_source) == expected_lean, f"{name} diverged from the canonical map"

    # 2. the coverage axis ties too on the surfaces that carry it (status/graph),
    #    == doctor's / the tally's per-source coverage for each source
    for name, by_source in coverage_bearing.items():
        for source in ("web", "arxiv"):
            assert by_source[source]["coverage"] == canonical[source]["coverage"], \
                f"{name} coverage diverged for {source}"

    # 3. each surface's per-source entries sum to its own whole custody block beside
    #    them (H104 sum-to-whole, per surface — the two members can never disagree).
    #    `status`'s whole block uses the ledger vocabulary (`unchanged`); the graph
    #    and browse blocks use the posture vocabulary (`verified`), so normalise each
    #    to the canonical posture counts.
    whole = custody_counts(items, verdicts)
    per_surface = [
        ("status", status_payload["by_source"], status_payload["custody"]["tiers"],
         _posture_from_ledger_counts(status_payload["custody"]["drift"])),
        ("graph", graph_custody["by_source"], graph_custody["tiers"], graph_custody["drift"]),
        ("list --stats", list_custody["by_source"], list_custody["tiers"], list_custody["drift"]),
        ("search --stats", search_custody["by_source"], search_custody["tiers"],
         search_custody["drift"]),
    ]
    for name, by_source, block_tiers, block_drift in per_surface:
        summed_tiers, summed_drift = _sum_tiers_drift(by_source)
        assert summed_tiers == block_tiers == whole["tiers"], f"{name} tiers ≠ its block"
        assert summed_drift == block_drift == whole["drift"], f"{name} drift ≠ its block"

    # mutation-check: the cross-surface equality has teeth — perturbing a single
    # per-source count on any one surface's fold breaks the tie to the canonical map
    perturbed = {
        source: {"tiers": dict(entry["tiers"]), "drift": dict(entry["drift"])}
        for source, entry in expected_lean.items()
    }
    perturbed["web"]["tiers"]["full"] += 1
    assert perturbed != expected_lean


def test_graph_object_twin_by_source_is_whole_library_not_a_subset(scrolls_home):
    # roadmap H195 (graph leg): the MCP object-twin `get_link_graph` carries
    # `stats.custody.by_source` (the H150/H186 shape). This pins its *content* tie to
    # `run_doctor` — and corrects the slice's "connected-only ⊂ doctor" framing with
    # the honest scope fact the code actually holds: the graph's custody tally is
    # folded over the *whole* `stats.items` scope (`graph.items`, graph.to_payload —
    # roadmap H52/H150), **not** the connected `nodes`. So the object-twin's
    # `by_source` equals `doctor`'s full `custody.by_source` field-for-field (coverage
    # included) *independent of* `include_isolated` — excluding an isolated item from
    # the rendered `nodes` does **not** drop it from the custody tally (nodes ≠ custody
    # scope). The load-bearing subtlety, pinned positively: the graph object-twin is
    # never a *subset* of doctor; an isolate is still counted. The MCP-twin sibling of
    # the CLI `graph --all` tie (H150/H157), reached through the object entrypoint at
    # its non-isolating default.
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    # the whole-connected case: a multi-source ring web:1 → web:2 → arxiv:1 → web:1, so
    # every item takes part in an edge and is a node (≥2 sources, differing per-source
    # mixes). web:1 verified, web:2 full+drifted, arxiv:1 partial+unverified.
    insert_item(db, _item("web:1", "Topic one", extracted_text="b1",
                          raw_text="<raw>1</raw>", content_hash="sha256:1",
                          links=("https://example.com/web:2",)))
    insert_item(db, _item("web:2", "Topic two", extracted_text="b2",
                          raw_text="<raw>2</raw>", content_hash="sha256:2",
                          links=("https://example.com/arxiv:1",)))
    insert_item(db, _item("arxiv:1", "Topic arxiv", source="arxiv",
                          extracted_text="a",  # no hash → partial
                          links=("https://example.com/web:1",)))
    record_events(db, [
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),
        CustodyEvent("web:2", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:2", "sha256:changed", None),
        # arxiv:1 left unverified
    ])

    doctor_by_source = run_doctor(get_paths())["custody"]["by_source"]
    # non-vacuous: ≥2 sources, and the two per-source pictures differ (a fold that
    # merged/mislabeled sources would break the field-for-field tie)
    assert set(doctor_by_source) == {"arxiv", "web"}
    assert doctor_by_source["web"]["tiers"] != doctor_by_source["arxiv"]["tiers"]

    # the whole-connected case: every item is a node, and the object-twin's by_source
    # equals doctor's full map (coverage included) — node set == custody scope.
    graph = mcp_server.get_link_graph()
    assert {node["id"] for node in graph["nodes"]} == {"web:1", "web:2", "arxiv:1"}
    assert graph["stats"]["nodes"] == graph["stats"]["items"] == 3
    graph_by_source = graph["stats"]["custody"]["by_source"]
    assert graph_by_source == doctor_by_source            # field-for-field, incl coverage
    assert "coverage" in graph_by_source["web"]           # the full {tiers,drift,coverage}

    # the isolated-item case: add a third source that links to nothing. It is excluded
    # from the default graph's `nodes` ...
    insert_item(db, _item("wikipedia:1", "Topic wiki", source="wikipedia",
                          stage="detected"))  # no content → reference; no links → isolated
    doctor_by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(doctor_by_source) == {"arxiv", "web", "wikipedia"}

    graph = mcp_server.get_link_graph()  # default include_isolated=False
    assert "wikipedia" not in {node["source"] for node in graph["nodes"]}  # isolate ≠ node
    assert graph["stats"]["items"] == 4                   # but it is in the scope
    # ... yet `by_source` STILL carries wikipedia and equals doctor's full map — the
    # object-twin is NOT a subset of doctor; the honest correction to the slice framing.
    graph_by_source = graph["stats"]["custody"]["by_source"]
    assert set(graph_by_source) == {"arxiv", "web", "wikipedia"}   # not a subset
    assert graph_by_source == doctor_by_source

    # independent of `include_isolated`: widening only changes which items become
    # `nodes`, not the custody scope — by_source is byte-identical.
    graph_all = mcp_server.get_link_graph(include_isolated=True)
    assert {node["source"] for node in graph_all["nodes"]} == {"arxiv", "web", "wikipedia"}
    assert graph_all["stats"]["custody"]["by_source"] == graph_by_source == doctor_by_source

    # mutation-check: the field-for-field equality has teeth — perturbing one
    # per-source count breaks the tie to doctor's map.
    perturbed = {
        source: {"tiers": dict(entry["tiers"]), "drift": dict(entry["drift"]),
                 "coverage": dict(entry["coverage"])}
        for source, entry in graph_by_source.items()
    }
    perturbed["web"]["tiers"]["full"] += 1
    assert perturbed != doctor_by_source


def test_works_object_twin_by_source_subsets_doctor_by_representation(scrolls_home):
    # roadmap H195 (works leg): the MCP object-twin `get_works` carries
    # `stats.custody.by_source` (the H155/H186 lean shape). Unlike the graph twin
    # (whole-library by construction, the test above), the works tally is genuinely
    # *scope-restricted* — folded over the reported works' **representations**
    # (works.to_payload, H100/H155), lean `{tiers, drift}` (no per-source coverage).
    # So the object-twin's `by_source` equals `doctor`'s `by_source` projected to
    # tiers/drift *exactly when* every item is a representation of a reported work;
    # over a seed with an *unrepresented* item the twin is a strict **subset** of
    # doctor's — the dropped source is exactly the unrepresented item's. The honest
    # scope difference H195 names, pinned on the surface where it actually holds.
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    # the whole-represented case: a DOI-shared work with two representations across two
    # sources — a full+drifted arxiv preprint and a reference+unverified crossref
    # published record (the H100 works seed). Both items are representations, so the
    # works scope == the whole library.
    insert_item(db, _item(
        "arxiv:1706.03762", "Attention Is All You Need", source="arxiv",
        source_id="1706.03762", url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",), stage="rendered",
        raw_text="<raw>preprint body</raw>", content_hash="sha256:a"))
    insert_item(db, _item(
        "crossref:10.5555/3295222", "Attention Is All You Need", source="crossref",
        source_id="10.5555/3295222", url="https://doi.org/10.5555/3295222",
        stage="rendered"))  # no raw_text/hash → reference
    record_events(db, [
        CustodyEvent("arxiv:1706.03762", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:a", "sha256:x", None),
        # crossref left unverified
    ])

    def _lean(by_source, keys=None):
        return {source: {"tiers": entry["tiers"], "drift": entry["drift"]}
                for source, entry in by_source.items() if keys is None or source in keys}

    doctor_by_source = run_doctor(get_paths())["custody"]["by_source"]
    # non-vacuous: ≥2 sources with differing per-source pictures
    assert set(doctor_by_source) == {"arxiv", "crossref"}
    assert doctor_by_source["arxiv"]["tiers"] != doctor_by_source["crossref"]["tiers"]

    works_by_source = mcp_server.get_works()["stats"]["custody"]["by_source"]
    # the whole-represented case: every item is a rep, so the works scope == doctor's
    assert set(works_by_source) == {"arxiv", "crossref"}
    assert works_by_source == _lean(doctor_by_source)     # field-for-field (lean axes)
    assert "coverage" not in works_by_source["arxiv"]     # the lean shape (H155)

    # the unrepresented-item case: add a wikipedia item with no shared DOI — it forms
    # no multi-representation work, so it is absent from the works scope ...
    insert_item(db, _item("wikipedia:1", "Topic wiki", source="wikipedia",
                          extracted_text="t", raw_text="<raw>t</raw>",
                          content_hash="sha256:w"))
    doctor_by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(doctor_by_source) == {"arxiv", "crossref", "wikipedia"}

    works_by_source = mcp_server.get_works()["stats"]["custody"]["by_source"]
    # ... so the twin is a strict subset of doctor's, dropping exactly that source —
    # the honest scope difference, never a disagreement.
    assert set(works_by_source) < set(doctor_by_source)
    assert set(doctor_by_source) - set(works_by_source) == {"wikipedia"}
    # over the shared sources the twin still equals doctor's lean projection
    assert works_by_source == _lean(doctor_by_source, set(works_by_source))

    # mutation-check: the subset equality has teeth — perturbing a shared per-source
    # count breaks the tie to doctor's lean projection.
    perturbed = {
        source: {"tiers": dict(entry["tiers"]), "drift": dict(entry["drift"])}
        for source, entry in works_by_source.items()
    }
    perturbed["arxiv"]["drift"]["drifted"] += 1
    assert perturbed != _lean(doctor_by_source, set(works_by_source))


def test_object_twin_attention_inherits_the_by_source_scope_split(scrolls_home, capsys):
    # roadmap H211: the distilled weakest-source `attention` flag the two MCP
    # object-twins carry (`stats.custody.attention`, H164/H174) inherits the same
    # scope split H195 pinned on their `by_source` content — and the works twin's
    # representation-only scope can make its flag *honestly disagree* with the
    # whole-library audit. Over a seed where the only actionable loss sits on an
    # *unrepresented*, *isolated* item:
    #   - the GRAPH flag is whole-library — it equals
    #     `weakest_source(doctor.by_source)` ≡ `status` ≡ `maintain` field-for-field
    #     (coverage included) and *sees the loss even though the item is no node*;
    #   - the WORKS flag ranks only the represented scope, so it is honestly `null`
    #     ("all clear within the consolidatable scope"), NOT because the scope is
    #     single-source (it has two) but because that scope carries no loss.
    # Mutation: bringing the same loss into the represented scope (the drifted item
    # gains the work's DOI link) makes the works flag fire and re-converge with the
    # whole-library flag on every shared field, coverage staying the graph flag's alone.
    from scrolls import mcp_server

    main(["init"])
    db = get_paths().db_path
    doi_link = "https://doi.org/10.5555/3295222"
    # a CLEAN two-rep work across two sources: a full+verified arxiv preprint and a
    # reference+unverified crossref published record (the H100/H195 works seed). Both
    # are representations, so the works scope is exactly {arxiv, crossref}.
    insert_item(db, _item(
        "arxiv:1706.03762", "Attention Is All You Need", source="arxiv",
        source_id="1706.03762", url="https://arxiv.org/abs/1706.03762",
        links=(doi_link,), stage="rendered",
        raw_text="<raw>preprint</raw>", content_hash="sha256:a"))
    insert_item(db, _item(
        "crossref:10.5555/3295222", "Attention Is All You Need", source="crossref",
        source_id="10.5555/3295222", url=doi_link, stage="rendered"))  # reference
    # the ONLY actionable loss: a full web note that drifted — no DOI, no links, so it
    # is both *unrepresented* (forms no multi-rep work) and *isolated* (no graph edge).
    insert_item(db, _item(
        "web:lone", "Topic lone web note",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:w"))
    record_events(db, [
        CustodyEvent("arxiv:1706.03762", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:a", "sha256:a", None),
        CustodyEvent("web:lone", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:w", "sha256:x", None),
        # crossref left unverified
    ])
    capsys.readouterr()

    # the canonical whole-library flag — web is the unambiguous weakest source (the
    # only one carrying loss), across ≥2 sources, with coverage riding along (H153).
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"arxiv", "crossref", "web"}
    canonical = weakest_source(by_source)
    assert canonical is not None
    assert canonical["source"] == "web"
    assert canonical["drift"]["drifted"] == 1
    assert "coverage" in canonical                      # the coverage-bearing flag

    # GRAPH leg: the graph flag is whole-library — it sees web's loss even though
    # web:lone is isolated (no edge → no node), and equals the canonical flag
    # field-for-field, coverage included (graph uses the coverage-bearing distillation).
    graph = mcp_server.get_link_graph()
    assert "web" not in {node["source"] for node in graph["nodes"]}   # isolate ≠ node
    assert graph["stats"]["custody"]["attention"] == canonical

    # ... and converges with the JSON status/maintain flags it shares the primitive
    # with (the H129/H160 tie, re-pinned here at the object-twin entrypoint).
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] == canonical
    assert main(["maintain", "--no-recheck"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] == canonical

    # WORKS leg: the works flag ranks only the represented scope ({arxiv, crossref},
    # both clean) — so it is honestly `null`. The load-bearing subtlety: the null is
    # the *fully-clean* gate, NOT the single-source gate — the works scope has TWO
    # sources, neither carrying loss, so an agent reads "all clear within what I can
    # consolidate" while the whole-library audit separately flags web's drift.
    works = mcp_server.get_works()
    works_by_source = works["stats"]["custody"]["by_source"]
    assert set(works_by_source) == {"arxiv", "crossref"}   # ≥2 sources, web absent
    assert "web" not in works_by_source                    # the loss is outside scope
    works_attention = works["stats"]["custody"]["attention"]
    assert works_attention is None                         # honest disagreement
    # the null is genuinely the clean-scope distillation, not a too-few-sources artefact
    assert weakest_source(works_by_source, include_coverage=False) is None

    # MUTATION — move the SAME loss into the represented scope: give web:lone the
    # work's doi.org link so it becomes a third representation (same item, same drift).
    assert update_item(db, _item(
        "web:lone", "Topic lone web note",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:w",
        links=(doi_link,)))

    # the whole-library audit is unchanged — web still carries the only loss.
    by_source2 = run_doctor(get_paths())["custody"]["by_source"]
    canonical2 = weakest_source(by_source2)
    assert canonical2 is not None and canonical2["source"] == "web"

    works2 = mcp_server.get_works()
    works_by_source2 = works2["stats"]["custody"]["by_source"]
    assert set(works_by_source2) == {"arxiv", "crossref", "web"}   # web now represented
    works_attention2 = works2["stats"]["custody"]["attention"]
    # the works flag now FIRES — and re-converges with the whole-library flag on every
    # SHARED field; coverage stays the whole-library flag's alone (the lean projection,
    # H174: a (fidelity, drift) pair cannot recover coverage).
    assert works_attention2 is not None
    shared = ("source", "tiers", "drift", "reason", "command")
    assert {k: works_attention2[k] for k in shared} == {k: canonical2[k] for k in shared}
    assert "coverage" not in works_attention2     # the lean flag omits it
    assert "coverage" in canonical2               # the whole-library flag carries it


# --- the per-item invariant (roadmap H59) ------------------------------------


def _seed_linked_drift_postures(db):
    """Four ring-linked scrolls, one per drift posture, all matching "topic".

    Every scroll links to the next (`web:1`→`web:2`→`web:3`→`web:4`→`web:1`), so
    every item participates in a graph edge and is a `graph` node; every title
    and a shared `topic` tag make all four match a `topic` search and relate to
    any anchor — so each whole-library surface enumerates all four, and
    `related <anchor>` reaches every other item. The four postures: `web:1`
    re-checked unchanged (→`verified`), `web:2` drifted, `web:3` rotted, `web:4`
    never re-checked (→`unverified`).
    """
    ring = {1: 2, 2: 3, 3: 4, 4: 1}
    for index, nxt in ring.items():
        insert_item(db, _item(
            f"web:{index}", f"Topic scroll {index}",
            extracted_text=f"topic body {index}",
            raw_text=f"<raw>topic {index}</raw>", content_hash=f"sha256:{index}",
            tags=("topic",), links=(f"https://example.com/web:{nxt}",),
        ))
    record_events(db, [
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),
        CustodyEvent("web:2", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:2", "sha256:x", None),
        CustodyEvent("web:3", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:3", None, "HTTP Error 404"),
        # web:4 left unverified
    ])


def _bundle_postures(text):
    """Map item id → drift posture parsed from a bundle briefing's per-scroll lines.

    Each entry heads with ``## N. <title> (`<id>`)`` and carries a
    ``- custody `<posture>` …`` line (roadmap H42); pair each id with the posture
    that follows it, so the briefing's per-scroll posture can be compared against
    the JSON surfaces.
    """
    postures = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^## \d+\. .*\(`([^`]+)`\)\s*$", line)
        if heading:
            current = heading.group(1)
            continue
        custody = re.match(r"^- custody `(\w+)`", line)
        if custody and current is not None:
            postures[current] = custody.group(1)
            current = None
    return postures


def _bundle_last_checked(text):
    """Map item id → `last_checked` parsed from a bundle briefing's custody lines.

    The briefing's `_drift_line` (roadmap H42) carries the timestamp in prose:
    a ``custody`` line ending ``as of <checked_at>`` for a checked scroll, or
    ``never re-checked against its source`` for one with no verdict. So the time
    axis is *present* in the Markdown surface too — parse the ``as of`` date (or
    `None` for never-checked) to compare it against the JSON surfaces'
    `last_checked` (roadmap H88).
    """
    stamps = {}
    current = None
    for line in text.splitlines():
        heading = re.match(r"^## \d+\. .*\(`([^`]+)`\)\s*$", line)
        if heading:
            current = heading.group(1)
            continue
        custody = re.match(r"^- custody `\w+`.* as of (\S+)\s*$", line)
        never = re.match(r"^- custody `unverified` — never re-checked", line)
        if current is not None and (custody or never):
            stamps[current] = custody.group(1) if custody else None
            current = None
    return stamps


def _context_excerpt_tags(text):
    """Map item id → (drift posture, last_checked) from the `full` context excerpts.

    Each `full`-tier `scrolls context` excerpt carries an id/source meta line
    (`` `<id>` · <source>[ · <path>] ``) followed by the per-source drift tag
    `` _drift `<posture>` · last seen <checked_at>_ `` — or `· never re-checked`
    when the ledger holds no verdict (roadmap H62/H90). Pair each id parsed off a
    meta line with the posture/timestamp on the drift tag that follows it (a
    classification tag may sit between, and is skipped), so the model-facing
    bundle's per-excerpt custody can be compared against the JSON `show` surface.
    The timestamp is `None` for a never-re-checked excerpt — the honest-absence
    counterpart of the `unverified` posture and `show`'s `null` `last_checked`.
    """
    tags = {}
    current = None
    for line in text.splitlines():
        meta = re.match(r"^`([^`]+)` · ", line)
        if meta:
            current = meta.group(1)
            continue
        drift = re.match(
            r"^_drift `(\w+)` · (?:last seen (\S+)|never re-checked)_$", line)
        if drift and current is not None:
            tags[current] = (drift.group(1), drift.group(2))
            current = None
    return tags


def _library_markers(text):
    """Map item title → (fidelity, drift, last_checked) from a compiled page's rows.

    Each per-item row on a compiled `library/` group page ends with the H89/H93
    custody marker `· <fidelity> · <drift> · checked <ts>` (or `· never checked`
    for an item with no ledger verdict); this parses the three trailing tokens and
    the row's link title so the human-readable Markdown surface can be compared
    against the JSON surfaces. Keyed by title (unique in the fixture) because the
    row's link encodes the scroll path, not the item id. The greedy `.*` before the
    anchored marker lets the optional ` — <note>` segment fall inside it, so the
    parse works whether or not a row carries a note; the time token is
    `checked <ts>` → the verbatim timestamp, or `never checked` → `None` (the
    honest-absence timestamp, the `null` counterpart of the `unverified` posture).
    """
    markers = {}
    for line in text.splitlines():
        m = re.match(
            r"^\s*- \[([^\]]+)\]\([^)]+\).* · (\w+) · (\w+) · "
            r"(?:checked (\S+)|never checked)\s*$", line)
        if m:
            markers[m.group(1)] = (m.group(2), m.group(3), m.group(4))
    return markers


def _library_headline(text):
    """Parse the compiled `_Custody:_` scope headline into non-zero count maps.

    The KB compiler writes a `custody.custody_headline` line — `_Custody: N
    scroll(s) · fidelity <tier counts> · drift <posture counts>._` — under each
    group list page's count line (roadmap H95) and in the landing `index.md`
    header (H96). This parses that one line back into its scroll count and the
    *non-zero* fidelity-tier / drift-posture count maps (the headline shows only
    non-zero sections), the way `_library_markers` parses the per-row markers
    (H91), so the compiled *scope* summary can be compared against
    `custody_counts` / `facets` / `doctor` for the same scope. Returns `None`
    when the page carries no headline (the rollup pages, roadmap H95 scope).
    """
    line = next((l for l in text.splitlines() if l.startswith("_Custody:")), None)
    if line is None:
        return None
    inner = line[len("_Custody: "):-len("._")]  # strip the `_Custody: ` … `._` frame
    sections = inner.split(" · ")
    count = int(re.match(r"(\d+) scroll", sections[0]).group(1))
    tiers, drift = {}, {}
    for section in sections[1:]:
        if section.startswith("fidelity "):
            target, body = tiers, section[len("fidelity "):]
        elif section.startswith("drift "):
            target, body = drift, section[len("drift "):]
        else:  # pragma: no cover - the headline has only these two sections
            continue
        for pair in body.split(", "):
            name, value = pair.rsplit(" ", 1)
            target[name] = int(value)
    return {"count": count, "tiers": tiers, "drift": drift}


def _by_source_bullets(text):
    """The ``- `<source>` — …`` per-source bullets under a surface's `_By source:_`.

    The Markdown counterpart of `_library_headline` for the per-source breakdown
    (roadmap H151): finds the `_By source:_` lead-in `render_custody_by_source`
    writes, then collects the consecutive ``- `…``-prefixed bullets that follow
    (skipping the blank spacer between the lead-in and the first bullet, stopping at
    the first non-bullet line). Distinguishes the per-source bullets (``- `<source>`
    — …``, backtick after the dash) from a compiled group page's per-item rows
    (``- [Title](path) · …``, a `[` after the dash), so the parse returns exactly
    the per-source split. Returns `[]` when the surface carries no breakdown (a
    single-source/empty scope, or the HTML form, which uses `<li>` not `- `).
    """
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip() == "_By source:_"), None)
    if start is None:
        return []
    bullets = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("- `"):
            bullets.append(stripped)
        elif stripped == "":
            continue  # the blank spacer the renderer writes around the bullets
        else:
            break  # the next section (`## …`, per-item rows) ends the breakdown
    return bullets


def _html_by_source_bullets(html_text):
    """Reconstruct the Markdown `- `<source>` — …` bullets from the HTML twin.

    The `export bundle --format html` form renders the *same* structured
    `custody_source_breakdown` as one `<li>` per source inside
    `<ul class="custody-by-source">` (roadmap H141), not literal Markdown bullets.
    This parses each `<li><code>SOURCE</code> — REST</li>` back into the canonical
    ``- `SOURCE` — REST`` bullet (HTML-unescaping both halves) so the HTML form's
    per-source content can be compared byte-for-byte against the Markdown surfaces
    (roadmap H151). Scoped to the `custody-by-source` list so the per-scroll
    `custody-facts` `<li>`s (which do not open with `<li><code>`) never leak in.
    """
    block = re.search(r'<ul class="custody-by-source">(.*?)</ul>', html_text, re.S)
    if block is None:
        return []
    bullets = []
    for m in re.finditer(r"<li><code>([^<]+)</code> — (.*?)</li>", block.group(1), re.S):
        bullets.append(f"- `{html.unescape(m.group(1))}` — {html.unescape(m.group(2))}")
    return bullets


def _parse_by_source_bullet(bullet):
    """Parse a ``- `<source>` — N scroll(s) · fidelity … · drift …`` bullet.

    Returns ``(source, n, tiers, drift)`` — the per-source counterpart of
    `_library_headline`'s section parse, reading the *non-zero* fidelity-tier and
    drift-posture counts a bullet shows (each as ``<name> <count>``). Lets the
    per-source bullets be summed and checked against the surface's own scope
    headline (roadmap H151).
    """
    m = re.match(r"- `([^`]+)` — (\d+) scroll\(s\)(.*)$", bullet)
    source, n, rest = m.group(1), int(m.group(2)), m.group(3)
    tiers, drift = {}, {}
    for section in rest.split(" · "):
        section = section.strip()
        if section.startswith("fidelity "):
            target, body = tiers, section[len("fidelity "):]
        elif section.startswith("drift "):
            target, body = drift, section[len("drift "):]
        else:
            continue
        for pair in body.split(", "):
            name, value = pair.rsplit(" ", 1)
            target[name] = int(value)
    return source, n, tiers, drift


def _parse_by_source_coverage(bullet):
    """Parse the trailing ``coverage V/T`` section of a per-source bullet.

    Returns ``{verified, total}`` — the per-source recheck coverage a `_By source:_`
    bullet now trails (roadmap H158), the readable counterpart of the JSON
    `by_source[S].coverage`. Returns ``None`` when a bullet carries no coverage
    section (so a future coverage-free surface reads as honest absence, not zero).
    """
    m = re.search(r"· coverage (\d+)/(\d+)", bullet)
    if not m:
        return None
    return {"verified": int(m.group(1)), "total": int(m.group(2))}


def _sum_by_source_bullets(bullets):
    """Sum a surface's per-source bullets into a `{count, tiers, drift}` whole.

    The per-source split's scope total — every item lands in exactly one source
    group, so summing the bullets re-counts the whole scope. Compared against the
    surface's own `_library_headline` so a surface can never render per-source
    bullets over a different scope than the headline above them (roadmap H151).
    """
    count, tiers, drift = 0, {}, {}
    for bullet in bullets:
        _, n, bullet_tiers, bullet_drift = _parse_by_source_bullet(bullet)
        count += n
        for name, value in bullet_tiers.items():
            tiers[name] = tiers.get(name, 0) + value
        for name, value in bullet_drift.items():
            drift[name] = drift.get(name, 0) + value
    return {"count": count, "tiers": tiers, "drift": drift}


def _seed_unified_per_source_fixture(db):
    """One multi-source seed every readable per-source surface scopes identically.

    Five held, *rendered* scrolls (so the compiled `index.md`/group page include
    them), all in category ``ml`` (so `categories/ml.md`'s scope == the whole
    library), every title carrying "topic" (so `export bundle topic`/`context
    topic` match the whole library) — across two sources with *different* tier/drift
    mixes (so the per-source breakdown is genuinely multi-source and the two
    bullets differ, the H151 mutation-sensitivity). The shared scope lets the
    readable per-source breakdown be compared byte-for-byte across the bundle
    (Markdown + HTML), the `context` bundle, the compiled `index.md`, and the
    compiled `categories/ml.md` group page at once.

    `web`: full+verified, full+drifted, reference+unverified (3).
    `arxiv`: full+verified, partial+rotted (2).
    """
    rendered = dict(stage="rendered", category="ml")
    insert_item(db, _item(
        "web:fv", "Topic web full verified", markdown_path="scrolls/web/fv.md",
        extracted_text="topic body", raw_text="<raw>topic</raw>",
        content_hash="sha256:wfv", **rendered))
    insert_item(db, _item(
        "web:fd", "Topic web full drifted", markdown_path="scrolls/web/fd.md",
        extracted_text="topic body", raw_text="<raw>topic</raw>",
        content_hash="sha256:wfd", **rendered))
    insert_item(db, _item(
        "web:ru", "Topic web reference pointer", markdown_path="scrolls/web/ru.md",
        **rendered))  # no content → reference, never re-checked → unverified
    insert_item(db, _item(
        "arxiv:fv", "Topic arxiv full verified", source="arxiv",
        url="https://arxiv.org/abs/fv", markdown_path="scrolls/arxiv/fv.md",
        extracted_text="topic body", raw_text="<raw>topic</raw>",
        content_hash="sha256:afv", **rendered))
    insert_item(db, _item(
        "arxiv:pr", "Topic arxiv partial rotted", source="arxiv",
        url="https://arxiv.org/abs/pr", markdown_path="scrolls/arxiv/pr.md",
        extracted_text="topic only extracted", **rendered))  # extracted, no hash → partial
    record_events(db, [
        CustodyEvent("web:fv", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:wfv", "sha256:wfv", None),
        CustodyEvent("web:fd", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:wfd", "sha256:x", None),
        CustodyEvent("arxiv:fv", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:afv", "sha256:afv", None),
        CustodyEvent("arxiv:pr", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:pr", None, "HTTP Error 404"),
        # web:ru left unverified
    ])


def _seed_compiled_scope_fixture(db):
    """Rendered scrolls spanning the fidelity/drift axes across *two* sources, so a
    `--source` filter genuinely narrows the index scope to a group page's scope.

    Three `web` scrolls (a full+verified, a full+drifted, a reference+never) land
    on `sources/web.md`; one `arxiv` scroll (a partial+rotted) lands on
    `sources/arxiv.md`. Every item is rendered (`markdown_path` set) so the KB
    includes it *and* `facets` (over held items) counts the same set the compiled
    pages render. The `web` group-page scope is a proper subset of the whole
    rendered library the `index.md` headline summarises, so the test pins
    convergence at two distinct scopes, not one.
    """
    insert_item(db, _item(
        "web:fv", "Scope full verified", stage="rendered",
        markdown_path="scrolls/web/scope-full-verified.md",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:fv"))
    insert_item(db, _item(
        "web:fd", "Scope full drifted", stage="rendered",
        markdown_path="scrolls/web/scope-full-drifted.md",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:fd"))
    insert_item(db, _item(
        "web:ru", "Scope reference unverified", stage="rendered",
        markdown_path="scrolls/web/scope-reference-unverified.md"))  # no content → reference
    insert_item(db, _item(
        "arxiv:pr", "Scope partial rotted", source="arxiv",
        url="https://arxiv.org/abs/pr", stage="rendered",
        markdown_path="scrolls/arxiv/scope-partial-rotted.md",
        extracted_text="only extracted"))  # extracted, no hash/raw → partial
    record_events(db, [
        CustodyEvent("web:fv", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:fv", "sha256:fv", None),
        CustodyEvent("web:fd", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:fd", "sha256:x", None),
        CustodyEvent("arxiv:pr", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:pr", None, "HTTP Error 404"),
        # web:ru left unverified
    ])


def test_compiled_library_pages_agree_on_the_scope_custody_headline(scrolls_home, capsys):
    # roadmap H97: H95 put a `_Custody:_` scope headline on the compiled group list
    # pages (over the page's members) and H96 on the landing `index.md` (over the
    # rendered library), each built from the shared `custody.custody_headline` and
    # *claimed* to converge with `custody_counts`/`facets`/`doctor` for its scope —
    # but that scope-level convergence is pinned only per-surface in `test_kb.py`.
    # Fold it into the cross-surface invariant: parse the headline off a compiled
    # page and assert its tier/posture totals equal the canonical tally for that
    # page's scope. The scope-level analogue of H91's per-item compiled-page tie.
    main(["init"])
    db = get_paths().db_path
    _seed_compiled_scope_fixture(db)
    capsys.readouterr()

    verdicts = latest_events(db)
    items = list_items(db)
    web_members = [item for item in items if item.source == "web"]

    # the canonical pictures the compiled headlines must reproduce
    web_canonical = custody_counts(web_members, verdicts)
    library_canonical = custody_counts(items, verdicts)  # all items here are rendered
    # sanity: the group-page scope is a proper subset of the whole library
    assert _nonzero(web_canonical["tiers"]) == {"full": 2, "reference": 1}
    assert _nonzero(web_canonical["drift"]) == {"verified": 1, "unverified": 1, "drifted": 1}
    assert _nonzero(library_canonical["tiers"]) == {"full": 2, "partial": 1, "reference": 1}
    assert _nonzero(library_canonical["drift"]) == {
        "verified": 1, "unverified": 1, "drifted": 1, "rotted": 1}

    assert main(["kb"]) == 0
    capsys.readouterr()
    library = get_paths().library_dir

    # 1. the group page (`sources/web.md`) headline == custody_counts(web members)
    #    == facets fidelity/drift scoped to `--source web` — the human-readable
    #    scope summary drilled from, and totalling, the page's own scope
    web_page = (library / "sources" / "web.md").read_text(encoding="utf-8")
    web_headline = _library_headline(web_page)
    assert web_headline["count"] == len(web_members)
    assert web_headline["tiers"] == _nonzero(web_canonical["tiers"])
    assert web_headline["drift"] == _nonzero(web_canonical["drift"])
    web_fidelity = _facet_map(
        compute_facets(db, field="fidelity", source="web")["facets"]["fidelity"])
    web_drift = _facet_map(
        compute_facets(db, field="drift", source="web")["facets"]["drift"])
    assert web_headline["tiers"] == web_fidelity
    assert web_headline["drift"] == web_drift

    # 2. the landing `index.md` headline == custody_counts over the whole rendered
    #    library == `doctor`'s custody aggregate (all items rendered here) == the
    #    whole-library facets — the compiled counterpart of the `status` headline
    index_headline = _library_headline((library / "index.md").read_text(encoding="utf-8"))
    assert index_headline["count"] == len(items)
    assert index_headline["tiers"] == _nonzero(library_canonical["tiers"])
    assert index_headline["drift"] == _nonzero(library_canonical["drift"])
    custody = run_doctor(get_paths())["custody"]
    assert _nonzero(custody["tiers"]) == index_headline["tiers"]
    assert _nonzero(_posture_from_ledger_counts(custody["drift"])) == index_headline["drift"]
    assert index_headline["tiers"] == _facet_map(
        compute_facets(db, field="fidelity")["facets"]["fidelity"])
    assert index_headline["drift"] == _facet_map(
        compute_facets(db, field="drift")["facets"]["drift"])

    # 3. the rollup pages carry no scope headline (roadmap H95 scope boundary), so
    #    the parser returns None — the compiled-surface convergence is exactly the
    #    group pages + the index
    for rollup in ("graph.md", "works.md"):
        assert _library_headline((library / rollup).read_text(encoding="utf-8")) is None


def test_compiled_index_per_source_breakdown_converges_with_doctor_by_source(
    scrolls_home, capsys
):
    # roadmap H145: the landing `index.md` follows its whole-library headline with a
    # `_By source:_` breakdown — the compiled-surface counterpart of the JSON
    # `status` `by_source` (H133) and the `export bundle` briefing (H141), through
    # the same shared `custody.render_custody_by_source`. Fold it into the
    # cross-surface invariant beside the bundle tie above: over the multi-source
    # seed (all rendered, so the index scope == the whole library == doctor's
    # scope) the compiled bullets equal `render_custody_by_source` over *both*
    # `doctor.custody.by_source` and `custody_counts_by_source`, and the headline
    # (the whole-scope sum the per-source lines total) is present too.
    from scrolls.custody import render_custody_by_source

    main(["init"])
    db = get_paths().db_path
    _seed_compiled_scope_fixture(db)  # web (3) + arxiv (1), every item rendered
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}

    # the rendered breakdown is a faithful read of doctor's map and of the tally
    expected = render_custody_by_source(by_source)
    assert expected == render_custody_by_source(custody_counts_by_source(items, verdicts))
    assert expected  # the seed is genuinely multi-source (non-vacuous)

    assert main(["kb"]) == 0
    capsys.readouterr()
    index = (get_paths().library_dir / "index.md").read_text(encoding="utf-8")
    header = index.split("## Sources")[0]
    # every breakdown line (the trailing spacer aside) reads in the compiled index,
    # under the whole-library headline the per-source bullets total
    for line in expected[:-1]:
        assert line in header
    assert custody_headline(items, verdicts) in header
    assert header.index("_Custody:") < header.index("_By source:_")


def test_compiled_group_page_per_source_breakdown_converges_with_doctor_by_source(
    scrolls_home, capsys
):
    # roadmap H152: a multi-source group list page (a category/concept/tag spanning
    # sources) follows its scope headline with the same `_By source:_` breakdown the
    # landing `index.md` (H145), the `export bundle` briefing (H141), and the
    # `context` bundle (H149) carry, through the shared
    # `custody.render_custody_by_source`. Fold it into the cross-surface invariant
    # beside the index tie above: over a multi-source category where every item shares
    # the category (so the page scope == the whole rendered library == doctor's scope)
    # the compiled group-page bullets equal `render_custody_by_source` over *both*
    # `doctor.custody.by_source` and `custody_counts_by_source`, under the page
    # headline they total. The single-source `sources/*.md` pages carry no breakdown
    # (the helper's `<2`-source no-op).
    from scrolls.custody import render_custody_by_source

    main(["init"])
    db = get_paths().db_path
    # category `ml` spans web (full+drifted, reference+never) and arxiv (full+verified);
    # every held item is in `ml`, so `categories/ml.md`'s scope == the whole library
    insert_item(db, _item(
        "web:fd", "ML full drifted", category="ml", stage="rendered",
        markdown_path="scrolls/web/ml-full-drifted.md",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:fd"))
    insert_item(db, _item(
        "web:ru", "ML reference unverified", category="ml", stage="rendered",
        markdown_path="scrolls/web/ml-reference-unverified.md"))  # no content → reference
    insert_item(db, _item(
        "arxiv:fv", "ML full verified", source="arxiv",
        url="https://arxiv.org/abs/fv", category="ml", stage="rendered",
        markdown_path="scrolls/arxiv/ml-full-verified.md",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:fv"))
    record_events(db, [
        CustodyEvent("web:fd", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:fd", "sha256:x", None),
        CustodyEvent("arxiv:fv", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:fv", "sha256:fv", None),
        # web:ru left unverified
    ])
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}

    # the rendered breakdown is a faithful read of doctor's map and of the tally
    expected = render_custody_by_source(by_source)
    assert expected == render_custody_by_source(custody_counts_by_source(items, verdicts))
    assert expected  # the seed is genuinely multi-source (non-vacuous)

    assert main(["kb"]) == 0
    capsys.readouterr()
    library = get_paths().library_dir
    page = (library / "categories" / "ml.md").read_text(encoding="utf-8")
    # every breakdown line (the trailing spacer aside) reads in the compiled group
    # page, under the scope headline the per-source bullets total
    for line in expected[:-1]:
        assert line in page
    assert custody_headline(items, verdicts) in page
    assert page.index("_Custody:") < page.index("_By source:_")
    # a single-source `sources/*.md` page carries the headline but no breakdown
    web_page = (library / "sources" / "web.md").read_text(encoding="utf-8")
    assert "_Custody:" in web_page
    assert "_By source:_" not in web_page


def test_readable_per_source_breakdown_is_byte_identical_across_surfaces(
    scrolls_home, capsys
):
    # roadmap H151: the four tests above each tie *one* readable surface's
    # `_By source:_` breakdown to `doctor`'s `custody.by_source`. This pins the
    # consolidating property *once*: every readable surface that carries the
    # breakdown — the `export bundle` briefing (H141) **and its HTML form**, the
    # model-facing `scrolls context` bundle (`connected`+, H149), the compiled
    # landing `index.md` (H145), and a multi-source compiled group page (H152) —
    # renders byte-identical per-source bullets for the *same* scope, all equal to
    # `render_custody_by_source(doctor.custody.by_source)` and to the same renderer
    # over `custody_counts_by_source`. The readable-line analogue of the JSON
    # `by_source` convergence (`status`/`graph`/`doctor`, H133/H150/H157). One seed
    # gives every surface the same scope: all rendered (compiled index/group page),
    # all category `ml` (group page scope == library), every title "topic" (bundle/
    # context query == library).
    from scrolls.bundle import build_bundle, build_bundle_html
    from scrolls.context import build_context

    main(["init"])
    db = get_paths().db_path
    _seed_unified_per_source_fixture(db)  # web (3) + arxiv (2), all rendered, all `ml`
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}

    # the canonical readable breakdown — doctor's map and the tally render identically
    canonical = render_custody_by_source(by_source)
    assert canonical == render_custody_by_source(custody_counts_by_source(items, verdicts))
    expected_bullets = [line for line in canonical if line.startswith("- `")]
    assert len(expected_bullets) == 2  # genuinely multi-source (non-vacuous)
    assert expected_bullets[0] != expected_bullets[1]  # the two sources' mixes differ

    # compile the library once for the two compiled surfaces
    assert main(["kb"]) == 0
    capsys.readouterr()
    library = get_paths().library_dir
    index_md = (library / "index.md").read_text(encoding="utf-8")
    group_md = (library / "categories" / "ml.md").read_text(encoding="utf-8")

    bundle_md = build_bundle(db, "topic")
    bundle_html = build_bundle_html(db, "topic")
    context_md = build_context(db, "topic", budget="connected")  # the breakdown rides connected+

    surfaces = {
        "bundle-markdown": _by_source_bullets(bundle_md),
        "bundle-html": _html_by_source_bullets(bundle_html),
        "context": _by_source_bullets(context_md),
        "compiled-index": _by_source_bullets(index_md),
        "compiled-group-page": _by_source_bullets(group_md),
    }

    # 1. every readable surface renders the *same* per-source bullets, byte-identical
    #    to the canonical `render_custody_by_source(doctor.custody.by_source)`
    for name, bullets in surfaces.items():
        assert bullets == expected_bullets, f"{name} diverged from the canonical breakdown"

    # 2. each Markdown surface carries the shared scope headline the bullets sit under,
    #    and its per-source bullets sum to that headline's own scope (the surface can't
    #    render bullets over a different scope than the headline above them)
    scope_headline = custody_headline(items, verdicts)
    canonical_total = _sum_by_source_bullets(expected_bullets)
    for name, text in {
        "bundle-markdown": bundle_md,
        "context": context_md,
        "compiled-index": index_md,
        "compiled-group-page": group_md,
    }.items():
        assert scope_headline in text, f"{name} missing the shared scope headline"
        headline = _library_headline(text)
        summed = _sum_by_source_bullets(surfaces[name])
        assert summed["count"] == headline["count"], f"{name} bullets ≠ headline count"
        assert summed["tiers"] == headline["tiers"], f"{name} bullets ≠ headline tiers"
        assert summed["drift"] == headline["drift"], f"{name} bullets ≠ headline drift"
        # and that scope total == doctor's whole-library custody (the module spine)
        assert summed == canonical_total


def test_readable_per_source_coverage_converges_with_the_json_by_source(
    scrolls_home, capsys
):
    # roadmap H158: H151 pins the readable `_By source:_` bullets byte-identical
    # across surfaces (coverage section included by construction); this pins the
    # load-bearing *value* — the readable `coverage V/T` section on each bullet
    # equals the JSON `by_source[S].coverage` (`doctor`'s map and the shared tally's)
    # for that source. The readable-coverage counterpart of the JSON per-source
    # coverage tie (H121), so the readable surfaces an agent skims and the audit can
    # never disagree on how much of a source is checked.
    main(["init"])
    db = get_paths().db_path
    _seed_unified_per_source_fixture(db)  # web (3) + arxiv (2), all rendered, all `ml`
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    canonical = custody_counts_by_source(items, verdicts)
    assert set(by_source) == {"web", "arxiv"}

    bullets = [
        line for line in render_custody_by_source(by_source) if line.startswith("- `")
    ]
    seen = {}
    for bullet in bullets:
        source, *_ = _parse_by_source_bullet(bullet)
        cov = _parse_by_source_coverage(bullet)
        assert cov is not None, f"{source} bullet carries no coverage section"
        # the readable section == doctor's JSON per-source coverage == the tally's
        assert cov == by_source[source]["coverage"]
        assert cov == canonical[source]["coverage"]
        seen[source] = cov
    # the seed: web has 2 hash-bearing held items both verdicted; arxiv one
    # hash-bearing verdicted (its partial-fidelity item is hash-less → excluded)
    assert seen == {
        "web": {"verified": 2, "total": 2},
        "arxiv": {"verified": 1, "total": 1},
    }
    # and the per-source coverage sums to the whole-library recheck coverage (H121)
    hash_bearing = [item for item in items if item.content_hash]
    summed = {"verified": 0, "total": 0}
    for cov in seen.values():
        summed["verified"] += cov["verified"]
        summed["total"] += cov["total"]
    assert summed == recheck_coverage(hash_bearing, verdicts)


_ATTENTION_MD = re.compile(
    r"_Attention: source `([^`]+)` carries the most drift \(([^)]+)\) — "
    r"recheck with `([^`]+)`\._"
)
_ATTENTION_HTML = re.compile(
    r'<p class="custody-attention">Attention: source <code>([^<]+)</code> '
    r"carries the most drift \(([^)]+)\) — recheck with "
    r"<code>([^<]+)</code>\.</p>"
)


def _attention_fields(text, pattern):
    """Parse a readable weakest-source `_Attention:_` line back into a dict.

    Returns ``{source, reason, command}`` (HTML matches are unescaped), or ``None``
    when the surface carries no attention line — so a surface's honest absence and a
    genuine flag are both observable. Mirrors `_library_headline`/`_parse_by_source_
    bullet`: the readable surface is parsed back and compared to the primitive.
    """
    match = pattern.search(text)
    if match is None:
        return None
    source, reason, command = (html.unescape(g) for g in match.groups())
    return {"source": source, "reason": reason, "command": command}


def test_readable_attention_line_converges_across_surfaces_and_the_json_flag(
    scrolls_home, capsys
):
    # roadmap H159: the weakest-source pointer now rides three readable surfaces —
    # the `export bundle` briefing (Markdown + HTML) and the `scrolls context`
    # bundle — each *claimed* to carry the same flag the JSON `status`/`maintain`
    # `attention` does. Fold the readable-line tie into the convergence spine beside
    # the H139 JSON `attention` tie (the readable counterpart): over one multi-source
    # loss seed, every surface's parsed `{source, reason, command}` equals the shared
    # `weakest_source` over the scope's own `custody_counts_by_source`, which equals
    # `weakest_source(doctor.custody.by_source)` and the JSON `status`/`maintain`
    # flag — so the readable line and the JSON flag can never name different sources.
    # (The full field-for-field three-surface invariant is H160; this pins the
    # readable line's identity to the primitive, the H151 readable-breakdown analogue.)
    from scrolls.bundle import build_bundle, build_bundle_html
    from scrolls.context import build_context

    main(["init"])
    db = get_paths().db_path
    _seed_unified_per_source_fixture(db)  # web (1 drifted) + arxiv (1 rotted)
    capsys.readouterr()

    items = list_items(db)
    verdicts = latest_events(db)
    by_source = run_doctor(get_paths())["custody"]["by_source"]
    # the canonical flag — over doctor's map and over the scope's own tally, equal
    flagged = weakest_source(by_source)
    assert flagged == weakest_source(custody_counts_by_source(items, verdicts))
    # non-vacuous: a genuine cross-source pick. web (1 drifted) and arxiv (1 rotted)
    # tie on loss; web carries the lone reference item, so the tie-break names web.
    assert flagged is not None
    assert flagged["source"] == "web"
    assert flagged["reason"] == "1 drifted"
    expected = {
        "source": flagged["source"],
        "reason": flagged["reason"],
        "command": flagged["command"],
    }

    # the canonical readable line the primitive renders (Markdown)
    canonical_line = render_custody_attention(by_source)
    assert canonical_line  # the renderer agrees there is a flag to show

    bundle_md = build_bundle(db, "topic")
    bundle_html = build_bundle_html(db, "topic")
    context_md = build_context(db, "topic", budget="connected")  # rides connected+

    # 1. every readable surface's parsed attention fields == the canonical primitive
    surfaces = {
        "bundle-markdown": _attention_fields(bundle_md, _ATTENTION_MD),
        "bundle-html": _attention_fields(bundle_html, _ATTENTION_HTML),
        "context": _attention_fields(context_md, _ATTENTION_MD),
    }
    for name, fields in surfaces.items():
        assert fields == expected, f"{name} attention diverged from weakest_source"
    # the Markdown surfaces carry the byte-identical canonical line, not just the fields
    for line in canonical_line:
        assert line in bundle_md
        assert line in context_md

    # 2. == the JSON `status` flag (status threads weakest_source over the same audit)
    assert main(["status"]) == 0
    status_attention = json.loads(capsys.readouterr().out)["attention"]
    assert status_attention == flagged
    assert status_attention["source"] == surfaces["bundle-markdown"]["source"]
    assert status_attention["command"] == surfaces["bundle-markdown"]["command"]

    # 3. == the `maintain --no-recheck` report's flag (the scheduled sibling). The
    #    exit mirrors doctor's structural issues (the rendered fixture's markdown
    #    files are absent → missing_scrolls), but the custody `attention` is the same
    #    distillation regardless — the flag, not the exit code, is what converges.
    main(["maintain", "--no-recheck"])
    maintain_attention = json.loads(capsys.readouterr().out)["attention"]
    assert maintain_attention == flagged


def test_readable_attention_line_absent_together_with_the_json_flag(scrolls_home, capsys):
    # the honest-absence counterpart: a clean multi-source scope (≥2 sources, no
    # `drifted`/`rotted`) shows the `_By source:_` split but no `_Attention:_` line on
    # any readable surface — exactly when the JSON `status`/`maintain` flag is null.
    from scrolls.bundle import build_bundle, build_bundle_html
    from scrolls.context import build_context

    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item("web:ok", "Topic web ok", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:wok"))
    insert_item(db, _item("arxiv:ok", "Topic arxiv ok", source="arxiv",
                          url="https://arxiv.org/abs/ok", extracted_text="topic",
                          raw_text="<raw>topic</raw>", content_hash="sha256:aok"))
    record_events(db, [
        CustodyEvent("web:ok", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:wok", "sha256:wok", None),
        # arxiv:ok left unverified — neither source carries loss
    ])
    capsys.readouterr()

    by_source = run_doctor(get_paths())["custody"]["by_source"]
    assert set(by_source) == {"web", "arxiv"}  # ≥2 sources, so the gate is the loss
    assert weakest_source(by_source) is None
    assert render_custody_attention(by_source) == []

    bundle_md = build_bundle(db, "topic")
    assert "_By source:_" in bundle_md  # the multi-source split still renders
    assert _attention_fields(bundle_md, _ATTENTION_MD) is None
    assert _attention_fields(build_bundle_html(db, "topic"), _ATTENTION_HTML) is None
    assert _attention_fields(build_context(db, "topic", budget="connected"),
                             _ATTENTION_MD) is None

    # the JSON flag is null on both surfaces, together with the readable absence
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None
    assert main(["maintain", "--no-recheck"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] is None


# --- readable `_Refresh:_` line ≡ doctor's per-source debt maps (roadmap H178) -
#
# The enrichment/summary-axis sibling of the readable `_Attention:_` tie above:
# the `_Refresh:_` line on the `export bundle`/`scrolls context` briefings names
# the sources whose `classify --stale`/`kb --stale --source <S>` to run, over the
# *same* `stale_*_counts_by_source` builders `doctor`'s `custody.enrichment
# .by_source`/`custody.summaries.by_source` fold — so the readable pointer and the
# structured maps can never name different sources. Pinned over a whole-library
# bundle scope (the query matches every member, so scope == library and the
# scope-consistent line equals the whole-library audit), mutation-checked.

_REFRESH_CLASS_MD = re.compile(r"classifications stale in ([^—]+?) — refresh with")
_REFRESH_SUMM_MD = re.compile(r"summaries stale in ([^—]+?) — refresh with")
_REFRESH_CLASS_HTML = re.compile(r"classifications stale in (.+?) — refresh with")
_REFRESH_SUMM_HTML = re.compile(r"summaries stale in (.+?) — refresh with")


def _refresh_sources(text, pattern):
    """The sorted source names a `_Refresh:_` clause lists, or [] when absent.

    Parses the backtick (Markdown) / `<code>` (HTML) source tokens of one axis's
    clause, so the readable surface is read back and compared to the audit map — the
    refresh-axis counterpart of `_attention_fields`.
    """
    match = pattern.search(text)
    if match is None:
        return []
    clause = match.group(1)
    sources = re.findall(r"`([^`]+)`", clause) + re.findall(r"<code>([^<]+)</code>", clause)
    return sorted(sources)


def test_readable_refresh_line_converges_with_the_doctor_debt_maps(scrolls_home):
    # roadmap H178: every readable briefing's `_Refresh:_` line names exactly the
    # sources doctor's `custody.enrichment.by_source`/`custody.summaries.by_source`
    # do — the readable refresh-axis sibling of the H159 attention tie. Non-vacuous
    # (the enrichment axis names one source, the summary axis two — the H171
    # multi-source attribution) and mutation-checked.
    from scrolls.bundle import build_bundle, build_bundle_html
    from scrolls.context import build_context
    from scrolls.kb import ConceptSummary, save_concept_summary
    from scrolls.kb_llm import eligible_concepts, members_hash

    main(["init"])
    db = get_paths().db_path

    # enrichment debt on `web`: a rules classification under a superseded ruleset
    insert_item(db, _item(
        "web:stale", "Topic stale", source="web", category="tutorial",
        provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": "deadbeef0000"},
        extracted_text="topic", raw_text="<raw>topic</raw>",
        stage="rendered", markdown_path="scrolls/web/stale.md",
        content_hash="sha256:ws"))
    # summary debt on a web+arxiv cluster (attributes to BOTH — the H171 asymmetry).
    # The members carry "topic" so they fall in the bundle's query scope — the
    # briefing's per-source debt is scope-consistent, so the cluster must be in-scope
    # for the whole-library doctor map to equal the scope-consistent line.
    insert_item(db, _item(
        "web:b1", "Topic bm25 one", source="web", concepts=("Bm25",),
        url="https://web.example.com/b1", extracted_text="topic",
        raw_text="<raw>topic</raw>", stage="rendered",
        markdown_path="scrolls/web/b1.md", content_hash="h1"))
    insert_item(db, _item(
        "arxiv:b2", "Topic bm25 two", source="arxiv", concepts=("Bm25",),
        url="https://arxiv.org/abs/b2", extracted_text="topic",
        raw_text="<raw>topic</raw>", stage="rendered",
        markdown_path="scrolls/arxiv/b2.md", content_hash="h2"))
    save_concept_summary(db, ConceptSummary(
        slug="bm25", display="Bm25", summary="Old synthesis.",
        members_hash="stale-old", engine="kb-llm-v1", model="claude-opus-4-8",
        generated_at="2026-06-16T00:00:00+00:00"))

    report = run_doctor(get_paths())["custody"]
    enr_sources = sorted(report["enrichment"]["by_source"])
    summ_sources = sorted(report["summaries"]["by_source"])
    # non-vacuous: the two axes name different source sets
    assert enr_sources == ["web"]
    assert summ_sources == ["arxiv", "web"]

    bundle_md = build_bundle(db, "topic")
    bundle_html = build_bundle_html(db, "topic")
    context_md = build_context(db, "topic", budget="connected")

    # every readable surface names exactly doctor's per-source debt sources
    assert _refresh_sources(bundle_md, _REFRESH_CLASS_MD) == enr_sources
    assert _refresh_sources(bundle_md, _REFRESH_SUMM_MD) == summ_sources
    assert _refresh_sources(context_md, _REFRESH_CLASS_MD) == enr_sources
    assert _refresh_sources(context_md, _REFRESH_SUMM_MD) == summ_sources
    assert _refresh_sources(bundle_html, _REFRESH_CLASS_HTML) == enr_sources
    assert _refresh_sources(bundle_html, _REFRESH_SUMM_HTML) == summ_sources

    # mutation check: refresh arxiv's cluster (members_hash → live) so the summary
    # is current; the summary axis then drops arxiv, and the line follows the map
    eligible = eligible_concepts(list_items(db))
    save_concept_summary(db, ConceptSummary(
        slug="bm25", display="Bm25", summary="Fresh synthesis.",
        members_hash=members_hash(eligible["bm25"]["items"]), engine="kb-llm-v1",
        model="claude-opus-4-8", generated_at="2026-06-17T00:00:00+00:00"))
    report2 = run_doctor(get_paths())["custody"]
    assert report2["summaries"]["by_source"] == {}  # the cluster is current now
    assert "summaries stale in" not in build_bundle(db, "topic")
    # the enrichment axis is untouched — web's stale classification still shows
    assert _refresh_sources(build_bundle(db, "topic"), _REFRESH_CLASS_MD) == ["web"]


def test_compiled_pages_carry_the_action_lines_converging_with_doctor(
    scrolls_home, capsys
):
    # roadmap H184: the compiled `library/` index + group pages now carry the
    # readable `_Attention:_` (H159) and `_Refresh:_` (H178) action-pointer lines
    # beside the `_By source:_` map (H145/H152), through the SAME shared renderers.
    # Fold the compiled surfaces into the cross-surface convergence beside the
    # bundle/context ties above: over one multi-source seed (drift + a stale
    # classification + a stale multi-source summary, every item rendered so the
    # compiled pages cover it), the compiled `_Attention:_` line names
    # `weakest_source(doctor.by_source)` == the JSON `status` flag, and the compiled
    # `_Refresh:_` clauses name exactly doctor's `enrichment.by_source`/
    # `summaries.by_source` keys. Non-vacuous (the two refresh axes name different
    # source sets) and mutation-checked.
    from scrolls.kb import ConceptSummary, save_concept_summary

    main(["init"])
    db = get_paths().db_path
    # web carries the only drift (the `_Attention:_` weakest source) and a stale
    # classification (enrichment debt {web}); the web+arxiv concept `bm25` has a
    # stale stored summary (summary debt {arxiv, web} — the H171 attribution). Every
    # item is in category `ml` and rendered, so the index/group page scopes == the
    # whole rendered library == doctor's scope.
    insert_item(db, _item(
        "web:fd", "ML full drifted", category="ml", stage="rendered",
        concepts=("Bm25",), markdown_path="scrolls/web/fd.md",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:fd",
        provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": "deadbeef0000"}))
    insert_item(db, _item(
        "arxiv:b2", "ML arxiv two", source="arxiv", category="ml", stage="rendered",
        concepts=("Bm25",), url="https://arxiv.org/abs/b2",
        markdown_path="scrolls/arxiv/b2.md", extracted_text="body",
        raw_text="<raw>body</raw>", content_hash="sha256:b2"))
    record_events(db, [
        CustodyEvent("web:fd", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:fd", "sha256:x", None),
        # arxiv:b2 left unverified — only web carries actionable loss
    ])
    save_concept_summary(db, ConceptSummary(
        slug="bm25", display="Bm25", summary="Old synthesis.",
        members_hash="stale-old", engine="kb-llm-v1", model="claude-opus-4-8",
        generated_at="2026-06-16T00:00:00+00:00"))
    capsys.readouterr()

    report = run_doctor(get_paths())["custody"]
    flagged = weakest_source(report["by_source"])
    enr_sources = sorted(report["enrichment"]["by_source"])
    summ_sources = sorted(report["summaries"]["by_source"])
    # non-vacuous: attention names web; the two refresh axes name different sets
    assert flagged is not None and flagged["source"] == "web"
    assert enr_sources == ["web"]
    assert summ_sources == ["arxiv", "web"]
    expected_attention = {k: flagged[k] for k in ("source", "reason", "command")}

    assert main(["kb"]) == 0
    capsys.readouterr()
    library = get_paths().library_dir
    index_header = (library / "index.md").read_text(
        encoding="utf-8").split("## Sources")[0]
    group_page = (library / "categories" / "ml.md").read_text(encoding="utf-8")

    # both compiled surfaces carry all three lines, in order, converging with doctor
    for surface in (index_header, group_page):
        assert _attention_fields(surface, _ATTENTION_MD) == expected_attention
        assert _refresh_sources(surface, _REFRESH_CLASS_MD) == enr_sources
        assert _refresh_sources(surface, _REFRESH_SUMM_MD) == summ_sources
        assert (surface.index("_Custody:") < surface.index("_Attention:")
                < surface.index("_Refresh:") < surface.index("_By source:_"))

    # == the JSON `status` flag — the compiled readable line and the flag agree
    assert main(["status"]) == 0
    assert json.loads(capsys.readouterr().out)["attention"] == flagged

    # mutation check: re-classify web:fd under the live ruleset → the enrichment axis
    # drops web; the compiled `_Refresh:_` line follows the map (the summary axis,
    # untouched, still names both sources)
    import dataclasses

    from scrolls.classify import RULESET_FINGERPRINT
    from scrolls.items import get_item, update_item
    web_fd = get_item(db, "web:fd")
    update_item(db, dataclasses.replace(web_fd, provenance={
        "classified_by": "rules-v1", "classified_basis": "weak-source",
        "classified_ruleset": RULESET_FINGERPRINT}))
    assert main(["kb"]) == 0
    capsys.readouterr()
    refreshed = (library / "categories" / "ml.md").read_text(encoding="utf-8")
    assert _refresh_sources(refreshed, _REFRESH_CLASS_MD) == []  # enrichment cleared
    assert _refresh_sources(refreshed, _REFRESH_SUMM_MD) == ["arxiv", "web"]


def _seed_single_source_refresh_fixture(db):
    """A multi-source library whose refresh debt splits so each `sources/*.md` page's
    `_Refresh:_` reads exactly its own single-source scope (roadmap H193).

    `web` carries a stale rules classification (enrichment debt {web}) **and** a
    *within-source* stale summary cluster — the web-only concept `WebOnly`, two
    rendered web members under a superseded `members_hash` (summary debt {web} that
    survives a single-source scope, ≥ `MIN_MEMBERS` web members). The concept `Bm25`
    spans one web + one arxiv member with a stale stored summary: at the whole-library
    scope it is eligible (2 members) and attributes to {arxiv, web} (the H171
    multi-source attribution), but under *either* single-source scope it narrows below
    `MIN_MEMBERS` and drops out — so `web`'s summary debt collapses to the WebOnly
    cluster alone and `arxiv`'s only summary participation vanishes (its page is then
    honestly clean). Every item is rendered, so the compiled `sources/<S>.md` page's
    own-member scope == `doctor --source <S>`'s held set.
    """
    from scrolls.kb import ConceptSummary, save_concept_summary

    # web: a rules classification under a superseded ruleset → enrichment debt {web}
    insert_item(db, _item(
        "web:stale", "Topic stale classification", source="web", category="tutorial",
        provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": "deadbeef0000"},
        extracted_text="topic", raw_text="<raw>topic</raw>", stage="rendered",
        markdown_path="scrolls/web/stale.md", content_hash="sha256:ws"))
    # web-only concept `WebOnly`: two rendered web members → eligible at every scope
    insert_item(db, _item(
        "web:wo1", "Topic web-only one", source="web", concepts=("WebOnly",),
        url="https://web.example.com/wo1", extracted_text="topic",
        raw_text="<raw>topic</raw>", stage="rendered",
        markdown_path="scrolls/web/wo1.md", content_hash="sha256:wo1"))
    insert_item(db, _item(
        "web:wo2", "Topic web-only two", source="web", concepts=("WebOnly",),
        url="https://web.example.com/wo2", extracted_text="topic",
        raw_text="<raw>topic</raw>", stage="rendered",
        markdown_path="scrolls/web/wo2.md", content_hash="sha256:wo2"))
    # multi-source concept `Bm25`: one web + one arxiv member — narrows below
    # MIN_MEMBERS under either single-source scope
    insert_item(db, _item(
        "web:bm1", "Topic bm25 web", source="web", concepts=("Bm25",),
        url="https://web.example.com/bm1", extracted_text="topic",
        raw_text="<raw>topic</raw>", stage="rendered",
        markdown_path="scrolls/web/bm1.md", content_hash="sha256:bm1"))
    insert_item(db, _item(
        "arxiv:bm2", "Topic bm25 arxiv", source="arxiv", concepts=("Bm25",),
        url="https://arxiv.org/abs/bm2", extracted_text="topic",
        raw_text="<raw>topic</raw>", stage="rendered",
        markdown_path="scrolls/arxiv/bm2.md", content_hash="sha256:bm2"))
    # both clusters carry a stale stored summary (a superseded members_hash)
    for slug, display in (("webonly", "WebOnly"), ("bm25", "Bm25")):
        save_concept_summary(db, ConceptSummary(
            slug=slug, display=display, summary="Old synthesis.",
            members_hash="stale-old", engine="kb-llm-v1", model="claude-opus-4-8",
            generated_at="2026-06-16T00:00:00+00:00"))


def test_single_source_page_refresh_line_converges_with_doctor_source_debt(
    scrolls_home, capsys
):
    # roadmap H193: H184 put the readable action lines on the compiled `library/`
    # index/group pages and H190 pinned their honest *absence* (a clean page omits
    # them). The positive companion for the single-source `sources/<S>.md` pages —
    # which carry the `_Refresh:_` line (it has no single-source gate) but never
    # `_Attention:_`/`_By source:_` (the `<2`-source no-ops) — is that the page's
    # `_Refresh:_` clauses name exactly `doctor --source <S>`'s
    # `enrichment.by_source`/`summaries.by_source` keys *for the page's own scope*.
    # The load-bearing subtlety pinned positively: a multi-source concept's stale
    # summary attributes to several sources at the whole-library scope (the H171
    # attribution) but narrows below `MIN_MEMBERS` under a single-source scope and
    # drops out — so the single-source page's summary axis reflects only the
    # within-source clusters, exactly as `doctor --source <S>` does. Non-vacuous (web
    # carries both axes) and mutation-checked (a refresh clears the named clause).
    main(["init"])
    db = get_paths().db_path
    _seed_single_source_refresh_fixture(db)
    capsys.readouterr()

    # whole-library: web carries the only enrichment debt; the summary axis names
    # BOTH sources — the web-only `WebOnly` cluster {web} plus the multi-source `Bm25`
    # cluster {arxiv, web} (the H171 attribution)
    whole = run_doctor(get_paths())["custody"]
    assert sorted(whole["enrichment"]["by_source"]) == ["web"]
    assert sorted(whole["summaries"]["by_source"]) == ["arxiv", "web"]

    # scoped: under a single-source scope the multi-source `Bm25` cluster narrows
    # below MIN_MEMBERS and drops out — so web's summary debt is the WebOnly cluster
    # alone ({web: 1}, NOT {web: 2}) and arxiv's only summary participation vanishes
    web_doctor = run_doctor(get_paths(), source="web")["custody"]
    arxiv_doctor = run_doctor(get_paths(), source="arxiv")["custody"]
    assert web_doctor["enrichment"]["by_source"] == {"web": 1}
    assert web_doctor["summaries"]["by_source"] == {"web": 1}  # Bm25 narrowed out
    assert arxiv_doctor["enrichment"]["by_source"] == {}
    assert arxiv_doctor["summaries"]["by_source"] == {}        # Bm25 narrowed out

    assert main(["kb"]) == 0
    capsys.readouterr()
    library = get_paths().library_dir
    web_page = (library / "sources" / "web.md").read_text(encoding="utf-8")
    arxiv_page = (library / "sources" / "arxiv.md").read_text(encoding="utf-8")

    # 1. `sources/web.md`: the `_Refresh:_` clauses name exactly doctor --source web's
    #    debt-map keys for the page's own scope, on both axes
    assert (_refresh_sources(web_page, _REFRESH_CLASS_MD)
            == sorted(web_doctor["enrichment"]["by_source"]) == ["web"])
    assert (_refresh_sources(web_page, _REFRESH_SUMM_MD)
            == sorted(web_doctor["summaries"]["by_source"]) == ["web"])
    # the single-source page carries the headline + the `_Refresh:_` pointer but
    # never the `<2`-source no-op action/breakdown lines
    assert "_Custody:" in web_page
    assert "_Refresh:" in web_page
    assert "_Attention:" not in web_page
    assert "_By source:_" not in web_page

    # 2. `sources/arxiv.md`: arxiv's only debt was the multi-source `Bm25` cluster,
    #    which narrowed out — so the page is honestly clean (no `_Refresh:_` line),
    #    converging with doctor --source arxiv's empty debt maps (the single-source
    #    page sibling of the H190 honest absence)
    assert (_refresh_sources(arxiv_page, _REFRESH_CLASS_MD)
            == sorted(arxiv_doctor["enrichment"]["by_source"]) == [])
    assert (_refresh_sources(arxiv_page, _REFRESH_SUMM_MD)
            == sorted(arxiv_doctor["summaries"]["by_source"]) == [])
    assert "_Custody:" in arxiv_page  # the scope headline is always present
    assert "_Refresh:" not in arxiv_page
    assert "_Attention:" not in arxiv_page
    assert "_By source:_" not in arxiv_page

    # mutation check: re-classify web:stale under the live ruleset → the enrichment
    # axis clears; `sources/web.md`'s `_Refresh:_` line drops its classifications
    # clause and keeps the summaries clause (WebOnly is untouched), still converging
    # with doctor --source web — proving the clauses are derived, not coincidental
    import dataclasses

    from scrolls.classify import RULESET_FINGERPRINT
    from scrolls.items import get_item, update_item
    web_stale = get_item(db, "web:stale")
    update_item(db, dataclasses.replace(web_stale, provenance={
        "classified_by": "rules-v1", "classified_basis": "weak-source",
        "classified_ruleset": RULESET_FINGERPRINT}))
    assert main(["kb"]) == 0
    capsys.readouterr()
    web_doctor2 = run_doctor(get_paths(), source="web")["custody"]
    assert web_doctor2["enrichment"]["by_source"] == {}        # enrichment cleared
    assert web_doctor2["summaries"]["by_source"] == {"web": 1}  # summary untouched
    refreshed = (library / "sources" / "web.md").read_text(encoding="utf-8")
    assert (_refresh_sources(refreshed, _REFRESH_CLASS_MD)
            == sorted(web_doctor2["enrichment"]["by_source"]) == [])
    assert (_refresh_sources(refreshed, _REFRESH_SUMM_MD)
            == sorted(web_doctor2["summaries"]["by_source"]) == ["web"])
    assert "_Refresh:" in refreshed  # the line survives (the summary axis remains)


# --- the two action lines read byte-identical across the readable surfaces ----
#
# roadmap H188: H151 pins the `_By source:_` breakdown byte-identical across the
# readable surfaces; this extends that posture to the two *action* lines H184 put
# on the compiled pages beside the bundle/context briefings — the drift
# `_Attention:_` (H159) and the refresh `_Refresh:_` (H178). The H159/H178 ties
# above parse each line back to its primitive *per surface*; this pins the
# consolidating property *once*: over a scope identical across every Markdown
# surface, each action line is character-for-character the same string — so the
# one shared `render_custody_attention`/`render_custody_refresh` is the only
# source of the wording, and no surface can drift in punctuation or phrasing.

_ATTENTION_LINE = re.compile(r"^_Attention: .*?\._$", re.MULTILINE)
_REFRESH_LINE = re.compile(r"^_Refresh: .*?\._$", re.MULTILINE)


def _action_line(text, pattern):
    """The full `_Attention:_` / `_Refresh:_` line a surface renders, or None.

    Unlike `_attention_fields`/`_refresh_sources` (which decompose a line into the
    structured fields each axis tie compares), this returns the *whole* rendered
    line verbatim, so two surfaces can be compared byte-for-byte.
    """
    match = pattern.search(text)
    return match.group(0) if match else None


def _seed_action_line_fixture(db):
    """One multi-source scope carrying BOTH action-line bases over one shared scope.

    `web` carries the only drift (so the `_Attention:_` weakest source is web) and a
    rules classification under a superseded ruleset (enrichment debt {web}); the
    web+arxiv concept `Bm25` has a stale stored summary (summary debt {arxiv, web} —
    the H171 multi-source attribution). Every item is category `ml`, rendered, and
    carries "topic", so the bundle/context query, the compiled `index.md` (whole
    rendered library) and the compiled `categories/ml.md` group page all scope to the
    *same* item set — the precondition for a byte-identical action line.
    """
    from scrolls.kb import ConceptSummary, save_concept_summary

    insert_item(db, _item(
        "web:fd", "Topic web drifted", category="ml", stage="rendered",
        concepts=("Bm25",), markdown_path="scrolls/web/fd.md",
        extracted_text="topic body", raw_text="<raw>topic body</raw>",
        content_hash="sha256:fd",
        provenance={"classified_by": "rules-v1", "classified_basis": "weak-source",
                    "classified_ruleset": "deadbeef0000"}))
    insert_item(db, _item(
        "arxiv:b2", "Topic arxiv two", source="arxiv", category="ml",
        stage="rendered", concepts=("Bm25",), url="https://arxiv.org/abs/b2",
        markdown_path="scrolls/arxiv/b2.md", extracted_text="topic body",
        raw_text="<raw>topic body</raw>", content_hash="sha256:b2"))
    record_events(db, [
        CustodyEvent("web:fd", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:fd", "sha256:x", None),
        # arxiv:b2 left unverified — only web carries actionable drift
    ])
    save_concept_summary(db, ConceptSummary(
        slug="bm25", display="Bm25", summary="Old synthesis.",
        members_hash="stale-old", engine="kb-llm-v1", model="claude-opus-4-8",
        generated_at="2026-06-16T00:00:00+00:00"))


def test_action_lines_are_byte_identical_across_readable_surfaces(scrolls_home, capsys):
    # roadmap H188: over one unified scope (identical across the bundle query, the
    # context query, the compiled index, and a compiled group page) each action line
    # reads character-for-character the same on every Markdown surface and equals
    # render_custody_attention/render_custody_refresh over the shared scope. The
    # action-line analogue of H151's byte-identical `_By source:_` invariant.
    from scrolls.bundle import build_bundle
    from scrolls.context import build_context

    main(["init"])
    db = get_paths().db_path
    _seed_action_line_fixture(db)
    capsys.readouterr()

    report = run_doctor(get_paths())["custody"]
    # the canonical lines the shared renderers produce over doctor's whole-library maps
    canonical_attention = render_custody_attention(report["by_source"])
    canonical_refresh = render_custody_refresh(
        report["enrichment"]["by_source"], report["summaries"]["by_source"])
    # non-vacuous: both action lines genuinely have a basis to render
    assert canonical_attention and canonical_refresh
    attention_line = canonical_attention[0]
    refresh_line = canonical_refresh[0]
    assert "`web`" in attention_line and "1 drifted" in attention_line
    assert "classifications stale in `web`" in refresh_line
    assert "summaries stale in `arxiv`, `web`" in refresh_line  # the H171 attribution

    assert main(["kb"]) == 0
    capsys.readouterr()
    library = get_paths().library_dir
    surfaces = {
        "bundle-markdown": build_bundle(db, "topic"),
        "context": build_context(db, "topic", budget="connected"),
        "compiled-index": (library / "index.md").read_text(encoding="utf-8"),
        "compiled-group-page": (library / "categories" / "ml.md").read_text(
            encoding="utf-8"),
    }
    for name, text in surfaces.items():
        assert _action_line(text, _ATTENTION_LINE) == attention_line, \
            f"{name} attention line diverged from the shared renderer"
        assert _action_line(text, _REFRESH_LINE) == refresh_line, \
            f"{name} refresh line diverged from the shared renderer"

    # mutation check: re-classify web:fd under the live ruleset → the enrichment axis
    # clears, so the `_Refresh:_` line drops its classifications clause. Every surface
    # re-derives and stays byte-identical to the new canonical (the summary axis is
    # untouched) — proving the lines are genuinely derived, not coincidentally equal.
    import dataclasses

    from scrolls.classify import RULESET_FINGERPRINT
    from scrolls.items import get_item, update_item
    web_fd = get_item(db, "web:fd")
    update_item(db, dataclasses.replace(web_fd, provenance={
        "classified_by": "rules-v1", "classified_basis": "weak-source",
        "classified_ruleset": RULESET_FINGERPRINT}))
    assert main(["kb"]) == 0
    capsys.readouterr()
    report2 = run_doctor(get_paths())["custody"]
    refresh_line2 = render_custody_refresh(
        report2["enrichment"]["by_source"], report2["summaries"]["by_source"])[0]
    assert "classifications stale in" not in refresh_line2  # enrichment cleared
    assert "summaries stale in `arxiv`, `web`" in refresh_line2  # summary untouched
    assert refresh_line2 != refresh_line  # the line genuinely changed
    surfaces2 = {
        "bundle-markdown": build_bundle(db, "topic"),
        "context": build_context(db, "topic", budget="connected"),
        "compiled-index": (library / "index.md").read_text(encoding="utf-8"),
        "compiled-group-page": (library / "categories" / "ml.md").read_text(
            encoding="utf-8"),
    }
    for name, text in surfaces2.items():
        assert _action_line(text, _REFRESH_LINE) == refresh_line2, \
            f"{name} refresh line diverged after the data changed"


def test_action_line_content_parity_on_the_html_bundle_form(scrolls_home, capsys):
    # roadmap H192: H188 pins the two action lines (`_Attention:_` H159, `_Refresh:_`
    # H178) byte-identical across the *Markdown* surfaces. The HTML bundle renders the
    # same pointers as `<p class="custody-attention">`/`<p class="custody-refresh">`, so
    # it can never be *string*-identical to the Markdown — but its *content* must not
    # diverge. Over the same `_seed_action_line_fixture` scope, pin that the HTML form
    # names the same source/reason/recheck-command on the attention axis and the same
    # per-axis source list on the refresh axis as the Markdown form (and the canonical
    # primitive) — the action-line analogue of H151's `_html_by_source_bullets` content
    # tie. Non-vacuous (both axes present) and mutation-checked (perturbing the data
    # moves both forms together).
    from scrolls.bundle import build_bundle, build_bundle_html

    main(["init"])
    db = get_paths().db_path
    _seed_action_line_fixture(db)  # web: drift + enrichment debt; Bm25: summary debt
    capsys.readouterr()

    # the canonical fields the shared renderers/audit produce over the whole library
    report = run_doctor(get_paths())["custody"]
    canonical_attention = _attention_fields(
        render_custody_attention(report["by_source"])[0], _ATTENTION_MD)
    enr_sources = sorted(report["enrichment"]["by_source"])
    summ_sources = sorted(report["summaries"]["by_source"])
    # non-vacuous: both action axes genuinely have a basis to render
    assert canonical_attention == {
        "source": "web", "reason": "1 drifted",
        "command": "scrolls verify --source web",
    }
    assert enr_sources == ["web"]
    assert summ_sources == ["arxiv", "web"]  # the H171 multi-source attribution

    bundle_md = build_bundle(db, "topic")
    bundle_html = build_bundle_html(db, "topic")

    # 1. the attention line: the HTML form's parsed {source, reason, command} equals
    #    the Markdown form's and the canonical primitive — same flag, two renderings
    md_attention = _attention_fields(bundle_md, _ATTENTION_MD)
    html_attention = _attention_fields(bundle_html, _ATTENTION_HTML)
    assert html_attention is not None  # the HTML form genuinely carries the line
    assert html_attention == md_attention == canonical_attention

    # 2. the refresh line: the HTML form's per-axis source lists equal the Markdown's
    #    and the doctor debt maps — the two forms name the same source(s) per axis
    for axis, md_pat, html_pat, expected in (
        ("classifications", _REFRESH_CLASS_MD, _REFRESH_CLASS_HTML, enr_sources),
        ("summaries", _REFRESH_SUMM_MD, _REFRESH_SUMM_HTML, summ_sources),
    ):
        md_sources = _refresh_sources(bundle_md, md_pat)
        html_sources = _refresh_sources(bundle_html, html_pat)
        assert html_sources, f"{axis} clause absent on the HTML form"
        assert html_sources == md_sources == expected, f"{axis} HTML diverged from Markdown"

    # mutation check: re-classify web:fd under the live ruleset → the enrichment axis
    # clears. Both forms drop the classifications clause together (the summary axis is
    # untouched), proving the two renderings are genuinely derived from the same maps,
    # not coincidentally equal over this one fixture.
    import dataclasses

    from scrolls.classify import RULESET_FINGERPRINT
    from scrolls.items import get_item, update_item
    web_fd = get_item(db, "web:fd")
    update_item(db, dataclasses.replace(web_fd, provenance={
        "classified_by": "rules-v1", "classified_basis": "weak-source",
        "classified_ruleset": RULESET_FINGERPRINT}))

    bundle_md2 = build_bundle(db, "topic")
    bundle_html2 = build_bundle_html(db, "topic")
    # the classifications clause is gone on *both* forms (enrichment debt cleared)
    assert _refresh_sources(bundle_md2, _REFRESH_CLASS_MD) == []
    assert _refresh_sources(bundle_html2, _REFRESH_CLASS_HTML) == []
    # the summaries axis is untouched and still agrees across the two forms
    assert (_refresh_sources(bundle_html2, _REFRESH_SUMM_HTML)
            == _refresh_sources(bundle_md2, _REFRESH_SUMM_MD) == summ_sources)
    # the attention axis (drift, not enrichment) is untouched and still agrees too
    assert (_attention_fields(bundle_html2, _ATTENTION_HTML)
            == _attention_fields(bundle_md2, _ATTENTION_MD) == canonical_attention)


def _parse_attention_reason(reason):
    """Decompose a `_Attention:_` line's reason into a `{drifted, rotted}` loss map.

    The reason is the flagged source's non-zero loss postures in canonical order —
    ``"1 drifted, 1 rotted"`` (or a single ``"2 drifted"``) — the readable rendering
    of the JSON flag's `drift` block (`_attention_reason`). This reads it back into
    the structured ``{drifted, rotted}`` integers, zeros filled so the shape is
    stable, so the readable loss can be compared field-for-field against the JSON
    flag's `drift["drifted"]`/`drift["rotted"]` (roadmap H160).
    """
    counts = {"drifted": 0, "rotted": 0}
    for piece in reason.split(", "):
        value, posture = piece.split(" ", 1)
        counts[posture] = int(value)
    return counts


def _readable_full_shape(text, pattern, bullets):
    """Distil a readable surface's weakest-source flag to the JSON flag's full shape.

    Reads the `_Attention:_` line (source / loss reason / recheck command) and folds
    in the flagged source's `_By source:_` ``coverage V/T`` section (H158) — so the
    readable surface, across its two custody members (the attention line + the
    per-source breakdown), carries the *same* ``{source, drifted, rotted, coverage,
    command}`` the JSON `attention` flag does. Returns ``None`` when the surface shows
    no attention line (honest absence) — the readable counterpart of a `null` JSON
    flag. The H160 full field-for-field counterpart of `_attention_fields` (which
    stops at the line's `{source, reason, command}`).
    """
    fields = _attention_fields(text, pattern)
    if fields is None:
        return None
    loss = _parse_attention_reason(fields["reason"])
    coverage = None
    for bullet in bullets:
        if _parse_by_source_bullet(bullet)[0] == fields["source"]:
            coverage = _parse_by_source_coverage(bullet)
            break
    return {
        "source": fields["source"],
        "drifted": loss["drifted"],
        "rotted": loss["rotted"],
        "coverage": coverage,
        "command": fields["command"],
    }


def _json_full_shape(flag):
    """The same ``{source, drifted, rotted, coverage, command}`` from a JSON flag.

    Projects a JSON `attention` flag (`status`/`maintain`, the coverage-bearing
    shape) to the five fields the readable surface can expose, so the readable
    distillation and the JSON flag compare field-for-field (roadmap H160). ``None``
    passes through (honest absence on both sides).
    """
    if flag is None:
        return None
    return {
        "source": flag["source"],
        "drifted": flag["drift"]["drifted"],
        "rotted": flag["drift"]["rotted"],
        "coverage": flag["coverage"],
        "command": flag["command"],
    }


def _seed_full_shape_loss(db):
    """A multi-source loss seed whose weakest source is non-vacuous on every field.

    The H159 seed flags a source with a single-posture reason (``1 drifted``) over a
    full ``2/2`` coverage — enough to tie the line's *identity* to the primitive, but
    several H160 fields (the rotted leg, a partial coverage) read a trivial default.
    This seed makes the weakest source carry **both** a drifted and a rotted item (a
    two-posture reason) over a **partial** ``2/3`` coverage, so the full-shape
    field-for-field tie — and its mutation check — exercises every field with a
    distinct, non-default value.

    web (the weakest source): a drifted full item, a rotted full item, a
    never-rechecked full item (→ coverage 2/3), and a reference-only pointer. arxiv
    (clean): a verified full item and a partial item. So web's flag is
    ``1 drifted, 1 rotted`` over coverage ``2/3``; arxiv carries zero loss — web is
    the unambiguous weakest source on a genuinely structured flag. Every title carries
    "topic" so the query-scoped bundle/context scope is the whole library (the
    readable and JSON flags share one scope).
    """
    insert_item(db, _item(
        "web:drift", "Topic web drift",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:wd"))
    insert_item(db, _item(
        "web:rot", "Topic web rot",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:wr"))
    insert_item(db, _item(
        "web:fresh", "Topic web fresh",  # hash-bearing, never re-checked → coverage 2/3
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:wfr"))
    insert_item(db, _item("web:ref", "Topic web pointer", stage="detected"))  # reference
    insert_item(db, _item(
        "arxiv:full", "Topic arxiv full", source="arxiv",
        url="https://arxiv.org/abs/full",
        extracted_text="topic", raw_text="<raw>topic</raw>", content_hash="sha256:af"))
    insert_item(db, _item(
        "arxiv:partial", "Topic arxiv partial", source="arxiv",
        url="https://arxiv.org/abs/partial", extracted_text="topic"))  # no hash → partial
    record_events(db, [
        CustodyEvent("web:drift", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:wd", "sha256:x", None),
        CustodyEvent("web:rot", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:wr", None, "HTTP Error 404"),
        CustodyEvent("arxiv:full", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:af", "sha256:af", None),
        # web:fresh, web:ref, arxiv:partial left unverified
    ])


def test_attention_flag_full_shape_converges_field_for_field(scrolls_home, capsys):
    # roadmap H160: the weakest-source `attention` flag rides three surfaces — JSON
    # `status` (H139), JSON `maintain` (H119/H137), and the readable bundle/context
    # `_Attention:_` line (H159) — each *claimed* to carry the same `{source, drifted,
    # rotted, coverage, command}` distilled from doctor's `custody.by_source`. H159's
    # tie pins the readable line's source/reason/command to the primitive; this is the
    # *full field-for-field* invariant (the H151/H157 readable+JSON pattern): over a
    # loss seed whose weakest source carries BOTH drifted and rotted over a *partial*
    # coverage (so every field is non-trivial), the readable surface distilled (the
    # `_Attention:_` line's source/loss/command PLUS the flagged source's `_By source:_`
    # coverage section, H158) equals the JSON `status` and `maintain` flags field-for-
    # field, all equal `weakest_source(doctor.custody.by_source)` — mutation-checked, so
    # perturbing any one field of any surface's distillation breaks the tie.
    from scrolls.bundle import build_bundle, build_bundle_html
    from scrolls.context import build_context

    main(["init"])
    db = get_paths().db_path
    _seed_full_shape_loss(db)
    capsys.readouterr()

    by_source = run_doctor(get_paths())["custody"]["by_source"]
    flagged = weakest_source(by_source)
    # the canonical full shape — non-vacuous on EVERY field the surfaces compare: web
    # carries both a drifted AND a rotted item (a two-posture reason) over a partial
    # 2/3 coverage, so no field is a trivial 0 / single-posture / full-coverage default.
    assert flagged is not None
    assert flagged["source"] == "web"
    assert flagged["drift"]["drifted"] == 1 and flagged["drift"]["rotted"] == 1
    assert flagged["coverage"] == {"verified": 2, "total": 3}
    canonical = _json_full_shape(flagged)
    assert canonical == {
        "source": "web", "drifted": 1, "rotted": 1,
        "coverage": {"verified": 2, "total": 3},
        "command": "scrolls verify --source web",
    }

    # the readable surfaces (Markdown bundle, HTML bundle, context bundle) — the
    # bundle scope is the whole library (every title carries "topic"), so the readable
    # flag and the JSON flag distil one scope.
    bundle_md = build_bundle(db, "topic")
    bundle_html = build_bundle_html(db, "topic")
    context_md = build_context(db, "topic", budget="connected")  # rides connected+

    readable = {
        "bundle-markdown": _readable_full_shape(
            bundle_md, _ATTENTION_MD, _by_source_bullets(bundle_md)),
        "bundle-html": _readable_full_shape(
            bundle_html, _ATTENTION_HTML, _html_by_source_bullets(bundle_html)),
        "context": _readable_full_shape(
            context_md, _ATTENTION_MD, _by_source_bullets(context_md)),
    }
    # 1. every readable surface distils to the SAME full shape as the canonical flag,
    #    and the coverage leg is genuinely read off the surface (not an absent None)
    for name, shape in readable.items():
        assert shape == canonical, f"{name} full-shape diverged from weakest_source"
        assert shape["coverage"] == {"verified": 2, "total": 3}, name

    # 2. == the JSON `status` flag distilled, field for field
    assert main(["status"]) == 0
    status_flag = json.loads(capsys.readouterr().out)["attention"]
    assert _json_full_shape(status_flag) == canonical

    # 3. == the `maintain --no-recheck` flag distilled (the scheduled sibling) —
    #    `--no-recheck` keeps the ledger pristine so it reads the same state
    assert main(["maintain", "--no-recheck"]) == 0
    maintain_flag = json.loads(capsys.readouterr().out)["attention"]
    assert _json_full_shape(maintain_flag) == canonical

    # 4. teeth: the agreement is not vacuous — perturbing any ONE field of the
    #    canonical shape breaks the tie with every surface, so a real desync in any
    #    distillation (readable line, coverage bullet, or JSON flag) fails here.
    md_shape = readable["bundle-markdown"]
    status_shape = _json_full_shape(status_flag)
    for field, bad in (
        ("source", "arxiv"),
        ("drifted", 2),
        ("rotted", 0),
        ("coverage", {"verified": 3, "total": 3}),
        ("command", "scrolls verify --source arxiv"),
    ):
        perturbed = {**canonical, field: bad}
        assert perturbed != md_shape, field
        assert perturbed != status_shape, field


def _seed_marker_fixture(db):
    """Four held, rendered scrolls (markdown_path set so the KB includes them),
    one per `(fidelity, drift)` pair the compiled-page marker must show.

    Spans the fidelity axis (`full`/`partial`/`reference`) crossed with three
    drift verdicts plus a never-checked item — so the parsed marker exercises
    both halves of the H89 marker against the canonical primitives. All source
    ``web``, so every item lands on the one `sources/web.md` list page.
    """
    insert_item(db, _item(
        "web:fv", "Marker full verified", stage="rendered",
        markdown_path="scrolls/web/marker-full-verified.md",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:fv"))
    insert_item(db, _item(
        "web:fd", "Marker full drifted", stage="rendered",
        markdown_path="scrolls/web/marker-full-drifted.md",
        extracted_text="body", raw_text="<raw>body</raw>", content_hash="sha256:fd"))
    insert_item(db, _item(
        "web:pr", "Marker partial rotted", stage="rendered",
        markdown_path="scrolls/web/marker-partial-rotted.md",
        extracted_text="only extracted"))  # extracted, no hash/raw → partial
    insert_item(db, _item(
        "web:ru", "Marker reference unverified", stage="rendered",
        markdown_path="scrolls/web/marker-reference-unverified.md"))  # no content → reference
    record_events(db, [
        CustodyEvent("web:fv", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:fv", "sha256:fv", None),
        CustodyEvent("web:fd", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:fd", "sha256:x", None),
        CustodyEvent("web:pr", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:pr", None, "HTTP Error 404"),
        # web:ru left unverified
    ])


def test_compiled_library_page_agrees_on_the_per_item_custody_marker(scrolls_home, capsys):
    # roadmap H91/H93: H89 put the `· <fidelity> · <drift>` marker on the compiled
    # `library/` list-page rows — the human-readable surface the per-item picture
    # skipped — and H93 folded in the time axis (`· checked <ts>` / `· never
    # checked`). Fold it all into the convergence invariant: the marker a human
    # reads off a compiled page equals the canonical (`get_fidelity`,
    # `drift_posture`, `last_checked`) *and* the JSON `list` surface's
    # `fidelity`+`drift`+`last_checked`, for every item.
    main(["init"])
    db = get_paths().db_path
    _seed_marker_fixture(db)
    capsys.readouterr()

    verdicts = latest_events(db)
    items = list_items(db)
    canonical = {
        item.title: (
            get_fidelity(item),
            drift_posture(verdicts.get(item.id)),
            last_checked(verdicts.get(item.id)),
        )
        for item in items
    }
    # sanity: the fixture spans the fidelity axis crossed with four postures, each
    # checked item carrying its verdict's timestamp and the never-checked item the
    # honest `None` (the H93 time axis)
    assert set(canonical.values()) == {
        ("full", "verified", "2026-06-14T00:00:00+00:00"),
        ("full", "drifted", "2026-06-14T00:00:00+00:00"),
        ("partial", "rotted", "2026-06-14T00:00:00+00:00"),
        ("reference", "unverified", None),
    }

    # the JSON browse surface (H58/H84): fidelity + drift + last_checked per item
    assert main(["list"]) == 0
    title_by_id = {item.id: item.title for item in items}
    list_markers = {
        title_by_id[r["id"]]: (r["fidelity"], r["drift"], r["last_checked"])
        for r in json.loads(capsys.readouterr().out)
    }

    # the compiled human-readable surface (H89/H93): the markers on sources/web.md
    assert main(["kb"]) == 0
    capsys.readouterr()
    page = (get_paths().library_dir / "sources" / "web.md").read_text(encoding="utf-8")
    compiled_markers = _library_markers(page)

    # all three agree, for every item — the compiled library reads the same
    # per-item custody picture (fidelity + drift + as-of-when) as the agent surfaces
    assert compiled_markers == canonical
    assert list_markers == canonical

    # and the marker's timestamp equals the head of each item's `history` ledger
    # (the H88 tie on the compiled surface): `None` ⇔ the empty timeline
    for item in items:
        assert main(["history", item.id]) == 0
        events = json.loads(capsys.readouterr().out)
        head_checked_at = events[0]["checked_at"] if events else None
        assert compiled_markers[item.title][2] == head_checked_at


def test_every_surface_agrees_on_an_items_drift_posture(scrolls_home, capsys):
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    # the canonical per-item posture: drift_posture over each item's latest verdict
    verdicts = latest_events(db)
    canonical = {
        item.id: drift_posture(verdicts.get(item.id)) for item in list_items(db)
    }
    # sanity: the fixture spans four distinct postures
    assert set(canonical.values()) == {"verified", "drifted", "rotted", "unverified"}

    # list rows (H58)
    assert main(["list"]) == 0
    list_drift = {r["id"]: r["drift"] for r in json.loads(capsys.readouterr().out)}
    # search hits (H58) — every title carries "topic"
    assert main(["search", "topic"]) == 0
    search_drift = {h["id"]: h["drift"] for h in json.loads(capsys.readouterr().out)}
    # graph nodes (H56) — every item is a node via the ring of links
    assert main(["graph"]) == 0
    graph_drift = {
        n["id"]: n["drift"] for n in json.loads(capsys.readouterr().out)["nodes"]
    }
    # bundle briefing (H42) — every match is in scope and carries a custody line
    assert main(["export", "bundle", "topic"]) == 0
    bundle_drift = _bundle_postures(capsys.readouterr().out)
    # related hits (H56) from web:1 — reaches every other item (link + shared tag)
    assert main(["related", "web:1"]) == 0
    related_drift = {h["id"]: h["drift"] for h in json.loads(capsys.readouterr().out)}
    # show — the inspect surface (H61), one item at a time
    show_drift = {}
    for item_id in canonical:
        assert main(["show", item_id]) == 0
        show_drift[item_id] = json.loads(capsys.readouterr().out)["drift"]

    # every whole-library surface reports the canonical posture for every item
    assert list_drift == canonical
    assert search_drift == canonical
    assert graph_drift == canonical
    assert bundle_drift == canonical
    assert show_drift == canonical
    # related carries every item *except its anchor*, each at the canonical posture
    assert related_drift == {
        item_id: posture
        for item_id, posture in canonical.items()
        if item_id != "web:1"
    }


def test_every_surface_agrees_on_an_items_last_checked(scrolls_home, capsys):
    # roadmap H88: the time-axis analogue of the drift-posture invariant above.
    # `last_checked` now rides every per-item surface (list/search/show H84,
    # related/graph H86, the bundle briefing's `as of` line H42); this asserts a
    # given item reads the *same* timestamp on every one of them, with `null` ⇔ the
    # bundle's "never re-checked" ⇔ the JSON surfaces' null. (`works` has no work in
    # this ring fixture — its parity is pinned in the works-seed test.)
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    # the canonical per-item timestamp: last_checked over each item's latest verdict
    verdicts = latest_events(db)
    canonical = {
        item.id: last_checked(verdicts.get(item.id)) for item in list_items(db)
    }
    # sanity: three checked at the fixture timestamp, web:4 never
    assert canonical == {
        "web:1": "2026-06-14T00:00:00+00:00",
        "web:2": "2026-06-14T00:00:00+00:00",
        "web:3": "2026-06-14T00:00:00+00:00",
        "web:4": None,
    }

    # list rows (H84)
    assert main(["list"]) == 0
    list_ts = {r["id"]: r["last_checked"] for r in json.loads(capsys.readouterr().out)}
    # search hits (H84)
    assert main(["search", "topic"]) == 0
    search_ts = {h["id"]: h["last_checked"] for h in json.loads(capsys.readouterr().out)}
    # graph nodes (H86)
    assert main(["graph"]) == 0
    graph_ts = {
        n["id"]: n["last_checked"] for n in json.loads(capsys.readouterr().out)["nodes"]
    }
    # bundle briefing (H42) — the `as of <date>` / "never re-checked" prose
    assert main(["export", "bundle", "topic"]) == 0
    bundle_ts = _bundle_last_checked(capsys.readouterr().out)
    # related hits (H86) from web:1 — reaches every other item
    assert main(["related", "web:1"]) == 0
    related_ts = {h["id"]: h["last_checked"] for h in json.loads(capsys.readouterr().out)}
    # show — the inspect surface (H84), one item at a time
    show_ts = {}
    for item_id in canonical:
        assert main(["show", item_id]) == 0
        show_ts[item_id] = json.loads(capsys.readouterr().out)["last_checked"]

    # every whole-library surface reports the canonical timestamp for every item
    assert list_ts == canonical
    assert search_ts == canonical
    assert graph_ts == canonical
    assert bundle_ts == canonical
    assert show_ts == canonical
    # related carries every item *except its anchor*, each at the canonical stamp
    assert related_ts == {
        item_id: ts for item_id, ts in canonical.items() if item_id != "web:1"
    }


def test_context_excerpt_tags_agree_with_the_inspect_surface(scrolls_home, capsys):
    # roadmap H94: H44/H62/H90 put the classification + drift + `last_checked` tags
    # on the `full`-tier `context` excerpts — the bundle an agent actually drops into
    # its window — each *claimed* to read the same as the `show`/`list` surfaces. That
    # parity was pinned only obliquely (`test_context_excerpt_drift_matches_the_ledger
    # _primitives` ties the tag to the ledger primitive, not to the inspect surface).
    # Fold the model-facing bundle into the per-item invariant as a surface in its own
    # right: over the four-posture fixture the `_drift <posture> · last seen <ts>` tag
    # an agent reads in each excerpt must equal the `drift`/`last_checked` `scrolls
    # show` reports for that item — and `never re-checked` ⇔ the `unverified`/`null`
    # honest absence — so the per-source custody in the model-facing bundle can never
    # silently desync from the inspect surface.
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    # the canonical per-item (posture, timestamp) over each item's latest verdict
    verdicts = latest_events(db)
    canonical = {
        item.id: (
            drift_posture(verdicts.get(item.id)),
            last_checked(verdicts.get(item.id)),
        )
        for item in list_items(db)
    }
    # sanity: the fixture spans the four postures, three checked + one never — so the
    # tag exercises both the `last seen <ts>` and the `never re-checked` honest absence
    assert {posture for posture, _ in canonical.values()} == {
        "verified", "drifted", "rotted", "unverified"}
    assert canonical["web:4"] == ("unverified", None)  # never re-checked → null

    # the model-facing bundle at the default `full` budget — each excerpt's drift tag
    assert main(["context", "topic"]) == 0
    context_tags = _context_excerpt_tags(capsys.readouterr().out)
    # every in-scope item rendered an excerpt with a parsed tag (none silently dropped)
    assert set(context_tags) == set(canonical)

    # the inspect surface — `show` carries `drift` + `last_checked` per item (H61/H84)
    show_tags = {}
    for item_id in canonical:
        assert main(["show", item_id]) == 0
        payload = json.loads(capsys.readouterr().out)
        show_tags[item_id] = (payload["drift"], payload["last_checked"])

    # the excerpt an agent reads, the inspect surface, and the ledger primitives all
    # agree on each item's (posture, as-of-when) — per-source custody can't desync
    assert context_tags == canonical
    assert show_tags == canonical


def test_per_item_drift_totals_the_facets_count(scrolls_home, capsys):
    # tie the per-item axis back to the aggregate: each whole-library surface's
    # per-item posture counts equal `facets drift`'s count for that posture, so a
    # change that desyncs the per-item field from the aggregate fails here.
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    main(["facets", "drift"])
    facet_counts = _facet_map(json.loads(capsys.readouterr().out)["facets"]["drift"])

    def _posture_counts(rows):
        counts = {}
        for posture in (row["drift"] for row in rows):
            counts[posture] = counts.get(posture, 0) + 1
        return counts

    assert main(["list"]) == 0
    assert _posture_counts(json.loads(capsys.readouterr().out)) == facet_counts
    assert main(["search", "topic"]) == 0
    assert _posture_counts(json.loads(capsys.readouterr().out)) == facet_counts
    assert main(["graph"]) == 0
    assert _posture_counts(json.loads(capsys.readouterr().out)["nodes"]) == facet_counts


def test_works_representation_agrees_on_an_items_drift_posture(scrolls_home, capsys):
    # the seventh per-item surface (roadmap H64): the `works` representation shape.
    # It needs a DOI-sharing fixture (the ring above links by URL, forms no work),
    # so it has its own seed — an arXiv preprint + its published Crossref record,
    # one drifted, one never re-checked. The drift each representation carries must
    # equal the canonical `drift_posture` and the item's own `list` row.
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item(
        "arxiv:1706.03762", "Attention Is All You Need", source="arxiv",
        source_id="1706.03762", url="https://arxiv.org/abs/1706.03762",
        links=("https://doi.org/10.5555/3295222",), stage="rendered",
        raw_text="<raw>preprint body</raw>", content_hash="sha256:a",
    ))
    insert_item(db, _item(
        "crossref:10.5555/3295222", "Attention Is All You Need", source="crossref",
        source_id="10.5555/3295222", url="https://doi.org/10.5555/3295222",
        stage="rendered", raw_text="<raw>record</raw>", content_hash="sha256:b",
    ))
    record_events(db, [
        CustodyEvent("arxiv:1706.03762", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:a", "sha256:x", None),
        # crossref left unverified
    ])
    capsys.readouterr()

    verdicts = latest_events(db)
    canonical = {
        item.id: drift_posture(verdicts.get(item.id)) for item in list_items(db)
    }
    assert set(canonical.values()) == {"drifted", "unverified"}

    assert main(["works"]) == 0
    rep_rows = json.loads(capsys.readouterr().out)["works"][0]["representations"]
    reps = {r["id"]: r["drift"] for r in rep_rows}
    reps_ts = {r["id"]: r["last_checked"] for r in rep_rows}
    assert main(["list"]) == 0
    list_rows = json.loads(capsys.readouterr().out)
    list_drift = {r["id"]: r["drift"] for r in list_rows}
    list_ts = {r["id"]: r["last_checked"] for r in list_rows}

    assert reps == canonical
    assert reps == list_drift
    # H87: the time axis travels with the representation too, at parity with the
    # `list` row — the drifted preprint carries the verdict's timestamp, the
    # never-checked record `null`.
    assert reps_ts == list_ts
    assert reps_ts == {
        "arxiv:1706.03762": "2026-06-14T00:00:00+00:00",
        "crossref:10.5555/3295222": None,
    }


def _posture_from_history(events):
    """The drift posture an item's `history` head implies — the tie H70 pins.

    `history` returns the full ledger newest-first (each `event_payload` dict);
    the *head* is the latest verdict, so `drift_posture` of it must equal the
    `drift` posture every browse/inspect surface shows. An empty ledger means
    never checked, the `unverified` posture those surfaces default to.
    """
    if not events:
        return "unverified"
    head = events[0]
    return drift_posture(CustodyEvent(
        item_id="",
        checked_at=head["checked_at"],
        status=head["status"],
        prior_hash=head["prior_hash"],
        observed_hash=head["observed_hash"],
        detail=head["detail"],
    ))


def test_history_head_agrees_with_the_per_item_drift_posture(scrolls_home, capsys):
    # roadmap H70: `scrolls history` exposes the *full* ledger; the load-bearing
    # tie is that the posture its newest event implies equals the `drift` every
    # latest-posture surface (list/search/show/…) reports for the same item — and
    # `[]` ⇒ `unverified`, the never-checked default they all share. So the
    # full-timeline surface can never silently disagree with the postures that
    # summarize it (the per-item-timeline analogue of H59).
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    verdicts = latest_events(db)
    canonical = {
        item.id: drift_posture(verdicts.get(item.id)) for item in list_items(db)
    }
    # sanity: the fixture spans verified / drifted / rotted / unverified
    assert set(canonical.values()) == {"verified", "drifted", "rotted", "unverified"}

    history_posture = {}
    for item_id in canonical:
        assert main(["history", item_id]) == 0
        history_posture[item_id] = _posture_from_history(
            json.loads(capsys.readouterr().out)
        )

    # the head of the ledger `history` returns maps to the posture everywhere else
    assert history_posture == canonical
    # and the never-checked item is the honest empty timeline ⇒ unverified
    assert main(["history", "web:4"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert canonical["web:4"] == "unverified"


def test_last_checked_agrees_with_the_history_head_checked_at(scrolls_home, capsys):
    # roadmap H84: the per-item `drift` posture has a time sibling — `last_checked`,
    # *when* that verdict was taken — riding `list`/`search`/`show`. The tie this
    # pins (the time-axis counterpart of the H70 posture tie): the timestamp every
    # latest-posture surface shows equals the `checked_at` of the head of the
    # `history` ledger for that item, and `None` ⇔ the honest empty timeline ⇔
    # never re-checked. So the staleness an agent reads off a browse row can never
    # silently disagree with the ledger `history` reads back.
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    items = [item.id for item in list_items(db)]

    # the canonical last-checked per item: the head of its `history` ledger
    canonical = {}
    for item_id in items:
        assert main(["history", item_id]) == 0
        events = json.loads(capsys.readouterr().out)
        canonical[item_id] = events[0]["checked_at"] if events else None
    # sanity: three were checked at the fixture timestamp, web:4 never
    assert canonical == {
        "web:1": "2026-06-14T00:00:00+00:00",
        "web:2": "2026-06-14T00:00:00+00:00",
        "web:3": "2026-06-14T00:00:00+00:00",
        "web:4": None,
    }

    # list rows + search hits carry the same timestamp (H84)
    assert main(["list"]) == 0
    assert {r["id"]: r["last_checked"] for r in json.loads(capsys.readouterr().out)} == canonical
    assert main(["search", "topic"]) == 0
    assert {h["id"]: h["last_checked"] for h in json.loads(capsys.readouterr().out)} == canonical
    # …and the inspect surface, one item at a time
    show_ts = {}
    for item_id in items:
        assert main(["show", item_id]) == 0
        show_ts[item_id] = json.loads(capsys.readouterr().out)["last_checked"]
    assert show_ts == canonical

    # the node-shape surfaces carry the same timestamp too (H86): graph nodes over
    # the ring of links, and related hits from web:1 (every item but its anchor)
    assert main(["graph"]) == 0
    graph_ts = {
        n["id"]: n["last_checked"] for n in json.loads(capsys.readouterr().out)["nodes"]
    }
    assert graph_ts == canonical
    assert main(["related", "web:1"]) == 0
    related_ts = {h["id"]: h["last_checked"] for h in json.loads(capsys.readouterr().out)}
    assert related_ts == {
        item_id: ts for item_id, ts in canonical.items() if item_id != "web:1"
    }


# --- portable custody: the posture survives export→import (roadmap H73) ------


def test_the_drift_posture_survives_an_export_import_round_trip(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # H73: H59/H70 pin that an item reads the same posture on every surface *in one
    # library*; H67/H72 make the ledger portable. The load-bearing property this
    # pins is that the posture an item reads after an export→import is exactly the
    # posture it read before — custody travels losslessly, not just the item. So
    # the convergence invariant holds *across* the two libraries, by construction
    # of the deduped restore.
    main(["init"])
    db_a = get_paths().db_path
    _seed_linked_drift_postures(db_a)
    capsys.readouterr()

    # the canonical per-item posture in A
    verdicts_a = latest_events(db_a)
    canonical = {
        item.id: drift_posture(verdicts_a.get(item.id)) for item in list_items(db_a)
    }
    assert set(canonical.values()) == {"verified", "drifted", "rotted", "unverified"}
    # …and A's drift facet aggregate
    main(["facets", "drift"])
    facets_a = _facet_map(json.loads(capsys.readouterr().out)["facets"]["drift"])

    # export the whole topic scope (items + their verify ledger, H67) from A
    assert main(["export", "bundle", "topic"]) == 0
    bundle_path = tmp_path / "briefing.md"
    bundle_path.write_text(capsys.readouterr().out, encoding="utf-8")

    # restore into a fresh library B
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    capsys.readouterr()
    assert main(["import", "bundle", str(bundle_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    # every item and every recorded check travelled (web:4 has no event)
    assert report["imported"] == 4
    assert report["events"] == {"imported": 3, "skipped": 0}

    # every per-item surface in B reports the *same* posture A did — the per-item
    # convergence invariant (H59), now across the round trip
    assert main(["list"]) == 0
    assert {r["id"]: r["drift"] for r in json.loads(capsys.readouterr().out)} == canonical
    assert main(["search", "topic"]) == 0
    assert {h["id"]: h["drift"] for h in json.loads(capsys.readouterr().out)} == canonical
    show_drift = {}
    for item_id in canonical:
        assert main(["show", item_id]) == 0
        show_drift[item_id] = json.loads(capsys.readouterr().out)["drift"]
    assert show_drift == canonical
    # the full ledger round-trips too: history's head implies the same posture (H70)
    history_posture = {}
    for item_id in canonical:
        assert main(["history", item_id]) == 0
        history_posture[item_id] = _posture_from_history(
            json.loads(capsys.readouterr().out)
        )
    assert history_posture == canonical
    # a re-exported bundle from B carries the same per-scroll postures
    assert main(["export", "bundle", "topic"]) == 0
    assert _bundle_postures(capsys.readouterr().out) == canonical
    # and the drift facet aggregate converges across the two libraries
    assert main(["facets", "drift"]) == 0
    facets_b = _facet_map(json.loads(capsys.readouterr().out)["facets"]["drift"])
    assert facets_b == facets_a


def test_whole_library_export_events_round_trip_preserves_the_posture(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # the H72 backup-path counterpart: `export items` + `export events` from A,
    # restored into fresh B, must reproduce A's per-item posture on every surface
    # — custody travels with the whole-library backup, not just the bundle.
    main(["init"])
    db_a = get_paths().db_path
    _seed_linked_drift_postures(db_a)
    capsys.readouterr()

    verdicts_a = latest_events(db_a)
    canonical = {
        item.id: drift_posture(verdicts_a.get(item.id)) for item in list_items(db_a)
    }
    assert set(canonical.values()) == {"verified", "drifted", "rotted", "unverified"}

    main(["export", "items"])
    items_path = tmp_path / "library.jsonl"
    items_path.write_text(capsys.readouterr().out, encoding="utf-8")
    main(["export", "events"])
    events_path = tmp_path / "ledger.jsonl"
    events_path.write_text(capsys.readouterr().out, encoding="utf-8")

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    capsys.readouterr()
    assert main(["import", "items", str(items_path)]) == 0
    capsys.readouterr()  # discard the items-import report
    assert main(["import", "events", str(events_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "imported": 3, "skipped": 0, "events": 3
    }

    assert main(["list"]) == 0
    assert {r["id"]: r["drift"] for r in json.loads(capsys.readouterr().out)} == canonical
    # re-importing the ledger is a custody no-op (idempotent)
    assert main(["import", "events", str(events_path)]) == 0
    assert json.loads(capsys.readouterr().out)["skipped"] == 3


def _seed_staggered_drift_ledger(db):
    """Four held scrolls whose ledgers span two timestamps — an old verdict and a
    newer one that determines the posture — so an `export events --since` window
    partitions the ledger with *partial* overlap against a full backup.

    The newer (2026-06-14) verdict per item fixes the same four postures the ring
    fixture has (web:1 `verified`, web:2 `drifted`, web:3 `rotted`, web:4
    `unverified`); the older (2026-06-10) verdicts are the ones a `--since
    2026-06-12` incremental backup leaves behind, so the full backup carries them
    and the union must dedup the overlapping recent ones.
    """
    for index in (1, 2, 3, 4):
        insert_item(db, _item(
            f"web:{index}", f"Topic scroll {index}",
            extracted_text=f"topic body {index}", content_hash=f"sha256:{index}",
        ))
    record_events(db, [
        # older verdicts (before the incremental window) — only in the full backup
        CustodyEvent("web:1", "2026-06-10T00:00:00+00:00", "drifted", "sha256:1", "sha256:o", None),
        CustodyEvent("web:2", "2026-06-10T00:00:00+00:00", "unchanged", "sha256:2", "sha256:2", None),
        CustodyEvent("web:3", "2026-06-10T00:00:00+00:00", "unchanged", "sha256:3", "sha256:3", None),
        # newer verdicts (in the incremental window) — set the latest posture
        CustodyEvent("web:1", "2026-06-14T00:00:00+00:00", "unchanged", "sha256:1", "sha256:1", None),
        CustodyEvent("web:2", "2026-06-14T00:00:00+00:00", "drifted", "sha256:2", "sha256:x", None),
        CustodyEvent("web:3", "2026-06-14T00:00:00+00:00", "rotted", "sha256:3", None, "HTTP Error 404"),
        # web:4 never checked → unverified
    ])


def test_incremental_backup_union_preserves_the_posture(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # H78: H73 pins that a *whole-ledger* export→import preserves the posture;
    # H75 adds the incremental (`--since`) backup. The load-bearing property this
    # pins is that a full `export events` plus an *overlapping* `export events
    # --since` incremental backup, restored together into a fresh library, is as
    # lossless for custody as the whole-ledger path — the union dedups (no double
    # count) and B reproduces A's per-item posture and `facets drift` aggregate.
    main(["init"])
    db_a = get_paths().db_path
    _seed_staggered_drift_ledger(db_a)
    capsys.readouterr()

    verdicts_a = latest_events(db_a)
    canonical = {
        item.id: drift_posture(verdicts_a.get(item.id)) for item in list_items(db_a)
    }
    assert set(canonical.values()) == {"verified", "drifted", "rotted", "unverified"}
    main(["facets", "drift"])
    facets_a = _facet_map(json.loads(capsys.readouterr().out)["facets"]["drift"])

    # a full backup (every event) and an overlapping incremental one (only the
    # recent window — the 3 newest verdicts, which the full backup also carries)
    main(["export", "events"])
    full = capsys.readouterr().out
    main(["export", "events", "--since", "2026-06-12T00:00:00+00:00"])
    incr = capsys.readouterr().out
    # the incremental backup is a strict subset of the full one (3 of 6 events)
    assert len(full.splitlines()) == 6
    assert len(incr.splitlines()) == 3

    # restore the *union* of the two backups into a fresh library B in one import
    # — the realistic "restore all my backup rows" operation: `import events`
    # sorts the batch by checked_at, so restored ids stay chronological (the
    # posture an item reads back is its newest verdict) and the within-batch
    # content-dedup drops the 3 rows the two backups share.
    union_path = tmp_path / "union.jsonl"
    union_path.write_text(full + incr, encoding="utf-8")  # 9 rows: 6 + 3 overlap

    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    db_b = get_paths().db_path
    for item in list_items(db_a):
        insert_item(db_b, item)
    capsys.readouterr()
    assert main(["import", "events", str(union_path)]) == 0
    # the 6 distinct events land once; the 3 overlapping rows dedup — never
    # double-counted, so the union is as lossless as the whole-ledger backup
    assert json.loads(capsys.readouterr().out) == {"imported": 6, "skipped": 3, "events": 9}

    # B reproduces A's per-item posture on every surface — the windowed/incremental
    # path is as lossless for custody as the whole-ledger path (H73)
    assert main(["list"]) == 0
    assert {r["id"]: r["drift"] for r in json.loads(capsys.readouterr().out)} == canonical
    history_posture = {}
    for item_id in canonical:
        assert main(["history", item_id]) == 0
        history_posture[item_id] = _posture_from_history(json.loads(capsys.readouterr().out))
    assert history_posture == canonical
    # …and the drift facet aggregate converges across the two libraries
    assert main(["facets", "drift"]) == 0
    assert _facet_map(json.loads(capsys.readouterr().out)["facets"]["drift"]) == facets_a


# --- the verify-selection family (roadmap H81) -----------------------------
#
# `scrolls verify` now carries four batch *selections* over one shared trio of
# `custody` selectors: `--unverified` (`unverified_items`), `--stale-before`
# (`items_checked_before`), and `--drift` (`items_in_posture`), plus `--all`.
# Those selections are the *act* side of the same custody picture the read
# surfaces above enumerate. This section pins the documented relationships as a
# tested contract — the verify-axis sibling of the per-item read invariant — so
# a change that desyncs the recheck set from the read enumeration fails here.
# The network edge is stubbed so every re-check reads `unchanged` offline.


def _stub_recapture(monkeypatch, fn):
    monkeypatch.setattr(cli, "live_recapture", fn)


def test_verify_drift_rechecks_exactly_what_list_drift_enumerates(scrolls_home, monkeypatch, capsys):
    # the act-side ≡ read-side drill: for every posture, `verify --drift X`
    # re-captures exactly the rows `list --drift X` shows (the shared
    # `items_in_posture` selector backs both).
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    postures = ("verified", "drifted", "rotted", "unverified")
    # snapshot every `list --drift X` set before any verify mutates the ledger
    listed = {}
    for posture in postures:
        assert main(["list", "--drift", posture]) == 0
        listed[posture] = {r["id"] for r in json.loads(capsys.readouterr().out)}
    assert listed == {
        "verified": {"web:1"}, "drifted": {"web:2"},
        "rotted": {"web:3"}, "unverified": {"web:4"},
    }

    _stub_recapture(monkeypatch, lambda i: i)  # every re-check reads `unchanged`
    for posture in postures:
        # each posture's items are distinct and not yet re-checked, so the live
        # ledger still places them at `posture` when this selection reads it
        assert main(["verify", "--drift", posture]) == 0
        rechecked = {r["id"] for r in json.loads(capsys.readouterr().out)["results"]}
        assert rechecked == listed[posture]


def test_list_stale_before_enumerates_exactly_the_verify_stale_before_set(scrolls_home, monkeypatch, capsys):
    # H85: the read-side `list --stale-before B` enumerates exactly the set the
    # act-side `verify --stale-before B` re-captures — the shared
    # `items_checked_before` selector backs both, the time-axis counterpart of the
    # `list --drift` ≡ `verify --drift` parity. The ring's three verdicts sit at
    # 2026-06-14, so a 2026-06-14 boundary is a real partition: those three are
    # fresh (checked *at* the exclusive boundary), web:4 (never checked) is stale.
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    boundary = "2026-06-14T00:00:00+00:00"
    # snapshot the read enumeration before any verify mutates the ledger
    assert main(["list", "--stale-before", boundary]) == 0
    listed = {r["id"] for r in json.loads(capsys.readouterr().out)}
    assert listed == {"web:4"}  # the never-checked one; the rest checked at the boundary

    _stub_recapture(monkeypatch, lambda i: i)
    assert main(["verify", "--stale-before", boundary]) == 0
    rechecked = {r["id"] for r in json.loads(capsys.readouterr().out)["results"]}
    assert rechecked == listed  # the recheck set is exactly the enumerated set


def test_verify_stale_before_future_subsumes_unverified_and_clears_the_signal(scrolls_home, monkeypatch, capsys):
    # `--stale-before <future>` is a superset of `--unverified` (every
    # never-checked item is trivially stale), so it clears the same
    # `doctor custody.drift.unverified` bucket `--unverified` targets.
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    capsys.readouterr()

    main(["doctor"])
    assert json.loads(capsys.readouterr().out)["custody"]["drift"]["unverified"] == 1
    main(["list", "--drift", "unverified"])
    unverified_ids = {r["id"] for r in json.loads(capsys.readouterr().out)}
    assert unverified_ids == {"web:4"}

    _stub_recapture(monkeypatch, lambda i: i)
    assert main(["verify", "--stale-before", "2099-01-01T00:00:00+00:00"]) == 0
    rechecked = {r["id"] for r in json.loads(capsys.readouterr().out)["results"]}
    assert rechecked == {"web:1", "web:2", "web:3", "web:4"}  # all four are stale
    assert unverified_ids.issubset(rechecked)  # ⊇ the never-checked set

    main(["doctor"])
    after = json.loads(capsys.readouterr().out)["custody"]["drift"]
    assert after["unverified"] == 0 and after["checked"] == 4


def test_every_batch_selection_skips_reference_only_items(scrolls_home, monkeypatch, capsys):
    # a reference-only capture has no baseline hash to diff a re-fetch against,
    # so it is never re-checked by *any* batch selection — even though it is
    # `unverified` and would otherwise be in `--unverified`/`--stale-before`/
    # `--drift unverified`'s set. (The assertion holds regardless of ledger
    # mutation: web:ref has no hash, so it is filtered out at every selection.)
    main(["init"])
    db = get_paths().db_path
    _seed_linked_drift_postures(db)
    insert_item(db, _item(
        "web:ref", "Reference only", content_hash=None, extracted_text=None,
        raw_text=None, stage="detected", tags=("topic",)))
    capsys.readouterr()

    _stub_recapture(monkeypatch, lambda i: i)
    for argv in (
        ["verify", "--all"],
        ["verify", "--unverified"],
        ["verify", "--stale-before", "2099-01-01T00:00:00+00:00"],
        ["verify", "--drift", "unverified"],
        ["verify", "--source", "web"],
    ):
        assert main(argv) == 0
        rechecked = {r["id"] for r in json.loads(capsys.readouterr().out)["results"]}
        assert "web:ref" not in rechecked


def _seed_per_source_custody(db):
    """Held scrolls across two sources, all never re-checked.

    `web` holds two hash-bearing scrolls (web:1, web:2) and one reference-only
    pointer (web:ref, no hash → unverifiable); `arxiv` holds one hash-bearing
    scroll (arxiv:1). All start `unverified` (no ledger verdicts), so a
    per-source recheck of `web` can clear exactly that source's unverified
    bucket while `arxiv` stays untouched — the per-source counterpart of how
    `--unverified` clears the whole-library bucket.
    """
    for index in (1, 2):
        insert_item(db, _item(
            f"web:{index}", f"Web scroll {index}",
            extracted_text=f"web body {index}", raw_text=f"<raw>web {index}</raw>",
            content_hash=f"sha256:web{index}",
        ))
    insert_item(db, _item(
        "web:ref", "Web reference pointer", stage="detected"))  # no hash
    insert_item(db, _item(
        "arxiv:1", "Arxiv scroll one", source="arxiv",
        url="https://arxiv.org/abs/2401.00001",
        extracted_text="arxiv body", raw_text="<raw>arxiv</raw>",
        content_hash="sha256:arxiv1",
    ))


def test_verify_source_rechecks_exactly_what_list_source_enumerates(scrolls_home, monkeypatch, capsys):
    # the act-side ≡ read-side drill on the *source* axis (the verify-axis sibling
    # of `list --source`, the H125 counterpart of the H54 `--drift` parity above):
    # for every held source, `verify --source S` re-captures exactly `list --source S`'s
    # held, hash-bearing rows. The reference-only web row is in the listing but has
    # no baseline hash, so it is never re-captured — the row-vs-recheck distinction.
    main(["init"])
    db = get_paths().db_path
    _seed_per_source_custody(db)
    capsys.readouterr()

    # the held hash-bearing rows per source (reference-only web:ref excluded)
    expected = {"web": {"web:1", "web:2"}, "arxiv": {"arxiv:1"}}

    listed = {}
    for source in ("web", "arxiv"):
        assert main(["list", "--source", source]) == 0
        rows = json.loads(capsys.readouterr().out)
        listed[source] = {r["id"] for r in rows if r["fidelity"] != "reference"}
    assert listed == expected
    # `list --source web` carries the reference-only row too — verify drops it
    assert main(["list", "--source", "web"]) == 0
    assert {r["id"] for r in json.loads(capsys.readouterr().out)} == {
        "web:1", "web:2", "web:ref"}

    _stub_recapture(monkeypatch, lambda i: i)  # every re-check reads `unchanged`
    for source in ("web", "arxiv"):
        assert main(["verify", "--source", source]) == 0
        rechecked = {r["id"] for r in json.loads(capsys.readouterr().out)["results"]}
        assert rechecked == listed[source] == expected[source]


def test_verify_source_clears_that_sources_unverified_bucket(scrolls_home, monkeypatch, capsys):
    # re-verifying source web clears exactly that source's `unverified` count in
    # doctor's `custody.by_source[web]` (the per-source counterpart of how
    # `--unverified` clears the whole-library bucket, and `--drift` its posture):
    # web's two hash-bearing rows move to `verified`, the reference-only one stays
    # `unverified` (honestly — no baseline), and `arxiv` is untouched.
    main(["init"])
    db = get_paths().db_path
    _seed_per_source_custody(db)
    capsys.readouterr()

    main(["doctor"])
    before = json.loads(capsys.readouterr().out)["custody"]["by_source"]
    assert before["web"]["drift"]["unverified"] == 3  # web:1, web:2, web:ref
    assert before["arxiv"]["drift"]["unverified"] == 1

    _stub_recapture(monkeypatch, lambda i: i)
    assert main(["verify", "--source", "web"]) == 0
    capsys.readouterr()

    main(["doctor"])
    after = json.loads(capsys.readouterr().out)["custody"]["by_source"]
    assert after["web"]["drift"]["verified"] == 2  # the two hash-bearing rows
    assert after["web"]["drift"]["unverified"] == 1  # only the reference-only one
    assert after["arxiv"]["drift"]["unverified"] == 1  # other source untouched
    # the per-source coverage tracks it: web now 2-of-2 verifiable covered
    assert after["web"]["coverage"] == {"verified": 2, "total": 2}
    assert after["arxiv"]["coverage"] == {"verified": 0, "total": 1}


# --- maintain's scheduled recheck ≡ the explicit verify selection (roadmap H111)
#
# A default `scrolls maintain` pass stale-bounds its recheck to the held items not
# seen since the last run (H83): the boundary is the last recorded snapshot's
# `recorded_at` (`maintain.last_run_boundary`), and the set is `items_checked_before`
# at that boundary. `scrolls verify --stale-before <ISO>` (H79) is the *explicit*
# act-side selection over the *same* `items_checked_before` selector. The
# load-bearing tie: the set a scheduled pass re-verifies is exactly the set the
# explicit recheck would over the boundary maintain derives — so maintain's
# recurring recheck is the self-timestamping face of the verify-selection family
# (the section above), not a parallel-implementation coincidence. Captured by a
# recording recapture stub (the set each pass actually touches), so a refactor that
# desynced the scheduled boundary from the explicit one fails here.

# The boundary the crafted "last run" records; the fixture below partitions the
# ledger around it (two verdicts before it → stale, one at and one after → fresh).
_MAINTAIN_BOUNDARY = "2026-06-12T00:00:00+00:00"


def _seed_mixed_staleness(db):
    """Five held scrolls partitioned by ledger staleness against `_MAINTAIN_BOUNDARY`.

    `web:1` carries an *old* verdict (2026-06-10, before the boundary → stale);
    `web:2` one exactly *at* the boundary and `web:3` one *after* it (both fresh,
    since `items_checked_before` is exclusive — checked at/after the boundary is
    not stale); `web:4` is never re-checked (trivially stale at any boundary);
    `web:ref` is reference-only (no `content_hash` → unverifiable, excluded from
    every recheck). So the boundary's stale set is exactly the hash-bearing
    {web:1, web:4}, a genuine partition (not all, not none).
    """
    for index in (1, 2, 3, 4):
        insert_item(db, _item(
            f"web:{index}", f"Topic scroll {index}",
            extracted_text=f"topic body {index}", raw_text=f"<raw>topic {index}</raw>",
            content_hash=f"sha256:{index}", tags=("topic",),
        ))
    insert_item(db, _item(
        "web:ref", "Topic reference", stage="detected", tags=("topic",)))  # no hash
    record_events(db, [
        CustodyEvent("web:1", "2026-06-10T00:00:00+00:00", "unchanged",
                     "sha256:1", "sha256:1", None),  # before boundary → stale
        CustodyEvent("web:2", "2026-06-12T00:00:00+00:00", "unchanged",
                     "sha256:2", "sha256:2", None),  # at boundary → fresh (exclusive)
        CustodyEvent("web:3", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:3", "sha256:3", None),  # after boundary → fresh
        # web:4 never checked → trivially stale; web:ref has no hash → unverifiable
    ])


def _record_recheck(monkeypatch, argv, capsys):
    """Run a verify/maintain pass with a recording recapture stub; return the set
    of item ids it actually re-captured — the set that pass *targeted*.

    The recapture seam (`cli.live_recapture`) is the one network edge both `verify`
    and `maintain` route their recheck through, so recording the ids it is called
    with observes the targeted set directly, offline. Drains stdout (the pass
    prints a report we don't need here).
    """
    seen = []
    _stub_recapture(monkeypatch, lambda i: seen.append(i.id) or i)
    assert main(argv) == 0
    capsys.readouterr()
    return set(seen)


def test_maintain_default_recheck_targets_the_verify_stale_before_set(
    scrolls_home, tmp_path, monkeypatch, capsys
):
    # roadmap H111: the set a default `scrolls maintain` pass re-verifies is exactly
    # the set `verify --stale-before <last-run recorded_at>` selects, over the
    # boundary `last_run_boundary` derives off the recorded snapshot. Both go through
    # the one `items_checked_before` selector; pin the behavioral tie end-to-end.
    main(["init"])
    db_a = get_paths().db_path
    _seed_mixed_staleness(db_a)

    # the canonical stale set the boundary partitions (the shared primitive both use)
    hash_bearing = [item for item in list_items(db_a) if item.content_hash]
    verdicts = latest_events(db_a)
    boundary = parse_since(_MAINTAIN_BOUNDARY)
    canonical = {
        item.id for item in items_checked_before(hash_bearing, verdicts, boundary)
    }
    assert canonical == {"web:1", "web:4"}  # old verdict + never-checked; 2/3 fresh, ref no hash
    # the never-checked `--unverified` bucket is subsumed by the stale set
    # (a never-checked item is trivially stale at any boundary, H79)
    unverified = {item.id for item in unverified_items(hash_bearing, verdicts)}
    assert unverified == {"web:4"}
    assert unverified.issubset(canonical)

    # record a "last run" whose `recorded_at` *is* the boundary, then confirm
    # maintain derives exactly that boundary off the recorded snapshot
    save_snapshot(snapshot_path(get_paths()), {"recorded_at": _MAINTAIN_BOUNDARY})
    assert last_run_boundary(load_snapshot(snapshot_path(get_paths()))) == boundary
    capsys.readouterr()

    # the set a default maintain pass actually re-verifies (captured via the stub)
    maintained = _record_recheck(monkeypatch, ["maintain"], capsys)

    # the same fixture in a fresh library B, the explicit `verify --stale-before`
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "library-b"))
    main(["init"])
    _seed_mixed_staleness(get_paths().db_path)
    capsys.readouterr()
    verified = _record_recheck(
        monkeypatch, ["verify", "--stale-before", _MAINTAIN_BOUNDARY], capsys
    )

    # the scheduled pass and the explicit recheck select the same stale set
    assert maintained == canonical
    assert verified == canonical
    assert maintained == verified


def test_maintain_all_recheck_ignores_the_boundary(scrolls_home, monkeypatch, capsys):
    # roadmap H111: `maintain --all` is the H83 escape hatch — it ignores the
    # recorded boundary and rechecks the whole hash-bearing set (the `verify --all`
    # behavior), regardless of staleness. So the boundary bounds the *default* pass,
    # never the explicit whole-library one.
    main(["init"])
    db = get_paths().db_path
    _seed_mixed_staleness(db)

    hash_bearing = {item.id for item in list_items(db) if item.content_hash}
    boundary = parse_since(_MAINTAIN_BOUNDARY)
    stale = {
        item.id
        for item in items_checked_before(
            list_items(db), latest_events(db), boundary
        )
        if item.content_hash
    }
    assert stale == {"web:1", "web:4"} and stale < hash_bearing  # boundary excludes the fresh

    # record a last run so a *default* pass would stale-bound — `--all` must override it
    save_snapshot(snapshot_path(get_paths()), {"recorded_at": _MAINTAIN_BOUNDARY})
    capsys.readouterr()

    rechecked = _record_recheck(monkeypatch, ["maintain", "--all"], capsys)
    # the whole hash-bearing set, strictly more than the stale set the boundary picks
    assert rechecked == hash_bearing == {"web:1", "web:2", "web:3", "web:4"}
    assert stale < rechecked


# --- the trend ≡ telescoped per-run deltas invariant (roadmap H143) ----------
#
# `compute_trend` (H46/H115/H131) reports the net first→last movement on three
# count axes — `drift_change` (drifted+rotted), `coverage_change`, `stale_change`
# — plus the scalar `score.change`, by reading only the window's *endpoints*
# (`runs[0]`/`runs[-1]`). `compute_delta` (H34) records the *per-run* before/after/
# change between consecutive snapshots — the step-by-step history `maintain
# --history` reads back. The load-bearing property neither layer pins is that the
# trend's net change equals the **telescoped sum** of those per-run deltas across
# the window: the endpoint-only aggregation and the recorded steps agree, so the
# trajectory a worker reads can never silently disagree with the history it also
# reads. This section pins that identity — the trend-layer analogue of the
# per-surface convergence invariants above.

# The drift axes a snapshot carries (maintain's `_DRIFT_AXES`); only `drifted`/
# `rotted` feed the trend, but a snapshot populates them all, so `compute_delta`'s
# per-key diff has every key on both sides.
_DRIFT_KEYS = ("checked", "unverified", "unchanged", "drifted", "rotted", "error")


def _snapshot(*, score, drifted, rotted, verified, total, enrichment, summaries):
    """A custody snapshot in the `custody_snapshot` shape the trend/delta read.

    Only the axes the trend and delta compare are populated meaningfully; `tiers`
    is irrelevant to the trend's three count axes and the scalar score, so it is
    left empty (the delta diffs it, but this invariant asserts the trend axes).
    """
    return {
        "score": score,
        "tiers": {},
        "drift": {axis: 0 for axis in _DRIFT_KEYS} | {"drifted": drifted, "rotted": rotted},
        "coverage": {"verified": verified, "total": total},
        "enrichment_stale": enrichment,
        "summaries_stale": summaries,
    }


def _telescoped(snapshots):
    """Σ the per-run `compute_delta` changes across consecutive snapshots.

    The step-by-step history a worker reads: `compute_delta(snapshots[i-1],
    snapshots[i])` for every adjacent pair, summed per axis. `compute_trend` reads
    only the endpoints; this sums every recorded step, so the two must agree (the
    telescoping identity). Returns the count-axis sums plus the deltas themselves
    (so a caller can telescope the scalar score when no endpoint is null).
    """
    deltas = [compute_delta(snapshots[i - 1], snapshots[i]) for i in range(1, len(snapshots))]
    drift = sum(
        d["drift"]["drifted"]["change"] + d["drift"]["rotted"]["change"] for d in deltas
    )
    coverage = {
        "verified": sum(d["coverage"]["verified"]["change"] for d in deltas),
        "total": sum(d["coverage"]["total"]["change"] for d in deltas),
    }
    stale = {
        "enrichment": sum(d["enrichment_stale"]["change"] for d in deltas),
        "summaries": sum(d["summaries_stale"]["change"] for d in deltas),
    }
    return drift, coverage, stale, deltas


def _trend_window(snapshots):
    """Wrap snapshots as the `{recorded_at, snapshot}` run records `compute_trend`
    consumes (the shape `read_log` returns), timestamped one day apart."""
    return [
        {"recorded_at": f"2026-06-{10 + i:02d}T00:00:00+00:00", "snapshot": snap}
        for i, snap in enumerate(snapshots)
    ]


# A four-run window that moves *non-monotonically* on every axis — drift rises
# then falls, score falls then rises, enrichment rises then falls — so the
# telescoping is a genuine sum of signed intermediate steps, not an endpoint
# coincidence a monotone window would also satisfy.
_TREND_SNAPSHOTS = [
    _snapshot(score=100, drifted=0, rotted=0, verified=1, total=4, enrichment=0, summaries=0),
    _snapshot(score=90, drifted=1, rotted=0, verified=2, total=4, enrichment=1, summaries=0),
    _snapshot(score=80, drifted=1, rotted=1, verified=3, total=5, enrichment=2, summaries=1),
    _snapshot(score=85, drifted=0, rotted=1, verified=4, total=5, enrichment=1, summaries=1),
]


def test_trend_change_equals_the_telescoped_per_run_deltas():
    # roadmap H143: the trend's endpoint-only net change == the telescoped sum of
    # the per-run `compute_delta` changes, on every axis — so the trajectory and
    # the step-by-step history are the same numbers.
    trend = compute_trend(_trend_window(_TREND_SNAPSHOTS))
    drift, coverage, stale, deltas = _telescoped(_TREND_SNAPSHOTS)

    # the scalar score telescopes (last − first == Σ per-run changes)
    first_score = _TREND_SNAPSHOTS[0]["score"]
    last_score = _TREND_SNAPSHOTS[-1]["score"]
    assert trend["score"]["change"] == last_score - first_score
    assert trend["score"]["change"] == sum(d["score"]["change"] for d in deltas)

    # the three count axes telescope
    assert trend["drift_change"] == drift
    assert trend["coverage_change"] == coverage
    assert trend["stale_change"] == stale

    # non-vacuous: the window genuinely moves on every axis (else the identity is
    # trivially 0 == 0), and the intermediate steps are signed (a real telescope)
    assert trend["score"]["change"] == -15
    assert trend["drift_change"] == 1
    assert trend["coverage_change"] == {"verified": 3, "total": 1}
    assert trend["stale_change"] == {"enrichment": 1, "summaries": 1}
    assert [d["drift"]["drifted"]["change"] for d in deltas] == [1, 0, -1]  # up then down


def test_perturbing_one_endpoint_moves_trend_and_telescope_together():
    # mutation check (roadmap H143): perturbing one endpoint changes *both* the
    # trend's net change and the telescoped sum by the same amount — the identity
    # tracks the data, not a constant, so the assertion above is not vacuous.
    base_trend = compute_trend(_trend_window(_TREND_SNAPSHOTS))

    # add one more `rotted` at the *last* endpoint (one step's worth of drift loss)
    perturbed = [*_TREND_SNAPSHOTS[:-1], _snapshot(
        score=85, drifted=0, rotted=2, verified=4, total=5, enrichment=1, summaries=1)]
    perturbed_trend = compute_trend(_trend_window(perturbed))
    p_drift, _, _, _ = _telescoped(perturbed)

    # the perturbation moved the value (so the test has teeth) …
    assert perturbed_trend["drift_change"] == base_trend["drift_change"] + 1
    # … and the telescoped identity still holds at the new value
    assert perturbed_trend["drift_change"] == p_drift


def test_recorded_history_deltas_telescope_to_the_trend(scrolls_home, capsys):
    # roadmap H143, the worker-facing form: the per-run deltas `maintain --history`
    # reads back from `.maintenance/log.jsonl` (each entry's recorded `delta`,
    # `compute_delta(prev, this)` exactly as a real pass records it) telescope to
    # `compute_trend` over the same read-back window. Ties the trend to the recorded
    # history a worker also reads, through the real `append_log_entry`/`read_log`
    # path — not a hand-summed delta.
    main(["init"])
    path = log_path(get_paths())

    # write the window as a real maintain log: entry[0]'s delta is the first-run
    # (previous=None → null changes); entry[i]'s is compute_delta(S[i-1], S[i]).
    previous = None
    for record in _trend_window(_TREND_SNAPSHOTS):
        snap = record["snapshot"]
        entry = {
            "recorded_at": record["recorded_at"],
            "snapshot": snap,
            "delta": compute_delta(previous, snap),
        }
        append_log_entry(path, entry)
        previous = snap

    window = read_log(path)
    assert len(window) == len(_TREND_SNAPSHOTS)
    assert window[0]["delta"]["first_run"] is True  # the first run telescopes from nothing

    trend = compute_trend(window)

    # telescope the *recorded* deltas (the ones `--history` shows), skipping the
    # first-run entry (null changes) — exactly the consecutive-pair deltas
    steps = [entry["delta"] for entry in window[1:]]
    assert trend["drift_change"] == sum(
        s["drift"]["drifted"]["change"] + s["drift"]["rotted"]["change"] for s in steps)
    assert trend["coverage_change"] == {
        "verified": sum(s["coverage"]["verified"]["change"] for s in steps),
        "total": sum(s["coverage"]["total"]["change"] for s in steps),
    }
    assert trend["stale_change"] == {
        "enrichment": sum(s["enrichment_stale"]["change"] for s in steps),
        "summaries": sum(s["summaries_stale"]["change"] for s in steps),
    }
    assert trend["score"]["change"] == sum(s["score"]["change"] for s in steps)


def test_trend_telescopes_on_count_axes_with_a_null_score_endpoint():
    # honest-absence edge (roadmap H143): a `None`-score endpoint (an
    # uninitialized-library run) yields a *null* trend score change, never a
    # fabricated zero — but the count axes still telescope cleanly (they do not
    # depend on the score). So the score honesty does not break the drift/coverage/
    # stale telescoping.
    snapshots = [
        _snapshot(score=None, drifted=0, rotted=0, verified=0, total=0, enrichment=0, summaries=0),
        _snapshot(score=90, drifted=1, rotted=0, verified=2, total=4, enrichment=1, summaries=0),
        _snapshot(score=80, drifted=1, rotted=1, verified=3, total=5, enrichment=2, summaries=1),
    ]
    trend = compute_trend(_trend_window(snapshots))
    drift, coverage, stale, deltas = _telescoped(snapshots)

    # the score change is the honest null (a None endpoint has no scalar movement)
    assert trend["score"]["change"] is None
    assert trend["score"]["first"] is None
    # the first step's score change is null too (before is None) — so it does *not*
    # telescope on the score axis, exactly why the trend reports null there
    assert deltas[0]["score"]["change"] is None

    # the count axes still telescope — independent of the score
    assert trend["drift_change"] == drift == 2
    assert trend["coverage_change"] == coverage == {"verified": 3, "total": 5}
    assert trend["stale_change"] == stale == {"enrichment": 2, "summaries": 1}


def test_a_sub_two_run_window_has_no_trajectory_to_telescope():
    # honest-absence edge (roadmap H143): a window of fewer than two runs is not a
    # trajectory — a single point has no direction — so `compute_trend` reports
    # *null* deltas and `insufficient-history`, never a fabricated zero. There are
    # no consecutive pairs to telescope, so the null trend is the honest counterpart
    # of "no steps recorded" (distinct from a real 0-change telescope over ≥2 runs).
    for snapshots in ([], [_TREND_SNAPSHOTS[0]]):
        trend = compute_trend(_trend_window(snapshots))
        assert trend["posture"] == "insufficient-history"
        assert trend["score"] is None
        assert trend["drift_change"] is None
        assert trend["coverage_change"] is None
        assert trend["stale_change"] is None
        # no adjacent pairs → no per-run deltas to sum (the empty telescope)
        _, _, _, deltas = _telescoped(snapshots)
        assert deltas == []
