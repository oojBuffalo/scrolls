# Architecture Decision Records

One short record per consequential decision, written when the decision is
made (see `docs/agents/domain.md`). All records below are accepted and
implemented on this branch; `docs/architecture.md` describes the system
they add up to.

| ADR | Decision | Consequence in the code |
| --- | --- | --- |
| [0001](0001-implementation-stack.md) | Python ≥3.11 + uv, src layout, stdlib-first dependencies | `pyproject.toml`; per-adapter deps must pay their way |
| [0002](0002-first-fetch-adapter-wikipedia.md) | First fetch adapter is Wikipedia via the MediaWiki action API | fixed the adapter contract: `ScrollItem -> ScrollItem`, `FetchError`, stage `detected → fetched` |
| [0003](0003-youtube-adapter-oembed-transcripts.md) | YouTube via keyless oEmbed + optional transcripts, not yt-dlp | caption-less videos degrade to metadata-only scrolls |
| [0004](0004-rules-classification-engine.md) | Classification starts with a deterministic rules engine | `rules-v1`; unmatched items stay unclassified for a future LLM engine |
| [0005](0005-deterministic-kb-compiler.md) | KB compiler is a deterministic frontmatter rollup | `library/` rebuilt from scratch each run; concept pages merge by slug |
| [0006](0006-agent-install-stays-in-library-root.md) | `agent install` writes only under the library root | never edits `~/.claude` or other tools' config trees |
| [0007](0007-github-adapter-topics-as-concepts.md) | GitHub via keyless REST; repo topics become concepts | first `concepts` producer; `GITHUB_TOKEN` lifts the rate limit |
| [0008](0008-arxiv-adapter-atom-abstracts.md) | arXiv via the Atom export API; abstract becomes the summary | taxonomy codes go to `tags`; name mapping deferred |
| [0009](0009-fieldtheory-import.md) | X bookmarks arrive via Field Theory import, not native sync | `import fieldtheory`; JSONL lines preserved in `raw_text`; ids dedupe against `scrolls add` |
| [0010](0010-arxiv-pdf-full-text-pypdf.md) | arXiv PDF full text extracted inline with pypdf | PDF failure degrades to the abstract-only scroll |
