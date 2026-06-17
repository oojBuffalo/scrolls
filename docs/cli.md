# Scrolls CLI Reference

The output contract for every command: arguments, JSON keys, exit codes,
and error envelopes. This is the reference for agents (and contributors)
consuming `scrolls` output programmatically; `README.md` tells the same
story in prose, and `docs/architecture.md` explains the system behind it.

Every example below is real output captured from `scrolls 0.1.0`
(schema version 7) on this branch — see
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
integrity boundary is the agent contract (custody-vision §6); false
absence corrupts an agent's memory the same way a fabricated row does.
So every read and audit surface — `search`, `list`, `related`, `works`,
`context`, `doctor`, `maintain` (run offline with `--no-recheck`),
`export bundle` (the shareable artifact), `history` (the per-item custody
ledger), and their MCP twins — honors one
cross-cutting contract:
**results are scope-honest and completeness-honest; "nothing found" is
never confused with "not checked," and nothing is fabricated for content
the library does not hold** (PRD cap 7, MVP M2, adapted from
obsidian-second-brain's anti-fabrication rules — see
`docs/agents/obsidian-second-brain-inspiration.md`). The contract has two
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
(custody-vision §6, surface parity;
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
`search_scrolls`/`list_scrolls` consumer reads a list, custody-vision §6
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
Each landed with its own tests in the matching suite. The MCP twins read
from the same builders, so `get_works`/`get_context_bundle` carry the scope
echo and coverage line too; the bare-list `search_scrolls`/`list_scrolls`
twins keep returning the bare list for now, their G2 parity (an envelope
option) following once the CLI shape has stabilized. G1 is the half that is
already true across every surface and is locked so it cannot regress.

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
`test_works_stats_custody_agrees_with_its_representations`). The **compiled
human-readable**
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
verify` carries five batch selections over the same `custody` selectors:
`--unverified` (`unverified_items`), `--stale-before` (`items_checked_before`),
`--drift` (`items_in_posture`), and `--source` (the item-intrinsic `source`
filter, the one selection that reads no ledger — roadmap H125), plus `--all`. The
invariant asserts they relate as documented: `verify --drift <posture>`
re-captures exactly the rows `list --drift <posture>` enumerates (the act-side ≡
read-side drill, by the shared `items_in_posture`); `verify --source <S>`
re-captures exactly `list --source <S>`'s held, hash-bearing rows and clears that
source's `unverified` count in `doctor`'s `custody.by_source[S]` (the per-source
counterpart of how `--unverified` clears the whole-library bucket); `verify
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
`drifted`/`rotted`/`error`), and the stale enrichment/summary counts. It is
distilled from the same `run_doctor` custody view (network-free) via the
`custody_snapshot` primitive `scrolls maintain` records, so `status` can
never disagree with `doctor` or a maintenance snapshot
(`test_status_custody_headline_converges_with_doctor`). Before `init` the
`score` is honestly `null` (no store), not a fabricated `100`; an empty but
initialized library is trivially fully custodied (`100`), the "empty is
healthy" posture `doctor` reports.

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

| Key | Meaning |
| --- | --- |
| `initialized` / `schema_version` | `false`/`null` until `init` |
| `root` | library root in use |
| `items` | `total`, `by_stage` (always all three stages), `by_source` (present sources only), `unclassified` |
| `subscriptions` | followed feeds (`scrolls follow`) |
| `custody` | the custody headline — `score`, `tiers`, `drift` posture, `enrichment_stale`, `summaries_stale` (converges with `doctor`) |
| `headline` | the one-line `custody` block rendered (`_Custody: …_`), at parity with the `maintain` report's `headline` |
| `by_source` | the per-source `{tiers, drift, coverage}` custody breakdown (sorted keys; sums to `custody`), the status-surface counterpart of `doctor`'s `custody.by_source` / `maintain`'s `by_source` |

