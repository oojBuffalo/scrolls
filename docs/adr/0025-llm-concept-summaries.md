# ADR 0025: LLM concept summaries are stored data the deterministic compiler includes

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0005's deterministic KB compiler groups scrolls into concept pages
and explicitly left a slot for IDEAS.md §9's "fancy version": LLM-
synthesized prose describing how a concept shows up across the saved
items that share it. Both `README.md` and `docs/architecture.md` have
carried it as the named next step since the LLM classification engine
(ADR 0015) established the opt-in LLM tier.

The open questions: where synthesized prose lives, given that the
compiler rebuilds every page from scratch on each run; how to keep
repeat runs from re-billing the whole library; which concepts deserve a
synthesis at all; and how a second LLM engine shares the credential and
transport handling the first one already carries.

## Decision

1. **Summaries are stored data, not compile-time output.** A new
   `concept_summaries` table (schema v6) holds one row per concept
   slug: display form, summary text, a members fingerprint, engine,
   model, and timestamp. `scrolls kb --engine llm` writes the store and
   then compiles; a plain `scrolls kb` only reads it. Synthesizing
   during compilation was rejected because pages are rebuilt from
   scratch each run (ADR 0005): the prose would either be re-billed on
   every compile or silently destroyed by the next keyless run. With
   the store, the deterministic compiler stays deterministic — and a
   paid summary survives every later offline compile, leading its
   concept page.
2. **Generation is incremental via a members fingerprint.** Each row
   records a SHA-256 over the member items' `(id, content_hash)` pairs,
   order-independent. A concept whose fingerprint (and engine version)
   matches its stored row reports `current` with no model call, so
   re-running on an unchanged library costs nothing — the same posture
   as feed HTTP caching (ADR 0019). Membership changes, refetched
   content, or a bumped `kb-llm-v1` engine tag regenerate exactly the
   affected concepts.
3. **Only concepts with 2+ member scrolls qualify.** Cross-item
   synthesis is the value; a one-scroll concept page has nothing to
   synthesize beyond that item's own summary, and arXiv taxonomy names
   and GitHub topics make single-member concepts the common case.
   Summaries whose concept drops below the bar (or vanishes) are
   pruned — stale prose about members that left is worse than the
   honest deterministic page.
4. **The LLM tier gets one shared transport: `scrolls/llm.py`.** The
   structured-output Messages call, the credential-sniffing
   (`TypeError` → `LLMAuthError`), and the error hierarchy moved out of
   `classify_llm` into a shared module; each engine binds only its
   prompt, schema, and validation. `LLMAuthError` is now a sibling of
   `LLMClassifyError` under `LLMError` rather than its subclass, and
   the CLI catches the base. Both engines also share the tier's model
   choice: `$SCROLLS_LLM_MODEL`, then `[classify] llm_model`
   (ADR 0016), then the default — one knob, because one library talks
   to one model; a `[kb]` config section can come later if the engines
   ever need to diverge.
5. **Failure semantics mirror classification (ADR 0015).** A
   per-concept API failure reports `failed` and never aborts the run;
   the compile still happens, exit 1. Missing credentials abort before
   compiling — every remaining concept would fail identically — but
   summaries already saved stay saved, so the next run resumes where
   the abort happened.

## Consequences

- `scrolls kb` output gains a `summaries` count; `--engine llm` adds
  `generated`/`current`/`failed`/`pruned` and per-concept `results`
  (`docs/cli.md`).
- Schema v6; pre-v6 libraries migrate on the next write command, and
  the read-only `scrolls kb` tolerates an unmigrated database
  (`test_load_concept_summaries_tolerates_pre_v6_database`).
- Concept pages lead with the stored summary above the scroll list
  (`docs/library-format.md`); MCP's `get_concept_page` serves it with
  no changes. MCP also gains `compile_library` — the deterministic
  compiler only, so an MCP agent can refresh concept pages after
  ingesting, but no MCP tool ever makes paid API calls implicitly
  (the ADR 0015 "explicit, paid, networked step" posture).
- The Batches API transport (ADR 0022) does not yet apply to concept
  summaries; at typical concept counts the per-call path is fine, and
  the shared transport gives a batch variant an obvious home if
  libraries outgrow it.
- Tests: `tests/test_kb_llm.py` (engine, offline via injected
  completer), `tests/test_kb.py` (store, compile inclusion, CLI paths),
  `tests/test_db.py` (v5→v6 migration).
