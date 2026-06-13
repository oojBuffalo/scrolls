# ADR 0026: `scrolls doctor` — integrity diagnosis and offline repair

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

The library is deliberately two-headed: SQLite is the canonical index,
Markdown files are the canonical artifacts (IDEAS.md §3). Two stores
drift. Users delete or move scroll and media files; out-of-band SQL can
desync the FTS index; and — the concrete debt that motivated this —
ADR 0023 chose not to migrate pre-normalization libraries, so a library
older than URL normalization can hold a junk-URL item that a clean
re-add duplicates. ADR 0023 named the remedy ("a `doctor`-style dedupe
can repair it if it ever matters") and the README carried it as the
first next candidate. Nothing reported drift, let alone repaired it.

## Decision

1. **One command, two modes.** `scrolls doctor` reports; `scrolls
   doctor --fix` additionally repairs. The engine lives in
   `src/scrolls/doctor.py`, the CLI stays a thin `_cmd_doctor`.
2. **Five checks.** Duplicate url-hash items grouped by
   `(source, normalize_url(url))`; items whose recorded
   `markdown_path` file is gone; media refs whose recorded `path` file
   is gone; `.md` files under `scrolls/` no item owns; and FTS5
   `integrity-check` against the items table (SQLite ≥ 3.42 — older
   ones honestly report `unsupported` rather than guessing).
   Duplicates only consider items without a `source_id`: everywhere
   else the URL spelling never was the identity, and doctor does not
   second-guess source detection.
3. **Fix only what is provably safe offline.** Merge duplicates,
   rewrite missing scrolls from the index (IDEAS.md §3: scrolls can
   always be rebuilt), rebuild the FTS index. Missing media is
   `scrolls media`'s job (network; its batch mode already re-captures
   refs whose file is gone). Orphan scrolls are never deleted — doctor
   cannot prove it wrote them. The one file deletion allowed is a
   merged loser's scroll, which doctor itself just made redundant.
4. **Merges must kill the duplicate for good.** The survivor's id is
   minted from the normalized URL — `make_item_id(source, None,
   normalized)` — because that is what a future clean `scrolls add`
   mints; keeping any other member's id would let the duplicate recur.
   Content fields follow the most advanced member (rendered > fetched
   > detected, then earliest `saved_at`, then id — deterministic);
   `category`/`domain` take the first value across members in that
   order (ADR 0018 keeps no is-user-set bookkeeping, so fill-if-empty
   is the honest merge); `tags`/`concepts` union; `saved_at` keeps the
   earliest save. The row swap is atomic
   (`items.replace_items`: delete the group + insert the survivor in
   one transaction), losing scroll files are removed, and the
   survivor's scroll is re-rendered so frontmatter shows the merged
   identity.
5. **Exit 0 means fully consistent.** Unlike the batch commands (exit
   1 only when an item *failed*), doctor exits 1 whenever drift
   remains — found-but-not-fixed counts, including the report-only
   kinds. That makes `scrolls doctor` cron-able as a health probe.
   Report mode never mutates; doctor never creates a library and never
   touches the network.
6. **Not exposed over MCP.** Doctor deletes rows and files; that stays
   a deliberate CLI action, consistent with ADR 0025's rule that MCP
   tools never do consequential things implicitly.

## Consequences

- ADR 0023's open migration debt has its remedy: `doctor --fix`
  converges a pre-normalization library to one clean item per
  resource, and re-running it (or re-adding the URL) cannot resurrect
  the duplicate.
- A deleted scrolls tree is recoverable: `doctor --fix` rewrites every
  recorded scroll from the index.
- A merge can over-claim only if two genuinely different pages share a
  normalized URL — the same risk boundary ADR 0023 already accepted
  for new registrations, now applied to old rows.
- Orphan scrolls and missing media keep doctor exiting 1 until the
  user (or `scrolls media`) resolves them; "doctor is green" therefore
  actually means consistent, at the cost of demanding manual cleanup
  for findings it refuses to auto-fix.
- FTS verification depends on the SQLite runtime: before 3.42 the
  check degrades to `unsupported` (not an issue, not a guess), while
  `--fix` could still rebuild — acceptable, since every supported
  platform observed ships ≥ 3.42.

## Proof

`src/scrolls/doctor.py`, tested end-to-end in `tests/test_doctor.py`
(clean/uninitialized libraries, each check's found/fixed/refused path,
merge semantics including searchability and non-recurrence, exit
codes) and `tests/test_items.py` for the atomic `replace_items`;
captured CLI output in `docs/cli.md`. 532 passing.
