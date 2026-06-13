# 0033: Stack Exchange via the keyless API; question + top answers, tags as concepts

Date: 2026-06-13

Status: accepted

## Context

Stack Overflow and the wider Stack Exchange network are among the most
common save targets a developer has — Scrolls' core audience (IDEAS.md
§11). Until now a `stackoverflow.com/questions/…` URL fell through to
the generic `web` adapter (ADR 0001), which runs `trafilatura` over the
HTML question page: it captures the question prose but mangles or drops
the code blocks and the answers, and the answers are where the knowledge
actually lives. Stack Exchange also publishes a stable, keyless JSON API
(`api.stackexchange.com/2.3`) returning the question, its answers, the
author-applied tags, scores, and dates as structured data, so a
dedicated adapter is both more faithful and cheaper than scraping.

Three facts about that API shaped the design. (1) It is one network of
~180 sites reached through a single `site` query parameter, so one
adapter can serve all of them if it knows each host's slug. (2) The
question and its answers are *separate* resources — `/questions/<id>`
and `/questions/<id>/answers` — so carrying the answers costs a second
request. (3) A nonexistent question is not an HTTP error; the API
answers `200` with an empty `items` list, and (verified) it returns
plain JSON when no `Accept-Encoding` is sent, so the shared
stdlib transport (`src/scrolls/sources/http.py`) needs no gzip handling.

## Decision

`scrolls add`/`fetch` of a Stack Exchange question runs a new keyless
adapter (`src/scrolls/sources/stackexchange.py`):

- **One adapter, the whole network; the site rides in `source_id`.**
  `detect_source` maps dedicated domains (`stackoverflow.com`,
  `superuser.com`, `serverfault.com`, `askubuntu.com`, `stackapps.com`,
  and `mathoverflow.net`, whose API slug literally keeps `.net`) through
  a table, and every `*.stackexchange.com` host to the label before
  `.stackexchange.com` — so `math.stackexchange.com` → `math` and
  `rpg.meta.stackexchange.com` → `rpg.meta`
  (`src/scrolls/sources/detect.py`). The `source_id` is `<site>:<id>`,
  so item ids are `stackexchange:stackoverflow:11227809` — the way
  Wikipedia encodes its language edition in `wikipedia:en:SQLite`
  (ADR 0002). The last colon splits site from id, so dotted slugs
  survive the round trip back to the fetch URL.
- **Detection claims the host, fetches only questions.** A question URL
  is `/questions/<id>/…` or the `/q/<id>` shortlink; tag pages, user
  pages, the site home, and `/a/<id>` answer permalinks carry no
  question id and become the source with no fetchable item — exactly
  github's and Hacker News's pattern (ADR 0007, ADR 0031), where the
  host is claimed but only some paths fetch. Resolving an answer
  permalink to its question is a deferred enrichment, not a `web` scrape.
- **The answer is the knowledge, so the scroll carries it — optionally.**
  The required first GET is the question; a second GET pulls the top
  answers by votes (`pagesize=5`). Answers are optional enrichment like
  github's README (ADR 0007): a question the API reports as having none
  skips the request, and an answers request that fails still produces a
  question-only scroll. `extraction_method` records which path ran
  (`stackexchange-api:question+answers` vs `…:question`). The body and
  answers are joined into `extracted_text` as a nested `### Top Answers`
  subsection, so the answer text becomes FTS-searchable, not just the
  question (`tests/test_stackexchange.py`).
- **The accepted answer leads, even when it isn't top-voted.** Answers
  arrive vote-sorted; a stable re-sort moves the `accepted_answer_id`
  first while keeping the rest in vote order, and each answer's byline
  records its author and score. The canonical solution is what an agent
  reads first.
- **Tags become `concepts`.** A question's tags — `python`,
  `branch-prediction` — are curated topical labels, identical in spirit
  to github repo topics, so they feed the KB concept pages the same way
  (ADR 0007, ADR 0012). They are not mirrored into `tags`, which stays
  the organizational field bookmarks-import folders write (ADR 0030).
- **`summary` leads with the question's first paragraph.** Like
  Wikipedia and Hacker News (ADR 0002, ADR 0031); a bodyless stub
  degrades to the honest status the API reports — `"Stack Exchange
  question: N votes, M answers."` (singular units handled) — and a stub
  with neither gets no summary rather than an invented one (the
  recurring honestly-empty posture, ADRs 0004, 0013).
- **HTML → text with stdlib, markup before entities.** SE post bodies
  are richer HTML than HN's: block tags (`<p>`, `<pre>`, headings,
  `<blockquote>`, tables) become paragraph breaks, `<li>` a bullet,
  `<br>` a newline, remaining inline tags are dropped, and only then are
  entities unescaped — so escaped angle brackets inside quoted code
  survive as literal text, and code blocks (whose newlines are already
  literal in the payload) keep their shape. No new dependency for a
  small tag grammar (ADR 0001).
- **Stack Exchange items default to `reference`, weakly.** A saved Q&A
  thread is used as a reference answer, so `stackexchange` is a weak
  source default in the rules engine (`src/scrolls/classify.py`,
  ADR 0004) — *not* a curated-source category like wikipedia→reference,
  because an explicit "how to …" title is genuinely a tutorial and the
  title rules (checked first) should win. The LLM engine (ADR 0015) can
  refine the rest.

Per the no-network rule (ADR 0001), both GETs are injected and tests run
against payloads recorded and trimmed from the live API
(`tests/test_stackexchange.py`).

## Consequences

- A saved Stack Overflow question becomes a clean scroll — title,
  author, date, tags-as-concepts, the question, and the accepted-first
  top answers — instead of a `trafilatura` scrape of the HTML page. The
  eighth keyless fetch adapter; `x` (Field Theory import only, ADR 0009)
  remains the sole detected source without one.
- The whole Stack Exchange network is covered by one adapter, so a
  bookmarked or feed-synced Math.SE, Super User, or MathOverflow
  question (ADR 0030, ADR 0017) enriches with no extra code — the same
  leverage Wikipedia's per-language coverage gets from one adapter.
- The second (answers) request makes this the second adapter to spend an
  optional follow-up GET (after github's README), and the per-question
  cost is two requests against the keyless 300/day/IP quota. Heavy bulk
  enrichment should pace with `scrolls fetch --limit N` (ADR 0029);
  an API key (raising the quota) is a future option, like
  `GITHUB_TOKEN` (ADR 0007), not needed for normal use.
- The raw question and answer objects are kept verbatim in `raw_text`,
  so a future enrichment (more answers, comment trees) can expand a
  thread without a refetch — the raw-record-spine discipline github,
  arxiv, and Hacker News already follow.
