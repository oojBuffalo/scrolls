# Domain Docs

Scrolls currently uses a single-context documentation layout.

Primary context sources, in reading order for a new contributor or agent:

- `README.md` — public project framing and the current command surface.
- `docs/architecture.md` — how the implemented system fits together: pipeline stages, module map, data model, the source adapter contract, and how to add an adapter.
- `docs/cli.md` — the CLI output contract: per-command JSON keys, exit codes, and error envelopes, with captured real output and an offline reproduction script.
- `docs/adr/` — architectural decision records, indexed at `docs/adr/README.md`.
- `IDEAS.md` — the product/architecture brainstorm the implementation draws from; not everything in it exists yet.
- `CLAUDE.md` — agent operating guide.

When making consequential decisions, prefer adding a short ADR under `docs/adr/` (and a row in its index) rather than burying rationale in chat history. When a slice changes the pipeline, adapter contract, or data model, update `docs/architecture.md` in the same commit; when it changes a command's arguments, output keys, or exit codes, update `docs/cli.md` in the same commit.

Terminology:

- **Source** — a platform or archive adapter such as YouTube, Wikipedia, X/Twitter, Google Takeout, Field Theory, web pages, GitHub, PDFs.
- **Item** — a normalized internal record from any source.
- **Scroll** — a durable Markdown artifact generated from an item.
- **Library** — a compiled interlinked knowledge base from scrolls.
- **Context bundle** — a compact cited package of relevant scrolls for agents.
