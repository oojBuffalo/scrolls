# Scrolls Architecture

How the implemented system works today, with pointers into the code and
tests that prove each claim. For the product vision and design brainstorm
see `IDEAS.md`; for the rationale behind individual decisions see the
ADRs indexed at `docs/adr/README.md`.

Everything below describes code on this branch, verified by
`uv run pytest` (1945 tests at the time of writing). The docs themselves
are guarded by `tests/test_docs.py`: cited test names, relative links,
and `IDEAS.md §N` references must resolve, and `docs/cli.md`'s captured
examples are pinned to the code's version and schema.

## The pipeline

The mental model `Sources → Items → Scrolls → Library → Agents` maps to
a small set of idempotent stages. Each item row carries a `stage` column;
each command moves items between stages or derives artifacts from them.

```text
 feed ── follow ───────▶ subscription ── sync ──▶ new entry URLs join at 'detected'
 OPML ── import opml ──┘

 URL ── add ──▶ detected ── fetch ──▶ fetched ── md ──▶ rendered
                  │ ▲                   ▲                  │
                  │ ├ import google-takeout                │
                  │ ├ import bookmarks                     │
                  │ └ import pocket                        │
                  │   import fieldtheory┘                  ▼
                  │            classify (stage-neutral, sets category)
                  │            media    (stage-neutral, downloads media refs)
                  │            kb       (stage-neutral, compiles library/)
                  │
                  └─ sources without a fetch adapter stay 'detected'
```

- `scrolls add <url>` detects the source, mints a stable id, and inserts
  a row at stage `detected` (`src/scrolls/cli.py`, `src/scrolls/items.py`).
- `scrolls fetch [id]` runs the source adapter, filling title, extracted
  text, summary, links, media, content hash, and provenance, and moves
  the item to `fetched` (`src/scrolls/sources/`). `--limit N` paces a
  batch run — at most N attempts, oldest saved first, resuming next
  run — so a bulk-imported spine enriches incrementally.
- `scrolls md [id]` renders each fetched item to a Markdown scroll at
  `scrolls/<source>/<slug>.md` and moves it to `rendered`
  (`src/scrolls/render.py`).
- `scrolls classify [id]`, `scrolls media [id]`, and `scrolls kb` are
  stage-neutral engines: classification assigns `category` without
  advancing the stage, media capture downloads items' media refs into
  `media/<source>/`, and the KB compiler rebuilds `library/` from
  whatever is rendered (`src/scrolls/classify.py`,
  `src/scrolls/media.py`, `src/scrolls/kb.py`).
- **Enrichment is provenance-complete and re-derivable** (PRD cap 8,
  custody-vision §3.6). Every engine that writes a derived field records
  *how* it was produced, in `provenance`, alongside (never replacing) the
  capture facts: the rules engine stamps `classified_by="rules-v1"`,
  the precedence tier that fired (`classified_basis` — one of
  `curated-source` / `title-pattern` / `documentation-url` / `weak-source`),
  and a fingerprint of the rule tables it ran under (`classified_ruleset`,
  `RULESET_FINGERPRINT`) so a held classification names the exact ruleset
  that produced it (`classify.py`, roadmap H20); the LLM classifier adds
  `classified_model` (`classify_llm.py`); and the LLM concept summaries
  store a `members_hash` fingerprint of the scrolls they synthesize so an
  unchanged concept is skipped on re-run (`kb_llm.py`). A derived
  `classification` view (`items.classification_view` over a raw provenance
  dict, exposed as `items.classification_provenance` for an item — `by` /
  `basis` / `ruleset` / `model`) carries this onto every browse and inspect
  surface identically: `scrolls list`, `show`, `search`, and the MCP
  `list_scrolls` / `get_scroll` / `search_scrolls` twins (the ranked surfaces
  derive it per-hit from the FTS row's own provenance column via the shared
  `search.hit_payload` serializer, so it costs no extra query and the `--stats`
  scope/truncation stays honest — roadmap H26). Every present view also carries
  a derived `confidence` marker (`items.classification_confidence`, roadmap H21,
  the obsidian "confidence levels" adaptation): `level` (`deterministic` for a
  rules match, `inferred` for an LLM category — the trust axis) and, for the
  rules engine only, `freshness` (`current` / `stale` / `unknown` against the
  live ruleset — the recency axis; omitted for the LLM, where there is no ruleset
  and a timestamp would break idempotence, so no freshness is fabricated). The
  freshness leg delegates to `classify.classification_freshness`, the *single*
  recency primitive `doctor`'s `custody.enrichment` aggregate and `classify
  --stale` also read, so the per-item marker an agent sees can never disagree
  with the count doctor reports. `scrolls facets method` is the
  aggregate axis of the same view (roadmap H28): the library bucketed by how each
  held category was produced — `rules-v1` / `llm-v1`, or the honest `user-set` /
  `unclassified` buckets — built from the same `classification_view`, so the
  counts and the per-item view never disagree. The custody axes are browsable
  too: `scrolls facets fidelity` buckets by custody tier and `scrolls facets
  drift` (roadmap H48) by drift posture (`verified`/`unverified`/`drifted`/
  `rotted`/`error`) read through the same `custody.drift_posture`/`latest_events`
  `doctor`'s `custody.drift` and the scope custody headlines use, so the browse
  aggregate converges with them for a scope. The `unverified` bucket all of these
  count — held items the ledger has no verdict for, the one
  `custody.unverified_items` predicate `doctor`'s `custody.drift.unverified` now
  delegates to — is made actionable by `scrolls verify --unverified` (roadmap
  H51), which re-checks exactly that hash-bearing set, so a re-check clears the
  bucket those surfaces flag (the report→refresh pairing `classify --stale` /
  `kb --stale` have on the enrichment axes, on the verify axis). The count is
  also *enumerable*: `scrolls list --drift <posture>` (+ the MCP `list_scrolls`
  twin, roadmap H54) selects the held items in a posture through the shared
  `custody.items_in_posture` selector (the read-side sibling of
  `unverified_items`, over the same `drift_posture`/`latest_events`), so the rows
  it returns total `facets drift`'s count for that posture — drill from the
  aggregate to the items, the read-side companion of `verify --unverified`'s
  act-side selection. Beyond filtering, the per-item drift posture *rides* the
  primary browse rows themselves (roadmap H58): `items.item_summary` (→ `scrolls
  list` + MCP `list_scrolls`) and `search.SearchHit`/`hit_payload` (→ `scrolls
  search` + MCP `search_scrolls`) each carry a `drift` field beside `fidelity`,
  populated from one `latest_events` read per call passed in (the way `works`
  membership is, so the surface reads the ledger once, not per row). So every
  browse/landing surface — `list` rows, `search` hits, `related` hits (H56),
  `graph` nodes (H56), and the bundle briefing (H42) — reports the *same*
  two-axis per-item custody picture (`fidelity` = how much is held, `drift` =
  whether the source moved), each through the same `custody.drift_posture` over
  `latest_events`, so a given item reads the same posture wherever an agent
  reaches it, and the posture a `list` row shows is exactly the one its `--drift`
  filter selects on. The cross-engine contract — method is recorded,
  re-derivation is deterministic, the capture chain survives, and nothing
  unmatched is fabricated — is pinned as one invariant in
  `tests/test_enrichment_provenance.py` (the cap-8 baseline, the way
  `test_completeness.py` pins M2). `scrolls doctor` makes the ruleset
  fingerprint actionable: its `custody.enrichment` block reports items
  classified under a *superseded* ruleset (stored `classified_ruleset` ≠
  the live `RULESET_FINGERPRINT`) as a re-derivable, report-only signal —
  never auto-reclassified, the drift block's enrichment counterpart
  (roadmap H25). `scrolls classify --stale` is the explicit refresh that
  acts on that signal: it re-runs the rules engine over exactly the items
  doctor reports stale (the one shared predicate
  `classify.is_stale_classification` backs both, so the count doctor shows
  equals the count the refresh touches, and it converges), refreshing
  `category` + `classified_ruleset` to the live ruleset — regeneration on
  request, never doctor's silent overwrite, closing the loop H20 (record) →
  H25 (report) → H27 (refresh). User overrides stay out of that pool: a
  hand-set category drops the engine stamp (`overrides.apply_overrides`), so
  it is never counted stale and never refreshed — user overrides always win.
  The classification axis now also carries a per-item confidence/recency marker
  (roadmap H21, above). The **summary axis** mirrors it (roadmap H29): a derived
  `summary_provenance` view (`kb_llm.summary_provenance` over a stored
  `ConceptSummary` and the concept's live members — `by` / `members_hash` /
  `freshness`, `None` when never synthesized) and a `doctor` `custody.summaries`
  block that reports summary-eligible concepts (≥ `MIN_MEMBERS` rendered members,
  the one shared `kb_llm.eligible_concepts` denominator the generators use) whose
  stored summary's `members_hash` no longer matches the live members as `stale` —
  the membership moved since synthesis, so the summary is regenerable. Like
  enrichment, it is report-only and never auto-regenerated; the view, the doctor
  aggregate, and `scrolls kb --stale` (roadmap H31) share one
  `kb_llm.summary_freshness` primitive (`current` / `stale` / `never`), so the
  per-concept marker, doctor's counts, and the refresh pool can never disagree —
  the convergence the classification axis pins, on the summary axis. `scrolls kb
  --stale` is the explicit refresh that acts on the signal: it re-synthesizes
  **only** the concepts doctor flags stale (the shared `kb_llm.is_stale_summary`
  predicate, so the count converges and refreshing clears the signal), implying
  the llm engine and composing with `--batch`, while leaving never-summarized
  concepts and orphan pruning to a full `kb --engine llm` — a targeted refresh on
  request, never doctor's silent overwrite, closing the summary-axis loop H29
  (record/report) → H31 (refresh), the counterpart of `classify --stale`.
- `scrolls ingest <url>` chains add → fetch → classify → md for one URL.
- `scrolls import fieldtheory` bulk-inserts X bookmarks directly at stage
  `fetched`, since the archive already contains the content
  (`src/scrolls/fieldtheory.py`, ADR 0009).
- `scrolls import google-takeout` bulk-inserts YouTube watch history at
  stage `detected` — Takeout is a spine with no content, so the export's
  title/channel/watch-time seed items the way feed entries do and
  `scrolls fetch` enriches them (`src/scrolls/takeout.py`, ADR 0029).
- `scrolls import bookmarks` bulk-inserts a browser bookmarks HTML
  export at stage `detected` — another bare spine, but heterogeneous:
  each URL routes through the same detection as `add`, and folder
  ancestry becomes `tags` (`src/scrolls/bookmarks.py`, ADR 0030).
  `scrolls export bookmarks` is the inverse: `bookmarks.dump_bookmark_export`
  serializes the library's items back to a Netscape bookmark file on stdout
  (the artifact-is-the-output convention), carrying the item spine — URL,
  title, `saved_at` → `ADD_DATE`, `tags` → a flat `TAGS` attribute — so a
  curated library moves back into any browser or read-later tool, the
  round-trip that makes the import a way-station rather than a sink (ADR 0079).
- `scrolls import pocket` bulk-inserts a Pocket CSV data export
  (`title,url,time_added,tags,status`; a `.zip` of `part_*.csv`, a
  directory, or one `.csv`) at stage `detected` — the read-later spine,
  the same heterogeneous bookmarks shape: each URL detects like `add`,
  `time_added` → `saved_at`, pipe-delimited Pocket `tags` → `tags`, and
  a title equal to the URL (Pocket's "no title") is dropped for fetch to
  fill; columns are read by header name, so any `url`-bearing CSV imports
  (`src/scrolls/pocket.py`, ADR 0074).
- `scrolls import opml <path>` bulk-inserts feed *subscriptions* from an
  OPML file — the universal feed-list export of every RSS reader — the one
  import that produces subscriptions, not items: each feed `<outline>`
  becomes a `subscriptions` row with the same `make_subscription_id` a
  manual `follow` mints (so the two dedupe), and the first `sync` discovers
  its entries. Network-free unlike `follow` (which validates by fetching):
  the `xmlUrl` is trusted on import the way a bookmarks export's URLs are,
  a dead feed surfacing only on its first sync; parsed from bytes (the XML
  encoding declaration), folders walked but dropped (subscriptions carry no
  tags), non-http feeds counted (`src/scrolls/opml.py`, ADR 0076).
  `scrolls export opml` is the inverse: `opml.dump_opml_export` serializes
  the library's subscriptions back to an OPML document on stdout (the
  artifact-is-the-output convention), the round-trip that makes the import a
  way-station rather than a sink (ADR 0077).
- `scrolls export items` / `scrolls import items <path>` are the **lossless**
  export pair (`src/scrolls/items_export.py`, ADR 0082): where `export opml`
  and `export bookmarks` round-trip against external tools and so carry only a
  spine, this round-trips against Scrolls' own model and carries **every**
  `ScrollItem` field (extracted text, links, media, provenance, content hash,
  stage) as JSON Lines on stdout — one item per line via `items.item_to_dict`.
  It is the back-up / migrate / merge format. `import items` restores the
  index rows with `INSERT OR IGNORE` (dedupe by id) at whatever stage each item
  carried; the derived scrolls/media/`library/` rebuild from those rows with
  `scrolls doctor --fix` and `scrolls kb`. Malformed input is rejected loudly
  (a backup must not restore silently incomplete), unknown keys tolerated
  (forward compatibility).
- `scrolls export bundle <query>` / `scrolls import bundle <path>` are the
  **shareable** complement (`src/scrolls/bundle.py`, ADR 0103): one
  self-contained Markdown file that is both a readable topic *briefing* (per
  scroll: id, source, custody fidelity tier, capture timestamp, link, capped
  excerpt, its verify-ledger **drift posture**
  `verified`/`unverified`/`drifted`/`rotted`/`error` via the shared
  `custody.drift_posture` over `latest_events` — so the briefing posture and
  `doctor`'s `custody.drift` aggregate cannot disagree, roadmap H42 — and —
  when an engine classified it — the `classification` view
  `by`/`basis`/`confidence`; a `--concept`-scoped bundle also carries that
  concept's synthesized summary and its `summary_provenance`, roadmap H35, so
  *how a result was derived* and *how custody stands* travel in the reading, not
  only the data) and a
  lossless re-import unit — the same `item_to_dict` JSONL `export items` writes,
  embedded in a code fence wrapped in the ADR 0102 `@generated` sentinel. The
  briefing's provenance lines are *derived read views* (omitted on honest
  absence), outside the fence, so the round-trip stays a property of the JSONL
  block alone. The bundle is *scoped* (a query + the `context`/`search`
  facets) and *complete about that scope* (every match, not a top-N), so it is
  the "take it with me" half of the dogfood flow where `export items` is the
  whole-library backup. `import bundle` reuses the `import items` path
  (`item_from_dict`, `INSERT OR IGNORE`), so losslessness is the ADR 0082/0099
  property already tested; the sentinel keeps the briefing body hand-annotatable
  across a re-export (refresh-safe, ADR 0102). Above the entries a one-line scope
  **custody headline** (`custody.custody_headline`/`custody_counts`: N scrolls,
  fidelity-tier and drift-posture counts over the in-bundle scrolls, roadmap H45)
  summarises how custody stands across the whole bundle; the *same* shared
  headline rides the `scrolls context` bundle from the `connected` tier up
  (roadmap H47) and `scrolls status`'s custody block (H38), so the scope
  headlines converge for a scope by construction — one custody tally, many
  surfaces. The `scrolls graph` payload carries the same tally as a JSON
  `stats.custody` block (the count maps, not a rendered line, since graph emits
  JSON) over its whole `stats.items` scope (roadmap H52), and `scrolls facets
  fidelity`/`drift` (H48) are the browse aggregates of the two axes — all reading
  `custody.custody_counts`, so the cross-surface convergence is pinned once in
  `tests/test_custody_convergence.py` (H50). The full dogfood flow these
  surfaces compose into — *hold → prove (`doctor`) → detect (`verify`) → take it
  with me (`export`/`import bundle`)* — is narrated, with captured before/after
  custody output, in [`docs/dogfood.md`](dogfood.md) and proven offline against
  fixtures in `tests/test_dogfood.py` (MVP M5).
- `scrolls maintain` (`src/scrolls/maintain.py`) is the dogfood flow's *recurring*
  sibling — one scheduled custody-maintenance pass: bounded **recheck**
  (`verify --all`, `--limit`/`--no-recheck`) → **regenerate** views (deterministic
  `compile_kb`) → read-only **audit** (`run_doctor`) → a **custody delta** against
  the snapshot the last run recorded at `<root>/.maintenance/last-run.json`. The
  composition already ships; the module owns only the new piece — `custody_snapshot`
  distils a doctor report into the comparable scalars (`score`, `tiers`, drift
  posture, `enrichment_stale`/`summaries_stale`), `compute_delta` diffs this run's
  snapshot against the last (`first_run` when there is no baseline; a baseline
  missing an axis reads zero, the ADR 0082 forward-compat posture). Report-only and
  idempotent (custody §2.4): it records drift events and regenerates views but never
  repairs rows, reclassifies, or re-summarizes — `doctor --fix` / `classify --stale`
  / `kb --stale` stay the explicit on-request mutations; the dot-prefixed snapshot
  is never a compiled page and never created by `init`, so a lost/corrupt one just
  degrades to "first run". The delta makes the dogfood's custody point recurring:
  source drift moves the *drift posture* without lowering the integrity *score*
  (`tests/test_maintain.py`; roadmap H22/H23/H34). Each run also **appends** its
  `{recorded_at, snapshot, delta}` to an append-only `<root>/.maintenance/log.jsonl`
  (the custody-ledger posture: append, never rewrite); `scrolls maintain --history
  [N]` reads the last N runs back as a JSON array — the custody *trend*, not just
  the last diff. The history read is custody-safe like the snapshot: a missing log
  is an empty history and one corrupt line is skipped (roadmap H36). `--history
  --trend` (roadmap H46) wraps the window in a `{trend, runs}` envelope (the
  opt-in `search --stats` pattern, so the bare array stays the default and the
  completeness `[]` never regresses) whose `compute_trend` distils the first→last
  net `score`/drift movement into one `posture` — `regressing`/`improving`/`holding`,
  integrity-first; <2 runs is `insufficient-history` (a single point has no
  direction).
- `scrolls status` carries a one-line **custody headline** under its item
  counts (`custody`): integrity `score`, fidelity `tiers`, drift posture, and
  the stale enrichment/summary counts — "how custody stands" without parsing a
  full `doctor` report. It is the same `custody_snapshot(run_doctor(...))`
  distillation `maintain` records, so `status`, `doctor`, and a maintenance
  snapshot can never disagree (network-free; `score` is honestly `null` before
  `init`, `100` for an empty initialized library — the "empty is healthy"
  posture; `tests/test_cli.py`, roadmap H38).
- `scrolls follow <url>` / `scrolls sync [id]` subscribe to RSS/Atom
  feeds and register their new entry URLs at stage `detected` through
  the same detection/dedupe as `add` — sync discovers URLs, adapters
  still fetch (`src/scrolls/feeds.py`, ADR 0017).

Per-item failures never abort a batch: `fetch`, `md`, `media`,
`sync` (per subscription), and `kb --engine llm` (per concept) report
each failure in their JSON output and continue (`tests/test_cli.py`).

## Storage: SQLite is the index, Markdown is the artifact

Two stores, by design (IDEAS.md §3):

- **`db.sqlite`** — the canonical index. One `items` table whose columns
  mirror the `ScrollItem` dataclass one-to-one (`src/scrolls/items.py`,
  `src/scrolls/db.py`). List-valued fields (`tags`, `concepts`, `links`,
  `media`) and `provenance` round-trip through JSON text columns. An
  external-content FTS5 table (`items_fts`) over title/summary/extracted
  text is kept in sync by SQL triggers so no Python write path can forget
  it. A `subscriptions` table holds followed feeds and their sync
  state, including each feed's HTTP cache validators (ADR 0017,
  ADR 0019) — sync state belongs to the index, not config (IDEAS.md
  §3). A `concept_summaries` table holds the LLM concept engine's
  synthesized concept-page summaries with the members fingerprint that
  makes regeneration incremental (ADR 0025). `meta` carries the schema
  version (`SCHEMA_VERSION = 6`);
  `MIGRATIONS[n]` walks any version gap in one transaction, and opening a
  newer-versioned library raises instead of corrupting it
  (`tests/test_db.py`).
- **`scrolls/<source>/<slug>.md`** — the durable, human- and
  agent-readable artifact. Frontmatter lines are `key: <JSON value>`
  (YAML 1.2 is a JSON superset, so standard parsers read them with zero
  dependencies). Scrolls can always be rebuilt from the index;
  `markdown_path` is recorded so re-renders keep a stable path
  (`src/scrolls/render.py`, `tests/test_render.py`). The full file
  format — frontmatter keys, body sections, KB page formats, and the
  stability guarantees consumers may rely on — is specified in
  `docs/library-format.md`.

The library root is `~/.scrolls`, overridden by `$SCROLLS_HOME` — every
path derives from the root so tests and portable installs can relocate
the whole tree (`src/scrolls/paths.py`):

```text
$SCROLLS_HOME (default ~/.scrolls)
  db.sqlite      # items + subscriptions + concept_summaries tables + FTS5 index + schema meta
  scrolls/       # one Markdown scroll per rendered item, per source
  library/       # compiled KB: index.md, graph.md, sources/, categories/, concepts/
  agents/        # generated agent instruction files (claude/, codex/, hermes/)
  items/         # reserved (the raw record export is `scrolls export items`, to stdout; dir unused)
  media/         # captured media files (PDFs, thumbnails, photos), per source
  config.toml    # settings; today: [classify] default_engine + llm_model