```console
$ scrolls status        # before init
{"initialized": false, "root": "/tmp/scrolls-demo.BgrqMO/home-empty", "schema_version": null, "items": {"total": 0, "by_stage": {"detected": 0, "fetched": 0, "rendered": 0}, "by_source": {}, "unclassified": 0}, "subscriptions": 0, "custody": {"score": null, "tiers": {"full": 0, "partial": 0, "reference": 0}, "drift": {"checked": 0, "unverified": 0, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "enrichment_stale": 0, "summaries_stale": 0}, "headline": "_Custody: 0 scroll(s)._"}
[exit 0]

$ scrolls status        # after the imports and adds below
{"initialized": true, "root": "/tmp/scrolls-demo.BgrqMO/home", "schema_version": 6, "items": {"total": 4, "by_stage": {"detected": 2, "fetched": 2, "rendered": 0}, "by_source": {"arxiv": 1, "x": 3}, "unclassified": 3}, "subscriptions": 0, "custody": {"score": 100, "tiers": {"full": 2, "partial": 0, "reference": 2}, "drift": {"checked": 0, "unverified": 4, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "enrichment_stale": 0, "summaries_stale": 0}, "headline": "_Custody: 4 scroll(s) · fidelity full 2, reference 2 · drift unverified 4._", "by_source": {"arxiv": {"tiers": {"full": 1, "partial": 0, "reference": 0}, "drift": {"verified": 0, "unverified": 1, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 1}}, "x": {"tiers": {"full": 1, "partial": 0, "reference": 2}, "drift": {"verified": 0, "unverified": 3, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 1}}}}
[exit 0]
```

*(x:1111 is already classified here — the Field Theory import's
frontmatter join carries `category` over — which is why `unclassified`
is 3 of 4)*

### `scrolls paths`

Print every library path (`test_paths_prints_layout_json`). `items` is a
reserved directory, currently unused; `media` holds files downloaded by
`scrolls media`.

```console
$ scrolls paths
{"root": "/tmp/scrolls-demo.BgrqMO/home", "items": "/tmp/scrolls-demo.BgrqMO/home/items", "scrolls": "/tmp/scrolls-demo.BgrqMO/home/scrolls", "library": "/tmp/scrolls-demo.BgrqMO/home/library", "media": "/tmp/scrolls-demo.BgrqMO/home/media", "agents": "/tmp/scrolls-demo.BgrqMO/home/agents", "db": "/tmp/scrolls-demo.BgrqMO/home/db.sqlite", "config": "/tmp/scrolls-demo.BgrqMO/home/config.toml"}
[exit 0]
```

### `scrolls doctor [--fix]`

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

### `scrolls verify [id] [--all | --unverified | --stale-before ISO | --drift POSTURE | --source S] [--limit N]`

Re-capture held items and record whether the live source still matches the
copy in custody (ADR 0098; cited tests in `tests/test_verify_cli.py` and
`tests/test_custody.py`). Verifying re-fetches an item through the same
adapter `scrolls fetch` uses, recomputes its content hash, diffs it against
the stored one, and appends a **custody event** to the ledger — it never
overwrites the original capture, so proving a source changed can never lose
what was held.

Exactly one *selection* is required — a single item `id`/URL, `--all`,
`--unverified`, `--stale-before`, `--drift`, or `--source` — never more than one
(`test_verify_needs_an_id_or_all`, `test_verify_rejects_id_and_all_together`,
`test_verify_rejects_all_and_unverified_together`,
`test_verify_rejects_all_and_stale_before_together`,
`test_verify_rejects_all_and_drift_together`,
`test_verify_rejects_all_and_source_together`,
`test_verify_rejects_source_and_drift_together`). `--all` re-checks every
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

`--limit N` paces a large `--all`/`--unverified`/`--stale-before`/`--drift`/`--source`
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

