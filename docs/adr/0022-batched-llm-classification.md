# ADR 0022: Batched LLM classification via the Message Batches API

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0015 shipped the LLM classification engine with one Messages API
call per item and named its own upgrade: "the Batches API (50% cost) is
the obvious upgrade if libraries get big." A Field Theory import or a
backlog of synced feed items can put hundreds of unclassified items in
front of `classify --engine llm`, where per-item calls pay double and
serialize on network latency.

The Message Batches API processes the same requests asynchronously at
half the per-token price: submit up to 100k requests, poll
`processing_status` until `ended`, read per-request results keyed by
`custom_id`. All Messages features — including the structured outputs
that pin the category vocabulary — work inside batch requests. The open
questions: how the CLI exposes it, whether to block or persist batch
state, and how per-request failures map onto the existing batch
semantics.

## Decision

1. **An explicit flag, not a new engine: `classify --engine llm
   --batch`.** The transport changes; the engine doesn't. Prompts,
   schema, validation, merge rules, and `classified_by: llm-v1`
   provenance are byte-identical to the per-item path (the request
   params are built from the same constants). Auto-batching above a
   threshold was rejected — it would change a run's latency profile
   silently, against ADR 0015's "explicit, paid, networked step"
   posture. The flag requires the llm engine and a whole-run
   invocation; `--batch` with one item id is a contradiction and errors.
2. **Block and poll; no persisted batch state.** The CLI submits one
   batch and polls (5s doubling to 60s) until it ends — typically
   minutes at personal-library scale, bounded by the API at 24h. A
   two-phase submit/collect design (pending batch ids in SQLite, a
   collect command) was rejected as lifecycle machinery this scale
   doesn't justify; Ctrl-C loses only the result mapping, items stay
   unclassified, and re-running resubmits. Revisit if real batches ever
   outgrow a terminal wait.
3. **Positional `custom_id`s.** Batches custom_ids must match
   `[A-Za-z0-9_-]{1,64}`, so item ids like `wikipedia:en:SQLite` cannot
   key the requests; `item-<index>` does, mapped back by position.
4. **Failure semantics extend ADR 0015's, per scope.** Per-request
   outcomes (`errored`, `expired`, `canceled`, a refusal, an invalid
   payload) fail their item and never abort the batch; contentless
   items fail locally without being submitted; and a whole-batch
   failure — missing credentials, the submission itself rejected —
   aborts the run with the standard error envelope, because every item
   fails identically. An empty run submits nothing.
5. **Injectable batch completer.** `classify_items_llm_batch` takes a
   `complete_batch(system, [(custom_id, card)], model)` callable
   mirroring ADR 0015's `complete`; the real transport
   (`_anthropic_complete_batch`) is tested by stubbing the SDK client,
   never the network, with the poll loop observable via an injectable
   sleep.

## Consequences

- Bulk LLM classification costs half per token, and one CLI invocation
  classifies an entire backlog in one submission.
- The CLI blocks while polling — acceptable for a deliberate bulk run,
  and documented in `--help` and `docs/cli.md`. The per-item path
  remains the default for small runs and interactive use.
- The engine module now has two transports sharing one validation path
  (`_classified`), so a future engine change (vocabulary, schema,
  merge rules) lands in both automatically.
- Live verification was offline-only, as with ADR 0015: this machine
  has no Anthropic credentials, so the smoke test exercised the flag's
  error envelopes and the empty-run no-submit path. The success path is
  locked by stubbed-SDK tests; the first keyed `--batch` run should
  confirm end to end.
- MCP does not expose classification (either transport); the shell
  interface remains the classification surface.

## Proof

`classify_items_llm_batch` + `_anthropic_complete_batch` in
`src/scrolls/classify_llm.py`, the `--batch` flag in `cli.py`, offline
tests (`tests/test_classify_llm.py` batch section, `--batch` CLI tests
in `tests/test_cli.py`; 445 passing), and a live smoke of the error
envelopes (`--batch` with rules engine, with an item id, and an empty
llm run submitting nothing) captured in `docs/cli.md`.