```

## The data model

`ScrollItem` (`src/scrolls/items.py`) is the single normalized record
every source becomes — the IDEAS.md §12 model, frozen as a dataclass:
identity (`id`, `source`, `source_id`, `url`, `canonical_url`), content
(`title`, `author`, `published_at`, `raw_text`, `extracted_text`,
`summary`), classification (`category`, `domain`, `tags`, `concepts`),
graph edges (`links`, `media`), and bookkeeping (`content_hash`,
`markdown_path`, `provenance`, `stage`, `saved_at`).

Item ids are stable and deduplicating: `source:source_id` when the URL
carries a source-local id (`wikipedia:en:SQLite`, `arxiv:1706.03762`,
`x:1234567890`), else `source:` plus a 12-hex-char SHA-256 of the URL
(`make_item_id`). `scrolls add` of a tweet URL and a Field Theory import
of the same tweet therefore collide on purpose — `INSERT OR IGNORE`
keeps the existing row (`tests/test_items.py`, `tests/test_fieldtheory.py`).

Because the URL string itself is the identity of `web`/`pdf` items,
registration normalizes it first (`normalize_url` in
`src/scrolls/sources/urls.py`, ADR 0023): tracking params (`utm_*`,
`fbclid`, …), fragments, host casing, and default ports are dropped
before hashing and the normalized form is what gets stored, so the
same article saved via differently decorated links stays one item
(`tests/test_urls.py`). Everything else — param order, percent
encoding, ambiguous names like `ref` — survives byte-identical, and
feed subscription URLs are never rewritten.

## The source adapter model

Two small contracts make every platform the same kind of scroll
(IDEAS.md §1):

1. **Detection** — `detect_source(url) -> DetectedSource(source, source_id)`
   in `src/scrolls/sources/detect.py`. Pure URL inspection, no network:
   host tables map to `youtube`, `wikipedia`, `wikidata` (the
   structured-knowledge sibling of Wikipedia — a `wikidata.org` entity URL,
   the `Q<digits>` item id taken from the first path segment that is a QID so
   `/wiki/Q42`, the RDF concept URI `/entity/Q42`, and the canonical
   `/wiki/Special:EntityData/Q42.json` all detect alike, uppercased to canonical
   so `/wiki/q42` dedupes; Properties/Lexemes deferred as schema/meta, ADR 0075),
   `github` (a repo `owner/repo`, or — when the URL is `/issues/<n>` or the web
   PR path `/pull/<n>` — an issue/pull-request *discussion thread*
   `owner/repo#<n>`, a second content kind on the same source the adapter
   dispatches on the `#`, deep thread links deduping while `/blob`/`/tree`/the
   issue-and-PR lists collapse to the repo, ADR 0084),
   `gist` (a `gist.github.com` URL — the developer code-snippet type,
   its own source since the host/API/content differ from a repo; the gist id
   alone is the `source_id` (`gist:<id>`) because the API is keyed by it and the
   owner login is decorative, so `/<owner>/<id>`, a bare `/<id>`, and a revision
   URL all dedupe, the hex id folded lowercase; a bare one-segment id is claimed
   only at full modern-id length so a username's gist-list page isn't stolen,
   ADR 0078),
   `gitlab` (a
   `gitlab.com/<group>/<project>` URL — gitlab.com only, the second code
   host; the whole `group[/subgroup…]/project` path before any `/-/`
   sub-resource separator as `source_id`, nested-group-aware, folded
   lowercase since GitLab forces lowercase slugs, deep links deduping to the
   project — or, when the URL is `/-/issues/<n>` or `/-/merge_requests/<n>`, an
   issue/merge-request *discussion thread* in GitLab's own cross-reference
   notation `group/project#<n>`/`group/project!<n>`, the second content kind on
   the source the adapter dispatches on the marker, the github thread template
   ADR 0084 with one divergence GitLab forces: issues and MRs have **separate
   iid sequences**, so a bare `#<n>` is ambiguous and the `#`/`!` marker — which
   also picks the endpoint — disambiguates them, ADR 0055/0085), `gitea` (a `codeberg.org`/`gitea.com`
   `/<owner>/<repo>` URL — the third code host, one source for Gitea and its
   fork Forgejo; uniquely the *instance host rides in the* `source_id`
   (`<host>/<owner>/<repo>`, `www.` folded off, owner/repo verbatim) because
   the Gitea API lives on each instance's own host, so reaching a self-hosted
   instance later is a detection-only change, ADR 0056 — or, when the URL is
   `/issues/<n>` or the **plural** PR path `/pulls/<n>`, an issue/pull-request
   *discussion thread* `<host>/<owner>/<repo>#<n>`, the github thread template
   ADR 0084 since Gitea unifies numbering like github so one `#` marker suffices,
   the only divergence the plural `/pulls/` web path vs github's singular, deep
   thread links deduping while the lists/`/src` collapse to the repo, ADR 0086),
   `bitbucket` (a
   `bitbucket.org/<workspace>/<repo>` URL — the fourth code host, host-scoped
   with a single fixed API host like github since Bitbucket Cloud is one
   service, *not* host-in-id like gitea; the flat `<workspace>/<repo>` folded
   lowercase since Bitbucket auto-lowercases slugs and routes
   case-insensitively, deep links deduping to the repo, ADR 0057 — or, when the
   URL is `/issues/<n>` or the hyphenated PR path `/pull-requests/<n>`, an
   issue/pull-request *discussion thread* in gitlab's cross-reference notation
   `workspace/repo#<n>`/`!<n>`, since Bitbucket splits issue/PR numbering like
   gitlab so the marker disambiguates and picks the endpoint, the gitlab
   two-marker template ADR 0085 — completing the code-host thread family,
   ADR 0087), `arxiv`,
   `biorxiv` and `medrxiv` (the `/content/10.1101/<accession>` URL on each
   server's host, the `10.1101/<accession>` DOI as `source_id` with the `vN`
   version and `.full`/`.full.pdf`/early-access views stripped so every view
   dedupes; kept as *two* sources because a medRxiv paper does not live on
   bioRxiv, even though one fetch adapter serves both off the shared
   `api.biorxiv.org`, ADR 0068),
   `x`,
   `hackernews`, `lobsters` (a `/s/<short_id>` story URL, the short id
   verbatim), `bluesky` (a `bsky.app/profile/<actor>/post/<rkey>` post URL,
   `<actor>/<rkey>` as `source_id` with the actor folded lowercase — handle
   and DID are both case-insensitive — and the record key verbatim; the
   post's true AT-URI identity needs a DID resolvable only at fetch time,
   ADR 0048), the `stackexchange` network (every site's question
   URL, the per-site API slug carried in `source_id`), `pypi`
   (project pages, the PEP 503-normalized package name as `source_id` so
   a versioned page dedupes to the package), `npm` (package pages,
   the package name verbatim as `source_id` — the registry is
   case-sensitive, so unlike PyPI it is not folded — scoped names and
   version pages included), `crates` (crate pages, the name folded
   case-insensitively like a PyPI one so a version page dedupes),
   `packagist` (Composer package pages, the `vendor/name` folded
   lowercase as `source_id` since Composer names are case-insensitive, a
   trailing `.json` and deeper subpages stripped),
   `rubygems` (gem pages, the gem name verbatim as `source_id` since
   RubyGems is case-sensitive like npm, version pages included),
   `go` (`pkg.go.dev` module pages, the module path verbatim as
   `source_id` — case-sensitive, the part before any `@version`, with a
   domain first segment so stdlib and site routes carry no fetchable
   module),
   `devto` (a `dev.to/<user>/<slug>` article URL, the flat two-segment
   `<user>/<slug>` folded lowercase since Forem mints lowercase handles and
   slugs and the case-sensitive API only resolves the lowercase form — the
   gitlab/bitbucket fold — deep links deduping to the article, reserved
   `t`/site routes carrying no article, the URL handle being the author *or
   organization* the post is published under, ADR 0061),
   `crossref` (a `doi.org`/`dx.doi.org` DOI link, the DOI folded
   lowercase as `source_id` since DOIs are case-insensitive — the DOI's
   *registration agency*, Crossref, DataCite, or any other (JaLC, mEDRA, …)
   via content negotiation, is resolved at fetch time, not detection,
   ADR 0045/0081), and
   `huggingface` (model, dataset, and Space repo pages on
   `huggingface.co`/`hf.co`, the repo *kind* in the `source_id` as
   `model:<org>/<name>`, `dataset:<...>`, or `space:<...>` so one adapter
   serves all three API endpoints — the Stack Exchange shape — the id kept
   verbatim since the Hub is case-sensitive, subpages deduped to the
   two-segment repo, site routes carrying no fetchable repo), `openlibrary`
   (book pages on `openlibrary.org` — a *work* `/works/OL…W`, an *edition*
   `/books/OL…M`, or an `/isbn/<isbn>`; the kind rides in the `source_id`, but
   the OLID's own `W`/`M` type letter encodes work-vs-edition so only the ISBN
   form needs an `isbn:` prefix, the OLID uppercased to a canonical form and a
   title-slug/`/editions` subpage deduping to it — author/subject/search routes
   carry no book, ADR 0073), `zenodo` (open-science records on `zenodo.org` —
   datasets, software, preprints; the version-specific record id as `source_id`,
   taken from the digits after a `record`/`records` path segment so the modern
   `/records/<id>`, the legacy `/record/<id>`, and the pasted `/api/records/<id>`
   forms all detect alike and a deeper `/files`/`/preview` link dedupes; the recid
   is kept verbatim as a version id since `conceptrecid`/`conceptdoi` name the
   all-versions concept — the Open Library edition rule, ADR 0073/0083), and
   `pubmed`
   (the biomedical literature, the integer PMID as `source_id`; the
   dedicated `pubmed.ncbi.nlm.nih.gov` host is claimed wholesale with the
   PMID as the first path segment, while the legacy
   `ncbi.nlm.nih.gov/pubmed/<pmid>` form is *shape-matched* because that
   host also serves PMC/Gene/Nucleotide — those fall through to `web` —
   ADR 0065), and `rfc` (IETF technical standards via the RFC Editor's JSON
   view; **host-restricted shape matching** across `rfc-editor.org`,
   `datatracker.ietf.org`, `tools.ietf.org`, and `ietf.org` — only the
   `rfc<digits>` path shape is claimed, the integer number with leading zeros
   stripped so `rfc0020` and `rfc20` dedupe to `rfc:20`, while Internet-Drafts,
   working-group, and org pages on those shared hosts fall through to `web` —
   the legacy-NCBI-host posture, ADR 0066). Two
   *shape-only* branches then run on any host not already claimed, because
   the Fediverse is federated with no host set: `mastodon` matches a
   Mastodon-API status URL (`/@<user>/<digits>`, GoToSocial's
   `/@<user>/statuses/<id>`, Pleroma's `/notice/<id>`, the shared AP
   `/users/<user>/statuses/<id>`), `misskey` matches the Misskey-family
   `/notes/<id>`, and `lemmy` matches the link-aggregator `/post/<digits>`
   — all folding the instance host into the id (`<host>/<id>`,
   instance-local), each id constrained as strictly as its anchoring
   literal is weak (Lemmy's `post` literal needs an all-digits id and
   exactly two segments), a misdetect degrading to a benign failed
   fetch (ADRs 0049–0052). PieFed shares Lemmy's exact `/post/<digits>`
   shape, so it too detects as `lemmy` — which of the two backends actually
   serves a post (Lemmy's `/api/v3` or PieFed's `/api/alpha`) is resolved at
   *fetch* time by the `threadiverse` dispatcher, not at detection (ADR 0053,
   the DOI-dispatch pattern of ADR 0045). A fourth shape-only branch,
   `discourse`, then matches the forum software's `/t/<slug>/<id>` topic URL on
   any unclaimed host (`discourse:<host>/<topic_id>`, the slug display-only and
   dropped, the all-digits id carrying the weak `t` literal) — the **first
   non-Fediverse host-less source**, proving the shape-detection technique
   generalizes beyond ActivityPub (ADR 0054). Finally `.pdf`
   paths map to `pdf`; everything else is `web`. A
   known source with `source_id=None` means the adapter resolves
   identity at fetch time (`tests/test_detect.py`).
