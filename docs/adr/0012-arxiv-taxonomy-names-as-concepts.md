# ADR 0012: arXiv taxonomy display names become concepts via a bundled table

- Status: accepted
- Date: 2026-06-12
- Deciders: autonomous agent (per project decision posture in `CLAUDE.md`)

## Context

ADR 0008 put arXiv taxonomy codes (`cs.CL`) in `tags` and deliberately
deferred mapping them to human-readable names, leaving papers out of the
KB's concept pages — github topics (ADR 0007) and wikipedia categories
were the only concept producers. The codes are curated, stable, and
already fetched; only the code → name mapping was missing.

## Decision

1. **Bundle the mapping as a generated table** —
   `src/scrolls/sources/arxiv_taxonomy.py`, 155 entries captured from
   <https://arxiv.org/category_taxonomy> on 2026-06-12. The taxonomy
   changes rarely (last reorganization 2017); a static table costs no
   network call at fetch time and keeps tests offline. Regenerate with
   the script below when arXiv adds categories.
2. **Display names go to `concepts`, codes stay in `tags`.** A search
   for `cs.CL` and a search for "Computation and Language" should both
   work, and `related`'s shared-tag and shared-concept signals stay
   distinct.
3. **Names are used verbatim.** Collisions are features: `cs.LG` and
   `stat.ML` both display as "Machine Learning" and merge into one
   concept (deduped at fetch, merged by slug in the KB like any other
   spelling collision). Accepted nit: a few names are generic outside
   their group ("Computation" for `stat.CO`); they are rare in practice
   and harmless as concept pages.
4. **Unknown codes produce no concept.** Pre-2007 archive names
   (`cmp-lg`, `alg-geom`) stay tags-only rather than guessing.

## Consequences

- arXiv papers join the concept graph: KB concept pages and
  `scrolls related`'s shared-concept signal now connect papers to each
  other and to github/wikipedia items (`tests/test_arxiv.py`,
  `test_ingest_arxiv_paper_end_to_end`).
- ADR 0008's "no concepts from codes" choice is superseded by this
  record; its abstract-as-summary and tags decisions stand.
- Regeneration script (network):

  ```python
  import re, urllib.request
  req = urllib.request.Request(
      "https://arxiv.org/category_taxonomy",
      headers={"User-Agent": "scrolls-dev (taxonomy table generation)"},
  )
  html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
  pairs = re.findall(
      r"<h4>\s*([a-z-]+(?:\.[A-Za-z-]+)?)\s*<span>\(([^)]+)\)</span>", html
  )
  # emit CATEGORY_NAMES entries from `pairs`, update the captured date
  ```
