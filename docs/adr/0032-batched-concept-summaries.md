# ADR 0032: Batched concept summaries, and the shared Message Batches transport

- Status: accepted
- Date: 2026-06-13
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0025 shipped the LLM concept engine (`kb --engine llm`) with one
Anthropic Messages call per concept and named its own upgrade: the
architecture doc's "Status and known next steps" listed *batched concept
summaries* — "the Message Batches transport (ADR 0022) has an obvious
home in the shared `llm.py`." A large library can put dozens or hundreds
of 2+-scroll concepts in front of the engine on its first run (or after a
big import), where per-concept calls pay double and serialize on network
latency — exactly the case ADR 0022 already solved for classification.

But ADR 0022's Batches transport (`_anthropic_complete_batch`) lived
inside `classify_llm.py`, hard-wired to that engine's schema, token cap,
and `LLMClassifyError`. The classification and concept engines already
share the *per-item* transport (`llm.anthropic_complete`, ADR 0025); the
batch transport was the one piece that hadn't been pulled up. Adding a
second copy in `kb_llm.py` would duplicate the submit/poll/collect loop
and the SDK's no-credentials handling — the opposite of ADR 0025's
extraction.

## Decision

1. **Extract the Batches transport into `scrolls/llm.py`.**
   `anthropic_complete_batch(system, requests, model, *, schema,
   max_tokens) -> dict[str, str | LLMError]` mirrors `anthropic_complete`'s
   signature exactly: schema and token cap are parameters, not constants,
   so any engine binds its own. The submit-one-batch / poll
   (5s doubling to 60s) / map-results-by-`custom_id` loop, the SDK's
   no-credentials `TypeError` handling, and the per-request outcome
   classifier (`_batch_entry_outcome`) all move here once. Per-request
   failures map to base `LLMError` values; whole-batch failures raise
   (`LLMAuthError` for no credentials, `LLMError` for a rejected
   submission). The poll `_sleep` is module-level in `llm.py` so tests
   observe the loop.

2. **`classify_llm._anthropic_complete_batch` becomes a thin wrapper.**
   It binds `RESPONSE_SCHEMA`/`_MAX_TOKENS` and re-tags each per-request
   `LLMError` as `LLMClassifyError`, so the classification engine and its
   tests keep one error type and byte-identical behavior. No CLI or
   engine logic for `classify --engine llm --batch` changed.

3. **An explicit flag, not a new engine: `kb --engine llm --batch`** —
   the same posture as ADR 0022. The transport changes; the engine
   doesn't. `generate_concept_summaries_batch` shares `summarize`'s
   eligibility (2+ scrolls), members-fingerprint incremental skipping,
   pruning of disqualified concepts, the JSON result shape, the
   `_parse_summary` validation, and the `_store_summary` save with the
   per-call `generate_concept_summaries`. Only concepts that actually
   need (re)generation are submitted; a fully-current or empty library
   submits nothing. The flag requires the llm engine; `kb --batch` on the
   deterministic engine is a contradiction and errors before compiling.

4. **Positional `custom_id`s.** Batches custom_ids must match
   `[A-Za-z0-9_-]{1,64}`, and a concept slug need not (e.g. it could
   carry punctuation a future grouping admits); `concept-<index>` keys
   the requests, mapped back by a single page-ordered plan pass so the
   batch result list matches the per-call run's order.

5. **Failure semantics extend ADR 0025's, per scope.** A per-concept
   batch failure (errored, expired, canceled, a refusal, an unparseable
   payload, or no result entry) is reported and the library still
   compiles, exit 1 — same as a per-call API failure. A whole-batch
   failure — missing credentials or a rejected submission — aborts before
   compiling with the standard error envelope, keeping any summaries
   saved on an earlier run. Generation is one submission, so unlike the
   per-call path there is no mid-run auth abort to leave partial state.

## Consequences

- Bulk concept-summary synthesis costs half per token, and one `kb
  --engine llm --batch` invocation generates an entire backlog in one
  submission. The per-call path stays the default for small or
  interactive runs.
- The LLM tier now has exactly one Batches transport, shared by both
  engines. A future Batches change (a two-phase submit/collect to replace
  the terminal wait, retry policy, request limits) lands once in
  `llm.py` and both `--batch` paths inherit it. Decisions 4–5 of ADR 0022
  (positional ids, block-and-poll, no persisted state) now describe the
  shared transport, not just classification.
- `kb`'s JSON payload is unchanged between transports: `--batch` reports
  the same `generated`/`current`/`failed`/`pruned` + per-concept
  `results` keys ahead of the compile summary, so consumers can't tell
  which transport ran.
- Live verification was offline-only, as with ADRs 0015/0022/0025: this
  machine has no Anthropic credentials, so the smoke test exercised the
  flag's guard (`--batch` on the deterministic engine), the no-eligible
  zero run that submits nothing, and the missing-credentials abort on a
  seeded 2-scroll concept — all captured in `docs/cli.md`. The success
  path is locked by stubbed-completer tests; the first keyed run should
  confirm end to end.
- MCP still exposes only the deterministic `compile_library` (ADR 0025);
  neither `--batch` path is an MCP tool, so no MCP call ever makes paid
  API requests implicitly.

## Proof

`anthropic_complete_batch` + `_batch_entry_outcome` in
`src/scrolls/llm.py`; `generate_concept_summaries_batch` +
`_anthropic_complete_batch` in `src/scrolls/kb_llm.py`; the thin
`classify_llm._anthropic_complete_batch` wrapper; the `--batch` flag and
guard in `cli.py`. Offline tests: the batch-engine section of
`tests/test_kb_llm.py` (one-submission generation, incremental skipping,
per-concept failure isolation, pruning, per-call/batch parity, schema
binding, auth mapping), the CLI tests in `tests/test_kb.py`
(`test_kb_llm_batch_flag_submits_one_batch`,
`test_kb_batch_flag_requires_the_llm_engine`,
`test_kb_llm_batch_without_credentials_aborts_before_compiling`), and the
unchanged classification batch tests in `tests/test_classify_llm.py` and
`tests/test_cli.py` (649 passing). A live smoke of the guard, zero run,
and credentials abort is captured in `docs/cli.md`.