2. **Fetching** — a function `ScrollItem -> ScrollItem` that fills in
   content and returns the item at stage `fetched`, raising `FetchError`
   on any failure (`src/scrolls/sources/__init__.py`, ADR 0002). The
   `FETCH_ADAPTERS` dict maps source names to these functions. A source
   with no entry (today only `x`) is still registered by `scrolls add`
   but skipped by `scrolls fetch` until its adapter lands. One source can
   map to a *dispatch* over several adapters: `crossref` points at the
   `doi.py` dispatcher, a three-tier cascade — the Crossref adapter, then
   the DataCite one for a DOI Crossref doesn't hold (ADR 0045), then a
   generic content-negotiation adapter (`csl.py`) for a DOI neither holds,
   reaching every other registration agency (JaLC, mEDRA, …) at once
   through one CSL-JSON request (ADR 0081) — the registration agency can't
   be read off a `doi.org` URL, so it is resolved at fetch time, not
   detection.

Implemented fetch adapters, all keyless:

| Source | Module | Method | Distinctive output | ADR |
| --- | --- | --- | --- | --- |
| wikipedia | `sources/wikipedia.py` | MediaWiki action API, stdlib only | page categories → `concepts` | 0002 |
| wikidata | `sources/wikidata.py` | keyless entity-data `.json` + one batched `wbgetentities` label call, stdlib only | the structured-knowledge sibling of Wikipedia (only `Q<digits>` items, Properties/Lexemes deferred); `P31`/`P279` *type* relations → `concepts` resolved QID→label in one call (the Wikipedia-categories analog, ADR 0002); label → `title` (`en` then the script-agnostic `mul` then any), description → `summary` with **no `extracted_text`** (no prose body — the Crossref/Open Library shape), `tags` empty by design; English sitelink → `en.wikipedia.org` `link` (the **Wikidata↔Wikipedia edge**), `P856` → `link`, `P18` Commons image → `thumbnail`; `wikidata → reference`; `raw_text` is a slim projection since an entity can be hundreds of KB; degrades to metadata-only | 0075 |
| web | `sources/web.py` | `trafilatura` extraction | readable article text | 0001 (dep policy) |
| youtube | `sources/youtube.py` | oEmbed + optional `youtube-transcript-api` | transcript → extracted text; degrades to metadata-only | 0003 |
| github | `sources/github.py` | REST API + optional README | repo topics → `concepts`; `GITHUB_TOKEN` lifts rate limit | 0007 |
| github (issue / PR) | `sources/github.py` | keyless `GET /repos/<o>/<r>/issues/<n>` + optional comments | a second content kind on the **same** source — an issue or pull-request *discussion thread* (the HN/Lobsters/Discourse family at where developers argue about code), identity `owner/repo#<n>` (GitHub's cross-ref notation), the adapter dispatching on the `#` (the huggingface one-source-many-kinds shape ADR 0041, *not* gist's own-source split — an issue lives on github.com/api.github.com and extends the repo's id); the issues endpoint serves both issues and PRs (a PR carries a `pull_request` object) so one GET fetches the thread, comments a second GET (`?per_page=100`) only when present, degrading to body-only; Markdown body + `#### Comment by <user>` bylined comments → `extracted_text` (Lobsters/SE economy, no HTML), labels → `concepts` (the github-topics rule), kind + state (`issue`/`pull request`, `open`/`closed`/`merged` via `pull_request.merged_at`) → `tags`, a `github.com/<owner>/<repo>` link → the **issue↔repo edge** + body-URL scan → outbound edges; title leads `owner/repo#<n>:` (RFC rule); **no category default** — a thread is heterogeneous, so `github → project` applies only to repos (a `#`-bearing id is unclassified, the HN/gist honesty); degrades to metadata-only | 0084 |
| gist | `sources/gist.py` | keyless `GET /gists/<id>`, files inlined in one request | the developer code-snippet content type the repo adapter doesn't reach; identity is the gist id alone (`gist:<id>` — the owner login is decorative, the API resolves it, so `/<owner>/<id>`, bare `/<id>`, and revision URLs dedupe), hex id folded lowercase; one keyless GET returns the whole gist with each file's `content` inlined (Lobsters' economy, ADR 0046) → each file a sorted `### <filename>` fenced section in `extracted_text`; distinct file `language`s → `tags` (the bitbucket `language`→tag facet, ADR 0057), **`concepts` empty by design** (no topic facet); `title` = description else first filename, `summary` = a `"N files: …"` manifest, `author` = `owner.login`; **no category default** (a snippet is heterogeneous — the HN posture, ADR 0031); github's `GITHUB_TOKEN`/`GH_TOKEN` posture, all-blank-files → metadata-only | 0078 |
| gitlab | `sources/gitlab.py` | keyless REST API + optional README via the `/-/raw/` route | the second code host (gitlab.com only); nested-group path URL-encoded whole + folded lowercase; `topics` → `concepts`, SPDX `license.key` → `tag`; `GITLAB_TOKEN` (→`PRIVATE-TOKEN`) lifts the rate limit; degrades to metadata-only | 0055 |
| gitlab (issue / MR) | `sources/gitlab.py` | keyless `GET /projects/<enc>/{issues,merge_requests}/<iid>` + optional `/notes` | the github thread template (ADR 0084) on the next host, with the divergence GitLab forces — issues and MRs keep **separate iid sequences**, so identity is GitLab's own cross-reference notation (`group/project#<iid>` issue, `group/project!<iid>` MR) and the `#`/`!` marker both disambiguates *and* picks the endpoint (`#`→`/issues`, `!`→`/merge_requests`), unlike github's one endpoint serving both; the adapter dispatches on the marker (the huggingface one-source-many-kinds shape, *not* a new source — an MR lives on gitlab.com/api.github-style and extends the project's id); project path URL-encoded whole like a repo fetch; one GET for the thread, `/notes?sort=asc` a second only when `user_notes_count` > 0 — but gitlab.com **gates anonymous notes (401)** while serving the metadata keyless, so the common keyless case degrades to body-only and `GITLAB_TOKEN` reaches the conversation; Markdown description (no HTML strip) + `#### Comment by <username>` bylined notes → `extracted_text` with GitLab **system notes (`system: true`) dropped** as automated activity (the Discourse mod-action skip); labels → `concepts` (both bare-string and object shapes), kind + state → `tags` with the state **normalized to github's vocab** (`opened`→`open`, a merged MR read directly from `state`); `gitlab.com/<project>` link → thread↔project edge + body-URL scan; **no category default** — a thread is heterogeneous (the github carve-out, a `#`/`!`-bearing id stays unclassified); degrades to metadata-only | 0085 |
| gitea (incl. Forgejo) | `sources/gitea.py` | keyless `GET /api/v1/repos/<o>/<r>` + optional README via the API raw route | the third code host (codeberg.org/gitea.com), and the first to carry the instance host *in the id* (`gitea:<host>/<owner>/<repo>`) because the API is per-host not a single service — one adapter for Gitea + its API-compatible fork Forgejo (the mastodon/forks pattern); inline `topics` → `concepts` like github (no second call), no inline license so `tags` empty; README is README.md-first via the API raw route (the web `download_url` login-gates anonymous gitea.com clients; listing a big root times out) with a root-listing fallback for a non-`.md` README; `GITEA_TOKEN`/`FORGEJO_TOKEN` (→`Authorization: token`) lifts the limit; degrades to metadata-only | 0056 |
| gitea (issue / PR) | `sources/gitea.py` | keyless `GET /api/v1/repos/<o>/<r>/issues/<n>` + optional comments | the github thread template (ADR 0084) on the third host, applying github's rule *not* gitlab's because Gitea/Forgejo **unify issue/PR numbering** like github — one `/issues/<index>` endpoint serves both (a PR carries a `pull_request` object), so a single `#` marker suffices; identity `<host>/<owner>/<repo>#<n>` keeps the per-instance host (ADR 0056) and adds the thread marker the adapter dispatches on (the huggingface one-source-many-kinds shape, repo path byte-unchanged); the one divergence detection encodes is the **plural PR web path `/pulls/<n>`** (vs github's singular `/pull/<n>`); one GET then `…/issues/<n>/comments?per_page=100` only when present — and **the comments endpoint is keyless** (unlike gitlab's 401-gated `/notes`), so the common case reaches the whole conversation with no token, degrading to body-only on failure; Markdown body + `#### Comment by <user>` bylined comments → `extracted_text` (no HTML strip), labels → `concepts`, kind + state (`issue`/`pull request`, `open`/`closed`/`merged` via `pull_request.merged_at`, the vocab matching github's directly) → `tags`, a `<host>/<owner>/<repo>` link → the **thread↔repo edge** + body-URL scan; title leads host-free `owner/repo#<n>:` (matching the repo's `full_name` title); author/byline read `login` else `username`; **no category default** — `gitea → project` applies only to repos (a `#`-bearing id is unclassified, the github one-marker carve-out); degrades to metadata-only | 0086 |
| bitbucket | `sources/bitbucket.py` | keyless `GET /2.0/repositories/<ws>/<repo>` + optional README via the `/src/<branch>` route | the fourth code host; Bitbucket *Cloud* is a single service so it is host-scoped with a fixed API host and a flat `<workspace>/<repo>` identity like github (not host-in-id like gitea; Bitbucket Server/DC deferred), folded lowercase (slugs auto-lowercase, case-insensitive routing — the gitlab fold); **no topics so `concepts` empty by design**, `language` → the one `tag`; README via the `/src/<mainbranch>/<path>` route (no `/readme` endpoint, no `/raw/` route) — README.md-first then a root-listing fallback for a non-`.md` README; `BITBUCKET_TOKEN` (→`Authorization: Bearer`) lifts the limit; degrades to metadata-only | 0057 |
| bitbucket (issue / PR) | `sources/bitbucket.py` | keyless `GET /2.0/repositories/<ws>/<repo>/{issues,pullrequests}/<n>` + optional comments | the **gitlab** thread template (ADR 0085) on the fourth and last web-discoverable host, completing the family; Bitbucket splits issue/PR numbering on separate endpoints like gitlab (not github/gitea's unified one), so identity uses gitlab's cross-reference markers — `workspace/repo#<n>` issue, `workspace/repo!<n>` PR (Bitbucket has no native PR marker, so reusing gitlab's keeps cross-host identity uniform) — and the marker dispatches on both kind and endpoint; the web PR path is **hyphenated** `/pull-requests/<n>` while the API is `/pullrequests/<n>`; one GET then `/comments?pagelen=100` gated on `comment_count` (fetched when the field is absent — the issue payload), degrading to body-only; PR body = `description`, issue body = `content.raw` + `#### Comment by <display_name>` bylined comments → `extracted_text` with **deleted and inline diff-line comments skipped** (the deferred review slice); kind + state → `tags` (state normalized to github's vocab: `OPEN`→`open`, `MERGED`→`merged`, `DECLINED`/`SUPERSEDED`→`closed`, issue states binned open/closed), **`concepts` empty by design** (no labels feature); `bitbucket.org/<ws>/<repo>` link → thread↔repo edge + body-URL scan; title host-free `workspace/repo#<n>:`; author from PR `author`/issue `reporter`; **no category default** — a thread is heterogeneous (the gitlab two-marker carve-out, `#`/`!` id unclassified); the native **issue tracker is deprecated by Atlassian** (410 on most repos) so PRs are the live-verified common case, issues best-effort; degrades to metadata-only | 0087 |
| arxiv | `sources/arxiv.py` | Atom export API + `pypdf` full text | abstract → `summary`, taxonomy codes → `tags`, their display names → `concepts`, PDF → `media`, published `arxiv:doi` → `doi.org` `link` (preprint↔published edge, ADR 0038); degrades to abstract-only | 0008, 0010, 0012, 0038 |
| biorxiv, medrxiv | `sources/biorxiv.py` | keyless `api.biorxiv.org/details/<server>/<doi>`, stdlib JSON, one request | arXiv's biology/medicine preprint siblings; **two distinct sources, one shared adapter** (it reads `item.source` to pick the `<server>`) — *not* one source with a server qualifier (the huggingface unify is rejected: a medRxiv paper does not live on bioRxiv, so labeling it `biorxiv` would be dishonest — ADR 0045's honesty value), the inverse of the doi/threadiverse one-source-many-adapters shape; identity `10.1101/<accession>`, every `vN`/`.full`/`.full.pdf`/early-access view deduping to it (arXiv `abs`/`pdf` dedupe); the **highest version** in the ascending `collection` is the current preprint; abstract → `summary` with **no `extracted_text`** and **no PDF media** (the `.full.pdf` 403s anonymous clients — the deliberate divergence from arXiv whose PDF serves freely, ADR 0010); subject `category` → the one `concept` (sentence-cased so `HIV/AIDS` survives), study `type` (space-bearing only, so medRxiv's `PUBLISHAHEADOFPRINT` sentinel drops) + `server` venue + recognized CC `license` → `tags`; `published` journal DOI → `doi.org` `link` (preprint↔published edge, arXiv's `arxiv:doi` analog ADR 0038, PubMed's biomedical sibling ADR 0065), unpublished preprints edgeless; `biorxiv`/`medrxiv → paper`; degrades to metadata-only | 0068 |
| pdf | `sources/pdf.py` | direct download + `pypdf` text and document metadata | `/Title`-or-filename → `title`, `/Subject` → `summary`, the document → `media`; non-PDF payload fails, textless PDF degrades to metadata-only | 0013 |
| hackernews | `sources/hackernews.py` | keyless Firebase API, one request, stdlib only | text posts → body + lead `summary`; link posts → "N points, M comments" + bare article URL in `links`; degrades to metadata-only; `kids` kept in `raw_text` | 0031 |
| stackexchange | `sources/stackexchange.py` | keyless Stack Exchange API, stdlib only; optional second GET for answers | one adapter for the whole network (site in `source_id`); question + accepted-first top answers → `extracted_text`; tags → `concepts`; degrades to question-only | 0033 |
| pypi | `sources/pypi.py` | keyless PyPI JSON API, stdlib only | latest-release metadata; description (README) → searchable text; keywords → `concepts`, classifiers → `tags`, project URLs → `links` (package↔repo edge); `pypi → tool`; degrades to metadata-only | 0034 |
| npm | `sources/npm.py` | keyless registry JSON, stdlib only; capped `dist.tarball` GET when the packument has no README | latest-release metadata; README from packument or, when empty (common for high-traffic packages), its tarball → searchable text; keywords → `concepts` (no classifier analog, `tags` empty); homepage + normalized repository → `links` (package↔repo edge); `npm → tool`; degrades to metadata-only | 0035 |
| crates | `sources/crates.py` | keyless crates.io JSON API + capped `.crate` tarball GET for the README | displayed-version metadata; raw README from the `.crate` tarball → searchable text; keywords → `concepts`, curated category taxonomy → `tags`; homepage/docs/normalized repository → `links` (crate↔repo edge); `crates → tool`; degrades to metadata-only | 0036 |
| crossref (`doi.org`, Crossref agency) | `sources/crossref.py` via `sources/doi.py` dispatch | keyless Crossref DOI metadata API, stdlib only | registered work metadata for a `doi.org` DOI (folded lowercase identity); JATS abstract → plain `summary` (no full text, so no `extracted_text`); `subject` → `concepts`, `type`+venue → `tags`; publisher landing page → `links` (`reference` DOIs dropped); `crossref → paper` like arXiv; degrades to metadata-only | 0037 |
| crossref (`doi.org`, DataCite agency) | `sources/datacite.py` via `sources/doi.py` dispatch | keyless DataCite DOI metadata API, stdlib only | fetch-time fallback when Crossref 404s a DOI (datasets/software/etc.); JSON:API `attributes` → titles+subtitle, creators "Given Family", `Abstract` description → `summary` (no full text), `subjects` → `concepts`, DataCite date precedence, `resourceTypeGeneral`+`resourceType`+publisher → `tags`, landing + container-DOI `links` (cross-source edge); `resourceTypeGeneral` → `provenance.resource_type` drives classification (`Dataset → dataset`, `Software`/`Model` → `tool`, text types → `paper`, `Image`/`Sound` → `media`); source stays `crossref`, `provenance.adapter="datacite"` is honest; degrades to metadata-only | 0045 |
| crossref (`doi.org`, any other agency) | `sources/csl.py` via `sources/doi.py` dispatch | keyless DOI content negotiation (`doi.org/<doi>` with `Accept: application/vnd.citationstyles.csl+json`), stdlib only | the **third dispatch tier**, reached when Crossref *and* DataCite 404 a DOI — one adapter for every remaining registration agency (JaLC, mEDRA, KISTI, OP, …), since the resolver proxies CSL-JSON to whichever agency holds the DOI; CSL-JSON is Crossref's REST JSON's sibling (`title`/`container-title` plain strings, authors carry `literal` for orgs) so the Crossref mapping transfers: JATS `abstract` → plain `summary`, `subject` → `concepts`, `type`+venue → `tags`, `URL` landing page → the one `link`; `type` → `provenance.resource_type` defaults classification to `paper` (the post-DataCite agencies are scholarly) but honors a `dataset`/`software`/`figure` type; source stays `crossref`, `provenance.adapter="content-negotiation"` is honest; a parsed-but-non-CSL body raises rather than minting a junk scroll; degrades to metadata-only | 0081 |
| pubmed | `sources/pubmed.py` | keyless NCBI E-utilities efetch API, stdlib ElementTree, one request | the biomedical literature, the arXiv/Crossref paper sibling (PMID identity); MeSH `DescriptorName`s → `concepts` (the curated controlled vocabulary, github-topics/arXiv-taxonomy role; qualifiers dropped), author `Keyword`s the fallback for not-yet-MEDLINE-indexed records; structured abstract → `summary` (no full text, so no `extracted_text`, the Crossref shape); publication types + journal venue → `tags`; date precedence electronic `ArticleDate` → journal `PubDate` (month-name/year-only/`MedlineDate` parsed) → history; article DOI → `doi.org` `link` (PubMed↔Crossref paper edge, ADR 0038's biomedical analog); `pubmed → paper`; degrades to metadata-only | 0065 |
| rfc | `sources/rfc.py` | keyless RFC Editor JSON view (`rfc-editor.org/rfc/rfc<N>.json`) + the `.txt` spec body, stdlib only | IETF technical standards, a content type with no prior home; host-restricted shape detection (RFC Editor + `datatracker`/`tools`/`ietf`, only `rfc<digits>` claimed, drafts/WG/org → `web`); integer-number identity, leading zeros stripped; `keywords` → `concepts` (github-topics/MeSH role; whitespace placeholder dropped), maturity `status` title-cased → the one `tag`; abstract → `summary`, the `.txt` spec body fetched + de-paginated → `extracted_text` (the arXiv abstract+PDF split, ADR 0010/0067; classic form-feed/`[Page N]`/running-header pagination stripped, modern unpaginated format passes through; degrades to abstract-only on `.txt` failure); DOI `10.17487/RFC<N>` → `doi.org` `link` (RFC↔Crossref edge), `obsoletes`/`updates` → `rfc-editor.org/rfc/rfc<M>` `link`s (RFC↔RFC lineage; inverse relations not re-emitted); number leads the title; `Month Year` dates padded to first-of-month; `rfc → reference`; degrades to metadata-only | 0066, 0067 |
| packagist | `sources/packagist.py` | keyless Packagist JSON API, stdlib only | Composer package metadata for a `vendor/name` (folded lowercase identity); highest *stable* release picked by ranking the numeric `version_normalized` (no `default_version` pointer, no comparator dep); description → `summary` (no README in the API, so no `extracted_text`); keywords → `concepts`, `type`+SPDX licenses → `tags`; repository/homepage/git source → `links` (package↔repo edge); `packagist → tool`; honestly metadata-only | 0039 |
| rubygems | `sources/rubygems.py` | keyless RubyGems JSON API, stdlib only | gem metadata for a `name` (verbatim, case-sensitive identity like npm); `gems/<name>.json` returns the latest version inline (no version selection); `info` → `summary` (no README in the API, so no `extracted_text`); no keywords so `concepts` empty *by design*, SPDX licenses → `tags`; homepage/source/docs URIs → `links` (gem↔repo edge survives a tagged-tree source URI); `rubygems → tool`; honestly metadata-only | 0040 |
| huggingface | `sources/huggingface.py` | keyless Hub JSON API, stdlib only; second GET for the card README | one adapter for models + datasets + Spaces (kind in `source_id`, a `_PATH_SEGMENT` map routes the endpoint); card README (frontmatter stripped) → `extracted_text`, its lead paragraph → `summary` (dataset `description` the fallback); concepts from structured fields (`pipeline_tag`/`task_categories` + `cardData.tags`), *not* the flat tag soup; framework facet + license → `tags` (`library_name` for a model, `sdk` for a Space); `arxiv:`→arxiv.org `link` (model↔paper edge), `dataset:`/`base_model:`→Hub `link`, a Space's `cardData.models`/`datasets`→Hub `link` (space↔model/dataset edge); `model`/`space → tool`, `dataset → dataset`; degrades to metadata-only | 0041, 0043 |
| lobsters | `sources/lobsters.py` | keyless `lobste.rs/s/<id>.json`, stdlib only, one request | story + tags + the *entire* comment thread in one GET (HN defers comments, SE spends a second GET); `description_plain`/`comment_plain` already plain, no HTML grammar; body + bylined comments (deleted/moderated skipped, all kept) → searchable `extracted_text`; link submission's article → bare `links` (HN pattern), `summary` = body lead else "N points, M comments"; tags → `concepts`; **no category default — unclassified like HN**; degrades to metadata-only | 0046 |
| go | `sources/go.py` | keyless `proxy.golang.org`, stdlib only; second GET for the go.mod | module-path identity (case-sensitive, verbatim; module = path before `@`); `/@latest` → version+time, `/@v/<v>.mod` → the go.mod manifest as searchable `extracted_text`; the sparsest adapter — no description (`summary` None), no keywords (`concepts=()`), no license/classifier facet (`tags=()`); repo `link` from `Origin.URL` else derived from the module path for known VCS hosts (package↔repo edge); request case-encoded (`X`→`!x`); `go → tool`; degrades to metadata-only | 0042 |
| pub | `sources/pub.py` | keyless `pub.dev/api/packages/<name>`, stdlib only, one request | the Dart/Flutter package registry, seventh of the family; `latest.pubspec` is the manifest (no version selection); identity folded lowercase — the *forgiving* fold (PyPI/crates/Packagist rule, since pub's canonical name is always lowercase, so a case-sensitive-API miss can only be *rescued*, never caused); `pubspec.topics` → `concepts` (the github-topics role — pub *feeds* the concept graph, unlike keyword-less RubyGems/Go), description → `summary` (no README in the JSON, so no `extracted_text`); a Flutter-SDK dependency (`environment.flutter`/a `flutter` dep) → the **derived** `flutter` tag (a pure-Dart package left untagged, Go's honest-empty posture); repository+homepage → `links`, the monorepo-tree repository URL resolving to the repo via `detect_source` (package↔repo edge); `latest.published` → `published_at`; `pub → tool`; honestly metadata-only | 0088 |
| hex | `sources/hex.py` | keyless `hex.pm/api/packages/<name>`, stdlib only, one request | the Elixir/Erlang package registry, eighth of the family and pub.dev's twin in field layout (a `meta` object of description/licenses/links); identity folded lowercase (the forgiving PyPI/crates/Packagist/pub rule — `packages/Ecto` 404s but the canonical name is always lowercase); `meta.description` → `summary` (no README in the JSON, so no `extracted_text`); **`concepts` empty *by design*** (Hex has no keywords — RubyGems'/Go's structural gap, the axis on which Hex *diverges* from its layout-twin pub.dev, whose topics feed the concept graph); SPDX `meta.licenses` → `tags`; the `meta.links` `{label: url}` **map's values** → `links` (a new shape — RubyGems/pub read named scalar fields; the `GitHub` entry wires the package↔repo edge); `published_at` from the release matching `latest_stable_version` (robust to a pre-release topping the list); author left `None` (no clean byline — `owners` carries emails); `hex → tool`; honestly metadata-only | 0089 |
| nuget | `sources/nuget.py` | keyless `api.nuget.org` flat container — `GET /v3-flatcontainer/<id>/index.json` then the `<version>/<id>.nuspec`, stdlib JSON + ElementTree | the .NET package registry, ninth of the family and the one top-tier ecosystem it hadn't reached; **two plain requests** the Go "version index + manifest" shape (ADR 0042) rather than the registration API, which is **gzip even on a plain GET** (the UTF-8 `get_json` can't read it) and paginates — the flat container is plain JSON + a plain XML nuspec, no gzip/pagination; latest **stable** version picked by Packagist's numeric ranking (the top version is often a pre-release); the nuspec parsed **namespace-agnostically** (the namespace URI varies by schema generation, so children matched by *local* name); identity folded lowercase (the forgiving fold — NuGet ids are case-insensitive and the flat-container path requires lowercase), display casing read back from the nuspec `<id>`; `<tags>` → `concepts` (the github-topics/PyPI-keywords role — the .NET ecosystem joins the KB concept graph), `<description>` → `summary` (no README in the nuspec — it ships in the `.nupkg` — so no `extracted_text`, metadata-only), SPDX `<license type="expression">` → the one `tag`, `<projectUrl>`+`<repository url>` → `links` (package↔repo edge); `published_at` left as the seed (the nuspec carries no date — Go's honest gap); the nuspec **is** the metadata so its failure is a FetchError (no metadata-only fallback, unlike Go's optional go.mod); `nuget → tool` | 0090 |
| hackage | `sources/hackage.py` | keyless `GET hackage.haskell.org/package/<name>/<name>.cabal`, stdlib only, one request | the Haskell package registry, tenth of the family; the endpoint serves the latest version's **cabal** manifest (no version selection — RubyGems' inline-latest), the family's first indentation-structured `field: value` manifest rather than JSON, so the one new thing is a small **cabal parser** (top-level fields at column 0 with indented continuations, section headers — `library`/`source-repository head` — whose body is skipped except the repo `location`, `--` comments dropped); identity is the name **verbatim** (case-sensitive like npm/RubyGems — `QuickCheck`, the singular `/package/<name>` claimed not the plural `/packages/` list, a trailing dotted-numeric version stripped); `category` → `concepts` (comma-split, the github-topics role — Haskell joins the concept graph), and **richer than the metadata-only registries**: the cabal's `description` → `extracted_text` (the prose body, the `.` line a blank-line marker) with `synopsis` → `summary` — the first registry whose own manifest carries prose; `license` → the one `tag` verbatim (SPDX on modern cabals, a legacy id like `BSD2` on older ones), `author` (`<email>` stripped) → byline, `homepage` + the repository `location` → `links` (`.git` folded, package↔repo edge); `published_at` left as the seed (the cabal has no date — Go/NuGet's honest gap); a cabal with no `name` → FetchError; `hackage → tool` | 0091 |
| maven | `sources/maven.py` | keyless `repo1.maven.org/maven2` flat repository — `GET /<group-path>/<artifact>/maven-metadata.xml` then the `<version>/<artifact>-<version>.pom`, stdlib ElementTree | the JVM package registry (Java/Kotlin/Scala/Clojure/Android), eleventh of the family and the **largest** ecosystem it hadn't reached; **two plain requests** the Go/NuGet "version index + manifest" shape (ADR 0042/0090) against the flat repository (a static file tree) rather than the rate-limited Solr search API; identity is the Maven **coordinate `groupId:artifactId` verbatim** (case-sensitive like a literal file tree, npm/RubyGems' rule), the reverse-DNS group **path-encoded** (`com.google.guava`→`com/google/guava`, Go's request-encoding cousin); detection has **two grammars** — the unambiguous `/artifact/<g>/<a>` UI pages (central.sonatype.com, search.maven.org, mvnrepository.com) and the raw `/maven2/<group-path>/<artifact>` file tree (group reassembled around the version directory); latest **release** preferred from the index `<release>` (it gets stable build classifiers like `-jre`/`-android` right where a hyphen heuristic fails), a SNAPSHOT-excluded numeric ranking the fallback; the POM parsed **namespace-agnostically** (local-name match, the nuspec lesson); **diverges from NuGet on two axes** — `concepts=()` by design (a POM has no keyword facet — the RubyGems/Go/Hex posture, the JVM a metadata-and-edges source not a concept source) and `published_at` read from the **version index's `<lastUpdated>`** (the only adapter whose date lives outside its own manifest); `<name>` else coordinate → title, `<organization><name>` else first developer → author, `<description>` → `summary` (the README ships in the jar, so no `extracted_text` — metadata-only), `<licenses><license><name>` → `tags` verbatim (freeform names, the Hackage rule), `<url>`+the `<scm>` repository → `links` (ssh `git@host:path`/`git://` normalized, `.git` folded, package↔repo edge); the POM **is** the metadata so its failure is a FetchError (no metadata-only fallback, unlike Go's optional go.mod); `maven → tool` | 0092 |
| bluesky | `sources/bluesky.py` | keyless AppView (`public.api.bsky.app`), stdlib only; `resolveHandle` GET for a handle URL, then one `getPostThread` | the open social-post source X couldn't be (IDEAS.md §6 deferred X; its API is now paywalled); a handle URL resolves to the DID the AT-URI needs (a `did:` URL skips it), then one call returns the post + its reply tree; post text + bylined replies (deleted/blocked/empty skipped) → `extracted_text`, image alt text the body of a textless post; external card / quoted post / inline `#link` facets → `links` (post↔post + cross-source edges), images → `photo` media, `#hashtag` facets → `concepts`; synthesized title, `summary` = lead else alt else card title else engagement status; **no category default — unclassified like HN/Lobsters**; degrades to metadata-only | 0048 |
| mastodon (incl. GoToSocial, Pleroma/Akkoma) | `sources/mastodon.py` | keyless Mastodon REST API, stdlib only; `GET /api/v1/statuses/<id>` then optional `.../context` | the Fediverse Mastodon-API family on one adapter, matched by URL *shape* not host (no shared host to key on); HTML `content` → text via stdlib `HTMLParser` (no trafilatura), flat `descendants` → bylined replies; card + body links → `links` (mentions/hashtags excluded), images → `photo`/videos → `thumbnail` media, `tags[].name` → `concepts`; `spoiler_text` content warning leads the body, a boost unwraps; synthesized title, `summary` = lead else alt else card title else engagement status; **no category default**; degrades to metadata-only | 0049, 0050 |
| misskey (incl. Sharkey, Firefish, Foundkey) | `sources/misskey.py` | keyless Misskey API, stdlib only; `POST /api/notes/show` (JSON body) then optional `notes/children` | the Fediverse Misskey-API family — *not* Mastodon-compatible, so its own source/adapter; the first POST-bodied adapter (new `http.post_json`); MFM `text` is already plain (no HTML parser, Lobsters' economy), links scanned from the text + a quote-renote's note → `links` (post↔post + cross-source edges), `files` → `photo`/video-`thumbnail` media (`comment` alt searchable), bare-string `tags` → `concepts`, `cw` content warning leads the body, a pure renote unwraps; synthesized title, `summary` = lead else alt else engagement status; **no category default**; degrades to metadata-only | 0051 |
| lemmy (Lemmy backend) | `sources/lemmy.py` via `sources/threadiverse.py` dispatch | keyless Lemmy API v3, stdlib only; `GET /api/v3/post` then optional `/comment/list` | the federated link aggregator (HN/Lobsters' cousin) — *not* Mastodon/Misskey-compatible, so its own source/adapter, the third Fediverse split by client API; plain GET so `http.get_json` serves it; a *real* `name` title (an aggregator entry, not synthesized) and `ap_id` canonical; flat comments sorted into thread pre-order by integer `path`, bylined like Lobsters (deleted/removed skipped); link post `url` → article `link`, text post `body` the content, image post `url` → `photo` media (told by `url_content_type`), `thumbnail_url` → preview; body URLs + `cross_posts` `ap_id` → `links` (cross-source + post↔post edges); community → one `concept`; `summary` = body lead else "N points, M comments"; **no category default — unclassified like HN/Lobsters/social**; degrades to post-only | 0052 |
| lemmy (PieFed backend) | `sources/piefed.py` via `sources/threadiverse.py` dispatch | keyless PieFed `/api/alpha`, stdlib only; `GET /post` then optional `/comment/list` | PieFed shares Lemmy's exact `/post/<digits>` URL, so it can't be its own *detected* source; but its API is its own (`/api/alpha`, `post.title`/`creator.user_name`/`comment.body`/`post_type` not Lemmy's `name`/`name`/`content`/`url_content_type`), so it can't ride Lemmy's *adapter* either — its own adapter on Lemmy's source, resolved at fetch time by the `threadiverse` dispatcher (Lemmy first, PieFed fallback — the `doi.py` pattern); identity stays `lemmy:<host>/<id>`, `provenance.adapter="piefed"` honest (the DataCite-vs-Crossref split); otherwise mirrors Lemmy — image by `post_type=="Image"`, cross-posts (no `ap_id`) → same-instance `/post/<id>` links, `summary` = body lead else "PieFed discussion: N points, M comments"; `Poll`/`Event` payloads kept in `raw_text`; degrades to post-only | 0053 |
| discourse | `sources/discourse.py` | keyless Discourse `.json` view, stdlib only; `GET /t/<id>.json` — topic **and** its first page of posts in *one* request | the centralized *forum* sibling of the aggregators, and the **first non-Fediverse host-less source** (matched by `/t/<slug>/<id>` shape on any unclaimed host, slug dropped from identity, the weak `t` literal making the all-digits id carry the weight); a *real* `title` (a forum thread, not a synthesized post), opening post → body, later posts → bylined `### Replies` (mod-action/whisper/deleted skipped); HTML `cooked` → text via stdlib `HTMLParser` (no trafilatura); `tags` → `concepts`, outbound `details.links` (internal/reflection filtered) → `links` (cross-source edges), `image_url` → `thumbnail` media; `summary` = OP lead else "N replies, M likes"; **no category default — unclassified like HN/Lobsters/Lemmy/social**; validates `post_stream` so a misdetect raises rather than mis-scrolls; long threads first-page-only (full `stream` in `raw_text`) | 0054 |
| devto | `sources/devto.py` | keyless `dev.to/api/articles/<user>/<slug>`, stdlib only, one request | the developer-blogging platform a `web` scrape left a concept-less island; one GET returns the whole article so `tags` → `concepts` joins it to the KB graph (github-topics pattern), `tags` field empty (no license/classifier facet); identity `<user>/<slug>` folded lowercase (Forem mints lowercase, case-sensitive API only resolves it — the gitlab/bitbucket fold); the URL handle is the author *or organization*, so `author` reads the byline `user.name` (the person); `body_markdown` already Markdown (no HTML grammar, Lobsters' economy) → `extracted_text`, `description` → `summary` (→ lead → engagement → None), cross-post `canonical_url` → `links` (cross-source edge) while the scroll's canonical stays the dev.to permalink, `cover_image`/`social_image` → `thumbnail` media; **no category default — unclassified like HN/Lobsters/Bluesky**; self-hosted Forem deferred; degrades to metadata-only | 0061 |
| openlibrary | `sources/openlibrary.py` | keyless Open Library `.json` view, stdlib only; bounded GETs for author names + an edition's work | **books**, a content type with no prior home (the dev.to/RFC island, ADR 0061/0066); the Internet Archive's open catalog, books' Crossref, modeling them in the same **FRBR** sense `scrolls works` uses (ADR 0069) — a *work* (`/works/OL…W`), an *edition* (`/books/OL…M`), an ISBN (`/isbn/<isbn>` naming an edition); all three claimed, the kind in the id (the OLID's own `W`/`M` letter encodes work-vs-edition, only ISBN needs an `isbn:` prefix — huggingface kind-in-id without the prefix), OLID uppercased to canonical (route-insensitive, crates/gitlab fold), the adapter routing on the id (`/isbn` 302-redirects to the edition, urllib follows); curated `subjects` → `concepts` (github-topics/MeSH role — the whole point), admin flags + LC/Dewey call numbers filtered, deduped + capped; subjects live on the work so an edition follows its `works` ref for them (the two-request shape); `description` (string or `{value}`) → `summary`, **no `extracted_text`** (catalog metadata not the body — Crossref/PubMed shape), `tags` empty by design (no controlled facet — go/rubygems posture); authors named by key, resolved with bounded GETs (`et al.` truncation, failures skipped); edition → `/works/<OLID>` `link` (edition↔work edge), work external `links` → edges, first present `covers` id (`-1` skipped) → `thumbnail` media; free-form dates padded (RFC rule); **no category default** — fiction + non-fiction, so forcing `reference` would be dishonest (the medRxiv honesty); degrades to metadata-only | 0073 |
| zenodo | `sources/zenodo.py` | keyless InvenioRDM REST API (`zenodo.org/api/records/<id>`), stdlib only, one request | **research datasets and software**, a content type left a `web` scrape (the dev.to/Open Library island, ADR 0061/0073); CERN's open-science repository, the citable-DOI snapshot of every released GitHub repo; the record JSON has top-level fields + descriptive `metadata` (**no JSON:API envelope** unlike DataCite); identity is the version-specific recid the URL carries (after a `record`/`records` segment, deeper links dedupe — the Discourse slug-drop), the `conceptdoi` naming the all-versions concept (the Open Library edition rule, not a fetch-time rewrite); Zenodo's DOIs are **DataCite**-registered, so the record **DOI → `doi.org` link** ties the landing page to its DataCite DOI scroll and clusters them as one work in `scrolls works` (ADR 0045/0069) — the landing-page form complementing the `doi.org` form already covered (ADR 0045); HTML `description` → plain `summary`, **no `extracted_text`** (the files are the body — the Crossref/DataCite metadata-only shape, kept consistent with the DOI twin); `resource_type.type` → `provenance.resource_type` → category (`dataset → dataset`, `software → tool`, `publication → paper`, `image`/`video → media`, ambiguous types unclassified — the DataCite fetch-time-fact mechanism, ADR 0045); `keywords` + `subjects` → `concepts`, `type`+`subtype`+`license.id` → `tags`; `related_identifiers` → links by scheme (`doi`/`arxiv`/`url`, the preprint edge ADR 0038); partial dates padded (RFC rule); degrades to metadata-only | 0083 |

X items arrive through `scrolls import fieldtheory` rather than a fetch
adapter (ADR 0009): the Field Theory JSONL cache is the raw-record spine
(each line preserved verbatim in `raw_text`), and classified pages join
`category`/`domain` by tweet id.

Shared HTTP transport lives in `src/scrolls/sources/http.py` (stdlib
urllib, descriptive User-Agent). Adapters take the fetcher as an
injectable parameter, which is why no test touches the network.

### Adding a new adapter

The pattern every existing adapter followed:

1. Map the URL shape in `sources/detect.py` and cover it in
   `tests/test_detect.py`. Decide what the stable `source_id` is.
2. Write `sources/<name>.py` exposing
   `fetch_item(item, fetcher=...) -> ScrollItem`. Fill what the platform
   offers; raise `FetchError` for anything else. Degrade gracefully when
   an enrichment (transcript, README, PDF text) fails — a metadata-only
   scroll beats no scroll.
3. Register it in `FETCH_ADAPTERS` (`sources/__init__.py`).
4. Test against recorded fixture payloads with an injected fetcher
   (`tests/test_<name>.py`) — never the live API.
5. If the platform implies a category, add a platform rule to
   `classify.py` (e.g. arxiv → paper, github → project; ADR 0004).
6. Note the adapter in `README.md` and record non-obvious choices in an
   ADR (`docs/adr/`).

## Downstream engines

Each engine is deterministic today, with an explicit slot where an LLM
version can join later — deterministic-first is a deliberate, recurring
choice (ADRs 0004, 0005).

- **Classification** (`classify.py`, ADR 0004) — rules engine
  (`rules-v1`), layer one of IDEAS.md §8's "rules first → optional LLM
  second → user overrides always win". Precedence: curated platforms,
  then title patterns, then URL shape, then youtube → media. Unmatched
  items honestly stay unclassified. A curated source is usually a flat
  source→category map, but seven sources read a per-item fact instead:
  huggingface's repo kind (`tool`/`dataset`), crossref/zenodo's resource
  type (ADR 0045/0083), and **the four code hosts' content kind** — a repo is a
  `project`, but a github issue/PR (`owner/repo#<n>`), gitlab issue/MR
  (`group/project#<n>`/`!<n>`), gitea issue/PR (`<host>/<owner>/<repo>#<n>`), or
  bitbucket issue/PR (`workspace/repo#<n>`/`!<n>`) is a heterogeneous discussion
  thread left unclassified like a Hacker News post (ADR 0084/0085/0086/0087).
  Which of the four tiers fired is recorded as `classified_basis`, paired with
  a `classified_ruleset` fingerprint of the rule tables, so a stored category
  names the exact ruleset that produced it (roadmap H20). Batch runs never
  overwrite an existing category; `classify <id>` explicitly reclassifies, and
  `classify --stale` re-runs the engine over exactly the items doctor flags as
  classified under a superseded ruleset (`is_stale_classification`, roadmap H27)
  (`tests/test_classify.py`).
- **LLM classification** (`classify_llm.py`, ADR 0015) — layer two
  (`llm-v1`), run explicitly via `classify --engine llm`: one Anthropic
  Messages call per item with structured outputs pinning `category` to
  the full IDEAS.md §8 vocabulary, plus `domain` and model `concepts`
  merged after the platform-curated ones. `--batch` (ADR 0022) sends
  the same requests as one Message Batches submission at half the
  per-token price, polled until it ends on the shared transport
  (`llm.anthropic_complete_batch`, now also the concept engine's batch
  path — ADR 0032); both per-item and batch share one validation path.
  The completers are injectable,
  so tests stay offline (`tests/test_classify_llm.py`); the SDK is
  imported lazily, and missing credentials abort the batch
  (`LLMAuthError`) while per-item API failures don't. `config.toml`'s
  `[classify]` section (`config.py`, ADR 0016) makes the engine and
  model sticky per library; the `--engine` flag and `$SCROLLS_LLM_MODEL`
  always win (`tests/test_config.py`).
- **User overrides** (`overrides.py`, ADR 0018) — `scrolls set` is
  IDEAS.md §8's third layer: it writes exactly the fields the engines
  write (`category`, `domain`, `tags`, `concepts`), free-form, with
  empty values clearing a field back to the batch-classifiable pool. A
  set category sticks because batch runs never overwrite one. Setting
  `category` also drops the engine's category-derivation stamps
  (`classified_by` / `classified_basis` / `classified_ruleset` /
  `classified_model`), keeping the contract `classification_view` documents
  ("a user override carries no engine stamp") true — so a hand-set category
  shows no method, and stays out of doctor's stale count and `classify --stale`
  (`tests/test_overrides.py`).
- **Search** (`search.py`) — FTS5 BM25 with title weighted over summary
  over body. Query tokens are quoted and AND-ed, so arbitrary agent
  input never hits FTS5 syntax errors. Optional `source`/`category`/`stage`
  facets scope the ranked match — they AND with the FTS match and leave
  the BM25 order untouched, mirroring `scrolls list`'s filters (`""`
  category selects unclassified), so a search can ask "papers about X" over
  30+ heterogeneous sources, not just "anything mentioning X" (ADR 0058,
  `tests/test_search.py`). Two further facets, `tag` and `concept`, scope
  by *membership* in the JSON list columns rather than single-column
  equality: a `json_each` `EXISTS` subquery with `tag` lowered and
  `concept` slugified — the `scrolls related` comparisons, via two SQL
  functions registered on the connection (`items.register_facet_functions`)
  — so the filtering stays in SQL and `search`'s `LIMIT` is still correct
  (ADR 0059). The membership-clause builder (`items.tag_concept_filters`)
  and the full scalar+membership filter builder (`items.item_filters`,
  promoted from `search` so `search`, `list`, and `facets` share one)
  keep the facets identical across the surfaces.
- **Facets** (`facets.py`) — the browse half of the search/browse pair:
  `scrolls facets [field]` enumerates the *filterable vocabulary* — the
  `sources`, `categories`, `tags`, and `concepts` an agent can pass to the
  search/list facets — with per-value item counts, so "what can I filter
  by?" has a live JSON answer instead of only the static KB facet pages
  (ADR 0080, `tests/test_facets.py`). Sources and categories are scalar
  `GROUP BY` counts (the unclassified pool surfaces as `""`,
  round-trippable to `--category ""`); tags and concepts reuse the KB's
  `group_tags`/`group_concepts` so the enumerated values group exactly as
  the `--tag`/`--concept` filters key on them (case-fold, slug), each
  counted by distinct item. The same optional facets scope the counts
  (`scrolls facets concepts --source arxiv`), and the dimension reuses
  `items.item_filters`.
- **Related items** (`related.py`, IDEAS.md §10) — explainable scoring,
  no LLM: a *same-work* sibling first (a shared DOI binds a preprint to its
  published article — the `works` lens, ADR 0069/0096 — outranking a one-way
  link because identity beats citation, and catching the hub-absent case the
  link graph cannot: two representations both naming `doi.org/D` with no
  Crossref item present share no edge yet are one work), then link
  connections in either direction (resolved through source
  detection, so `arxiv.org/pdf/X` finds item `arxiv:X`, an arXiv
  preprint's published `doi.org` link finds its `crossref:<doi>` paper —
  ADR 0038 — and a Hugging Face model's `arxiv:` tag finds the
  `arxiv:<id>` paper it introduced — ADR 0041 — while a Space finds the
  model it serves and the dataset it draws on — ADR 0043, a DataCite
  dataset finds the Crossref paper it is part of through its container DOI
  — ADR 0045, and a PubMed record's article `doi.org` link finds its
  `crossref:<doi>` paper — ADR 0065, the biomedical analog of the
  arXiv preprint↔published edge — while an RFC's DOI link finds its
  `crossref:<doi>` paper and its `obsoletes`/`updates` links find the RFCs it
  supersedes — ADR 0066, the standards-lineage analog), shared concepts
  (merged by slug), shared tags, same category/domain as weak
  corroboration. A genuine same-work pair whose hub is present scores both
  the same-work and the link edge — complementary facts, not double counting.
  Every hit carries its `reasons`, its custody `fidelity` tier, and — from one
  `latest_events` read per call — its custody `drift` posture (roadmap H56), so
  a neighbour an agent follows reports both how much of it the library holds and
  whether its source has drifted (`tests/test_related.py`).
- **Link graph** (`graph.py`, ADR 0044) — `scrolls graph` resolves *every*
  item's links into directed edges across the whole library, the
  whole-library complement to `related`'s per-item lens. The link-resolution
  primitives (`link_tokens`, `identity_tokens`) live here and `related.py`
  imports them, so both views agree on what a link resolves to. The build
  indexes every item's identity tokens once then probes with each link
  (linear, not the per-pair O(n²)); nodes are the connected items by
  default (`--all` adds isolates), `stats.items` the library total and
  `stats.clusters` the number of 2+-member components. Each node carries both
  custody axes — its `fidelity` tier (item-intrinsic, on the `Node`) and its
  `drift` posture (added in `to_payload` from the same `verdicts` the
  `stats.custody` tally reads, roadmap H56), so a node reads the same posture
  whether reached here or as a `related` hit, and a node's posture never
  disagrees with its contribution to the scope count. The
  same `{nodes, edges, stats}` payload backs the MCP `get_link_graph` tool
  (`tests/test_graph.py`). `connected_components` partitions the graph into
  clusters (edges undirected for the partition, the directed edges kept) and
  `graph_over` builds a graph over a *given* item set — both feed the KB's
  `library/graph.md` page (ADR 0062), the browsable form of the same
  structure.
- **Works** (`works.py`, ADR 0069) — `scrolls works` clusters the items
  that are *the same scholarly work* (an arXiv preprint, its published
  Crossref article, a PubMed record, a bioRxiv/medRxiv preprint) keyed by
  the **DOI that names the work**, so a library holding one work as several
  near-duplicate `paper` entries can consolidate them. A representation
  contributes a work's DOI when its `source_id` is itself a DOI
  (`crossref`, `biorxiv`/`medrxiv` — the `10.1101/<accession>` accession is
  one) or it carries a `doi.org` link (resolved through the same
  `detect_source` + `normalize_url` path the graph uses). Where the link
  graph connects two items only when one's link resolves to an item
  *already present*, `works` clusters by the shared DOI identity, so two
  representations bind even when the `crossref` item that would link them is
  absent — a cluster the graph structurally cannot form. Only 2+-member
  works are reported by default (`--min N`); the `{works, stats}` payload
  carries the same node shape and `stats.items` total as `graph`, and
  `works_over(items)` mirrors `graph_over(items)` so the KB works page
  (`library/works.md`, ADR 0070) reuses it over rendered items
  (`tests/test_works.py`). `scrolls works <ref>` is the per-item lens
  (ADR 0072) — `works_for_item(items, id)` filters `works_over` to the
  work(s) one item represents, with every saved sibling representation: the
  `scrolls related`↔`scrolls graph` symmetry applied to DOI clustering. It
  drops the 2+ floor (a solo work is the explicit "no sibling saved" answer)
  and raises for an absent item like `find_related`; the same lens backs
  `get_works(item=...)`.
- **KB compiler** (`kb.py`, ADR 0005) — rebuilds `library/index.md`,
  `library/graph.md`, `library/works.md`, plus per-source, per-category,
  per-concept, and per-tag pages each run so stale groups can't linger; other
  files under `library/` are left alone. **Regeneration is refresh-safe**
  (`generated.py`, ADR 0102): each page wraps its content in a sentinel
  `@generated`…`@end` fence, and a recompile replaces only the fenced region —
  so a hand annotation outside the fence survives, enacting custody-vision §2
  ("views are regenerable") without clobbering edits. A page whose group
  vanishes is removed unless it carries such an annotation, in which case it is
  kept with the generated region tombstoned (the annotation is never silently
  dropped). **Category pages
  consolidate works** (ADR 0071): a category page is the one group page where
  a scholarly work's near-duplicate representations co-occur (they share a
  category like `paper` but span sources), so each 2+-representation work
  among the page's members — `works_over(members)`, the same DOI clustering
  `scrolls works` and `works.md` use — collapses into one consolidated entry
  (a bold work heading with the `doi.org` link, its canonical
  representation's title, then each representation as a nested bullet linking
  to its scroll) instead of several flat bullets; source pages stay flat
  (single-source, no cross-source reps co-occur) and the count line still
  counts scrolls. Concept pages merge spellings by
  slug, and lead with a stored synthesized summary when the LLM concept
  engine has written one — the store (`concept_summaries`) lives on the
  compiler's side so a plain `scrolls kb` includes summaries with no model,
  key, or network. Tag pages (`group_tags`, ADR 0064) are the browsable
  complement to the `--tag` query facet (ADR 0059), grouping items by tag
  **case-insensitively** (the facet's rule, not concepts' slug merge — so
  `MIT`/`mit` are one page, `C++`/`C#` two despite a shared slug, the page
  filenames disambiguated by a numeric suffix); they carry a **Related
  Tags** co-occurrence section sharing the extracted `_co_occurring` core
  with Related Concepts, and a `tags` count joins the compile summary.
  `graph.md` is the browsable form of `scrolls graph`'s link structure
  (ADR 0062): the rendered scrolls that link to one another, grouped into
  clusters (`graph.connected_components(graph_over(rendered_items))`) and
  rendered as adjacency lists, with the index linking to it and the compile
  summary reporting a `clusters` count; built over rendered items only so
  every link on the page resolves to a scroll file (`tests/test_kb.py`).
  `works.md` is the parallel browsable form of `scrolls works`'s DOI
  clustering (ADR 0070): `works_over(rendered_items)` grouped under each work's
  DOI, every representation linking to its scroll, the index linking to it and
  the compile summary reporting a `works` count — the rendered-only scope
  meaning the page's work count can fall below `scrolls works`'s whole-library
  count, the same divergence `graph.md` has from `scrolls graph`.
  Each concept page also ends with a **Related Concepts** section
  (`related_concepts`, ADR 0063) — the concepts that co-occur on its member
  scrolls, ranked by shared-scroll count — the deterministic concept-graph
  complement to `graph.md`, kept on the concept pages rather than as
  `scrolls graph` edges so concept cliques don't swamp the sparse link edges
  (ADR 0044/0047/0062 deferred concept edges in the link graph for that
  reason).
- **LLM concept engine** (`kb_llm.py`, ADR 0025) — IDEAS.md §9's fancy
  version, run via `kb --engine llm`: a model synthesizes how each
  concept with 2+ member scrolls shows up across them, writing the
  store the compiler reads. Incremental by members fingerprint —
  unchanged concepts cost nothing on re-run, summaries for dissolved
  concepts are pruned. `--batch` (ADR 0032) synthesizes every concept
  needing (re)generation in one Message Batches submission at half the
  per-token price — identical eligibility, skipping, pruning, result
  shape, and per-concept failure isolation, sharing one validation
  (`_parse_summary`) and save path with the per-call transport. Failure
  semantics mirror classification: per-concept failures still compile,
  missing credentials abort but keep what's saved (`tests/test_kb_llm.py`,
  `tests/test_kb.py`). Both LLM engines share one transport (`llm.py`):
  the structured-output call (`anthropic_complete`), its Message Batches
  twin (`anthropic_complete_batch`, the shared poll loop both `--batch`
  paths bind their schema onto — ADR 0022, ADR 0032), credential
  handling, the `LLMError`/`LLMAuthError` hierarchy, and the tier's
  model choice (`$SCROLLS_LLM_MODEL` > `[classify] llm_model` >
  default).
- **Feed sync** (`feeds.py`, ADR 0017) — `follow` validates an RSS
  2.0/Atom feed by fetching it once (stdlib ElementTree, no feedparser)
  and stores the subscription; `sync` polls each feed and registers new
  entry URLs at stage `detected` through `detect_source` +
  `make_item_id`, so dedupe and adapter routing are the same as
  `scrolls add`; each entry's feed title names the new item and its
  entry date (normalized to UTC ISO 8601) seeds `published_at`, with
  fetch replacing both only by the source's own values (ADR 0021).
  Polls are conditional GETs (ADR 0019): a full
  response's `ETag`/`Last-Modified` land on the subscription and a 304
  reports the feed `unchanged` without re-parsing; follow never stores
  validators, so the first sync always sees the feed's current entries.
  YouTube playlist/channel URLs map to their public
  feeds syntactically; one dead feed fails its subscription, never the
  batch (`tests/test_feeds.py`, `tests/test_http.py`).
- **Media capture** (`media.py`, ADR 0011) — downloads items' media
  refs to `media/<source>/<id-slug>-<n><ext>`, records each file's
  root-relative `path` on the ref (reused on re-capture, so locations
  are stable), and re-renders the scroll so frontmatter points at local
  files. Batch runs capture only refs missing from disk; `media <id>`
  re-captures explicitly (`tests/test_media.py`).
- **Context bundles** (`context.py`, IDEAS.md §11) — `scrolls context`
  emits Markdown (the bundle *is* the artifact agents drop into
  context), unlike the data commands; errors stay JSON on stderr. Each
  excerpt carries item id, source, and scroll path for follow-up. Beyond
  the FTS matches, a **Connected scrolls** section pulls in items linked
  to or from those matches through the link graph (`build_graph`, the
  same edges `scrolls graph` reports) but not themselves keyword hits —
  the model↔paper, package↔repo, and dataset↔parent-work edges of
  ADRs 0034–0046 surfacing where an agent reads them, not only in
  `scrolls related`/`graph` (ADR 0047). Link-only and high-precision
  (concept/tag signal deferred), ranked by centrality, capped at the
  match count, and omitted when nothing connects; the MCP
  `get_context_bundle` inherits it through `build_context`
  (`tests/test_context.py`). The bundle takes the same
  `source`/`category`/`stage` facets as search (ADR 0058), plus the
  `tag`/`concept` membership facets (ADR 0059): they narrow the
  underlying ranked match — and so the connected-scrolls graph — so a
  bundle can cover "what the *papers* tagged efficient say about X"; a
  scoped bundle names its facets in the title (`category=unclassified` for
  the empty-string pool, `tag`/`concept` verbatim) to stay self-documenting
  once dropped into context.
- **Agent install** (`agents.py`, ADR 0006) — writes instruction files
  under `<root>/agents/` only, never into another tool's config tree
  (`tests/test_agents.py`). Regeneration is **refresh-safe** the same way the
  KB compiler is (`generated.py`, ADR 0102): the shared command-reference body
  is the fenced `@generated` region, so a reinstall refreshes it while a note
  appended after the `@end` marker survives. Skill frontmatter is a regenerated
  *header* pinned above the fence — its `---` must stay at byte 0 to load as a
  skill — so for SKILL.md only a suffix annotation is preserved; Codex's
  header-less AGENTS.md keeps an annotation either side, like a `library/` page.
- **Doctor** (`doctor.py`, ADR 0026) — `scrolls doctor` diagnoses drift
  between the index and the file tree: duplicate url-hash items left by
  pre-normalization URLs (ADR 0023's deferred debt), recorded scroll
  files missing on disk, captured media files gone, orphan scroll files,
  FTS desync. `--fix` repairs only what is safe offline — merges each
  duplicate group atomically into the id a clean re-add would mint
  (`items.replace_items`), rewrites missing scrolls from the index,
  rebuilds FTS — and exits 0 only when the library ends fully
  consistent, so it works as a cron-able health probe. Missing media
  stays `scrolls media`'s job; orphan files are never deleted
  (`tests/test_doctor.py`).
- **Maintain** (`maintain.py`, roadmap H22/H23/H34, H36) — `scrolls maintain`
  is the scheduled custody-maintenance pass: recheck → regenerate → audit →
  custody delta vs the last run (snapshot at `<root>/.maintenance/last-run.json`).
  Built entirely from the surfaces above (`verify`, `compile_kb`, `run_doctor`);
  the module owns only the snapshot/delta layer plus the append-only run log
  (`log.jsonl`, read back by `maintain --history [N]` — the custody trend).
  Report-only and idempotent — records drift events and regenerates views, never
  repairs rows or re-enriches — so it is a safe cron-able pass
  (`tests/test_maintain.py`). Like doctor, deliberately not exposed over MCP (a
  mutating operator surface).
- **Removal** (`remove.py`, ADR 0027) — `scrolls rm` deletes an item's
  files (scroll, captured media) and then its row, in that order, so an
  interrupted removal leaves a re-runnable item rather than orphan
  files; the FTS delete trigger keeps search in sync. Refs are ids or
  URLs resolved through the same normalize → detect → mint chain as
  `add`, and every recorded path is validated against the library root
  before anything is deleted. No tombstone: a still-followed feed
  re-registers the entry on the next sync. Deliberately not exposed
  over MCP, like doctor (`tests/test_remove.py`).
- **MCP server** (`mcp_server.py`, ADR 0014, ADR 0020) — `scrolls mcp`
  serves the same engines to MCP clients over stdio: plain sync tool
  functions (`get_context_bundle`, `search_scrolls`, `list_scrolls`,
  `list_facets` (ADR 0080 — the filterable vocabulary with counts, the
  discovery counterpart to `list_scrolls`), `get_scroll`,
  `get_related_scrolls`, `get_link_graph`, `get_works` (ADR 0069 —
  same-work clusters by DOI; `item=` gives the per-item lens of ADR 0072),
  `get_concept_page`,
  `get_tag_page` (ADR 0064 — tag matched case-insensitively, slug
  collisions resolved by the page's `# Tag:` heading),
  `list_sources`,
  `ingest_url`, the feed subscription tools `follow_feed`,
  `unfollow_feed`, `list_feed_subscriptions`, `sync_feeds`, plus
  `compile_library`) registered
  on FastMCP, which derives schemas from type hints. Read tools mirror
  CLI conventions — empty library, empty results; unknown id, tool
  error — `sync_feeds` shares the CLI's batch semantics through
  `feeds.sync_many`, and `compile_library` is the deterministic
  compiler only: LLM summary generation (ADR 0025) stays a CLI step so
  no MCP tool ever makes paid API calls implicitly (`tests/test_mcp.py`).

## Interface conventions

The per-command contract — output keys, exit-code semantics, error
envelopes, with captured real output — lives in `docs/cli.md`. The
recurring rules:

- **JSON on stdout** for every data command; errors as JSON on stderr
  with exit 1. The deliberate exceptions emit the artifact itself: `context`
  emits a Markdown bundle, `export opml` an OPML document (ADR 0077),
  `export bookmarks` a Netscape bookmark file (ADR 0079), and the
  scroll/KB files are Markdown — in each the output *is* the thing the
  command produces, not a report about it.
- **CLI is one module** (`cli.py`): argparse subcommands, each a thin
  `cmd_*` function over the library modules. The CLI owns process
  concerns (JSON encoding, exit codes, loading `config.toml` — ADR
  0016); engines stay importable and
  testable without it (`tests/test_cli.py` covers the seams). The
  add/ingest chain lives in `src/scrolls/pipeline.py` so the CLI and
  the MCP server share one implementation (ADR 0014).
- **Item refs are ids or URLs** (ADR 0028): every command that takes an
  item id also accepts the item's URL, resolved by
  `pipeline.resolve_item_id` through the same normalize → detect → mint
  chain `add` registers with, so the saved URL is always a valid handle
  (`tests/test_pipeline.py`). The MCP item-ref tools — `get_scroll`,
  `get_related_scrolls`, and `get_works` — share the same resolver, so an
  agent that found an item's `url` can inspect, relate, or cluster it
  without first learning its minted id (`tests/test_mcp.py`).
- **Dependency posture** (ADR 0001): stdlib first; a third-party package
  must buy its feature something substantial. Today's full list:
  `trafilatura` (web), `youtube-transcript-api` (youtube), `pypdf`
  (arxiv and pdf), `mcp` (the protocol server, imported only by
  `scrolls mcp`), `anthropic` (the LLM tier, imported only by
  `scrolls classify --engine llm` and `scrolls kb --engine llm`) — see
  `pyproject.toml`.
- **No network in tests**: every adapter takes an injectable fetcher;
  fixtures are recorded payloads. The suite runs in under a second.

## Status and known next steps

All five IDEAS.md §14 MVP passes have a working first version: library
skeleton, URL → Markdown for the §6 trio plus github/arxiv/x-via-import,
FTS5 search, two-layer classification (rules + LLM, ADRs 0004/0015), and
the compiled KB with context bundles and agent install.

Next steps already identified in decision records, in no required order:

- **Social posts** — the Bluesky adapter (ADR 0048) reaches the keyless
  social-post source IDEAS.md §6 deferred X for, on the open network; the
  Mastodon adapter (ADR 0049) reaches the federated Fediverse by URL
  *shape* rather than host — now serving its API-compatible forks
  GoToSocial and Pleroma/Akkoma on the same source and fetch adapter, since
  they expose the identical `/api/v1/statuses` surface and only their URL
  routes and id formats differ (ADR 0050); and the Misskey adapter
  (ADR 0051) reaches the Misskey-family software (Sharkey, Firefish,
  Foundkey) on its `/notes/<id>` shape. Misskey corrected the earlier
  assumption that it would be one more mastodon shape: it speaks its own
  `POST /api/notes/show` API, not Mastodon's, so the Fediverse is now
  covered by *two* adapters split by client API, not host — and a future
  Fediverse software with a third API (a Lemmy/PieFed post) would split off
  the same way. `x`
  itself still arrives only through `import fieldtheory` (ADR 0009): a
  native `x` fetch adapter would let a pasted or synced tweet URL enrich
  on its own, but X's read API is now paywalled, so it cannot be keyless
  like every other adapter. The remaining tightening is DID-canonical
  Bluesky / home-instance-canonical Mastodon/Misskey identity (resolve a
  post's true id at fetch time so it dedupes across the routes that reach
  it — ADRs 0048–0051 all defer it as the only fetch-time id rewrite any
  adapter would do).
- **Discussion aggregators and forums** — the federated link aggregators
  Lemmy (ADR 0052) and PieFed (ADR 0053) and the centralized forum software
  Discourse (ADR 0054) extend the discussion family beyond the centralized
  Hacker News (ADR 0031) and Lobsters (ADR 0046). Discourse is the first
  *non-Fediverse* host-less source — shape-detected by its `/t/<slug>/<id>`
  topic URL the way the Fediverse sources are — so the technique is now
  general, not ActivityPub-specific. **Mbin** (the kbin fork) was the named
  next aggregator (ADRs 0052/0053), but its read API is OAuth-gated — its
  `security.yaml` grants no anonymous `/api/entry`, and live instances 401/403
  an unauthenticated read — so it cannot join as a keyless adapter without a
  client-credentials token dance or an ActivityPub `apId` object fetch; it is
  deferred to its own ADR if that posture is ever taken (ADR 0054). A future
  Lemmy-shaped aggregator with a *distinct* URL would detect separately like
  Discourse; one sharing `/post/<digits>` would slot into the `threadiverse`
  dispatcher like PieFed.
- **More code hosts** — the GitHub adapter (ADR 0007) got siblings in
  GitLab (ADR 0055, the second major host), Gitea/Forgejo (ADR 0056, the
  third — Codeberg and gitea.com), and Bitbucket (ADR 0057, the fourth — "the
  remaining big one"), so the four big hosts are now covered. The family spans
  both identity shapes: github/gitlab/**bitbucket** are host-scoped with a
  single fixed API host (Bitbucket Cloud is one service, so it took github's
  flat `<workspace>/<repo>` — folded lowercase like gitlab — *not* gitea's
  host-in-id), while Gitea introduced the host-in-identity shape
  (`gitea:<host>/<owner>/<repo>`) a self-hosted-across-many-hosts platform
  needs: the instance host rides in the `source_id` because the API lives on
  each host, so two extensions are now cheap detection changes rather than
  adapter rewrites. *More Gitea/Forgejo hosts* (self-hosted Codeberg-likes)
  could join via a configured host allowlist, the adapter already host-carrying.
  *Gitea's cousin Gitea-API hosts* aside, *self-hosted GitLab* (deferred in
  ADR 0055 because a bare repo root carries no shape tell) would want the same
  host allowlist or an explicit source hint. *Bitbucket Server/Data Center*
  (the self-hosted product, a different `/rest/api/1.0/` API on arbitrary hosts)
  would be its own adapter, not a detection-only change like a new gitea host.
  *Issue/PR threads* are a second content kind on **all four** code-host sources
  now — github (ADR 0084, `owner/repo#<n>` dispatched on the `#`), gitlab
  (ADR 0085), gitea (ADR 0086), and bitbucket (ADR 0087) — so the family is
  complete. GitLab forced the first adaptation of the template — its issues and
  MRs keep *separate* iid sequences, so the marker must distinguish them
  (github's `#<n>` is a unified namespace), and the `#`/`!` doubles as the
  endpoint selector (`GET /api/v4/projects/<id>/issues/<iid>` vs
  `/merge_requests/<iid>`, each with `/notes`). Gitea took github's rule
  unchanged — it *unifies* issue/PR numbering (one
  `/api/v1/repos/<o>/<r>/issues/<index>` serves both → one `#` marker), the only
  divergence the plural web path `/pulls/<n>`, and unlike gitlab its `/comments`
  endpoint is keyless. Bitbucket took gitlab's rule — it *splits* numbering on
  separate endpoints (`/issues/<n>` vs `/pullrequests/<n>` → the `#`/`!`
  two-marker rule, the web PR path hyphenated `/pull-requests/<n>`), with
  `concepts` empty (no labels feature) and the state normalized to github's vocab
  like the others; its native issue tracker is deprecated by Atlassian (410 on
  most repos), so PRs are the live-verified case. The two identity shapes the
  hosts forced — unified `#<n>` (github/gitea) and split `#`/`!`
  (gitlab/bitbucket) — and a uniform `tags` vocabulary
  (`issue`/`pull request`/`merge request`, `open`/`closed`/`merged`) mean
  cross-host `--tag` filters work. No web-discoverable hosts remain; *self-hosted*
  thread support (GitLab CE, Gitea instances, Bitbucket Server/DC) would ride on
  the same per-host detection slice their repos await.
- **Two-phase batch submit/collect** — both `--batch` paths (ADR 0022,
  ADR 0032) block and poll until the batch ends. If a real batch ever
  outgrows a terminal wait, the persisted-batch-id design those ADRs
  weighed and deferred has an obvious home in the shared `llm.py`.
- **More package registries** — the PyPI adapter (ADR 0034) set the
  pattern and npm (0035), crates.io (0036), Packagist (0039), RubyGems
  (0040), Go modules (0042), pub.dev (0088), Hex (0089), NuGet (0090),
  Hackage (0091), and Maven Central (0092) followed it, spanning Python,
  JavaScript, Rust, PHP, Ruby, Go, Dart/Flutter, Elixir/Erlang, .NET, Haskell,
  and the JVM — the eleven cover every top-tier language ecosystem. Go was the
  sparsest — the `proxy.golang.org` `@latest`
  carries no description, keywords, or license, so `summary`/`concepts`/
  `tags` are all empty and the go.mod manifest is the searchable content —
  while pub.dev and Hex are the family's pair of *twins in field layout*
  (a `meta`/`pubspec` object of description + licenses + links) that
  *diverge on the concept signal*: pub's `pubspec.topics` feed the KB
  concept graph like PyPI's keywords, where Hex (like RubyGems and Go)
  carries none — the clean illustration that the registry's *data*, not the
  adapter, decides whether a package can join the concept graph. pub's
  `flutter` tag is the family's first *derived* facet (computed from the SDK
  dependency, not read from a declared field), and Hex's `meta.links` map
  is its first map-shaped links source (the values iterated where the
  others read named scalar fields). NuGet took the Go *shape* — a flat-container
  version index then the `.nuspec` manifest, two plain requests — over its
  richer registration API, which is gzip-only (the shared UTF-8 `get_json`
  can't read it) and paginates; its `<tags>` feed the concept graph like
  pub/PyPI, and it is the family's first XML manifest (parsed
  namespace-agnostically since the nuspec namespace URI varies by schema
  generation). Hackage broke the JSON mold entirely: its endpoint serves the
  latest version's **cabal** manifest, an indentation-structured `field: value`
  format, so the adapter carries the family's first cabal parser — and the
  cabal's `description` is real prose, making Hackage the first registry whose
  own manifest carries a searchable body (Go's go.mod is a dependency manifest,
  not prose). Maven Central — the largest ecosystem of all (Java/Kotlin/Scala/
  Clojure/Android) — took the same flat-file shape: a `maven-metadata.xml`
  version index then the `.pom` manifest (the family's second XML manifest,
  parsed namespace-agnostically like the nuspec), two plain requests against the
  static repository rather than the rate-limited Solr search API. It is
  identity-distinct — the only **coordinate** (`groupId:artifactId`, the
  reverse-DNS group path-encoded `com.google.guava`→`com/google/guava`, Go's
  request-encoding cousin) — and *diverges from NuGet on two axes*: its POM has
  no keyword facet, so `concepts` are empty by design (the RubyGems/Go/Hex
  posture, the JVM a metadata-and-edges source not a concept source), and its
  `published_at` is read from the **version index's `<lastUpdated>`**, making it
  the only adapter whose date lives outside its own content manifest. The eleven
  span the case-sensitivity axis on purpose —
  PyPI/crates/Packagist/pub/Hex/NuGet fold, npm/RubyGems/Hackage/**Maven**
  preserve, Go preserves with request case-encoding — pub, Hex, and NuGet the
  *forgiving* end of the fold (their canonical names are always lowercase, so
  folding can only rescue a mistyped URL, never miss). Packagist's
  comparator-free "highest stable `version_normalized`" selection (ADR 0039,
  reused by NuGet's pre-release-skipping ranking and Maven's SNAPSHOT-excluded
  fallback) and Go's request case-encoding (`X`→`!x`, ADR 0042) are the
  techniques a future JSON-metadata registry can reuse; **CPAN** (Perl, via the
  rich MetaCPAN JSON API, with a module→distribution resolve for `/pod/` URLs),
  **CRAN** (R), and **conda-forge** remain reachable on the same pattern,
  unclaimed until a saved URL needs one.
- **More DOI registration agencies** — Crossref (ADR 0037) and DataCite
  (ADR 0045) now share the `doi.org` detection through the `doi.py`
  fetch-time dispatch (Crossref first, DataCite fallback). A smaller
  agency (mEDRA, JaLC, the Korea/China RAs) that publishes keyless
  metadata could join the same dispatch without a new URL shape — and a
  DOI-RA pre-lookup (`doi.org/doiRA/<doi>`) would replace the wasted
  Crossref 404 a DataCite fetch currently pays, if that latency matters.
- **Cross-source `paper` enrichment** — arXiv and its published Crossref
  version now relate through the `arxiv:doi` link (ADR 0038); a PubMed
  record relates to its Crossref DOI the same way (ADR 0065); and a
  bioRxiv/medRxiv preprint relates to its published-journal DOI the same way
  again (ADR 0068) — so the biomedical literature and both major
  preprint servers join the paper graph too, with up to *four*
  representations of one work potentially in the library at once (an arXiv
  or bioRxiv/medRxiv preprint, a PubMed record, the published DOI).
  `scrolls works` (ADR 0069) delivers the consolidation view: it
  clusters those representations by the shared DOI that names the work —
  catching same-work groups even when the binding Crossref item is absent,
  which the link graph cannot — `library/works.md` (ADR 0070, the
  `library/graph.md` analog, fed by the same `works_over(items)`) makes
  that clustering a browsable KB page, and **category pages now consolidate
  a work's representations** (ADR 0071): the same `works_over` clustering,
  scoped to each category page's members, collapses a work's near-duplicate
  `paper` entries into one consolidated entry on the page where they
  co-occur — the *presentation* form of the long-flagged merge. The
  remaining step is the deeper merge of the **scrolls themselves**:
  collapsing a work's per-representation scroll files and index rows into one
  canonical item (so `search`, `list`, and the source pages also see one
  entry, not several), alongside the reverse enrichment from richer Crossref
  `relation` data that would let that one item carry every representation's
  metadata.
