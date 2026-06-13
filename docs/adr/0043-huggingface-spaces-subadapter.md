# 0043: Hugging Face Spaces as a third repo kind on the Hub adapter

Date: 2026-06-13

Status: accepted

## Context

ADR 0041 built one Hugging Face adapter for two repo kinds — models and
datasets — with the kind riding in the source id (`model:<id>` /
`dataset:<id>`, the Stack Exchange one-adapter-many-kinds shape, ADR 0033)
and `detect_source` picking it off the URL. It deliberately left Spaces
(`huggingface.co/spaces/<org>/<name>`) as a reserved path: registered as a
`huggingface` item but with no fetchable repo, so a saved Space fell
through to the generic `web` adapter and a `trafilatura` scrape of a
JS-rendered page. Spaces are the third first-class Hub repo kind — hosted
ML demos and apps (Gradio, Streamlit, Docker, static) — and they are
exactly the kind of artifact a developer saves, so closing the gap is the
natural next slice on the freshest adapter.

Three facts shaped the extension, confirmed against the live Hub API
(`/api/spaces/HuggingFaceH4/zephyr-chat`) before committing:

1. **A Space is the same adapter shape with a different endpoint.** The
   `/api/spaces/<id>` document mirrors the model/dataset response — `id`,
   `author`, `createdAt`, `tags`, `cardData` — and the card lives at the
   same `<repo>/raw/main/README.md` path, frontmatter and all. So Spaces
   slot into the existing routing (a `_PATH_SEGMENT` map keyed by kind)
   with no new transport: the kind picks the API endpoint, the site
   prefix, and the card URL.

2. **A Space's structured fields differ in two named ways.** It has no
   `pipeline_tag`/`task_categories` (so `concepts` come from
   `cardData.tags` alone, the github-topics parallel), and its framework
   facet is the `sdk` (`gradio`/`streamlit`/`docker`/`static`) rather than
   a model's `library_name` — the runtime that hosts the demo. The `sdk`
   fills the same `tags` slot `library_name` fills for a model. A Space's
   human name is its card `title` (the repo id is a slug like
   `org/cool-demo`), the analog of a dataset's `pretty_name`.

3. **A Space declares the repos it runs — a new edge for free.** A Space
   card's `cardData.models` and `cardData.datasets` list the model(s) it
   serves and the dataset(s) it draws on. These become space↔model and
   space↔dataset links that `scrolls related` resolves to the saved repos
   through the same source detection ADR 0041 used for the model↔paper and
   model↔dataset edges — a saved demo wiring to the model behind it
   (verified live: `space:HuggingFaceH4/zephyr-chat` relates to
   `model:HuggingFaceH4/zephyr-7b-beta` with reason "links to it").

## Decision

The Hugging Face adapter (`src/scrolls/sources/huggingface.py`) gains a
third repo kind, `space`:

- **Detection.** `detect_source` adds a `spaces/<org>/<name>` branch
  yielding `space:<org>/<name>` (the dataset branch's twin, with subpage
  dedupe to the two-segment repo); `spaces` leaves the reserved-path set's
  dead end (`src/scrolls/sources/detect.py`, `tests/test_detect.py`).
- **Routing by a kind→segment map.** A `_PATH_SEGMENT` dict
  (`model→models`, `dataset→datasets`, `space→spaces`) drives the API
  endpoint, the site prefix (`_site_prefix`, empty for a model at the host
  root), and the card URL — replacing the two-way `if kind == "dataset"`
  ternaries with one table that the kind validity check (`_parse_source_id`)
  also reads.
- **Field mapping.** The `sdk` fills the `tags` facet for a Space (the
  `library_name` slot for a model); `cardData.title` is the title (the
  `pretty_name` slot for a dataset); `concepts` come from `cardData.tags`;
  and `cardData.models`/`cardData.datasets` become the space↔model and
  space↔dataset links, appended to the flat-tag cross-references the
  models/datasets already mine. Model and dataset behavior is byte-for-byte
  unchanged — the space branches are additive.
- **Classification.** A Space joins a model as a curated `tool` (a hosted
  artifact you use, like a package or a model), distinct from a dataset's
  `dataset` (`src/scrolls/classify.py`, ADR 0004).
- **Degradation.** A Space with no card degrades to a metadata-only scroll
  (ADR 0002), but the space↔model/dataset edges survive because they come
  from `cardData` (in the API response), not the card body — so even a
  card-less demo keeps its most useful graph edges.

Per the no-network rule (ADR 0001), both GETs stay injected; tests run
against a recorded Space document and card (`tests/test_huggingface.py`),
and the decision was smoke-tested end to end against the live Hub
(`HuggingFaceH4/zephyr-chat`, including the space↔model edge).

## Consequences

- A saved Hugging Face Space becomes a clean scroll — its card title, the
  card prose as searchable content, the `sdk`+license tags, and the
  model/dataset edges — instead of a `trafilatura` scrape. The Hub adapter
  now covers all three first-class repo kinds; `x` (Field Theory import
  only, ADR 0009) remains the sole detected source with no fetch adapter.
- The space↔model/dataset edges deepen the graph in the direction ADR 0041
  established: a saved demo, the model it serves, and the dataset it draws
  on now interlink in `scrolls related` and on the KB concept pages.
- The `_PATH_SEGMENT` refactor leaves the adapter ready for any further
  Hub kind on the same `/api/<segment>/<id>` shape with one table entry
  and a detection branch, no new transport.
- The reserved-path table (`HUGGINGFACE_RESERVED`) keeps `spaces` for
  documentation, but the dedicated branch claims it first — the dataset
  precedent, now matched in code to the comment ADR 0041 wrote ahead of
  it.
