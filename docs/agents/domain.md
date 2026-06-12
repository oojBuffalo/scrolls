# Domain Docs

Scrolls currently uses a single-context documentation layout.

Primary context sources:

- `README.md` — public project framing.
- `IDEAS.md` — detailed product/architecture brainstorm.
- `CLAUDE.md` — agent operating guide.
- `docs/adr/` — future architectural decision records.

When making consequential decisions, prefer adding a short ADR under `docs/adr/` rather than burying rationale in chat history.

Terminology:

- **Source** — a platform or archive adapter such as YouTube, Wikipedia, X/Twitter, Google Takeout, Field Theory, web pages, GitHub, PDFs.
- **Item** — a normalized internal record from any source.
- **Scroll** — a durable Markdown artifact generated from an item.
- **Library** — a compiled interlinked knowledge base from scrolls.
- **Context bundle** — a compact cited package of relevant scrolls for agents.
