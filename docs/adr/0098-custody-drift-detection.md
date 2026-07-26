# 0098: Custody drift/rot detection — `scrolls verify` and the event ledger

Date: 2026-06-15

Status: accepted

*Amended: 2026-07-26 — the vision docs were merged into `docs/vision.md`
(§ numbering preserved); the path reference below was updated. Decision
content unchanged.*

## Context

The custody-first vision (`docs/vision.md`) names drift/rot detection
as capability 3 and the **explicit next slice** after the integrity audit:

> `scrolls fetch --recheck` (or `scrolls verify`) re-captures a rendered item,
> compares against the stored hash, and records a custody event without
> clobbering the original capture. Doctor aggregates these into a rot/drift
> report. This is the custody *ledger* made real.

ADR 0097 deliberately built the offline integrity audit *first* so this
network-bearing slice would "land after the integrity audit gives it a
deterministic home to report into," and left the vocabulary stable for it: it
named the absent piece as "a real diff [that] belongs to the later
`fetch --recheck` drift slice." This record is that slice.

The integrity audit answers "do we still hold, on disk, what the index
claims?" entirely offline. It cannot answer the question custody actually
exists to answer: *has the live source drifted away from, or rotted out from
under, what we captured?* ADR 0097 noted why a generic offline hash recompute
is impossible — each adapter hashes a different, unstored input — so the only
honest way to detect drift is to **re-capture through the same adapter** and
diff the freshly computed hash against the stored one.

## Decision

**`scrolls verify [id] [--all] [--limit N]`** re-captures held items and
records a drift/rot verdict, in a new `src/scrolls/custody.py` module.

**Verdict taxonomy** (`CUSTODY_STATUSES`), per re-capture:

- `unchanged` — the re-captured `content_hash` equals the stored one. The live
  source still matches our capture.
- `drifted` — the hashes differ. The source changed since we saved it; we still
  hold the original capture, and now we know it diverged.
- `rotted` — the resource is gone (a definitive HTTP **404/410**). We can no
  longer re-fetch; our capture may be the last copy.
- `error` — the re-capture failed for another reason (transient network, parse
  failure, no adapter). Not a verdict about the *source*, just an honest "could
  not check now."

**`verify_item(item, recapture, *, now)` is pure.** It takes the stored item, a
`recapture` callable (`ScrollItem -> ScrollItem`, raising `FetchError`), and the
timestamp to stamp, so the entire decision is deterministic and testable with no
network. The one impure step, `live_recapture`, routes to the same
`FETCH_ADAPTERS` entry `scrolls fetch` uses, so a re-capture sees exactly what a
fresh capture would.

**Rot vs. error reads the real HTTP status, never a string.** Adapters wrap
transport failures as `raise FetchError(...) from exc`, so the original
`urllib` `HTTPError` (carrying `.code`) survives as the cause. `verify_item`
classifies `rotted` only when that cause's status is 404 or 410; everything else
is `error`. A "not found" *in a message* never decides custody — the status code
does, or it stays `error`.

**The capture is never clobbered.** `verify` only appends to the ledger; it
never writes the item row. Detecting that a source changed must not destroy the
proof of what it was when we saved it — that is the whole point of custody.

**A new append-only `custody_events` table** (schema v7) is the ledger:
`item_id`, `checked_at`, `status`, `prior_hash`, `observed_hash`, `detail`, and
a monotonic `id`. Append-only by design — the full drift history of an item is
reconstructable. `latest_events` reads the most recent verdict per item by
`MAX(id)`, which breaks the same-second `checked_at` ties a timestamp cannot.

**Doctor aggregates, in `report["custody"]["drift"]`:** `checked`, the
`unchanged`/`drifted`/`rotted`/`error` counts, and the actionable
`drifted`/`rotted` `events` themselves — but only for items *currently held*
(a verdict for a since-deleted item is not this library's drift). Consistent
with ADR 0097's stance that custody findings are a *report* doctor cannot
repair, drift **never** feeds the structural `issues`/`fixed` or the exit code.

**CLI contract.** Exactly one of an item `id`/URL or `--all` is required
(never both); `--all` re-checks only items carrying a captured `content_hash`
(a reference-only or `detected` item has no baseline to diff against), and
`--limit N` paces a large run oldest-first, exactly like `scrolls fetch`. Exit
is 0 when every item was checked — `drifted`/`rotted` are *successful* checks
recording a real event — and 1 when any `error` left an item unchecked, the
same exit posture as `fetch`.

## Consequences

- The custody ledger is real: the library can answer "what have I lost, or what
  changed, since I saved it?" by `scrolls verify`-ing items and reading
  `scrolls doctor`'s `custody.drift` report. ADR 0097's deferred "real diff"
  now exists, reporting into the vocabulary that ADR left stable.
- `rotted` is grounded in the actual HTTP 404/410 status, so it is emitted only
  when an adapter that uses the shared transport (the large majority) preserves
  the cause. An adapter that swallows the status, or a source whose human URL is
  not its fetch endpoint, degrades to `error` — honest: we could not *prove*
  rot, so we do not claim it.
- Schema is v7; `init_db` migrates older libraries by adding `custody_events`
  with no change to existing rows or other tables. `scrolls verify` migrates the
  library before its first write, so a v6 library gains the ledger on first use.
- The capture row is provably untouched by a `drifted` verdict
  (`test_verify_never_clobbers_the_capture`), so verification is safe to run
  repeatedly — the ledger grows, the captures do not move.
- **The capability is reachable on every surface.** Beyond the CLI, the MCP
  `verify_scroll(item_id)` tool exposes the single-item path to agents (the
  primary users), mirroring the CLI contract — unknown item or missing baseline
  hash raises (the MCP convention), a verdict otherwise — and pointing at
  `scrolls doctor`'s `custody.drift` block for the aggregate report. This
  honors the vision's surface-consistency principle: the same engine, framed
  for each surface.
- Verified offline: `tests/test_custody.py` (every verdict via injected
  recapture, the 404/410-vs-503 split, the no-write property, the
  `MAX(id)` latest-per-item tiebreak, the append-only history),
  `tests/test_doctor.py` drift section (per-verdict counts, latest-only,
  deleted-item exclusion, exit-code isolation), `tests/test_verify_cli.py`
  (every CLI status path, the `id`-xor-`--all` argument contract, `--all`
  baseline filtering and `--limit` pacing, and the verify→doctor handoff), and
  `tests/test_mcp.py` (the `verify_scroll` tool's drift verdict, unknown-item
  and missing-baseline raises, and the locked tool surface).

## Deferred

- **MCP batch / drift-report read.** The MCP tool verifies one item; the `--all`
  batch and an MCP read of the aggregate drift report wait on a broader decision
  about whether `scrolls doctor` itself should be an MCP tool (it carries
  repair semantics the read tools do not).
- **Re-capture-on-accept.** `verify` only records; a future "accept the drift"
  path (re-render from the fresh capture, recording the supersession) would be
  the natural complement, but overwriting a capture is a separate, heavier
  decision than detecting that it should change.
- **Rot/drift gating.** Whether a `rotted`/`drifted` count should gate an exit
  code anywhere (e.g. a `--strict` verify) is left until a workflow needs it;
  the counts are recorded and reportable now.