`--status <verdict>` is the **verdict axis** — return only the checks whose
`status` is one of the closed set `unchanged`/`drifted`/`rotted`/`error` (the
raw event verdict `history` emits, *not* the reader-facing drift posture — so
it is `unchanged`, not `verified`). "Show me only the times this source
actually *changed*" — an agent triaging a long ledger reads the drift/rot
events without scanning the steady-state re-checks
(`test_history_status_filters_to_one_verdict`). It is a closed vocabulary
guarded by argparse `choices` (an unknown verdict is a usage error, exit 2,
never a silent empty — `test_history_status_is_a_closed_vocabulary`), and
composes with the other two axes **verdict → window → cap**: filter the
verdict, then `--since` the time, then `--limit` the count
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
```

### `scrolls maintain [--all] [--limit N | --no-recheck | --history [N]] [--trend]`

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
`coverage_change`, and `stale_change` all null) and `posture: insufficient-history`
(honest absence). `--trend` only shapes a `--history` read; passed alone it is a
usage error (exit 2), never a silently-ignored flag that runs a full pass.

This is **report-only and idempotent** (custody-vision §2.4): it records drift
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
then the source name. The value is `{source, tiers, drift, reason}` — the flagged
source's own tally plus a one-line `reason` naming the loss (e.g. `"2 drifted, 1
rotted"`). Honest **`null`** when nothing stands out: an **empty** library (nothing
to flag), a **single** source (no source stands out — the whole-library `custody`
block already says everything; `attention` only adds value by discriminating
*across* sources, so a one-source library is null even with drift), or a
**fully-clean** library (no source carries any drifted/rotted loss — reference-only
is the normal capture posture, a tie-breaker, never a trigger). Like `by_source`,
it rides the live pass only.

