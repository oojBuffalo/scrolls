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
| [0011](0011-media-capture-command.md) | Media capture is an explicit `scrolls media` command, not part of fetch | media refs gain a root-relative `path`; `media/` tree is cache, not canon |
| [0012](0012-arxiv-taxonomy-names-as-concepts.md) | arXiv taxonomy display names become concepts via a bundled table | papers join the KB concept graph; codes stay in `tags`; supersedes 0008's deferral |
| [0013](0013-generic-pdf-adapter.md) | Generic PDF URLs get a fetch adapter via pypdf | every detected source except `x` now fetches; the binary is the raw record (media ref + content hash), not `raw_text` |
| [0014](0014-mcp-server.md) | `scrolls mcp` serves the library over stdio via the official MCP SDK | tools wrap the same engines as the CLI; ingest chain extracted to `src/scrolls/pipeline.py`; SDK imported lazily |
| [0015](0015-llm-classification-engine.md) | LLM classification is an explicit opt-in: `classify --engine llm` via the Anthropic SDK | fills `domain` + merges `concepts`; structured outputs pin the category vocabulary; missing credentials abort the batch |
| [0016](0016-config-toml-classify-section.md) | `config.toml` is read, starting with the `[classify]` section | `default_engine` + `llm_model`; flag/env overrides always win; malformed config errors honestly; only the CLI loads config |
| [0017](0017-feed-subscriptions-sync.md) | Sync is feed subscriptions, not per-platform sync commands | `follow`/`unfollow`/`sync` over RSS/Atom via stdlib; `subscriptions` table (schema v4); sync registers at `detected`, adapters still fetch |
| [0018](0018-user-overrides-scrolls-set.md) | User overrides are `scrolls set`, free-form and clearable | IDEAS.md §8 layer three; engines' fields only; empty value clears; all-or-nothing parsing; no override bookkeeping |
| [0019](0019-feed-http-caching.md) | Feed polling uses HTTP conditional GETs | `etag`/`last_modified` on subscriptions (schema v5); 304 → status `unchanged`; follow never seeds the cache — only a full sync stores validators |
| [0020](0020-mcp-feed-subscriptions.md) | The MCP server exposes feed subscriptions | `follow_feed`/`unfollow_feed`/`list_feed_subscriptions`/`sync_feeds`; batch semantics shared with the CLI via `feeds.sync_many` |
| [0021](0021-feed-entry-published-dates.md) | Feed entry dates seed `published_at`, normalized to UTC ISO 8601 | RSS `pubDate`/Atom `published`-else-`updated`; adapters' own date wins, seed is the fallback; unparseable dates become None |
| [0022](0022-batched-llm-classification.md) | Batched LLM classification is `classify --engine llm --batch` via the Message Batches API | same engine, half the per-token price; block-and-poll, no persisted batch state; per-request failures fail their item, whole-batch failures abort |
| [0023](0023-url-normalization-item-identity.md) | URLs are normalized at registration; the normalized form is identity and storage | `normalize_url` strips tracking params/fragments/default ports before hashing; `related` matches raw + normalized; feed subscription URLs untouched; closes ADR 0017's identity quirk |
