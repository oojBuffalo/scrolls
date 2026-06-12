# ADR 0015: LLM classification engine as an explicit opt-in (`classify --engine llm`)

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0004 shipped layer one of IDEAS.md §8's "rules first → optional LLM
second → user overrides always win" and reserved an explicit slot for
layer two: an engine that runs where rules honestly stop — unmatched
items stay `category: null`, and `domain`/`concepts` were deferred
entirely because inventing keyword lists would be manufactured taxonomy.
ADR 0005's KB concept pages were likewise designed for an LLM concept
producer to join the platform-curated ones (github topics, wikipedia
categories, arXiv taxonomy names). With all five IDEAS.md §14 MVP passes
working, this was the next slice named in `README.md` and
`docs/architecture.md`.

The open questions: how the model is called (SDK vs raw HTTP, which
model), what the engine is allowed to fill, how its output is kept
trustworthy, and how it composes with the existing batch/override
semantics — all under the project's "no network in tests" rule.

## Decision

1. **A separate engine module, selected per run.** `scrolls classify
   [id] --engine llm` runs `src/scrolls/classify_llm.py` (engine name
   `llm-v1`); the default stays `rules`. `scrolls ingest` keeps
   classifying inline with rules only — it must stay keyless and
   offline. The LLM pass is an explicit, paid, networked step the user
   invokes deliberately, typically after `ingest`/`import` to pick up
   what rules left unmatched.
2. **Official Anthropic SDK, imported lazily.** Same dependency logic
   that admitted `mcp` (ADR 0014): the SDK buys credential resolution,
   typed errors, retries, and structured outputs. Only
   `classify --engine llm` pays the import. Default model is
   `claude-opus-4-8`; `SCROLLS_LLM_MODEL` overrides it (e.g.
   `claude-haiku-4-5` for cheap bulk runs — the user's cost call, not
   the tool's). The reserved `[classify]` section in `config.toml` can
   absorb these knobs when config reading lands.
3. **Structured outputs instead of parse-and-pray.** The request pins a
   JSON schema (`output_config.format`) whose `category` is an enum of
   the full IDEAS.md §8 vocabulary, so the response parses and the
   category is in-vocabulary by construction. The engine still
   validates — the completer is injectable, and fakes deserve the same
   honesty.
4. **Fill what rules couldn't; merge, don't clobber.** The engine
   assigns `category` (full vocabulary — with content in front of it,
   the model can use `tool`/`research`/`dataset`… responsibly), fills
   `domain`, and appends model `concepts` after the platform-curated
   ones (no duplicates), keeping canonical spellings first for the KB's
   slug merge. `tags` stay platform-owned (arXiv taxonomy codes), a
   deliberate narrowing of ADR 0004's "fill domain/concepts/tags".
   Provenance gains `classified_by: llm-v1` and `classified_model`.
5. **Same override semantics, one new failure rule.** Batch runs never
   overwrite an existing category; `classify <id> --engine llm`
   explicitly reclassifies; rendered scrolls are re-rendered. Per-item
   API failures are reported and don't abort the batch, but missing
   credentials (`LLMAuthError`) abort the whole run with the standard
   error envelope — every remaining item would fail identically.
6. **Injectable completer keeps tests offline.** `classify_item_llm`
   takes a `complete(system, user, model) -> str` callable, mirroring
   the adapters' injectable fetcher. Tests inject fakes; the real
   completer's credential handling is tested by stubbing the SDK client
   class, never the network.

## Consequences

- IDEAS.md §8's three layers all exist: rules, LLM, and user overrides
  (which still win — batch never touches an existing category).
- KB concept pages gain their second producer class: model-derived
  concepts flow through the same slug merge as platform-curated ones.
- A batch over N unmatched items makes N API calls — no batching API
  use yet. Fine at personal-library scale; the Batches API (50% cost)
  is the obvious upgrade if libraries get big.
- The engine call itself was verified offline only: this machine has no
  Anthropic credentials, so the live smoke test exercised the
  no-credentials path (which caught a real bug — the SDK raises its
  auth `TypeError` at request-build time, not client construction).
  The success path is locked by injected-completer tests; the first
  keyed run should confirm it end to end.
- `anthropic` joins the dependency list (ADR 0001 posture: it buys
  structured outputs and credential handling we will not hand-roll).

## Proof

`src/scrolls/classify_llm.py` + `--engine` in `cli.py`, with offline
tests (`tests/test_classify_llm.py`, llm CLI tests in
`tests/test_cli.py`; 332 passing) and a live smoke test of the
no-credentials envelope: `scrolls classify wikipedia:en:SQLite
--engine llm` without keys prints the JSON error envelope and exits 1
(captured in `docs/cli.md`).