The sharp custody point the delta makes visible (the dogfood proof's, recurring):
detecting source drift moves the *drift posture* (`unverified` → `drifted`)
**without lowering the integrity `score`** — raw is sacred, drift is a recorded
event, not a loss of what we hold. Exit mirrors `doctor`: nonzero only when
structural `issues` remain (run `doctor --fix` / `scrolls media`); drift and stale
enrichment/summaries are reported, never a failure.

```console
$ scrolls maintain --all --limit 50      # second run; force a whole-library recheck — one source has drifted
{"recorded_at": "2026-06-16T13:00:00+00:00", "recheck": {"skipped": false, "scope": "all", "since": null, "checked": 3, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0, "coverage": {"verified": 3, "total": 3}}, "compiled": {"items": 3, "sources": 2, "categories": 3, "concepts": 2, "tags": 3, "summaries": 0, "clusters": 0, "works": 0, "pages": 9}, "custody": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 3, "unverified": 0, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 3, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0}, "headline": "_Custody: 3 scroll(s) · fidelity full 3 · drift verified 2, drifted 1._", "by_source": {"arxiv": {"tiers": {"full": 1, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 1, "total": 1}}, "web": {"tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 0, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 2, "total": 2}}}, "attention": {"source": "web", "tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 0, "drifted": 1, "rotted": 0, "error": 0}, "reason": "1 drifted"}, "delta": {"first_run": false, "since": "2026-06-16T12:00:00+00:00", "score": {"before": 100, "after": 100, "change": 0}, "tiers": {"full": {"before": 3, "after": 3, "change": 0}, "partial": {"before": 0, "after": 0, "change": 0}, "reference": {"before": 0, "after": 0, "change": 0}}, "drift": {"checked": {"before": 0, "after": 3, "change": 3}, "drifted": {"before": 0, "after": 1, "change": 1}, "error": {"before": 0, "after": 0, "change": 0}, "rotted": {"before": 0, "after": 0, "change": 0}, "unchanged": {"before": 0, "after": 2, "change": 2}, "unverified": {"before": 3, "after": 0, "change": -3}}, "enrichment_stale": {"before": 0, "after": 0, "change": 0}, "summaries_stale": {"before": 0, "after": 0, "change": 0}}, "issues": 0, "suggested": []}
[exit 0]

$ scrolls maintain --history 2           # the custody trajectory, oldest first
[{"recorded_at": "2026-06-16T12:00:00+00:00", "snapshot": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 0, "unverified": 3, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0}, "delta": {"first_run": true, "since": null, "score": {"before": null, "after": 100, "change": null}}, "headline": "_Custody: 3 scroll(s) · fidelity full 3 · drift unverified 3._"}, {"recorded_at": "2026-06-16T13:00:00+00:00", "snapshot": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 3, "unverified": 0, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 3, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0}, "delta": {"first_run": false, "since": "2026-06-16T12:00:00+00:00", "score": {"before": 100, "after": 100, "change": 0}}, "headline": "_Custody: 3 scroll(s) · fidelity full 3 · drift verified 2, drifted 1._"}]
[exit 0]

$ scrolls maintain --history --trend     # the trajectory's direction in one word
{"trend": {"runs": 2, "since": "2026-06-16T12:00:00+00:00", "score": {"first": 100, "last": 100, "change": 0}, "drift_change": 1, "coverage_change": {"verified": 3, "total": 0}, "stale_change": {"enrichment": 0, "summaries": 0}, "posture": "regressing"}, "runs": [{"recorded_at": "2026-06-16T12:00:00+00:00", "snapshot": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 0, "unverified": 3, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 0, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0}, "delta": {"first_run": true, "since": null}, "headline": "_Custody: 3 scroll(s) · fidelity full 3 · drift unverified 3._"}, {"recorded_at": "2026-06-16T13:00:00+00:00", "snapshot": {"score": 100, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 3, "unverified": 0, "unchanged": 2, "drifted": 1, "rotted": 0, "error": 0}, "coverage": {"verified": 3, "total": 3}, "enrichment_stale": 0, "summaries_stale": 0}, "delta": {"first_run": false, "since": "2026-06-16T12:00:00+00:00"}, "headline": "_Custody: 3 scroll(s) · fidelity full 3 · drift verified 2, drifted 1._"}]}
[exit 0]

$ scrolls maintain --no-recheck          # a pass that found a deleted scroll and a stale category
{"recorded_at": "2026-06-16T14:00:00+00:00", "recheck": {"skipped": true, "checked": 0, "unchanged": 0, "drifted": 0, "rotted": 0, "error": 0}, "compiled": {"items": 3, "sources": 2, "categories": 3, "concepts": 2, "tags": 3, "summaries": 0, "clusters": 0, "works": 0, "pages": 9}, "custody": {"score": 67, "tiers": {"full": 3, "partial": 0, "reference": 0}, "drift": {"checked": 3, "unverified": 0, "unchanged": 3, "drifted": 0, "rotted": 0, "error": 0}, "coverage": {"verified": 3, "total": 3}, "enrichment_stale": 1, "summaries_stale": 0}, "headline": "_Custody: 3 scroll(s) · fidelity full 3 · drift verified 3._", "delta": {"first_run": false, "since": "2026-06-16T13:00:00+00:00", "score": {"before": 100, "after": 67, "change": -33}}, "issues": 1, "suggested": [{"command": "scrolls doctor --fix", "addresses": ["missing_scrolls"]}, {"command": "scrolls classify --stale", "addresses": ["enrichment_stale"]}]}
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

| Key | Meaning |
| --- | --- |
| `imported` | new items inserted |
| `skipped` | already present (id collision is the dedupe working) |
| `items` | item records read from the file (blank lines excluded) |

```console
$ scrolls import items /tmp/scrolls-demo.BgrqMO/library.jsonl
{"imported": 6, "skipped": 0, "items": 6}
[exit 0]

$ scrolls import items /tmp/scrolls-demo.BgrqMO/library.jsonl
{"imported": 0, "skipped": 6, "items": 6}
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

### `scrolls export items`

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

### `scrolls export events [--source S] [--category C] [--tag T] [--since ISO]`

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
```

### `scrolls export bundle <query> [--source S] [--category C] [--stage ST] [--tag T] [--concept K] [--format markdown|html]`

A scoped, self-contained **custody bundle** for a topic — one Markdown file
an agent can hand to a person or another library (ADR 0103, MVP M4,
`tests/test_bundle.py`). Two layers in one file: a readable **briefing**
(title + scope, then a one-line scope **custody headline** — `N scroll(s)`,
the fidelity-tier counts, and the drift-posture counts across the *whole*
bundle, so a reader gauges "how custody stands" without scanning every entry
(roadmap H45); its totals equal the per-scroll entries and `doctor`'s `custody`
aggregate for the same scope by construction, the bundle-level counterpart of
`status`'s custody headline — `test_scope_custody_headline_totals_equal_the_entries_and_doctor`),
then one entry per in-scope scroll naming its id, source, custody **fidelity**
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

`--format` (default `markdown`) chooses the output form (roadmap H39). `markdown`
is the **canonical, lossless, re-importable** bundle described above — the form
`scrolls import bundle` round-trips against. `html` renders the *same* scope and
the *same* per-scroll custody picture (fidelity tier, drift posture,
classification provenance, the scope custody headline, and a `--concept`
bundle's summary) as a **self-contained, browser-readable briefing** — one
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

| Key | Meaning |
| --- | --- |
| `imported` | new scrolls inserted |
| `skipped` | already present (id collision is the dedupe working) |
| `items` | scroll records read from the custody block |
| `events` | `{imported, skipped}` custody events restored / deduped from the events block |

```console
$ scrolls export bundle "database engine" > briefing.md

$ scrolls import bundle briefing.md
{"imported": 2, "skipped": 0, "items": 2, "events": {"imported": 3, "skipped": 0}}
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
H21, the obsidian "confidence levels" adaptation) so an agent knows *how much
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

