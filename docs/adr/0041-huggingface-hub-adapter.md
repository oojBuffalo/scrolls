# 0041: Hugging Face Hub via the keyless API; one adapter for models and datasets, the arXiv tag as a cross-source link

Date: 2026-06-13

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) —
increasingly includes Hugging Face model and dataset pages. Until now a
`huggingface.co/<org>/<name>` URL fell through to the generic `web`
adapter (ADR 0001), which runs `trafilatura` over a heavily
JS-rendered page: it captures little of the structured metadata the Hub
already holds — the task, the library, the license, the datasets a model
trained on, the paper that introduced it. The Hub publishes a stable,
keyless JSON API (`huggingface.co/api/models|datasets/<id>`) returning all
of it, and a raw card endpoint (`<repo>/raw/main/README.md`) returning the
model/dataset card, so a dedicated adapter is both more faithful and
cheaper than scraping.

This is the ML-artifact sibling of the package-registry adapters (PyPI
0034, npm 0035, crates 0036, Packagist 0039, RubyGems 0040): the same
keyless-JSON shape, the same author-declared-keywords→concepts mapping.
Three facts distinguished its design, all confirmed by smoke-testing the
live API before committing — the discipline the prior adapter ADRs used.

1. **One host serves two repo kinds under different API endpoints.**
   Models live at `/api/models/<id>`, datasets at `/api/datasets/<id>`.
   Rather than mint two sources, the repo *kind* rides in the source id
   (`model:<org>/<name>`, `dataset:<org>/<name>`) the way the Stack
   Exchange site does (ADR 0033) — `detect_source` reads the kind off the
   URL, and the one adapter routes accordingly. A model is a `tool` (a
   published artifact you install and use, like a package); a dataset is a
   `dataset` — the term already in the IDEAS.md §8 vocabulary, the first
   rule to produce it.

2. **The Hub flattens every tag into one array, mostly auto-derived.** A
   repo's `tags` mixes genuine author intent (`exbert`) with machine noise
   (frameworks `pytorch`/`jax`, `region:us`, `endpoints_compatible`, file
   formats, size buckets). Mining that soup for concepts would flood the
   KB with `region:us`. So concepts/tags come from the *structured* fields
   instead — the task (`pipeline_tag` for models, `task_categories` for
   datasets) and the author's `cardData.tags` feed the concept graph (the
   github-topics parallel, ADR 0007); `library_name` and the `license`
   fill the `tags` facet slot. The flat array is read only for its
   cross-reference prefixes (below).

3. **The card is a separate raw fetch, and its summary beats the API's.**
   The searchable content — the model/dataset card — is not in the JSON;
   it is the repo's `README.md`, fetched raw and stripped of the leading
   YAML frontmatter (which is just `cardData` re-serialized). The card's
   first prose paragraph is the cleanest one-line `summary`. A dataset's
   API `description` field looked like a better summary source, but
   smoke-testing `rajpurkar/squad` live showed the Hub derives it crudely
   from the card — tabs, table-of-contents fragments, and a "See the full
   description…" suffix included — so the card lead paragraph wins for
   both kinds, and the `description` is only a whitespace-collapsed
   fallback when a repo has no card. (This is exactly the kind of bug live
   verification catches that a hand-written fixture would not.)

## Decision

`scrolls add`/`fetch` of a Hugging Face model or dataset runs a new
keyless adapter (`src/scrolls/sources/huggingface.py`):

