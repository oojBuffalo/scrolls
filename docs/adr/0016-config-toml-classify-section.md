# ADR 0016: config.toml is read, starting with the [classify] section

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

`scrolls init` has written a placeholder `config.toml` since Pass 1, and
two decision records pointed at it: ADR 0004 reserved a `[classify]`
section to select engines, and ADR 0015 noted the LLM engine's
model/engine knobs should move there once config reading existed. With
two classification engines live, "no settings are read yet" stopped
being a harmless placeholder: choosing the LLM engine or a cheaper
model meant typing `--engine llm` and exporting `SCROLLS_LLM_MODEL` on
every invocation.

## Decision

1. **Read exactly the section the engines need, no more.**
   `src/scrolls/config.py` parses `config.toml` with stdlib `tomllib`
   (the project requires Python ≥3.11) into a frozen `ScrollsConfig`
   with two fields, the IDEAS.md §8 shape: `[classify] default_engine`
   (`"rules"` or `"llm"`) and `llm_model`. No other sections are
   defined; unknown tables and keys are ignored rather than rejected,
   so future sections can land without breaking older binaries.
2. **Per-invocation overrides always win.** The `--engine` flag beats
   `default_engine`; `$SCROLLS_LLM_MODEL` beats `llm_model`; built-in
   defaults (`rules`, `claude-opus-4-8`) apply last. The `--engine`
   argparse default becomes `None` so "flag not given" is
   distinguishable from "flag says rules".
3. **Only the CLI loads config.** Config is a process concern like JSON
   encoding and exit codes; `classify_item_llm` keeps taking an
   explicit `model` parameter, and `scrolls ingest` still classifies
   inline with rules regardless of `default_engine` — the keyless,
   offline ingest promise of ADR 0015 is not configurable away.
4. **A config the user wrote deserves honest errors.** A missing file
   is simply the defaults, but unparseable TOML, a non-table
   `[classify]`, an unknown engine, or a non-string model raise
   `ConfigError`, which the CLI reports as the standard JSON error
   envelope with exit 1 — never silent fallback to defaults.
5. **The init template documents the live settings.** `scrolls init`
   now writes a commented `[classify]` example instead of "no settings
   are read yet"; the comment-only template still parses to defaults
   (locked by `test_comment_only_template_yields_defaults`).

## Consequences

- `scrolls classify` semantics are configurable per library: a library
  whose owner wants every batch run to use the LLM sets
  `default_engine = "llm"` once. Scripts that need determinism pass
  `--engine rules` explicitly.
- Existing libraries keep their old placeholder `config.toml` (init
  preserves it); it parses to defaults, so nothing changes until the
  user writes settings.
- Every classify run now stats and parses one small TOML file —
  negligible, and only `classify` loads it today.
- The `[classify]` section is the template for future config: other
  commands should add their own narrow sections rather than a grab-bag
  of top-level keys. A `scrolls set`-style category override command
  (ADR 0004) remains open.

## Proof

`src/scrolls/config.py` + config resolution in `cli.py`, with offline
tests (`tests/test_config.py`, config CLI tests in `tests/test_cli.py`;
345 passing) and live runs: `default_engine = "llm"` routes a bare
`scrolls classify` to the LLM engine (hitting the credentials envelope
on a keyless machine), and a malformed `config.toml` produces
`{"error": "config.toml: invalid TOML: …"}` with exit 1.