### `scrolls list [--source S] [--stage S] [--category C] [--tag T] [--concept K] [--drift D] [--stale-before ISO] [--limit N] [--stats]`

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

`--drift D` is the one filter that is not a stored column: a custody **drift
posture** read from the verify ledger (`verified`/`unverified`/`drifted`/
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
`drift`, `method`) is reported, in that order, and a `field` narrows the
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

### `scrolls search <query> [--limit N] [--source S] [--category C] [--stage ST] [--tag T] [--concept K] [--stats]`

FTS5 BM25 over title/summary/extracted text, title weighted highest
(`src/scrolls/search.py`, `tests/test_search.py`). Query tokens are
quoted and AND-ed, so arbitrary agent input never hits FTS5 syntax
errors. `score` is SQLite's `bm25()`: results are ordered best-first and
**more negative means a stronger match**. Default limit 20
(`test_search_respects_limit_flag`). No matches prints `[]`; a blank
query is an error (`test_search_blank_query_is_an_error`).

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

Hit keys: `id`, `source`, `title`, `url`, `stage`, `score`, `snippet`
(matches bracketed, `…` for elided context), the per-item custody axes —
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

```console
$ scrolls search "sqlite fts5"
[{"id": "x:1111", "source": "x", "title": "@karpathy: SQLite FTS5 is criminally underrated for local search.", "url": "https://x.com/karpathy/status/1111", "stage": "rendered", "score": -2.9315057596986334, "snippet": "@karpathy: [SQLite] [FTS5] is criminally underrated for local search.", "fidelity": "full", "works": []}]
[exit 0]

$ scrolls search "attention transformer"
[{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered", "score": -3.40e-06, "snippet": "We propose the [Transformer] based on [attention] mechanisms.", "fidelity": "full", "works": [{"doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222", "canonical": "crossref:10.5555/3295222", "is_canonical": false, "representations": 2}]}, {"id": "crossref:10.5555/3295222", "source": "crossref", "title": "Attention Is All You Need", "url": "https://doi.org/10.5555/3295222", "stage": "fetched", "score": -3.40e-06, "snippet": "We propose the [Transformer] based on [attention] mechanisms.", "fidelity": "partial", "works": [{"doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222", "canonical": "crossref:10.5555/3295222", "is_canonical": true, "representations": 2}]}]
[exit 0]

$ scrolls search "sqlite fts5" --source arxiv
[]
[exit 0]

$ scrolls search "sqlite fts5" --limit 1 --stats
{"scope": {"query": "sqlite fts5", "limit": 1}, "stats": {"returned": 1, "matched": 3, "truncated": true, "custody": {"tiers": {"full": 2, "partial": 1, "reference": 0}, "drift": {"verified": 0, "unverified": 3, "drifted": 0, "rotted": 0, "error": 0}}}, "results": [{"id": "x:1111", ...}]}
[exit 0]

$ scrolls search "sqlite fts5" --source arxiv --stats
{"scope": {"query": "sqlite fts5", "source": "arxiv", "limit": 20}, "stats": {"returned": 0, "matched": 0, "truncated": false, "custody": {"tiers": {"full": 0, "partial": 0, "reference": 0}, "drift": {"verified": 0, "unverified": 0, "drifted": 0, "rotted": 0, "error": 0}}}, "results": []}
[exit 0]

$ scrolls search "   "
{"error": "search query has no searchable tokens"}
[exit 1]
```

