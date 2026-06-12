# 0014: MCP server over stdio via the official SDK

- Status: accepted
- Date: 2026-06-12

## Context

IDEAS.md §10 sequences agent access deliberately: reliable shell
commands first, MCP second, and "do not make MCP mandatory for v1".
The shell interface is complete — every engine has a JSON-emitting
command, `scrolls context` emits agent-ready Markdown, and
`scrolls agent install` teaches the shell-first workflow. The
architecture doc has carried "MCP server" as a named next step since
the interface landed. Agents that speak MCP (Claude Code, Claude
Desktop, others) can consume tools with typed schemas directly, without
shelling out or parsing stdout.

## Decision

`scrolls mcp` serves the library over stdio using the official `mcp`
Python SDK (FastMCP):

- **The SDK is a hard dependency, imported lazily.** Hand-rolling
  JSON-RPC plus the MCP handshake in stdlib is the kind of protocol
  maintenance ADR 0001's "must buy something substantial" test exists
  to avoid — the SDK buys the entire protocol surface. Like
  `trafilatura` and `pypdf`, it is installed always but imported only
  by the command that needs it, so every other command stays free of
  its import cost.
- **Tools wrap engines, not the CLI.** `src/scrolls/mcp_server.py`
  defines plain sync functions over the same engine modules the CLI
  calls; FastMCP derives schemas from type hints and descriptions from
  docstrings. The ingest chain moved out of `cli.py` into
  `src/scrolls/pipeline.py` (`register_url`, `ingest_url`,
  `ensure_library`) so both interfaces share one implementation — the
  CLI keeps process concerns (JSON printing, exit codes), per the
  documented posture.
- **The tool set is IDEAS.md §10's list plus context bundles:**
  `search_scrolls`, `get_scroll`, `get_related_scrolls`,
  `get_concept_page`, `list_sources`, `ingest_url`, and
  `get_context_bundle` (§11 — the bundle is the agent-native artifact,
  so it would be wrong to omit it from the agent-native interface).
- **CLI conventions carry over.** Empty/uninitialized library → empty
  results for read tools; unknown ids raise (FastMCP returns a tool
  error); `ingest_url` reports fetch problems as an `error` key in its
  payload because the item was still registered — the same asymmetry
  `scrolls ingest` has.

## Consequences

- Agents can connect with
  `claude mcp add scrolls -- uv run scrolls mcp` (or equivalent client
  config); the shell interface remains primary and fully sufficient.
- Tool functions are tested directly against a temp library
  (`tests/test_mcp.py`); one test builds the real server and locks the
  registered tool names, so adding or renaming a tool fails tests until
  documented intent matches.
- The generated agent instruction files (ADR 0006) still teach the
  shell-first workflow; mentioning `scrolls mcp` there is a possible
  follow-up once the server has real-world mileage.
- `scrolls mcp` is the first command that blocks and emits no JSON —
  documented as its own interface section in `docs/cli.md`.
