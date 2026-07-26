# Domain Docs

*Amended: 2026-07-26 — vision merged into `docs/vision.md`, inspiration
consolidated under `docs/inspiration/`, dev check-ins added.*

Scrolls currently uses a single-context documentation layout.

Primary context sources, in reading order for a new contributor or agent:

- `README.md` — public project framing and the current command surface.
- `docs/architecture.md` — how the implemented system fits together: pipeline stages, module map, data model, the source adapter contract, and how to add an adapter.
- `docs/adapters.md` — the per-source adapter catalog: what each adapter captures, its identity rules, and its fidelity boundary.
- `docs/cli.md` — the CLI output contract: per-command JSON keys, exit codes, and error envelopes, with captured real output and an offline reproduction script.
- `docs/library-format.md` — the on-disk artifact contract: scroll frontmatter and body format, compiled `library/` page formats, agent instruction files, and what consumers may rely on.
- `docs/adr/` — architectural decision records, indexed at `docs/adr/README.md`.
- `docs/vision.md` — the operative north star (custody-first synthesis; the three vision documents were merged here 2026-07-26 — `docs/custody-vision.md` and `docs/agents/vision.md` are stubs pointing here, kept because ADRs reference them).
- `docs/product/prd.md` — product direction; `docs/product/mvp.md` — the shipped near-term scope. Both defer to the vision as authority.
- `docs/agents/autonomous-roadmap.md` — the hour/day/week automation buffer the hourly worker follows, mapped to the PRD/MVP.
- `docs/agents/progress/` — dated dev check-ins (`<YYMMDD>/`): `report.md` (facts), `reconciliation.md` (progress vs goals — deviations + corrections), `plans.md` (next objectives + 1/3/7-day plan).
- `docs/inspiration/` — the inspiration/lineage record (Field Theory CLI, last30days-skill, obsidian-second-brain), one document per source with explicit adopt/adapt/reject mappings, indexed by its README.
- `IDEAS.md` — the product/architecture brainstorm the implementation draws from; not everything in it exists yet.
- `CLAUDE.md` — agent operating guide.

When making consequential decisions, prefer adding a short ADR under `docs/adr/` (and a row in its index) rather than burying rationale in chat history. When a slice changes the pipeline, adapter contract, or data model, update `docs/architecture.md` in the same commit; when it changes a command's arguments, output keys, or exit codes, update `docs/cli.md` in the same commit; when it changes scroll frontmatter, body sections, or `library/` page formats, update `docs/library-format.md` in the same commit (its pinned examples are enforced by `tests/test_docs.py`, so the suite will remind you).

Terminology:

- **Source** — a platform or archive adapter such as YouTube, Wikipedia, X/Twitter, Google Takeout, Field Theory, web pages, GitHub, PDFs.
- **Item** — a normalized internal record from any source.
- **Scroll** — a durable Markdown artifact generated from an item.
- **Library** — a compiled interlinked knowledge base from scrolls.
- **Context bundle** — a compact cited package of relevant scrolls for agents.
