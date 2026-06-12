# ADR 0004: Pass 4 starts with a deterministic rules classification engine

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

With the MVP source trio fetched, rendered, and searchable, the next pass
is classification (IDEAS.md §14 Pass 4). IDEAS.md §8 mandates the layering
"regex/rules first → optional LLM second → user overrides always win".
The open questions were what layer one can honestly classify without a
model, and how classification interacts with the `detected → fetched →
rendered` stage pipeline, where rendering already happens before
classification.

## Decision

1. **Category only, from real signals.** The rules engine
   (`scrolls/classify.py`, engine name `rules-v1`) assigns only
   `category`. Inventing keyword lists for `domain`/`concepts` would be
   manufactured taxonomy with no model behind it; those fields wait for
   the LLM engine. Categories come from the IDEAS.md §8 extended
   vocabulary: `reference`, `paper`, `project`, `media`, `tutorial`,
   `opinion`, `documentation`.
2. **Precedence: platform → title → URL → weak default.** Curated
   platforms win outright (wikipedia → reference, arxiv → paper, github →
   project: a wikipedia page titled "How to Solve It" is still an
   encyclopedia entry). Then title patterns (tutorial, opinion), then URL
   shape (`docs.` hosts, `.readthedocs.io`, `/docs/` paths →
   documentation), then youtube → media as a weak default. Unmatched
   items honestly stay `category: null` instead of getting a guessed
   label — the batch picks them up again on the next run, so improved
   rules or a future LLM engine apply automatically.
3. **Classification does not advance `stage`.** It is enrichment, not a
   pipeline step: items keep their stage, and `scrolls classify`
   re-renders already-rendered scrolls so frontmatter stays in sync with
   the DB. Inserting a `classified` stage would have broken `scrolls md`
   batch semantics for no benefit. The batch classifies fetched/rendered
   items (richest signals); `detected` items wait for fetch.
4. **User overrides win via batch/explicit asymmetry.** Batch runs never
   touch an item that already has a category, wherever it came from.
   `scrolls classify <id>` is an explicit reclassify and replaces the
   category. The engine stamps `provenance.classified_by = rules-v1`
   alongside fetch provenance.

## Consequences

- `scrolls classify` is idempotent and safe to run after every fetch.
  `scrolls ingest` classifies inline (add → fetch → classify → md) so the
  first render already carries the category; it never replaces an
  existing one. The batch command remains for items added via
  `add`/`fetch` and for re-running improved rules.
- Unmatched items are re-examined every batch run — wasted work at large
  scale, revisit if libraries get big.
- There is no way yet to *set* a category by hand from the CLI; user
  overrides currently require editing the DB. A `scrolls set` (or
  classify `--category`) slice can add this.
- The future LLM engine slot is clear: run after rules leave an item
  unmatched, fill `domain`/`concepts`/`tags`, record its own
  `classified_by`. The reserved `[classify]` config section in
  `config.toml` will select engines.

## Proof

`src/scrolls/classify.py` + `scrolls classify` in `cli.py`, with
deterministic tests (`tests/test_classify.py`, classify CLI tests in
`tests/test_cli.py`; 167 passing) and a live smoke test: ingesting
`en.wikipedia.org/wiki/Okapi_BM25` and `youtu.be/jNQXAC9IVRw` then
running `scrolls classify` produced `reference` and `media`, and the
rendered scrolls' frontmatter gained `category` lines.