The last `--stats` call is the honest empty: nothing matched, but the
result still names the scope it checked (`query`, `source=arxiv`), so it
can never be misread as "the library holds nothing about sqlite."

### `scrolls related <id> [--limit N] [--stats]`

Deterministic, explainable connections (IDEAS.md §10,
`tests/test_related.py`): link edges in either direction (resolved
through source detection, so a tweet linking to `arxiv.org/abs/X` finds
item `arxiv:X`), shared concepts, shared tags, same category/domain as
weak corroboration. `score` is an integer (higher = more connected) and
every hit carries its `reasons` plus the neighbour's `fidelity` tier
(`full`/`partial`/`reference`, ADR 0097/0100), its custody `drift` posture
(`verified`/`unverified`/`drifted`/`rotted`/`error`, roadmap H56, read from the
verify ledger), and `last_checked` — *when* that drift verdict was taken, or
`null` when never re-checked (roadmap H86) — so following an edge tells you how
much of the item you land on the library holds, whether that source has drifted
out from under the capture, *and as of when*: the same per-item custody picture
the `graph` node shape and the browse rows carry. Default
limit 10. Unknown id is an error envelope on stderr.

`--stats` wraps the array in the same scope-honest `{scope, stats,
results}` envelope `search`/`list` use (the completeness contract G2):
`scope` names the anchor `item` and the `limit`, and `stats` reports
`returned`, `matched` (every item that relates, counted past the cap —
`src/scrolls/related.py` `count_related`), `truncated`, and a `custody`
tally (roadmap H99) — the same `{tiers, drift}` fidelity-tier/drift-posture
maps `search`/`list --stats` carry, here folded over the anchor's *related
neighbourhood* (the full scored set, pre-cap, excluding the anchor itself),
so a reader sees "of the N items related to this one, how much is held in
full and how much has drifted" without a second `facets` call. Each map sums
to `matched`. Opt-in: without it the output is the bare array unchanged
(`test_cli_related_stats_is_opt_in_default_stays_a_bare_array`,
`test_cli_related_stats_echoes_anchor_and_marks_truncation`,
`test_cli_related_stats_custody_tallies_the_matched_related_set`).

```console
$ scrolls related x:2222
[{"id": "arxiv:1706.03762", "source": "arxiv", "title": null, "url": "https://arxiv.org/abs/1706.03762", "stage": "detected", "score": 5, "reasons": ["links to it"], "fidelity": "reference", "drift": "unverified", "last_checked": null}]
[exit 0]

$ scrolls related x:2222 --limit 1 --stats
{"scope": {"item": "x:2222", "limit": 1}, "stats": {"returned": 1, "matched": 3, "truncated": true, "custody": {"tiers": {"full": 0, "partial": 0, "reference": 3}, "drift": {"verified": 0, "unverified": 3, "drifted": 0, "rotted": 0, "error": 0}}}, "results": [{"id": "arxiv:1706.03762", ...}]}
[exit 0]
```

### `scrolls graph [--all]`

