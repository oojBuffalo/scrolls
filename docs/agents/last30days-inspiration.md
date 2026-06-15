# Last30Days inspiration for Scrolls

The Scrolls agent trunk should take explicit product and architecture inspiration from [`mvanhorn/last30days-skill`](https://github.com/mvanhorn/last30days-skill), while adapting the ideas to Scrolls' local-first library model rather than copying its implementation.

## Why it matters

`last30days-skill` is a strong example of an agent-facing product where the agent contract, engine behavior, output shape, fixtures, and dogfood workflows are all treated as first-class product surfaces. Scrolls should aim for the same level of operational usefulness: not just many adapters, but a coherent system agents can trust, inspect, export, and reuse.

## Patterns to adapt

1. **Agent-facing contract plus engine contract**
   - Last30Days separates `SKILL.md` instructions from the Python engine and defines exact invocation/output obligations.
   - Scrolls analog: keep CLI, MCP, Markdown library output, and agent instructions in sync with explicit contracts and tests. Avoid features that exist only in code but are invisible to agents.

2. **Multi-source fanout with graceful degradation**
   - Last30Days fans out across Reddit, X, YouTube, TikTok, HN, Polymarket, GitHub, and web, with per-source fallbacks and errors that do not kill the whole run.
   - Scrolls analog: ingestion and library compilation should tolerate partial source failures, preserve per-item/source errors, and make degraded states inspectable via `doctor`, `status`, source pages, and MCP.

3. **Evidence clustering and dedupe over raw accumulation**
   - Last30Days merges cross-source clusters when several platforms discuss the same story.
   - Scrolls analog: prioritize deep works merge, duplicate representation collapse, related-item clustering, and search/list/MCP consistency so the library does not become many near-identical rows.

4. **Signal-aware ranking**
   - Last30Days scores by engagement, recency, source quality, humor/virality, and relevance instead of treating every result as equal.
   - Scrolls analog: expose ranking signals such as source confidence, link graph centrality, publication date, tag/concept overlap, engagement when available, and relationship density. Keep ranking explainable in CLI/MCP output.

5. **Durable shareable artifacts**
   - Last30Days can emit self-contained HTML briefs alongside chat output.
   - Scrolls analog: strengthen export/import, Markdown bundles, shareable library slices, and other artifacts that can move through email, Slack, Notion, git, or another agent without a live DB.

6. **Fixtures, evals, and regression tests as product infrastructure**
   - Last30Days carries fixtures for many providers and explicit quality/regression tests.
   - Scrolls analog: keep adding fixture-backed tests for source adapters, MCP responses, search/list/filter behavior, export/import round trips, doctor/repair, and dogfood scenarios.

7. **Dogfood workflows**
   - Last30Days documents real before-meeting, comparison, and fast-learning workflows.
   - Scrolls analog: build and test end-to-end workflows an agent actually uses: ingest a project/topic, search it, inspect related scrolls, export/import it, repair it, and cite the resulting Markdown library.

## Near-term autonomous priority

Future autonomous runs should prefer these Scrolls slices over additional one-off registry/source adapters unless a new adapter unlocks or validates a broader pattern:

- deep works merge / duplicate representation collapse,
- source confidence and ranking explanations,
- MCP/search/list consistency,
- doctor/repair for degraded library state,
- export/import and shareable bundle workflows,
- threaded/comment rendering and evidence clustering,
- fixtures/evals for dogfood scenarios,
- agent-facing contract tests that keep docs, CLI, MCP, and output artifacts aligned.