- **One source, the repo kind in the source id.** `detect_source` claims
  `huggingface.co`/`www.huggingface.co` and the short `hf.co`, and a model
  URL (`<org>/<name>`, the github two-segment rule) yields
  `huggingface:model:<org>/<name>` while a `datasets/<...>` URL yields
  `huggingface:dataset:<...>` (`src/scrolls/sources/detect.py`,
  `tests/test_detect.py`). Repo subpages (`/tree/main`, `/blob/…`) dedupe
  to the repo by taking only the first two segments — the pypi
  version-page rule. Ids are kept **verbatim**: the Hub is case-sensitive,
  so this is npm's/github's rule (ADR 0035), not the case-folding PyPI
  applies. Site routes (`docs`, `blog`, `models`, …, via a reserved-path
  table like github's), `spaces` (no adapter yet), and a bare `<org>`
  profile carry no fetchable repo and become the source with no item — the
  family's pattern.
- **Fetch routes on the kind and fetches the card second.** The adapter
  GETs `/api/{models,datasets}/<id>`, reads the canonical `id` back for
  the title/URLs, then GETs the card README. A missing card, a 404, or any
  transient failure degrades to a metadata-only scroll (ADR 0002), the
  `extraction_method` recording whether the card was captured
  (`huggingface-api:json+card` vs `…:json`).
- **Concepts from the structured fields, not the flat tags.** Model
  concepts are `pipeline_tag` + `cardData.tags`; dataset concepts are
  `task_categories` + `task_ids` + `cardData.tags` — author-declared,
  deduped, the github-topics parallel. The flat `tags` array is
  deliberately not mined, so the concept graph stays clean.
- **`tags` are the framework + license facets.** `library_name`
  (`transformers`, `diffusers`; models only) and the `cardData.license`
  fill the structured-facet slot PyPI's classifiers and SPDX licenses fill
  elsewhere.
- **The flat tag array's cross-reference prefixes become links — the
  headline edges.** An `arxiv:<id>` tag becomes a
  `https://arxiv.org/abs/<id>` link, which `scrolls related` resolves to
  the saved `arxiv:<id>` item (verified live: `bert-base-uncased` →
  `arxiv:1810.04805`). This is the model↔paper edge, kin to ADR 0038's
  arXiv preprint↔published-DOI edge — a saved model wires to the paper
  that introduced it with no new edge type. A `dataset:<name>` tag becomes
  the dataset's Hub page (the model↔dataset edge, verified: `bert` →
  `huggingface:dataset:bookcorpus`). And a `base_model:<id>` tag becomes
  the base model's Hub page (the model↔base-model lineage edge): the Hub
  emits it both bare and with a relation (`base_model:meta-llama/Llama-3.1-8B`
  *and* `base_model:finetune:meta-llama/Llama-3.1-8B`), so the id is the
  segment after the last colon and the deduped link is one — a relation-only
  fragment with no `<org>/<name>` is dropped.
- **The card is the content; its lead paragraph is the summary.** The raw
  README with its YAML frontmatter stripped is the `extracted_text`; its
  first prose paragraph (headings, badges, tables, and TOC lists skipped,
  soft-wraps collapsed) is the `summary`, with a dataset's
  whitespace-collapsed `description` as the only fallback.
- **Title, author, date.** Title is the canonical repo id, except a
  dataset prefers its human `cardData.pretty_name` ("SQuAD"). Author is the
  `author` namespace. `published_at` is `createdAt` (the repo's
  publication, not the noisier `lastModified`), through the shared
  `to_utc_iso` (ADR 0024) with the feed/import seed as fallback.
- **A model classifies as `tool`, a dataset as `dataset`.** The rules
  engine special-cases `huggingface` on the source-id prefix
  (`src/scrolls/classify.py`, ADR 0004): `model:` → `tool` (a published
  artifact you use, joining the package registries), `dataset:` → `dataset`
  (the IDEAS.md §8 term). A huggingface item that is neither — a profile
  page registered but never fetched — has no inherent category and falls
  through honestly.

Per the no-network rule (ADR 0001), both the JSON GET and the card GET are
injected; tests run against a recorded model document, dataset document,
and card README (`tests/test_huggingface.py`), and the decision was
smoke-tested end to end against the live API (`bert-base-uncased`,
`rajpurkar/squad`, and the model→paper and model→dataset `related` edges).

## Consequences

- A saved Hugging Face model or dataset becomes a clean scroll — title,
  author, publish date, the card as searchable text, the task and card
  tags as concepts, the library/license as tags, and the arXiv/dataset
  cross-source links — instead of a `trafilatura` scrape of a JS page. The
  fifteenth keyless fetch adapter; `x` (Field Theory import only, ADR 0009)
  remains the sole detected source without one.
- The model↔paper edge connects Scrolls' two literature halves to its ML
  artifacts: a saved model, its arXiv preprint (ADR 0008), and that
  preprint's published Crossref version (ADR 0037, 0038) now form one
  chain in `scrolls related`, no LLM involved.
- One adapter spanning two repo kinds keeps `detect.py` and
  `FETCH_ADAPTERS` small (the Stack Exchange lesson, ADR 0033) at the cost
  of a kind-prefixed source id and a kind branch in three functions — the
  right trade for two endpoints that share a host, an auth story, and a
  card convention.
- Choosing structured fields over the flat tag array is the adapter's
  defining judgment: it keeps the concept graph free of `region:us` noise
  at the cost of dropping a few genuine bare tags (`bert`). The full,
  curated metadata subset stays in `raw_text`, so a future enrichment —
  mining select flat tags, an HF-minted `doi:` link — can expand a repo
  without a refetch.
- `spaces` register but do not fetch: a Space is an app, not a knowledge
  artifact, and its metadata API differs. It is the obvious next slice on
  this host if demand appears.
- Go modules remain the last obvious *package* registry on the
  JSON-metadata pattern (the `proxy.golang.org` endpoints, ADR 0040); the
  Hub adapter shows the same pattern generalizes cleanly beyond package
  registries to any keyless metadata API with author-declared tags.
