# Scrolls

Scrolls is a **local-first custody system** for the internet artifacts you have
deliberately saved or referenced — bookmarks, papers, videos, repositories,
threads, PDFs. Its job is *not* discovery or web search; it is durable
stewardship of what you already chose to keep:

- **Hold** each artifact faithfully as an individual Markdown scroll with rich provenance.
- **Prove** what it was at capture time (raw text, content hash, source response).
- **Surface** drift and rot honestly when the live source changes or disappears.
- **Degrade** transparently when full fidelity isn't possible — never silently.
- **Export** everything losslessly, so you can walk away at any moment.

The library is a *custody ledger*, and agents (Claude Code, Codex, Hermes) are its
primary readers — they trust it because nothing in it is a black box.

```text
Sources → Items → Scrolls → Library → Agents
```

## Pipeline

1. **Ingest** — detect and fetch saved content through a source adapter.
2. **Enrich** — add source metadata, media/link context, transcripts, article text, or page extracts.
3. **Classify** — category, domain, concepts, and usefulness (rules engine, optional LLM).
4. **Reconcile** — merge representations of the same work, detect duplicates, surface conflicts and drift.
5. **Index & compile** — SQLite/FTS index plus a Karpathy-style interlinked Markdown knowledge base.
6. **Expose** — serve the library to humans and agents via CLI, MCP, and portable bundles.

## Quickstart

```bash
scrolls ingest https://en.wikipedia.org/wiki/SQLite  # add + fetch + classify + md
scrolls import fieldtheory          # bulk-import X bookmarks from Field Theory
scrolls follow https://www.youtube.com/playlist?list=PL12345  # subscribe to a feed
scrolls sync                        # register new items from followed feeds
scrolls search "distributed systems"
scrolls context "sqlite fts"        # compact Markdown bundle for agents
scrolls related wikipedia:en:SQLite
scrolls kb                          # compile the interlinked library
scrolls agent install               # write agent instruction files
```

`scrolls sync` is feed-based live delta updates — distinct from one-off `add` and
bulk `import`. Follow any RSS/Atom feed (a blog, a YouTube channel or playlist, an
arXiv category, a GitHub releases feed) and `sync` registers its new entries.

Every command emits JSON to stdout (Markdown for `context`/`export bundle`), so the
whole surface is scriptable and agent-drivable.

## Commands

Every command emits JSON to stdout (Markdown for `context` and `export bundle`);
errors are typed envelopes on stderr. The full per-flag reference — every output
key, exit code, and error envelope with captured real output — is in
**[`docs/cli.md`](docs/cli.md)**.

Setup & inspection:

```text
scrolls init                  # create the library skeleton (idempotent)
scrolls status                # counts, schema, and a custody headline
scrolls paths                 # library layout
scrolls detect <url>          # URL → source adapter + source-local id
```

Ingest & enrich:

```text
scrolls add <url>             # register a URL (stage: detected)
scrolls ingest <url>          # add + fetch + md in one step
scrolls fetch [id]            # run source adapters for detected items
scrolls md [id]               # render fetched items as Markdown scrolls
scrolls media [id]            # download uncaptured media into media/
```

Follow feeds (live deltas):

```text
scrolls follow [url]          # subscribe to an RSS/Atom feed, or list subscriptions
scrolls sync [id]             # register new items from followed feeds
scrolls unfollow <id>         # remove a subscription
```

Classify:

```text
scrolls classify [id]         # rules engine; --engine llm adds category/domain/concepts
scrolls set <id> key=val ...  # set classification fields by hand
```

Browse & search:

```text
scrolls search <query>        # BM25-ranked full-text search
scrolls list                  # filtered listing (--source/--stage/--category/--tag/--drift …)
scrolls show <id>             # one item in full
scrolls facets [dimension]    # the filterable vocabulary with counts
scrolls related <id>          # items connected to one item, with reasons
scrolls graph                 # the whole-library link graph
scrolls works [ref]           # scholarly works clustered by DOI
scrolls context <query>       # compact Markdown context bundle for agents
```

Custody & integrity:

```text
scrolls verify [id|--all| …]  # re-capture held items, record drift/rot events
scrolls history <id>          # an item's custody-ledger timeline
scrolls reconcile <id>        # resolve a recorded import conflict (--keep-held)
scrolls archive list          # the accept-incoming recovery index
scrolls archive show <id>     # recover a prior capture as re-importable JSONL
scrolls archive restore <id>  # restore a specific archived prior in place
scrolls archive diff <id>     # compare the held copy against an archived prior
scrolls archive prune         # bound the recovery store by a retention policy
scrolls doctor                # integrity audit; --fix repairs what's safe offline
scrolls maintain              # one scheduled custody pass (recheck → regen → audit)
```

Import / export (lossless round-trip):

```text
scrolls import fieldtheory        # X bookmarks from a Field Theory archive
scrolls import google-takeout <p> # YouTube watch history from a Google Takeout export
scrolls import bookmarks <p>      # a browser bookmarks HTML export
scrolls import pocket <p>         # a Pocket CSV export
scrolls import opml <p>           # feed subscriptions from an OPML file
scrolls import items <p>          # restore items from a JSONL export
scrolls import events <p>         # restore the verify ledger
scrolls import archive <p>        # restore the prior-content recovery store
scrolls import bundle <p>         # restore scrolls + custody ledger from a bundle
scrolls export items              # lossless JSONL of every item (full backup)
scrolls export events             # the verify ledger as JSONL
scrolls export archive            # the prior-content recovery store as JSONL
scrolls export bundle "<query>"   # scoped, shareable, re-importable custody bundle
scrolls export opml               # feed subscriptions as OPML
scrolls export bookmarks          # items as a Netscape bookmark file
```

