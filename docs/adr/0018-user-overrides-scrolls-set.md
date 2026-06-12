# ADR 0018: User overrides are `scrolls set`, free-form and clearable

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

IDEAS.md §8 layers classification as "regex/rules first → optional LLM
second → user overrides always win". Layers one and two exist (ADRs
0004, 0015), and the "always win" half was already implemented
implicitly — batch classify never overwrites an existing category — but
there was no way to *create* an override: categories could be assigned
by engines yet never set by hand. ADR 0004 and the architecture doc
both carried this as a named next step.

## Decision

1. **One command, the engines' fields only.** `scrolls set <id>
   field=value...` writes exactly what the classification engines
   write: `category`, `domain`, and the comma-separated lists `tags`
   and `concepts`. Identity and pipeline fields (`url`, `stage`,
   `title`, …) are a different concern and stay un-settable.
2. **Values are free-form.** The rules and LLM engines pin their own
   vocabularies; a human (or supervising agent) overriding them is the
   point of the layer, so no vocabulary check applies. The KB compiler
   groups whatever exists.
3. **Empty clears; lists replace.** `category=` returns the item to
   the batch-classifiable pool — without it, an item could never be
   reclassified by batch runs again. List assignments replace rather
   than merge, because merge has no syntax for removal.
4. **All-or-nothing parsing.** Any malformed assignment or unknown
   field rejects the whole invocation before anything is applied
   (`OverrideError` → standard error envelope), so a typo never
   half-applies.
5. **Stage-neutral, render-synced.** Like `classify`, `set` does not
   advance the stage but re-renders an already-rendered scroll so
   frontmatter matches the index.
6. **No override bookkeeping.** Nothing records that a value was
   user-set: the existing batch semantics (never overwrite a set
   category) already make overrides stick, and explicit
   `classify <id>` replacing one is itself a user action. If engines
   ever need to distinguish user-set from engine-set values, a
   provenance marker can join then.

## Consequences

- The §8 stack is complete: rules, LLM, and user overrides, each
  testable in isolation (`src/scrolls/overrides.py` is pure parsing +
  `dataclasses.replace`; the CLI owns persistence and re-rendering).
- Agents get a safe correction surface: `scrolls show`, then
  `scrolls set` with explicit values, with the error envelope naming
  the settable fields on a miss.
- `domain`/`tags`/`concepts` set by hand are indistinguishable from
  adapter- or LLM-produced ones downstream (KB pages, related-items
  scoring) — which is exactly the intent.
- The MCP server does not expose `set` yet; the shell interface
  remains primary (ADR 0014).

## Proof

`src/scrolls/overrides.py` + `_cmd_set` in `src/scrolls/cli.py`, locked
by `tests/test_overrides.py` (parser/apply) and the `set` CLI tests in
`tests/test_cli.py` (398 passing), including the §8 guarantee itself:
`test_set_survives_batch_classify` sets `category=opinion` on an item
whose title matches the tutorial rule, runs batch classify, and the
override stands. `docs/cli.md`'s examples are captured real output.
