# 0075: Wikidata adapter — structured knowledge, the Wikipedia sibling

Date: 2026-06-13

Status: accepted

## Context

The Wikipedia adapter (ADR 0002) was the first real fetch adapter: one keyless
GET against the MediaWiki API turns a saved article URL into a clean scroll, its
editor-curated page categories becoming `concepts`. But Wikipedia has a
structured-data sibling that had no home. [Wikidata](https://www.wikidata.org) is
the Wikimedia knowledge graph — the same world Wikipedia describes in prose,
modeled as **entities** (`Q<digits>`): each a node with multilingual labels and
descriptions, typed statements (`P31` *instance of*, `P279` *subclass of*, `P18`
*image*, `P856` *official website*, …), and **sitelinks** back to the Wikipedia
articles about it.

A saved `wikidata.org/wiki/Q42` link fell through to the `web` adapter, which
scrapes the JS-rendered entity page — producing some text but none of the
structured signal Wikidata publishes, and crucially no `concepts` and no edge to
the Wikipedia article it describes. The entity became a concept-less, unlinked
island: the exact gap dev.to had before ADR 0061, standards before ADR 0066, and
books before ADR 0073. Wikidata's entity data is served keyless with no key and no
runtime dependency (the arXiv/Crossref/Open Library discipline,
ADR 0008/0037/0073), so the fix is a dedicated adapter — the structured twin of
the very first one.

## Decision

Add a `wikidata` source (host-claimed on `wikidata.org`/`www.`/`m.`) and a
keyless fetch adapter (`sources/wikidata.py`).

- **Only Q items are claimed; the QID is the identity.** A `/wiki/Q42`,
  `/entity/Q42` (the RDF concept URI, including its bare `http` form), or
  `/wiki/Special:EntityData/Q42.json` URL all detect to `wikidata:Q42` — the id is
  the first path segment that *is* a QID (a trailing extension stripped), which
  covers every route without enumerating them; on `wikidata.org` a `/wiki/Q<n>`
  title is always entity Q<n>. The QID is uppercased to its canonical form (routes
  are case-insensitive, the crates/Open Library fold — ADR 0036/0073), so
  `/wiki/q42` and `/entity/Q42` dedupe. Properties (`Property:P…`) and Lexemes
  (`Lexeme:L…`) are deferred — they are schema/meta entities, not the "things" a
  knowledge library saves — and the project/portal/home pages carry no Q item (the
  github profile-page pattern).

- **The type relations are the concepts.** An entity's `P31` (*instance of*) and
  `P279` (*subclass of*) statements place it in Wikidata's ontology — the
  structured "what kind of thing is this" signal, the direct analog of the
  Wikipedia adapter's page categories → `concepts` (ADR 0002) and of github
  topics / MeSH / Open Library subjects (ADR 0007/0065/0073). Their values are
  QIDs (`Q5`, not "human"), so they are resolved to labels with **one batched**
  `wbgetentities&props=labels` request — the Open Library author-key resolution
  (ADR 0073) economized into a single call however many types an entity carries.
  Labels are deduped case-insensitively (`P31` before `P279`), capped, and a
  failed resolution degrades to no concepts rather than failing the fetch. Richer
  property-specific concepts (occupation `P106`, field of work `P101`, genre
  `P136`) are deferred to keep the property set principled and bounded — the type
  hierarchy is the one universal, ontological signal.

- **The label is the title, the description is the summary; no full text.**
  Wikidata stores no prose body, so a scroll is honestly summary-only with **no
  `extracted_text`** (the Crossref/PubMed/Open Library metadata-only shape,
  ADR 0037/0065/0073). Labels/descriptions are per-language: the title prefers the
  English label then the script-agnostic **`mul`** label Wikidata now mints for
  names that read alike across languages — so `Q42`'s "Douglas Adams", stored under
  `mul` with *no* `en` label, is still found — then any `en-*` variant, then any
  value. `tags` stay empty by design (no clean controlled facet — the
  go/rubygems/Open Library posture, ADR 0042/0040/0073).

- **The sitelinks are cross-source edges.** The English Wikipedia sitelink becomes
  an `en.wikipedia.org/wiki/<Title>` `link` (spaces → underscores, the canonical
  form the detector reads back) — the **Wikidata↔Wikipedia edge**
  `scrolls related`/`graph` resolves to the saved Wikipedia scroll for the same
  subject (the model↔paper / edition↔work edge of ADR 0041/0073). The official
  website (`P856`) is an outbound `link` too; the representative image (`P18`, a
  Commons filename) becomes a `thumbnail` on `commons.wikimedia.org/wiki/Special:
  FilePath/<file>` (the Open Library cover convention, ADR 0073/0011).
  Other-language sitelinks are deferred to keep `links` bounded — a popular entity
  carries 200+.

- **`reference` category, and a slim `raw_text`.** A Wikidata entity is an
  encyclopedic entry to consult, so it classifies as `reference` like the
  Wikipedia article about it (the classify curated rule) — the honest default
  Wikidata's uniform "structured fact" nature allows, unlike Open Library's
  fiction/non-fiction split (ADR 0073). Because an entity can be hundreds of KB
  (every language's label, hundreds of sitelinks), `raw_text` keeps only the
  projection the adapter consumed — the en/`mul` labels and descriptions, the four
  read claim properties, and the English sitelink — so the index stays lean while
  still rebuildable.

## Consequences

- **Wikidata entities join the library as first-class scrolls, wired to
  Wikipedia.** A saved entity now contributes its type hierarchy to the concept
  graph, dedupes its `/wiki`, `/entity`, and case-variant URLs onto one id, and
  links to the Wikipedia article about it — `test_wikidata.py` covers the
  type-relations-as-concepts resolution, the en→`mul` label fallback, the
  case-insensitive concept dedupe, the resolution-degrades path, the `somevalue`
  skip, the slim `raw_text` projection, the redirected-entity id, and the
  `reference` classification, all offline against trimmed fixtures (ADR 0001). A
  live smoke test confirmed a person (`Q42`), a concept (`Q11660`), and a city
  (`Q90`) ingest cleanly, that all three URL forms dedupe, and that
  `scrolls related wikidata:Q42` resolves the Wikidata↔Wikipedia edge to the saved
  Douglas Adams article.

- **The structured twin of the first adapter.** Where the Wikipedia adapter reads
  an article's prose and its categories, the Wikidata adapter reads an entity's
  facts and its ontology — two views of one subject, now joined by the sitelink
  edge. This also gives ADR 0073's deferred book `identifiers` enrichment a target:
  an Open Library work's Wikidata `identifiers` value would link a book to its
  entity here.

- **Deferred.** Properties and Lexemes (schema/meta entities); property-specific
  concepts beyond the type hierarchy (occupation, field of work, genre); the full
  multilingual sitelink set as edges; and reading `P18`-class media for more than
  the one representative image are all left for later. This ADR adds the adapter
  for Q items, not the whole Wikibase data model.
