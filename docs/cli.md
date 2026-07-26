# Scrolls CLI Reference

The output contract for every command: arguments, JSON keys, exit codes,
and error envelopes. This is the reference for agents (and contributors)
consuming `scrolls` output programmatically; `README.md` tells the same
story in prose, and `docs/architecture.md` explains the system behind it.

Every example below is real output captured from `scrolls 0.1.0`
(schema version 8) on this branch — see
[Reproducing these examples](#reproducing-these-examples). Each behavior
claim cites the test that locks it; unless noted, tests live in
`tests/test_cli.py`.

## Conventions

- **JSON on stdout.** Every data command prints exactly one compact JSON
  document. Two deliberate exceptions emit Markdown: `scrolls context`
  (the bundle *is* the artifact) and the scroll/library files themselves.
- **Errors are JSON on stderr, exit 1.** Shape: `{"error": "<message>"}`.
  Nothing is printed to stdout in that case
  (`test_detect_rejects_non_http_url`, `test_show_unknown_id_is_an_error`).
- **Batch commands report per-item results.** `fetch`, `classify`, `md`,
  `media`, `rm`, `sync`, `import fieldtheory`, and `kb --engine llm`
  process every item (for `rm`, every ref; for `sync`, every
  subscription; for `kb --engine llm`, every qualifying concept), never
  abort mid-batch, and exit 1 if **any** item *failed* — skipped items
  do not fail the run
  (`test_fetch_continues_past_failures_and_exits_nonzero`,
  `test_fetch_all_skips_sources_without_adapter`,
  `test_media_continues_past_failures_and_exits_nonzero`,
  `test_sync_continues_past_feed_failures_and_exits_nonzero`).
- **`ingest` is the asymmetry to know about:** its failure payload goes to
  *stdout* (with an `error` key merged into the normal payload) plus
  exit 1, because the item was still registered
  (`test_ingest_without_adapter_registers_but_reports_failure`).
- **Library root** is `~/.scrolls`, overridden by `$SCROLLS_HOME`
  (`tests/test_paths.py`). Commands that write auto-initialize the
  library; read-only commands on a missing library return empty results
  rather than errors (`test_list_before_init_prints_empty_array`,
  `test_search_before_init_prints_empty_array`).
- **Item ids** are stable and deduplicating: `source:source_id` when the
  URL carries a source-local id (`wikipedia:en:SQLite`,
  `arxiv:1706.03762`, `x:1111`), else `source:` + a 12-hex-char SHA-256
  of the URL (`tests/test_items.py`).
- **The saved URL works wherever an item id does** (ADR 0028): every
  command that takes an item id (`show`, `fetch`, `classify`, `md`,
  `media`, `set`, `related`, `rm`) also accepts the item's URL, in any
  tracking-decorated spelling — resolved to the id `add` would mint
  (`tests/test_pipeline.py`, `test_show_accepts_item_url`,
  `test_fetch_accepts_item_url`). A URL that matches nothing reports
  the id it resolved to
  (`test_show_unknown_url_reports_the_resolved_id`). Subscription ids
  (`sync`, `unfollow`) are a separate namespace; `unfollow` accepts
  feed URLs already.
- **Stages**: `detected → fetched → rendered`, advanced by
  `fetch` and `md`; `classify`, `media`, and `kb` are stage-neutral.

## The completeness contract

A custody library is only trustworthy if an agent can believe what its
browse and audit surfaces *don't* say as much as what they do. The
integrity boundary is the agent contract (vision §6); false
absence corrupts an agent's memory the same way a fabricated row does.
So every read and audit surface — `search`, `list`, `related`, `works`,
`context`, `doctor`, `maintain` (run offline with `--no-recheck`),
`export bundle` (the shareable artifact), `history` (the per-item custody
ledger), and their MCP twins — honors one
cross-cutting contract:
**results are scope-honest and completeness-honest; "nothing found" is
never confused with "not checked," and nothing is fabricated for content
the library does not hold** (PRD cap 7, MVP M2, an adapted anti-fabrication
mechanism — see
`docs/inspiration/obsidian-second-brain-inspiration.md`). The contract has two
guarantees.

### G1 — Honest absence, honest failure *(enforced; `tests/test_completeness.py`)*

The anti-fabrication core. Three claims, each true across all nine surfaces
and pinned as a single named invariant rather than re-proved per command:

- **Checked-and-empty is exit 0 in the surface's normal shape.** A surface
  that looked at its (possibly scoped) slice and found nothing returns the
  *empty form of its own output* — `[]` for `search`/`list`/`related`,
  `{"works": [], "stats": {…}}` for `works`, a `No matching scrolls.`
  bundle for `context`, a zero-finding report for `doctor`, for `maintain`
  a zero-`issues` report whose audit never fabricates a custody picture (an
  uninitialized library reads `score: null`, never a perfect `100`), for
  `export bundle` a valid, *importable* `No matching scrolls.` bundle (never an
  error, never a fabricated entry), and for `history` an `[]` timeline when the
  item is held but the ledger has never checked it — and exits 0. An empty result is a real
  answer, never an error and never a fabricated row
  (`test_checked_and_empty_is_exit_zero_in_normal_shape`,
  `test_before_init_is_empty_in_shape_across_surfaces`).
- **Could-not-check is exit ≠ 0 with an error envelope on stderr, and
  stdout stays empty.** Bad input (a blank `search`/`context`/`export bundle`
  query) and an unknown id/URL (`related`, `works <ref>`, `show`) are *not
  checked*, and
  they are loud: `{"error": "…"}` on stderr, exit 1, nothing on stdout
  (`test_could_not_check_errors_loudly_not_emptily`). `history` draws the same
  split — a never-checked held item is the empty `[]`, but an unknown ref is a
  loud error, so a typo can never read as "no history."
- **Therefore empty ≠ error.** The exit code plus the stream is the
  discriminator an agent reads: exit 0 + empty-in-shape means "I checked
  this slice and nothing matched"; exit ≠ 0 + `error` on stderr means "I
  could not check." A surface never reports a check it could not perform
  as an empty success (`test_empty_is_distinguishable_from_could_not_check`).

The same invariant holds for the **MCP twins** (`search_scrolls`,
`list_scrolls`, `get_related_scrolls`, `get_works`, `get_context_bundle`,
`get_scroll`, `get_scroll_history`), where "exit 0 + empty shape" becomes "returns the empty
form" and an error envelope becomes a raised tool error — so an agent gets
the same honesty whether it reads the CLI or the protocol server
(vision §6, surface parity;
`test_mcp_checked_and_empty_returns_the_empty_shape`,
`test_mcp_could_not_check_raises_not_emptily`).

A corollary already guaranteed elsewhere and reaffirmed here: a filter or
facet that excludes every item yields the **empty shape, not an error**, so
"nothing in *this* scope" is a first-class honest answer scoped to what was
applied — never a silent claim about the whole library
(`test_a_facet_that_excludes_everything_is_empty_not_error`). And no
surface invents held content: a `reference`-only item reports fidelity
`reference`, not a fabricated body or hash (the fidelity-travels contract,
ADR 0100). Read-only commands on a missing library return the same empty
shape rather than erroring, so the payload shape never varies between "no
library yet" and "library, no matches"
(`test_before_init_is_empty_in_shape_across_surfaces`).

The contract reaches the **compiled `library/` pages** too: their derived
`_Attention:_` / `_Refresh:_` action-pointer lines (roadmap H184) are honest
about absence the same way the JSON flags are — a clean / empty / single-source
compiled library never emits an `_Attention:_` it has no JSON `attention` basis
for, nor a `_Refresh:_` clause for an enrichment/summary axis carrying no stale
debt (roadmap H190; `test_compiled_pages_omit_action_lines_with_no_basis`,
`test_compiled_refresh_line_is_per_axis_honest`).

### G2 — Honest scope, honest completeness *(enforced across every read surface — `search`/`list`/`related` via `--stats`, `works`/`context`/`doctor` always-on)*

A scoped or `--limit`-capped result must let a reader that holds *only the
result* — not the call that produced it — recover the scope it covered and
whether it was truncated. A bare `search`/`related`/`list` array is silent
about both: a 20-row answer to `search "x" --source arxiv --limit 20`
cannot be told from "those are all 200 arXiv matches" by an agent that
didn't make the call, and every search is `LIMIT`-capped, so `len == limit`
is genuinely ambiguous. The contract closes that with a self-describing
companion, building on a shape already in the codebase rather than
inventing a new one:

- **Applied scope travels with the result**, the way `context` already
  prints its facets in the bundle title (`# Scrolls Context Bundle: <query>
  (source=arxiv)`) and `works`/`graph` already carry a `stats` companion.
  A scoped result names the filters it honored; an empty scoped result
  names them too, so "honest about scope" holds for the empty case.
  `scrolls works` echoes its scope explicitly: a `scope` companion naming the
  `min_representations` floor it clustered above, or the `ref` anchor of the
  per-item lens. Because `works` is uncapped — every work at or above the
  floor is reported — the floor *is* its truncation story: a work missing
  from the payload was below the reported floor, not absent from the library.
- **Truncation is explicit.** A capped result distinguishes "this is every
  match" from "top-N of more" — so absence below the cap is never read as
  absence in the library. `--limit 0` already means *zero rows*, not
  *unbounded*, so the cap is always meaningful. `scrolls context` renders this
  as a `Coverage:` line — `all N matching scrolls` when the bundle saw every
  match, `the top N of M matching scrolls` (with the lever to see the rest)
  when the cap hid some — over the same `count_matches` denominator the
  `--stats` envelope uses, so a bundle and a `--stats` search over the same
  scope agree on the match total.
- **`doctor` states what it verified.** The custody report distinguishes
  what it confirmed network-free *this run* (the integrity audit: scroll
  present, hash re-derivable, provenance complete) from what only `scrolls
  verify` can confirm against the live source: "unchanged as of the last
  verify" is not "verified now" (ADR 0098). The `drift` block names its
  `basis` (`last_verify` — its verdicts are read from the ledger, not
  re-checked live) and `as_of` (the freshest verdict the picture rests on),
  and counts `unverified` — held items the ledger has no verdict for, so
  unknown, **not** clean. Drift the report has not re-checked is named as
  un-rechecked, not folded into the healthy counts
  (`test_drift_names_held_items_never_verified_as_unverified`).

**Why the companion is opt-in, not the default shape.** G1 (above) locks
the bare array as the *empty form* of `search`/`list` — `[]`, exit 0 — and
that bare array is also the established CLI/MCP agent contract (every
`search_scrolls`/`list_scrolls` consumer reads a list, vision §6
surface parity). So G2 is delivered as a **deliberate, documented evolution
that adds** rather than replaces: `scrolls search --stats` / `scrolls list
--stats` wrap the array in a `{scope, stats, results}` envelope consistent
with the `stats` companion `works`/`graph` emit, while the default output
stays the G1-locked bare array. A reader that needs scope/truncation
honesty asks for it; nothing existing breaks. The envelope builder
(`src/scrolls/scope.py` `scope_envelope`) is pure, so the load-bearing
truncation arithmetic — `truncated` iff `matched > returned` — is pinned in
isolation (`tests/test_scope.py`); the surface wiring and scope echo are
pinned in `tests/test_cli.py` and `tests/test_search.py`. If always-on
honesty is later preferred, flipping the default is one line atop the same
builder.

The enforcement order is fixed by the roadmap: **H6 (done)** adds the
`--stats` scope + truncation envelope to `search` and `list`; **H7 (done)**
extends the same honesty to `related` (`count_related` is the past-the-cap
denominator), `works` (a `scope` companion naming the floor/anchor, always
on — `works` already emits an object, so there is no bare array to protect),
and `context` (the `Coverage:` line, over `count_matches`); **H8 (done)**
sharpens `doctor`'s drift block — `basis`/`as_of`/`unverified` make it
verified-now-vs-as-of-last-check honest (`docs/agents/autonomous-roadmap.md`).
With H8, **G2 is enforced across every read surface and M2 is complete.**
Each landed with its own tests in the matching suite. That scattered
per-surface scope-echo enforcement is then **consolidated once** (roadmap
H398, the fifth contract-consolidation cell, after the surface-parity matrix)
into `tests/test_completeness_contract.py`: a registry-driven invariant that
*every* browse/audit surface (`search`/`list`/`related`/`works`/`context`/
`doctor` and their MCP twins) is scope-honest and completeness-honest on two
axes. The **completeness keystone** — a `_COMPLETENESS_SURFACES` registry —
partitions the live read registries (`_CLI_READ_PATHS`/H394, `_MCP_READ_TOOLS`/
H388) together with their *named* exemptions, so a **new browse/audit surface
fails until it declares scope-honesty** (`test_completeness_matrix_is_complete`,
`test_completeness_surfaces_partition_the_live_read_registries`). The guard
proves each scope-echoing surface discloses a scope its other-scope read does
not (`test_every_scope_echoing_surface_discloses_its_scope`) and each surface's
empty form is distinguishable from a could-not-check
(`test_cli_every_surface_distinguishes_empty_from_not_checked`,
`test_mcp_every_surface_distinguishes_empty_from_not_checked`); the sabotage
drops one surface's scope echo — so a per-ref read claims whole-library
completeness — and fails *only* that surface's leg
(`test_dropping_a_scope_echo_fails_only_that_surface`). The MCP twins read
from the same builders, so `get_works`/`get_context_bundle` carry the scope
echo and coverage line too. The bare-list `search_scrolls`/`list_scrolls`/
`get_related_scrolls` twins are **array-only by design** (roadmap H163): they
return the bare per-item hit list — the G1-locked browse contract, never an
envelope — because the `--stats` opt-in is a CLI affordance with no natural
MCP analogue (an MCP tool returns one shape, not a flag-toggled one), and
vision §6 surface parity keeps the bare array the agent contract. The
per-source `stats.custody.by_source` split those CLI envelopes carry (H155) is
therefore *not* lost over MCP, only **relocated** to the surfaces that already
return an object: `get_link_graph` and `get_works` carry `stats.custody.
by_source` (H150/H100), and the dedicated whole-library audit
`get_library_health` carries `by_source` (the scope-level custody read over
MCP, H161). That asymmetry — browse twins array-only, the per-source picture
on the object/audit twins — is pinned in `tests/test_mcp.py`
(`test_mcp_browse_twins_are_array_only_per_source_custody_rides_object_twins`),
so a later run cannot silently grow a divergent MCP browse-stats envelope. The
whole MCP read-surface shape — these **array** twins, the **stats-object** twins
(`get_link_graph`/`get_works`), and the **nested audit** twin
(`get_library_health`, exactly `run_doctor`'s custody block) — is consolidated
into one decision-grade contract (`test_mcp_read_surface_shape_contract`, roadmap
H186; the prose home is the "MCP read-surface shape contract" note in
`docs/architecture.md`), so a future read tool has a single shape contract to
satisfy. The **Markdown-string** twins `get_context_bundle`/`get_concept_page`/
`get_tag_page` are the fourth class (roadmap H194): they return a `str` (the
output *is* the artifact, ADR 0077), carrying their custody honesty inside the
rendered text rather than a JSON envelope, pinned by the sibling
`test_mcp_read_surface_markdown_string_class` (which also anchors the context
bundle byte-for-byte to the CLI `context`). G1
is the half that is already true across every surface and is locked so it
cannot regress.

### A sibling invariant — custody reads the same everywhere

Where the completeness contract pins *honesty* (nothing fabricated, scope
disclosed), a sibling invariant pins *convergence*: the custody picture an agent
reads — fidelity-tier counts and drift-posture counts — is identical wherever it
appears. `scrolls status` (the custody headline), the `export bundle` briefing
and `scrolls context` headlines, `scrolls facets fidelity`/`drift`, the `graph`
and `search`/`list --stats` `stats.custody` blocks, and `doctor`'s `custody`
block all derive from one shared tally
(`custody.custody_counts`/`custody_headline` over `get_fidelity` +
`drift_posture`/`latest_events`), so they cannot disagree for a given scope (the
one vocabulary mapping: the posture `verified` is the ledger status
`unchanged`). That scope-level convergence is pinned once, across every surface,
in `tests/test_custody_convergence.py` — the custody-side analogue of
`tests/test_completeness.py` (roadmap H50). The `--stats` envelope's `custody`
member (roadmap H98/H99) is the browse-surface entry in that family, carried by
all three browse surfaces — `search`, `list`, and `related` — through the same
`custody.tally_custody` fold: for a filter-only `list` scope it equals `facets
fidelity`/`drift` for the same filters
(`test_list_stats_custody_member_converges_with_facets`), and on `related` it
covers the anchor's related *neighbourhood* (the full scored set, excluding the
anchor). `scrolls works` carries the same member in its always-on `stats` block
(roadmap H100) — there `tally_custody` folds the reported works' representations,
so the tally describes the multi-representation works in scope. In every case the
counts cover the matched scope, not just the returned page. That whole family is
pinned once (roadmap H101): each `stats.custody` member is asserted to equal the
tally over *its own* returned per-item `fidelity`/`drift` fields — so the envelope
aggregate can never desync from the per-item axes (H56/H58) it sums — with the
`related` anchor excluded, the `works` reps folded, and `graph --all` node ≡ item
scope (`test_stats_custody_family_agrees_with_its_own_per_item_fields`,
`test_works_stats_custody_agrees_with_its_representations`). Each `stats.custody`
member also carries a **`by_source`** split (roadmap H155) — the same matched scope
grouped per source (`custody.tally_custody_by_source` over each hit/representation's
own `source`/`fidelity`/`drift`), a `{source: {tiers, drift}}` map with sorted keys
and an empty `{}` for an empty scope. It is the browse counterpart of the per-source
`by_source` on the `graph` stats block (H150) and JSON `status` (H133): the
per-source entries sum to the whole-scope `stats.custody` beside them by
construction, and — for an uncapped whole-library scope — equal `doctor`'s
`custody.by_source` and `custody_counts_by_source` over the held items *on the
tiers/drift axes* (the lean browse family omits the per-source `coverage` the audit
surfaces add — coverage needs `content_hash` presence a `(fidelity, drift)` pair
cannot recover, so it stays a `doctor`/`graph` axis), pinned in
`test_browse_stats_by_source_converges_with_doctor_for_the_whole_library`. Those
per-surface JSON `by_source` ties (`status` H133, the `graph` block H150, and these
browse envelopes H155) are then pinned *together once* (roadmap H157) — the
JSON-surface sibling of H151's byte-identical readable test — so every structured
`by_source` map reads the same per-source picture in one obvious place
(`test_every_json_by_source_surface_converges_on_one_map`). Beside that map each
`stats.custody` member also distils it to a single weakest-source **`attention`**
flag (roadmap H174) — `{source, tiers, drift, reason, command}`, the source with the
most actionable `drifted + rotted` loss, its tally, a one-line reason, and the exact
`scrolls verify --source <S>` recheck command — via the same `custody.weakest_source`
primitive the `graph` block (H164) and JSON `status`/`maintain` (H139/H119) thread,
so an agent paging results reads *which* matched source most needs action without
scanning `by_source` itself. The browse flag is the **lean** projection: because the
browse `by_source` carries no per-source `coverage` (above), the flag is built with
`include_coverage=False` and carries **no `coverage` member** — never a fabricated
`0/0` a reader would misread as "nothing checked" — so it equals the coverage-bearing
`status`/`graph` flag on every shared field, projected to its lean shape. Honest
`null` on the same three gates as the JSON flag (empty / single-source / fully-clean
scope), so a single-source matched scope flags nothing even with drift; over an
uncapped whole-library scope it names the same source `status`/`graph`/`doctor` do
(`test_browse_stats_attention_converges_with_status_graph_and_doctor`). The
**compiled human-readable**
surface carries that scope picture too (roadmap H97): the KB compiler writes the
same `custody_headline` under each compiled `library/` group list page's count
line (H95) and in the landing `index.md` header (H96), and the invariant parses
it back off a compiled page and asserts its totals equal `custody_counts` for
that page's scope, `facets fidelity`/`drift` for the same `--source` filter, and —
for `index.md` — `doctor`'s `custody` aggregate over the whole rendered library.
So the compiled library's *scope* custody summary reads the same as the agent
aggregates, the scope-level counterpart of the per-item compiled-page tie below.

The same module pins the **per-item** counterpart (roadmap H59): the per-item
`drift` posture now rides every browse/landing surface — `scrolls list` rows and
`scrolls search` hits (H58), `scrolls related` hits and `scrolls graph` nodes
(H56), and the `export bundle` briefing (H42) — each reading the same
`custody.drift_posture` over `latest_events`. The invariant asserts a given item
reads the *same* `drift` on every surface that carries it, and that each
whole-library-enumerating surface's per-item posture counts total `facets drift`'s
count for that posture — tying the per-item axis back to the aggregate. Those
surfaces all carry only the *latest* posture; `scrolls history` reads the *full*
per-item ledger back, and the invariant pins the tie (roadmap H70): the posture
the head of the ledger `history` returns implies equals the `drift` every
latest-posture surface shows for that item (and `[]` ⇒ `unverified`), so the
full timeline an agent reads can never silently disagree with the postures that
summarize it. The time-axis counterpart (roadmap H84/H86/H87) is pinned the same
way: the `last_checked` timestamp `scrolls list`/`search`/`show` rows, `scrolls
related` hits, `scrolls graph` nodes, and `scrolls works` representations carry
beside `drift` equals the `checked_at` of that `history` head (and `null` ⇔ the
empty timeline ⇔ never re-checked), so the staleness an agent reads off a browse
row, a node, or a representation matches the ledger exactly. And just as the drift
posture has a single whole-library agreement test, the time axis has its mirror
(roadmap H88): one fixture, one assertion that a given item reads the *same*
`last_checked` on every surface that carries it — including the `export bundle`
briefing, whose `as of <date>` / "never re-checked" prose carries the timestamp in
Markdown — so a desync on any surface fails in one obvious place. The
**human-readable** surface those JSON rows previously skipped is folded in too
(roadmap H91): the `· <fidelity> · <drift>` marker the KB compiler writes on the
compiled `library/` list-page rows (H89) is parsed back off a compiled page and
asserted to equal the canonical `(get_fidelity, drift_posture)` and the `scrolls
list` surface — so the compiled library a human browses reads the same per-item
custody picture an agent does. The **model-facing `scrolls context` bundle** is
folded in the same way (roadmap H94): at the `full` budget each excerpt carries a
per-source `_drift <posture> · last seen <checked_at>_` tag (H62/H90), parsed back
off the excerpt and asserted to equal the `drift`/`last_checked` `scrolls show`
reports for that item (with `never re-checked` ⇔ the `unverified`/`null` honest
absence) — so the per-source custody in the bundle an agent drops into its window
can never silently desync from the inspect surface.

The module also pins the **portable-custody** round-trip (roadmap H73): since
the verify ledger travels (in the `export bundle` and as the whole-library
`export events` stream, H67/H72), the posture an item reads after an
export→import equals the posture it read before. It round-trips the four-posture
fixture into a fresh library and asserts that library reproduces the original's
per-item posture on every surface and its `facets drift` aggregate — custody
itself round-trips, not just the item. A companion case (roadmap H78) extends
this to the **incremental** backup: a full `export events` plus an overlapping
`export events --since` window, restored as their union in one import, is as
lossless for custody as the whole-ledger path — the union dedups (no
double-count) and the fresh library still reproduces the original's posture and
facets, so the windowed backup loses nothing the whole one keeps.

Finally, the module pins the **verify-selection family** (roadmap H81) — the
*act* side of the same custody picture the read surfaces enumerate. `scrolls
verify` carries six batch selections over the same `custody`/`items` selectors:
`--unverified` (`unverified_items`), `--stale-before` (`items_checked_before`),
`--drift` (`items_in_posture`), `--source` (the item-intrinsic `source` filter,
reading no ledger — roadmap H125), and `--fidelity` (the item-intrinsic
`get_fidelity` filter, the holdings axis, also reading no ledger — roadmap H252),
plus `--all`. The invariant asserts they relate as documented: `verify --drift
<posture>` re-captures exactly the rows `list --drift <posture>` enumerates (the
act-side ≡ read-side drill, by the shared `items_in_posture`); `verify --source
<S>` re-captures exactly `list --source <S>`'s held, hash-bearing rows and clears
that source's `unverified` count in `doctor`'s `custody.by_source[S]` (the
per-source counterpart of how `--unverified` clears the whole-library bucket);
`verify --fidelity <tier>` re-captures exactly `list --fidelity <tier>`'s held,
*hash-bearing* subset (genuinely narrower than the listing — a `full` capture held
by `raw_text` alone has no hash to diff, so it lists `full` yet is skipped); `verify
--stale-before <future>` re-checks a *superset* of `--unverified` and clears the
same `doctor custody.drift.unverified` bucket it subsumes; and every batch
selection skips reference-only items identically (no baseline hash to diff). So
the verify selections are a tested, actionable face of the custody read surfaces.

The **scheduled** member of that family is pinned the same way (roadmap H111). A
default `scrolls maintain` pass stale-bounds its recheck to the held items not
seen since the last run (H83) — the boundary is the last recorded snapshot's
`recorded_at` (`maintain.last_run_boundary`), and the set is `items_checked_before`
at it, the *same* selector `verify --stale-before <ISO>` (H79) uses explicitly. The
invariant captures (via a recording recapture stub) the set each pass actually
re-verifies and asserts the set a default maintain pass targets equals the set
`verify --stale-before <last-run recorded_at>` would, that the never-checked
`--unverified` bucket is subsumed by it (trivially stale at any boundary), and that
`maintain --all` ignores the boundary and rechecks the whole hash-bearing set (the
H83 escape hatch). So maintain's recurring recheck is the self-timestamping face of
the verify-selection family, not a parallel-implementation coincidence.

The **per-source** picture the scheduled worker reports is pinned to the audit the
same way (roadmap H127/H129). `scrolls maintain` carries a live-pass `by_source`
breakdown (H123) and distils it to a single weakest-source `attention` flag (H119);
both are pure reads of the `doctor` audit the pass already runs, so the invariant
pins their convergence directly: over the multi-source seed a `maintain --no-recheck`
pass's `by_source` equals `doctor`'s `custody.by_source`, `custody_counts_by_source`
over the held items, and `facets fidelity`/`drift --source <name>` per source (H127);
and its `attention.source` equals the source maximizing `drifted + rotted` in that
map, with `attention` honestly `null` exactly when no source carries actionable loss
(H129). `--no-recheck` keeps the pass network-free and the ledger pristine, so the
scheduled worker's per-source picture and a fresh standalone audit read identical
state — the per-source-maintenance counterpart of the `stats.custody` family (H101)
and stale-recheck (H111) ties above.

The **scoped read** is the read-side sibling of that per-source breakdown:
`doctor --source S` (roadmap H162), `status --source S` (H166), `maintain --source
S` (H165), and MCP `get_library_health(source=S)` (H167) each scope the *whole*
custody read to one source's held items through the **same** `run_doctor(source=)`
pre-filter, so a worker triaging the weakest source reads its full picture directly
instead of slicing it out of the whole-library report. Each is pinned to its
neighbour in its own test, and the consolidating property is pinned *once* (roadmap
H169, the capstone — the scoped-read sibling of H157's whole-library JSON
`by_source` consolidation): over the multi-source loss seed all four `--source S`
reads agree (the snapshot-shaped pair `status`/`maintain` equals the distilled
scoped `doctor` audit; the raw-block MCP read equals the scoped `doctor` block key
for key), each lines up with the whole-library audit's `by_source[S]` slice,
`by_source` collapses to the present-and-singleton `{S: …}`, the rendered headline
is identical across the three that render one, and `attention` is honestly `null`
on each (the single-source gate has nothing to rank across). Non-vacuous (the two
sources differ on every axis) and mutation-checked
(`test_per_source_scope_capstone_all_four_scoped_reads_agree`) — so the scoped
custody picture is one number whichever surface a worker or agent reaches, and a
future scoped surface has a single contract to satisfy.

The **holdings-axis scope twin** is `maintain --fidelity <tier>` (roadmap H255) —
the scheduled-maintenance *act* twin of `verify --fidelity` (H252), so a worker can
maintain "just my full-fidelity holdings". It is the holdings-axis sibling of
`maintain --source`, but it narrows *less*: only the **recheck** targets the tier
(the `verify --fidelity <tier>` held, hash-bearing subset — folding the same
`get_fidelity` primitive, so a `full` capture held by `raw_text` alone is listed but
skipped, and a tier with no fingerprint like `reference` is an honest empty no-op);
the **audit and view regeneration stay whole-library**. A fidelity tier spans
sources, so `run_doctor`'s source semantics (the `by_source` singleton-collapse, the
orphan/FTS skip) do not apply to it — scoping the audit is a separate, larger change
deferred unless the recheck-only shape proves insufficient. Like `--source` the pass
is **non-persisting**: it records per-item drift events (the next whole-library pass
folds them into the trend) but never writes the single whole-library snapshot/log
baseline, so a partial-recheck pass cannot stamp the trend as if it had rechecked
everything — its `delta` is honestly `null`. The vocabulary is closed (argparse
`choices`: a typo is exit 2); it composes with `--all`/`--limit`/`--no-recheck` and
conflicts with `--source` (one scope axis per pass) and `--history` (a read, not a
pass). CLI-only — no MCP batch-maintain scope twin, the `verify --fidelity` (H252)
precedent (`test_fidelity_audit_and_regen_stay_whole_library_unlike_source` and its
siblings in `tests/test_maintain.py`).

The **readable per-source breakdown** carries its own one-place tie (roadmap H151).
The `_By source:_` bullets that follow a scope custody headline ride four readable
surfaces — the `export bundle` briefing (H141) **and its HTML form**, the
model-facing `scrolls context` bundle (`connected`+, H149), the compiled landing
`index.md` (H145), and a multi-source compiled group page (`categories/`/`concepts/`/
`tags/`, H152) — each rendered through the shared `custody.render_custody_by_source`.
The invariant pins that over one multi-source seed (all rendered, all one category,
every title matching the bundle/context query, so all four surfaces scope to the
whole library) every surface renders **byte-identical** per-source bullets — the HTML
`<li>` form parsed back to the same Markdown bullet — all equal to
`render_custody_by_source` over both `doctor`'s `custody.by_source` and
`custody_counts_by_source`, and that each surface's bullets sum to its own scope
headline. So the per-source line reads the same number whichever readable surface an
agent reaches; it is the readable-line analogue of the JSON `by_source` convergence
(`status` H133, the `graph` `stats.custody.by_source` H150, the `list`/`search
--stats` envelopes H155 — pinned together once in H157,
`test_every_json_by_source_surface_converges_on_one_map`), pinned once in
`tests/test_custody_convergence.py` like the per-item and scope-headline ties above.
Each readable bullet also trails a `coverage V/T` section (roadmap H158); a sibling
tie pins its *value* — the readable coverage on each bullet equals the JSON
`by_source[S].coverage` (`doctor`'s map and the shared tally's) for that source — the
readable-coverage counterpart of the per-source coverage axis (H121), so the surfaces
an agent reads and the audit can never disagree on how much of a source is checked
(`test_readable_per_source_coverage_converges_with_the_json_by_source`).

Above that `_By source:_` map, the readable surfaces carry the **weakest-source
`_Attention:_` line** (roadmap H159) — the readable counterpart of the JSON
`attention` flag `scrolls status`/`maintain` carry. One line names the single source
with the most actionable loss and the exact recheck command —
`_Attention: source `<S>` carries the most drift (N drifted, M rotted) — recheck with
`scrolls verify --source <S>`._` — so an agent skimming the `export bundle` briefing
(Markdown **and** its HTML form, a red `custody-attention` paragraph) or the
`scrolls context` bundle (`connected`+) reads "this one source needs attention" before
scanning the whole map. It is distilled by the shared `custody.weakest_source`
primitive (now home in `custody.py` beside `custody_counts_by_source`, re-exported by
`maintain`) over the bundle scope's *own* per-source map, so the line names the same
source, reason, and command as the JSON flag by construction. Honest absence — omitted
entirely when no source carries actionable loss (single-source, clean, or empty scope),
exactly when the JSON `attention` is `null`. The readable-line tie is folded into the
convergence spine beside the JSON `attention` tie: every readable surface's parsed
`{source, reason, command}` equals `weakest_source(doctor.custody.by_source)` and the
`status`/`maintain` flag, all absent together on a clean scope
(`test_readable_attention_line_converges_across_surfaces_and_the_json_flag`,
`test_readable_attention_line_absent_together_with_the_json_flag`). The **full
field-for-field** invariant sharpens that tie (roadmap H160): the readable surface
distilled — the `_Attention:_` line's source / loss reason **decomposed into
`{drifted, rotted}`** / recheck command, *plus* the flagged source's `_By source:_`
`coverage V/T` section (H158) — carries the same `{source, drifted, rotted, coverage,
command}` the JSON `status`/`maintain` flag does, all equal to
`weakest_source(doctor.custody.by_source)`. Pinned over a seed whose weakest source
carries both a drifted and a rotted item over a partial `2/3` coverage (so every field
is non-trivial) and mutation-checked — perturbing any one field of any surface's
distillation breaks the tie
(`test_attention_flag_full_shape_converges_field_for_field`).

Directly beneath that per-source drift `_Attention:_` line, the `export bundle` and
`scrolls context` briefings carry a **work-level `_At-risk work:_` line** (roadmap
H264) — the *consolidation*-level counterpart of the per-**source** `_Attention:_`
line, the readable form of the at-risk-works alarm `doctor`'s `custody.works` /
`maintain`'s `at_risk_works` / MCP `get_library_health` carry as JSON. Where
`_Attention:_` names the single source with the most per-*item* loss, this names the
single **work** no representation *safely holds* — `_At-risk work: `<doi>` — no
representation is both full and unmoved (best held <tier>, safest drift <posture>);
N work(s) at risk._` — so an agent skimming the briefing reads "this work is at risk"
without re-running `doctor`. It is distilled by the shared
`works.render_at_risk_works` over the briefing scope's own clustered works (the same
`works.at_risk_signal` fold the JSON surfaces read), reusing `most_at_risk`'s `doi`
and `reason` verbatim, so the line names the same work as the JSON alarm by
construction; the trailing `N work(s) at risk` is the `at_risk` count, so a reader
knows whether the named work is the only one or the worst of several. The scope is
the **lean** reading — the works the briefing's matched set touches: `export bundle`
clusters its whole gathered item set, while `scrolls context` clusters the
*uncollapsed* matched scope (its `items` are collapsed to one canonical per work, so
a work's full custody picture — including a folded full+verified sibling that makes
it safely held — lives in the whole matched set, not the kept canonicals). Gated to
`connected`+ on `scrolls context` like the headline (the `index` tier reads no
ledger), always present on `export bundle`. Honest absence — omitted entirely when
no multi-representation work in scope is at risk (a clean, single-representation, or
empty scope), exactly when `most_at_risk` is `null`. The line lives **outside** the
lossless `@generated` JSONL fence, so it never touches the round-trip
(`test_at_risk_work_line_preserves_the_round_trip`,
`test_context_at_risk_work_line_mcp_parity`). The helper lives in `works.py` beside
`at_risk_signal` (not in `custody.py` with `render_custody_attention`): `works`
imports `custody`, so a `custody.render_at_risk_works` calling `at_risk_signal` would
close an import cycle — the home follows the primitive it distils. The **HTML
`export bundle` form** carries the same line (roadmap H271) — a red `custody-at-risk`
paragraph grouped with the `custody-attention` line and above `custody-refresh`,
distilled from the *same* `at_risk_signal` over the same lean scope — so the two
bundle forms cannot desync (the `custody-attention` HTML-twin precedent, H39).

That work-level `_At-risk work:_` line also rides the **compiled landing
`library/index.md`** (roadmap H269) — the consolidation alarm on the static
compiled surface, the at-risk counterpart of the whole-library `_Custody:_` headline
(H96). It sits directly beneath the headline, grouped with the per-source
`_Attention:_` line and above the `_Refresh:_`/`_By source:_` map — the same
`export bundle`/`scrolls context` order — through the *same* shared
`works.render_at_risk_works` over the rendered library, so a human browsing the
compiled library reads the same alarm an agent reads from `doctor`. Unlike the
per-**source** `_Attention:_`/`_Refresh:_` lines (which ride every multi-source group
page over its own members), the at-risk line rides **only `index.md`**: the
consolidation alarm is **non-source-attributable** — a work spans sources, so a
scoped group page would fragment its representations into single-rep clusters
(dropped by the `min_representations` floor) and could not converge with the
library-wide audit, exactly why `doctor`'s `custody.works` is *skipped* under
`--source`. The line sits **inside** the page's `@generated` sentinel fence (ADR
0102) — regenerated content like the headline and `_By source:_`, so a recompile
refreshes it (a recapture clears it) while a hand annotation outside the fence
survives. It converges with `doctor`'s `custody.works` over the whole rendered
library by construction (the parse-it-back tie the compiled custody headlines hold,
H97), and honest absence — no line — when no multi-representation work is at risk
(`test_compiled_index_at_risk_line_converges_with_doctor_works`,
`test_kb_group_pages_omit_the_at_risk_work_line`,
`test_kb_at_risk_work_line_is_refresh_safe`).

Grouped with those divergence lines, the `export bundle` and `scrolls context`
briefings carry a **`_Conflicts:_` line** (roadmap H277) — the readable completion
of `doctor`'s `custody.conflicts` JSON aggregate (H275, ADR 0104), the
**import-conflict-axis counterpart** of the drift `_Attention:_` line. Where
`_Attention:_` names the source whose *live source moved*, this names how many held
items carry an *unresolved import conflict* — a peer's capture of an id disagreed
with the held copy at merge time, and the divergence is still open (the held copy is
never auto-overwritten — raw is sacred): `_Conflicts: N item(s) carry an unresolved
import conflict._`, with the HTML twin `<p class="custody-conflicts">Conflicts: N
item(s) carry an unresolved import conflict.</p>`. It folds the *same*
`custody.unresolved_conflicts` predicate over the same `custody.latest_conflict_events`
map `doctor`'s `custody.conflicts` reads (the shared `custody.render_custody_conflicts`
helper), so the readable count and the JSON `items` cannot disagree for the same
scope. Unlike `_Attention:_`/`_Refresh:_`, it names **no command** — the resolution
act, a reviewed `reconcile` (roadmap H276), does not exist yet, so the line surfaces
the count only (fabricating a command would violate the orphan-command discipline;
the per-item detail lives on `doctor`'s `custody.conflicts.events` and `scrolls
history <id> --status conflict`). Folded over the briefing's own `items` (the
per-*item* custody axis the headline and `_Attention:_` line use — a conflict is a
per-item fact, not a work consolidation), gated to `connected`+ on `scrolls context`
like the headline (the `index` tier reads no ledger), and **export-only** on the
bundle (a derived read view, never inside the lossless `@generated` JSONL fence, so
the round-trip is untouched). Honest absence — omitted entirely when no held item in
scope carries an unresolved conflict, and a *resolved* conflict (the held copy now
matches the incoming hash) drops out via the resolution-aware predicate
(`test_bundle_carries_a_conflicts_line`, `test_conflicts_line_converges_with_doctor`,
`test_conflicts_line_is_resolution_aware`, `test_context_conflicts_line_mcp_parity`).

Grouped with those divergence lines, the `export bundle` and `scrolls context`
briefings carry an **`_Archive:_` line** (roadmap H319/H320) — the readable completion
of `doctor`'s `custody.archive` integrity audit (H293), the **recovery-store-axis
counterpart** of the `_Conflicts:_` divergence line. Where `_Conflicts:_` names held items whose *peer
capture disagreed at merge time*, this names how many in-scope **archived priors** are
corrupt — their advertised `prior_hash` (the fingerprint `archive list` / `archive
restore --hash` key on) no longer equals their `snapshot` body's own `content_hash`, a
custody-honesty bug invisible until restore (`archive restore --hash <prior_hash>`
would silently adopt content with a *different* hash than advertised):
`_Archive: N prior(s) fail integrity (prior_hash ≠ snapshot)._`, with the HTML twin
`<p class="custody-archive">Archive: N prior(s) fail integrity (prior_hash ≠
snapshot).</p>`. It folds the *same* `items.archive_integrity_block` over the same
in-scope `items.archived_records` `doctor` reads whole-library, rendered via the *same*
`maintain.archive_integrity_headline` the scheduled-maintenance `_Archive:_` line uses
(H298/H299). On both briefings the fold + render flow through one shared
`maintain.render_archive_integrity(db_path, item_ids)` (H320) — the `export bundle`'s
`_archive_integrity_lines` delegates to it, byte-identical — so the two readable
surfaces, the maintenance summary, and the JSON audit cannot desync (the
divergence-truth source extended from the *block* to the rendered *line*). The scope is
**in-scope** (the briefing's own items' archive, the `_Conflicts:_` / `--with-archive`
semantics — a corrupt prior on an item outside the query is not the briefing's to flag).
On the `export bundle` the line renders **unconditionally** — *independent of
`--with-archive`*: that flag governs whether the archive *data* travels, not whether
custody honesty about it does (custody §2.4 — fidelity/provenance ride every result). On
`scrolls context` it is gated to **`connected`+** like the headline / `_Conflicts:_` /
`_At-risk work:_` lines (the leanest `index` tier reads no recovery store, so it makes no
archive claim). Like `_Conflicts:_` it names **no command** (doctor never auto-rewrites
the recovery store — the suggested-block orphan discipline; the honest fixes are
re-import from a clean source or `archive prune` of the corrupt prior, both operator
acts) and is **export-only** on the bundle (a derived read view, never inside the
lossless `@generated` JSONL fence, so the round-trip is untouched). Honest absence —
omitted entirely when no in-scope archived prior is corrupt (the omit-when-clean briefing
posture). Folded over the per-*item* collapsed `items` (the `_Conflicts:_` choice — a
per-item custody fact, not a work consolidation)
(`test_bundle_carries_an_archive_integrity_line`,
`test_archive_line_converges_with_doctor`, `test_archive_line_is_in_scope`,
`test_archive_line_renders_without_with_archive`,
`test_bundle_html_carries_an_archive_integrity_line`,
`test_context_carries_an_archive_integrity_line`,
`test_context_archive_line_gated_off_index`,
`test_context_archive_line_mcp_parity`).

That `_Archive:_` line also rides the **compiled landing `library/index.md`** (roadmap
H321) — the recovery-store counterpart of the at-risk-works `index.md` line (H269) and
the whole-library `_Custody:_` headline (H96). It sits directly beneath the headline,
grouped with the per-source `_Attention:_` and work-level `_At-risk work:_` lines and
above the `_Refresh:_`/`_By source:_` map — the same `export bundle`/`scrolls context`
order (Attention → At-risk → Archive; the compiled pages carry no `_Conflicts:_` line) —
through the *same* shared `maintain.render_archive_integrity` the briefings fold, so a
human browsing the compiled library reads the same alarm an agent reads from `doctor`.
Unlike the briefings (which scope to their own items) the compiled line is
**whole-library** — `render_archive_integrity(db, None)` over the entire recovery store
(`items.archived_records(db)`), exactly the set `doctor`'s `custody.archive` folds —
because a compiled landing page is the library-wide view, not a query scope. Like the
at-risk line it is **non-source-attributable** (the recovery store is a single
whole-library store) and so rides **only `index.md`**: the scoped group pages omit it. It
sits **inside** the page's `@generated` sentinel fence (ADR 0102) — regenerated content
like the headline and `_By source:_`, so a recompile refreshes it (repairing or pruning
the corrupt prior clears it) while a hand annotation outside the fence survives. It
converges with `doctor`'s `custody.archive` over the whole library by construction, names
**no command** (the at-risk/conflicts orphan-command discipline), and honest absence — no
line — when the store is clean or empty (`test_kb_index_carries_an_archive_integrity_line`,
`test_kb_index_archive_line_converges_with_doctor`,
`test_kb_index_archive_line_converges_with_shared_renderer`,
`test_kb_index_groups_archive_line_with_the_loss_pointers`,
`test_kb_group_pages_omit_the_archive_line`,
`test_kb_index_omits_archive_line_when_store_is_clean`,
`test_kb_archive_line_is_refresh_safe`).

Grouped with those divergence lines, the `export bundle` and `scrolls context`
briefings also carry a **`_Duplicates:_` line** (roadmap H331) — the readable
completion of `doctor`'s `custody.content_duplicates` report (H325), the
**content-identity-axis sibling** of the `_Archive:_` line. Where `_Archive:_` flags a
corrupt recovery store, this flags **byte-identical holdings** — when ≥2 in-scope items
hold the same non-null `content_hash` under *different* ids (the same bytes saved from
two URLs, a mirror, a cross-post, or one work captured by two source adapters — a
genuinely new custody *shape*, vision §2.7, distinct from URL-spelling
duplicates and from canonical DOI works): `_Duplicates: N group(s) of byte-identical
content (M item(s))._`, with the HTML twin `<p class="custody-duplicates">Duplicates: N
group(s) of byte-identical content (M item(s)).</p>`. It folds the *same*
`items.content_duplicate_groups` (H325) over the briefing's in-scope items and renders
via the *same* `maintain.duplicates_headline` the scheduled-maintenance `_Duplicates:_`
line uses (H327) — **point-in-time, no cross-run trend clause** (a briefing carries no
delta, the `_Archive:_` posture) — through one shared
`maintain.render_content_duplicates(items)`, so the bundle line, the context line, the
`maintain` headline, and the JSON audit cannot desync. H327 surfaced the count on the
scheduled `maintain` pass; H331 lifts it to the shareable briefing an operator shares
(and a recipient reads). The scope is **in-scope** (the `_Conflicts:_` precedent — a
content group split by the scope reads only its in-scope members), and folded over the
**uncollapsed** matched set (the bundle's gathered `items`, `scrolls context`'s
`scope_items` — *not* the work-collapsed `items` the per-item `_Conflicts:_`/`_Archive:_`
lines use): content identity is *relational* across distinct ids, so a work-collapse
must not hide two byte-identical representations of one work (the H329
preprint-mirrored-into-DOI case) — it patterns with the work-level `_At-risk work:_`
line, not the per-item ones. On `scrolls context` it is gated to **`connected`+** like
the headline. It is **report-only** — names **no command** (raw is sacred; two faithful
copies are a redundancy fact an operator may *want*, never a `--fix` merge, the
no-fabricated-act discipline) — and **export-only** on the bundle (a derived read view,
outside the lossless `@generated` fence, so the round-trip is untouched). Honest
absence — omitted entirely on a clean/unique/empty scope (the omit-when-clean briefing
posture; `duplicates_headline` itself omits the line whenever `total_groups == 0`)
(`test_bundle_carries_a_content_duplicates_line`,
`test_bundle_duplicates_line_converges_with_doctor`,
`test_bundle_duplicates_line_is_in_scope`,
`test_bundle_html_carries_a_content_duplicates_line`,
`test_bundle_html_duplicates_count_matches_markdown`,
`test_context_carries_a_content_duplicates_line`,
`test_context_duplicates_line_sees_within_work_copies`,
`test_context_duplicates_line_gated_off_index`,
`test_context_duplicates_line_mcp_parity`).

That `_Duplicates:_` line also rides the **compiled landing `library/index.md`** (roadmap
H334) — the content-identity counterpart of the at-risk-works `index.md` line (H269) and
the recovery-store `_Archive:_` line (H321), the static-surface complement to H333's
*per-item* "also held as" marker. It sits directly beneath the `_Custody:_` headline,
grouped with the work-level `_At-risk work:_` and recovery-store `_Archive:_` lines and
above the `_Refresh:_`/`_By source:_` map — the same `export bundle`/`scrolls context`
order (Attention → At-risk → Archive → Duplicates; the compiled pages carry no
`_Conflicts:_` line) — through the *same* shared `maintain.render_content_duplicates` the
briefings fold, so a human browsing the compiled library reads the same redundancy an
agent reads from `doctor`. Unlike the briefings (which scope to their own items) the
compiled line is **whole-library** — `render_content_duplicates(None, db)` over the entire
holdings (`items.list_items(db)`, exactly the set `doctor`'s `custody.content_duplicates`
folds; the renderer's `None` scope loads the whole library, while a `[]` scope stays the
honest in-scope-of-nothing empty audit) — because a compiled landing page is the
library-wide view, not a query scope. Like the archive line it is
**non-source-attributable** (a content group spans sources, so a scoped group page
fragments it below the 2-id floor) and so rides **only `index.md`**: the scoped group pages
omit it. It sits **inside** the page's `@generated` sentinel fence (ADR 0102) — regenerated
content like the headline and `_By source:_`, so a recompile refreshes it (pruning or
re-capturing a byte-identical copy clears it) while a hand annotation outside the fence
survives. It converges with `doctor`'s `custody.content_duplicates` over the whole library
by construction, names **no command** (raw is sacred; two faithful copies are a redundancy
fact, never a `--fix` merge, the no-fabricated-act discipline), and honest absence — no
line — when the library holds nothing byte-identical
(`test_kb_index_carries_a_content_duplicate_line`,
`test_kb_index_content_duplicate_line_converges_with_doctor`,
`test_kb_index_content_duplicate_line_converges_with_shared_renderer`,
`test_kb_index_groups_content_duplicate_line_with_the_loss_pointers`,
`test_kb_index_omits_content_duplicate_line_when_library_is_unique`,
`test_kb_index_content_duplicate_line_is_whole_library`,
`test_kb_group_pages_omit_the_content_duplicate_line`,
`test_kb_index_content_duplicate_line_is_refresh_safe`).

Beside that drift `_Attention:_` line, the readable briefings also carry a
**per-source `_Refresh:_` line** (roadmap H178) — the enrichment/summary-axis
counterpart. Where `_Attention:_` names the source carrying the most drift and the
`verify --source <S>` recheck, `_Refresh:_` names the source(s) whose
classifications or summaries were produced under a superseded ruleset / changed
membership, and the *refresh* to run —
`_Refresh: classifications stale in `<S>`, … — refresh with `scrolls classify
--stale --source <S>`; summaries stale in `<S>`, … — refresh with `scrolls kb
--stale --source <S>`._` — so an agent skimming the `export bundle` briefing
(Markdown **and** its HTML form, an amber `custody-refresh` paragraph) or the
`scrolls context` bundle (`connected`+) reads "this source's enrichment needs
refreshing" without re-running `doctor`. The two source maps are computed over the
bundle's **own scope** items (the scope-consistent posture the `_Attention:_` line
takes) by the *same* `classify.stale_classification_counts_by_source` /
`kb_llm.stale_summary_counts_by_source` builders `doctor`'s
`custody.enrichment.by_source` / `custody.summaries.by_source` fold — so the line
names exactly the sources the audit maps do by construction
(`test_readable_refresh_line_converges_with_the_doctor_debt_maps`). Only the axes
that carry debt appear; the command is a `--source <S>` *template* (one run per
named source). Two deliberate differences from `_Attention:_`: it carries the
**summary axis** with the H171 multi-source attribution (a stale cluster's every
member source is named, so the summary clause can list more sources than there are
stale concepts), and it has **no single-source gate** — refresh debt is per-source
actionable work, not a cross-source comparison, so a single-source bundle with a
stale classification still shows it (the custody headline carries fidelity/drift,
not enrichment freshness, so it would otherwise hide the debt). Honest absence —
omitted entirely when no source carries refresh debt on either axis. The readable
line lives **outside** the lossless `@generated` JSONL fence, so it never touches
the round-trip (`test_refresh_line_preserves_the_round_trip`).

Both action lines also ride the **compiled `library/` pages** (roadmap H184) — the
landing `index.md` and every multi-source group page (`categories/`/`concepts/`/
`tags/`) carry `_Attention:_` then `_Refresh:_` between the scope custody headline
and the `_By source:_` map, the human-browseable counterpart of the bundle/context
briefings, through the *same* `custody.render_custody_attention` /
`custody.render_custody_refresh` primitives. The refresh debt is computed over each
page's **own** members (the scope-consistent posture above): a whole-library
`index.md` over every rendered item, a group page over its members — so a
single-source `sources/*.md` page (or a category narrowing a multi-source concept
below `MIN_MEMBERS`) names exactly the debt its scope carries, and a single-source
page shows `_Refresh:_` (no single-source gate) but never `_Attention:_`/`_By
source:_`. On a compiled page the lines sit **inside** the page's `@generated`
sentinel fence (ADR 0102) — they are regenerated content like `_By source:_`, so a
recompile refreshes them while a hand annotation outside the fence survives. Pinned
in the convergence spine beside the bundle/context ties: over one multi-source seed
the compiled `_Attention:_` line equals `weakest_source(doctor.custody.by_source)`
== the JSON `status` flag and the compiled `_Refresh:_` clauses name exactly
`doctor`'s `enrichment.by_source`/`summaries.by_source` keys, mutation-checked
(`test_compiled_pages_carry_the_action_lines_converging_with_doctor`).

Beyond *converging with doctor*, both action lines are pinned **byte-identical
across every readable surface** (roadmap H188) — the action-line counterpart of
H151's byte-identical `_By source:_` invariant. Over a scope identical across the
bundle query, the `scrolls context` query, the compiled `index.md`, and a compiled
group page, each rendered `_Attention:_` / `_Refresh:_` line is character-for-character
the same string and equals `render_custody_attention` / `render_custody_refresh`
over the shared scope, so the one shared renderer is the only source of the wording
and no surface can drift in punctuation or phrasing
(`test_action_lines_are_byte_identical_across_readable_surfaces`). And their
**honest absence** on the compiled pages is folded into the completeness contract
(roadmap H190): a clean / empty / single-source compiled library never emits an
`_Attention:_` it has no JSON `attention` basis for, nor a `_Refresh:_` clause for an
enrichment/summary axis carrying no stale debt
(`test_compiled_pages_omit_action_lines_with_no_basis`,
`test_compiled_refresh_line_is_per_axis_honest`).

Finally, the **trend layer** is pinned to the per-run history the same way
(roadmap H143). `maintain --trend` reports the net first→last movement on
`drift_change`/`coverage_change`/`stale_change`/`at_risk_change`/`conflicts_change`/`archive_mismatched_change`
(and the scalar `score.change`) by reading only the window's *endpoints*
(`compute_trend`), while
`maintain --history` shows the per-run before/after/change `compute_delta` records
between consecutive snapshots. `at_risk_change` (roadmap H267) is the net change in
the **at-risk-works** count — the works no representation safely holds (`doctor`'s
`custody.works.at_risk`, the H263 consolidation alarm) — recorded as the scalar
`at_risk` in each `custody_snapshot` and folded into the `delta` like the other
scalars; it is the *consolidation-loss-over-time* axis, so an operator reading the
trend sees "2 → 4 works at risk over the last 5 runs" without re-auditing each run.
`conflicts_change` (roadmap H279/H283) is the matching axis for the **unresolved
import-conflict** count (`doctor`'s `custody.conflicts.items`) — recorded as the
scalar `conflicts` in each snapshot since H279 and *differenced* since H283 — the
*peer-divergence-over-time* axis ("1 → 0 unresolved conflicts after a `reconcile`").
`archive_mismatched_change` (roadmap H293/H298/H299) is the matching axis for the
**archive-integrity mismatch** count (`doctor`'s `custody.archive.mismatched`) —
recorded as the scalar `archive_mismatched` in each snapshot since H298 and *differenced*
since H299 — the *recovery-store-corruption-over-time* axis ("0 → 2 corrupt priors after
a bad bundle import, then → 0 once repaired"). Like `coverage_change`/`stale_change` all
three are **reported axes, never a `posture` trigger** — the at-risk count re-views the
same `fidelity`/`drift` the score and `drift_change` already move the posture on (folding
it in would double-count the loss), the conflict count moves neither the score nor the
drift axis (the held copy is never overwritten — raw is sacred, custody §2.4), and the
archive mismatch is a corrupt *recovery convenience*, not the root of trust (the held
copy is intact — H293), so it too stays out of the integrity-first posture. The
invariant pins that the trend's net change equals the **telescoped sum** of those
per-run deltas across the window — on every axis — so the trajectory a worker reads
can never silently disagree with the step-by-step history it also reads. It asserts the identity over a non-monotone multi-run window (drift up then
down, score down then up), both by recomputing `compute_delta` over consecutive
snapshots and by telescoping the *recorded* deltas read back through the real
`.maintenance/log.jsonl`; covers the honest-absence edges (a `None`-score endpoint
yields a null trend `score.change` while the count axes still telescope; a `<2`-run
window has no trajectory) and is mutation-checked non-vacuous — the trend-layer
analogue of the per-surface convergence invariants above.

## Library lifecycle

### `scrolls init`

Create the library skeleton (idempotent; an existing `config.toml` is
preserved — `test_init_is_idempotent_and_preserves_config`).

| Key | Meaning |
| --- | --- |
| `root` | library root in use |
| `created` | `false` when the skeleton already existed |

```console
$ scrolls init
{"root": "/tmp/scrolls-demo.BgrqMO/home", "created": true}
[exit 0]
```

### `scrolls status`

Report library state without creating anything
(`test_status_before_init`, `test_status_after_init`).
`schema_version` is `null` until `init` (current version: 6,
`src/scrolls/db.py`). The counts answer "what should run next":
`by_stage.detected` items await `fetch`, `by_stage.fetched` await `md`,
and `unclassified` is the pool a batch `classify` would pick up
(`test_status_counts_items_and_subscriptions`,
`tests/test_items.py`). An uninitialized library reports zero-filled
counts, so the payload shape never varies.

`custody` is the one-line **custody headline** — "how custody stands"
without parsing a full `doctor` report: integrity `score`, the fidelity
`tiers` distribution, the drift posture (`checked`/`unverified`/`unchanged`/
`drifted`/`rotted`/`error`), the stale enrichment/summary counts, the at-risk-works
count (`at_risk`, roadmap H267), the **unresolved import-conflict count**
(`conflicts`, roadmap H279), and the **archive-integrity mismatch count**
(`archive_mismatched`, roadmap H298). It is distilled from the same `run_doctor` custody
view (network-free) via the `custody_snapshot` primitive `scrolls maintain` records,
so `status` can never disagree with `doctor` or a maintenance snapshot
(`test_status_custody_headline_converges_with_doctor`). Before `init` the
`score` is honestly `null` (no store), not a fabricated `100`; an empty but
initialized library is trivially fully custodied (`100`), the "empty is
healthy" posture `doctor` reports.

`conflicts` is the count of currently-held items carrying an **unresolved import
conflict** — a peer's bundle re-imported a held id with a *different* captured
content, surfaced (never silently swallowed) and recorded on the ledger (roadmap
H272–H274, ADR 0104). It is the JSON-`status` counterpart of the readable
`_Conflicts:_` briefing line the `export bundle`/`context` surfaces carry (H277):
`scrolls status` renders no readable conflict line, so it carries the machine scalar
beside `drift`/`at_risk`. Folded from the *same* `unresolved_conflicts` over
`latest_conflict_events` that `doctor`'s `custody.conflicts` reads — a pure read of
the report `run_doctor` already produced — so it converges field-for-field with
`doctor`'s `custody.conflicts.items` by construction
(`test_status_custody_conflicts_surfaces_an_unresolved_import_conflict`). The count
is **resolution-aware**: `scrolls reconcile <id> --keep-held` records a `resolved`
event that supersedes the open conflict, clearing the scalar (the held copy is never
overwritten — raw is sacred, custody §2.4;
`test_status_custody_conflicts_clears_after_reconcile`). Unlike the whole-library-only
`at_risk` alarm, it **scopes by source** for free — a held item owns a source, so
`status --source <S>` narrows the conflict fold exactly as it narrows `drift`
(`test_status_custody_conflicts_source_scopes_like_the_drift_scalar`). An empty or
conflict-free library reports the honest `0`
(`test_status_custody_conflicts_is_zero_on_a_clean_library`).

`archive_mismatched` is the count of archived priors whose advertised `prior_hash`
no longer equals their `snapshot` body's `content_hash` — a corrupt or laundered
**recovery row** (a bad `import archive` or hand-edited `--with-archive` bundle could
land one), the archive-integrity defect `doctor`'s `custody.archive` check folds
(roadmap H293). It is the JSON-`status` counterpart of the readable
`archive_integrity_headline` `maintain` line (H298): `scrolls status` renders no
readable archive line, so it carries the machine scalar beside `conflicts`/`at_risk`,
folded from the *same* `custody.archive.mismatched` the report `run_doctor` already
produced — so it converges with `doctor` and the `maintain` headline by construction
(`test_status_custody_archive_mismatched_surfaces_a_corrupt_prior`). Unlike the
source-attributable `conflicts`, the archive is a single **whole-library** recovery
store, so a `status --source <S>` read leaves it skipped and the scalar reads the
honest `0` even when a tampered prior is present — the whole-library read still
surfaces it (`test_status_custody_archive_mismatched_skipped_under_a_source_scope`).
A clean store reports `0`
(`test_status_custody_archive_mismatched_is_zero_on_a_clean_store`).

`content_duplicate_groups` / `content_duplicate_items` are the count of **groups of
held items sharing a non-null `content_hash` across different ids** and their member
total — byte-identical content held under more than one id (saved from two URLs, a
mirror, a cross-post, or one work captured by two source adapters), the content-identity
redundancy `doctor`'s `custody.content_duplicates` fold reports (roadmap H325). They are
the JSON-`status` counterpart of the readable `duplicates_headline` `maintain` line
(H327): `scrolls status` renders no readable duplicates line, so it carries the machine
scalars beside `archive_mismatched`/`conflicts`/`at_risk`, folded from the *same*
`custody.content_duplicates.total_groups`/`.total_items` the report `run_doctor` already
produced — so they converge with `doctor` and the `maintain` headline by construction.
Like the whole-library-only `at_risk`/`archive_mismatched` (a content group spans
sources), a `status --source <S>` read leaves the block skipped and the scalars read the
honest `0` even when a byte-identical pair is held — the whole-library read still
surfaces it. A library with no byte-identical holdings reports `0`.

`headline` is the one-line custody string rendered from the same snapshot —
`_Custody: N scroll(s) · fidelity <tier counts> · drift <posture counts>._`,
the shared `custody.custody_headline` every scope custody surface emits (the
`maintain` report, the bundle briefing, the `context` bundle, the compiled
`library/` pages). It is rendered from the `custody` block it sits beside
(`maintain.snapshot_headline`), so the rendered line and the structured block
converge by construction and equal `custody_headline` over the held library
(`test_status_carries_rendered_headline_converging_with_the_block`). An empty
or uninitialized library renders the honest `_Custody: 0 scroll(s)._`.

`by_source` is the **per-source custody breakdown** — the `{tiers, drift,
coverage}` tally split per source (`doctor`'s `custody.by_source`, roadmap H104) —
so a reader sees *which* source's custody is weakest (most reference-only, most
drifted, least covered) without running `maintain`/`doctor`. It is a faithful read
(`maintain.report_by_source`) of the **same** `run_doctor` map `status` already
computes for the custody headline above — no new audit, no new ledger read. Source
keys are sorted; the per-source tallies sum to the `custody` block beside them by
construction (every item lands in exactly one source group), so `status`,
`maintain`, `doctor`, and `facets fidelity`/`drift --source <name>` read one number
(`test_status_by_source_breakdown_converges_with_doctor`,
`test_status_by_source_converges_with_maintain_and_doctor`). An empty or
uninitialized library is the honest empty `{}` map (no sources held).

`attention` is the **single weakest source** worth acting on — the
status-surface counterpart of the `maintain` report's `attention` flag (roadmap
H119) — so a human reading `status` sees not just *how much* is held and drifted
but *which source* most needs action. It is distilled (`maintain.weakest_source`)
from the same `by_source` map above: the source with the most **actionable loss**
(the most `drifted` + `rotted` items), tie-broken by the most `reference`-only,
then the source name. The value is `{source, tiers, drift, coverage, reason, command}`
— the flagged source's tally (including its recheck **`coverage`** `{verified, total}`,
how much of the weak source is checked, roadmap H153), a one-line `reason` (e.g.
`"1 drifted"`), and the exact `scrolls verify --source <source>` recheck **`command`**
(H137) — derived from the audit `status` already makes (no new ledger read), so it
equals `maintain`'s `attention` and names `doctor`'s max-loss source by construction
(`test_status_attention_names_the_weakest_source`,
`test_status_attention_converges_with_maintain_and_doctor`). Honest **`null`** on
the same three gates `maintain` uses — an empty library, a **single** source (no
source stands out; the whole-library `custody` block already says everything), or
a **fully-clean** library (no source carries any drifted/rotted loss)
(`test_status_attention_is_null_when_nothing_stands_out`).

`enrichment_by_source` and `summary_by_source` are the **per-source refresh-debt
maps** — flat `{source: stale_count}` maps of the offending sources only, naming
*which* source's `classify --stale` / `kb --stale` to run (roadmap H177). They are
faithful reads (`maintain.report_enrichment_by_source` / `report_summary_by_source`)
of the **same** `run_doctor` audit `status` already makes — `doctor`'s
`custody.enrichment.by_source` (H135) and `custody.summaries.by_source` (H171) — so
the agent's primary read surface names per-source refresh debt at parity with the
scheduled worker's `maintain` report (H147/H175), with **no new audit and no new
ledger read** (`test_status_carries_per_source_refresh_debt_maps`). Source keys are
sorted. The two maps differ in how they total: `enrichment_by_source` sums to the
whole-library `custody.enrichment_stale` (every item has exactly one source), but
`summary_by_source` need **not** — a concept summary spans a cluster whose members
can come from several sources, so a stale summary is attributed to *each* of them
and the values can exceed `summaries_stale` (the H171 double-attribution asymmetry);
the `status`↔`doctor` tie is therefore faithful-read equality, never a sum-to-whole
check (`test_status_refresh_debt_summary_need_not_sum_to_the_whole`). A clean,
empty, or uninitialized library is the honest empty `{}` map on both axes
(`test_status_refresh_debt_maps_are_empty_on_a_clean_library`,
`test_status_refresh_debt_maps_are_empty_before_init`).

Over **MCP** the refresh debt rides the audit twin `get_library_health` (the
custody read an MCP agent makes), but in a **different — richer — shape**, the
H163-style "the MCP twin keeps its natural shape" call (roadmap H180):
`get_library_health` is *exactly* `run_doctor`'s custody block, so it carries the
whole **nested** `custody.enrichment` / `custody.summaries` re-derivability blocks
(`basis`, `current_ruleset`, `classified`/`eligible`, `current`, `stale`, `items`,
**and** `by_source`) — the flat CLI `status` maps are just the `by_source` slice of
those blocks hoisted to top level for the unattended worker. So the refresh debt is
not lost over MCP, only nested: `status.enrichment_by_source ==
get_library_health()["enrichment"]["by_source"]` and `status.summary_by_source ==
get_library_health()["summaries"]["by_source"]` by construction (both read the same
slice off one `run_doctor` audit), pinned scope-wide and source-scoped in
`tests/test_mcp.py`
(`test_get_library_health_refresh_debt_equals_cli_status_flat_maps`,
`test_get_library_health_source_scopes_the_refresh_debt`). The CLI does **not**
flatten and the MCP twin does **not** sprout flat duplicates — each surface keeps the
shape that fits it (the CLI a worker-friendly distillation, MCP the full audit
block).

| Key | Meaning |
| --- | --- |
| `initialized` / `schema_version` | `false`/`null` until `init` |
| `root` | library root in use |
| `items` | `total`, `by_stage` (always all three stages), `by_source` (present sources only), `unclassified` |
| `subscriptions` | followed feeds (`scrolls follow`) |
| `custody` | the custody headline — `score`, `tiers`, `drift` posture, `enrichment_stale`, `summaries_stale`, `at_risk` (the at-risk-works count, H267; `0` under a `--source` scope, which fragments works) (converges with `doctor`) |
| `headline` | the one-line `custody` block rendered (`_Custody: …_`), at parity with the `maintain` report's `headline` |
| `by_source` | the per-source `{tiers, drift, coverage}` custody breakdown (sorted keys; sums to `custody`), the status-surface counterpart of `doctor`'s `custody.by_source` / `maintain`'s `by_source` |
| `attention` | the single weakest source `{source, tiers, drift, coverage, reason, command}` (most drifted/rotted loss; `coverage` = how much of it is checked, H153) or `null` when nothing stands out, the status-surface counterpart of `maintain`'s `attention` |
| `enrichment_by_source` | the per-source stale-classification debt `{source: stale_count}` (offenders only; sums to `enrichment_stale`) — which source's `classify --stale` to run, a faithful read of `doctor`'s `custody.enrichment.by_source`, at parity with `maintain` (H177) |
| `summary_by_source` | the per-source stale-summary debt `{source: stale_count}` (offenders only; need **not** sum to `summaries_stale` — the H171 multi-source attribution) — which source's `kb --stale` to run, at parity with `maintain` (H177) |

`--source <S>` scopes the whole status read to one source's held items (roadmap
H166) — the status-surface counterpart of `doctor --source` (H162) and the
read-side sibling of the per-source act commands (`verify --source` H125, `classify
--stale --source` H154). Every block is then the one-source view: the `items` counts
(narrowed through `library_counts(source=)`), the `custody` headline, the rendered
`headline`, `by_source` (which collapses to the present-and-singleton `{S: …}`), and
the `enrichment_by_source`/`summary_by_source` refresh-debt maps (which collapse to
that source's debt only, equal to a `doctor --source S` audit's own maps — note a
multi-source concept that drops below `MIN_MEMBERS` under the scope is no longer
eligible, so a scoped `summary_by_source` reflects the scoped cluster,
`test_status_source_scopes_the_refresh_debt_maps`).
The whole payload stays internally consistent — the counts and the custody block
agree on scope — and the scoped `custody.tiers`/`drift`/`coverage` equals the
whole-library `by_source[S]` slice and a `doctor --source S` audit's custody block
by construction (`test_status_source_scope_converges_with_the_whole_library_by_source`).
`attention` is `null` under `--source` — the `weakest_source` flag only discriminates
*across* sources, and a single-source scope has nothing to stand out against (the
documented single-source gate). An unknown source holds nothing, so it is the honest
empty headline (`_Custody: 0 scroll(s)._`, `score: 100` over an initialized library),
never an error (`test_status_source_scopes_the_whole_payload_to_one_source`,
`test_status_source_unknown_is_the_honest_empty_headline`).

```console
$ scrolls status        # before init
{"initialized": false, "root": "/tmp/scrolls-demo.BgrqMO/home-empty", "schema_version": null, "items": {"total": 0, "by_stage": {"detected": 0, "fetched": 0, "rendered": 0}, "by_source": {}, "unclassified": 0}, "subscriptions": 0, "custody": {"score": null, "tiers": {"full": 0, "partial": 0, "reference": 0}, "drift": {"checked": 0, "unverified": 0, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "enrichment_stale": 0, "summaries_stale": 0, "at_risk": 0, "conflicts": 0, "archive_mismatched": 0, "content_duplicate_groups": 0, "content_duplicate_items": 0}, "headline": "_Custody: 0 scroll(s)._", "by_source": {}, "attention": null, "enrichment_by_source": {}, "summary_by_source": {}}
[exit 0]

$ scrolls status        # after the imports and adds below
{"initialized": true, "root": "/tmp/scrolls-demo.BgrqMO/home", "schema_version": 6, "items": {"total": 4, "by_stage": {"detected": 2, "fetched": 2, "rendered": 0}, "by_source": {"arxiv": 1, "x": 3}, "unclassified": 3}, "subscriptions": 0, "custody": {"score": 100, "tiers": {"full": 2, "partial": 0, "reference": 2}, "drift": {"checked": 0, "unverified": 4, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "enrichment_stale": 0, "summaries_stale": 0, "at_risk": 0, "conflicts": 0, "archive_mismatched": 0, "content_duplicate_groups": 0, "content_duplicate_items": 0}, "headline": "_Custody: 4 scroll(s) \u00b7 fidelity full 2, reference 2 \u00b7 drift unverified 4._", "by_source": {"arxiv": {"tiers": {"full": 1, "partial": 0, "reference": 0}, "drift": {"verified": 0, "unverified": 1, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 1}}, "x": {"tiers": {"full": 1, "partial": 0, "reference": 2}, "drift": {"verified": 0, "unverified": 3, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 1}}}, "attention": null, "enrichment_by_source": {}, "summary_by_source": {}}
[exit 0]
```

*(x:1111 is already classified here — the Field Theory import's
frontmatter join carries `category` over — which is why `unclassified`
is 3 of 4. `attention` is `null` because nothing has drifted yet — every
item is still `unverified`; once a source carries `drifted`/`rotted` loss
across a multi-source library it populates with that source and its `scrolls
verify --source <S>` recheck command, exactly as the `maintain` report's
`attention` does.)*

### `scrolls paths`

Print every library path (`test_paths_prints_layout_json`). `items` is a
reserved directory, currently unused; `media` holds files downloaded by
`scrolls media`.

```console
$ scrolls paths
{"root": "/tmp/scrolls-demo.BgrqMO/home", "items": "/tmp/scrolls-demo.BgrqMO/home/items", "scrolls": "/tmp/scrolls-demo.BgrqMO/home/scrolls", "library": "/tmp/scrolls-demo.BgrqMO/home/library", "media": "/tmp/scrolls-demo.BgrqMO/home/media", "agents": "/tmp/scrolls-demo.BgrqMO/home/agents", "db": "/tmp/scrolls-demo.BgrqMO/home/db.sqlite", "config": "/tmp/scrolls-demo.BgrqMO/home/config.toml"}
[exit 0]
```

### `scrolls doctor [--fix] [--source S]`

Check integrity between the SQLite index and the file tree, offline
(ADR 0026; all cited tests in `tests/test_doctor.py`). Five checks,
each a top-level key:

| Key | Finding | With `--fix` |
| --- | --- | --- |
| `duplicates` | url-hash items (no source-local id) whose URLs normalize to the same resource — the pre-normalization legacy ADR 0023 left in place | merged (`test_fix_merges_duplicates_into_canonical_id`) |
| `missing_scrolls` | items whose recorded scroll file is gone | rewritten from the index (`test_fix_rewrites_missing_scroll_from_the_index`) |
| `missing_media` | captured media files gone from disk | report-only; `scrolls media` re-downloads (`test_fix_leaves_missing_media_to_scrolls_media`) |
| `orphan_scrolls` | `.md` files under `scrolls/` no item owns | report-only; never deleted (`test_fix_never_deletes_orphan_scrolls`) |
| `fts` | search index out of sync with the items table | rebuilt (`test_fix_rebuilds_drifted_fts`) |

A duplicate merge keeps the most advanced member's content under the id
a clean re-add of the URL would mint (so the duplicate cannot recur —
`test_merged_duplicates_do_not_recur`), keeps the earliest `saved_at`,
fills `category`/`domain` from any member, unions `tags`/`concepts`,
deletes the losing rows and scroll files, and re-renders the survivor's
scroll (`test_fix_merges_classification_across_members`,
`test_fix_deletes_the_losing_duplicates_scroll_file`).

Exit semantics differ from the batch commands: exit 0 only when the
library ends fully consistent — already healthy, or every finding
repaired (`issues == fixed`); any drift left behind exits 1, including
the report-only kinds
(`test_doctor_fix_exits_one_when_unfixable_drift_remains`). Without
`--fix` nothing is mutated (`test_doctor_reports_issues_and_exits_one`),
and doctor never creates a library
(`test_doctor_before_init_exits_zero`). A repair the filesystem refuses
marks its finding `failed` (with `error`) and never aborts the rest; a
failed merge mutates nothing
(`test_fix_reports_a_scroll_it_cannot_rewrite`,
`test_fix_reports_a_merge_it_cannot_complete`).

```console
$ scrolls doctor        # healthy library
{"issues": 0, "fixed": 0, "duplicates": [], "missing_scrolls": [], "missing_media": [], "orphan_scrolls": [], "fts": {"in_sync": true, "status": "ok"}}
[exit 0]

$ scrolls doctor        # a planted pre-ADR-0023 duplicate + a deleted scroll file
{"issues": 2, "fixed": 0, "duplicates": [{"source": "web", "url": "https://blog.example/post", "ids": ["web:5e1a18c8f0f3", "web:af2e70e87b6d"], "status": "found"}], "missing_scrolls": [{"id": "x:1111", "path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md", "status": "found"}], "missing_media": [], "orphan_scrolls": [], "fts": {"in_sync": true, "status": "ok"}}
[exit 1]

$ scrolls doctor --fix
{"issues": 2, "fixed": 2, "duplicates": [{"source": "web", "url": "https://blog.example/post", "ids": ["web:5e1a18c8f0f3", "web:af2e70e87b6d"], "status": "merged", "merged_id": "web:af2e70e87b6d"}], "missing_scrolls": [{"id": "x:1111", "path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md", "status": "rewritten"}], "missing_media": [], "orphan_scrolls": [], "fts": {"in_sync": true, "status": "ok"}}
[exit 0]
```

`fts.status` is `ok`, `found`, `rebuilt`, `unsupported` (SQLite older
than 3.42 cannot verify the index against the table —
`test_fts_check_degrades_on_old_sqlite`), or `skipped` (no database).

Beyond those five repairable checks, every run also carries a `custody`
block — a network-free integrity *report* that never affects the
`issues`/`fixed` counts or the exit code (it records state doctor cannot
repair). It holds the fidelity `tiers` distribution, per-item integrity
`findings` with a percent-clean `score` (ADR 0097; cited tests in
`tests/test_doctor.py`), and a `drift` sub-block aggregating the latest
`scrolls verify` verdict per held item — `checked`, the
`unchanged`/`drifted`/`rotted`/`error` counts, and the actionable
`drifted`/`rotted` `events` themselves (ADR 0098;
`test_drift_report_counts_each_verdict`).

The custody block also carries a `by_source` map (roadmap H104) — the same
fidelity-tier / drift-posture aggregate split *per source*, so the audit names
*which* source's custody is weakest (most reference-only, most drifted) and an
operator knows where to target a [`verify --source`](#scrolls-verify-id) (the
act-side that re-verifies exactly that source, roadmap H125),
[`verify --drift`](#scrolls-verify-id) / [`media`](#scrolls-media) / recapture
instead of enumerating per source by hand.
Each entry is the `{tiers, drift}` shape the whole-library block uses (posture
words — `verified` ≡ the ledger's `unchanged`) **plus** a per-source `coverage`
`{verified, total}` (roadmap H121) — the per-source counterpart of the drift
block's whole-library `coverage`: of that source's *verifiable* (hash-bearing)
held items, how many carry a verdict. So the audit names not just which source
has the most drift but which is least *covered* (most never-checked); a
reference-only capture has no baseline hash, so it is excluded from a source's
denominator (coverage can reach full, never stuck below 100% on the
unverifiable). Entries are keyed by source name in sorted order; an empty library
is the honest empty map. Built from the *same* `custody.custody_counts` /
`custody.recheck_coverage` grouped by source, so the per-source tiers/drift
tallies sum to the whole-library `custody` block and the per-source coverage sums
to `drift.coverage` by construction (the convergence pinned in
`tests/test_custody_convergence.py`,
`test_doctor_by_source_converges_with_the_per_source_tally_and_facets`, where each
per-source tally also equals `facets fidelity`/`drift --source <name>`).
Report-only like the rest of the block — a weak per-source custody picture is a
view, never an `issue` or the exit code
(`test_custody_by_source_never_feeds_issues_or_the_exit_code` in
`tests/test_doctor.py`).

The custody block also carries a `works` sub-block (roadmap H263) — the
**at-risk-works** consolidation alarm, the work-level counterpart of the
weakest-source `attention` flag. Where that names the source carrying the most
per-*item* drift, this names the [**works**](#scrolls-works-ref---min-n---fidelity-t---drift-p)
carrying a *consolidation* loss: a work (the cluster of representations of one
scholarly work — a preprint, its published record, an index entry, ADR 0069) is
**at risk** when **no** representation is *safely held* (the per-work
`safely_held == false` of the H261 aggregate — every copy degraded
(`partial`/`reference`) or moved (`drifted`/`rotted`/`error`), no unmoved full form
anywhere). That is a sharper alarm than the per-item drift count: an item drifting
is survivable when a sibling representation of the *same* work is still
`full`+verified; a work with no safe representation is a real custody loss. The
block holds `{status, total, at_risk, most_at_risk}` — `total` the
multi-representation works audited, `at_risk` how many are not safely held, and
`most_at_risk` the single lowest-custody-ceiling one (`null` when none) so an
operator acts on *one* named work without scanning the set: worst `best_fidelity`
first (a work holding no full content — `reference` best — is more at risk than one
holding a `full`-but-`drifted` copy: the content is gone vs. merely moved), then
worst `safest_drift`, then `doi`. Its entry carries the work's
`doi`/`url`/`canonical`, `representations` count, the H261 `custody` verdict, and a
self-describing `reason` — but **no `command`** (unlike `attention`'s
`verify --source` recheck, there is no whole-library "recapture this work" act to
name; inventing one is what `maintain`'s `suggested` block refuses for orphans).
Report-only and a pure fold over the H261 aggregate (no schema change, no extra
ledger read); `maintain` surfaces the same block as `at_risk_works`
(`test_custody_works_flags_the_at_risk_works`,
`test_custody_works_names_the_lowest_ceiling_work_as_most_at_risk`,
`test_custody_works_never_feeds_issues_or_the_exit_code` in `tests/test_doctor.py`).
The live `at_risk_works` block rides the maintain pass only, but its **count**
(`at_risk`) is also recorded as the scalar `at_risk` in each `custody_snapshot`
(roadmap H267), so `maintain --history`/`--trend` carry the *consolidation-loss-over-
time* axis (`at_risk_change`, above) and `status`'s `custody.at_risk` reads it for the
current pass — the at-risk counterpart of recording recheck `coverage` in the snapshot.

The custody block also carries a `conflicts` sub-block (roadmap H275, ADR 0104) —
the scope-level **import-conflict aggregate**, the *read-aggregate sibling of
`drift`* over the other provenance-of-divergence axis. Where `drift` folds the
latest `scrolls verify` verdict per held item ("has the live source moved?"), this
folds the latest recorded import-`conflict` event per held item ("did a peer's
capture of this id disagree with mine when I merged a bundle?", recorded by
[`import items`](#scrolls-import-bundlefile) / `import bundle`, readable per-item via
[`history --status conflict`](#scrolls-history-id)). It holds `{basis, as_of, items,
events}`: `basis` is `import_ledger` (read from the recorded events, not live this
run), `items` the count of currently-held items carrying an **unresolved** conflict,
`as_of` the freshest unresolved conflict's timestamp (`null` when none), and `events`
the latest unresolved conflict per affected item (`id`/`status`/`checked_at`/
`prior_hash` (the held copy) / `observed_hash` (the incoming capture that disagreed)).
A conflict is **unresolved** while that latest event's `observed_hash` still differs
from the held copy's current `content_hash` — the held copy is never auto-overwritten
(raw is sacred), so every recorded conflict is unresolved today, but the predicate is
resolution-aware so a future `reconcile` (H276) that adopts the incoming content clears
it with no special "resolved" event (the `latest_events` held-filter precedent). The two
axes never mix — a conflict never inflates `drift` and a drift verdict never appears here
(`latest_conflict_events` reads only the `conflict` rows, `latest_events` only the verify
verdicts). Held-filtered like `drift` (a conflict on a since-deleted id is dropped) and,
unlike `custody.works`, **source-attributable** — so `--source S` scopes it for free (a
held item owns a source). Report-only, never `issues`/`fixed`/the exit code
(`test_doctor_custody_conflicts_surfaces_an_unresolved_import_conflict` and the
clean/held-filter/source-scope siblings in `tests/test_cli.py`); the MCP
[`get_library_health`](#mcp-tools) twin carries it for free, converging field-for-field
with this block.

The custody block also carries a `content_duplicates` sub-block (roadmap H325) —
the **content-identity redundancy report**, the byte-identity sibling of the
URL-spelling `duplicates` list and of canonical DOI `works`. A custody library can
hold **byte-identical content under different ids** — the same bytes saved from two
URLs, a mirror, a cross-post, or one work captured by two source adapters — a
genuinely new custody *shape* (vision §2.7), neither a spelling accident
(`duplicates`, ADR 0023) nor a scholarly cluster (`works`). It holds
`{status, groups, total_groups, total_items}`: the held items are grouped by their
non-null `content_hash` and every group of **≥2 distinct ids** is flagged as
`{content_hash, ids}` (groups ordered by hash, ids sorted within — a stable diff
line), with `total_items` the member count across all groups. A NULL/empty hash
fingerprints nothing (a reference-only item holds no captured content), so it is
skipped — two reference items are not byte-identical holdings. **Report-only and
never auto-merged**: unlike the URL-spelling `duplicates` (which `--fix` merges into
the canonical id), holding two faithful copies is a redundancy fact an operator may
want — content-identity across ids is custody-distinct provenance (raw is sacred,
custody §2.4) — so it never feeds `issues`/`fixed`/the exit code and names no repair
command (the dedup half of "evidence clustering", surfaced not silently collapsed).
A pure fold over `content_hash` (no schema change, no ledger read); the MCP
[`get_library_health`](#mcp-tools) twin carries it for free, converging field-for-field
with this block
(`test_content_duplicates_flags_a_two_id_group_sharing_a_content_hash`,
`test_content_duplicates_never_feeds_issues_or_the_exit_code`,
`test_content_duplicates_groups_across_sources` in `tests/test_doctor.py`).

`--source S` scopes the **whole** audit to one source's held items (roadmap H162)
— the audit-side counterpart of the per-source act commands
[`verify --source`](#scrolls-verify-id) (H125) and
[`classify --stale --source`](#scrolls-classify-id) (H154). Once `by_source` (or
[`status`](#scrolls-status)'s weakest-source `attention` flag) names the weakest
source, `--source` reads *that source's full custody report* — `score`, `tiers`,
`drift`, `coverage`, `enrichment`, and the offending-id lists (`drift.events`,
`enrichment.items`, `missing_scrolls`) — instead of slicing them out of the
whole-library report by hand. Scoping filters the *input* item set, so every
block is genuinely one-source and `by_source` collapses to the present-and-
singleton `{S: …}`. The convergence this guarantees, pinned in
`tests/test_custody_convergence.py`
(`test_doctor_source_scope_converges_with_the_whole_library_by_source`): a
`--source S` audit's `tiers`/`drift`/`coverage` equals the whole-library audit's
`by_source[S]` slice and its `enrichment.stale` equals `enrichment.by_source[S]`
(same held subset, same tally). Five checks are **not** source-attributable and so
are skipped under `--source`: `orphan_scrolls` (an unowned `.md` file belongs to
no source — and scoping the item set must not flag *other* sources' owned scrolls
as orphans), `fts` (a single library-wide index), the `custody.works`
at-risk-works alarm (a work spans sources, so a scoped item set fragments works —
a 2-representation work split arxiv+crossref drops below the floor and vanishes,
making "no work is at risk" a falsehood the scope produced), the `custody.archive`
integrity check (a single whole-library recovery store, not a per-source view), and
the `custody.content_duplicates` redundancy report (a content group likewise spans
sources — a web save + an arxiv mirror of the same bytes — so scoping fragments
groups below the 2-id floor, making "0 groups" the same scope-produced falsehood).
All five report their empty/`skipped` defaults (the works/archive/content blocks
keep `status: "skipped"`, never a fabricated "0 at risk"/"0 groups") and are left to
a whole-library `scrolls doctor`
(`test_doctor_source_skips_the_at_risk_works_alarm`,
`test_content_duplicates_skipped_under_a_source_scope` in `tests/test_doctor.py`). The
exit-code rule is unchanged — structural `issues > fixed` fails — now over only
that source's attributable findings; an unknown source holds nothing, so it is the
honest empty audit (`score: 100`, empty `by_source`, exit 0), never an error
(`test_doctor_unknown_source_is_the_honest_empty_audit`,
`test_doctor_source_reports_only_that_sources_missing_scrolls` in
`tests/test_doctor.py`).

The drift block states *what it verified* (completeness contract G2): doctor
is network-free, so its verdicts are read from the ledger, not confirmed live
this run. `basis` names that source (`last_verify` — as-of-the-last-`scrolls
verify`, not "verified now"), `as_of` is the freshest verdict timestamp the
picture rests on (`null` when nothing is verified), and `unverified` counts
held items the ledger has no verdict for — never re-checked, so unknown,
**not** clean (`test_drift_names_held_items_never_verified_as_unverified`). A
reader holding only the report can therefore tell "confirmed unchanged at the
last verify" from "never checked", and never read an unverified item as a
healthy one.

The drift block also reports verdict `coverage` as a *fraction* its raw counts
leave implicit (roadmap H113): `{verified, total}` over the held items that
*can* carry a verdict — `total` is the hash-bearing set (a reference-only
capture has no baseline hash to diff a re-fetch against, so it is unverifiable
and excluded from the denominator; coverage measures progress over what can
actually be covered and so can reach full), `verified` how many of those now do.
It is the same `custody.recheck_coverage` figure
[`scrolls maintain`](#scrolls-maintain) reports on its recheck (roadmap H109),
here with no recheck (doctor only reads the ledger) — so `scrolls doctor` shows
"N of M verifiable items carry a verdict" at parity with maintain.
`coverage.verified` equals the block's own `checked` count by construction
(every verdict-bearing held item is hash-bearing, since `verify` never runs on a
reference-only item), pinned in `tests/test_doctor.py`
(`test_drift_coverage_verified_equals_the_checked_count`) and across the two
surfaces in `tests/test_custody_convergence.py`
(`test_recheck_coverage_converges_across_doctor_and_maintain`).

The custody block also carries an `enrichment` sub-block — the re-derivability
counterpart of drift, over the rules engine's classifications (cap 8). Each
rules-classified item records the ruleset fingerprint that produced its
category (`classified_ruleset`, roadmap H20); this block aggregates them
against the live `current_ruleset`: `classified` (the rules-classified items
held — LLM classifications are a different axis and out of scope), `current`
(classified under the live ruleset), `stale` (classified under a *superseded*
one, with the offending ids + fingerprints listed in `items` so a re-classify
can be targeted), and `unfingerprinted` (classified before H20, so no
fingerprint — unknown, **not** silently current, the same honesty as drift's
`unverified`). It is honest, not alarmist: a stale fingerprint means the
ruleset changed since, not that the category is wrong, so — like drift — it
never feeds `issues`/the exit code, and doctor never auto-reclassifies (a
regenerated view is produced on request, never a silent overwrite;
`test_stale_ruleset_does_not_affect_issues_or_exit_code`). To act on the
signal, run [`scrolls classify --stale`](#scrolls-classify-id), the explicit
refresh that re-runs the rules engine over exactly the items reported here.
This aggregate is the rollup of the per-item `classification.confidence.freshness`
marker each browse surface carries (roadmap H21) — both derive from the one
`classify.classification_freshness` primitive, so `current`/`stale`/
`unfingerprinted` here equal the freshness an agent reads on the items themselves
(`test_per_item_confidence_marker_converges_with_the_doctor_aggregate`).

The `enrichment` block also carries a `by_source` map (roadmap H135) — the stale
count split per source, the re-derivability counterpart of the per-source
*coverage* `custody.by_source` carries (H121) — so the audit names *which* source
has the most categories to refresh, then act on just that one with
[`classify --stale --source <S>`](#scrolls-classify-id) (roadmap H154, the
enrichment-axis counterpart of `verify --source`): the count it refreshes equals
`by_source[<S>]` and the refresh clears that source's entry from this map. A flat
`{source: stale_count}` map of the **offending sources only** (a source with no
stale debt is omitted, the `items`-list posture), source keys sorted; every stale
item has exactly one source, so the per-source counts sum to `stale` by
construction (the H104/H121 sum-to-whole posture, on the enrichment axis —
`test_enrichment_by_source_sums_to_the_whole_enrichment_stale`,
`test_enrichment_by_source_converges_with_the_per_source_stale_classifications`).
It lives under `enrichment` (not folded into `custody.by_source`) so the shared
`custody_counts_by_source` — and the `maintain` report that faithfully reads it
(H123/H127) — stay byte-identical, and the verify-ledger module stays free of
classification coupling. The **summary axis carries its own per-source map**
(roadmap H171, documented with the `summaries` block below) — but, because a
concept summary spans a multi-source cluster, that map is attributed differently
and deliberately does **not** sum to the whole the way the enrichment/drift maps
do.

The custody block also carries a `summaries` sub-block — the same re-derivability
posture on the *LLM concept-summary* axis (cap 8, roadmap H29). Each stored
concept summary records the `members_hash` fingerprint of the scrolls it was
synthesized from (`kb_llm.members_hash`); this block aggregates the
summary-eligible concepts (≥ 2 rendered members, the `kb --engine llm`
denominator) against their live members: `eligible` (concepts that qualify for a
summary), `summarized` (those with a stored summary = `current` + `stale`),
`current` (the stored fingerprint matches the live members — a re-synthesis is a
no-op), `stale` (the members changed since synthesis, or a superseded engine
wrote it — the slug, stored `members_hash`, and `live_hash` are listed in `items`
so a re-synthesis can be targeted), and `never` (eligible but never summarized —
unknown, **not** silently current, drift's `unverified` honesty on the summary
axis). Like enrichment, it is report-only: a stale summary means the membership
moved, not that the synthesis is wrong, so it never feeds `issues`/the exit code,
and doctor never auto-regenerates (`test_stale_summary_does_not_affect_issues_or_exit_code`).
The buckets and the per-concept `summary_provenance` view share one
`kb_llm.summary_freshness` derivation, so the count here equals the freshness a
reader builds per concept (`test_summaries_aggregate_converges_with_the_per_concept_view`).
To act on the signal, run [`scrolls kb --stale`](#scrolls-kb---engine----stale),
the explicit refresh that re-synthesizes exactly the concepts reported here — the
summary-axis counterpart of `classify --stale`
(`test_kb_stale_clears_the_doctor_stale_signal`).

The `summaries` block also carries a `by_source` map (roadmap H171) — the
summary-axis counterpart of `enrichment.by_source` — so a worker triaging "source
`<S>`'s summaries are stale" sees which source's items drove a cluster stale
without scanning `items`. **It differs from the enrichment/drift maps in one
load-bearing way.** A concept summary spans a *cluster* whose members can come
from several sources, and the stored fingerprint records only the members digest,
not which member moved — so a stale summary is attributed to **every source among
its live members** (a summary is "stale for source S" if S participates in the
concept). That is exactly the offenders set [`kb --stale --source <S>`](#scrolls-kb---engine----stale)
(roadmap H172) re-synthesizes, since `kb --stale` operates on concepts, not
members — refreshing one source clears its entry here while leaving the rest. The
consequence: one multi-source stale concept counts toward more than
one source, so `by_source` **need not sum to `stale`**
(`sum(by_source.values()) >= stale`, equality iff every stale concept is
single-source) — unlike the enrichment/drift maps, where each item has exactly one
source. A flat `{source: stale_count}` map of the **offending sources only** (a
clean source omitted), keys sorted; pinned in
`test_summaries_by_source_attributes_a_multi_source_stale_concept_to_each_source`
and `test_summaries_by_source_converges_with_the_per_source_stale_summaries`.

### `scrolls verify [id] [--all | --unverified | --stale-before ISO | --drift POSTURE | --source S | --fidelity T] [--limit N]`

Re-capture held items and record whether the live source still matches the
copy in custody (ADR 0098; cited tests in `tests/test_verify_cli.py` and
`tests/test_custody.py`). Verifying re-fetches an item through the same
adapter `scrolls fetch` uses, recomputes its content hash, diffs it against
the stored one, and appends a **custody event** to the ledger — it never
overwrites the original capture, so proving a source changed can never lose
what was held.

Exactly one *selection* is required — a single item `id`/URL, `--all`,
`--unverified`, `--stale-before`, `--drift`, `--source`, or `--fidelity` — never
more than one
(`test_verify_needs_an_id_or_all`, `test_verify_rejects_id_and_all_together`,
`test_verify_rejects_all_and_unverified_together`,
`test_verify_rejects_all_and_stale_before_together`,
`test_verify_rejects_all_and_drift_together`,
`test_verify_rejects_all_and_source_together`,
`test_verify_rejects_source_and_drift_together`,
`test_verify_rejects_all_and_fidelity_together`,
`test_verify_rejects_source_and_fidelity_together`,
`test_verify_rejects_id_and_fidelity_together`). `--all` re-checks every
held item carrying a captured `content_hash` to diff against — a reference-only
or still-`detected` item has no baseline and is skipped. `--unverified` narrows
that to only the hash-bearing items the ledger has *no* verdict for — the same
`held − verdicts` set `doctor`'s `custody.drift.unverified`, `facets drift`, and
the scope custody headlines report, so re-checking clears exactly the
`unverified` bucket those surfaces flag (the report→refresh pairing
`classify --stale` and `kb --stale` have on the enrichment axes, on the verify
axis; `test_verify_unverified_checks_only_never_verified_items`,
`test_verify_unverified_clears_the_doctor_signal`). A reference-only capture has
nothing to diff a re-fetch against, so it honestly *stays* unverified
(`test_verify_unverified_skips_reference_only_items`).

`--stale-before <ISO>` is the **staleness-bounded** recheck — the act-side
sibling of `history --since` and `export events --since`, completing the
`--since` family across the read, the backup, and the recheck. It re-checks only
the hash-bearing items whose newest ledger verdict *predates* the boundary, plus
the never-checked (trivially stale at any boundary) — "re-verify everything not
seen since the last sweep". The boundary itself is *fresh*: an item last checked
exactly at it is not stale (the exact complement of the `checked_at >= boundary`
window the two reads keep; `test_verify_stale_before_selects_only_stale_and_never_checked`,
`test_verify_stale_before_treats_an_at_boundary_check_as_fresh`). Because a
never-checked item is always in, a far-future boundary subsumes `--unverified`
(`test_verify_stale_before_future_boundary_subsumes_unverified`). The boundary
normalizes through the shared `parse_since` (so a `Z` suffix, a different offset,
or a date-only `2026-06-15` all work; `test_verify_stale_before_accepts_a_date_only_boundary`),
and a malformed boundary is a loud usage error (exit 2, the `export events`
precedent), never a silently-empty recheck
(`test_verify_stale_before_malformed_boundary_is_a_loud_usage_error`).

`--drift <posture>` is the **posture-targeted** recheck — the act-side
counterpart of `scrolls list --drift` (the read enumeration) and the verify-axis
sibling of `--unverified`. It re-checks only the hash-bearing items currently at
a chosen drift posture (`verified`/`unverified`/`drifted`/`rotted`/`error`), so a
worker targets the *suspect* set instead of the whole library — `--drift drifted`
to re-confirm whether a changed source moved again or settled, `--drift error` to
retry a transient failure, `--drift rotted` to confirm a 404 is permanent. The
set it re-checks is exactly the rows `list --drift X` enumerates and `facets
drift` counts for the same scope (the shared `custody.items_in_posture` selector;
`test_verify_drift_rechecks_exactly_the_list_drift_rows`), so a recheck moves the
posture it targeted (`test_verify_drift_recheck_moves_the_posture`). It is a
closed vocabulary (argparse `choices` — a typo is exit 2, never a silent empty;
`test_verify_drift_rejects_an_unknown_posture`) and, like the other batch modes,
skips reference-only items with no baseline
(`test_verify_drift_skips_reference_only_items`).

`--source <S>` is the **per-source** recheck — the act-side of `doctor`'s
`custody.by_source` / `maintain`'s `attention` per-source breakdown (which name
*which* source's custody is weakest, most drifted, least covered), and the
verify-axis sibling of `scrolls list --source`. It re-checks only the
hash-bearing items from one source, so a worker re-verifies exactly the weakest
source without `--all` re-checking the whole library. The set it re-checks is
exactly `list --source S`'s held, hash-bearing rows (the shared item-intrinsic
`source` filter — orthogonal to the ledger-driven selections, no ledger read;
`test_verify_source_rechecks_exactly_the_list_source_hash_bearing_rows`,
`test_verify_source_rechecks_exactly_what_list_source_enumerates`), so
re-verifying a source clears exactly that source's `unverified` count in
`doctor`'s `custody.by_source[S]`
(`test_verify_source_clears_that_sources_unverified_bucket`). Unlike `--drift`,
`--source` is an **open** vocabulary (sources are open-ended), so a source
nothing is held for is an honest empty no-op, never an error
(`test_verify_source_unknown_source_is_an_empty_noop`); like the other batch
modes it skips reference-only items with no baseline
(`test_verify_source_skips_reference_only_items`).

`--fidelity <tier>` is the **holdings-axis** recheck — the act-axis twin of
`scrolls list --fidelity` / `search --fidelity` (the read enumeration / ranked
filter on the same axis), so a worker re-verifies exactly its full-fidelity (or
`partial`) holdings without `--all`. It folds the same `get_fidelity` primitive
those read surfaces count with — a pure function of stored content columns, **no
ledger read** (the honest holdings-fact axis, vs `--drift`'s ledger-claim axis).
Like every batch mode it re-checks only hash-bearing rows, so the set it touches
is `list --fidelity <tier>`'s held, *hash-bearing* subset — and that makes it
genuinely narrower than the listing: a `full` capture held by `raw_text` alone
carries no `content_hash`, so it lists `full` yet has no baseline to diff and is
skipped (`test_verify_fidelity_full_skips_a_full_item_without_a_baseline_hash`,
`test_verify_fidelity_rechecks_exactly_the_list_fidelity_hash_bearing_rows`). A
tier holding no fingerprint at all — typically `reference`, which keeps no content
— is therefore an honest empty no-op
(`test_verify_fidelity_reference_is_an_empty_noop`). It is a **closed** vocabulary
(argparse `choices` over `full`/`partial`/`reference` — a typo is exit 2, never a
silent empty; `test_verify_fidelity_rejects_an_unknown_tier`).

`--limit N` paces a large
`--all`/`--unverified`/`--stale-before`/`--drift`/`--source`/`--fidelity`
run (oldest saved first), like `scrolls fetch` — so a bounded pass makes monotone
coverage progress. A single `id` must itself hold a content hash
(`test_verify_item_without_content_hash_is_an_error`).

Each result carries a `status`:

| `status` | Meaning |
| --- | --- |
| `unchanged` | the re-captured hash equals the stored one — the source still matches custody |
| `drifted` | the hashes differ — the source changed since capture (the original is still held) |
| `rotted` | the resource is gone (HTTP 404/410) — custody may hold the last copy |
| `error` | the re-capture failed for another reason (transient network, no adapter) — not a verdict, just "could not check" |

`scrolls doctor` aggregates the latest event per item into its
`custody.drift` block (`test_verify_feeds_the_doctor_drift_report`). Exit
is 0 when every item was checked — `drifted` and `rotted` are *successful*
checks that recorded a real custody event — and 1 when any `error` left an
item unchecked, mirroring `scrolls fetch`
(`test_verify_transient_failure_is_error_and_exits_nonzero`).

```console
$ scrolls verify web:af2e70e87b6d        # source rewritten since capture
{"checked": 1, "unchanged": 0, "drifted": 1, "rotted": 0, "error": 0, "results": [{"id": "web:af2e70e87b6d", "status": "drifted", "prior_hash": "sha256:1f3c…", "observed_hash": "sha256:9c20…", "detail": null}]}
[exit 0]

$ scrolls verify --all
{"checked": 2, "unchanged": 1, "drifted": 0, "rotted": 1, "error": 0, "results": [{"id": "web:af2e70e87b6d", "status": "unchanged", "prior_hash": "sha256:9c20…", "observed_hash": "sha256:9c20…", "detail": null}, {"id": "x:1111", "status": "rotted", "prior_hash": "sha256:77ab…", "observed_hash": null, "detail": "web request failed: HTTP Error 404: Not Found"}]}
[exit 0]

$ scrolls verify --unverified      # only the held items doctor flags `unverified`
{"checked": 1, "unchanged": 1, "drifted": 0, "rotted": 0, "error": 0, "results": [{"id": "x:2222", "status": "unchanged", "prior_hash": "sha256:5e1a…", "observed_hash": "sha256:5e1a…", "detail": null}]}
[exit 0]

$ scrolls verify --stale-before 2026-06-15   # only items not re-checked since the last sweep
{"checked": 1, "unchanged": 1, "drifted": 0, "rotted": 0, "error": 0, "results": [{"id": "web:af2e70e87b6d", "status": "unchanged", "prior_hash": "sha256:9c20…", "observed_hash": "sha256:9c20…", "detail": null}]}
[exit 0]

$ scrolls verify --drift drifted      # re-check only the items flagged drifted — did the source settle?
{"checked": 1, "unchanged": 1, "drifted": 0, "rotted": 0, "error": 0, "results": [{"id": "web:af2e70e87b6d", "status": "unchanged", "prior_hash": "sha256:9c20…", "observed_hash": "sha256:9c20…", "detail": null}]}
[exit 0]

$ scrolls verify --source arxiv      # re-check only the weakest source doctor/maintain flagged
{"checked": 2, "unchanged": 2, "drifted": 0, "rotted": 0, "error": 0, "results": [{"id": "arxiv:2401.00001", "status": "unchanged", "prior_hash": "sha256:7c4d…", "observed_hash": "sha256:7c4d…", "detail": null}, {"id": "arxiv:2402.00002", "status": "unchanged", "prior_hash": "sha256:b81e…", "observed_hash": "sha256:b81e…", "detail": null}]}
[exit 0]

$ scrolls verify --fidelity full      # re-check only the full-fidelity holdings you can re-derive offline
{"checked": 2, "unchanged": 2, "drifted": 0, "rotted": 0, "error": 0, "results": [{"id": "arxiv:2401.00001", "status": "unchanged", "prior_hash": "sha256:7c4d…", "observed_hash": "sha256:7c4d…", "detail": null}, {"id": "web:af2e70e87b6d", "status": "unchanged", "prior_hash": "sha256:9c20…", "observed_hash": "sha256:9c20…", "detail": null}]}
[exit 0]
```

### `scrolls history <id> [--limit N] [--since ISO] [--status V]`

Print one item's **custody-ledger timeline**, newest first (cited tests in
`tests/test_verify_cli.py`). Where `scrolls verify` *appends* a custody event per
check and `show`/`list` carry only the *latest* `drift` posture (and
`doctor`/`facets` only aggregate counts), `history` reads back the complete
append-only ledger for one item — each `{checked_at, status, prior_hash,
observed_hash, detail}` — so an agent can see *when* a source drifted and *how
often* it has been re-checked. It is the per-item counterpart of `maintain
--history`'s scope-level trajectory, and the browsable form of the events
`verify` writes.

`<id>` is the item's id or, equivalently, the URL that saved it (ADR 0028),
resolved like `show`'s. The output is a JSON array; the event fields mirror
`verify`'s `results` rows minus the redundant per-row `id` (every event is the
same item). `--limit N` bounds a long ledger to the most recent N checks
(newest first, oldest dropped) — a worker that runs `scrolls maintain` on a
schedule appends a verdict per pass, so a long-lived item accumulates history;
the whole timeline is the default, and the slice mirrors `list --limit` so
`--limit 0` is the honest empty `[]` and an over-count returns all
(`test_history_limit_returns_the_most_recent_n`).

`--since <ISO>` is the **time-axis** sibling of `--limit`'s count cap: it
returns only the checks `checked_at >= <ISO>`, so a maintenance worker can ask
"what has this source done *since the last sweep*" without reading (or capping
by count) the whole ledger. The boundary is normalized through the one
`published_at`/`checked_at` vocabulary (ADR 0024), so a `Z` suffix, a different
offset, or a date-only `2026-06-15` (that day's midnight UTC) all compare
correctly against the stored `+00:00` stamps; the boundary is **inclusive** and
the two flags compose **window then cap** (`--since` cuts the time range, then
`--limit` caps the count of what remains —
`test_history_since_composes_with_limit_window_then_cap`). An empty window is
the honest `[]` (checked-and-empty, exit 0); a **malformed** `--since` is a loud
usage error on stderr, exit 2 — validated *before* the item lookup, so a typo'd
boundary on an unknown item is a usage error, not a missing-item one
(`test_history_malformed_since_beats_an_unknown_id`).

`--status <verdict>` is the **verdict axis** — return only the events whose
`status` is one of the closed set `unchanged`/`drifted`/`rotted`/`error` *plus*
the two conflict-axis events: the import-time `conflict` and its operator
`resolved` supersession (the raw event status `history` emits, *not* the
reader-facing drift posture — so it is `unchanged`, not `verified`). "Show me
only the times this source actually *changed*" — an agent triaging a long ledger
reads the drift/rot events without scanning the steady-state re-checks
(`test_history_status_filters_to_one_verdict`) — or "show me only the import
**conflicts**", the times another capture of this id disagreed with the held copy
at merge time (roadmap H274, recorded by both lossless importers — see *import
items*/*import bundle* below — readable here via `--status conflict`,
`test_import_items_records_a_conflict_as_a_custody_event`), or "show me the times
I **resolved** one" (`--status resolved`, the `reconcile --keep-held` decision —
see *reconcile* below, H276). Both are a *distinct* axis from drift, never a drift
posture: they ride the ledger and this timeline but `doctor`'s `custody.drift` /
`list --drift` ignore them (a peer disagreeing — or an operator affirming the held
copy — is no evidence the live source moved). `--status` is a closed vocabulary guarded by
argparse `choices` (an unknown verdict is a usage error, exit 2, never a silent
empty — `test_history_status_is_a_closed_vocabulary`), and composes with the
other two axes **verdict → window → cap**: filter the verdict, then `--since` the
time, then `--limit` the count
(`test_history_status_composes_with_since_and_limit`). A verdict nothing matches
is the honest `[]`.

Read-only and honest about absence (the completeness contract): a
held item the ledger has *never* checked is the empty `[]` — checked-and-empty,
exit 0 (`test_history_of_a_never_verified_item_is_empty`) — while an *unknown*
ref is a loud could-not-check error on stderr, exit 1
(`test_history_unknown_id_errors_loudly`), the same empty-vs-error split
`show`/`related` draw, so a typo can never masquerade as "no history".

```console
$ scrolls history web:af2e70e87b6d        # re-checked twice; drifted, then held
[{"checked_at": "2026-06-16T09:00:00+00:00", "status": "unchanged", "prior_hash": "sha256:9c20…", "observed_hash": "sha256:9c20…", "detail": null}, {"checked_at": "2026-06-14T09:00:00+00:00", "status": "drifted", "prior_hash": "sha256:1f3c…", "observed_hash": "sha256:9c20…", "detail": null}]
[exit 0]

$ scrolls history web:never-verified      # held, but never re-checked
[]
[exit 0]

$ scrolls history web:af2e70e87b6d --limit 1   # just the latest check
[{"checked_at": "2026-06-16T09:00:00+00:00", "status": "unchanged", "prior_hash": "sha256:9c20…", "observed_hash": "sha256:9c20…", "detail": null}]
[exit 0]

$ scrolls history web:af2e70e87b6d --since 2026-06-15   # only checks since the last sweep
[{"checked_at": "2026-06-16T09:00:00+00:00", "status": "unchanged", "prior_hash": "sha256:9c20…", "observed_hash": "sha256:9c20…", "detail": null}]
[exit 0]

$ scrolls history web:af2e70e87b6d --status drifted   # only the times the source actually changed
[{"checked_at": "2026-06-14T09:00:00+00:00", "status": "drifted", "prior_hash": "sha256:1f3c…", "observed_hash": "sha256:9c20…", "detail": null}]
[exit 0]

$ scrolls history web:af2e70e87b6d --status conflict   # only the times a re-import disagreed with the held copy
[{"checked_at": "2026-06-20T11:00:00+00:00", "status": "conflict", "prior_hash": "sha256:9c20…", "observed_hash": "sha256:7b41…", "detail": "import conflict: an incoming capture of this id differs from the held copy"}]
[exit 0]
```

### `scrolls reconcile <id> --keep-held [--dry-run]`

The **operator act** on a recorded import conflict — the resolution leg of the
conflict-on-import theme (detection: *import items*/*import bundle* below and
`scrolls history --status conflict`; scope read: `doctor`'s `custody.conflicts`
and the `_Conflicts:_` briefing line; ADR 0104/0105, cited tests in
`tests/test_cli.py`). When two captures of the same id collide on import the held
copy is kept and the divergence is *surfaced and recorded* but never resolved —
so `doctor`/the `_Conflicts:_` line flag it indefinitely. `reconcile` is the
explicit, operator-driven way to close it.

`--keep-held` **affirms the held copy** as authoritative. It records a `resolved`
conflict-axis custody event that *supersedes* the open conflict, so the divergence
clears from `doctor`'s `custody.conflicts`, the `_Conflicts:_` line, and the MCP
`get_library_health` twin (all fold the one shared `unresolved_conflicts`
predicate). Two custody guarantees hold by construction: the **held copy is never
overwritten** (raw is sacred, custody §2.4 — its content and `content_hash` are
provably untouched), and the **original `conflict` event survives** on the
timeline (append-only — `history --status conflict` still shows *when* a peer
disagreed; the resolution is a new `resolved` row, readable via `history --status
resolved`). It is **CLI-only** — a custody-changing write is an explicit operator
act, not an ambient MCP capability — like `verify`.

`--keep-held` is **required**: a bare `reconcile <id>` is a loud usage error (exit
2, nothing written) because the resolution is a decision, not a default. (The
sibling resolution — *adopt* the peer's capture — is the **import-path**
`import items`/`import bundle --accept-incoming` below, not a `reconcile` flag: at
`reconcile` time the incoming content is gone, only its hash was recorded, so
adopting it must re-supply the content at merge time, ADR 0105/0106.)

The command is **idempotent** and **dry-run-able**. A second `reconcile
--keep-held` after a resolution is an honest no-op (`{"resolved": false, "reason":
"no unresolved import conflict"}`, exit 0) — as is reconciling a held item that
never carried a conflict. `--dry-run` predicts the *same* decision payload the
live run would emit (plus `dry_run: true`) but **writes nothing** — the conflict
stays unresolved and no `resolved` event is recorded (the predict-the-write
discipline `import bundle --dry-run` uses). An unknown ref is a loud
could-not-check (exit 1), the `history`/`verify` empty-vs-error split. A genuinely
new divergent import *after* a resolution appends a fresh `conflict` event and
**re-opens** the alarm — new evidence of a new disagreement.

```console
$ scrolls reconcile web:demo --keep-held --dry-run   # predict: nothing is written
{"id": "web:demo", "resolved": true, "decision": "keep_held", "held_hash": "sha256:9c20…", "incoming_hash": "sha256:7b41…", "dry_run": true}
[exit 0]

$ scrolls reconcile web:demo --keep-held             # affirm the held copy (records a `resolved` event)
{"id": "web:demo", "resolved": true, "decision": "keep_held", "held_hash": "sha256:9c20…", "incoming_hash": "sha256:7b41…", "dry_run": false}
[exit 0]

$ scrolls reconcile web:demo --keep-held             # idempotent — already resolved
{"id": "web:demo", "resolved": false, "decision": "keep_held", "reason": "no unresolved import conflict", "dry_run": false}
[exit 0]

$ scrolls reconcile web:demo                          # a resolution is required, not a default
{"error": "reconcile needs a resolution: --keep-held (affirm the held copy). --accept-incoming (adopt the peer's capture) is deferred — the incoming content is not retained (ADR 0105)"}
[exit 2]
```

### `scrolls archive list [--id <id>]`

The **recovery index** for the accept-incoming resolution (ADR 0106, cited tests in
`tests/test_cli.py`). When `import items`/`import bundle --accept-incoming` adopts a
peer's diverging capture, the held copy it replaced is **archived first** — raw is
never destroyed (custody §2.4) — and `archive list` is how you see what was
superseded: each prior capture's item id, its `content_hash` (`prior_hash`), the
incoming hash that replaced it (`superseded_by`), and when. Newest first; `--id`
(an id or its URL) scopes to one item. Lightweight metadata only — the
model-complete prior snapshot is fetched on demand by `archive show`. A library that
never adopted anything honestly holds nothing (`{"count": 0, "archived": []}`).

```console
$ scrolls archive list
{"count": 1, "archived": [{"item_id": "web:demo", "prior_hash": "sha256:9c20…", "superseded_by": "sha256:7b41…", "archived_at": "2026-06-22T17:19:13+00:00"}]}
[exit 0]
```

### `scrolls archive show <id> [--all | --hash H | --at ISO]`

**Recovers** one item's selected archived prior capture (default: latest), emitting
it as a re-importable `export items` JSONL line on stdout (ADR 0106). Because the
line is the model-complete snapshot, restoring the prior copy is the **symmetric
round-trip** — pipe it back through `import items --accept-incoming` and the held
copy is the original again (the incoming archived in turn):

```console
$ scrolls archive show web:demo | scrolls import items /dev/stdin --accept-incoming
{"imported": 0, "skipped": 0, "unchanged": 0, "conflict": 0, "adopted": ["web:demo"], "conflicts": [], "items": 1}
[exit 0]
```

The single-prior selectors use the same `select_archived_snapshot` fold as
`archive diff` and `archive restore`, so the JSONL artifact an operator inspects is
the exact prior a dry-run restore would adopt:

- `--hash H` — emit the archived prior whose content hash is `H` (the `archive list`
  `prior_hash`).
- `--at ISO` — emit the **newest** prior archived **at or before** the boundary
  (date-only ok → that day's UTC midnight; inclusive).
- neither — emit the **latest** archived prior.

At most one of `--all`, `--hash`, and `--at` may be supplied. An id with no archived
prior (never superseded), an unknown id, or a selector with no match is a loud
could-not-recover (exit 1), the `verify`/`reconcile` empty-vs-error split.

`--all` (H285) emits **every** archived prior for the id — the whole recoverable
history, not just the latest or selected prior — as a JSONL stream, **newest first**
(the `archive list` order). After several adoptions a multi-supersession item carries
more than one prior; `--all` backs up or inspects all of them as re-importable
snapshots, where the default emits only the head:

```console
$ scrolls archive show web:demo --all          # newest archived prior first
{"id": "web:demo", "content_hash": "sha256:v2", ...}
{"id": "web:demo", "content_hash": "sha256:v1", ...}
{"id": "web:demo", "content_hash": "sha256:abc", ...}
[exit 0]
```

The default and `--all` never disagree by construction: `archive show <id>` is
byte-identical to `archive show <id> --all`'s first line (the latest selector is the
head of the shared `items.archived_snapshots` read). An empty history (`--all` on a
never-superseded id) is the same exit-1 could-not-recover.

The recovery **read** also travels over MCP (H281): `list_archived` is the twin of
`archive list` (the same `{count, archived}` index, folding the shared
`items.archive_entry_dict`) and `get_archived(item_id)` is the twin of `archive show`'s
default-latest read (the model-complete, re-importable prior snapshot) — so an agent
operating purely over MCP can read the recovery store. Version-selected `archive show`
and `archive diff` are currently CLI-only reads. The **write** stays **CLI-only**: the
`import … --accept-incoming` adoption, and the symmetric restore, are explicit operator
acts (custody §2.4).

### `scrolls archive restore <id> [--hash H | --at ISO] [--dry-run]`

**Restores** a *specific* archived prior in place (H286, ADR 0106's deferred
restore-by-version). `archive show <id> | import items --accept-incoming` already
restores the **latest** prior; `restore` picks a chosen *version* and adopts it
through the **same** custody-safe write (`adopt_incoming` — no new write path), just a
selection over the `archive show --all` history feeding the existing adoption:

- `--hash H` — restore the archived prior whose content hash is `H` (the `archive
  list` `prior_hash`). A specific version at any depth in the history, not just the
  latest.
- `--at ISO` — restore the **newest** prior archived **at or before** the boundary
  (date-only ok → that day's UTC midnight, the `verify --stale-before` normalization;
  the boundary is **inclusive**). The version held *as of* a point in time.
- neither — the **latest** archived prior (today's behaviour, byte-identical to
  `archive show`'s default). At most one selector (both is a usage error → exit 2).

Restore-by-version stays **fully reversible**: the adoption archives the
*currently-held* copy before replacing it (raw is never destroyed — custody §2.4), so
`archive show` afterward recovers the just-displaced copy. **Idempotent**: restoring a
prior that already *is* the held copy is an `unchanged` no-op (no archive row, no
event). A held id is replaced (`adopted`); a deleted id whose archive survives is
re-created (`imported`).

```console
$ scrolls archive restore web:demo --hash sha256:abc      # an older version, by hash
{"id": "web:demo", "selector": {"hash": "sha256:abc"}, "prior_hash": "sha256:abc", "archived_at": "2026-06-20T00:00:00+00:00", "held_hash": "sha256:v3", "outcome": "adopted", "restored": true, "dry_run": false}
{"warning": "1 held copy(ies) replaced by the incoming capture (accept-incoming — prior archived, recoverable via `scrolls archive show`): `web:demo`"}   # stderr
[exit 0]

$ scrolls archive restore web:demo --at 2026-06-21       # the version held as of a date
{"id": "web:demo", "selector": {"at": "2026-06-21T00:00:00+00:00"}, "prior_hash": "sha256:v1", "archived_at": "2026-06-21T00:00:00+00:00", "held_hash": "sha256:abc", "outcome": "adopted", "restored": true, "dry_run": false}
[exit 0]
```

`restored` is `true` when the held copy actually moved (`adopted`/`imported`), `false`
on the `unchanged` no-op; `held_hash` names the copy that was displaced (archived if
`adopted`). An id with no archived prior — or none matching the selector — is a loud
could-not-recover (exit 1, the `archive show` signal), the held copy untouched on a
miss. A malformed `--at` is a usage error (exit 2, the `archive prune --before`
precedent). **CLI-only** (a custody-changing write); `--dry-run` predicts the same
decision (`dry_run: true`) and writes nothing (the preview-never-drifts discipline,
H245/H273).

### `scrolls archive diff <id> [--hash H | --at ISO]`

**Compares** the currently-held copy against a selected archived prior — the *decide
before you restore* read (H288, ADR 0106). `archive restore` adopts a chosen version;
`diff` answers *"what would I get back, and what would I lose?"* **before** that write,
folding the **same** `select_archived_snapshot` selector restore uses (`--hash H`,
`--at ISO`, default the latest) against the held copy (`get_item`). It reports the
custody-relevant delta, no write:

- `held_hash` vs `prior_hash` — the captured-content fingerprints either side.
- `held_fidelity` / `prior_fidelity` — each copy's custody-fidelity tier (`full` /
  `partial` / `reference`, ADR 0097), so a degradation (e.g. the held copy now
  `partial`, the archived prior still `full`) is visible *before* the swap.
- `changed_fields` — the sorted, model-complete fields a restore would surface
  (`items.diff_snapshot` over `item_to_dict`: `content_hash`, `raw_text`, `title`, …);
  empty when the prior already *is* the held copy.
- `would_restore` — whether a restore would actually change the held copy: the H286
  idempotency predicted as a read (the same `content_hash` compare `merge_item` makes
  — `false` when the prior already is the held copy, an `unchanged` no-op). Note this
  keys on `content_hash`, so a metadata-only difference can list `changed_fields` while
  `would_restore` is `false` (honest, not contradictory — a restore wouldn't pick it up).

```console
$ scrolls archive diff web:demo --hash sha256:abc        # held vs a specific prior
{"id": "web:demo", "selector": {"hash": "sha256:abc"}, "prior_hash": "sha256:abc", "archived_at": "2026-06-20T00:00:00+00:00", "held_hash": "sha256:v3", "held_fidelity": "full", "prior_fidelity": "full", "changed_fields": ["content_hash", "raw_text"], "would_restore": true}
[exit 0]

$ scrolls archive diff web:demo                          # held vs the latest prior (default)
{"id": "web:demo", "selector": {"latest": true}, "prior_hash": "sha256:v2", "archived_at": "2026-06-21T00:00:00+00:00", "held_hash": "sha256:v3", "held_fidelity": "full", "prior_fidelity": "full", "changed_fields": ["content_hash", "raw_text"], "would_restore": true}
[exit 0]
```

**CLI-only read** — it writes nothing (the `archive show` gate; the MCP twin is
deferred). Exits mirror `archive restore`: an unresolvable ref is a usage error (exit
2), at most one version selector (exit 2), a malformed `--at` is a usage error (exit
2); an id with no archived prior — or none matching the selector — is a
could-not-recover (exit 1).

### `scrolls archive prune (--before ISO | --keep N) [--apply]`

**Bounds** the append-only recovery store by a retention policy (H282). The
`item_archive` grows on every accept-incoming adoption (and the symmetric restore
round-trip), so over time the store accumulates superseded captures. Pruning it is
**custody-safe** — the archive is a *recovery convenience*, not the root of trust
(raw is sacred for the **held** copy; a superseded prior is already a deliberate
replacement, ADR 0106 / custody §2.4) — but the act is **explicit**, **report-only
by default**, and **never touches a held row** (it only ever DELETEs from
`item_archive`).

Exactly **one** retention policy is required (a bare `prune`, or both at once, is a
usage error → exit 2, the `reconcile <id>` opt-in gate):

- `--before ISO` — drop priors archived **strictly before** the boundary
  (date-only ok → that day's UTC midnight, the `verify --stale-before` normalization).
  The time-based policy; it **may** drop an item's latest prior (after which
  `archive show` for that id is a could-not-recover — the honest consequence of a
  time-bound retention).
- `--keep N` — per item, keep the **most recent N** priors and drop the rest. N>=1
  (a `--keep 0` is rejected), so the latest prior **always survives** a keep-prune
  and `archive show <id>` keeps recovering it. The count-based policy.

**Report-only by default** — it predicts the drop set and writes nothing (the
dry-run discipline, H245/H273); `--apply` performs the deletion and warns loudly on
stderr (a recovery store was shrunk). The report is shared by both modes, so the
preview describes exactly what `--apply` would remove:

```console
$ scrolls archive prune --keep 1            # report-only: predict, write nothing
{"policy": {"keep": 1}, "applied": false, "matched": 2, "dropped": 0, "remaining": 1, "by_item": [{"item_id": "web:demo", "dropped": 2}], "archived": [ ...the two oldest priors... ]}
[exit 0]

$ scrolls archive prune --keep 1 --apply    # commit the deletion
{"policy": {"keep": 1}, "applied": true, "matched": 2, "dropped": 2, "remaining": 1, "by_item": [{"item_id": "web:demo", "dropped": 2}], "archived": [ ... ]}
{"warning": "pruned 2 archived prior capture(s) across 1 item(s) (held copies untouched): `web:demo`"}   # stderr
[exit 0]
```

`matched` is the drop set the policy selects; `dropped` is what was actually removed
(0 in preview, `== matched` after `--apply`); `remaining` is the archive rows that
survive; `by_item` rolls the drop set per item; `archived` carries the full
drop-set entries for review (the `archive list` shape). **Idempotent**: a second
`--apply` with the same policy finds the rows already gone and drops nothing. The
write is **CLI-only** (a custody-changing write, like `verify`/`reconcile`); an
uninitialized / pre-v8 library honestly reports an empty drop set.

### `scrolls maintain [--all] [--limit N | --no-recheck | --history [N]] [--trend] [--source S]`

One scheduled **custody-maintenance pass** — the dogfood flow's recurring sibling
(`docs/dogfood.md`), composed entirely from surfaces that already ship
(`tests/test_maintain.py`). It runs four steps in order and prints one report:

1. **recheck** — `scrolls verify` over the **stale set** by default: only the held,
   hash-bearing items not seen since the last recorded run — the boundary is that
   run's `recorded_at` (`<root>/.maintenance/last-run.json`), so a scheduled pass
   re-verifies the *new* work, not the whole library every run. It appends
   drift/rot events to the ledger and never touches the captures. The stale set is
   ordered **coverage-first** — never-checked items first, then already-verified
   ones oldest-verdict-first (`custody.recheck_order`) — so a `--limit N` pass
   spends its budget on *new* custody coverage instead of re-verifying the same
   head every run; successive bounded passes cycle the whole library (monotone
   coverage progress). `--all` ignores the staleness boundary and rechecks **every**
   held item (the pre-stale-bounding behavior), composing with `--limit` (so
   `--all --limit N` is a bounded whole-library recheck); a **first run** (no
   baseline) has no boundary, so it too rechecks everything. The recheck report's
   `scope` (`stale` / `all`) and `since` (the boundary, or null) disclose which
   window the pass used. `--no-recheck` skips the live edge entirely for a fully
   offline pass; `--limit`/`--no-recheck`/`--history` are mutually exclusive
   (`--limit` bounds a recheck `--no-recheck` would skip), and `--all` conflicts
   with `--no-recheck` / `--history` (a recheck-scope flag can't skip the recheck
   or shape a read-only history). The recheck report also carries a
   `coverage` member — `{verified, total}` over the held, hash-bearing
   (verifiable) items: `total` is how many *can* carry a verdict (a reference-only
   capture has no baseline hash to diff, so it is excluded — coverage can reach
   full), `verified` how many now do *after* this pass. So a single report answers
   "N of M verifiable items carry a verdict" and the coverage-first ordering's
   monotone progress is visible directly, without diffing the `unverified` count
   across runs. It is a read (`custody.recheck_coverage`), so it rides
   `--no-recheck` too, and converges with the audit by construction:
   `coverage.verified` equals doctor's `custody.drift.checked`, and
   `total − verified` its `custody.drift.unverified` when every held item is
   hash-bearing (both from the one `unverified_items` predicate).
2. **regenerate** — `scrolls kb` (the deterministic compile), rebuilding the
   `library/` views from the canonical rows. Never an LLM re-synthesis: refreshing
   concept summaries stays the explicit `scrolls kb --stale`.
3. **audit** — `scrolls doctor` (read-only, never `--fix`), read *after* the
   recheck and regenerate so the custody picture is the post-maintenance state.
4. **delta** — the custody change since the last run, compared against a snapshot
   recorded at `<root>/.maintenance/last-run.json`. The snapshot carries only the
   custody scalars the delta compares (`score`, fidelity `tiers`, the `drift`
   posture, the recheck `coverage` `{verified, total}` from the audit's
   `custody.drift.coverage`, and the `enrichment_stale`/`summaries_stale` counts
   from doctor's `custody.enrichment`/`custody.summaries` blocks). Recording
   `coverage` in the snapshot is what lets `--history`/`--trend` replay the
   *coverage trajectory* the coverage-first recheck drives, not just a
   point-in-time figure on one pass's report. On the first run there is no
   baseline (`delta.first_run: true`, every `before`/`change` null); a baseline
   missing an axis (an older snapshot, e.g. one written before `coverage` was
   tracked) reads that axis as zero, never null.

The report also carries a one-line **`headline`** — the shared
`custody.custody_headline` (`_Custody: N scroll(s) · fidelity <tier counts> ·
drift <posture counts>._`) the bundle briefing, the `context` bundle, and the
compiled `library/` pages all emit — so the unattended worker's log reads "how
custody stands" at a glance without assembling the raw `custody` counts. It is
rendered from the snapshot this run records (no second ledger read), so it
converges by construction with the `custody` block it sits beside and equals
`custody_headline` over the post-maintenance library (the `verified` posture is
the snapshot's `unchanged` count, the documented mapping). Each `--history` /
`--trend` run carries its own `headline`, rendered fresh from that run's recorded
snapshot at read time (so a pre-H103 log entry renders one too); the stored
`log.jsonl` keeps the bare `{recorded_at, snapshot, delta}`.

The report also carries a one-line **`at_risk_headline`** — the *consolidation-loss*
counterpart of `headline` (roadmap H268): `_At-risk works: N (▲M since last run)._`,
distilling the at-risk-works count the snapshot records (H267 — the works no
representation safely holds, `doctor`'s `custody.works.at_risk`) plus its signed
movement since the last run. `▲M` is a **rise** (more works lost their last safe
copy — worse), `▼M` a **fall** (a recapture restored one — better), and a `0` change
reads the explicit `(no change since last run)`. So a human skimming the maintenance
output reads the consolidation-loss trend without parsing the `delta` JSON — the
at-risk analogue of the `_Custody:_` headline and the per-source `_Attention:_` line.
Degrade-safe: on a first run, or a scoped non-persisting pass (`delta` null), it drops
the change clause — the bare `_At-risk works: N._` — *exactly* when there is no
baseline to difference against (a `--source` pass also skips the whole-work alarm, so
its count is `0`; a `--fidelity` pass audits whole-library, so its count is real but
still has no trend baseline). The count converges with the JSON `at_risk_works` alarm
and the `custody.at_risk` snapshot scalar by construction
(`test_maintain_report_carries_the_readable_at_risk_line`,
`test_maintain_report_at_risk_line_shows_the_rise_since_last_run`).

The report likewise carries a one-line **`conflicts_headline`** — the
*peer-divergence* counterpart on the conflict axis (roadmap H283): `_Conflicts: N
(▲M since last run)._`, distilling the unresolved-import-conflict count the snapshot
records (H279 — held items whose latest import conflict still disagrees with the held
copy, `doctor`'s `custody.conflicts.items`) plus its signed movement since the last
run. `▲M` is a **rise** (more held items carry an unresolved peer divergence — worse),
`▼M` a **fall** (a `reconcile --keep-held` / `import … --accept-incoming` resolution
cleared one — better), and a `0` change reads `(no change since last run)`. It is the
readable closure of the conflict scalar H279 recorded but left un-differenced.
Degrade-safe identically (the bare `_Conflicts: N._` on a first run / scoped
non-persisting pass). Unlike the whole-library-only at-risk line, the conflict count is
**source-attributable**, so a `--source S` pass narrows it to `S` (a held item owns a
source). Resolution-aware and converges with the `custody.conflicts` snapshot scalar
and `doctor`'s `custody.conflicts.items` by construction
(`test_maintain_report_carries_the_readable_conflicts_line`,
`test_maintain_report_conflicts_line_shows_the_rise_since_last_run`,
`test_maintain_report_conflicts_line_under_a_scope`).

The report also carries a one-line **`archive_integrity_headline`** — the readable
surfacing of `doctor`'s archive-integrity check on the *recovery store* axis (roadmap
H298): `_Archive: N prior(s) fail integrity (prior_hash ≠ snapshot)._`, the count of
archived priors whose advertised `prior_hash` — the fingerprint `archive
list`/`archive restore --hash` key on — no longer equals their model-complete
`snapshot` body's own `content_hash` (`doctor`'s `custody.archive.mismatched`, H293: a
corrupt/laundered recovery row a bad `import archive` or hand-edited `--with-archive`
bundle could land, invisible until restore). H293 put that check on the JSON read
surfaces only; this is the readable line for the scheduled pass an operator skims, the
`conflicts_headline` sibling on the archive axis. It carries the signed cross-run
movement (roadmap H299): `_Archive: N prior(s) fail integrity (prior_hash ≠ snapshot)
(▲M since last run)._`, where `▲M` is a **rise** (new corruption landed — a bad `import
archive` / hand-edited bundle, worse), `▼M` a **fall** (a prior re-imported clean or the
backup rebuilt — better), and a `0` change reads `(no change since last run)` (the
corruption persists, unrepaired). The *count* is the live audit's `custody.archive.mismatched`;
the *change* is the delta's `archive_mismatched.change`, so a first run / scoped
non-persisting pass drops the clause (the bare H298 line). **Omitted entirely** (the
field is `null`, never a fabricated `_Archive: 0 …_`) when there is nothing to flag — a
**steady-clean** store (`mismatched == 0` with no fall to report) *or* a skipped audit:
the archive is a single **whole-library** recovery store, so a `--source S` pass leaves
it `status: "skipped"` (the whole-library-only check never runs, so the line is dropped
regardless of any baseline), while a `--fidelity` pass (whose audit stays whole-library)
still computes it. Unlike the always-rendered at-risk/conflict lines it follows the
omit-when-clean briefing posture (a tampered backup is the exception worth a line) —
**with one H299 exception: a *repaired* backup** (the count just fell *to* zero) still
renders the `▼` line, since a fix is the direction worth surfacing, not silently
swallowing; a steady-zero store stays omitted. The count converges with the
`custody.archive_mismatched` snapshot scalar (what `scrolls status` reads) and `doctor`'s
`custody.archive.mismatched` by construction — only the clause is added
(`test_maintain_report_carries_the_archive_integrity_headline`,
`test_maintain_report_embeds_the_archive_integrity_trend_clause`,
`test_maintain_omits_the_archive_headline_on_a_clean_library`,
`test_maintain_source_pass_omits_the_archive_headline`).

The report also carries a one-line **`duplicates_headline`** — the readable surfacing
of `doctor`'s content-identity redundancy report on the *byte-identity* axis (roadmap
H327): `_Duplicates: N group(s) of byte-identical content (M item(s))._`, the count of
groups of held items that share a non-null `content_hash` across *different* ids and
their member total (`doctor`'s `custody.content_duplicates.total_groups`/`.total_items`,
H325 — the same bytes saved from two URLs, a mirror, a cross-post, or one work captured
by two source adapters). H325 put the fold on the JSON read surfaces only; this is the
readable line for the scheduled pass an operator skims, the `archive_integrity_headline`
sibling on the content-identity axis. It carries the signed cross-run movement (roadmap
H330): `_Duplicates: N group(s) of byte-identical content (M item(s)) (▲K since last
run)._`, where `▲K` is **new** redundancy (a fresh byte-identical pair landed), `▼K`
**pruned** copies (an operator deleted a duplicate), and a `0` change reads `(no change
since last run)`. The *count* is the live audit's `custody.content_duplicates`; the
*change* is the delta's `content_duplicate_groups.change` (the **group** count), so a
first run / scoped non-persisting pass drops the clause (the bare H327 line).
**Omitted entirely** (the field is `null`, never a fabricated `_Duplicates: 0 …_`) when
there is nothing to flag — a library with no byte-identical holdings (`total_groups ==
0`) *or* a skipped audit: a content group spans sources, so like the archive line it is
**whole-library only**, and a `--source S` pass leaves the block `status: "skipped"` (the
line dropped regardless), while a `--fidelity` pass (whose audit stays whole-library)
still computes it. **The one documented divergence from the archive trend line: the
omit-when-clean stays *unconditional*.** The `_Archive:_` line keeps a fall-to-zero
"repaired backup" exception (H299) because a fixed backup is a direction worth surfacing;
content duplicates have none — they are **report-only, never a defect** (holding two
faithful copies is a redundancy fact an operator may want, and there is no `--fix` merge
that "repairs" them — raw is sacred), so a count that fell *to* zero is an operator
pruning a copy, not a fix, and the `▲`/`▼` clause shows only while `total_groups > 0`
(both the steady-clean and the fallen-clean states stay silently omitted). The count
converges with the `custody.content_duplicate_groups`/`content_duplicate_items` snapshot
scalars (what `scrolls status` reads) and `doctor`'s `custody.content_duplicates` by
construction — the readable line is rendered from the same live audit block, and the
movement telescopes with the recorded per-run deltas
(`test_maintain_report_carries_the_duplicates_headline`,
`test_maintain_report_embeds_the_duplicates_trend_clause`,
`test_maintain_report_omits_the_duplicates_line_on_a_fall_to_zero`,
`test_maintain_omits_the_duplicates_headline_on_a_library_with_no_duplicates`,
`test_maintain_source_pass_omits_the_duplicates_headline`).

Each run also **appends** its `{recorded_at, snapshot, delta}` record to an
append-only `<root>/.maintenance/log.jsonl` — the custody *trend*, not just the
last diff. `scrolls maintain --history [N]` prints the last `N` recorded runs
(default 10) as a JSON array, oldest first, so a worker or agent reads the
score/drift *trajectory* over time. It is read-only — it never runs a pass,
rechecks, recompiles, or appends — and is mutually exclusive with `--limit` /
`--no-recheck` (those run a pass; `--history` reads one back). Honest absence
(the completeness contract): a library that has never run `maintain`, or no
library at all, prints `[]`, never an error. The log follows the custody-ledger
posture (append, never rewrite); like the snapshot it degrades safely — a
missing log is an empty history, and one corrupt line is skipped, never aborting
the read.

`scrolls maintain --history --trend` wraps the runs in a `{trend, runs}`
envelope (the opt-in-envelope pattern, like `search --stats`, so the bare array
stays the default and the completeness contract's empty `[]` never regresses).
The `trend` distils the window's *direction* so a worker reads it without
diffing entries: the net `score` change first→last, the net drift movement
(Δ`drifted`+Δ`rotted`), the net recheck-coverage movement (`coverage_change`,
`{verified, total}` net deltas — "is the library getting more covered?", Δ
`verified` up as bounded passes verify the never-checked tail, Δ`total` up as new
verifiable items are added), the net re-derivability-debt movement (`stale_change`,
`{enrichment, summaries}` net deltas — "is a `classify --stale` / `kb --stale`
refresh becoming overdue?", Δ the stale-classification count and Δ the
stale-summary count), and a one-word `posture` — `regressing` if the score
dropped *or* more scrolls drifted/rotted (integrity-first), `improving` if the
score rose or drift cleared, else `holding`. **`coverage_change` and `stale_change`
are separate reported axes, not `posture` inputs**: coverage measures *how much has
been checked* and staleness *how much enrichment is re-derivable*, neither *how
faithfully we hold what we have* — a held category produced under a superseded
ruleset is still held, so rising coverage is not "improving" integrity, a library
overdue for a re-check is not "regressing", and growing stale debt does not move
the posture. `posture` stays integrity-only. A window of fewer than two runs is
not a trajectory, so it carries null deltas (`score`, `drift_change`,
`coverage_change`, `stale_change`, `at_risk_change`, `conflicts_change`,
`archive_mismatched_change`, and `content_duplicates_change` all null) and
`posture: insufficient-history` (honest absence). `--trend` only shapes a
`--history` read; passed alone it is a usage error (exit 2), never a
silently-ignored flag that runs a full pass.

The trend also carries a one-line **`at_risk_headline`** — the trend twin of the
report's readable at-risk line (roadmap H268): `_At-risk works: N (▲M over K runs)._`,
the window's last at-risk-works count plus the net `at_risk_change` movement across
its `K` runs, so a human reads the consolidation-loss trajectory ("2 → 4 works at
risk over the last 5 runs") without parsing `at_risk_change`. Same `▲`/`▼`/`no change`
convention as the report line, with the window span (`over K runs`) replacing the
report's `since last run`. A `<2`-run window has no trajectory, so it reads the bare
`_At-risk works: N._` (the current count, no change clause — the same honest absence
the null `at_risk_change` takes; an empty history reads `0`)
(`test_trend_carries_the_readable_at_risk_line_over_the_window`,
`test_trend_at_risk_line_is_bare_under_two_runs`).

The trend also carries the matching **`conflicts_headline`** — the trend twin of the
report's readable conflict line (roadmap H283): `_Conflicts: N (▲M over K runs)._`,
the window's last unresolved-conflict count plus the net `conflicts_change` movement
across its `K` runs, so a human reads the peer-divergence trajectory ("1 → 0
unresolved conflicts over the last 3 runs") without parsing `conflicts_change`. Same
`▲`/`▼`/`no change` convention and `over K runs` span as the at-risk trend line, with
the same bare `_Conflicts: N._` under a `<2`-run window
(`test_trend_carries_the_readable_conflicts_line_over_the_window`,
`test_trend_conflicts_line_is_bare_under_two_runs`).

The trend also carries the matching **`archive_integrity_headline`** — the trend twin of
the report's readable archive line (roadmap H299): `_Archive: N prior(s) fail integrity
(prior_hash ≠ snapshot) (▲M over K runs)._`, the window's last archive-mismatch count
plus the net `archive_mismatched_change` movement across its `K` runs, so a human reads
the corruption trajectory ("1 → 2 corrupt priors over the last 3 runs") without parsing
`archive_mismatched_change`. Same `▲`/`▼`/`no change` convention and `over K runs` span
as the conflict trend line. Unlike the always-rendered at-risk/conflict trend lines it
keeps the report's omit-when-clean posture: the field is `null` for a steady-clean
window, the bare `_Archive: N …_` for a corrupt `<2`-run window (`None` if that one run
is clean), but a **fall to zero** across the window (a repaired backup) still renders the
`▼` line (`test_trend_carries_the_readable_archive_line_over_the_window`,
`test_trend_archive_line_shows_a_repaired_backup_falling_to_zero`,
`test_trend_archive_line_is_omitted_when_steady_clean`).

The trend also carries the matching **`duplicates_headline`** — the trend twin of the
report's readable content-duplicate line (roadmap H330): `_Duplicates: N group(s) of
byte-identical content (M item(s)) (▲K over R runs)._`, the window's last
content-duplicate group count + member total plus the net `content_duplicates_change`
movement across its `R` runs, so a human reads the redundancy trajectory ("1 → 2
duplicate groups over the last 3 runs") without parsing `content_duplicates_change`. Same
`▲`/`▼`/`no change` convention and `over R runs` span as the archive trend line. Like the
archive line it keeps the omit-when-clean posture (the field is `null` for a steady-clean
window, the bare `_Duplicates: N …_` for a `<2`-run window with redundancy, `None` if
that one run is clean) — **but with the same unconditional divergence as the report line:
there is no fall-to-zero exception**, so a window whose count fell *to* zero is silently
omitted (an operator pruned the last copy, not a defect repaired), unlike the archive
trend's repaired-backup `▼` line (`test_trend_carries_the_readable_duplicates_line_over_the_window`,
`test_trend_duplicates_line_is_omitted_on_a_fall_to_zero`,
`test_trend_duplicates_line_is_omitted_when_steady_clean`).

This is **report-only and idempotent** (vision §2.4): it records drift
events and regenerates views, but never repairs index rows, reclassifies, or
re-summarizes — `doctor --fix`, `classify --stale`, and `kb --stale` stay the
explicit, on-request mutations. The recorded snapshot is dot-prefixed so it is
never a compiled `library/` page and is never created by `scrolls init`; losing
or corrupting it just means "first run" (the pass degrades safely, never aborts).

Because maintain repairs nothing itself, the report carries a **`suggested`**
block: for each repairable finding the audit surfaces, the explicit on-request
command that closes it. Each entry is `{command, addresses}` — `addresses` names
exactly the finding categories present that the command repairs. The structural
fixes `doctor --fix` performs (duplicate items, missing scroll files, an
out-of-sync FTS index) are grouped into one suggestion; missing media
(`scrolls media`), stale classifications (`classify --stale`), and stale concept
summaries (`kb --stale`) are each their own. Suggestions are **by finding, never
by the aggregate `issues` count**: an orphan scroll bumps `issues` (and the exit
code) but has no on-request repair — doctor never deletes a file it cannot prove
it wrote (custody §2.4) — so it yields *no* suggestion rather than pointing at a
`doctor --fix` that would not remove it. A clean pass is the honest empty
`"suggested": []`. The block rides the live pass only, derived fresh from its
audit; it is not recorded in the snapshot, so `--history`/`--trend` (which replay
snapshots) never carry a stale suggestion. The category→command mapping is pinned
against doctor's *real* `fix=True` behavior (the categories routed to `doctor
--fix` are exactly the ones it transitions to a repaired status), so a suggestion
can never silently drift from what the command actually closes.

The two enrichment-axis refreshes are further **source-scoped when the debt is
confined** (roadmap H181). When the stale classifications / stale summaries sit in
a *strict subset* of the library's held sources, maintain suggests the minimal act
— one `scrolls classify --stale --source <S>` / `scrolls kb --stale --source <S>`
per offending source ([H154](#scrolls-classify-id) / [H172](#scrolls-kb---engine----stale))
instead of the whole-library sweep that would needlessly re-run the clean sources.
The held-source universe is `doctor`'s `custody.by_source` (every held source); the
offenders are `enrichment_by_source` / `summary_by_source`. When *every* held source
carries the debt — or a pre-`by_source` audit can't see the universe — scoping buys
nothing, so the whole-library `classify --stale` / `kb --stale` stands. On the
summary axis the H171 multi-source attribution carries through: a stale concept
spanning several sources is named under each, so each gets its own scoped `kb
--stale --source <S>`; refreshing under any one regenerates the whole cluster
(H172), so the per-source commands harmlessly double-cover it while their union
refreshes exactly the offenders.

A **scoped pass** (`maintain --source <S>`, below) always suggests the *scoped*
refresh (roadmap H182). Because the scoped pass pre-filters the audit through
`run_doctor(source=<S>)`, its held-source universe collapses to `{<S>}` and the
offenders are `{<S>}` too — making offenders == universe, so the strict-subset rule
above would emit the whole-library `classify --stale` / `kb --stale` even though the
operator explicitly scoped the pass to `<S>`. The pass's `--source <S>` scope is
threaded through, so a scoped pass with stale debt suggests `classify --stale
--source <S>` / `kb --stale --source <S>` to match its scope (a scoped pass with no
debt suggests nothing — `--source` never fabricates a command for an absent finding).
The whole-library pass is unchanged: with no scope declared, the strict-subset rule
governs as above.

The report also carries a **`duplicate_prunes`** block — the content-identity
counterpart of `suggested` (roadmap H356). The `suggested` block turns every
*repairable* finding into the command that closes it, but the content-duplicate
finding (`doctor`'s `custody.content_duplicates`, the byte-identical holdings the
`_Duplicates:_` headline counts) is deliberately *not* a repairable category: there
is no library-wide auto-fix and `doctor --fix` never merges a content duplicate
(holding two faithful copies is a redundancy fact an operator may want, not a defect,
and byte-identity across ids is custody-distinct provenance — raw is sacred). So an
operator saw "N group(s) of byte-identical content" with no guidance on *which copy to
keep* or *how to prune the rest*. `duplicate_prunes` fills that gap with **report-only**
guidance — one entry **per byte-identical group**, `{content_hash, keep, prune,
command}`: the `keep` copy (a deterministic canonical pick — **highest fidelity, then
earliest `saved_at`, then lowest id**, the ADR 0095 canonical-representation rule on the
content-identity axis), the `prune` ids (every other member, sorted), and the single
`scrolls rm <ids>` command that prunes them (`rm` takes several ids). It is **never
auto-executed and never a `doctor --fix` step** — a prune is an operator decision, so
this is *guidance*, not a repair the pass performs. Derived from `doctor`'s
authoritative `content_duplicates.groups`, so it converges with the `_Duplicates:_`
headline by construction: a clean library — or a `--source` pass, where a content group
spans sources so the whole-library check stays `status: "skipped"` — has no groups and
yields the honest empty `[]` (the same omit-when-clean / scoped-skip the headline
takes). Like `suggested` it rides the live pass only and is never recorded in the
snapshot, so `--history`/`--trend` carry none
(`test_suggest_duplicate_prunes_keeps_the_highest_fidelity_copy`,
`test_suggest_duplicate_prunes_is_report_only_never_a_doctor_fix_step`,
`test_maintain_report_carries_the_content_duplicate_prune_guidance`,
`test_maintain_source_scoped_pass_omits_the_prune_guidance`).

The report also carries a **`by_source`** member — the per-source custody
breakdown the audit already produces (`doctor`'s `custody.by_source`, the same
`{tiers, drift, coverage}` aggregate split per source, including the per-source
`coverage` `{verified, total}` of roadmap H121) — so the unattended log names
*which* source's custody is weakest (most reference-only, most drifted, or least
*covered*: the source to target a `verify --drift` / `scrolls media` / recapture
at) without re-running `doctor`. Source keys are sorted; because each per-source group folds through the
same `custody_counts`, the breakdown **sums to the `custody` block beside it** by
construction (every item lands in exactly one source group), with the documented
`verified ≡ unchanged` mapping. Like `suggested` (and the recheck `scope`/`since`)
it rides the **live pass only** — derived fresh from this pass's audit, never
recorded in the snapshot/log — so `--history`/`--trend` carry none. An empty or
uninitialized library is the honest empty map (no source stands out).

Distilled from that map, the report also carries an **`attention`** member — the
single source worth flagging, so the log names the one to act on without scanning
every source. It is the source with the most **actionable loss** (the most
`drifted` + `rotted` items — confirmed moved or gone, the set a follow-up `verify
--drift` / `scrolls media` targets), tie-broken by the most `reference`-only items,
then the source name. The value is `{source, tiers, drift, coverage, reason, command}`
— the flagged source's own tally (including its recheck **`coverage`**
`{verified, total}` — how much of the weak source is even checked, roadmap H153 —
so the flag tells you whether the drift is the whole story or just the verified
slice of a barely-covered source; it equals `doctor`'s
`custody.by_source[<source>].coverage` for that source by construction), a one-line
`reason` naming the loss (e.g. `"2 drifted, 1 rotted"`), and the exact **`command`**
to re-check it — `scrolls verify --source <source>` — so the report names not just
*which* source is weakest but the act that re-verifies it (a recheck, not a
`doctor --fix` repair, so it rides `attention` beside the source it names, never
`suggested`). Honest **`null`** when nothing
stands out: an **empty** library (nothing
to flag), a **single** source (no source stands out — the whole-library `custody`
block already says everything; `attention` only adds value by discriminating
*across* sources, so a one-source library is null even with drift), or a
**fully-clean** library (no source carries any drifted/rotted loss — reference-only
is the normal capture posture, a tie-breaker, never a trigger). Like `by_source`,
it rides the live pass only.

The report also carries an **`at_risk_works`** member (roadmap H263) — the
consolidation-level analogue of `attention`, the audit's `custody.works` block
threaded through unchanged (see [`doctor`](#scrolls-doctor---fix---source-s)). Where
`attention` names the source carrying the most per-*item* drift, this names the
**works** carrying a *consolidation* loss: `{status, total, at_risk, most_at_risk}`,
where a work is at risk when **no** representation is safely held (every copy
degraded or moved, no unmoved full form anywhere), and `most_at_risk` names the
single lowest-custody-ceiling one (`null` when none) — the one work to act on. A
work spans sources, so the alarm is **whole-library only**: an unscoped or
`--fidelity` pass carries the computed block (`status: "ok"`), a `--source` pass the
skipped default (`status: "skipped"` — a scoped audit cannot see whole works). Like
`by_source`/`attention`/`suggested` it rides the **live pass only** — derived fresh
from this pass's audit, never recorded in the snapshot/log, so `--history`/`--trend`
carry none (`test_maintain_reports_the_at_risk_works`,
`test_maintain_at_risk_works_skipped_under_a_source_scope`,
`test_maintain_history_does_not_carry_at_risk_works` in `tests/test_maintain.py`).

The report also carries an **`enrichment_by_source`** member (roadmap H147) — the
per-source **stale-classification debt** the audit already produces (`doctor`'s
`custody.enrichment.by_source`, the re-derivability counterpart of `by_source`'s
drift split) — a flat `{source: stale_count}` of the *offending* sources only
(sorted keys), so the unattended log names *which* source's `classify --stale` to
run without re-running `doctor`. A **standalone** member, not folded into
`by_source` (so the `by_source` ≡ `custody_counts_by_source` byte-identity holds);
it **sums to `custody.enrichment_stale`** by construction (every stale item has
exactly one source). Like `by_source`/`attention`/`suggested` it rides the **live
pass only** — derived fresh from this pass's audit, never recorded in the
snapshot/log — so `--history`/`--trend` carry none. Honest empty `{}` when no source
carries stale debt (the offenders-only posture: a clean source is omitted, never a
`0` entry), and when there is no library at all
(`test_maintain_report_carries_the_per_source_enrichment_staleness`,
`test_maintain_enrichment_by_source_sums_to_the_whole_library_enrichment_stale`,
`test_maintain_per_source_enrichment_on_a_clean_library_is_empty`,
`test_maintain_history_does_not_carry_the_per_source_enrichment_breakdown`; the
maintain↔doctor tie in `test_enrichment_by_source_converges_with_the_per_source_stale_classifications`).

Its **summary-axis sibling** **`summary_by_source`** (roadmap H175) does the same
for **stale concept summaries** — a faithful read of `doctor`'s
`custody.summaries.by_source` (H171), a flat `{source: stale_count}` of the
offending sources only (sorted keys), so the log names *which* source's
[`kb --stale`](#scrolls-kb---engine----stale) to run without re-running `doctor`.
The one load-bearing difference from `enrichment_by_source`: it **need not sum to
`custody.summaries_stale`**. A concept summary spans a *cluster* whose members can
come from several sources, and the stored fingerprint records only the digest (not
which member moved), so a stale summary is attributed to *each* contributing source
— a single multi-source stale concept counts toward every one of them, and
`sum(summary_by_source.values()) >= summaries_stale`. The `maintain`↔`doctor` tie is
therefore **faithful-read equality** (`summary_by_source ==
doctor.custody.summaries.by_source`), never a sum-to-whole check — unlike the
enrichment/drift maps where each item has exactly one source. Live-pass only and
honest-empty on the same gates as `enrichment_by_source`
(`test_maintain_report_carries_the_per_source_summary_staleness`,
`test_maintain_summary_by_source_need_not_sum_to_the_whole`,
`test_maintain_per_source_summary_on_a_clean_library_is_empty`,
`test_maintain_history_does_not_carry_the_per_source_summary_breakdown`; the
maintain↔doctor tie beside the enrichment one in
`test_summaries_by_source_converges_with_the_per_source_stale_summaries`).

The sharp custody point the delta makes visible (the dogfood proof's, recurring):
detecting source drift moves the *drift posture* (`unverified` → `drifted`)
**without lowering the integrity `score`** — raw is sacred, drift is a recorded
event, not a loss of what we hold. Exit mirrors `doctor`: nonzero only when
structural `issues` remain (run `doctor --fix` / `scrolls media`); drift and stale
enrichment/summaries are reported, never a failure.

`--source <S>` scopes the **whole pass** to one source's held items (roadmap H165)
— the scheduled-maintenance counterpart of [`doctor --source`](#scrolls-doctor)
(H162) and [`status --source`](#scrolls-status) (H166), and the maintenance sibling
of the act-side `verify --source` (H125), reusing the **same** `run_doctor(source=)`
pre-filter. The **recheck** narrows to that source's held, hash-bearing items (the
`verify --source S` set, still stale-bounded / `--all`-able / `--limit`-paced); the
**audit** is scoped, so `custody`, `headline`, `by_source` (the singleton `{S: …}`),
and `enrichment_by_source` are the one-source view; `attention` is therefore `null`
(a single source has nothing to flag *across* — the same gate as `status --source`).
The **`suggested`** refreshes are scoped to match (roadmap H182): a scoped pass with
stale debt suggests `classify --stale --source S` / `kb --stale --source S`, not the
whole-library sweep the collapsed universe would otherwise yield (see the `suggested`
block above).
The scoped `custody`/`by_source`/`headline` **converge by construction** with a
`doctor --source S` audit distilled and a `status --source S` payload, the third leg
of the per-source-scope triad (pinned in `tests/test_custody_convergence.py`). Three
properties keep a scoped pass custody-safe: **view regeneration stays whole-library**
(`compile_kb` is a deterministic global recompile, not a per-source one — only the
recheck/audit/`by_source` narrow); the pass **records per-item drift events** (real
work the next whole-library pass folds into the trend) but is otherwise
**non-persisting** — it never writes the single whole-library snapshot/trend log, so
a focused triage pass can't clobber the one baseline with a one-source slice (no
per-source storage shape); and because no per-source baseline exists to diff against
(the stored snapshot carries only whole-library scalars), the scoped **`delta` is
`null`** (the honest-absence posture — the per-pass `recheck` movement is the signal;
the whole-library `maintain` owns the cross-run trend). The report's top-level
**`source`** member echoes the scope (`null` for the whole-library pass). `--source`
composes with `--all`/`--limit`/`--no-recheck` (scope ∧ window/bound) and conflicts
with `--history` (a read of recorded passes, not a pass — exit 2). An unknown source
holds nothing, so a scoped pass is the honest empty pass (`_Custody: 0 scroll(s)._`,
empty `by_source`, `null` `attention`/`delta`, exit 0), never an error — sources are
open-ended. The exit code reflects only `<S>`'s attributable findings (orphan/FTS are
not source-attributable, so the scoped audit skips them per `doctor --source`).

```console
$ scrolls maintain --no-recheck --source web   # triage one source's custody (the `attention` flag named it)
{"recorded_at": "2026-06-18T17:00:00+00:00", "source": "web", "recheck": {"skipped": true, "scope": null, "since": null, "checked": 0, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0, "coverage": {"verified": 2, "total": 2}}, "compiled": {"items": 3, "sources": 2, "categories": 3, "concepts": 2, "tags": 3, "summaries": 0, "clusters": 0, "works": 0, "pages": 9}, "custody": {"score": 100, "tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"checked": 2, "unverified": 0, "unchanged": 1, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 2, "total": 2}, "enrichment_stale": 0, "summaries_stale": 0, "at_risk": 0, "conflicts": 0, "archive_mismatched": 0, "content_duplicate_groups": 0, "content_duplicate_items": 0}, "headline": "_Custody: 2 scroll(s) \u00b7 fidelity full 2 \u00b7 drift verified 1, drifted 1._", "at_risk_headline": "_At-risk works: 0._", "conflicts_headline": "_Conflicts: 0._", "archive_integrity_headline": null, "by_source": {"web": {"tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 0, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 2, "total": 2}}}, "attention": null, "enrichment_by_source": {}, "summary_by_source": {}, "delta": null, "issues": 0, "suggested": []}
[exit 0]

$ scrolls maintain --all --limit 50      # second run; force a whole-library recheck — one source has drifted
{"recorded_at": "2026-06-16T13:00:00+00:00", "recheck": {"skipped": false, "scope": "all", "since": null, "checked": 3, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0, "coverage": {"verified": 3, "total": 3}}, "compiled": {"items": 3, "sources": 2, "categories": 3, "concepts": 2, "tags": 3, "summaries": 0, "clusters": 0, "works": 0, "pages": 9}, "custody": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 3, "unverified": 0, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 3, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0, "at_risk": 0, "conflicts": 0, "archive_mismatched": 0, "content_duplicate_groups": 0, "content_duplicate_items": 0}, "headline": "_Custody: 3 scroll(s) \u00b7 fidelity full 3 \u00b7 drift verified 2, drifted 1._", "at_risk_headline": "_At-risk works: 0 (no change since last run)._", "conflicts_headline": "_Conflicts: 0 (no change since last run)._", "archive_integrity_headline": null, "by_source": {"arxiv": {"tiers": {"full": 1, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 1, "total": 1}}, "web": {"tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 0, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 2, "total": 2}}}, "attention": {"source": "web", "tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 0, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 2, "total": 2}, "reason": "1 drifted", "command": "scrolls verify --source web"}, "enrichment_by_source": {}, "summary_by_source": {}, "delta": {"first_run": false, "since": "2026-06-16T12:00:00+00:00", "score": {"before": 100, "after": 100, "change": 0}, "tiers": {"full": {"before": 3, "after": 3, "change": 0}, "partial": {"before": 0, "after": 0, "change": 0}, "reference": {"before": 0, "after": 0, "change": 0}}, "drift": {"checked": {"before": 0, "after": 3, "change": 3}, "drifted": {"before": 0, "after": 1, "change": 1}, "error": {"before": 0, "after": 0, "change": 0}, "rotted": {"before": 0, "after": 0, "change": 0}, "unchanged": {"before": 0, "after": 2, "change": 2}, "unverified": {"before": 3, "after": 0, "change": -3}}, "enrichment_stale": {"before": 0, "after": 0, "change": 0}, "summaries_stale": {"before": 0, "after": 0, "change": 0}, "at_risk": {"before": 0, "after": 0, "change": 0}, "conflicts": {"before": 0, "after": 0, "change": 0}}, "issues": 0, "suggested": []}
[exit 0]

$ scrolls maintain --history 2           # the custody trajectory, oldest first
[{"recorded_at": "2026-06-16T12:00:00+00:00", "snapshot": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 0, "unverified": 3, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0}, "delta": {"first_run": true, "since": null, "score": {"before": null, "after": 100, "change": null}}, "headline": "_Custody: 3 scroll(s) · fidelity full 3 · drift unverified 3._"}, {"recorded_at": "2026-06-16T13:00:00+00:00", "snapshot": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 3, "unverified": 0, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 3, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0}, "delta": {"first_run": false, "since": "2026-06-16T12:00:00+00:00", "score": {"before": 100, "after": 100, "change": 0}}, "headline": "_Custody: 3 scroll(s) · fidelity full 3 · drift verified 2, drifted 1._"}]
[exit 0]

$ scrolls maintain --history --trend     # the trajectory's direction in one word
{"trend": {"runs": 2, "since": "2026-06-16T12:00:00+00:00", "score": {"first": 100, "last": 100, "change": 0}, "drift_change": 1, "coverage_change": {"verified": 3, "total": 0}, "stale_change": {"enrichment": 0, "summaries": 0}, "at_risk_change": 0, "conflicts_change": 0, "at_risk_headline": "_At-risk works: 0 (no change over 2 runs)._", "conflicts_headline": "_Conflicts: 0 (no change over 2 runs)._", "posture": "regressing"}, "runs": [{"recorded_at": "2026-06-16T12:00:00+00:00", "snapshot": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 0, "unverified": 3, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0, "at_risk": 0, "conflicts": 0, "archive_mismatched": 0}, "delta": {"first_run": true, "since": null}, "headline": "_Custody: 3 scroll(s) \u00b7 fidelity full 3 \u00b7 drift unverified 3._"}, {"recorded_at": "2026-06-16T13:00:00+00:00", "snapshot": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 3, "unverified": 0, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 3, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0, "at_risk": 0, "conflicts": 0, "archive_mismatched": 0}, "delta": {"first_run": false, "since": "2026-06-16T12:00:00+00:00"}, "headline": "_Custody: 3 scroll(s) \u00b7 fidelity full 3 \u00b7 drift verified 2, drifted 1._"}]}
[exit 0]

$ scrolls maintain --no-recheck          # a pass that found a deleted scroll and a stale category
{"recorded_at": "2026-06-16T14:00:00+00:00", "recheck": {"skipped": true, "checked": 0, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "compiled": {"items": 3, "sources": 2, "categories": 3, "concepts": 2, "tags": 3, "summaries": 0, "clusters": 0, "works": 0, "pages": 9}, "custody": {"score": 67, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 3, "unverified": 0, "unchanged": 3, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 3, "total": 3}, "enrichment_stale": 1, "summaries_stale": 0, "at_risk": 0, "conflicts": 0, "archive_mismatched": 0, "content_duplicate_groups": 0, "content_duplicate_items": 0}, "headline": "_Custody: 3 scroll(s) \u00b7 fidelity full 3 \u00b7 drift verified 3._", "at_risk_headline": "_At-risk works: 0 (no change since last run)._", "conflicts_headline": "_Conflicts: 0 (no change since last run)._", "archive_integrity_headline": null, "enrichment_by_source": {"web": 1}, "summary_by_source": {}, "delta": {"first_run": false, "since": "2026-06-16T13:00:00+00:00", "score": {"before": 100, "after": 67, "change": -33}}, "issues": 1, "suggested": [{"command": "scrolls doctor --fix", "addresses": ["missing_scrolls"]}, {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]}]}
[exit 1]
```

## Getting items in

### `scrolls detect <url>`

Pure URL inspection, no network, nothing stored
(`tests/test_detect.py`). A known source with `"source_id": null` means
the adapter resolves identity at fetch time; unknown hosts fall back to
`"source": "web"`.

```console
$ scrolls detect https://en.wikipedia.org/wiki/SQLite
{"source": "wikipedia", "source_id": "en:SQLite"}
[exit 0]

$ scrolls detect notaurl
{"error": "not an http(s) URL: 'notaurl'"}
[exit 1]
```

### `scrolls add <url>`

Register a URL as an item at stage `detected` — no network. Re-adding
(or adding another URL form of the same item) returns the existing row
with `"created": false` (`test_add_persists_detected_item`,
`test_add_same_video_via_other_url_form_is_deduped`). The URL is
normalized first (ADR 0023): tracking params (`utm_*`, `fbclid`, …),
fragments, host casing, and default ports are stripped before hashing
and storing, so differently decorated links to the same page dedupe to
one item with a clean `url`
(`test_add_strips_tracking_params_before_identity`,
`test_add_stores_the_normalized_url`; `tests/test_urls.py` pins what
normalization may and may not touch).

| Key | Meaning |
| --- | --- |
| `id`, `source`, `source_id`, `url` | identity as detected, URL normalized |
| `stage` | always `detected` for a new row |
| `created` | `false` when the item already existed |

```console
$ scrolls add https://x.com/karpathy/status/3333
{"id": "x:3333", "source": "x", "source_id": "3333", "url": "https://x.com/karpathy/status/3333", "stage": "detected", "created": true}
[exit 0]

$ scrolls add 'https://blog.example.com/post?utm_source=newsletter&fbclid=IwAR0'
{"id": "web:dc65501e6b9a", "source": "web", "source_id": null, "url": "https://blog.example.com/post", "stage": "detected", "created": true}
[exit 0]
```

### `scrolls ingest <url>`

`add` + `fetch` + `classify` + `md` for one URL (network). On success the
payload carries the rendered result; re-ingesting refreshes content but
never replaces an existing category
(`test_ingest_runs_add_fetch_md_in_one_command`,
`test_ingest_existing_url_refreshes_it`).

```console
$ scrolls ingest https://en.wikipedia.org/wiki/SQLite
{"id": "wikipedia:en:SQLite", "source": "wikipedia", "url": "https://en.wikipedia.org/wiki/SQLite", "created": true, "title": "SQLite", "category": "reference", "stage": "rendered", "markdown_path": "scrolls/wikipedia/sqlite.md"}
[exit 0]
```

When the source has no fetch adapter, or the fetch fails, the item is
still registered (stage `detected`) and the same payload gains an
`error` key — on **stdout**, exit 1
(`test_ingest_without_adapter_registers_but_reports_failure`,
`test_ingest_fetch_failure_leaves_item_detected`):

```console
$ scrolls ingest https://x.com/karpathy/status/3333
{"id": "x:3333", "source": "x", "url": "https://x.com/karpathy/status/3333", "created": false, "stage": "detected", "error": "no fetch adapter for source 'x'"}
[exit 1]
```

### `scrolls import bookmarks <path>`

Bulk-import a browser bookmarks export (ADR 0030). `path` is the
`bookmarks.html` every major browser emits (Chrome, Firefox, Safari,
Edge — the Netscape bookmark file format, also spoken by Pinboard-style
services). A missing file, or one without the format's DOCTYPE marker,
is an error envelope on stderr
(`test_import_bookmarks_missing_file_is_an_error` in
`tests/test_cli.py`; `test_non_bookmark_html_raises` in
`tests/test_bookmarks.py`).

Bookmarks are a spine-only archive like Takeout — URL, anchor text,
`ADD_DATE`, folder placement — so items enter at stage `detected` and
`scrolls fetch` enriches them. Unlike Takeout the spine is
heterogeneous: every http(s) URL routes through the same source
detection and URL normalization as `scrolls add`, so a bookmarked
video becomes a `youtube` item, a repo a `github` item, a tweet an
`x` item, and they all dedupe against items the library already has
(`test_imports_bookmarks_as_detected_items`,
`test_x_bookmarks_register_without_an_adapter`,
`test_import_bookmarks_never_overwrites_existing_item`).

Folder ancestry becomes `tags` — the user's own curation, free-form
like `scrolls set`; root containers ("Bookmarks bar", "Other
Bookmarks", …) are browser furniture and excluded, and Firefox's
`TAGS` attribute merges in
(`test_folder_ancestry_becomes_tags`,
`test_root_container_folders_are_not_tags`,
`test_firefox_tags_attribute_merges_with_folder_tags`). The anchor
text seeds `title`, a `<DD>` note seeds `summary`, and `ADD_DATE`
(epoch seconds, or the milli/microsecond variants some exporters
write) becomes `saved_at` — when the page entered the user's life,
never `published_at` (`test_dd_description_seeds_summary`,
`test_millisecond_add_dates_are_normalized`).

Per-bookmark oddities never fail the run — exports accumulate
bookmarklets and smart folders — so the command exits 0 and counts
them instead:

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already existed (id collision is the dedupe working) |
| `bookmarks` | total bookmark entries in the export |
| `repeats` | extra copies of an already-seen URL (earliest `ADD_DATE` wins `saved_at`; folder tags union) |
| `ignored.not_http` | non-http(s) bookmarks (`javascript:` bookmarklets, Firefox `place:` folders, `file:` links) |
| `ignored.no_url` | anchors without an href |

```console
$ scrolls import bookmarks /tmp/scrolls-demo.BgrqMO/bookmarks.html
{"imported": 2, "skipped": 0, "bookmarks": 4, "repeats": 1, "ignored": {"not_http": 1, "no_url": 0}}
[exit 0]

$ scrolls import bookmarks /tmp/scrolls-demo.BgrqMO/bookmarks.html
{"imported": 0, "skipped": 2, "bookmarks": 4, "repeats": 1, "ignored": {"not_http": 1, "no_url": 0}}
[exit 0]
```

### `scrolls import fieldtheory [--root PATH]`

Bulk-import X bookmarks from a local Field Theory archive (default root
`~/.fieldtheory`; ADR 0009) — items arrive directly at stage `fetched`.
Existing items are never overwritten, so re-imports are cheap and safe
(`test_import_fieldtheory_end_to_end`,
`test_import_fieldtheory_is_idempotent`). Per-item success entries are
omitted (imports can cover hundreds of bookmarks); only line-level
failures are detailed, and any failure exits 1
(`test_import_fieldtheory_reports_bad_lines`). A missing archive is an
error envelope on stderr
(`test_import_fieldtheory_missing_archive_is_an_error`).

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already existed (id collision is the dedupe working) |
| `failed` / `failures` | unparseable JSONL lines, with line numbers |

```console
$ scrolls import fieldtheory --root /tmp/scrolls-demo.BgrqMO/fieldtheory
{"imported": 2, "skipped": 0, "failed": 0, "failures": []}
[exit 0]

$ scrolls import fieldtheory --root /tmp/scrolls-demo.BgrqMO/fieldtheory
{"imported": 0, "skipped": 2, "failed": 0, "failures": []}
[exit 0]
```

### `scrolls import google-takeout <path>`

Bulk-import YouTube watch history from a Google Takeout export
(ADR 0029). `path` is the Takeout `.zip`, an extracted directory, or
`watch-history.json` itself — the direct file path is the escape hatch
for localized exports whose directory names are translated. The JSON
export format is required (Takeout's default HTML history is not
parsed); a missing or non-JSON export is an error envelope on stderr
(`test_import_google_takeout_missing_export_is_an_error`,
`tests/test_takeout.py`).

Unlike `import fieldtheory`, Takeout carries no content — only video
URL, title, channel, and watch time — so items enter at stage
`detected` and `scrolls fetch` enriches them through the youtube
adapter, exactly like feed-synced entries. The watch time becomes
`saved_at`; `published_at` stays unset because Takeout doesn't know it
(`test_import_google_takeout_end_to_end`). Existing items are never
overwritten (`test_import_google_takeout_is_idempotent`,
`test_import_google_takeout_never_overwrites_existing_item`).

Per-entry oddities never fail the run — every watch history contains
ads, deleted videos, and community-post visits, so the command exits 0
and counts them instead:

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already existed (id collision is the dedupe working) |
| `events` | total watch events in the export |
| `repeats` | extra watches of an already-seen video (earliest watch wins `saved_at`) |
| `ignored.ads` | entries marked "From Google Ads" |
| `ignored.no_url` | entries with no URL (deleted/private videos) |
| `ignored.not_video` | YouTube URLs that aren't videos/playlists (posts, channel visits) |

```console
$ scrolls import google-takeout /tmp/scrolls-demo.BgrqMO/takeout.zip
{"imported": 1, "skipped": 0, "events": 4, "repeats": 1, "ignored": {"ads": 1, "no_url": 1, "not_video": 0}}
[exit 0]

$ scrolls import google-takeout /tmp/scrolls-demo.BgrqMO/takeout.zip
{"imported": 0, "skipped": 1, "events": 4, "repeats": 1, "ignored": {"ads": 1, "no_url": 1, "not_video": 0}}
[exit 0]
```

### `scrolls import pocket <path>`

Bulk-import a Pocket data export (ADR 0074) — the CSV
(`title,url,time_added,tags,status`) Mozilla mailed users when Pocket
shut down in 2025. `path` is the export `.zip` (large accounts split
across `part_*.csv`), a directory of CSV parts, or a single `.csv`. A
missing path, a zip/directory with no CSV, or a CSV without a `url`
column is an error envelope on stderr
(`test_import_pocket_missing_file_is_an_error` in `tests/test_cli.py`;
`test_csv_without_a_url_column_raises` in `tests/test_pocket.py`).

Pocket is a heterogeneous spine-only archive like browser bookmarks
(ADR 0030), so items enter at stage `detected` and reuse the same spine:
every URL routes through the same source detection and normalization as
`scrolls add`, so a saved video becomes a `youtube` item and a repo a
`github` item, all deduping against the library
(`test_imports_pocket_rows_as_detected_items`,
`test_import_pocket_never_overwrites_existing_item`). `time_added` (epoch
seconds) becomes `saved_at` — when the page entered the user's life,
never `published_at`. Pipe-delimited Pocket `tags` become `tags` (the
user's own curation, like bookmark folders), and a title equal to the
URL — Pocket's "no title" marker — is dropped so fetch fills the real one
(both are pinned by `test_imports_pocket_rows_as_detected_items`).
Columns are read by header name, so the importer also takes any CSV
carrying a `url` column.

Per-row oddities never fail the run — exports carry blank-URL lines and
the occasional non-http save — so the command exits 0 and counts them
instead:

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already existed (id collision is the dedupe working) |
| `rows` | total CSV data rows across the export's parts |
| `repeats` | extra copies of an already-seen URL (earliest `time_added` wins `saved_at`; tags union) |
| `ignored.no_url` | rows with a blank `url` field |
| `ignored.not_http` | non-http(s) saves (`mailto:`, bookmarklets, …) |
| `status` | unread/archive split across the detected save rows |

```console
$ scrolls import pocket /tmp/scrolls-demo.BgrqMO/pocket.csv
{"imported": 3, "skipped": 0, "rows": 4, "repeats": 0, "ignored": {"no_url": 1, "not_http": 0}, "status": {"unread": 2, "archive": 1}}
[exit 0]

$ scrolls import pocket /tmp/scrolls-demo.BgrqMO/pocket.csv
{"imported": 0, "skipped": 3, "rows": 4, "repeats": 0, "ignored": {"no_url": 1, "not_http": 0}, "status": {"unread": 2, "archive": 1}}
[exit 0]
```

### `scrolls import opml <path>`

Import feed subscriptions from an OPML file (ADR 0076) — the universal
feed-list interchange format every RSS reader (Feedly, Inoreader,
NetNewsWire, Reeder, The Old Reader, …) exports. This is the bulk sibling
of single-feed `scrolls follow`, and the one import that produces
**subscriptions** rather than items: an OPML file lists feeds, not saved
pages, so each feed outline becomes a row in the same `subscriptions`
table `scrolls follow` writes, and the **first `scrolls sync` discovers
each feed's entries**. A missing path, malformed XML, or a document whose
root is not `<opml>` (an RSS feed passed by mistake) is an error envelope
on stderr (`test_import_opml_missing_file_is_an_error` in
`tests/test_cli.py`; `test_non_opml_document_raises` in
`tests/test_opml.py`).

Unlike `scrolls follow`, which fetches a feed once to validate it, OPML
import is **network-free** like the other bulk imports: an export can hold
hundreds of feeds and the `xmlUrl` is declared to be a feed by the
exporting reader, so it is trusted on import and a dead feed surfaces only
on its first sync, failing its own subscription and never the batch
(`test_subscriptions_carry_no_validators_so_first_sync_sees_entries`). A
feed imported here gets the same subscription id `scrolls follow` of that
feed URL would mint, so an import and a manual follow dedupe on purpose
(`test_import_opml_dedupes_against_a_prior_follow`). The whole outline
tree is walked, so feeds nested in folders and top-level feeds alike
surface; folder grouping is display metadata in the source reader and is
dropped — subscriptions carry no tags
(`test_imports_opml_outlines_as_subscriptions`).

Per-outline oddities never fail the run — exports carry folders and the
occasional non-http feed — so the command exits 0 and counts them:

| Key | Meaning |
| --- | --- |
| `imported` | new subscriptions inserted |
| `skipped` | already followed (id collision is the dedupe working) |
| `feeds` | http(s) feed outlines found (duplicates included; `imported + skipped == feeds - repeats`) |
| `repeats` | extra copies of a feed URL already seen in the file |
| `ignored.not_http` | outlines with a non-http(s) `xmlUrl` (`file:`, `feed:`), counted separately from `feeds` |

```console
$ scrolls import opml /tmp/scrolls-demo.BgrqMO/subscriptions.opml
{"imported": 3, "skipped": 0, "feeds": 4, "repeats": 1, "ignored": {"not_http": 1}}
[exit 0]

$ scrolls import opml /tmp/scrolls-demo.BgrqMO/subscriptions.opml
{"imported": 0, "skipped": 3, "feeds": 4, "repeats": 1, "ignored": {"not_http": 1}}
[exit 0]
```

### `scrolls import items <path>`

Import items from a Scrolls JSONL export (ADR 0082) — the inverse of
`scrolls export items`, and the way a backed-up, migrated, or merged-in
library is restored. `path` is a `.jsonl` file `scrolls export items`
wrote: one JSON object per line, each a complete item record. A missing
file, or any malformed line — invalid JSON, a non-object, or a record
without the required identity fields (`id`, `source`, `url`, `saved_at`)
— is an error envelope on stderr naming the line, so a corrupt backup
fails loudly instead of restoring silently incomplete
(`test_import_items_missing_file_is_an_error`,
`test_import_items_malformed_line_is_an_error` in `tests/test_cli.py`;
`test_load_malformed_json_line_raises_naming_the_line` in
`tests/test_items_export.py`). Unknown keys are tolerated, so an export
written by a newer schema still loads here
(`test_load_ignores_unknown_keys`).

Unlike the spine imports (bookmarks, Pocket), this restores **every**
field — extracted text, links, media refs, provenance, content hash,
stage — because the export carries them. It restores the index rows only;
the derived artifacts rebuild from those rows — run `scrolls doctor --fix`
to rewrite any missing scroll file and the FTS index, then `scrolls kb`
to recompile the library. That full path is a *verified* round-trip, not
just an assertion: exporting a real library and rebuilding it in a fresh one
via `import items` → `doctor --fix` → `kb` reproduces the item rows, the
re-export JSONL, the rendered scrolls, the compiled `library/`, and search
results byte-for-byte, and the rebuilt library passes its own custody audit
(`tests/test_roundtrip.py`, ADR 0099); the one thing a JSONL backup cannot
carry is captured media *blobs*, which `doctor` then reports as missing for
`scrolls media` to re-download. Existing items are never overwritten
(`INSERT OR IGNORE` by id), so a re-import is cheap and a partial restore
resumes safely (`test_import_items_is_idempotent`,
`test_import_items_never_overwrites_existing_item`).

**A skip is not opaque — a conflict is surfaced, never silently swallowed.**
Because the held copy is never overwritten, the question that matters for
custody is *why* a row was skipped: an idempotent re-import of the **same**
captured content, or an incoming copy that **disagrees** with what we hold.
`import items` partitions every skip on the `content_hash` — the captured-content
fingerprint the verify ledger itself drifts on (`scrolls verify`) — into
`unchanged` (same content, a true no-op) and `conflict` (a different capture of
the same id: e.g. another library's bundle of a source that has since drifted).
The held copy is still kept — raw is sacred, a conflict is a *recorded, surfaced*
event, not an overwrite (vision §2.4; the adopted reconcile posture —
*detect and surface, don't silently rewrite*, `docs/reconciliation.md`). The
diverging ids ride the structured `conflicts` list (sorted, deduped, uncapped —
the completeness contract) **and** a loud stderr warning naming them (bounded
`(+N more)`), so a divergence is never lost in an opaque `skipped` count. A
difference in only a *derived* field (title, category, an enrichment tag) does
not change `content_hash` and is `unchanged`, not a conflict
(`test_import_items_title_only_edit_is_unchanged_not_a_conflict`). The shared
`merge_item` primitive and `_merge_items`/`_warn_conflicts` are the home for this
partition, ready for the bundle import to reuse
(`test_import_items_surfaces_a_content_conflict`,
`test_import_items_partitions_a_mixed_batch`,
`test_merge_item_classifies_the_insert_outcome`).

**A conflict is also *recorded* as a custody event** (roadmap H274, ADR 0104),
not just printed: each diverging id gets a typed `conflict` event appended to the
ledger (`prior_hash` = the held copy we keep, `observed_hash` = the incoming
capture that disagreed, stamped at import time), so the divergence is queryable
later via `scrolls history <id> --status conflict` instead of being re-detected
from scratch on every re-import. It is a **distinct** axis, never a drift posture:
`custody.latest_events` reads only the verify verdicts, so a conflict leaves
`doctor`'s `custody.drift` / `list --drift` / the custody headlines untouched (a
peer disagreeing is no evidence the live *source* moved — the M2 honesty). A clean
re-import records nothing (`test_import_items_records_a_conflict_as_a_custody_event`,
`test_import_items_clean_reimport_records_no_event`).

**`--accept-incoming` *adopts* the diverging copy** (roadmap H278, ADR 0106) — the
content-bearing resolution `reconcile` cannot do (at `reconcile` time the incoming
content is gone, only its hash was recorded; the import path has it in hand). On a
conflict it **replaces** the held copy with the incoming one and records a
`superseded` conflict-axis event — the *first import-path write that changes a held
capture*. It stays custody-safe: the prior copy is **archived first** (recoverable
via `scrolls archive show`, never destroyed — custody §2.4), and the adoption clears
the conflict across `doctor`/`status`/the `_Conflicts:_` line (both the status gate —
the latest axis event is now `superseded` — and the hash gate — the held copy *is*
the incoming). Opt-in (without the flag a conflict is surfaced and the held copy
kept), **idempotent** by construction (a re-import of an already-adopted capture is
`unchanged` — the held copy now equals the incoming), and loud on stderr (a held
copy was replaced). The adopted ids ride the structured `adopted` list
(`test_import_items_accept_incoming_adopts_and_archives_the_prior`,
`test_import_items_accept_incoming_clears_the_conflict_aggregate`,
`test_import_items_accept_incoming_is_idempotent`).

**A content duplicate *this* import added is counted** (roadmap H353). Beside the
`conflict` *divergence* notice rides its content-identity twin: `content_duplicates`
counts the freshly-inserted rows that landed **byte-identical** to a *distinct* held
copy — or to another row in the same import (the same captured `content_hash` under
two ids: a mirror, a cross-post, one work saved twice). It is the import-time, **point-
in-time** counterpart of `doctor`'s whole-library standing `custody.content_duplicates`
count: where `doctor` reports the redundancy the library holds *now*, this reports the
redundancy *this run introduced*. **Report-only** (the H325 discipline — two faithful
copies are a redundancy fact, never a defect): unlike `conflict` it rides **no stderr
warning** and never touches the exit code, and it is **idempotent** — scoped to the
freshly-inserted ids, so a clean re-import of an already-held copy reports `0` even
while the duplicate group still stands (that standing redundancy is `doctor`'s job). A
non-zero count points an operator at the existing prune flow (`list --content-duplicate`,
`scrolls doctor`); a NULL-hash reference-only row fingerprints nothing and never counts
(`test_import_items_reports_a_content_duplicate_against_a_held_copy`,
`test_import_items_reports_content_duplicates_within_the_same_import`,
`test_import_items_content_duplicates_is_zero_on_an_idempotent_reimport`,
`test_import_items_content_duplicates_skips_null_hash_references`).

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already present and not inserted (`== unchanged + conflict`) |
| `unchanged` | skipped: held copy has the same `content_hash` (idempotent) |
| `conflict` | skipped: held copy has a **different** `content_hash` (divergence surfaced, held copy kept) |
| `conflicts` | the distinct ids whose held copy diverged and was *kept* (sorted, uncapped) |
| `adopted` | the distinct ids whose held copy was *replaced* by the incoming under `--accept-incoming` (prior archived); `[]` otherwise |
| `content_duplicates` | how many freshly-imported rows landed byte-identical to a distinct held copy (or to another row in the same import) — report-only, idempotent; `0` when this import added no redundant copy |
| `items` | item records read from the file (blank lines excluded) |

```console
$ scrolls import items /tmp/scrolls-demo.BgrqMO/library.jsonl
{"imported": 6, "skipped": 0, "unchanged": 0, "conflict": 0, "adopted": [], "conflicts": [], "content_duplicates": 0, "items": 6}
[exit 0]

$ scrolls import items /tmp/scrolls-demo.BgrqMO/library.jsonl
{"imported": 0, "skipped": 6, "unchanged": 6, "conflict": 0, "adopted": [], "conflicts": [], "content_duplicates": 0, "items": 6}
[exit 0]

# an incoming copy of a held id with different captured content — surfaced,
# not silently dropped; the held copy is kept (custody §2.4)
$ scrolls import items /tmp/diverged.jsonl
{"warning": "1 item(s) in this import conflict with a held copy (different content — kept the held copy, not overwritten): `github:sqlite/sqlite`"}   # stderr
{"imported": 0, "skipped": 1, "unchanged": 0, "conflict": 1, "adopted": [], "conflicts": ["github:sqlite/sqlite"], "content_duplicates": 0, "items": 1}
[exit 0]

# adopt the diverging copy instead — the held copy is replaced, the prior archived
$ scrolls import items /tmp/diverged.jsonl --accept-incoming
{"warning": "1 held copy(ies) replaced by the incoming capture (accept-incoming — prior archived, recoverable via `scrolls archive show`): `github:sqlite/sqlite`"}   # stderr
{"imported": 0, "skipped": 0, "unchanged": 0, "conflict": 0, "adopted": ["github:sqlite/sqlite"], "conflicts": [], "content_duplicates": 0, "items": 1}
[exit 0]

# a mirror saved twice: the second row lands byte-identical to the held copy →
# one content duplicate (report-only, no warning — run `list --content-duplicate` to prune)
$ scrolls import items /tmp/mirror.jsonl
{"imported": 1, "skipped": 0, "unchanged": 0, "conflict": 0, "adopted": [], "conflicts": [], "content_duplicates": 1, "items": 1}
[exit 0]
```

### `scrolls export opml`

Export the library's feed subscriptions as an OPML 2.0 document (ADR 0077)
— the inverse of `scrolls import opml`, so the feeds you curate in Scrolls
can move to another reader, get backed up, or sync a second device. The
OPML document **is** the artifact, so it prints raw on stdout (the
`scrolls context` exception to the JSON-on-stdout rule) — redirect it to a
file or pipe it: `scrolls export opml > feeds.opml`. There is no path
argument; the shell owns redirection, so the command never writes to or
overwrites a file itself.

The export is flat — subscriptions carry no folder grouping (the import
dropped it), so it honestly emits a flat `<body>` rather than inventing a
hierarchy. Each subscription is one `<outline type="rss" text=… title=…
xmlUrl=…>` in `scrolls follow` listing order; a subscription with no title
labels itself by its feed URL (OPML requires a `text`), and attribute
values are XML-escaped, so a feed URL with `&` survives a re-import. The
round-trip is the contract: an export re-imports to the same feeds (the
import skips them as already-followed —
`test_export_opml_round_trips_through_import` in `tests/test_cli.py`,
`test_export_then_import_round_trips` in `tests/test_opml.py`). An empty
library produces a valid empty OPML, not an error
(`test_export_opml_empty_library_is_valid`).

```console
$ scrolls export opml
<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <head>
    <title>Scrolls subscriptions</title>
  </head>
  <body>
    <outline type="rss" text="Simon Willison" title="Simon Willison" xmlUrl="https://simonwillison.net/atom/everything/" />
    <outline type="rss" text="Julia Evans" title="Julia Evans" xmlUrl="https://jvns.ca/atom.xml" />
  </body>
</opml>
[exit 0]
```

### `scrolls export bookmarks`

Export the library's items as a Netscape-format bookmark file (ADR 0079)
— the inverse of `scrolls import bookmarks`, so a curated Scrolls library
can move back into a browser, a read-later tool, or a backup. The bookmark
file **is** the artifact, so it prints raw on stdout (the same exception
`scrolls export opml` makes to the JSON-on-stdout rule) — redirect or pipe
it: `scrolls export bookmarks > bookmarks.html`. There is no path argument;
the shell owns redirection.

By default the whole library is exported. Three optional filters — the
same durable item-property facets `scrolls list` filters by — scope it to
a slice and AND together: `--source` (e.g. `--source github`), `--category`
(an empty value selects unclassified items), and `--tag`
(case-insensitive). So `scrolls export bookmarks --source github >
repos.html` exports just the github items. `--stage` and `--concept` are
deliberately not offered (transient pipeline state and a derived KB lens,
not how a bookmark set is curated).

The export carries each item's *spine* — URL, title, save date, and tags —
because that is all a bookmark file holds; the extracted content stays in
the Markdown scrolls. Each item is one `<DT><A HREF=… ADD_DATE=… TAGS=…>`:
`saved_at` becomes the `ADD_DATE` epoch (via `dates.iso_to_epoch`, the
inverse of the importer's epoch reader), `tags` become a comma-joined
`TAGS` attribute (flat, not a folder tree — a browser ignores it but keeps
the bookmark, and Pinboard-style tools read it), and an item with no title
labels itself by its URL (a bookmark needs anchor text, the same rule
`export opml` uses). Items export in `scrolls list` order (oldest save
first), all of them. Text and attribute values are HTML-escaped, so a title
with `<`/`&` or a URL with `&` survives a re-import. The round-trip is the
contract: an export re-imports to the same items (the import skips them as
already-registered —
`test_export_bookmarks_round_trips_through_import` in `tests/test_cli.py`,
`test_export_round_trips_through_import` in `tests/test_bookmarks.py`). An
empty library produces a valid empty document, not an error
(`test_export_bookmarks_empty_library_is_valid`).

```console
$ scrolls export bookmarks
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file. DO NOT EDIT! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Scrolls bookmarks</TITLE>
<H1>Scrolls bookmarks</H1>
<DL><p>
    <DT><A HREF="https://en.wikipedia.org/wiki/SQLite" ADD_DATE="1781254800" TAGS="databases">SQLite</A>
    <DT><A HREF="https://www.youtube.com/watch?v=abc123xyz00" ADD_DATE="1781260200" TAGS="databases,search">How SQLite FTS Works</A>
</DL><p>
[exit 0]
```

### `scrolls export items [--source S] [--category C] [--tag T] [--fidelity T] [--drift P] [--content-duplicate]`

Export the library's items as a lossless JSON Lines stream (ADR 0082) —
the inverse of `scrolls import items`, and the way a whole library is
backed up, migrated to another machine, or merged into another. Where
`export bookmarks` and `export opml` round-trip against external tools and
so carry only a spine those formats can hold, this round-trips against
Scrolls' own model, so it carries **every** field: extracted text, links,
media refs, provenance, content hash, `markdown_path` (stored relative, so
it is portable), and stage. The stream **is** the artifact, so it prints
raw on stdout (the same exception `export opml`/`export bookmarks` make to
the JSON-on-stdout rule) — redirect or pipe it:
`scrolls export items > library.jsonl`. There is no path argument; the
shell owns redirection.

Each line is one complete item as a JSON object, in dataclass field order
(a stable line for diffs), in `scrolls list` order (oldest save first). The
same three durable item-property filters `export bookmarks` offers scope
the export and AND together: `--source`, `--category` (an empty value
selects unclassified items), and `--tag` (case-insensitive). So
`scrolls export items --source arxiv > papers.jsonl` exports just the arXiv
items (`test_export_items_source_filter_scopes_the_export` in
`tests/test_cli.py`).

**Custody scope (`--fidelity` / `--drift`).** Two more filters scope the
backup by the per-item custody axes — the backup-path sibling of
`export bundle --fidelity`/`--drift` (the shareable briefing). `--fidelity`
(`full`/`partial`/`reference`) backs up only the holdings at one
custody-fidelity tier (ADR 0097), reading no ledger — the honest holdings
fact; `--drift` (`verified`/`unverified`/`drifted`/`rotted`/`error`) backs up
only the rows at one custody drift posture, from the verify ledger. Both fold
the same `list_items` sieve `scrolls list --fidelity`/`--drift` use, so the
backup is the **byte-identical subset** of the whole-library backup for those
rows (`dump_items_export` over the kept rows, in saved order;
`test_export_items_fidelity_is_byte_identical_to_the_unscoped_subset`). They
AND with each other and every durable filter (`test_export_items_custody_axes_and_together`),
so `scrolls export items --fidelity full > rederivable.jsonl` backs up only
the holdings you can re-derive offline, and `--drift drifted` ships only the
moved rows for a recapture handoff. The lossless round-trip holds over the
scope: `import items` of a custody-scoped backup re-holds **exactly** the
exported rows, no leakage of the filtered-out tiers
(`test_export_items_custody_scoped_backup_round_trips_through_import`). Both
are a closed vocabulary — an unknown value is exit 2 (argparse `choices`),
never a silent empty backup
(`test_export_items_rejects_an_unknown_fidelity_tier`); the `_cmd_export_items`
programmatic path surfaces the `list_items` `ValueError` as exit 1
(`test_cmd_export_items_unknown_tier_on_the_programmatic_path_is_exit_1`).

**Content-identity scope (`--content-duplicate`).** A boolean flag that backs up
only the held items the library holds a **byte-identical copy of under another
id** — the content-duplicate set (the content-identity custody shape; the same
bytes saved twice, a mirror or cross-post). It folds the same whole-library
sibling sieve `scrolls list --content-duplicate` uses (the `content_duplicate_index`
fold), so the backup is the byte-identical subset enumerating exactly the held
members of `scrolls doctor`'s `custody.content_duplicates` groups — "ship only
the redundant copies so a recipient can dedup". The sibling scope is
whole-library, so `--source S --content-duplicate` backs up S's items that have a
byte-identical sibling *anywhere* held (the sibling may live in another source),
and the flag ANDs with `--fidelity`/`--drift`
(`test_export_items_content_duplicate_composes_with_source`). It is **report-only**
— it names what an operator may dedup, never merges. The lossless round-trip
carries the redundancy: `import items` of a content-duplicate backup re-holds the
pair and the rebuilt library's `doctor.custody.content_duplicates` re-flags the
same groups (`test_export_items_content_duplicate_round_trips_and_reflags`;
`content_hash` travels, the H336 guarantee).

The round-trip is the contract: an export re-imports to the same items,
every field intact — into a fresh library it is a faithful restore, into
the same one the import skips them as already-present
(`test_export_items_round_trips_through_import` in `tests/test_cli.py`,
`test_dump_then_load_is_a_lossless_round_trip` in
`tests/test_items_export.py`). An empty library produces an empty document
(zero lines), not an error (`test_export_items_empty_library_is_valid`).

```console
$ scrolls export items --source arxiv
{"id": "arxiv:1706.03762", "source": "arxiv", "url": "https://arxiv.org/abs/1706.03762", "saved_at": "2026-06-12T08:00:00+00:00", "source_id": "1706.03762", "canonical_url": "http://arxiv.org/abs/1706.03762v7", "title": "Attention Is All You Need", "author": "Ashish Vaswani et al.", "published_at": "2017-06-12T17:57:34+00:00", "raw_text": "<the raw Atom entry>", "extracted_text": "The dominant sequence transduction models…", "summary": "We propose the Transformer.", "category": "paper", "domain": null, "tags": ["cs.CL", "cs.LG"], "concepts": [], "links": ["https://arxiv.org/pdf/1706.03762"], "media": [{"type": "pdf", "url": "https://arxiv.org/pdf/1706.03762", "path": "media/arxiv/1706-03762-1.pdf"}], "content_hash": "sha256:6d2e1066…", "markdown_path": "scrolls/arxiv/attention-is-all-you-need.md", "provenance": {"adapter": "arxiv", "fetched_at": "2026-06-12T08:00:05+00:00", "extraction_method": "arxiv-atom+pypdf"}, "stage": "rendered"}
[exit 0]
```

### `scrolls export events [--source S] [--category C] [--tag T] [--since ISO] [--fidelity T] [--drift P]`

Export the verify ledger (`custody_events`) as a lossless JSON Lines stream —
**whole-library portable custody** (roadmap H72), the custody sibling of
`export items`. Where `export items` backs up the library's *items*, this backs
up its *custody record* — every recorded `verify` check — so a machine that has
neither can reconstruct both: `scrolls export items > library.jsonl` and
`scrolls export events > ledger.jsonl`, then `import items` followed by
`import events`. It is the backup-path counterpart of `export bundle`'s H67
portable custody (which carries a *scoped* topic's ledger inside a readable
briefing); this is the *whole* ledger as a machine stream.

Each line is one custody event as a JSON object — the full row
(`item_id`/`checked_at`/`status`/`prior_hash`/`observed_hash`/`detail`), the
`item_id` included because the stream spans many items (unlike `scrolls
history`, scoped to one). The stream **is** the artifact, so it prints raw on
stdout (the `export items` exception to the JSON-on-stdout rule); there is no
path argument. The same three durable item-property filters `export items`
offers scope it and AND together — `--source`, `--category` (empty selects
unclassified), `--tag` — by resolving the matching items and exporting *their*
events, so a slice's custody travels with the slice
(`test_export_events_source_filter_scopes_to_the_items_facet`).

`--since <ISO>` makes it an **incremental backup** (roadmap H75): it streams
only the events `checked_at >= <ISO>`, so a maintenance worker that backs up
custody after each sweep can append only what is new rather than re-exporting
the whole ledger every time. The boundary is normalized through the one
`checked_at` vocabulary (ADR 0024, a `Z` suffix / offset / date-only all
compare correctly) and is **inclusive**; it composes with the facets (window
then scope — `test_export_events_since_composes_with_the_source_facet`). Because
`import events` dedups on the content 5-tuple, the **union** of a full backup
and overlapping incremental ones re-imports idempotently — every duplicate row
is skipped (`test_export_events_since_union_reimports_idempotently`). An empty
window is a valid empty document, never an error
(`test_export_events_since_empty_window_is_an_empty_document`); a malformed
`--since` is a loud usage error, exit 2
(`test_export_events_malformed_since_is_a_usage_error`).

**Custody scope (`--fidelity` / `--drift`).** Two more filters scope the ledger
backup by the per-item custody axes (roadmap H260) — the ledger-backup sibling of
`export items --fidelity`/`--drift` (the item backup, H259). Unlike the item
backup they are an **item-set sieve**, not a per-row filter: they narrow the
*item resolution* — the same `list_items` sieve `scrolls list --fidelity`/`--drift`
fold — then the **whole ledger** of the selected items travels, exactly the way
`--source` already scopes events by item. `--fidelity`
(`full`/`partial`/`reference`) keeps only the custody history of holdings at one
fidelity tier (ADR 0097, no ledger read); `--drift`
(`verified`/`unverified`/`drifted`/`rotted`/`error`) keeps only the history of
the items **currently** at one drift posture. The current-posture semantics are
the load-bearing choice: `--drift drifted` ships a moved item's *entire* custody
record — including its earlier `unchanged` checks, not just the `drifted` row
(`test_export_events_drift_is_the_item_set_sieve_carrying_the_whole_ledger`) — so
a recapture handoff carries the full proof of *when* the source moved, not a
single event. Both axes AND with each other, with `--since` (which still windows
the surviving event rows — item-set sieve, then time window), and with the
durable filters (`test_export_events_custody_axes_and_together`,
`test_export_events_custody_scope_composes_with_since`). The round-trip holds
over the scope: `import events` of a drift-scoped backup restores **exactly** the
moved items' history, no leakage of the filtered-out items' events
(`test_export_events_custody_scoped_backup_round_trips_into_a_fresh_library`).
Both are a closed vocabulary — an unknown value is exit 2 (argparse `choices`),
never a silent empty backup (`test_export_events_rejects_an_unknown_fidelity_tier`);
the `_cmd_export_events` programmatic path surfaces the `list_items` `ValueError`
as exit 1 (`test_cmd_export_events_unknown_tier_on_the_programmatic_path_is_exit_1`).

An empty (or pre-`init`) library produces an empty document, never an error
(`test_export_events_empty_library_is_valid`,
`test_export_events_before_init_is_an_empty_document`). Restore with
`scrolls import events`.

```console
$ scrolls export events --source arxiv
{"item_id": "arxiv:1706.03762", "checked_at": "2026-06-14T00:00:00+00:00", "status": "drifted", "prior_hash": "sha256:6d2e1066", "observed_hash": "sha256:a1b2c3d4", "detail": null}
[exit 0]

$ scrolls export events --since 2026-06-16 >> ledger.jsonl   # append only checks since the last sweep
[exit 0]

$ scrolls export events --drift drifted > moved.jsonl        # the full custody history of the moved items, for a recapture handoff
[exit 0]
```

### `scrolls export archive [--id <id> | --source <S>] [--fidelity T] [--drift P] [--since <ISO>]`

Export the **prior-content archive** (`item_archive`, ADR 0106) as a lossless
JSON Lines stream — the **portable recovery store** (roadmap H280), the third
member of the lossless backup family beside `export items` (the holdings) and
`export events` (the custody ledger). When an `import … --accept-incoming` adopts
a peer's diverging capture, the superseded prior is archived first (recoverable
via `scrolls archive show`); but that archive is a *local* store. A library
rebuilt from `import items` + `import events` reads *that* an adoption happened
(the `superseded` event travels in the ledger) yet cannot recover the prior
*bytes*. This carries them, so `scrolls archive show` works on the rebuilt
library.

Each line is one archived prior as a JSON object — `item_id`, `archived_at`,
`prior_hash` (the archived copy's hash), `superseded_by` (the incoming hash that
replaced it), and the nested **model-complete `snapshot`** (the same lossless
`item_to_dict` shape `export items` writes), so recovery round-trips through the
importer the library already trusts. The stream **is** the artifact, so it prints
raw on stdout (the `export items` exception to the JSON-on-stdout rule); there is
no path argument.

Two ways to pick the item set whose recovery store travels. `--id <ref>` names
**one precise item** (an id, or a URL resolved to the id `add` would mint — the
`archive list --id` precedent). The **library-filter group** `--source` /
`--fidelity` / `--drift` is an **item-set sieve** that ANDs together: it resolves
the in-scope *held* items (the same `list --source`/`--fidelity`/`--drift`
primitive `export events` folds, roadmap H260/H301/H302), then ships their *whole*
archived history.

- `--source <S>` — *one source's* held items' priors (e.g. `--source web`), the
  `export events --source` analogue (roadmap H301).
- `--fidelity {full|partial|reference}` — the recovery store of items held at one
  custody-fidelity tier (ADR 0097); e.g. `--fidelity full` backs up "the recovery
  history of holdings I can re-derive offline" (roadmap H302, the holdings-axis
  companion of `--drift`).
- `--drift {verified|unverified|drifted|rotted|error}` — the recovery store of
  items *currently* at one drift posture (from the verify ledger); e.g. `--drift
  drifted` backs up "the recoverable priors of the moved items for a recapture
  handoff" — the items' *whole* archive (their earlier priors included), exactly as
  `--source` scopes by item, **not** a per-prior filter (roadmap H302).

`--since <ISO>` is a third, **orthogonal** axis — a *time* window on
`archived_at`, **not** an item-set sieve — so it is **not** part of that mutual
exclusion: it composes with whichever item selector ran (`--id`, the
library-filter group, or none), narrowing the resolved priors to those archived
**at/after** the boundary (inclusive `>=`). This is the **incremental recovery
backup since the last sweep** — the `export events --since` analogue on the
archive axis (roadmap H303). Re-importing the overlapping union of a full backup
and a later `--since` increment stays idempotent: `import archive` dedups by
`(item_id, prior_hash)`, so the increment adds only genuinely new priors
(`test_incremental_export_archive_re_imports_idempotently_over_the_full_backup`).
The boundary is normalized through the shared `parse_since` validator (a `Z`
suffix, an offset, or a date-only `2026-06-15` all accepted); a non-timestamp
value is a loud usage error (exit 2, stderr JSON, validated before any item
resolution — never a silently-empty backup that could mask a typo;
`test_export_archive_rejects_a_malformed_since`), while a window after every prior
is a valid empty document
(`test_export_archive_empty_since_window_is_a_valid_empty_document`).

The whole library's recovery store travels when no scope is given (the backup
case). `--id` selects one precise item while the library-filter group selects a
slice of the held library — two different selection modes — so combining `--id`
with any of `--source`/`--fidelity`/`--drift` is a loud usage error (exit 2,
stderr JSON; `test_export_archive_rejects_both_id_and_source`,
`test_export_archive_rejects_id_combined_with_custody_filters`). An unknown
`--fidelity`/`--drift` value is a closed-vocabulary usage error (exit 2;
`test_export_archive_rejects_an_unknown_fidelity_tier`). An empty (or pre-`init`)
library — an `--id` with no archived prior, a `--source` with no held items, or no
holding at the custody value — produces an empty document, never an error
(`test_export_archive_empty_library_is_valid`,
`test_export_archive_unmatched_id_is_an_empty_document`,
`test_export_archive_custody_axes_and_together`); a malformed URL `--id` is a loud
error (`test_export_archive_bad_url_id_is_a_usage_error`). Restore with
`scrolls import archive`.

The records are ordered content-deterministically (by `archived_at`, then
`item_id`, then `prior_hash`), independent of the per-library autoincrement id, so
a re-export after `import archive` reproduces the stream byte-for-byte — the
lossless-round-trip reach of the recovery store. The whole-bundle counterpart is
`scrolls export bundle --with-archive`, which carries the same records in a third
fenced block beside the items and events blocks.

```console
$ scrolls export archive
{"item_id": "wikipedia:en:SQLite", "archived_at": "2026-06-22T00:00:00+00:00", "prior_hash": "sha256:held", "superseded_by": "sha256:moved", "snapshot": {"id": "wikipedia:en:SQLite", "...": "..."}}
[exit 0]

$ scrolls export archive --id wikipedia:en:SQLite > sqlite-priors.jsonl   # one item's recovery store
[exit 0]

$ scrolls export archive --source web > web-priors.jsonl   # one source's recovery store
[exit 0]

$ scrolls export archive --drift drifted > moved-priors.jsonl   # the recoverable priors of the moved items, for a recapture handoff
[exit 0]

$ scrolls export archive --since 2026-06-22 > priors-since-last-sweep.jsonl   # incremental: only priors archived on/after the boundary
[exit 0]
```

### `scrolls export bundle <query> [--source S] [--category C] [--stage ST] [--tag T] [--concept K] [--fidelity T] [--drift P] [--strength {strong|moderate|weak}] [--content-duplicate] [--format markdown|html] [--with-archive]`

A scoped, self-contained **custody bundle** for a topic — one Markdown file
an agent can hand to a person or another library (ADR 0103, MVP M4,
`tests/test_bundle.py`). Two layers in one file: a readable **briefing**
(title + scope, then a one-line scope **custody headline** — `N scroll(s)`,
the fidelity-tier counts, and the drift-posture counts across the *whole*
bundle, so a reader gauges "how custody stands" without scanning every entry
(roadmap H45); its totals equal the per-scroll entries and `doctor`'s `custody`
aggregate for the same scope by construction, the bundle-level counterpart of
`status`'s custody headline — `test_scope_custody_headline_totals_equal_the_entries_and_doctor`).
For a **multi-source** scope a per-source **breakdown** follows under the headline
(`_By source:_`, one bullet per source with that source's fidelity/drift counts
and recheck `coverage V/T`, roadmap H141/H158), so a recipient of a shared briefing
sees *which* source's custody is weakest — and least checked — within the scope
without re-deriving it. It is built from the same
`custody_counts_by_source` `doctor`'s `custody.by_source` reports, so it sums to
the scope headline by construction and equals that map for the in-bundle items
(`test_bundle_per_source_breakdown_converges_with_doctor_by_source`); a
single-source or empty scope omits it (the whole-scope headline already says
everything). Like the headline it is a *derived read view outside* the
`@generated` JSONL fence, so the lossless round-trip is untouched
(`test_per_source_breakdown_preserves_the_round_trip`). Then one entry per
in-scope scroll naming its id, source, custody **fidelity**
tier, capture timestamp, link, content hash, a capped excerpt, its custody
**drift posture** from the verify ledger
(`verified`/`unverified`/`drifted`/`rotted`/`error`, roadmap H42 — derived
through the same `latest_events` `doctor`'s `custody.drift` aggregates, so the
per-scroll posture and doctor's counts cannot disagree; a drifted or rotted
scroll is still carried losslessly — raw is sacred, drift is a *recorded
posture*), and — when an engine classified it — *how the category was derived*:
the same `classification` view `list`/`show`/`search` carry (`by`/`basis`/
`confidence`, roadmap H20/H21/H35), omitted for an unclassified or user-set
category, the same honest absence the structured surfaces keep. A
`--concept`-scoped bundle also carries that concept's synthesized LLM summary
and its `summary_provenance` (engine + members-fingerprint freshness, roadmap
H29) — so a reader of the briefing sees provenance without parsing the JSONL),
and an embedded **custody block** — the lossless canonical rows as
JSON Lines inside a ` ```jsonl ` code fence, wrapped in the ADR 0102
`@generated`…`@end` sentinel. The block's JSONL is byte-identical to what
`export items` writes, so the bundle's losslessness is the same already tested
by ADR 0082/0099; the sentinel makes the block machine-locatable and keeps the
briefing body around it hand-annotatable across a re-export.

A second sibling `@generated` block — the **custody-events block** (roadmap
H67) — carries the in-scope items' verify ledger (`custody_events`) as JSON
Lines, so an item's drift *history* travels with it, not just the exporter's
last-seen posture frozen in the briefing prose: "lossless round-trip is a
guarantee" extended from the item to its custody record. The items block stays
the first region and byte-identical to `export items` (its round-trip
untouched); an unverified scope carries an empty events block, so the structure
is stable. `import bundle` restores the events with an idempotent, content-keyed
dedup, so a re-import is a custody no-op
(`test_custody_events_round_trip_into_a_fresh_library`,
`test_re_importing_a_bundle_dedups_the_custody_events`).

`--with-archive` appends an **optional third `@generated` region** — the
in-scope items' **prior-content archive** (`item_archive`, ADR 0106; roadmap
H280): the recoverable captures an `import … --accept-incoming` superseded. It is
**opt-in** because the archive can be large (a model-complete prior body per
adoption) and the `superseded` event already travels in the events block
documenting *that* an adoption happened — so without the flag the bundle carries
only the items + events blocks, byte-identical to a pre-H280 bundle (the
byte-identity / round-trip guarantees untouched —
`test_default_bundle_carries_no_archive_block`). With it, "take it with me"
includes the recovery store, so `scrolls archive show` works on the rebuilt
library (`test_with_archive_bundle_round_trips_the_recovery_store_to_a_fresh_library`).
The archive records are ordered content-deterministically, so a re-export from a
rebuilt library reproduces the block byte-for-byte
(`test_with_archive_bundle_re_exports_byte_identically`). `import bundle` restores
whatever archive block is present **unconditionally** (deduped by `(item_id,
prior_hash)` — the flag is an export concern only); a default bundle's absent
block restores as a clean `{imported: 0, skipped: 0}`. The whole-library JSONL
sibling is `scrolls export archive`.

It is the shareable complement to `export items` (the whole-library/faceted
backup) and the re-importable complement to `scrolls context` (a lossy excerpt
bundle for a model's context, not a round-trip). Scope is the same query +
facets `scrolls context`/`search` use (`--source`/`--category`/`--stage`/
`--tag`/`--concept`), but with **no cap**: the bundle carries *every* matching
scroll, because a take-it-with-you custody artifact must be complete about its
scope, not a top-N (the completeness contract,
`test_bundle_carries_every_match_not_a_capped_slice`). The bundle Markdown
**is** the artifact, so it prints raw on stdout (the `context`/`export items`
exception to the JSON-on-stdout rule) — `scrolls export bundle "<q>" >
briefing.md`. A blank query is a JSON error on stderr; an empty scope still
yields a valid, importable bundle saying `No matching scrolls.`
(`test_empty_scope_yields_a_valid_importable_bundle`). Re-import with
`scrolls import bundle`.

`--fidelity <tier>` and `--drift <posture>` add the two per-item **custody
scopes** (roadmap H258) — the custody-filter family on the *portable shareable
bundle*, the export twin of `context --fidelity`/`--drift` (H257), so a
custody-scoped briefing travels. `--fidelity` (the holdings axis, ADR 0097)
narrows the bundle to one custody-fidelity tier (`full`/`partial`/`reference`),
so an agent can "share only my full-fidelity holdings on this topic" — only the
sources it can re-derive offline. `--drift` (the ledger-claim axis, H58) narrows
it to one verify-ledger posture (`verified`/`unverified`/`drifted`/`rotted`/
`error`), so it can "export only the drifted ones for a recapture handoff".
Both AND with the facets and with each other, and are sieved **in SQL** through
the same `scrolls_fidelity`/`scrolls_drift` UDFs `search --fidelity`/`--drift`
apply (the bundle threads them straight to `search_items`/`count_matches`), so
the *whole* exported set — the briefing prose (the scope custody headline, the
per-source breakdown, the `_Attention:_`/`_Refresh:_` pointers), the lossless
custody block, *and* the custody-events block — describes exactly the kept slice
(`test_bundle_custody_headline_describes_the_kept_set`,
`test_bundle_fidelity_count_converges_with_the_unfiltered_headline`). The active
custody value is echoed in the title scope note — provenance of *what slice* was
shared (`test_bundle_custody_scope_is_named_in_the_title`). The lossless
round-trip holds over the scope: `import bundle` of a custody-scoped bundle
re-holds exactly the exported rows and their custody events, with no leakage of
the unscoped ones — the H216 mixed-fidelity round-trip narrowed to one custody
value (`test_bundle_custody_scope_round_trips_losslessly`). An unknown
tier/posture is rejected by argparse `choices` (exit 2) on the CLI, and by
`search_items` (`ValueError`) on the programmatic path
(`test_export_bundle_cli_rejects_unknown_custody_value`,
`test_bundle_unknown_custody_value_raises_valueerror`). The scope applies to the
HTML form too (both share the gather step, `test_bundle_html_custody_scope`).

Beside the scope custody headline the briefing carries a one-line **rank-confidence
headline** (roadmap H317) — `_Strength: strong <a>, moderate <b>, weak <c> (of N)._` —
the explainable-ranking surface (the `search`/`context` `match_strength`, vision
§3.5) lifted to the portable bundle: how many of the matches are **title hits** (`strong`,
BM25-weight 5×), **summary hits** (`moderate`, 2×), or **body-only** (`weak`, 1×), so a
recipient reads not just *what* matched but *how strongly* it ranked. Each in-scope scroll
then carries its own per-match marker — `· rank \`<strength>\`` on its drift line — and the
two fold the same value (the bundle-level headline is the histogram of the per-scroll
markers). Unlike `scrolls context` the bundle has **no cap and no same-work collapse**
(every match is its own entry), so the tally is over the *raw matched set* and sums to the
entry count. It is a ledger-free FTS-rank fact (a *derived read view*, outside the
`@generated` JSONL fence — the round-trip untouched), present on both the Markdown and the
HTML form, which render **byte-convergent** counts from the one shared
`render_strength_headline(tally_strength(...))` (`test_bundle_carries_strength_headline_and_per_scroll_markers`,
`test_bundle_html_carries_strength_headline_and_markers`,
`test_bundle_forms_converge_on_strength_counts`); an empty scope has nothing to rank, so
the headline and markers are simply omitted (`test_bundle_strength_absent_on_empty_scope`).

`--strength {strong|moderate|weak}` is the **rank-axis third scope** (roadmap H318)
— the *act* companion of that `_Strength:_` explanation, beside the two custody axes
`--fidelity`/`--drift`. It keeps only the matches whose query lands **at or above** a
field-weight band — `strong` keeps title hits, `moderate` title-or-summary, `weak`
everything — the same threshold the `search --strength` band applies (H314), threaded
straight to `search_items`/`count_matches` through the shared gather step. So an operator
ships "only the strong (title-hit) matches about X" as a portable briefing. Because the
bundle carries **no cap**, the sieve simply narrows the complete matched set (no
before-/after-cap split, unlike `search`/`context`); the re-folded `_Strength:_` headline
then describes exactly the kept slice (`test_bundle_strength_keeps_band_and_stronger`). It
**ANDs** with the facets and the custody axes — `--strength strong --fidelity full` ships
only the title-hit matches whose content you can re-derive offline
(`test_bundle_strength_ANDs_with_fidelity`) — is echoed in the title scope note
(`test_bundle_strength_scope_is_named_in_the_title`), and the lossless round-trip holds
over it: `import bundle` re-holds exactly the strength-scoped rows, with no leakage of the
weaker matches (`test_bundle_strength_round_trips_losslessly`). An unknown band is rejected
by argparse `choices` (exit 2) on the CLI and by `search_items` (`ValueError`) on the
programmatic path (`test_export_bundle_cli_rejects_unknown_strength`,
`test_bundle_strength_unknown_raises_valueerror`); the scope applies to the HTML form too
(both share the gather step, `test_bundle_html_strength_scope`).

`--content-duplicate` is the **content-identity scope** (roadmap H341) — a boolean
flag, the export companion of the `_Duplicates:_` briefing line (H331). It keeps
only the matches the library holds a **byte-identical copy of under another id**
(the content-duplicate custody shape), so an operator ships "only the redundant
copies about X for a recipient to dedup". It threads straight to
`search_items`/`count_matches` through the shared gather step as the same
whole-library `content_hash` sub-count clause `search --content-duplicate` applies
(H338), so the briefing, the lossless custody block, and the custody-events block
all carry exactly the byte-identical-held slice — and the re-folded `_Duplicates:_`
line describes the kept set (`test_bundle_content_duplicate_keeps_only_siblings`).
The sibling scope is **whole-library** (a content group spans the query/source
scope), so `--source S --content-duplicate` ships S's matches that have a
byte-identical sibling *anywhere* held; it **ANDs** with the facets, the custody
axes, and `--strength`, is echoed in the title scope note as a bare
`content-duplicate` marker (`test_bundle_content_duplicate_named_in_the_title`),
and is **report-only** — never a merge (raw is sacred). The lossless round-trip
carries the redundancy: `import bundle` of a content-duplicate-scoped bundle
re-holds exactly the redundant pair and the rebuilt library's
`doctor.custody.content_duplicates` re-flags the same group
(`test_export_bundle_cli_content_duplicate_round_trips_and_reflags`; `content_hash`
travels, the H336 guarantee). The scope applies to the HTML form too (both share
the gather step, `test_bundle_html_content_duplicate_keeps_only_siblings`).

`--format` (default `markdown`) chooses the output form (roadmap H39). `markdown`
is the **canonical, lossless, re-importable** bundle described above — the form
`scrolls import bundle` round-trips against. `html` renders the *same* scope and
the *same* per-scroll custody picture (fidelity tier, drift posture,
classification provenance, the scope custody headline, the rank-confidence
`_Strength:_` headline, the per-source breakdown,
and a `--concept` bundle's summary) as a **self-contained, browser-readable
briefing** — one
offline HTML file with inline CSS, no scripts, and nothing fetched from the
network; all dynamic content is HTML-escaped so a tag-bearing title or body can
never inject markup (`test_bundle_html_escapes_dynamic_content`). The HTML is
**export-only — not a re-import unit**: the lossless custody + custody-events
JSONL travels embedded in `<details>`/`<pre>` so the data is *present* for a
reader, but `import bundle` consumes the Markdown form, and the briefing says so
(no false round-trip claim) — the custody-honest split. Like the Markdown form,
the HTML prints raw on stdout (`scrolls export bundle "<q>" --format html >
briefing.html`) and tolerates a missing library
(`test_bundle_html_is_a_self_contained_document`,
`test_export_bundle_format_html_emits_html`).

### `scrolls import bundle <path>`

Import scrolls from a custody bundle, losslessly — the inverse of
`scrolls export bundle`, and the "take it with me" half of the dogfood flow.
`path` is a bundle file `export bundle` wrote; the importer reads its
sentinel-fenced custody block, parses each record exactly as `import items`
does (`item_from_dict`, the same required identity fields, unknown keys
tolerated), and restores the index rows. A file with no custody block, or a
malformed record, is a JSON error on stderr naming the record, so a corrupt
bundle fails loudly rather than restoring silently incomplete
(`test_parse_bundle_rejects_a_non_bundle`, `test_import_bundle_reports_a_corrupt_block`).
Existing scrolls are never overwritten (`INSERT OR IGNORE` by id, ADR 0082), so
re-importing a bundle into a library that already holds it imports nothing
(`test_import_bundle_never_overwrites_an_existing_scroll`); derived artifacts
rebuild from the rows via `scrolls doctor --fix` / `scrolls kb`, as with
`import items`. The export→import→`doctor --fix` round-trip across a fresh
library is verified end to end
(`test_export_import_round_trips_across_a_fresh_library`).

But a skip is not opaque: like `import items` (the H272 partition lifted here by
roadmap H273), the bundle importer splits every skip on the captured-content
`content_hash` into `unchanged` (an identical re-import — a true custody no-op)
and `conflict` (a held id whose incoming copy **disagrees** — e.g. a peer's
bundle of a source that has since drifted). The held copy is still kept — raw is
sacred, a conflict is a *recorded, surfaced* event, never an overwrite (vision
§2.4; the adopted *surface, don't silently rewrite* posture).
The diverging ids ride the structured `conflicts` list (sorted, deduped,
uncapped) **and** a bounded `{"warning": …}` on stderr naming them (the shared
`_merge_items`/`_warn_conflicts` helpers, the same as `import items`).
`skipped == unchanged + conflict` is the coherence invariant
(`test_import_bundle_surfaces_a_content_conflict`,
`test_import_bundle_dry_run_conflict_partition_matches_a_real_import`). Because
the recording rides the shared `_merge_items`, the bundle importer also writes a
typed `conflict` **custody event** for each divergence (roadmap H274, ADR 0104) —
queryable via `scrolls history <id> --status conflict`, a distinct axis that never
enters the drift posture — exactly as `import items` does; the `--dry-run` predicts
the conflict but, being read-only, records nothing
(`test_import_bundle_records_a_conflict_as_a_custody_event`,
`test_import_bundle_dry_run_records_no_conflict_event`).

**`--accept-incoming` *adopts* the diverging bundle copy** (roadmap H278, ADR 0106),
exactly as `import items --accept-incoming` does (the shared `_merge_items`): on a
conflict the held copy is **replaced** by the bundle's, its prior capture **archived
first** (recoverable via `scrolls archive show`, never destroyed — custody §2.4), and
a `superseded` event clears the conflict across `doctor`/`status`/the `_Conflicts:_`
line. The adopted ids ride a structured `adopted` list; it composes with `--dry-run`,
which then **predicts** the held→incoming adoptions and writes nothing (the
predict-the-write discipline on the adopt axis). Opt-in and idempotent — a re-import
of an already-adopted bundle is `unchanged`
(`test_import_bundle_accept_incoming_adopts_and_archives`,
`test_import_bundle_dry_run_accept_incoming_predicts_without_writing`).

The importer also restores the bundle's **custody-events block** (roadmap H67)
into the target's verify ledger, deduped by content — the 5-tuple
`(item_id, checked_at, status, prior_hash, observed_hash)`, *not* the
per-library autoincrement id — so a re-import is a custody no-op and never
double-counts a check (`test_re_importing_a_bundle_dedups_the_custody_events`).
Events ride for every in-scope item whether its row was freshly inserted or
already held (custody history merges); a pre-H67 bundle with no events block
imports items only, never crashing
(`test_a_pre_h67_bundle_without_an_events_block_imports_items_only`). The
restored ledger is the same one `scrolls history`/`doctor`/`facets drift` read,
so an imported item's drift posture is its exporter's.

The restore is honest about **orphan** events (roadmap H217): every custody event
must resolve to a held-or-imported item. A well-formed export never desyncs the
two blocks — its events ride only for in-scope items, all of which are also in the
items block — so the orphan count is `0`. A corrupt or hand-edited bundle whose
events name an item the items block omits has those events **counted (`orphaned`)
and *not* imported**, with a `{"warning": …}` on stderr: a ledger row for an item
`scrolls show` 404s on would be a dangling history, so it is neither silently
inserted nor silently dropped
(`test_import_bundle_skips_and_counts_orphan_custody_events`,
`custody.partition_resolvable_events`). The warning is **diagnosable** (roadmap
H225): it leads with the orphan *event* count, then names the distinct `item_id`s
those events dangle on (sorted, deduped, bounded with a `(+N more)` tail), so "2
orphan events" becomes "… not in this bundle …: `arxiv:x`, `web:ghost`" — the
operator can see *which* rows the items block is missing, not just that the bundle
is corrupt (`test_import_bundle_warning_names_which_items_the_orphans_dangle_on`).
The same distinct ids also ride the **structured** summary as `events.orphaned_items`
(roadmap H230) — sorted, deduped, and **uncapped**, so an agent piping stdout gets
the complete loss while the human warning keeps its bounded `(+N more)` tail
(structured completeness vs. human readability, the M2 ethos;
`test_import_bundle_summary_names_which_items_orphaned`,
`test_import_bundle_orphaned_items_is_uncapped_while_the_warning_bounds`).
(The whole-library `import events` restore
does *not* skip orphans — that path tolerates events restored before their items;
a bundle is an atomic items+events unit whose events should always anchor.)

The importer also restores the bundle's **prior-content archive block**
(roadmap H280) when one travelled — the optional third region a `--with-archive`
export carries. Restore is **unconditional** (whatever recovery store is present
is restored — the flag is an export concern only) and deduped by `(item_id,
prior_hash)`, so a re-import is a no-op (`test_import_bundle_archive_restore_is_idempotent`).
A lean default bundle carries no archive block, restoring as a clean
`{imported: 0, skipped: 0}` — the honest "we checked, none travelled". After the
restore, `scrolls archive show <id>` recovers the prior on the rebuilt library
(`test_with_archive_bundle_round_trips_the_recovery_store_to_a_fresh_library`).
The archive is a standalone recovery store keyed by `item_id` with no held-row
interaction (it only appends to `item_archive`), so it has no orphan concept like
the events restore. `--dry-run` predicts the archive restore without writing
(`test_import_bundle_dry_run_predicts_the_archive_restore`).

`--dry-run` (roadmap H220) **previews** the merge and writes nothing: an agent
handed a shared bundle can see *exactly* what an import would add vs. skip — the
same `{imported, skipped, unchanged, conflict, conflicts, content_duplicates, items,
events, archive}` summary the real import prints, plus a `"dry_run": true` marker — before committing to it.
It is the read-only sibling of the custody-safe import (ADR 0082): the item
partition is computed by `_preview_merge_items` (the read-only twin of
`_merge_items`), event counts by the same content-dedup the writer uses
(`custody.preview_import_events`), and the orphan split by
`partition_resolvable_events`. The bundle's own item ids anchor the event
partition, because a real import inserts those rows *before* partitioning — so a
preview into an *empty* library still resolves the bundle's events instead of
mis-flagging every one as an orphan. Orphan events warn on stderr in the preview
exactly as in a real import. The dry-run summary equals what the subsequent real
import prints (sans the dry-run-only fields), pinned so the preview never drifts
from reality (`test_import_bundle_dry_run_counts_match_a_real_import`,
`test_import_bundle_dry_run_previews_without_writing`,
`test_import_bundle_dry_run_previews_orphan_events`).

The dry-run also **predicts the conflict set** (roadmap H273): the same
`content_hash` compare the live merge runs, so the `conflict`/`conflicts` an
operator reads in the preview name exactly the held copies a real import would
surface as diverging — and the conflict warning is loud on stderr in the preview
too. The prediction simulates `INSERT OR IGNORE`'s within-batch view, so a bundle
that *repeats* an id with divergent content (a splice of two captures) classifies
identically on both paths: the first occurrence is the kept copy, a later one
conflicts against it, and the id rides `new` (library-absent) *and* `conflicts`
(the bundle disagrees with itself) at once
(`test_import_bundle_dry_run_predicts_the_conflict_set`,
`test_import_bundle_within_bundle_dup_with_divergent_content_conflicts_on_both`).

The bundle importer also counts the **content duplicates *this* import adds**
(roadmap H353), exactly as `import items` does (the same `content_duplicates` count):
a freshly-inserted bundle row that lands **byte-identical** to a *distinct* held copy —
or to another row in the same bundle. Report-only / no stderr warning, the point-in-
time counterpart of `doctor`'s whole-library standing `custody.content_duplicates`, and
**idempotent** (scoped to the freshly-inserted ids, so a clean re-import reports `0`).
The `--dry-run` **predicts** the same number, folding the content-identity index over
the *simulated* post-import library (held rows + the would-be-inserted new rows) — so
the preview's `content_duplicates` is byte-identical to the live import's, the same
"preview never drifts from reality" guarantee the conflict prediction holds
(`test_import_bundle_reports_a_content_duplicate_against_a_held_copy`,
`test_import_bundle_dry_run_predicts_content_duplicates`).

The dry-run also names *which* scrolls are new vs. already held (roadmap H226), so
the counts ("2 new") become reviewable ("`new`: which two") — an operator can
confirm the bundle adds what they expect before committing. The `new` and `held`
lists are sorted, deduped, and **uncapped** (the structured channel carries the
complete sets, unlike the bounded human orphan warning). They are dry-run-only;
the real import stays terse
(`test_import_bundle_dry_run_names_which_items_are_new_vs_held`).

| Key | Meaning |
| --- | --- |
| `imported` | new scrolls inserted (would-be-inserted under `--dry-run`) |
| `skipped` | already present and not inserted (`== unchanged + conflict`, H273) |
| `unchanged` | skipped: held copy has the **same** `content_hash` (an idempotent re-import, H273) |
| `conflict` | skipped: held copy has a **different** `content_hash` (divergence surfaced, held copy kept, H273) |
| `conflicts` | the distinct ids whose held copy diverged from the incoming bundle row and was *kept* — sorted, deduped, uncapped (H273); `[]` on a clean import |
| `adopted` | the distinct ids whose held copy was *replaced* by the incoming bundle row under `--accept-incoming` (prior archived, H278); `[]` otherwise |
| `content_duplicates` | how many freshly-imported rows landed byte-identical to a distinct held copy (or to another row in the same bundle) — report-only, idempotent, predicted under `--dry-run` (H353); `0` when the bundle added no redundant copy |
| `items` | scroll records read from the custody block |
| `new` | (dry-run only) the would-be-imported item ids — sorted, deduped; `len(new) == imported` |
| `held` | (dry-run only) the already-held item ids the merge would skip — sorted, deduped |
| `events` | `{imported, skipped, orphaned, orphaned_items}` — events restored / deduped from the events block, plus those skipped as orphans (no held-or-imported item, H217); `orphaned_items` names the distinct orphan ids (sorted, deduped, uncapped — H230) |
| `archive` | `{imported, skipped}` — prior-content archive rows restored / deduped from the optional `--with-archive` block (H280); `{0, 0}` when no archive block travelled |
| `dry_run` | present and `true` only under `--dry-run`; the summary is a preview and nothing was written |

```console
$ scrolls export bundle "database engine" > briefing.md

$ scrolls import bundle briefing.md --dry-run
{"dry_run": true, "imported": 2, "skipped": 0, "items": 2, "new": ["arxiv:1706.03762", "wikipedia:en:SQLite"], "held": [], "events": {"imported": 3, "skipped": 0, "orphaned": 0, "orphaned_items": []}}
[exit 0]

$ scrolls import bundle briefing.md
{"imported": 2, "skipped": 0, "items": 2, "events": {"imported": 3, "skipped": 0, "orphaned": 0, "orphaned_items": []}}
[exit 0]
```

### `scrolls import events <path>`

Restore custody events from a JSONL export — the inverse of `scrolls export
events`, the custody sibling of `import items` (roadmap H72). `path` is a file
`export events` wrote; each line is parsed exactly as `import bundle`'s events
are (`event_from_dict`, required identity `item_id`/`checked_at`/`status`,
unknown keys — including the per-library autoincrement `id` — tolerated) and
restored through the same idempotent `custody.import_events`. Restore is
**deduped by content** — the 5-tuple `(item_id, checked_at, status, prior_hash,
observed_hash)`, never the autoincrement id — so re-importing a backup is a
custody no-op (`test_import_events_is_idempotent`); the whole-library
export→import round-trip into a fresh library is verified end to end
(`test_export_events_round_trips_into_a_fresh_library`). A missing file or a
malformed line is a JSON error on stderr naming the line, so a corrupt backup
fails loudly rather than restoring silently incomplete
(`test_import_events_missing_file_is_an_error`). Events restore independently of
items (the ledger is keyed by `item_id` string), so the order is yours —
typically `import items` then `import events`.

| Key | Meaning |
| --- | --- |
| `imported` | new custody events appended |
| `skipped` | already present (content dedupe working) |
| `events` | custody-event rows read from the export |

```console
$ scrolls export events > ledger.jsonl

$ scrolls import events ledger.jsonl
{"imported": 5, "skipped": 0, "events": 5}
[exit 0]
```

### `scrolls import archive <path>`

Restore the **prior-content archive** from a JSONL export — the inverse of
`scrolls export archive`, the recovery-store sibling of `import items`/`import
events` (roadmap H280). `path` is a file `export archive` wrote; each line is
parsed through `archive_from_dict` (required identity
`item_id`/`archived_at`/`snapshot`, unknown keys — including the per-library
autoincrement `id` — tolerated) and restored through the idempotent
`items.import_archive`. Restore is **deduped by `(item_id, prior_hash)`** — never
the autoincrement id — so re-importing a backup, or the overlapping union of two
bundles, is a no-op (`test_import_archive_is_idempotent`); the whole-library
export→import round-trip into a fresh library is verified end to end
(`test_export_archive_round_trips_into_a_fresh_library`). A missing file or a
malformed line is a JSON error on stderr naming the line, so a corrupt recovery
backup fails loudly rather than restoring silently incomplete
(`test_import_archive_missing_file_is_an_error`).

The archive is a **standalone recovery store keyed by `item_id`** with no
held-row interaction — importing a prior for an id the target does not currently
hold simply populates the recovery store (it never touches a held copy, so there
is no orphan concept like the events restore). After restore, `scrolls archive
show <id>` re-emits the recovered prior as a re-importable line. Typically you
restore the holdings and ledger first (`import items`, `import events`), then
`import archive` to recover the superseded captures — though the order is yours.

| Key | Meaning |
| --- | --- |
| `imported` | new archived priors appended |
| `skipped` | already present (content dedupe working) |
| `archive` | archived-prior rows read from the export |

```console
$ scrolls export archive > archive.jsonl

$ scrolls import archive archive.jsonl
{"imported": 3, "skipped": 0, "archive": 3}
[exit 0]
```

## Following feeds

Live delta updates are feed-based (IDEAS.md §13, ADR 0017): follow any
RSS 2.0/Atom feed — a blog, a YouTube channel or playlist, an arXiv
category, a GitHub releases feed — and `sync` registers its new entries
through the same detection/dedupe as `scrolls add`. The examples below
talk to a feed served from localhost; any feed URL behaves the same
(see [Reproducing these examples](#reproducing-these-examples)).

### `scrolls follow [url]`

Subscribe to a feed. The URL is fetched once (network) to validate it
and capture the feed's title — a typo'd or non-feed URL is rejected
with nothing stored, instead of failing every future sync
(`test_follow_unreachable_feed_is_an_error`;
`test_follow_feed_bad_feed_stores_nothing` in `tests/test_feeds.py`).
Re-following returns the stored row with `"created": false`
(`test_follow_is_idempotent`). YouTube playlist and channel-id page
URLs map to their public Atom feeds purely syntactically
(`test_follow_youtube_playlist_url_follows_its_feed`). Without a URL:
list current subscriptions
(`test_follow_without_url_lists_subscriptions`,
`test_follow_list_before_init_prints_empty_array`).

| Key | Meaning |
| --- | --- |
| `id` | subscription id — 12 hex chars of the feed URL's SHA-256 |
| `feed_url` | the feed that will be polled (after any URL mapping) |
| `title` | the feed's own title, if it declares one |
| `created` | `false` when the feed was already followed |

```console
$ scrolls follow http://localhost:8943/feed.xml
{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "title": "Demo Weblog", "created": true}
[exit 0]

$ scrolls follow http://localhost:8943/missing.xml
{"error": "feed request failed: HTTP Error 404: File not found"}
[exit 1]

$ scrolls follow
[{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "title": "Demo Weblog", "added_at": "2026-06-12T22:07:58+00:00", "last_synced_at": null, "etag": null, "last_modified": null}]
[exit 0]
```

The listing's `etag`/`last_modified` are the feed's HTTP cache
validators, stored by the last full sync (ADR 0019) — always `null`
right after `follow`, which deliberately stores none
(`test_follow_feed_stores_no_validators` in `tests/test_feeds.py`):
follow registers no entries, so a stored validator would make the
first sync skip the feed's current entries.

### `scrolls sync [id]`

Poll every followed feed (network) and register each new entry URL as
an item at stage `detected` — exactly what `scrolls add` would store,
so a YouTube feed entry becomes a `youtube` item and a blog entry a
`web` item (`test_sync_registers_new_items_at_stage_detected`), except
that the entry's feed title names the item until fetch replaces it
(`test_sync_seeds_detected_items_with_entry_titles`,
`test_sync_never_retitles_known_items` in `tests/test_feeds.py`). Sync
only discovers URLs; run `scrolls fetch` (then `classify`/`md`) to
bring the new items in. Entries already in the library count as
`known`, so re-syncs are cheap (`test_sync_is_idempotent`); entries
whose link is not http(s) are skipped. Entry links are normalized like
`scrolls add` URLs (ADR 0023), so a feed that rotates tracking params
on its links never re-registers the same post
(`test_sync_normalizes_tracking_params_out_of_entry_links`). With an
id: sync only that
subscription (`test_sync_by_id_syncs_one_subscription`); unknown ids
are an error envelope (`test_sync_unknown_id_is_an_error`). One dead
feed fails its subscription but never the batch.

Each poll is a conditional GET (ADR 0019): a full response's
`ETag`/`Last-Modified` are stored on the subscription, and when the
server answers `304 Not Modified` on the next poll the subscription
reports `"status": "unchanged"` without re-downloading or re-parsing
the feed (`test_sync_unchanged_feed_reports_unchanged`;
`test_sync_not_modified_reports_unchanged` in `tests/test_feeds.py`).
Feeds that serve no validators just get a full response every time.

| Key | Meaning |
| --- | --- |
| `new` / `known` / `skipped` / `failed` / `unchanged` | totals (`failed` and `unchanged` count subscriptions) |
| `results[]` | per-subscription `{id, feed_url, status, ...}` with its own counts; `new_items` lists registered item ids, `error` the failure |

```console
$ scrolls sync
{"new": 2, "known": 0, "skipped": 0, "unchanged": 0, "failed": 0, "results": [{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "status": "synced", "new": 2, "known": 0, "skipped": 0, "new_items": ["web:081e89b0b346", "web:dbeb9a37d69a"]}]}
[exit 0]

$ scrolls sync          # the feed is unchanged: the server answers 304
{"new": 0, "known": 0, "skipped": 0, "unchanged": 1, "failed": 0, "results": [{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "status": "unchanged", "new": 0, "known": 0, "skipped": 0, "new_items": []}]}
[exit 0]

$ touch "$DEMO/site/feed.xml"   # the feed "changes" (new Last-Modified)
$ scrolls sync          # full response again; the same entries are known
{"new": 0, "known": 2, "skipped": 0, "unchanged": 0, "failed": 0, "results": [{"id": "ea77c1d5239e", "feed_url": "http://localhost:8943/feed.xml", "status": "synced", "new": 0, "known": 2, "skipped": 0, "new_items": []}]}
[exit 0]
```

### `scrolls unfollow <id>`

Remove a subscription by id — or by feed URL, which resolves to the
same id `follow` minted (`test_unfollow_removes_subscription`,
`test_unfollow_accepts_the_feed_url`). Items the feed registered stay
in the library; only the subscription goes. Unknown ids are an error
envelope (`test_unfollow_unknown_id_is_an_error`).

```console
$ scrolls unfollow http://localhost:8943/feed.xml
{"id": "ea77c1d5239e", "removed": true}
[exit 0]

$ scrolls unfollow ea77c1d5239e
{"error": "no such subscription: ea77c1d5239e"}
[exit 1]
```

## Pipeline stages

### `scrolls fetch [id] [--limit N]`

No argument: run the source adapter for every item at stage `detected`
(network). Items whose source has no adapter yet are *skipped* (they stay
`detected` for a future scrolls) and do not fail the run
(`test_fetch_all_skips_sources_without_adapter`). With an id: refetch
that one item regardless of stage — and asking for an adapterless item
by id is an honest *failure*, not a skip
(`test_fetch_by_id_refetches_regardless_of_stage`,
`test_fetch_by_id_without_adapter_fails`).

`--limit N` paces a batch run: at most N fetches are attempted, oldest
saved first, and the next run resumes where this one stopped — the way
to enrich a large `import google-takeout` spine incrementally
(`test_fetch_limit_caps_attempts_and_resumes`). The limit counts fetch
*attempts* (fetched + failed), not adapterless skips: skipped items
stay `detected` at the front of the saved order, so counting them
would wedge every paced run on the same skips
(`test_fetch_limit_does_not_count_adapterless_skips`). Items beyond
the limit are not reported. Combining `--limit` with an explicit id is
an error (`test_fetch_limit_with_explicit_id_is_an_error`).

| Key | Meaning |
| --- | --- |
| `fetched` / `skipped` / `failed` | batch counts |
| `results[]` | per-item `{id, status, ...}`; `title`+`stage` on success, `reason` on skip, `error` on failure |

```console
$ scrolls fetch                       # only an x item is detected
{"fetched": 0, "skipped": 1, "failed": 0, "results": [{"id": "x:3333", "status": "skipped", "reason": "no fetch adapter for source 'x'"}]}
[exit 0]

$ scrolls fetch x:3333                # by id: same situation is a failure
{"fetched": 0, "skipped": 0, "failed": 1, "results": [{"id": "x:3333", "status": "failed", "error": "no fetch adapter for source 'x'"}]}
[exit 1]

$ scrolls fetch arxiv:1706.03762      # by id, with network
{"fetched": 1, "skipped": 0, "failed": 0, "results": [{"id": "arxiv:1706.03762", "status": "fetched", "title": "Attention Is All You Need", "stage": "fetched"}]}
[exit 0]
```

### `scrolls classify [id]`

No argument: assign a `category` (rules engine `rules-v1`, ADR 0004) to
every fetched/rendered item that has none — an existing category, user-set
or imported, is never overwritten
(`test_classify_batch_never_overwrites_an_existing_category`,
`test_classify_llm_batch_never_overwrites_an_existing_category`). Unmatched
items honestly report `"status": "unmatched"` and stay unclassified
(`test_classify_batch_reports_unmatched_items`). With an id: explicit
reclassify, replacing any existing category
(`test_classify_by_id_reclassifies_explicitly`). Already-rendered scrolls
are re-rendered so frontmatter stays in sync
(`test_classify_batch_categorizes_and_rerenders`).

When a rule fires, the rules engine records how the category was produced
in `provenance`, so a re-classify is reproducible and auditable: the engine
(`classified_by="rules-v1"`), which precedence tier matched
(`classified_basis` — `curated-source` / `title-pattern` / `documentation-url`
/ `weak-source`), and a fingerprint of the rule tables it ran under
(`classified_ruleset`). The fingerprint changes if the rules change, so a
reader can tell whether a re-classify today would still reproduce the stored
category. This surfaces as a derived `classification` block on `show`,
`list`, and `search` (see those commands), so how a category was produced
reads identically on every browse surface; `tests/test_classify.py` pins the
per-tier basis, the fingerprint, and their deterministic re-derivation.

The `classification` block also carries a derived `confidence` marker (roadmap
H21, an adapted confidence-levels mechanism) so an agent knows *how much
to trust* the category without consulting `doctor` or knowing the live ruleset:

- `level` — the method's nature: `deterministic` for a rules match (it follows
  mechanically from recorded signals — reproducible and explainable) or
  `inferred` for an LLM category (a probabilistic model judgment, to be weighed
  more cautiously). This is the "rule-matched vs llm-inferred" trust axis.
- `freshness` — present only for the rules engine (where it can be answered):
  `current` / `stale` / `unknown` against the *live* ruleset, the per-item
  counterpart of doctor's `custody.enrichment` aggregate. Omitted for the LLM
  engine — there is no ruleset to compare and a wall-clock timestamp would break
  the idempotence contract, so no freshness is claimed rather than a guessed one
  (honest absence). Recency is the *ruleset fingerprint*, not a timestamp.

The marker reads from the same `classify.classification_freshness` derivation
doctor and `--stale` use, so the per-item recency an agent sees can never
disagree with the count doctor reports
(`test_per_item_confidence_marker_converges_with_the_doctor_aggregate`).

`--stale` re-runs the rules engine over exactly the items `scrolls doctor`
reports in `custody.enrichment.stale` — categories produced under a *superseded*
ruleset (`classified_ruleset` ≠ the live fingerprint) — refreshing both
`category` and `classified_ruleset` to the live ruleset. It is the explicit,
user-invoked counterpart to doctor's read-only stale signal: regeneration
happens *on request*, never as doctor's silent overwrite (custody §2.4),
closing the loop *record* (H20) → *report* (H25) → *refresh* (H27). Selection
is the one shared predicate (`classify.is_stale_classification`), so the count
doctor shows equals the count a refresh acts on, and it converges
(`test_classify_stale_clears_the_doctor_stale_signal`). It never touches
current-ruleset items, pre-H20 *unfingerprinted* items (unknown, not stale), or
user-set categories — a hand-set category carries no engine stamp
(`scrolls set` drops it), so user overrides always win
(`test_classify_stale_skips_current_ruleset_items`,
`test_classify_stale_leaves_user_set_categories_untouched`). An item the live
ruleset no longer matches falls to `"status": "unmatched"` and its stored
category is left untouched — surfaced, never wiped. Rules-only: `--stale`
rejects `--engine llm`, `--batch`, and a single id
(`test_classify_stale_rejects_the_llm_engine`,
`test_classify_stale_rejects_batch`, `test_classify_stale_rejects_an_item_id`).

`--stale --source <S>` narrows that refresh to one source's stale
classifications — exactly the slice doctor reports in
`custody.enrichment.by_source[<S>]` (roadmap H135), the enrichment-axis
counterpart of [`verify --source <S>`](#scrolls-verify-id) (the per-source
*drift* recheck). When `doctor`/`maintain` name `web` as carrying the most
stale-classification debt, `classify --stale --source web` refreshes just
those without touching another source's. The count it refreshes equals
doctor's per-source number by construction (both filter the one stale
predicate by source), and the refresh clears that source's entry from the
offenders-only map — the per-source `record → report → refresh` convergence
(`test_classify_stale_source_count_matches_doctor_by_source`, and the pure-
layer/doctor tie in
`test_classify_stale_source_refreshes_exactly_the_doctor_per_source_count`).
A source with no stale debt is the honest empty no-op (network-free, no
targets), never an error (`test_classify_stale_source_with_no_stale_is_a_clean_noop`).
`--source` is a *narrowing* of `--stale`, not a standalone selection like
`verify --source` — it needs `--stale` (without it, there is no stale set to
narrow: `test_classify_source_without_stale_is_an_error`). The summary axis has
no per-source counterpart — a concept summary spans sources, so `kb --stale`
stays whole-library (roadmap H135) — so this completes the per-source *refresh*
on the one enrichment axis that decomposes.

`--engine llm` (engine `llm-v1`, ADR 0015) classifies with a model via the
Anthropic API instead (network; needs `ANTHROPIC_API_KEY`; default model
`claude-opus-4-8`, overridable via `SCROLLS_LLM_MODEL`). It uses the full
IDEAS.md §8 category vocabulary and additionally fills `domain` and merges
model `concepts` after the platform-curated ones; classified results carry
`domain` and `concepts` keys
(`test_classify_llm_engine_classifies_and_rerenders`, in
`tests/test_classify_llm.py` for the engine itself). Batch semantics are
unchanged — never overwrites an existing category, per-item API failures
don't abort the batch
(`test_classify_llm_failure_is_reported_not_raised`) — except that missing
credentials abort the whole run with the standard error envelope, since
every remaining item would fail identically
(`test_classify_llm_without_credentials_aborts_with_error_envelope`).

`--batch` (ADR 0022) submits the whole `--engine llm` run as one Message
Batches API request at half the per-token price, polling until the batch
ends — typically minutes — instead of one API call per item
(`test_classify_llm_batch_flag_submits_one_batch`;
`test_batch_classifies_every_item_in_order` and
`test_real_batch_submits_polls_and_collects_results` in
`tests/test_classify_llm.py` for the engine and transport). Per-request
failures — errored, expired, refused — fail their item without aborting
the batch (`test_batch_per_item_errors_pass_through`), and missing
credentials still abort the run
(`test_classify_llm_batch_without_credentials_aborts_with_error_envelope`).
The flag needs the llm engine and a whole-run invocation
(`test_classify_batch_flag_requires_the_llm_engine`,
`test_classify_batch_flag_rejects_an_item_id`).

`config.toml`'s `[classify]` section (ADR 0016) sets the defaults:
`default_engine = "llm"` routes a bare `scrolls classify` to the LLM
engine (`test_classify_config_default_engine_llm_is_used`) and
`llm_model` picks its model
(`test_classify_config_llm_model_is_used`). Per-invocation overrides
win — `--engine` beats `default_engine`
(`test_classify_engine_flag_overrides_config`) and `$SCROLLS_LLM_MODEL`
beats `llm_model` (`test_classify_env_model_beats_config`). A malformed
or invalid config is an error envelope, never a silent fallback
(`test_classify_malformed_config_is_an_error_envelope`,
`tests/test_config.py` for the parser itself).

```console
$ scrolls classify    # x:1111 already has a category from the import join
{"classified": 1, "unmatched": 0, "failed": 0, "results": [{"id": "x:2222", "status": "classified", "category": "tutorial"}]}
[exit 0]

$ scrolls classify wikipedia:en:SQLite --engine llm   # no credentials set
{"error": "llm engine needs Anthropic credentials: set ANTHROPIC_API_KEY (\"Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of the `X-Api-Key` or `Authorization` headers to be explicitly omitted\")"}
[exit 1]

$ scrolls classify       # after writing broken TOML into config.toml
{"error": "config.toml: invalid TOML: Expected ']' at the end of a table declaration (at line 1, column 10)"}
[exit 1]

$ scrolls classify --batch     # the rules engine has nothing to batch
{"error": "--batch requires the llm engine (--engine llm)"}
[exit 1]

$ scrolls classify --stale     # refresh whatever doctor flagged stale
{"classified": 1, "unmatched": 0, "failed": 0, "results": [{"id": "web:3f1a", "status": "classified", "category": "tutorial"}]}
[exit 0]

$ scrolls classify --stale --source web   # only the source doctor flagged weakest
{"classified": 1, "unmatched": 0, "failed": 0, "results": [{"id": "web:3f1a", "status": "classified", "category": "tutorial"}]}
[exit 0]
```

### `scrolls set <id> field=value...`

Layer three of IDEAS.md §8 — user overrides always win (ADR 0018). Set
exactly the fields the classification engines write: `category`,
`domain`, and the comma-separated lists `tags` and `concepts`
(`test_set_overrides_fields_and_rerenders`). Values are free-form —
engines pin vocabularies, the user's word is final. An empty value
clears the field, returning the item to the batch-classifiable pool
(`test_set_empty_value_clears_for_reclassification`); list values
replace, not merge. A set category sticks because batch `classify`
never overwrites one (`test_set_survives_batch_classify`). A rendered
scroll is re-rendered so frontmatter stays in sync; nothing is applied
when any assignment is invalid (`test_set_unknown_field_is_an_error`,
`test_set_malformed_assignment_is_an_error`; the parser itself in
`tests/test_overrides.py`).

```console
$ scrolls set x:1111 tags=sqlite,fts "concepts=full-text search"
{"id": "x:1111", "status": "set", "category": "technique", "domain": "databases", "tags": ["sqlite", "fts"], "concepts": ["full-text search"], "markdown_path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md"}
[exit 0]

$ scrolls set x:1111 usefulness=high
{"error": "cannot set 'usefulness'; settable fields: category, domain, tags, concepts"}
[exit 1]
```

### `scrolls md [id]`

No argument: render every item at stage `fetched` to a Markdown scroll
at `scrolls/<source>/<slug>.md` (`tests/test_render.py`). With an id:
re-render even if already rendered; `markdown_path` keeps the path stable
across re-renders (`test_md_by_id_rerenders_a_rendered_item`,
`test_md_bulk_run_is_idempotent`). An item with no fetched content fails
(`test_md_by_id_fails_for_unfetched_item`).

```console
$ scrolls md
{"rendered": 2, "failed": 0, "results": [{"id": "x:1111", "status": "rendered", "path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md"}, {"id": "x:2222", "status": "rendered", "path": "scrolls/x/simonw-attention-is-all-you-need-still-holds-up-a-guide-to-reading-it-prope.md"}]}
[exit 0]
```

### `scrolls media [id]`

No argument: download every uncaptured media reference — arXiv PDFs,
youtube thumbnails, x photos — to `media/<source>/<id-slug>-<n><ext>`
(network), recording each file's root-relative path on the item's media
ref and re-rendering its scroll so frontmatter points at the local file
(`test_media_batch_captures_pending_refs_and_rerenders`). Captured refs
are never re-downloaded by a batch run, and a deleted file is healed on
the next one (`test_media_batch_is_idempotent`,
`tests/test_media.py`). With an id: explicit re-capture, overwriting the
recorded paths (`test_media_by_id_recaptures_explicitly`); an item with
nothing to capture is a *skip*, not a failure
(`test_media_by_id_without_refs_reports_skip`). One failed download
fails its item but never the batch, and refs captured before the failure
keep their files (`test_media_continues_past_failures_and_exits_nonzero`).

| Key | Meaning |
| --- | --- |
| `captured` / `skipped` / `failed` | batch counts (per item) |
| `results[]` | per-item `{id, status, ...}`; `files` lists captured root-relative paths, `error` is the first failed ref's message, `reason` explains a skip |

```console
$ scrolls media                       # one fetched arXiv item is pending
{"captured": 1, "skipped": 0, "failed": 0, "results": [{"id": "arxiv:1706.03762", "status": "captured", "files": ["media/arxiv/1706-03762-1.pdf"]}]}
[exit 0]

$ scrolls media                       # idempotent: nothing pending now
{"captured": 0, "skipped": 0, "failed": 0, "results": []}
[exit 0]

$ scrolls media x:1111                # this bookmark has no media refs
{"captured": 0, "skipped": 1, "failed": 0, "results": [{"id": "x:1111", "status": "skipped", "reason": "no media references to capture"}]}
[exit 0]
```

### `scrolls rm <id-or-url>...`

Remove items: the row, the rendered scroll, and captured media files —
the search index follows via the FTS delete trigger
(`test_removed_item_leaves_the_search_index`, `tests/test_remove.py`).
Each ref is an item id, or a URL resolved to the id `add` would mint —
normalization included, so any tracking-decorated spelling of the saved
URL is a valid handle (`test_rm_accepts_the_url_that_added_the_item`).
Files are deleted before the row, so an interrupted removal leaves a
re-runnable item, never orphan files
(`test_remove_rejects_paths_escaping_the_root` also locks the guard:
a recorded path escaping the library root fails its item before
anything is deleted). Batch semantics
(`test_rm_continues_past_failures_and_exits_nonzero`): per-ref results,
exit 1 if any ref failed.

Two things `rm` deliberately does not do (ADR 0027): KB pages
referencing the removed scroll stay until the next `scrolls kb`, and
there is no tombstone — an item still listed in a followed feed returns
on the next `sync`, so `unfollow` first when pruning a feed.

| Key | Meaning |
| --- | --- |
| `removed` / `failed` | batch counts (per ref) |
| `results[]` | per-ref `{ref, status, ...}`; on success `id`, `url` (the re-add receipt: `scrolls add <url>` re-registers the item), and `files` — deleted root-relative paths |

```console
$ scrolls rm x:3333                          # registered but never fetched
{"removed": 1, "failed": 0, "results": [{"ref": "x:3333", "id": "x:3333", "url": "https://x.com/karpathy/status/3333", "status": "removed", "files": []}]}
[exit 0]

$ scrolls rm https://x.com/simonw/status/2222     # by URL: files go too
{"removed": 1, "failed": 0, "results": [{"ref": "https://x.com/simonw/status/2222", "id": "x:2222", "url": "https://x.com/simonw/status/2222", "status": "removed", "files": ["scrolls/x/simonw-attention-is-all-you-need-still-holds-up-a-guide-to-reading-it-prope.md"]}]}
[exit 0]

$ scrolls rm x:2222 x:1111                   # x:2222 is already gone
{"removed": 1, "failed": 1, "results": [{"ref": "x:2222", "status": "failed", "error": "no such item: x:2222"}, {"ref": "x:1111", "id": "x:1111", "url": "https://x.com/karpathy/status/1111", "status": "removed", "files": ["scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md"]}]}
[exit 1]
```

## Reading the library

### `scrolls list [--source S] [--stage S] [--category C] [--tag T] [--concept K] [--fidelity F] [--drift D] [--stale-before ISO] [--stale-classification] [--stale-summary] [--limit N] [--stats]`

Every matching item as a summary array (full records: `scrolls show`).
An empty or uninitialized library prints `[]`
(`test_list_after_adds_prints_summaries`,
`test_list_before_init_prints_empty_array`). Summary keys: `id`,
`source`, `url`, `title`, `category`, `stage`, `saved_at`, the per-item
custody axes — `fidelity` (the custody tier — `full`/`partial`/`reference`,
ADR 0097/0100 — the same tier `scrolls search`/`scrolls facets fidelity` report),
`drift` (the custody **drift posture** — `verified`/`unverified`/`drifted`/
`rotted`/`error`, roadmap H58 — read from the verify ledger, the same posture
`scrolls related` hits and the `scrolls graph` node shape carry, and the exact
posture this row's `--drift` filter selects on; `unverified` when never
re-checked — `test_list_rows_carry_the_drift_posture`,
`test_list_row_drift_matches_the_drift_filter_value`), and `last_checked`
(the time axis of that posture — *when* the latest verdict was taken, the
verdict's `checked_at`, or `null` when never re-checked, roadmap H84 — so an
agent reads not just whether a source moved but as of when, and can pick a
`verify --stale-before ISO` boundary by inspection; equals this item's
`scrolls history` head `checked_at` —
`test_last_checked_reads_the_same_across_list_search_show`) — and `works`
(ADR 0101): the scholarly work(s) the item represents, `[]` unless it is
one of several saved forms of one work, in which case each entry names the
work's `doi`/`url`, the `canonical` form's id, whether this item
`is_canonical`, and the `representations` count. Membership is the
whole-library DOI clustering `scrolls works` reports — a filtered listing
(e.g. `--source arxiv`) still reports an item's full sibling count, even
when those siblings are filtered out of the rows shown. A row also carries
a derived `classification` block (`by` / `basis` / `ruleset`, plus `model`
for the LLM engine, and a `confidence` marker — `level` plus, for rules, a
`freshness`; see `classify`) when an engine recorded how the category was
produced — the same view `scrolls show` and the MCP twins surface; the key is
omitted entirely for an unclassified or user-set item, so the row's shape stays
stable (`test_list_omits_classification_for_an_unclassified_item`).

Filters combine with AND
(`test_list_filters_by_source_stage_and_category`): `--source` and
`--category` match exactly, `--stage` only accepts the three real
stages (a typo is a usage error, exit 2 —
`test_list_rejects_an_unknown_stage`), and `--category ""` selects
items *without* a category — the pool a batch `classify` would pick
up — mirroring `scrolls set`'s empty-clears convention. `--tag` and
`--concept` are membership facets over the JSON list columns (ADR 0059):
an item matches when the value is one of its tags (case-insensitive) or
concepts (matched by slug, so "BM25" and "bm25" agree), the same way
`scrolls related` compares them (`test_list_items_filters_by_tag`,
`test_list_items_filters_by_concept`). They carry no empty-string
overload — a value that nothing has prints `[]`.

`--fidelity F` is the **holdings-axis** filter — the companion of `--drift`'s
ledger-claim axis: a custody **fidelity tier** (`full`/`partial`/`reference`, a
closed vocabulary — a typo is a usage error, exit 2 —
`test_list_rejects_an_unknown_fidelity_tier`). It selects the items held at that
tier, derived per item by the same `items.get_fidelity`/`fidelity_tier` primitive
`scrolls facets fidelity` counts with — so the rows `--fidelity reference` returns
*total* `facets fidelity`'s `reference` count for the same scope
(`test_list_fidelity_rows_total_the_facets_fidelity_count`), the drill-from-the-
count companion to that aggregate (`facets fidelity` says *how many* are
reference-only, `list --fidelity reference` says *which ones* — the exact drill
the vision §3.2 names). Unlike `--drift` it reads **no ledger** — fidelity
is a pure function of the stored content columns — so it ANDs with every other
facet over the already-filtered rows (`--fidelity full --source web` is web's
full-fidelity holdings, `test_list_fidelity_composes_with_another_facet`). The
tier a row *shows* (its `fidelity` key) is exactly the tier it is *selected* by
(`test_list_row_fidelity_matches_the_fidelity_filter_value`). A valid tier nothing
is held at prints `[]`
(`test_list_fidelity_is_honestly_empty_for_a_tier_with_no_items`); under `--stats`,
`matched` is the post-fidelity count, so it equals the facet count, not the
library total (`test_list_fidelity_is_echoed_in_the_stats_scope`). The MCP twin
`list_scrolls(fidelity=)` carries the same selection
(`test_list_scrolls_filters_by_fidelity_tier`).

`--drift D` is a **ledger-derived** filter (read from the verify ledger, not a
stored column — the claim axis to `--fidelity`'s holdings axis): a custody **drift
posture** (`verified`/`unverified`/`drifted`/
`rotted`/`error`, a closed vocabulary — a typo is a usage error, exit 2 —
`test_list_rejects_an_unknown_drift_posture`). It selects the held items whose
latest ledger verdict maps to that posture, via the same `custody.drift_posture`
over `latest_events` that `scrolls facets drift` counts — so the rows `--drift
drifted` returns *total* `facets drift`'s `drifted` count for the same scope
(`test_list_drift_rows_total_the_facets_drift_count`). It is the drill-from-the-
count companion to that aggregate and the read-side sibling of `verify
--unverified`'s act-side selection: `facets drift` says *how many* are drifted,
`list --drift drifted` says *which ones*. A valid posture nothing is in prints
`[]` (`test_list_drift_is_honestly_empty_for_a_posture_with_no_items`); under
`--stats`, `matched` is the post-drift count, so it equals the facet count, not
the library total.

`--stale-before <ISO>` is the other ledger-derived filter: it selects the held
items whose *newest* verify-ledger verdict predates the boundary — the **stale
set**. It is the read-side sibling of `scrolls verify --stale-before` (the
act-side recheck), exactly as `--drift` is the read-side sibling of `scrolls
verify --drift`: both share the one `custody.items_checked_before` selector, so
the rows `list --stale-before B` shows are *exactly* the set `verify
--stale-before B` would re-capture (drill-from-the-window convergence,
`test_list_stale_before_enumerates_exactly_the_verify_stale_before_set`). A
never-checked item is trivially stale (included); the boundary itself is *fresh*
(the exclusive `< boundary`, the complement of the `checked_at >=` window
`history --since`/`export events --since` keep). The boundary normalizes through
the same `custody.parse_since` (a `Z` suffix / offset / date-only all work), so a
malformed value is a loud usage error (exit 2, validated before the store read —
`test_list_stale_before_rejects_a_malformed_boundary`), never a silently-empty
listing. It composes with the stored facets (window then scope) and `--drift`
(both ledger filters over one read), and each returned row's own `last_checked`
(H84) shows *why* it is stale (`test_list_stale_before_selects_the_stale_set`).

`--stale-classification` is the **enrichment**-axis read enumeration — the
counterpart of `--drift` on the *drift* axis (roadmap H185). It is a flag (not a
ledger filter): it selects the held items whose rules-classified category the
*live* ruleset would no longer reproduce — the **stale-enrichment set** — by
reading each item's own `provenance`, via the same `classify.stale_classifications`
selector `scrolls classify --stale` acts on and `scrolls doctor`'s
`custody.enrichment.stale` counts. So the rows it returns are *exactly* the items
that refresh acts on, and they **total** `doctor`'s `custody.enrichment.stale`
(drill-from-the-count convergence, `test_list_stale_classification_rows_total_the_doctor_aggregate`):
where `doctor` says *how many* categories are stale and which sources hold them,
`list --stale-classification` says *which items* — the read-side sibling of the
`classify --stale` act, exactly as `list --drift` is the read-side sibling of
`verify --drift`. It ANDs with the stored facets, so `--stale-classification
--source S` narrows to one source's refresh debt and totals `doctor`'s
`enrichment.by_source[S]` (`test_list_stale_classification_ands_with_other_facets`).
LLM classifications, unfingerprinted (pre-H20) classifications, and user-set
categories are *not* stale (each is a different re-derivability axis or a user
override that always wins — see `classify --stale`), so they are never returned.
A library with nothing stale prints `[]` — honest absence, never an error
(`test_list_stale_classification_is_honestly_empty_when_nothing_stale`); under
`--stats` the flag is echoed in `scope` only when honored (the `None`-is-pruned
convention), and `matched` is the post-filter count.

`--stale-summary` is the **summary**-axis read enumeration — the sibling of
`--stale-classification` on the LLM-summary axis (roadmap H189). It is a flag too:
it selects the held items that belong to a concept whose stored LLM summary the
*live* members would no longer reproduce — the **stale-summary set** — via the
same `kb_llm.eligible_concepts` + `is_stale_summary` predicate `scrolls kb --stale`
refreshes on and `scrolls doctor`'s `custody.summaries` reports. So the rows it
returns are *exactly* the members a `kb --stale` refresh's clusters span: where
`doctor` says *which concepts* are stale and which sources hold them,
`list --stale-summary` says *which scrolls* drive them stale — the read-side
sibling of the `kb --stale` act (`test_list_stale_summary_lists_the_members_of_the_doctor_stale_concepts`).
Unlike the other three filters it is **not** item-local: summary staleness is a
property of a *concept* over its whole membership, so the stale-member set is
computed over the **whole library** and then intersected with the filtered rows.
That intersection makes it AND with the stored facets *and* carry the H171
attribution: a multi-source stale cluster lists **every** member, so
`--stale-summary --source S` returns S's members of the clusters S participates in
— equal to the S-members `kb --stale --source S` would refresh
(`test_list_stale_summary_ands_with_source_carrying_the_h171_attribution`). An
item belonging to several stale concepts appears once (deduped by id). A current
or never-summarized concept contributes nothing (a current summary is a no-op, a
never-summarized eligible concept is generation not refresh — see `kb --stale`),
so a library with nothing stale prints `[]` — honest absence, never an error
(`test_list_stale_summary_is_honestly_empty_when_nothing_stale`); under `--stats`
the flag is echoed in `scope` only when honored, and `matched` is the post-filter
member count.

By default the listing is uncapped — every item in scope, oldest saved
first. `--limit N` caps it to the first `N`; `--stats` then wraps the
array in the scope-honest `{scope, stats, results}` envelope (the
completeness contract G2) so a reader holding only the result can tell a
capped slice from the whole scope. `--stats` is opt-in: without it the
output is the bare array unchanged (`test_list_stats_is_opt_in_default_stays_a_bare_array`).
See the contract section above for the envelope's shape and guarantees.

The `--stats` envelope's `stats` block also carries a `custody` member (roadmap
H98): the `custody.custody_counts` tally — fidelity-tier and drift-posture
counts — over the **matched** scope (the full match set the cap may have hidden,
not just the returned page), so a reader paging results sees "of the N matched,
how much is held in full and how much has drifted" without a second `facets`
call. It is the browse-surface counterpart of the `graph` `stats.custody` block,
built from the same shared tally, so for a filter-only `list` scope it equals
`facets fidelity`/`drift` for the same filters by construction
(`test_list_stats_custody_member_converges_with_facets`); the tier/posture counts
sum to `stats.matched`.

```console
$ scrolls list
[{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "category": "technique", "stage": "fetched", "saved_at": "2026-06-04T04:27:46+00:00", "fidelity": "full", "drift": "unverified", "last_checked": null, "works": []}, {"id": "x:2222", ...}, {"id": "arxiv:1706.03762", ..., "title": null, "stage": "detected", ...}, {"id": "x:3333", ...}]
[exit 0]

$ scrolls list --source x --category technique
[{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "category": "technique", "stage": "fetched", "saved_at": "2026-06-04T04:27:46+00:00", "fidelity": "full", "works": []}]
[exit 0]

$ scrolls list --source x --limit 1 --stats
{"scope": {"source": "x", "limit": 1}, "stats": {"returned": 1, "matched": 2, "truncated": true, "custody": {"tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"verified": 0, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0}}}, "results": [{"id": "x:1111", ...}]}
[exit 0]

$ scrolls facets drift                      # the aggregate: how many at each posture
{"facets": {"drift": [{"value": "unverified", "count": 3}, {"value": "drifted", "count": 1}]}}
$ scrolls list --drift drifted              # drill to the rows: which one drifted
[{"id": "arxiv:1706.03762", "source": "arxiv", ..., "fidelity": "full", "works": []}]
[exit 0]

$ scrolls doctor | jq .custody.enrichment.stale   # the aggregate: how many categories are stale
2
$ scrolls list --stale-classification             # drill to the rows: which items to refresh
[{"id": "x:1111", ...}, {"id": "arxiv:1706.03762", ...}]
$ scrolls list --stale-classification --source x  # one source's refresh debt
[{"id": "x:1111", ...}]
[exit 0]

$ scrolls doctor | jq '.custody.summaries.items | length'   # the aggregate: how many concepts are stale
2
$ scrolls list --stale-summary                    # drill to the members: which scrolls drive them stale
[{"id": "wikipedia:bm25", ...}, {"id": "web:fts", ...}, {"id": "arxiv:1706.03762", ...}]
$ scrolls list --stale-summary --source web       # one source's members of the stale clusters
[{"id": "web:fts", ...}]
[exit 0]
```

*(in the bare-array calls, entries after the first are elided here for
width — every entry has the same nine keys. In the `--stats` call,
`matched: 2 > returned: 1` marks the listing truncated below the cap.)*

### `scrolls facets [field] [--source S] [--category C] [--stage ST] [--tag T] [--concept K]`

The filterable vocabulary with item counts — the browse half of the
search/browse pair (ADR 0080). `list`/`search`/`context` *narrow* by
`--source`/`--category`/`--tag`/`--concept`; `facets` *enumerates* what
those values can be, so an agent learns the library's real categories,
tags, and concept slugs before filtering. Output is
`{"facets": {dimension: [{"value", "count", …}, …]}}`; with no `field`,
every dimension (`sources`, `categories`, `tags`, `concepts`, `fidelity`,
`drift`, `method`, `content-duplicate`) is reported, in that order, and a
`field` narrows the
payload to that one (`test_facets_reports_every_dimension`,
`test_facets_single_field_returns_only_that_dimension`). An empty or
uninitialized library reports every dimension as `[]`
(`test_facets_uninitialized_library_is_empty_but_well_shaped`); an
unknown `field` is a usage error, exit 2
(`test_facets_rejects_an_unknown_field`).

Each list is ranked by count descending, then value ascending, and
capped at `--limit` (default 20) per dimension
(`test_facets_limit_caps_each_dimension`). Sources and categories are
the scalar columns; the unclassified pool surfaces as the `""` category
value, round-trippable to `--category ""`
(`test_categories_report_unclassified_pool_as_empty_string`). Tags and
concepts are grouped exactly as the `--tag`/`--concept` filters and the
KB pages group them — tags case-folded, concepts by slug, the smallest
spelling the display form
(`test_tags_merge_case_insensitively_with_smallest_spelling`,
`test_concepts_merge_by_slug_and_expose_the_slug`); a concept also
carries the `slug` you would pass to `--concept`, and two spellings of
one concept on one item count it once
(`test_repeated_spellings_on_one_item_count_it_once`). The same optional
facets that scope `search` scope the counts here, so
`scrolls facets concepts --source arxiv` answers "which concepts do my
arXiv papers carry?".

`fidelity`, `drift`, and `method` are *derived* dimensions, not stored
columns. `fidelity` counts items by custody tier (`full`/`partial`/`reference`,
ADR 0097), the same tier `search`/`list` carry per item. `drift` counts them by
custody **drift posture** read from the verify ledger
(`verified`/`unverified`/`drifted`/`rotted`/`error`, roadmap H48) — the browse
aggregate of the same `custody.drift_posture` over `latest_events` that
`doctor`'s `custody.drift` block and the scope custody headlines (H45/H47) read,
so `scrolls facets drift` converges with them for the same scope (`verified` ≡
doctor's `unchanged`; a never-checked item is counted as `unverified`, never
silently dropped). It answers "how much of my library has drifted, and how much
has never been re-checked?" (`test_drift_counts_by_posture`,
`test_drift_facet_converges_with_doctor_custody_drift`). `method` counts
them by how each held category was produced — `rules-v1` / `llm-v1` for an
engine-classified item, `user-set` for a hand-set category with no engine
stamp, and `unclassified` for none — the aggregate counterpart of the
per-item `classification` view (roadmap H20/H26), built from the same
`items.classification_view` derivation so the counts and the per-item view
never disagree. It answers "how much of my library was auto-classified vs
set by hand vs still unclassified?", and completes the search ≡ list ≡ MCP
≡ facets parity on the aggregate axis
(`test_method_counts_by_how_the_category_was_produced`,
`test_facets_method_buckets_how_categories_were_produced`).

`content-duplicate` partitions the held items into `duplicate`/`unique` by
whether each carries a **byte-identical sibling** — the same bytes held under
another id (the content-identity custody shape, roadmap H325). It is the browse
aggregate of the same `items.content_duplicate_index` that `list`/`search
--content-duplicate` (H338) select on and `doctor`'s `custody.content_duplicates`
counts, so the `duplicate` count converges with both over the same scope: over the
whole library it equals `doctor`'s `total_items` (the *M* in the `maintain`
`_Duplicates:_` headline), and over any scope it equals the rows the
`--content-duplicate` drill returns (drill-from-the-count, the `drift` ↔ `facets
drift` twin on the content-identity axis). The sibling fold is **whole-library**
even under `--source` (a content group spans sources, the H328 cross-source rule),
so `scrolls facets content-duplicate --source S` reports how many of S's items have
a byte-identical sibling held *anywhere*. `unique` covers both a genuinely lone
capture and a NULL/empty-`content_hash` reference item (which holds no bytes to
match); a clean library reports only `unique` (the omit-when-clean shape — no empty
`duplicate` bucket). Report-only, never a merge — the facet names what an operator
may dedup, the tool never does (raw is sacred). It answers "how redundant is my
library — how many holdings are byte-for-byte copies of another?"
(`test_facets_content_duplicate_partitions_and_drills_from_the_count`,
`test_content_duplicate_facet_converges_with_doctor_and_the_drill_filter`).

```console
$ scrolls facets
{"facets": {"sources": [{"value": "x", "count": 3}, {"value": "arxiv", "count": 1}, {"value": "web", "count": 1}, {"value": "wikipedia", "count": 1}, {"value": "youtube", "count": 1}], "categories": [{"value": "", "count": 3}, {"value": "paper", "count": 1}, {"value": "reference", "count": 1}, {"value": "technique", "count": 1}, {"value": "tutorial", "count": 1}], "tags": [{"value": "Databases", "count": 2}, {"value": "Reading", "count": 1}, {"value": "cs.CL", "count": 1}, {"value": "cs.LG", "count": 1}, {"value": "fts", "count": 1}, {"value": "sqlite", "count": 1}], "concepts": [{"value": "full-text search", "count": 2, "slug": "full-text-search"}, {"value": "Computation and Language", "count": 1, "slug": "computation-and-language"}, {"value": "Database engines", "count": 1, "slug": "database-engines"}, {"value": "Machine Learning", "count": 1, "slug": "machine-learning"}, ...]}}
[exit 0]

$ scrolls facets concepts --source arxiv
{"facets": {"concepts": [{"value": "Computation and Language", "count": 1, "slug": "computation-and-language"}, {"value": "Machine Learning", "count": 1, "slug": "machine-learning"}]}}
[exit 0]
```

*(the first call's `concepts` list is elided for width — the unclassified
`x:3333`/`youtube`/`web` items and the `""` category show the pool a
batch `classify` would pick up)*

### `scrolls show <id>`

One item in full: every `ScrollItem` field
(`docs/architecture.md` → "The data model"), with list fields always
present as JSON arrays (`test_show_prints_full_item_json`). Unset fields
are `null`, not omitted. The id may also be the item's URL — see
Conventions (`test_show_accepts_item_url`). Beside the raw record, `show`
adds the derived per-item custody axes the browse rows carry (roadmap H61/H84):
`fidelity` (the custody tier — `full`/`partial`/`reference`), `drift` (the
custody **drift posture** — `verified`/`unverified`/`drifted`/`rotted`/`error`,
from the item's latest verify-ledger verdict; `unverified` when never
re-checked), and `last_checked` (*when* that verdict was taken, or `null` when
never re-checked — the time axis of the same picture) — so the inspect surface
reads the same per-item custody picture as `scrolls list`/`search` for the same
item (`test_show_carries_the_two_custody_axes`,
`test_show_custody_axes_match_the_list_row`,
`test_show_carries_the_last_checked_timestamp`). When an engine classified the
item, `show` also adds a derived `classification` block (`by` / `basis` /
`ruleset`, plus `model` for the LLM engine, and a `confidence` trust/recency
marker — see `classify`) alongside the raw `provenance` keys — the same view
`scrolls list` and the MCP `get_scroll` / `list_scrolls` twins surface, so how
the category was produced *and how much to trust it* read identically wherever
it appears (`test_show_surfaces_the_classification_method`).

```console
$ scrolls show x:1111
{"id": "x:1111", "source": "x", "url": "https://x.com/karpathy/status/1111", "saved_at": "2026-06-04T04:27:46+00:00", "source_id": "1111", "canonical_url": null, "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "author": "Andrej Karpathy (@karpathy)", "published_at": "2026-06-01T15:34:00+00:00", "raw_text": "{\"id\": \"1111\", \"tweetId\": \"1111\", …}", "extracted_text": "SQLite FTS5 is criminally underrated for local search.", "summary": null, "category": "technique", "domain": "databases", "tags": [], "concepts": [], "links": ["https://sqlite.org/fts5.html"], "media": [], "content_hash": "sha256:da27b0…", "markdown_path": "scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md", "provenance": {"adapter": "fieldtheory-import", "fetched_at": "2026-06-12T20:29:15+00:00", "extraction_method": "fieldtheory:bookmarks.jsonl"}, "stage": "rendered"}
[exit 1 if no such item, else 0]
```

*(the `raw_text` and `content_hash` values are elided here for width;
the real output is one complete compact JSON document)*

```console
$ scrolls show x:9999
{"error": "no such item: x:9999"}
[exit 1]
```

### `scrolls search <query> [--limit N] [--source S] [--category C] [--stage ST] [--tag T] [--concept K] [--fidelity F] [--drift D] [--strength W] [--stats]`

FTS5 BM25 over title/summary/extracted text, title weighted highest
(`src/scrolls/search.py`, `tests/test_search.py`). Query tokens are
quoted and AND-ed, so arbitrary agent input never hits FTS5 syntax
errors. `score` is SQLite's `bm25()`: results are ordered best-first and
**more negative means a stronger match**. Default limit 20
(`test_search_respects_limit_flag`). No matches prints `[]`; a blank
query is an error (`test_search_blank_query_is_an_error`).

The raw `score` is opaque — a negative float whose magnitude depends on the
query and corpus, so it tells an agent the *order* but not *why*. Each hit
therefore also explains its own rank: **`matched_fields`** names the indexed
fields the query terms actually landed in, in BM25-weight order
(`title`/`summary`/`extracted_text`), and **`match_strength`** distils that into
the qualitative confidence those weights imply — `strong` for a title hit,
`moderate` for a summary hit, `weak` for a body-only hit
(`test_search_hit_explains_a_title_match`,
`test_search_hit_explains_a_body_only_match`,
`test_search_hit_explains_a_summary_match_as_moderate`). The fields are read by
column-restricted FTS matches over the already-ranked hit rowids, never by
hauling a match's body text, and an *any-token* (OR) test per field, so a hit
whose tokens split across columns — one in the title, another in the body —
names *both* fields it landed in rather than reporting an empty set
(`test_search_explains_a_match_split_across_columns`). Because the explanation
is grounded in the very column weights that produced the rank, it is custody's
ranking signal (provenance/holdings, not engagement — vision §3.5), not
an invented relevance score.

`--source`, `--category`, `--stage`, `--tag`, and `--concept` scope the
ranked match (`test_search_filters_by_source_and_category`,
`test_search_filters_by_tag`, `test_search_filters_by_concept`, ADRs
0058/0059): they AND with the FTS match and with each other and leave the
BM25 order untouched. `--source` and `--stage` match exactly (`--stage`
choices: `detected`/`fetched`/`rendered`); `--category` matches exactly
too, except an empty value (`--category ""`), which selects unclassified
items — the same convention `scrolls list`/`scrolls set` use. `--tag` and
`--concept` are membership facets over the JSON list columns — `--tag`
case-insensitive, `--concept` by slug, as `scrolls related` compares them
— with no empty-string overload. A facet that excludes every hit prints
`[]`, not an error.

`--fidelity F` is the **holdings-axis** filter on the ranked surface — the
search twin of `scrolls list --fidelity` (ADR 0097): a custody **fidelity tier**
(`full`/`partial`/`reference`, the same closed vocabulary — a typo is a usage
error, exit 2 — `test_search_rejects_an_unknown_fidelity_tier`). It keeps only
the matches the library holds at that tier, derived from the same content-presence
flags each hit's own `fidelity` key is read off, so a hit is *selected* by exactly
the tier it *shows* (`test_search_fidelity_hits_match_the_filter_value`). The one
difference from `list --fidelity`: `list` has no cap, so it sieves its loaded rows
in Python; `search` applies a ranked `LIMIT`, so the tier must scope the *ranked*
selection — it ANDs into the SQL **before** the cap (via the `scrolls_fidelity`
UDF over the presence booleans, never the body text), so `--fidelity full --limit
5` returns the *top five full-fidelity matches*, not the full ones among the top
five (`test_search_fidelity_applies_before_the_limit`). It composes with every
other facet (`--fidelity full --source arxiv` is arxiv's full-fidelity matches,
`test_search_fidelity_composes_with_source`); `count_matches` applies the same
clause, so under `--stats` the `matched` denominator counts only the kept tier and
the truncation marker is never inflated by tiers it never showed
(`test_search_fidelity_scope_echo_and_truncation_denominator`). The MCP twin
`search_scrolls(fidelity=)` carries the same selection
(`test_search_scrolls_filters_by_fidelity_tier`).

`--drift D` is the **ledger-claim-axis** filter on the ranked surface — the
companion of `--fidelity`'s holdings axis and the search twin of `scrolls list
--drift` (roadmap H58): a custody **drift posture**
(`verified`/`unverified`/`drifted`/`rotted`/`error`, the same closed vocabulary
— a typo is a usage error, exit 2 — `test_search_rejects_an_unknown_drift_posture`).
It keeps only the matches whose latest verify verdict reads at that posture, the
same posture each hit's own `drift` key shows, so a hit is *selected* by exactly
the posture it *shows* (`test_search_drift_hits_match_the_filter_value`). The
design difference from `--fidelity`: a fidelity tier is a pure function of an
item's own content columns, but a drift posture is read from the **verify ledger**,
so the filter cannot ride a content-column UDF. It instead ANDs the `scrolls_drift`
UDF over the item's *latest `custody_events` verdict* (a correlated subquery for
the most-recent row, `NULL` → `unverified`) into the SQL **before** the cap — so,
like `--fidelity`, it scopes the *ranked* selection (`--drift verified --limit 5`
returns the top five verified matches, not the verified ones among the top five —
`test_search_drift_applies_before_the_limit`), which `list --drift` (no cap)
sieves in Python instead. Both `scrolls_fidelity` and `scrolls_drift` delegate to
the same primitives the per-hit fields are read off (`fidelity_tier` /
`posture_from_status`), so the filter and the row never disagree. It composes with
every other facet, including `--fidelity` (the two custody axes AND independently —
`--fidelity full --drift drifted` is the full-fidelity matches that have drifted,
`test_search_drift_composes_with_fidelity`); `count_matches` applies the same
clause, so under `--stats` the `matched` denominator counts only the kept posture
(`test_search_drift_scope_echo_and_truncation_denominator`). The per-posture
totals across the closed vocabulary partition the query's matches — they sum to the
unfiltered match count (`test_search_drift_partitions_the_query_matches`), the
drill-from-`facets drift` convergence on the ranked surface. The MCP twin
`search_scrolls(drift=)` carries the same selection
(`test_search_scrolls_filters_by_drift_posture`).

`--strength W` is the **rank-axis** filter on the ranked surface — the act-axis
companion of the `match_strength` explanation and the rank sibling of
`--fidelity`/`--drift` (roadmap H314): a match-strength **band**
(`strong`/`moderate`/`weak`, the same closed vocabulary — a typo is a usage error,
exit 2 — `test_search_unknown_strength_band_is_exit_2`). Unlike the *categorical*
custody filters, `--strength` is a **threshold** (at or above): `--strength strong`
keeps only the matches whose query lands in the **title**, `--strength moderate`
keeps title-or-summary matches, and `--strength weak` keeps every match — because a
hit reads `match_strength == band` exactly when its query lands in that band's
column *or* a higher-weighted one (`test_search_strength_is_a_threshold_at_or_above_the_band`).
Like `--fidelity`/`--drift` it ANDs into the SQL **before** the cap, so it scopes
the *ranked* selection (the top hits at that strength) and `count_matches` stays the
honest uncapped denominator (`test_search_strength_applies_before_the_limit`); it
rides a column-restricted `items_fts` sub-match over the columns at or above the
band — the same any-token (OR) test the per-hit `match_strength` is read off — so a
hit is *selected* by exactly the field-landing it *shows*
(`test_search_strength_filter_agrees_with_the_per_hit_strength`). It composes with
every other facet, including `--fidelity` (the rank and holdings axes AND
independently, `test_search_strength_composes_with_fidelity`). Because the bands are
ordered, the `--strength <band>` matched count equals the sum of the
`stats.strength` tally's bands *at or above* `<band>` — the (cumulative)
drill-from-strength convergence (`test_search_strength_drills_from_the_unfiltered_tally`).
The MCP twin `search_scrolls(strength=)` carries the same selection
(`test_search_scrolls_filters_by_match_strength`).

Hit keys: `id`, `source`, `title`, `url`, `stage`, `score`, `snippet`
(matches bracketed, `…` for elided context), the rank explanation —
`matched_fields` (the indexed fields the query landed in, BM25-weight order) and
`match_strength` (`strong`/`moderate`/`weak`, the strongest field's band) — the per-item custody axes —
`fidelity` (the custody tier — `full`/`partial`/`reference`, ADR 0097/0100 — at
which the library still holds the match, the same tier `scrolls list` and
`scrolls facets fidelity` report), `drift` (the custody **drift posture** —
`verified`/`unverified`/`drifted`/`rotted`/`error`, roadmap H58 — read from the
verify ledger, the same posture `scrolls list` rows, `scrolls related` hits, and
the `scrolls graph` node shape carry; `unverified` when never re-checked —
`test_search_hits_carry_their_custody_drift_posture`), and `last_checked` (*when*
that verdict was taken, or `null` when never re-checked — the time axis of the
picture, roadmap H84, `test_search_hits_carry_their_last_checked_timestamp`) — so
a hit says not just *what* matched but how much of it you hold, whether the source
has drifted out from under the capture, *and* as of when — and `works` (ADR 0101): the scholarly work(s) the hit
represents, `[]` for most hits but, when two hits are the same work (an
arXiv preprint and its published Crossref record), each carries the work's
`doi`/`url`, the `canonical` form's id, whether this hit `is_canonical`,
and the `representations` count, so an agent collapses the duplicate and
follows the canonical instead of treating the two as unrelated matches.
Membership is the whole-library DOI clustering `scrolls works` reports, so
a hit knows its work even when its sibling ranks below the limit.

When an engine produced the hit's category, the hit also carries a derived
`classification` block — `by` / `basis` / `ruleset` for the rules engine,
`by` / `model` for the LLM engine — the *same* view `scrolls list`/`show`
surface (roadmap H26), so how a category was produced reads identically
whether an agent browsed to the item or searched for it. It is derived
per-hit from the row's own provenance, so the `--stats` count and truncation
marker are untouched (still scope-honest, G2). A user-set or unclassified
hit omits the key entirely — the honest-absence row shape `list` keeps
(`test_search_surfaces_the_classification_method`,
`test_search_omits_classification_for_an_unclassified_item`,
`test_classification_view_is_identical_across_browse_surfaces`).

`--stats` wraps the ranked array in the scope-honest `{scope, stats,
results}` envelope (the completeness contract G2): `scope` echoes the
query and every facet honored, and `stats` reports `returned`, `matched`
(every match in scope, counted past the cap — `src/scrolls/search.py`
`count_matches`), and `truncated` (`matched > returned`). It resolves the
`len == limit` ambiguity — "the top 20 of 200" is no longer indistinguishable
from "all 20 matches" to a reader that didn't make the call. Opt-in:
without it the output is the bare array unchanged
(`test_search_stats_is_opt_in_default_stays_a_bare_array`,
`test_search_stats_envelope_echoes_scope_and_marks_truncation`).

`stats` also carries a `custody` member (roadmap H98) — the `custody_counts`
tally over the **matched** scope (the full query-matched set, not just the
returned page), so a reader sees the custody of *everything that matched this
query*, not only the top hits it paged. Each hit already carries its own
`fidelity`/`drift` (the per-item parity, roadmap H58), so the envelope folds
those; the tally re-reads the full match set only when the cap actually hid rows
(truncated), reusing the page otherwise. The tier/posture counts sum to
`stats.matched` (`test_search_stats_custody_covers_the_matched_scope_past_the_cap`).

`stats` also carries a `strength` member (roadmap H313) — the rank-quality
histogram `{strong, moderate, weak}` over the same **matched** scope, beside
`custody`. Each hit already carries its own `match_strength` (the explanation
above), so the envelope folds those into per-band counts that **partition** the
matched scope — they sum to `stats.matched`, so a reader sees not just *how much*
matched but the *rank quality* of it ("12 matched: 2 strong, 4 moderate, 6 weak"),
and the `--strength <band>` count is the cumulative sum of the bands at or above
`<band>` (`test_search_stats_strength_tallies_the_matched_scope`,
`test_search_stats_strength_covers_the_matched_scope_past_the_cap`). Like `custody`
it is a `search`-only axis (only a ranked hit has a `match_strength`), so `list
--stats` carries no `strength` block
(`test_search_stats_strength_is_opt_in_absent_from_the_bare_array`).

```console
$ scrolls search "sqlite fts5"
[{"id": "x:1111", "source": "x", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "url": "https://x.com/karpathy/status/1111", "stage": "rendered", "score": -2.9315057596986334, "snippet": "@karpathy: [SQLite] [FTS5] is criminally underrated for local search.", "fidelity": "full", "works": [], "matched_fields": ["title", "summary", "extracted_text"], "match_strength": "strong"}]
[exit 0]

$ scrolls search "attention transformer"
[{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered", "score": -3.40e-06, "snippet": "We propose the [Transformer] based on [attention] mechanisms.", "fidelity": "full", "works": [{"doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222", "canonical": "crossref:10.5555/3295222", "is_canonical": false, "representations": 2}]}, {"id": "crossref:10.5555/3295222", "source": "crossref", "title": "Attention Is All You Need", "url": "https://doi.org/10.5555/3295222", "stage": "fetched", "score": -3.40e-06, "snippet": "We propose the [Transformer] based on [attention] mechanisms.", "fidelity": "partial", "works": [{"doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222", "canonical": "crossref:10.5555/3295222", "is_canonical": true, "representations": 2}]}]
[exit 0]

$ scrolls search "sqlite fts5" --source arxiv
[]
[exit 0]

$ scrolls search "sqlite fts5" --limit 1 --stats
{"scope": {"query": "sqlite fts5", "limit": 1}, "stats": {"returned": 1, "matched": 3, "truncated": true, "custody": {"tiers": {"full": 2, "partial": 1, "reference": 0}, "drift": {"verified": 0, "unverified": 3, "drifted": 0, "rotted": 0, "error": 0}}, "strength": {"strong": 1, "moderate": 2, "weak": 0}}, "results": [{"id": "x:1111", ...}]}
[exit 0]

$ scrolls search "sqlite fts5" --strength strong   # only matches whose query is in the title
[{"id": "x:1111", "source": "x", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "url": "https://x.com/karpathy/status/1111", "stage": "rendered", "score": -2.9315057596986334, "snippet": "@karpathy: [SQLite] [FTS5] is criminally underrated for local search.", "fidelity": "full", "works": [], "matched_fields": ["title", "summary", "extracted_text"], "match_strength": "strong"}]
[exit 0]

$ scrolls search "sqlite fts5" --source arxiv --stats
{"scope": {"query": "sqlite fts5", "source": "arxiv", "limit": 20}, "stats": {"returned": 0, "matched": 0, "truncated": false, "custody": {"tiers": {"full": 0, "partial": 0, "reference": 0}, "drift": {"verified": 0, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0}}, "strength": {"strong": 0, "moderate": 0, "weak": 0}}, "results": []}
[exit 0]

$ scrolls search "   "
{"error": "search query has no searchable tokens"}
[exit 1]
```

The last `--stats` call is the honest empty: nothing matched, but the
result still names the scope it checked (`query`, `source=arxiv`), so it
can never be misread as "the library holds nothing about sqlite."

### `scrolls related <id> [--fidelity TIER] [--drift POSTURE] [--strength BAND] [--content-duplicate] [--limit N] [--stats]`

Deterministic, explainable connections (IDEAS.md §10,
`tests/test_related.py`): **identical content** (two items hold byte-identical
content under different ids — the same bytes saved from two URLs, a mirror, a
cross-post, or one work captured by two source adapters, matched on a shared
non-null `content_hash`; the H325 content-identity custody shape on the
relationship surface, roadmap H326), same work (a shared DOI), link edges in
either direction (resolved through source detection, so a tweet linking to
`arxiv.org/abs/X` finds item `arxiv:X`), shared concepts, shared tags, same
category/domain as weak corroboration. A byte-identical edge is the *strongest*
possible bond — stronger than even a same-work edge (`identical content`
outranks `same work`, since byte-identity beats shared scholarly identity) — and
is **complementary** to it: two items can be both byte-identical *and* share a
DOI, and both `reasons` then fire (the same bytes, *and* the same work), not
double counting. `score` is an integer (higher = more connected) and
every hit carries its `reasons` plus a one-word `relation_strength` band
(`strong`/`moderate`/`weak`, roadmap H322) — the relationship-surface analogue of
`search`'s `match_strength`, the legible companion the opaque integer `score`
lacks: it is the band of the *strongest contributing signal class* (an
identical-content, same-work, or link edge → `strong`, shared concepts/tags →
`moderate`, same category/domain → `weak`), grounded in the relation point weights
so it names the *kind* of the strongest bond, not the multiplied magnitude (three
shared tags, score 6, is still a `moderate` topical bond, not an identity one). Beside it travels the neighbour's
`fidelity` tier
(`full`/`partial`/`reference`, ADR 0097/0100), its custody `drift` posture
(`verified`/`unverified`/`drifted`/`rotted`/`error`, roadmap H56, read from the
verify ledger), and `last_checked` — *when* that drift verdict was taken, or
`null` when never re-checked (roadmap H86) — so following an edge tells you how
much of the item you land on the library holds, whether that source has drifted
out from under the capture, *and as of when*: the same per-item custody picture
the `graph` node shape and the browse rows carry. Default
limit 10. Unknown id is an error envelope on stderr.

`--fidelity TIER` and `--drift POSTURE` scope the neighbourhood to one custody
value per axis — the relationship-surface twin of `list`/`search`'s
`--fidelity`/`--drift` (roadmap H254), completing the custody-filter family
across the last un-filtered read surface. `--fidelity full` keeps only the
neighbours you can re-derive offline; `--drift drifted` only the ones whose
source has moved. Each filter folds the *same* per-hit field it reads off the
row (`fidelity`/`drift`), so a neighbour is selected by exactly the value it
shows, and the two axes AND. The sieve runs **before** `--limit` (the `list`
sieve shape, not `search`'s before-LIMIT ranking), so the cap returns the
top-`k` neighbours *at that value* — not the matching ones among the top-`k`.
The vocabulary is closed (`full`/`partial`/`reference`;
`verified`/`unverified`/`drifted`/`rotted`/`error`); a typo is a usage error
(exit 2), never a silent empty neighbourhood. With `--stats`, the echoed
`scope` names the honored filters and `matched` counts the *filtered* set, so
`related --fidelity X --stats` totals the tier-X count in an unfiltered
`related --stats`'s neighbourhood tally
(`test_related_custody_filter_rows_drill_from_the_neighbourhood_tally`).

`--strength BAND` keeps only neighbours related at that strength band **or
stronger** (roadmap H324) — the relationship-surface twin of `search --strength`
on the rank axis. Threshold (at or above): `--strength strong` keeps only the
identity-/citation-grade bonds (same-work and link edges), `--strength moderate`
adds shared concepts/tags, `--strength weak` keeps every neighbour. It folds the
*same* per-hit `relation_strength` (H322) a hit shows, so a neighbour is kept by
exactly the band it reports; the sieve runs **before** `--limit` (the `--fidelity`
sieve shape), so the cap returns the top neighbours *at that strength*, and it
**ANDs** with `--fidelity`/`--drift` (e.g. `--strength strong --fidelity full` =
the strongly-related neighbours you can re-derive offline). Closed vocabulary
(`strong`/`moderate`/`weak`); a typo is a usage error (exit 2). With `--stats` the
`matched` count drills from the unfiltered `strength` tally — `--strength <band>`
totals the bands at or above `<band>` (threshold, strongest-first prefix)
(`test_cli_related_strength_drills_from_the_tally`,
`test_related_strength_ands_with_fidelity`).

`--content-duplicate` keeps only neighbours the library holds a **byte-identical
copy of under another id** (roadmap H350) — the relationship-surface twin of
`list`/`search --content-duplicate` (H338), completing the content-identity
filter family across the read surfaces. A boolean flag (present/absent): a
neighbour is kept iff its own `content_duplicate_ids` is non-empty — its bytes
are also held under some *other* id. The sieve folds the **same** whole-library
`content_duplicate_index` `list`/`search --content-duplicate` select on and
`doctor`'s `custody.content_duplicates` count, so the three agree by
construction. Scope is **whole-library** (the H328 cross-source rule): the
byte-identical twin may live anywhere — under the anchor item itself, or in
another source — so a neighbour is kept by its library-wide redundancy, *not* by
how it relates to the anchor. This makes the filter **distinct from the
`identical content` edge**: that edge (a `reasons` entry) fires only when a
neighbour shares the *anchor's* bytes, whereas `--content-duplicate` keeps a
neighbour byte-identical to *any* other held item, even one outside the
neighbourhood. Report-only (raw is sacred, H325 — it names no merge). The sieve
runs **before** `--limit` (the `--fidelity` sieve shape), so the cap returns the
top neighbours *that are content-duplicates*, and it **ANDs** with
`--fidelity`/`--drift`/`--strength`. With `--stats` the flag rides the echoed
`scope` as a bare boolean and `matched` counts the filtered set
(`test_cli_related_content_duplicate_filters_the_rows`,
`test_find_related_content_duplicate_is_the_library_property_not_the_edge`,
`test_find_related_content_duplicate_sieves_before_the_cap`).

`--stats` wraps the array in the same scope-honest `{scope, stats,
results}` envelope `search`/`list` use (the completeness contract G2):
`scope` names the anchor `item`, the `limit`, and any
`--fidelity`/`--drift`/`--strength`/`--content-duplicate` filter honored (pruned
when absent), and
`stats` reports `returned`, `matched`
(every item that relates *within the active filters*, counted past the cap —
`src/scrolls/related.py` `count_related`), `truncated`, and a `custody`
tally (roadmap H99) — the same `{tiers, drift}` fidelity-tier/drift-posture
maps `search`/`list --stats` carry, here folded over the anchor's *related
neighbourhood* (the full scored set, pre-cap, excluding the anchor itself),
so a reader sees "of the N items related to this one, how much is held in
full and how much has drifted" without a second `facets` call. Each map sums
to `matched`. `stats` also carries a `strength` tally (roadmap H323) — the
`{strong, moderate, weak}` `relation_strength` histogram over that same matched
neighbourhood (the relation-axis analogue of `search --stats`'s `strength`,
roadmap H313), so a reader sees the relationship-quality distribution ("how many
neighbours are identity-/citation-grade bonds vs weak corroboration") in one call;
the bands sum to `matched`, the drill-from-tally tie behind `--strength`. Opt-in:
without it the output is the bare array unchanged
(`test_cli_related_stats_is_opt_in_default_stays_a_bare_array`,
`test_cli_related_stats_echoes_anchor_and_marks_truncation`,
`test_cli_related_stats_custody_tallies_the_matched_related_set`,
`test_cli_related_stats_carries_a_relation_strength_tally`).

```console
$ scrolls related x:2222
[{"id": "arxiv:1706.03762", "source": "arxiv", "title": null, "url": "https://arxiv.org/abs/1706.03762", "stage": "detected", "score": 5, "reasons": ["links to it"], "relation_strength": "strong", "fidelity": "reference", "drift": "unverified", "last_checked": null}]
[exit 0]

$ scrolls related x:2222 --limit 1 --stats
{"scope": {"item": "x:2222", "limit": 1}, "stats": {"returned": 1, "matched": 3, "truncated": true, "custody": {"tiers": {"full": 0, "partial": 0, "reference": 3}, "drift": {"verified": 0, "unverified": 3, "drifted": 0, "rotted": 0, "error": 0}}, "strength": {"strong": 3, "moderate": 0, "weak": 0}}, "results": [{"id": "arxiv:1706.03762", ...}]}
[exit 0]
```

### `scrolls graph [--all] [--content-duplicate]`

The whole-library link graph in one call (ADR 0044, `tests/test_graph.py`).
Where `related` scores *one* item's neighborhood, this resolves *every*
item's links into directed edges — `from → to` whenever a link inside one
saved item names another (a tweet citing a paper, a model's `arxiv:` tag,
a preprint's published DOI), with `via` the link that matched. Resolution
is the same two-sided, source-detecting match `related` uses (ADR 0023),
so the graph is exactly the connections `related` would find, materialized
at once. Nodes carry the `id`, `source`, `title`, `url`, `stage`, `fidelity`,
`drift`, `last_checked`, `content_duplicate_ids` shape — the full per-item custody
picture travels with the node: the `fidelity` tier (how much is held, ADR 0100),
the `drift` posture (whether the source moved, roadmap H56, read from the verify
ledger), `last_checked` (*when* that posture was taken, or `null` when never
re-checked, roadmap H86), and `content_duplicate_ids` (the *other* held ids
byte-identical to this node — its `content_hash` siblings, `[]` when uniquely held
or holding no content, roadmap H343) — the same custody picture a `related` hit,
`show`/`get_scroll`, and the browse rows carry, read through the same
`custody.drift_posture`/`custody.last_checked` over `latest_events` plus the
whole-scope `items.content_duplicate_index` fold (computed once, not per node), so
a node reads the same wherever it is reached and an agent walking the graph sees a
node's redundancy without a second `show`. The content-identity axis is
**report-only** — a node names its byte-identical twins, never a merge (raw is
sacred). Sorted by id; edges sorted by `(from, to)`.

Nodes are the *connected* items by default — `--all` widens it to every
item, isolated ones included. `stats.items` is the library total,
so `nodes`/`edges` read as connectivity against the whole; `stats.clusters`
counts the connected components with 2+ members — the link clusters the
KB's `graph.md` page renders (ADR 0062), so a singleton added by `--all` is
not counted (`test_cli_graph_stats_count_clusters`). An empty or
uninitialized library is an empty graph, exit 0.

`--content-duplicate` (roadmap H352) scopes the graph to nodes the library
holds a **byte-identical copy of under another id** — those whose
`content_duplicate_ids` is non-empty (the same whole-library
`items.content_duplicate_index` `doctor`'s `custody.content_duplicates`
counts) — the node-set analogue of `list --content-duplicate` lifted to the
relationship graph. The subgraph is **induced**: an edge survives only when
*both* its endpoints survive, so the result stays well-formed (no edge dangles
at a removed node) — and it drops edges from the *already-resolved* full graph
rather than re-resolving links over the kept subset, which could mint an edge
the full graph never had (`test_graph_content_duplicate_induces_never_re_resolves`).
Whole-library sibling scope (roadmap H328): a content group spanning two
clusters keeps both ends even with no edge between them
(`test_graph_content_duplicate_spans_components`). It is **report-only** — it
names the redundant nodes, never a merge — and **ANDs with `--all`** (the
default view shows only connected duplicate nodes; `--all` surfaces an isolated
duplicate pair too, `test_graph_content_duplicate_ands_with_all`). `stats`
then describes the scoped subgraph — `stats.items`/`stats.custody` count the
content-duplicate set, not the whole library
(`test_graph_content_duplicate_stats_describe_the_scoped_set`). A library with
no byte-identical holdings yields the honest empty subgraph, exit 0.

`stats.custody` is the graph-surface member of the custody-headline family
(`scrolls status`, the bundle/`context` briefings, `facets fidelity`/`drift`):
fidelity-tier and drift-posture count maps over the whole `stats.items` scope
(not just the connected nodes), so it is independent of `--all`
(`test_graph_stats_custody_is_independent_of_include_all`) and converges with
`doctor`'s `custody` block, `facets`, and the scope headlines for the same scope
(`test_graph_custody_block_converges_with_doctor`). Graph emits JSON, so the
counts travel directly — `verified` is the ledger `unchanged` (custody §2.4),
`unverified` the held items with no verdict.

`stats.custody.by_source` (roadmap H150) splits that whole-scope tally per
source — a `{source: {tiers, drift, coverage}}` map (sorted keys) over the same
`stats.items` scope, the graph-surface counterpart of the per-source `by_source`
on `scrolls status` (H133), the `export bundle` briefing (H141), and the compiled
`index.md` (H145). So a reader of the link graph sees *which* source's custody is
weakest without dropping to `status`/`doctor`. The per-source entries sum to the
whole `stats.custody` block beside them (every item lands in one source group) and
equal `doctor`'s `custody.by_source` for the whole-library scope, independent of
`--all` (`test_graph_stats_custody_splits_per_source`,
`test_graph_stats_custody_by_source_is_independent_of_include_all`,
`test_graph_by_source_converges_with_doctor_and_the_per_source_tally`). An empty
graph is the honest empty `{}` map.

`stats.custody.attention` (roadmap H164) distils that per-source map to the
single weakest source — the one carrying the most actionable loss
(`drifted` + `rotted`, tie-broken by most `reference`-only then name) — via the
shared `custody.weakest_source`, the *same* primitive JSON `scrolls status`
(H139) and `scrolls maintain` (H119) thread. So a reader of the link graph sees
not just *which* source's custody is weakest but the one to act on, with its own
`{tiers, drift, coverage}` tally and the exact `scrolls verify --source <S>`
recheck command (H137). It is honestly `null` on the same three gates as the JSON
flags — an empty map, a single source (nothing to rank across), or a fully-clean
scope (no `drifted`/`rotted` loss) — so a loss-free or one-source graph flags
nothing even with drift, and it ranks the whole `stats.custody.by_source` scope so
it is independent of `--all`. Converges with `status`/`maintain`/`doctor` by
construction (same primitive over the same map),
pinned in `test_graph_attention_converges_with_status_maintain_and_doctor`.

```console
$ scrolls graph
{"nodes": [{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered", "fidelity": "full", "drift": "verified", "last_checked": "2026-06-14T00:00:00+00:00", "content_duplicate_ids": []}, {"id": "x:2222", "source": "x", "title": "@karpathy: the attention paper still holds up", "url": "https://x.com/karpathy/status/2222", "stage": "rendered", "fidelity": "full", "drift": "unverified", "last_checked": null, "content_duplicate_ids": []}], "edges": [{"from": "x:2222", "to": "arxiv:1706.03762", "via": "https://arxiv.org/abs/1706.03762"}], "stats": {"items": 2, "nodes": 2, "edges": 1, "clusters": 1, "custody": {"tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 1, "drifted": 0, "rotted": 0, "error": 0}, "by_source": {"arxiv": {"tiers": {"full": 1, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 1, "total": 1}}, "x": {"tiers": {"full": 1, "partial": 0, "reference": 0}, "drift": {"verified": 0, "unverified": 1, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 1}}}, "attention": null}}}
[exit 0]
```

### `scrolls works [ref] [--min N] [--fidelity T] [--drift P] [--at-risk] [--content-duplicate]`

Scholarly works the library holds more than one representation of, keyed
by DOI (ADR 0069, `tests/test_works.py`). One work — an arXiv preprint,
its published Crossref article, a PubMed record, a bioRxiv/medRxiv
preprint — can sit in the library as several near-duplicate `paper`
entries; this groups them. A representation contributes a work's DOI when
its `source_id` is itself a DOI (`crossref`, `biorxiv`/`medrxiv`) or it
carries a `doi.org` link (every paper adapter emits the published work's
DOI as one).

Where `scrolls graph` connects items only when one's link resolves to
another *already in the library*, `works` clusters by the *shared DOI*, so
an arXiv preprint and a PubMed record that both name `doi.org/D` are one
work even when the `crossref:D` item that would link them is absent
(`test_clusters_without_the_crossref_hub_present`). Each work carries its
`doi`, canonical `url`, and `representations` (the `id`/`source`/`title`/
`url`/`stage` node shape plus the **full per-item custody picture** — `fidelity`
(how much is held, ADR 0100), `drift` (whether the source moved, roadmap H64),
and `last_checked` (as of when, roadmap H87, `null` when never re-checked) — so
each representation reports the custody tier it is held at, its drift posture,
*and* when that verdict was taken: the preprint may be full while the published
record is a bare reference, and either may have drifted since capture. The same
`custody.drift_posture`/`custody.last_checked` over `latest_events` every other
per-item surface reads, so a representation's `drift` and `last_checked` equal
that item's `list` row by construction, `unverified`/`null` when never re-checked
— `test_cli_works_representation_drift_matches_the_list_row`,
`test_cli_works_representation_last_checked_matches_the_list_row`), sorted by
id; works sort by representation count then DOI.

Each work also carries a `custody` block — the work-level *aggregate* custody
posture, the **consolidation** of its representations' per-item custody (roadmap
H261, the new custody *shape*: custody at the level of a work, not just the item):
`{best_fidelity, safest_drift, safely_held}`. `best_fidelity` is the best
(most-complete) tier any representation holds and `safest_drift` the safest
(most-reassuring) drift posture any carries — each picked independently across the
cluster, "what is the most re-derivable / least-moved form of this work?".
`safely_held` is the consolidation verdict: `true` iff **∃ a representation that is
`full` *and* whose drift is `verified` or `unverified`** — an unmoved, fully
re-derivable copy of the work exists somewhere in its cluster, so the work survives
even if its other forms degraded or drifted. It is the **strong** form: a `partial`
capture cannot fully re-derive the work, so it is never a safe hold even when
verified, and a `full` copy that has *drifted*/*rotted* (or could not be checked —
*error*) is not safe either; both must hold on the *same* representation, so a work
with a drifted full preprint and a verified *partial* record is **not** safely held.
A pure fold over the same `fidelity`/`drift` the representations carry — no extra
ledger read, agreeing with the entries it rides beside by construction
(`test_cli_works_carries_the_aggregate_custody_block`).

Beside that `custody` block each work carries a `content_duplicate` boolean
(roadmap H329) — `true` iff **two of the work's representations hold byte-identical
content** (the same non-null `content_hash`): a preprint mirrored into its DOI
capture, a published record duplicating the arXiv body. The consolidation-surface
sibling of the whole-library `doctor.custody.content_duplicates` report (H325): where
that report counts byte-identical groups *anywhere* in the library, this asks the
question *within a work* — "does this work hold the same bytes under two forms?" — a
redundancy an operator consolidating the work may want to know. **Report-only, never
a merge** (content-identity across a work's forms is custody-distinct provenance; raw
is sacred, the H325 no-fabricated-act discipline), a pure fold over the per-rep
`content_hash` (no schema change). The H325 NULL-skip holds: a reference-only
representation captures no content, so it fingerprints nothing and never forms a
byte-identical pair (two reference reps hold no bytes — `false`). Rides the MCP
`get_works` twin for free (both route through `works.to_payload`), so the flag reads
identically on CLI and MCP
(`test_work_content_duplicate_flags_a_byte_identical_rep_pair`,
`test_get_works_flags_a_byte_identical_rep_pair_at_parity_with_cli`).

`--min N` sets the minimum
representations per work (default 2 — a single-representation work is just
a paper); `--min 1` lists every DOI-bearing item. `stats.items` is the
library total. `stats.custody` is the works-surface member of the
`stats.custody` family (roadmap H100, beside the browse
`search`/`list`/`related --stats` envelopes and the `graph` stats block) — the
shared `custody.tally_custody` fidelity-tier and drift-posture count maps over
the **reported works' representations** (the same `(fidelity, drift)` each
representation entry above carries), so a reader sees "of the
multi-representation works in scope, how much is held in full and how much
drifted" without a second `facets` call. It is scoped to the representation
*entries* (not `stats.items`), so its totals equal the rendered representations
by construction — an item that represents two works contributes to both, as it
is rendered twice (`test_stats_custody_totals_equal_the_reported_representation_entries`).
A `scope` companion echoes the floor it clustered above
(`{"min_representations": N}`) so a reader holding only the payload can tell
"these are every multi-representation work" from "every work of 3+
representations" — the completeness contract's G2 honesty, and since `works`
is uncapped the floor *is* its truncation story: a work missing from the
payload was below the reported floor, not absent. An empty or uninitialized
library is no works, exit 0 — with the scope still named.

Beside that tally, `stats.custody.at_risk` is the **scope-level at-risk-works
summary** (roadmap H266) — the works-surface counterpart of the
`doctor`/`maintain`/MCP `get_library_health` at-risk-works alarm (H263), and a
sibling of the `attention` weakest-source flag in the same `stats.custody`
loss-summary family (`attention` being itself a scope-level custody-loss summary,
a source flag rather than a rep tally). It is the shared `at_risk_signal` fold —
`{total, at_risk, most_at_risk}` over the **reported** works — so a reader of any
`works` payload sees "N of the reported works are at risk; worst is `<doi>`"
without a second `doctor` call: `total` is the reported-works count (equal to
`stats.works` beside it), `at_risk` how many are not safely held, and
`most_at_risk` the single lowest-custody-ceiling one (`null` when none is at risk,
the same `{doi, url, canonical, representations, custody, reason}` entry — and the
same no-`command` discipline — the alarm names). A pure fold over the *reported*
works, so it composes with the filters below: under `--at-risk` every reported
work is at risk (`at_risk == total`), and under `--fidelity full` it counts the
at-risk subset of the kept works. No extra ledger read (the same `verdicts` the
per-rep `drift` folds), and over the unscoped default 2+ clustering it converges
field-for-field with `doctor`'s `custody.works` (minus its `status`) by
construction (`test_stats_custody_at_risk_summarizes_the_reported_works`,
`test_cli_works_stats_custody_at_risk_converges_with_doctor`).

`--fidelity T` / `--drift P` are the custody-filter family on the
**consolidation** surface (roadmap H262, `tests/test_works.py`): the family
scoped each per-*item* custody axis on every read/act/export surface
(`list`/`search`/`related`/`context`/`export …`), and this lifts the same
per-item predicate to the *work* — the cluster of representations. The
**contains** semantics: a work is kept *whole* (every representation still
travels) when it **has a representation** at the custody value, since a work is
a set of forms and "show me the works with a drifted representation" wants the
work *and its siblings* — so a reader can see whether a safe sibling exists —
not the lone matching form. So `--drift drifted` surfaces *the works needing a
recapture decision* with their representation set intact. The filter folds the
same per-rep `fidelity`/`drift` the representations carry, applied before the
`--min`/report cut, and the two axes AND **on the same representation**:
`--fidelity full --drift drifted` keeps a work iff some rep is *both* full and
drifted (a fully-held copy whose source moved — the recapture candidate where
the content is in hand), not merely some full rep and some — possibly different —
drifted rep. Closed vocabulary → exit 2 (argparse `choices=`, the `verify
--fidelity`/`related --drift` precedent). `stats.custody` honors the filter (it
tallies the *reported* works' representations) and the filters ride the `scope`
echo, pruned when unset (G2). The filter composes with the per-item `ref` lens
too — `works <id> --drift drifted` answers "is the work this item represents one
with a drifted rep?" (`test_cli_works_filters_by_fidelity_tier`,
`test_cli_works_filters_by_drift_posture`,
`test_cli_works_ands_both_custody_axes`).

`--at-risk` is the **at-risk-works browse predicate** (roadmap H265,
`tests/test_works.py`): it keeps only the works **no representation safely holds**
— the per-work `safely_held == false` set the `doctor`/`maintain`/MCP
at-risk-works alarm (roadmap H263) counts, surfaced here as a *filter*. It is a
genuinely new predicate, **not** a `--fidelity`/`--drift` value: "no rep is safely
held" is the negation of *∃ a full, unmoved copy*, so it cannot be expressed as a
single per-rep custody filter — the consolidation analogue of `scrolls list
--drift`. It **ANDs** with `--fidelity`/`--drift`: `--at-risk --fidelity full`
surfaces the at-risk works that *also* hold a full rep — the **recapture
candidates** whose content is still in hand but whose work is at risk (the full
copy drifted), the sharpest "act on this" set. The same `work_custody`
`safely_held` fold the aggregate `custody` block and the alarm read (one rule,
three reads), applied before the report cut so `stats.custody` partitions exactly
the kept set; the flag rides the `scope` echo, present only when set (G2). Composes
with the per-item `ref` lens too — `works <id> --at-risk` answers "is the work this
item represents at risk?" (`test_cli_works_at_risk_browses_the_unsafely_held_works`,
`test_cli_works_at_risk_ands_with_the_custody_filters`,
`test_cli_works_at_risk_composes_with_the_per_item_ref_lens`).

`--content-duplicate` is the **content-identity browse predicate** (roadmap H344,
`tests/test_works.py`): it keeps only the works that **hold the same bytes under two
representations** — the per-work `content_duplicate == true` flag (above, H329: ≥2 reps
share a non-null `content_hash`) surfaced here as a *filter*, the consolidation-surface
twin of `scrolls list --content-duplicate` (H338). It is the **within-work** scope the
flag already carries: a work is kept iff *its own* forms duplicate each other — distinct
from `list --content-duplicate`'s whole-library sibling scope, which keeps an item whose
byte-identical twin lives *anywhere*. A boolean property, not a `--fidelity`/`--drift`
value, reading **no ledger** (`content_hash` is item-intrinsic), so it **ANDs** with
`--fidelity`/`--drift`/`--at-risk`: `--content-duplicate --fidelity reference` keeps the
duplicate-bearing works that *also* hold a reference form. The same
`work_content_duplicate` fold the per-work flag reads (one rule, two reads — the
drill-from-the-flag tie), applied before the report cut so `stats.custody` partitions
exactly the kept set; the flag rides the `scope` echo, present only when set (G2). The
H325 NULL-skip holds (a reference-only rep fingerprints nothing, so a full+reference pair
is not a duplicate). **Report-only, never a merge** (raw is sacred). Composes with the
per-item `ref` lens too — `works <id> --content-duplicate` answers "does the work this
item represents hold a byte-identical pair?", and rides the MCP `get_works` twin
(`test_cli_works_content_duplicate_browses_the_byte_identical_works`,
`test_cli_works_content_duplicate_ands_with_the_custody_filters`,
`test_get_works_content_duplicate_matches_the_cli_twin`).

With a `ref` (an item id or URL — the saved URL is a valid handle wherever
an id is, ADR 0028), `works` reports the *per-item* lens instead: the
work(s) that one item represents, with every saved sibling representation
(ADR 0072, `test_cli_works_with_ref_reports_only_that_items_work`). This is
to `scrolls works` what `scrolls related <id>` is to `scrolls graph` — an
agent that found one form of a work (a search hit, a scroll) learns which
other forms are in the library. In this form `--min` is ignored and a work
is reported even with a single representation (just that item), so "no
sibling saved" is an explicit answer; an item that names no DOI is no
works, and an unknown item is a JSON error on stderr, exit 1. The `scope`
companion here names the resolved `ref` anchor (`{"ref": "arxiv:…"}`, the
item id even when a URL was passed) rather than the floor it ignores.

```console
$ scrolls works
{"scope": {"min_representations": 2}, "works": [{"doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222", "canonical": "crossref:10.5555/3295222", "custody": {"best_fidelity": "full", "safest_drift": "unverified", "safely_held": true}, "content_duplicate": false, "representations": [{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered", "fidelity": "full", "drift": "unverified", "last_checked": null}, {"id": "crossref:10.5555/3295222", "source": "crossref", "title": "Attention Is All You Need", "url": "https://doi.org/10.5555/3295222", "stage": "fetched", "fidelity": "partial", "drift": "unverified", "last_checked": null}]}], "stats": {"items": 2, "works": 1, "custody": {"tiers": {"full": 1, "partial": 1, "reference": 0}, "drift": {"verified": 0, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0}}}}
[exit 0]

$ scrolls works arxiv:1706.03762
{"scope": {"ref": "arxiv:1706.03762"}, "works": [{"doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222", "canonical": "crossref:10.5555/3295222", "custody": {"best_fidelity": "full", "safest_drift": "unverified", "safely_held": true}, "content_duplicate": false, "representations": [{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered", "fidelity": "full", "drift": "unverified", "last_checked": null}, {"id": "crossref:10.5555/3295222", "source": "crossref", "title": "Attention Is All You Need", "url": "https://doi.org/10.5555/3295222", "stage": "fetched", "fidelity": "partial", "drift": "unverified", "last_checked": null}]}], "stats": {"items": 2, "works": 1, "custody": {"tiers": {"full": 1, "partial": 1, "reference": 0}, "drift": {"verified": 0, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0}}}}
[exit 0]
```

### `scrolls context <query> [--limit N] [--budget B] [--source S] [--category C] [--stage ST] [--tag T] [--concept K] [--fidelity F] [--drift D] [--strength W] [--content-duplicate]`

The Markdown exception: a compact context bundle — best matches,
capped excerpts, source links — that agents drop directly into context
(IDEAS.md §11, `tests/test_context.py`). Each excerpt carries the item
id, source, and scroll path for follow-up with `scrolls show` or a file
read. When the matches link to or from other saved scrolls, a
`## Connected scrolls` section (between Excerpts and Links) lists those
neighbors from the link graph (`scrolls graph`, ADR 0044/0047) — a match's
paper, repo, or dataset that keyword search would miss — each naming the
match and direction that pulled it in
(`test_context_surfaces_connected_scrolls`). It is omitted when there are
no such connections. Default limit 8. Errors are still JSON on stderr
(blank query, as with `search`).

A `Coverage:` line under the title states how much of the library the bundle
saw (the completeness contract's G2 truncation honesty,
`test_context_marks_truncation_when_matches_exceed_the_limit`): `all N
matching scrolls` when every match fit under the cap, or `the top N of M
matching scrolls — raise \`--limit\` …` when the cap hid some, so absence
below the cap is never read as absence in the library. The count is over the
same `count_matches` denominator `scrolls search --stats` uses, so a bundle
and a `--stats` search of the same scope agree on the total; a same-work
duplicate folded into its best-ranked sibling (ADR 0101) is still *covered*
(named in that sibling's note), so a collapsed bundle reads as complete, not
truncated. The line appears only when there are matches — the empty bundle
keeps its G1-locked `No matching scrolls.` form untouched.

Each match also **explains why it ranked** (roadmap H315, vision §3.5,
`test_context_best_match_lines_carry_a_strength_marker`): its Best-Matches line
ends in a compact `· <strength>` marker naming the strongest indexed field its
query landed in — `strong` (title), `moderate` (summary), `weak` (body-only) —
the legible companion to the opaque BM25 order each hit already carries
(`match_strength`, H312), in the same `· ` marker idiom the browse list-row
carries its `· <fidelity> · <drift>` custody markers (H89). Beside the Coverage
line a one-line **`_Strength: strong <a>, moderate <b>, weak <c> (of N)._`
headline** folds those markers into a bundle-level rank-confidence summary (the
H313 `tally_strength` histogram, the shared `render_strength_headline`), so an
agent skimming the bundle reads not just *what* matched but *how strongly*. The
headline tallies the **kept** matches — the bundle collapses same-work
duplicates (ADR 0101), so a folded sibling's strength is counted once, not twice
(`test_context_strength_counts_a_collapsed_work_once`) — so it converges with
the per-line markers by construction
(`test_context_strength_headline_folds_the_per_match_markers`). Both are
ledger-free FTS facts, so unlike the `_Custody:_` headline they travel at *every*
budget tier, including the leanest `index` catalog
(`test_context_strength_renders_at_every_budget_tier`), where an agent most needs
to tell a strong match from a weak one before spending budget on bodies. The MCP
`get_context_bundle` twin carries both for free
(`test_get_context_bundle_carries_the_strength_explanation`).

`--budget` bounds the bundle's *depth* — a budgeted boot sequence, identity/
index first, deep bodies on demand (MVP M3, an adapted progressive-context
mechanism, `tests/test_context.py`). The three tiers are strictly nested: `index` is the
catalog alone (Best Matches + Links — ids, titles, source URLs, and any
same-work collapse note, with no link-graph build at all); `connected` adds the
`## Connected scrolls` graph; `full` (the default) adds the `## Excerpts` deep
bodies, i.e. the current flat bundle, unchanged. A tier below `full` carries a
`_Budget:_` note under the Coverage line disclosing what it held back and the
lever to get it (`--budget full`, or `scrolls show <id>` for one body), so a
catalog-only bundle is never read as "all there is" — the depth-axis counterpart
to the Coverage line's scope honesty, and the two hold independently (a budgeted
bundle still states full vs truncated coverage). Same-work collapse (ADR 0101)
is index-level, so it holds at every tier:
`test_context_index_budget_still_collapses_same_work`.

From the `connected` tier up the bundle also carries a one-line `_Custody:_`
**headline** — `N scroll(s)`, the fidelity-tier counts, and the drift-posture
counts over the in-bundle scrolls — so an agent sees how much of what it is
about to read is full-fidelity and how much has drifted before reading a word
(roadmap H47, `test_context_carries_a_scope_custody_headline`). It is the same
shared `custody_headline` the shareable bundle briefing (H45) and `scrolls
status` (H38) render, so the three converge for the same scope; over an
uncapped, uncollapsed whole-library scope the counts equal `doctor`'s `custody`
aggregate (`test_context_custody_headline_converges_with_doctor`). Gated to
`connected`/`full` (like the depth-bearing sections) so the leanest `index`
tier stays a bare catalog (`test_context_custody_headline_gated_off_index`).

The `index` tier reads no custody ledger, so it carries no `_Custody:_`
headline (a `verified`/`unverified` drift verdict over a ledger it never read
would be the M2 anti-fabrication violation the gate above avoids). But fidelity
is a ledger-free *holdings* fact (`get_fidelity`, derived from stored fields),
so it travels even there — *fidelity travels with every result* (vision
principle 3, roadmap H212): the `index` bundle carries a one-line
`_Fidelity: full <a>, partial <b>, reference <c> (of N)._` holdings note so an
agent reading the leanest catalog learns how much of the matched set it holds in
full *before* spending budget on a deeper tier. The line carries **only**
fidelity — never a drift claim. Its tier counts are the same `custody_counts`
the `connected`+ `_Custody:_` headline folds (the `_fidelity_tokens` primitive
is shared), so the `index` line and the headline's `fidelity` section are
byte-identical and cannot disagree on what fraction is held in full
(`test_context_index_budget_carries_fidelity_holdings`,
`test_context_index_fidelity_counts_match_the_connected_headline`); from
`connected` up the headline already carries fidelity, so the dedicated line is an
`index`-only lever, never duplicated above it
(`test_context_fidelity_line_only_at_index_headline_carries_it_above`).

A *multi-source* bundle follows that headline with a **`_By source:_`
breakdown** — one bullet per source naming that source's fidelity tiers, drift
postures, and recheck coverage (`· coverage V/T`, roadmap H158 — of that
source's verifiable held items, how many carry a verdict; always shown, even
`coverage 0/0`, so the section is positionally stable) — so an agent gauges
*which source in the bundle is weakest and least checked* without re-deriving it
(roadmap H149,
`test_context_carries_a_per_source_custody_breakdown`). It is the same shared
`custody.render_custody_by_source` the `export bundle` briefing (H141) and the
compiled `library/index.md` (H145) render, so the per-source line reads
byte-identical across surfaces; it folds the same `custody_counts_by_source` the
scope headline already covers (one ledger read), so the bullets sum to the
headline by construction and equal `doctor`'s `custody.by_source` for the same
scope (`test_context_per_source_breakdown_sums_to_the_scope_headline`,
`test_context_per_source_breakdown_converges_with_doctor_by_source`). A
single-source or empty scope omits the split — the whole-scope headline already
says everything (`test_context_per_source_breakdown_omitted_for_a_single_source`)
— and like the headline it is gated off `index`
(`test_context_per_source_breakdown_gated_off_index`).

At the `full` budget each excerpt also carries two compact **per-source trust
tags** beneath its meta line (roadmap H44 + H62 + H90) — the per-excerpt
counterpart of the scope `_Custody:_` headline, so an agent dropping an excerpt
into its window sees *that source's* provenance, not just the scope aggregate:

- `_classified by \`<engine>\` (<basis|model …>) · confidence <level>[, <freshness>]_`
  — *how the category was derived*, the same `classification_provenance` view
  `show`/`list`/`search` and the shareable bundle briefing carry, rendered through
  the shared `classification_phrase` so the method/confidence reads byte-identical
  across surfaces (`test_context_excerpt_classification_phrase_matches_the_shared_view`).
  Omitted on honest absence — an unclassified or user-set item claims no method, so
  the line is simply dropped (`test_context_excerpt_classification_omitted_on_honest_absence`).
- `_drift \`<posture>\` · last seen <checked_at>_` — *whether the source has
  moved, and as of when* (roadmap H90): the `custody.drift_posture` over the
  item's latest verify-ledger verdict (`verified`/`unverified`/`drifted`/`rotted`/
  `error`) followed by the `custody.last_checked` of that verdict, or
  `· never re-checked` when the ledger holds no verdict — the honest-absence
  counterpart of the `unverified` posture, never a faked time
  (`test_context_excerpt_drift_unverified_when_never_checked`). Always shown, with
  `unverified` stated explicitly so a never-checked source is never read as
  "clean"; it reads the same ledger the headline shares (one read) through the
  same `drift_posture`/`last_checked` every surface uses, so the per-excerpt
  posture/staleness and the scope count cannot disagree
  (`test_context_excerpt_drift_matches_the_ledger_primitives`). So an agent can
  pick a `verify --stale-before <ISO>` boundary straight from an excerpt.

Both are a `full`-only deepening (like `## Excerpts`): the `index`/`connected`
tiers stay lean catalogs and carry no per-excerpt tag
(`test_context_excerpt_tags_absent_below_full`).

`--source`, `--category`, `--stage`, `--tag`, and `--concept` scope the
bundle exactly as they scope `scrolls search` (ADRs 0058/0059,
`test_context_facets_scope_the_bundle`,
`test_context_tag_and_concept_facets_scope_the_bundle`): they narrow the
underlying ranked match (and so the connected-scrolls graph). When any
facet is set the title carries a scope note — `# Scrolls Context Bundle:
<query> (source=arxiv)` — so a scoped bundle stays self-documenting; an
empty `--category ""` selects unclassified items and reads as
`category=unclassified`, while `--tag`/`--concept` report their value
verbatim. A facet that excludes everything still yields a valid `No
matching scrolls.` bundle, with the scope note intact.

`--fidelity <tier>` and `--drift <posture>` are the two per-item **custody
scopes** (roadmap H257, `tests/test_context.py`) — the custody-filter family
(`list`/`search`/`verify`/`related --fidelity`/`--drift`) reaching the agent
context bundle, the one progressive read surface it had not. `--fidelity`
keeps only the matches the library holds at one custody-fidelity tier
(`full`/`partial`/`reference`, ADR 0097 — the holdings axis, a content-column
fact), so an agent on a tight budget can build its working context from "only
the full-fidelity sources I can re-derive offline"
(`test_context_fidelity_filter_keeps_only_that_tier`). `--drift` keeps only the
matches at one verify-ledger posture
(`verified`/`unverified`/`drifted`/`rotted`/`error` — the ledger-claim axis), so
it can "exclude the ones that have moved"
(`test_context_drift_filter_keeps_only_that_posture`). Both fold the *same*
`scrolls_fidelity`/`scrolls_drift` UDFs `scrolls search --fidelity`/`--drift`
use (`build_context` passes them straight to `search_items`/`count_matches`), so
they AND with the facets and — crucially — sieve the candidate set **before**
the `--limit` cap (the `list`-sieve shape): the bundle covers the top matches
*at that custody value*, not the top matches then sieved
(`test_context_custody_filters_sieve_before_the_limit`). Because the sieve runs
before the budget tier nests its excerpts, everything downstream — the
work-collapse, the `_Custody:_`/`_Fidelity:_` headline, the Coverage
denominator, and the `full`-budget per-excerpt drift tags — reads the kept set,
so the rendered headline describes exactly what the bundle contains
(`test_context_drift_filter_describes_kept_set_at_full_budget`). The convergence
invariant pins it honest: a `--fidelity T` bundle's holdings count equals tier
`T`'s share of the *unfiltered* bundle's `_Fidelity:_` line — the per-value
filters partition the unfiltered scope, never inflate it
(`test_context_fidelity_filter_partitions_the_unfiltered_holdings`,
`test_context_drift_filter_partitions_the_facets_drift_aggregate` in
`tests/test_custody_convergence.py`). The scope note names the active custody
value — `(fidelity=full)`, `(drift=drifted)` — beside the facet echo
(`test_context_custody_scope_named_in_the_title`); a closed vocabulary, so an
unknown tier/posture is exit 2 (argparse `choices`) on the CLI and a `ValueError`
on the `build_context`/MCP path
(`test_context_cli_rejects_unknown_custody_values`). The two axes reach MCP
clients through the same `get_context_bundle(query, fidelity=, drift=)` twin
(`test_get_context_bundle_filters_by_fidelity_tier`,
`test_get_context_bundle_filters_by_drift_posture` in `tests/test_mcp.py`).

`--strength <band>` is the **rank-axis** third scope (roadmap H316,
`tests/test_context.py`) — the same before-cap threshold band `scrolls search
--strength` adds (H314), here lifted to the context bundle, the act-axis
companion of the `· <strength>` match explanation above. It keeps only the
matches whose query lands at or above one rank-strength band, and like
`search`/`--fidelity` it is a **threshold** (at or above), not exact-band
equality: `--strength strong` keeps only the title hits, `--strength moderate`
keeps title-or-summary matches, and `--strength weak` keeps every match
(`test_context_strength_filter_keeps_the_band_and_stronger`). It threads straight
into `search_items`/`count_matches` beside `--fidelity`/`--drift`
(`build_context` passes it through), so it ANDs with them and the facets
(`test_context_strength_ands_with_fidelity`) and sieves the candidate set
**before** the `--limit` cap — the bundle covers the top matches *at that
strength*, and the Coverage denominator counts only that band's matches
(`test_context_strength_sieves_before_the_limit`). The kept slice re-folds the
`_Strength:_` headline and per-match markers (H315), so a `--strength strong`
bundle reports a strong-only headline describing exactly what it contains, never
the whole-library tally (`test_context_strength_filter_rescopes_the_headline`).
The scope note names the band — `(strength=strong)` — beside the facet/custody
echo (`test_context_strength_scope_named_in_the_title`); a closed vocabulary, so
an unknown band is exit 2 (argparse `choices`) on the CLI and a `ValueError` on
the `build_context`/MCP path (`test_context_cli_rejects_unknown_strength`,
`test_context_unknown_strength_raises`). It reaches MCP clients through the same
`get_context_bundle(query, strength=)` twin
(`test_get_context_bundle_filters_by_match_strength`,
`test_get_context_bundle_rejects_an_unknown_match_strength` in
`tests/test_mcp.py`).

`--content-duplicate` is the **content-identity** browse scope (roadmap H345,
`tests/test_context.py`) — the same boolean `scrolls list`/`search
--content-duplicate` add (H338), here lifted to the context bundle beside
`--fidelity`/`--drift`/`--strength`, the third browse surface to carry it. It
keeps only the matches the library holds a byte-identical copy of under another
id (the same non-null `content_hash` — a mirror, a cross-post, or one work
captured by two adapters), so an agent can brief on **exactly the redundant
holdings it might dedup** (`test_context_content_duplicate_keeps_only_redundant_holdings`).
A **boolean** flag, present-or-absent (not a value); the sibling may live in
*any* source — a content group spans the query scope (the whole-library sibling
rule, H328), so a match is kept when its byte-identical twin is held *anywhere*,
not only among the query's other hits
(`test_context_content_duplicate_uses_whole_library_sibling_scope`). It reuses
the H338 `search_items(content_duplicate=)` clause (the correlated `content_hash`
sub-count), so the kept set cannot disagree with `list`/`search` — `context
--content-duplicate`'s ids equal `search --content-duplicate`'s over the same
query scope (`test_context_content_duplicate_converges_with_search`). It ANDs
with the facets and the custody axes — `--content-duplicate --fidelity full`
keeps only the redundant copies held in full
(`test_context_content_duplicate_ands_with_fidelity`) — and sieves the candidate
set **before** the `--limit`/`--budget` cap, so the Coverage denominator counts
only the redundant matches and the kept slice re-folds the `_Duplicates:_`
briefing line (`test_context_content_duplicate_rescopes_coverage_and_duplicates_line`,
`test_context_content_duplicate_sieves_before_the_limit`). The scope note carries
a bare `content-duplicate` marker — `(content-duplicate)`, the H341 `export
bundle` idiom — beside the facet echo
(`test_context_content_duplicate_scope_named_in_the_title`). It is **report-only**
— never a merge (raw is sacred, H325). It reaches MCP clients through the same
`get_context_bundle(query, content_duplicate=)` twin, at byte parity with the CLI
(`test_get_context_bundle_filters_by_content_duplicate` in `tests/test_mcp.py`).

```console
$ scrolls context "local search"
# Scrolls Context Bundle: local search

_Coverage: all 1 matching scrolls._

_Strength: strong 1 (of 1)._

_Custody: 1 scroll(s) · fidelity full 1 · drift unverified 1._

## Best Matches

1. @karpathy: SQLite FTS5 is criminally underrated for local search. (`x:1111`) — technique · strong

## Excerpts

### @karpathy: SQLite FTS5 is criminally underrated for local search.

`x:1111` · x · scrolls/x/karpathy-sqlite-fts5-is-criminally-underrated-for-local-search.md
_classified by `rules-v1` (title-pattern) · confidence deterministic, current_
_drift `unverified` · never re-checked_

SQLite FTS5 is criminally underrated for local search.

## Links

- [@karpathy: SQLite FTS5 is criminally underrated for local search.](https://x.com/karpathy/status/1111)
[exit 0]
```

A multi-source bundle adds the `_By source:_` breakdown under the headline (here
at `--budget connected`, so no excerpts — just the catalog and the link graph):

```console
$ scrolls context "database" --budget connected
# Scrolls Context Bundle: database

_Coverage: all 3 matching scrolls._

_Strength: strong 3 (of 3)._

_Budget: connected — best matches, the link graph, and source links, no excerpts. Re-run with `--budget full` for excerpts; `scrolls show <id>` reads a body._

_Custody: 3 scroll(s) · fidelity full 3 · drift verified 1, unverified 1, drifted 1._

_By source:_

- `arxiv` — 1 scroll(s) · fidelity full 1 · drift unverified 1 · coverage 0/1
- `web` — 2 scroll(s) · fidelity full 2 · drift verified 1, drifted 1 · coverage 2/2

## Best Matches

1. Full database (`web:full`) · strong
2. Moved database (`web:moved`) · strong
3. Arxiv database paper (`arxiv:1`) · strong
[exit 0]
```

`--strength` scopes the same bundle to one rank-strength band, sieving before the
cap so the Coverage denominator and the `_Strength:_` headline describe only the
kept slice (here only the title hits — the lone strong-band match):

```console
$ scrolls context "ranking" --budget index --strength strong
# Scrolls Context Bundle: ranking (strength=strong)

_Coverage: all 1 matching scrolls._

_Strength: strong 1 (of 1)._

_Budget: index — the catalog only (best matches and source links). Re-run with `--budget connected` for the link graph or `--budget full` for excerpts; `scrolls show <id>` reads a body._

_Fidelity: full 1 (of 1)._

## Best Matches

1. BM25 ranking guide (`web:guide`) · strong
[exit 0]
```

## Derived artifacts

### `scrolls kb [--engine ...] [--stale [--source S]]`

Rebuild the interlinked library pages under `library/` from scratch
(stale groups can't linger; other files there are untouched — ADR 0005,
`tests/test_kb.py`). Output is the compile summary. Concept pages lead
with a stored synthesized summary when the LLM concept engine has
written one — the default compile includes them without any model call
(`test_kb_concept_page_leads_with_stored_summary`,
`test_kb_llm_engine_synthesizes_then_compiles`).

| Key | Meaning |
| --- | --- |
| `items` | rendered scrolls included |
| `sources` / `categories` / `concepts` / `tags` | group pages written per kind |
| `summaries` | concept pages that carried a stored synthesized summary |
| `clusters` | connected components in the link-graph page `graph.md` (ADR 0062) |
| `works` | multi-representation works in the works page `works.md` (ADR 0070) |
| `pages` | total files written, including `index.md`, `graph.md`, and `works.md` |

Tag pages (`tags/<name>.md`, ADR 0064) mirror concept pages — the
library's items grouped by each `tag`, case-insensitively (`MIT` and `mit`
are one page, the `--tag` facet's rule), with a `## Related Tags`
co-occurrence section — so the `--tag` facet you can search by is now also
browsable (`test_kb_compiles_tag_pages`).

`graph.md` is the browsable form of `scrolls graph`'s link structure: the
rendered scrolls that link to one another grouped into clusters, largest
first, each an adjacency list of members and their `→ target` edges; it is
always written (empty → `No linked scrolls yet.`) and the index links to it
(`test_kb_graph_page_clusters_linked_scrolls`).

`works.md` is the browsable form of `scrolls works`'s DOI clustering
(ADR 0070): the rendered scrolls that are the same scholarly work — a
preprint and its published article, an indexing record — grouped under the
DOI that names the work, each a `## <doi>` section linking its
representations' scrolls; always written (empty → `No works held in
multiple representations yet.`) and the index links to it
(`test_kb_works_page_clusters_representations_by_shared_doi`). Because the
page is over rendered items only, its work count can be below `scrolls
works`'s whole-library count — the rendered-only divergence `graph.md` also
has from `scrolls graph`.

Beneath each `## <doi>` section's resolver line sits a **per-work
`_Custody:_` marker** (roadmap H270) —
`_Custody: best held <tier>, safest drift <posture> — safely held._` (or
`— at risk._` when no representation is both `full` and unmoved) — the
works-page analogue of the per-item `· <fidelity> · <drift>` marker on the
list pages (H89). It is the `render_work_custody_marker` distillation of the
shared `works.work_custody` fold (H261) over the work's representations and
the custody ledger, so it reads the *same* aggregate verdict an agent reads
from `scrolls works`'s per-work `custody` block (convergent by construction)
and an at-risk section's marker agrees with whether `index.md`'s
`_At-risk work:_` line / `doctor`'s `custody.works` names that work
(`test_compiled_works_page_marker_converges_with_scrolls_works`). Like the
rest of the page body it sits inside the `@generated` sentinel fence
(ADR 0102), so a recompile refreshes it — a recapture flips a section from
`at risk` to `safely held` — while a hand annotation outside the fence
survives.

`--engine llm` (engine `kb-llm-v1`, ADR 0025) first brings the summary
store up to date via the Anthropic API (network; needs
`ANTHROPIC_API_KEY`; model from `[classify] llm_model`, overridable via
`SCROLLS_LLM_MODEL` — `test_kb_llm_engine_uses_config_llm_model`), then
compiles. Only concepts with 2+ scrolls qualify, and generation is
incremental: a concept whose members haven't changed reports `current`
without a model call, so re-running on an unchanged library costs
nothing (`test_kb_llm_engine_rerun_is_free_when_nothing_changed`);
summaries whose concept no longer qualifies are `pruned`
(`test_generate_prunes_summaries_for_disqualified_concepts` in
`tests/test_kb_llm.py`). The payload adds `generated` / `current` /
`failed` / `pruned` and per-concept `results` ahead of the compile
summary. Per-concept API failures are reported and the compile still
runs, exit 1 (`test_kb_llm_engine_reports_failures_but_still_compiles`);
missing credentials abort before compiling with the standard error
envelope, keeping any summaries already saved
(`test_kb_llm_engine_without_credentials_aborts_before_compiling`).

`--batch` (ADR 0032) synthesizes every concept that needs (re)generation
in one Message Batches submission at half the per-token price, polling
until the batch ends — typically minutes — instead of one API call per
concept (`test_kb_llm_batch_flag_submits_one_batch`;
`test_batch_summarizes_multi_member_concepts_in_one_submission` in
`tests/test_kb_llm.py` for the engine). Eligibility, incremental skipping,
pruning, the result shape, and per-concept failure isolation are
identical to the per-call path — only the transport differs, and both
share one validation and save path. A concept whose batch request failed
is reported and the compile still runs
(`test_batch_isolates_per_concept_failures`); missing credentials still
abort before compiling
(`test_kb_llm_batch_without_credentials_aborts_before_compiling`). The
flag needs the llm engine (`test_kb_batch_flag_requires_the_llm_engine`)
and shares the Batches transport with `classify --engine llm --batch`
(`tests/test_classify_llm.py`).

`--stale` is the *targeted refresh* on the summary axis — the counterpart of
[`classify --stale`](#scrolls-classify-id) (the loop H29 record/report → H31
refresh). It re-synthesizes **only** the concept summaries `scrolls doctor`
reports in `custody.summaries.stale` — a stored summary whose members changed
since synthesis — refreshing each summary and its members fingerprint to the
live members, then compiles. It implies `--engine llm` (the deterministic
compiler has no summaries to refresh; `--engine deterministic` is rejected —
`test_kb_stale_rejects_the_deterministic_engine`) and composes with `--batch`.
Unlike a full `--engine llm` run it does **not** generate summaries for
never-summarized eligible concepts (that is generation, left to the full run)
and does not prune orphans; on a current library it touches nothing and calls no
model (`test_kb_stale_is_a_noop_when_nothing_is_stale`). The set it regenerates
is exactly the set doctor reports stale — one shared `kb_llm.is_stale_summary`
predicate behind both — so refreshing clears the signal
(`test_kb_stale_clears_the_doctor_stale_signal`), the way `classify --stale`
clears `custody.enrichment.stale`. It never rewrites a current summary or
generates a missing one — regeneration on request, never doctor's silent
overwrite (custody §2.4).

`--source <S>` narrows that `--stale` refresh to one source — the summary-axis
counterpart of [`classify --stale --source`](#scrolls-classify-id) (roadmap
H172, H154 on the enrichment axis). It re-synthesizes exactly the stale concepts
**source `<S>` participates in** — `<S>` among a concept's live members, the same
attribution `doctor`'s `custody.summaries.by_source[<S>]` reports (a stale
summary records only the members digest, not which member moved, so a
multi-source cluster is "stale for" every member source and is refreshed under
*any* of them). The concepts it regenerates therefore equal that offenders set,
and refreshing **clears that source's entry** from the `by_source` map while
leaving the rest (`test_kb_stale_source_clears_only_that_sources_doctor_entry`,
`test_kb_stale_source_for_a_multi_source_cluster_refreshes_under_either_source`).
`--source` is a *narrowing* of `--stale`, not a standalone selection: `--source`
without `--stale` is a usage error (`test_kb_source_without_stale_is_a_usage_error`),
and a source with no stale debt is the network-free no-op
(`test_kb_stale_source_unknown_is_a_network_free_noop`). It implies the llm engine
and composes with `--batch`, exactly like whole-library `--stale`. The
act↔report convergence — the regenerated concept set equals
`custody.summaries.by_source[<S>]`'s offenders and refreshing clears that source's
entry (the multi-source cluster clearing all its sources) — is pinned in the
cross-surface convergence suite beside its
[`classify --stale --source`](#scrolls-classify-id) sibling
(`test_kb_stale_source_refreshes_exactly_the_doctor_per_source_summaries` in
`tests/test_custody_convergence.py`, roadmap H176), completing the per-source
refresh convergence on both enrichment axes.

```console
$ scrolls kb
{"items": 2, "sources": 1, "categories": 2, "concepts": 0, "tags": 0, "summaries": 0, "clusters": 0, "works": 0, "pages": 6}
[exit 0]

$ scrolls kb --engine llm     # no 2-scroll concepts yet: a zero run, no key needed
{"generated": 0, "current": 0, "failed": 0, "pruned": 0, "results": [], "items": 2, "sources": 1, "categories": 2, "concepts": 0, "tags": 0, "summaries": 0, "clusters": 0, "works": 0, "pages": 6}
[exit 0]

$ scrolls kb --engine llm     # with a 2-scroll concept but no credentials set
{"error": "llm engine needs Anthropic credentials: set ANTHROPIC_API_KEY (\"Could not resolve authentication method. Expected one of api_key, auth_token, or credentials to be set. Or for one of the `X-Api-Key` or `Authorization` headers to be explicitly omitted\")"}
[exit 1]

$ scrolls kb --batch          # the deterministic engine has nothing to batch
{"error": "--batch requires the llm engine (--engine llm)"}
[exit 1]

$ scrolls kb --source web     # --source narrows the --stale refresh; it needs it
{"error": "kb --source narrows the --stale refresh; pass --stale"}
[exit 1]

$ scrolls kb --stale --source web   # refresh only the stale concepts web is in
{"generated": 1, "current": 0, "failed": 0, "pruned": 0, "results": [{"slug": "bm25", "concept": "BM25", "status": "generated"}], "items": 6, "sources": 3, "categories": 0, "concepts": 2, "tags": 0, "summaries": 2, "clusters": 0, "works": 0, "pages": 8}
[exit 0]
```

### `scrolls agent install`

Write agent instruction files under `<root>/agents/` — never into
another tool's config tree; copy or symlink them where your tool expects
them (ADR 0006, `tests/test_agents.py`).

```console
$ scrolls agent install
{"root": "/tmp/scrolls-demo.BgrqMO/home", "installed": ["agents/claude/SKILL.md", "agents/codex/AGENTS.md", "agents/hermes/SKILL.md"]}
[exit 0]
```

## Agent protocol server

### `scrolls mcp`

The one command that blocks and prints nothing: serve the library to
MCP clients over stdio until the client disconnects (ADR 0014,
`tests/test_mcp.py`). Connect a client to the command itself, e.g.:

```bash
claude mcp add scrolls -- uv run scrolls mcp
```

The tools wrap the same engines as the CLI commands
(`test_server_exposes_exactly_the_documented_tools`):

| Tool | CLI equivalent | Returns |
| --- | --- | --- |
| `get_context_bundle(query, limit=8, source=None, category=None, stage=None, tag=None, concept=None, budget="full")` | `scrolls context` | Markdown bundle, optionally faceted; `budget` (`index`/`connected`/`full`) bounds depth |
| `search_scrolls(query, limit=20, source=None, category=None, stage=None, tag=None, concept=None)` | `scrolls search` | hit list with snippets, the per-item custody axes (`fidelity` + `drift` (H58) + `last_checked` (H84)), and `works` membership (ADR 0101), optionally faceted |
| `list_scrolls(source=None, stage=None, category=None, tag=None, concept=None, drift=None, stale_before=None, stale_classification=False, stale_summary=False, limit=50)` | `scrolls list` | item summaries by facet (with the per-item custody axes `fidelity` + `drift` (H58) + `last_checked` (H84) and `works` membership, ADR 0101), no query (ADR 0060); `drift` filters by posture (H54), `stale_before` by staleness window (H85), `stale_classification` by the stale-enrichment set (H185) — rows total `get_library_health`'s `enrichment.stale`; `stale_summary` by the stale-summary set (H189) — the members of the concepts `get_library_health` flags stale in `summaries.items` |
| `list_facets(field=None, source=None, category=None, stage=None, tag=None, concept=None, limit=20)` | `scrolls facets` | the filterable vocabulary with counts, optionally scoped (ADR 0080) |
| `get_scroll(item_id)` | `scrolls show` | full item record + the per-item custody axes (`fidelity` + `drift` (H61) + `last_checked` (H84)) and `classification` view; `item_id` is an id or the item's URL (ADR 0028) |
| `get_scroll_history(item_id, limit=None, since=None, status=None)` | `scrolls history <id> [--limit N] [--since ISO] [--status V]` | the item's custody-ledger timeline (each `{checked_at, status, prior_hash, observed_hash, detail}`, newest first); three filter axes applied verdict → window → cap: `status` (unchanged/drifted/rotted/error) the verdict, `since` the time window, `limit` the count; `[]` when never verified or nothing matches, error on an unknown id, malformed `since`, or unknown `status`; `item_id` is an id or URL (ADR 0028; `test_get_scroll_history_status_filters_like_the_cli`) |
| `get_related_scrolls(item_id, limit=10, fidelity=, drift=, strength=)` | `scrolls related` | hits with `reasons`, a `relation_strength` band (`strong`/`moderate`/`weak`, H322 — the `match_strength` twin), and the per-item custody axes (`fidelity` + `drift` (H56) + `last_checked` (H86)); `fidelity`/`drift` scope the neighbourhood to one custody value per axis (H254) and `strength` to one rank band or stronger (H324, threshold), sieving before the cap; `item_id` is an id or URL (ADR 0028) |
| `get_link_graph(include_isolated=False)` | `scrolls graph` | `{nodes, edges, stats}` link graph (ADR 0044); each node carries the per-item custody axes (`fidelity` + `drift` (H56) + `last_checked` (H86)); `stats.custody` carries the per-source `by_source` split (H150) and the weakest-source `attention` flag (H164) |
| `get_works(min_representations=2, item=, fidelity=, drift=, at_risk=)` | `scrolls works` | `{works, stats}` — same-work clusters by DOI (ADR 0069); each representation carries the per-item custody axes (`fidelity` + `drift` (H64) + `last_checked` (H87)); each work carries an aggregate `custody` block `{best_fidelity, safest_drift, safely_held}` consolidating its reps (H261); `fidelity`/`drift` keep whole works that *contain* a representation at that custody value, ANDing on the same rep (the contains-semantics consolidation filter, H262); `at_risk=True` keeps only the works no representation safely holds — the negation of *∃(full ∧ unmoved)*, the at-risk-works alarm (H263) as a browse predicate, ANDing with `fidelity`/`drift` (H265); `stats.custody` tallies the reported reps (H100) and carries an `at_risk` summary `{total, at_risk, most_at_risk}` over the reported works — the works-surface twin of `get_library_health`'s at-risk alarm, convergent by construction (H266) |
| `get_concept_page(concept)` | reading `library/concepts/<slug>.md` | Markdown page |
| `get_tag_page(tag)` | reading `library/tags/<name>.md` | Markdown page; tag matched case-insensitively, slug collisions resolved by heading (ADR 0064) |
| `list_sources()` | — | item counts per source |
| `get_library_health(source=…)` | `scrolls status` / `doctor [--source]` (custody block) | the whole-library custody audit (H161): `run_doctor`'s custody block (`score`/`tiers`/`drift`+`coverage`/`by_source`/`enrichment`/`summaries`/`works`) plus the distilled weakest-source `attention` flag and one-line `headline` `status` adds. The `works` member is the H263 at-risk-works consolidation alarm carried verbatim from the doctor block (`{status, total, at_risk, most_at_risk}` — the works no representation safely holds, whole-library only so a `--source` read carries the skipped default), pinned convergent with `doctor` by `test_get_library_health_carries_the_at_risk_works_alarm`. The optional `source` scopes the *whole* read to one source's held items (H167) — the MCP sibling of CLI `doctor --source`/`status --source`, reusing the same `run_doctor(source=)` pre-filter; `by_source` collapses to the singleton `{S: …}`, `attention` is `null` (single-source gate), and the scoped block equals a `doctor --source S` / `status --source S` over the same library. Read-only **posture** — the repairable structural-findings/exit-code axis stays a CLI concern (`doctor --fix`); network-free (drift read from the ledger). Converges with the CLI `status`/`doctor` by construction (`test_get_library_health_matches_cli_status_field_for_field`, `test_mcp_library_health_converges_with_status_and_doctor`, `test_mcp_library_health_source_scope_converges_with_doctor_and_status_source`); empty/uninitialized / unknown source → the honest present-but-empty block (`score: null`/`100`, `attention: null`). The per-source **refresh debt** rides here too, but **nested** (`enrichment.by_source`/`summaries.by_source`) rather than flattened like CLI `status`'s `enrichment_by_source`/`summary_by_source` (H180) — the MCP twin keeps the fuller re-derivability block; the flat CLI maps equal its `by_source` slices by construction (`test_get_library_health_refresh_debt_equals_cli_status_flat_maps`, `test_get_library_health_source_scopes_the_refresh_debt`), and the nested MCP read joins the full three-way refresh-debt tie ≡ `status` ≡ `doctor` over the combined stale-classification+stale-summary seed — whole-library and `--source`-scoped, carrying the double-attribution asymmetry and the single-source-cluster scope-collapse (H208, `test_mcp_library_health_refresh_debt_by_source_converges_with_status_and_doctor`) |
| `run_maintenance(source=None)` | `scrolls maintain [--source S] --no-recheck` | one scheduled custody pass over MCP (H196): regenerate the compiled views, audit the post-maintenance state, compute the custody `delta` vs the last recorded run, and record this run's snapshot + append it to the trend log — returning the same report shape the CLI prints (`recheck`/`compiled`/`custody`/`headline`/`at_risk_headline`/`conflicts_headline`/`archive_integrity_headline`/`by_source`/`attention`/`enrichment_by_source`/`summary_by_source`/`delta`/`issues`/`suggested`). The readable `at_risk_headline` (`_At-risk works: N (▲M since last run)._`, roadmap H268), `conflicts_headline` (`_Conflicts: N (▲M since last run)._`, roadmap H283 — the peer-divergence trend on the conflict axis), and `archive_integrity_headline` (`_Archive: N prior(s) fail integrity (prior_hash ≠ snapshot)._`, roadmap H298 — the recovery-store integrity count, `null` when clean/scoped) ride the report for free here too, the consolidation-loss / unresolved-import-conflict / archive-integrity counterparts of `headline`. **Offline by default — the recheck is skipped:** `maintain`'s recheck is its one live network edge, and an MCP tool must not trigger implicit re-captures, so the MCP path always runs `--no-recheck` (drift read from the ledger, never re-checked); targeted live rechecks stay the explicit `verify_scroll` act (the `get_library_health`-vs-`doctor --fix` read/act boundary). The optional `source` scopes the pass to one source's held items (H203) — the MCP sibling of CLI `maintain --source S`, for an agent that has just read this library's `attention` flag and wants to run the pass on *that* weakest source; view regeneration stays whole-library (deterministic global recompile), the audit/delta narrow to `S` (`by_source` collapses to the singleton `{S: …}`, `attention` is `null`), and a scoped pass is **non-persisting** (writes no whole-library snapshot/log baseline, so its `delta` is honestly `null` — the whole-library pass owns the trend, ADR 0082). Report-only and idempotent (records the snapshot/log on a whole-library pass, never repairs rows). Converges field-for-field with the CLI `maintain [--source S] --no-recheck` (`test_run_maintenance_converges_with_cli_maintain_no_recheck`, `test_run_maintenance_source_converges_with_cli_maintain_source`); empty/uninitialized / unknown source → the honest-empty pass (`score: null`, `_Custody: 0 scroll(s)._`) |
| `get_maintenance_history(limit=None, trend=False)` | `scrolls maintain --history [--trend]` | the recorded maintenance runs oldest-first — the custody *trajectory* over time, the read sibling of `run_maintenance` (H198). Returns the bare runs array (each `{recorded_at, snapshot, delta, headline}`) by default; `limit` bounds it to the most recent N (`None` is the full history — the CLI's bare `--history` instead defaults to the 10 most recent). With `trend=True` the runs are wrapped in the `{trend, runs}` envelope `maintain --history --trend` prints, whose `trend` distils the window's net score/drift/coverage movement into one posture (improving / holding / regressing) — the opt-in-envelope parity with the CLI, so the bare-array completeness `[]` never regresses. Read-only and network-free; honest absence — a never-maintained / uninitialized library is the empty `[]` (or the `insufficient-history` trend envelope), never an error. Converges with the CLI `maintain --history` field-for-field (`test_get_maintenance_history_matches_cli_maintain_history`) |
| `ingest_url(url)` | `scrolls ingest` | the ingest payload, `error` key included (`test_ingest_url_without_adapter_reports_error_as_data`) |
| `verify_scroll(item_id)` | `scrolls verify <id>` | the custody event (`status` unchanged/drifted/rotted/error + hashes); records to the ledger, never clobbers the capture (ADR 0098; `test_verify_scroll_records_drift`) |
| `follow_feed(url)` | `scrolls follow <url>` | the subscription plus `created` (ADR 0020) |
| `unfollow_feed(ref)` | `scrolls unfollow <id>` | `{id, removed}`; accepts id or feed URL |
| `list_feed_subscriptions()` | `scrolls follow` | subscriptions with sync state |
| `sync_feeds(subscription_id=None)` | `scrolls sync [id]` | the sync batch payload; per-feed failures are `failed` results, not tool errors (`test_sync_feeds_registers_entries_then_reports_unchanged`) |
| `compile_library()` | `scrolls kb` | the compile summary; deterministic only — LLM summary generation stays a CLI step (`test_compile_library_builds_the_pages_get_concept_page_serves`) |

Read tools follow the CLI conventions: an empty or uninitialized
library yields empty results (`test_search_scrolls_before_init_returns_empty`),
unknown ids are tool errors (`test_get_scroll_unknown_id_raises`), and the
item-ref tools (`get_scroll`, `get_scroll_history`, `get_related_scrolls`,
`get_works`) accept the
item's URL as readily as its id, the same `resolve_item_id` chain the CLI uses
(ADR 0028, `test_get_scroll_accepts_the_items_url`).

## Reproducing these examples

Everything above except the three marked network calls (`ingest` of a
Wikipedia page, `fetch arxiv:1706.03762`, and the `scrolls media` run
that downloads its PDF) runs fully offline — the feed examples talk
only to a local server. Scratch setup:

```bash
DEMO=$(mktemp -d)
export SCROLLS_HOME="$DEMO/home"

# a local feed for the follow/sync examples (any RSS/Atom URL works the same)
mkdir "$DEMO/site"
cat > "$DEMO/site/feed.xml" <<'EOF'
<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Demo Weblog</title>
    <link>http://localhost:8943/</link>
    <item>
      <title>Post one</title>
      <link>http://localhost:8943/2026/post-one/</link>
    </item>
    <item>
      <title>Post two</title>
      <link>http://localhost:8943/2026/post-two/</link>
    </item>
  </channel>
</rss>
EOF
(cd "$DEMO/site" && python3 -m http.server 8943 &)

mkdir -p "$DEMO/fieldtheory/bookmarks" "$DEMO/fieldtheory/library/bookmarks"
cat > "$DEMO/fieldtheory/bookmarks/bookmarks.jsonl" <<'EOF'
{"id": "1111", "tweetId": "1111", "url": "https://x.com/karpathy/status/1111", "text": "SQLite FTS5 is criminally underrated for local search.", "authorHandle": "karpathy", "authorName": "Andrej Karpathy", "postedAt": "Mon Jun 01 15:34:00 +0000 2026", "syncedAt": "2026-06-04T04:27:46.057Z", "media": [], "links": ["https://sqlite.org/fts5.html"], "tags": []}
{"id": "2222", "tweetId": "2222", "url": "https://x.com/simonw/status/2222", "text": "Attention Is All You Need still holds up - a guide to reading it properly.", "authorHandle": "simonw", "authorName": "Simon Willison", "postedAt": "Tue Jun 02 09:12:00 +0000 2026", "syncedAt": "2026-06-04T04:27:46.057Z", "media": [], "links": ["https://arxiv.org/abs/1706.03762"], "tags": []}
EOF
cat > "$DEMO/fieldtheory/library/bookmarks/2026-06-01-karpathy.md" <<'EOF'
---
category: technique
domain: databases
tweet_id: "1111"
---
EOF

cat > "$DEMO/bookmarks.html" <<'EOF'
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><H3>Databases</H3>
        <DL><p>
            <DT><A HREF="https://www.youtube.com/watch?v=fts5video01" ADD_DATE="1614556800">SQLite Internals: B-trees</A>
            <DT><A HREF="https://example.com/sqlite-article?utm_source=share" ADD_DATE="1620000000">SQLite &amp; FTS Internals</A>
            <DD>Why SQLite's full-text search is enough.
        </DL><p>
        <DT><A HREF="javascript:void(0)" ADD_DATE="1610000000">Bookmarklet</A>
    </DL><p>
    <DT><H3>Reading</H3>
    <DL><p>
        <DT><A HREF="https://example.com/sqlite-article" ADD_DATE="1700000000">SQLite article again</A>
    </DL><p>
</DL><p>
EOF

python3 - "$DEMO" <<'EOF'
import json, sys, zipfile
from pathlib import Path
entries = [
    {"header": "YouTube", "title": "Watched How SQLite FTS Works",
     "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
     "subtitles": [{"name": "Some Channel"}],
     "time": "2025-03-01T09:00:00.000Z"},
    {"header": "YouTube", "title": "Watched Buy Our Thing",
     "titleUrl": "https://www.youtube.com/watch?v=advideo0001",
     "details": [{"name": "From Google Ads"}],
     "time": "2025-01-02T00:00:00.000Z"},
    {"header": "YouTube", "title": "Watched a video that has been removed",
     "time": "2025-01-03T00:00:00.000Z"},
    {"header": "YouTube", "title": "Watched How SQLite FTS Works",
     "titleUrl": "https://www.youtube.com/watch?v=abc123xyz00",
     "subtitles": [{"name": "Some Channel"}],
     "time": "2024-10-12T18:23:45.123Z"},
]
with zipfile.ZipFile(Path(sys.argv[1]) / "takeout.zip", "w") as zf:
    zf.writestr("Takeout/YouTube and YouTube Music/history/watch-history.json",
                json.dumps(entries))
EOF
```

Then, in order (`uv run scrolls …` when running from a source checkout):

```bash
scrolls init
scrolls status
scrolls paths
scrolls detect https://en.wikipedia.org/wiki/SQLite
scrolls add https://x.com/karpathy/status/3333
scrolls ingest https://x.com/karpathy/status/3333  # no adapter: exit 1
scrolls fetch                                      # skips the x item
scrolls fetch x:3333                               # by-id: fails, exit 1
scrolls import fieldtheory --root "$DEMO/fieldtheory"
scrolls import fieldtheory --root "$DEMO/fieldtheory"   # idempotent
scrolls import google-takeout "$DEMO/takeout.zip"
scrolls import google-takeout "$DEMO/takeout.zip"       # idempotent
scrolls import bookmarks "$DEMO/bookmarks.html"
scrolls import bookmarks "$DEMO/bookmarks.html"         # idempotent
scrolls add https://arxiv.org/abs/1706.03762
scrolls status                                    # populated counts now
scrolls list
scrolls list --source x --category technique      # filters AND together
scrolls ingest https://en.wikipedia.org/wiki/SQLite  # network
scrolls classify
scrolls classify wikipedia:en:SQLite --engine llm  # without a key: exit 1
scrolls md
scrolls fetch arxiv:1706.03762                     # network
scrolls media                                      # network: downloads the PDF
scrolls media                                      # idempotent, offline
scrolls media x:1111                               # skip: no media refs
scrolls search "sqlite fts5"
scrolls show x:1111
scrolls related x:2222
scrolls kb
scrolls kb --engine llm                            # no 2-scroll concepts yet: zero run
scrolls kb --batch                                 # deterministic engine: guard, exit 1
scrolls context "local search"
scrolls agent install
scrolls follow http://localhost:8943/feed.xml     # local server only
scrolls follow http://localhost:8943/missing.xml  # 404: exit 1
scrolls follow                                    # list subscriptions
scrolls sync                                      # 2 new items
scrolls sync                                      # 304: unchanged (http.server honors If-Modified-Since)
touch "$DEMO/site/feed.xml"                       # new Last-Modified
scrolls sync                                      # full response again: 2 known
scrolls unfollow http://localhost:8943/feed.xml
scrolls unfollow ea77c1d5239e                     # already gone: exit 1
scrolls set x:1111 tags=sqlite,fts "concepts=full-text search"
scrolls set x:1111 usefulness=high                # unknown field: exit 1
scrolls set x:2222 "concepts=full-text search"    # a 2-scroll concept now exists
scrolls facets                                    # the filterable vocabulary, with counts
scrolls facets concepts --source arxiv            # concepts scoped to one source
scrolls kb --engine llm                           # without a key: exit 1
scrolls kb --engine llm --batch                   # batch transport, without a key: exit 1
scrolls doctor                                    # healthy: exit 0

# plant the legacy state doctor repairs: a pre-ADR-0023 junk-URL row
# (today's `add` normalizes, so only an old library can hold one) ...
python3 -c "
from scrolls.paths import get_paths
from scrolls.items import ScrollItem, insert_item, make_item_id
url = 'https://blog.example/post?utm_source=newsletter'
insert_item(get_paths().db_path, ScrollItem(id=make_item_id('web', None, url),
    source='web', url=url, saved_at='2026-06-01T00:00:00+00:00'))
"
scrolls add https://blog.example/post             # ... its clean twin ...
rm "$SCROLLS_HOME"/scrolls/x/karpathy-*.md        # ... and a lost scroll file
scrolls doctor                                    # 2 findings: exit 1
scrolls doctor --fix                              # merged + rewritten: exit 0
scrolls doctor                                    # healthy again
scrolls rm x:3333                                 # never fetched: row only
scrolls rm https://x.com/simonw/status/2222       # by URL; scroll file too
scrolls rm x:2222 x:1111                          # one already gone: exit 1
```

(Stop the feed server with `kill %1` when done.)

The walkthrough exercises the dedupe (`x:` ids from the import collide
with `scrolls add` of the same tweet URL on purpose), the title-pattern
classify rule (`x:2222`'s "a guide to" → `tutorial`), and the
link-resolution path of `related` (`x:2222` → `arxiv:1706.03762`) — the
same behaviors the test suite locks.
