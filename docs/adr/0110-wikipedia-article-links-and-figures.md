# ADR 0110: A saved Wikipedia article is its prose, its link graph, and its figures

Date: 2026-08-18

Status: accepted

Amends: [0002](0002-first-fetch-adapter-wikipedia.md)

## Context

ADR 0109 shipped the reading-lists on-ramp, which enumerates saved articles
and leaves capture to the ADR 0002 fetch adapter. Running it against a real
account exposed what that adapter actually keeps.

**It kept prose and nothing else.** Every fetched Wikipedia item held
`links == []` and `media == []`. For a single `scrolls add` of one article
that was easy to miss. For a 566-article library pulled from a user's reading
lists — the user's own description: *"I use the reading list to bookmark
articles I find useful"* — it is the difference between a knowledgebase and a
pile of disconnected text files.

**The link graph is the part a library has that a page does not.** Scrolls
already resolves an item's `links` into edges (`graph.py`), so an article
linking to another saved article is an edge waiting to be drawn. Capturing
zero links meant a 566-article library had a graph with no Wikipedia in it at
all, and the wiki's most useful property — what connects to what — was the one
thing thrown away.

## Decision

The Wikipedia adapter captures an article's **outbound links** and its
**figures** alongside the prose.

### Links

- **Mainspace links become wiki URLs** (`prop=links`, `plnamespace=0`), minted
  through the same encoder the reading-lists collection uses. One encoder, so
  a link captured from an article and an entry pulled from a list are spelled
  identically and resolve to the same item.
- **External links follow them** (`prop=extlinks`). On a Wikipedia article
  these are the citations, which is exactly what a knowledgebase should keep.
- **Backlinks are answered from the library, not from Wikipedia.** MediaWiki's
  own `list=backlinks` would return thousands of pages, almost all unsaved.
  Within a library the useful backlink is "which of *my* articles point here",
  and that falls out of the existing graph once outbound links exist.
- **Deduped, first occurrence wins order.**

### Figures

- **A second request is required.** `generator=images` replaces the page set,
  so it cannot ride along with the article query. This amends 0002's "one GET"
  property, which no longer holds.
- **The request is best-effort.** A failed figure list returns no media rather
  than raising. Losing a diagram must never cost 26,000 characters of article.
- **Editorial furniture is filtered by name.** MediaWiki lists every file a
  page renders, so `Commons-logo`, `Edit-clear`, the ambox maintenance banners
  and the OOjs UI icons arrive mixed in with the real figures — on
  *Dihydrocodeine*, six of ten files were chrome. `_CHROME_PATTERNS` matches
  them by substring. This is a heuristic over a slow-moving set, not a
  guarantee: a new icon leaks through as a media ref until its pattern is
  added, and that is stated where the code lives.

### What is captured, at what size

- **Analytics parameters are stripped.** Wikimedia appends
  `utm_source`/`utm_campaign`/`utm_content` to every `imageinfo` URL. They
  describe the API call, not the file; left in place, two captures of one
  image would differ by a campaign tag.
- **Rasters wider than 1600px are captured at MediaWiki's 1280px thumbnail**,
  with the full-resolution address kept on the ref as `original_url`. A
  3857px press photo is not more useful to an agent than a 1280px one, and
  costs an order of magnitude more disk. Recording what was passed over is
  what makes the choice custody rather than loss.
- **Smaller files keep their original**, because thumbnailing is not
  uniformly a win: a vector diagram's "thumbnail" is a rasterization both
  larger *and* lossier than the SVG it came from.

### Links reach disk

`links` joins the scroll frontmatter beside `media`, under the same omission
rule. Captured-but-unrendered meant the edges lived only in SQLite while the
scroll — the durable artifact — showed none of them.

## Consequences

- **Verified against live Wikipedia on 2026-08-18**, over the 566 articles of
  a real reading-list library: 566 fetched, 0 failures, 15 MB of prose,
  222,895 links and 5,416 figure refs, of which 1,383 were capped photos.
- **Media capture is now the expensive step.** Text is 15 MB; the figures are
  roughly 1.5 GB. `scrolls media` stays a separate opt-in command, so a user
  who wants the knowledgebase without the pictures simply does not run it.
- **The chrome filter is a maintenance surface**, in the same family as X's
  rotating query id: it works, and when Wikipedia adds an icon the fix is one
  pattern.
- **Deferred: inline link anchors.** `explaintext` returns prose with link
  markup stripped, so links are captured as a list rather than positioned
  within the text. Recovering anchor positions needs the wikitext or HTML, a
  different capture entirely.