The whole-library link graph in one call (ADR 0044, `tests/test_graph.py`).
Where `related` scores *one* item's neighborhood, this resolves *every*
item's links into directed edges — `from → to` whenever a link inside one
saved item names another (a tweet citing a paper, a model's `arxiv:` tag,
a preprint's published DOI), with `via` the link that matched. Resolution
is the same two-sided, source-detecting match `related` uses (ADR 0023),
so the graph is exactly the connections `related` would find, materialized
at once. Nodes carry the `id`, `source`, `title`, `url`, `stage`, `fidelity`,
`drift`, `last_checked` shape `related` hits use — the full per-item custody
picture travels with the node: the `fidelity` tier (how much is held, ADR 0100),
the `drift` posture (whether the source moved, roadmap H56, read from the verify
ledger), and `last_checked` (*when* that posture was taken, or `null` when never
re-checked, roadmap H86) — the same three fields a `related` hit and the browse
rows carry, read through the same `custody.drift_posture`/`custody.last_checked`
over `latest_events`, so a node reads the same wherever it is reached. Sorted by
id; edges sorted by `(from, to)`.

Nodes are the *connected* items by default — `--all` widens it to every
item, isolated ones included. `stats.items` is always the library total,
so `nodes`/`edges` read as connectivity against the whole; `stats.clusters`
counts the connected components with 2+ members — the link clusters the
KB's `graph.md` page renders (ADR 0062), so a singleton added by `--all` is
not counted (`test_cli_graph_stats_count_clusters`). An empty or
uninitialized library is an empty graph, exit 0.

`stats.custody` is the graph-surface member of the custody-headline family
(`scrolls status`, the bundle/`context` briefings, `facets fidelity`/`drift`):
fidelity-tier and drift-posture count maps over the whole `stats.items` scope
(not just the connected nodes), so it is independent of `--all`
(`test_graph_stats_custody_is_independent_of_include_all`) and converges with
`doctor`'s `custody` block, `facets`, and the scope headlines for the same scope
(`test_graph_custody_block_converges_with_doctor`). Graph emits JSON, so the
counts travel directly — `verified` is the ledger `unchanged` (custody §2.4),
`unverified` the held items with no verdict.

```console
$ scrolls graph
{"nodes": [{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered", "fidelity": "full", "drift": "verified", "last_checked": "2026-06-14T00:00:00+00:00"}, {"id": "x:2222", "source": "x", "title": "@karpathy: the attention paper still holds up", "url": "https://x.com/karpathy/status/2222", "stage": "rendered", "fidelity": "full", "drift": "unverified", "last_checked": null}], "edges": [{"from": "x:2222", "to": "arxiv:1706.03762", "via": "https://arxiv.org/abs/1706.03762"}], "stats": {"items": 2, "nodes": 2, "edges": 1, "clusters": 1, "custody": {"tiers": {"full": 2, "partial": 0, "reference": 0}, "drift": {"verified": 1, "unverified": 1, "drifted": 0, "rotted": 0, "error": 0}}}}
[exit 0]
```

### `scrolls works [ref] [--min N]`

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
id; works sort by representation count then DOI. `--min N` sets the minimum
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
{"scope": {"min_representations": 2}, "works": [{"doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222", "canonical": "crossref:10.5555/3295222", "representations": [{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered", "fidelity": "full", "drift": "unverified", "last_checked": null}, {"id": "crossref:10.5555/3295222", "source": "crossref", "title": "Attention Is All You Need", "url": "https://doi.org/10.5555/3295222", "stage": "fetched", "fidelity": "partial", "drift": "unverified", "last_checked": null}]}], "stats": {"items": 2, "works": 1, "custody": {"tiers": {"full": 1, "partial": 1, "reference": 0}, "drift": {"verified": 0, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0}}}}
[exit 0]

$ scrolls works arxiv:1706.03762
{"scope": {"ref": "arxiv:1706.03762"}, "works": [{"doi": "10.5555/3295222", "url": "https://doi.org/10.5555/3295222", "canonical": "crossref:10.5555/3295222", "representations": [{"id": "arxiv:1706.03762", "source": "arxiv", "title": "Attention Is All You Need", "url": "https://arxiv.org/abs/1706.03762", "stage": "rendered", "fidelity": "full", "drift": "unverified", "last_checked": null}, {"id": "crossref:10.5555/3295222", "source": "crossref", "title": "Attention Is All You Need", "url": "https://doi.org/10.5555/3295222", "stage": "fetched", "fidelity": "partial", "drift": "unverified", "last_checked": null}]}], "stats": {"items": 2, "works": 1, "custody": {"tiers": {"full": 1, "partial": 1, "reference": 0}, "drift": {"verified": 0, "unverified": 2, "drifted": 0, "rotted": 0, "error": 0}}}}
[exit 0]
```

### `scrolls context <query> [--limit N] [--budget B] [--source S] [--category C] [--stage ST] [--tag T] [--concept K]`

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

`--budget` bounds the bundle's *depth* — a budgeted boot sequence, identity/
index first, deep bodies on demand (MVP M3, the obsidian L0–L3 adaptation,
`tests/test_context.py`). The three tiers are strictly nested: `index` is the
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

```console
$ scrolls context "local search"
# Scrolls Context Bundle: local search

_Coverage: all 1 matching scrolls._

_Custody: 1 scroll(s) · fidelity full 1 · drift unverified 1._

## Best Matches

1. @karpathy: SQLite FTS5 is criminally underrated for local search. (`x:1111`) — technique

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

## Derived artifacts

### `scrolls kb [--engine ...] [--stale]`

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
| `list_scrolls(source=None, stage=None, category=None, tag=None, concept=None, drift=None, stale_before=None, limit=50)` | `scrolls list` | item summaries by facet (with the per-item custody axes `fidelity` + `drift` (H58) + `last_checked` (H84) and `works` membership, ADR 0101), no query (ADR 0060); `drift` filters by posture (H54), `stale_before` by staleness window (H85) |
| `list_facets(field=None, source=None, category=None, stage=None, tag=None, concept=None, limit=20)` | `scrolls facets` | the filterable vocabulary with counts, optionally scoped (ADR 0080) |
| `get_scroll(item_id)` | `scrolls show` | full item record + the per-item custody axes (`fidelity` + `drift` (H61) + `last_checked` (H84)) and `classification` view; `item_id` is an id or the item's URL (ADR 0028) |
| `get_scroll_history(item_id, limit=None, since=None, status=None)` | `scrolls history <id> [--limit N] [--since ISO] [--status V]` | the item's custody-ledger timeline (each `{checked_at, status, prior_hash, observed_hash, detail}`, newest first); three filter axes applied verdict → window → cap: `status` (unchanged/drifted/rotted/error) the verdict, `since` the time window, `limit` the count; `[]` when never verified or nothing matches, error on an unknown id, malformed `since`, or unknown `status`; `item_id` is an id or URL (ADR 0028; `test_get_scroll_history_status_filters_like_the_cli`) |
| `get_related_scrolls(item_id, limit=10)` | `scrolls related` | hits with `reasons` and the per-item custody axes (`fidelity` + `drift` (H56) + `last_checked` (H86)); `item_id` is an id or URL (ADR 0028) |
| `get_link_graph(include_isolated=False)` | `scrolls graph` | `{nodes, edges, stats}` link graph (ADR 0044); each node carries the per-item custody axes (`fidelity` + `drift` (H56) + `last_checked` (H86)) |
| `get_works(min_representations=2)` | `scrolls works` | `{works, stats}` — same-work clusters by DOI (ADR 0069); each representation carries the per-item custody axes (`fidelity` + `drift` (H64) + `last_checked` (H87)); `stats.custody` tallies the reported reps (H100) |
| `get_concept_page(concept)` | reading `library/concepts/<slug>.md` | Markdown page |
| `get_tag_page(tag)` | reading `library/tags/<name>.md` | Markdown page; tag matched case-insensitively, slug collisions resolved by heading (ADR 0064) |
| `list_sources()` | — | item counts per source |
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
