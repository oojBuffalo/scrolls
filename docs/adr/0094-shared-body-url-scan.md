# 0094: One shared grammar for body-URL edges

Date: 2026-06-15

Status: accepted

## Context

Sources whose content is free text rather than structured metadata read their
outbound links straight out of that text: a code host's issue/PR thread
description (github/gitlab/gitea/bitbucket, ADR 0084–0087) and a Fediverse
post's body (misskey, lemmy, piefed, ADR 0051–0053) both carry cross-references
to other issues, papers, and repos as bare URLs, and pulling them into `links`
is what wires the item to what it cites through `scrolls related`/`graph` (the
cross-source edges, ADR 0044).

Reading a URL out of prose is a small grammar with a known sharp edge, and all
seven adapters had copied it verbatim:

```python
_URL_RE = re.compile(r"https?://[^\s<>]+")
_URL_TRAILING = ".,;:!?\"')]}>"
...
for match in _URL_RE.finditer(body):
    url = match.group(0).rstrip(_URL_TRAILING)
    if url:
        ...
```

The regex captures a maximal `http(s)` run stopping at whitespace or an angle
bracket; the `rstrip` then removes the trailing punctuation a scan over prose
over-captures — the period ending a sentence, the `)` closing a Markdown/MFM
inline link. The four code hosts wrapped that scan in an identical second
shape: seed the item's `links` with the one repo/project edge, then append the
body URLs, deduped and never self-linking the thread. The grammar and the
code-host wrapper were each one decision expressed seven and four times — a
thirteenth thread adapter would copy them again, and tightening the trailing
set (or fixing the glued inline-link over-capture) meant editing every copy.

This is the same duplication ADR 0093 removed from the *rendering* tail of the
same adapter family; the link scan is its twin on the *extraction* side.

## Decision

Move the grammar into `src/scrolls/sources/urls.py` — the module that already
owns URL identity (`normalize_url`, ADR 0023) — as two functions:

- `scan_urls(text)` — the primitive: the `http(s)` URLs in free text, trailing
  punctuation trimmed, in first-seen order, no dedupe, `[]` for a non-string
  input (the `.get()` an adapter passes may be `None`). The three Fediverse
  adapters' `_content_links` now delegate to it, keeping only their one-line
  per-source rationale (Misskey has no facet list; a Lemmy/PieFed body is
  Markdown).
- `body_edge_links(seed, self_url, body)` — the code-host wrapper: the `seed`
  edge followed by `scan_urls(body)`, deduped and self-excluded. The four code
  hosts' `_issue_links`/`_thread_links` now return this with only the two facts
  that legitimately differ per host — the seed link (`github.com/<repo>`,
  `gitlab.com/<project>`, gitea's per-instance `<host>/<repo>`) and which field
  holds the thread's own URL.

The split mirrors ADR 0093 and ADR 0002: a shared module owns the grammar every
adapter copied, each adapter keeps the source-specific facts (the seed, the
self URL, why links come from text), and the call sites are unchanged.

## Consequences

- The body-URL grammar lives in one place. The known over-capture — a glued
  inline-link run the regex swallows whole, today a benign missed edge —
  becomes a single fix behind a stable call site if it is ever worth making,
  landing for every thread and Fediverse source at once.
- Behavior-preserving by construction: every per-adapter link test
  (`tests/test_github.py`, `test_gitlab.py`, `test_lemmy.py`, `test_misskey.py`,
  …) passes unchanged, pinning byte-identical `links`; `tests/test_urls.py`
  covers `scan_urls` (ordering, trailing trim, angle-bracket stop, no dedupe,
  non-string input) and `body_edge_links` (seed-first, self-exclusion,
  dedupe) directly.
- The next text-bearing adapter calls `scan_urls`/`body_edge_links` instead of
  re-deriving the grammar — the consolidation the autonomous priority favors
  over one-off adapters, the extraction-side twin of ADR 0093's rendering-side
  one.
- Deliberately left for a future slice: the `_plain` CRLF/blank-run normalizer
  duplicated across the four code hosts plus lobsters and devto, and the
  paragraph-split `_text` shared by the three Fediverse adapters — the same
  shape of duplication, a separate behavior-preserving consolidation.