Compile & serve:

```text
scrolls kb                    # compile the interlinked library pages
scrolls agent install         # write agent instruction files
scrolls mcp                   # serve the library to MCP clients over stdio
scrolls rm <id-or-url> ...    # remove items and the files they own
```

## Sources & adapters

Each item is captured through a source-specific adapter. Scrolls ships adapters for
Wikipedia/Wikidata, general web articles, YouTube, GitHub (repos + issues/PRs),
GitLab/Gitea/Bitbucket, arXiv/bioRxiv/medRxiv, PDFs, Hacker News, Stack Exchange,
Lobsters, the package registries (PyPI, npm, crates.io, Packagist, RubyGems, Go,
Hex, pub.dev, NuGet, Hackage, Maven), DOI resolution (Crossref → DataCite →
content-negotiation), the Fediverse (Mastodon and forks, Misskey, Lemmy/PieFed) and
Bluesky, Discourse forums, Dev.to, RFCs, Open Library, and Zenodo.

Adapters are commodity capture mechanisms; a new one is justified only when it
exercises a genuinely new *custody shape*. The full catalog — what each adapter
captures, its identity rules, and its fidelity boundary — is in
**[`docs/adapters.md`](docs/adapters.md)**; the adapter *contract* and how to add
one is in [`docs/architecture.md`](docs/architecture.md).

## Custody model

- **Fidelity tiers.** Every scroll declares how much is held: `full` (a re-derivable
  body is preserved), `partial` (degraded but honest), or `reference` (pointer +
  provenance only). Fidelity is a queryable facet.
- **Drift is an event, not an overwrite.** `scrolls verify` re-captures a held item
  and records `unchanged` / `drifted` / `rotted` / `error` into an append-only
  ledger — the original capture is never clobbered. `scrolls history` reads the
  timeline back per item.
- **Integrity is reported, not asserted.** `scrolls doctor` carries a `custody`
  block: a percent-clean score, per-item findings, drift aggregates, and a
  whole-library **posture** verdict (`sound` / `attention` / `at_risk`).
- **Custody travels with results.** Every browse row, related hit, and graph node
  (CLI + MCP) carries the item's fidelity, drift posture, and `last_checked` inline.
- **Custody is portable.** `scrolls export bundle` carries the in-scope items'
  verify ledger and prior-content archive; `import bundle` restores them, deduped —
  so a recipient inherits the drift *history*, not just a frozen snapshot.

The operative north star is **[`docs/vision.md`](docs/vision.md)**;
reconciliation and conflict mechanics are in
[`docs/reconciliation.md`](docs/reconciliation.md).

## Library layout

```text
~/.scrolls/        # or $SCROLLS_HOME
  db.sqlite       # canonical index: items + subscriptions + concept_summaries, FTS5 search, schema meta
  scrolls/        # individual Markdown files, one per item, per source
  library/        # compiled interlinked KB (index, graph, works, sources, categories, concepts, tags)
  agents/         # generated agent instruction files (SKILL.md, AGENTS.md)
  items/          # reserved (the raw record export is `scrolls export items`, to stdout)
  media/          # captured media files (PDFs, thumbnails, photos), per source
  config.toml     # settings; today: [classify] default_engine + llm_model
```

The on-disk format — scroll frontmatter and body, compiled `library/` pages, agent
files, and what a consumer may rely on — is specified in
[`docs/library-format.md`](docs/library-format.md).

## Design principles

- Custody first: hold faithfully, prove capture, surface drift, export losslessly.
- Raw is sacred; every derived view is rebuildable from raw + index.
- Markdown scrolls are the durable artifact; SQLite is a fast, rebuildable index.
- Classification works with or without an LLM; provenance is explicit for every item.
- The agent contract is the integrity boundary — identical semantics across CLI, MCP,
  facets, and compiled pages.
- Useful from the shell, coding agents, and Hermes skills.

## Documentation

Reading order (see [`AGENTS.md`](AGENTS.md) for the contributor guide):

1. [`docs/architecture.md`](docs/architecture.md) — pipeline, data model, module map, adapter contract.
2. [`docs/cli.md`](docs/cli.md) — CLI JSON/output contract, exit codes, error envelopes.
3. [`docs/library-format.md`](docs/library-format.md) — scroll, `library/`, agent-doc, and media artifacts.
4. [`docs/adapters.md`](docs/adapters.md) — the source-adapter catalog.
5. [`docs/vision.md`](docs/vision.md) — the operative north star (custody-first).
6. [`docs/reconciliation.md`](docs/reconciliation.md) — reconciliation and custody-conflict design.
7. [`docs/adr/README.md`](docs/adr/README.md) — the decision records behind the implementation.
8. [`docs/product/prd.md`](docs/product/prd.md), [`docs/product/mvp.md`](docs/product/mvp.md) — product direction and scope.
9. [`docs/dogfood.md`](docs/dogfood.md) — the end-to-end *hold → prove → detect → take-it-with-me* workflow.

## Status

Early but substantial. Stack: Python ≥3.11 managed with
[uv](https://docs.astral.sh/uv/) (see
[`docs/adr/0001-implementation-stack.md`](docs/adr/0001-implementation-stack.md)).
Item stages are `detected → fetched → rendered`; classification, media capture, and
KB compilation are stage-neutral. The rules + LLM classification stack, feed-based
sync, the deterministic KB compiler and LLM concept engine, the custody subsystem
(verify ledger, drift audit, posture, conflict/reconcile, portable bundles), and the
MCP server all have working implementations on both the shell and MCP surfaces.

```bash
uv run scrolls init      # create the library skeleton (idempotent)
uv run scrolls status    # initialized? schema? item/stage/source counts + custody headline
uv run pytest            # test suite
```
