# ADR 0111: Math in a scroll body is KaTeX, normalized at render time

Date: 2026-08-19

Status: accepted

Amends: [0110](0110-wikipedia-article-links-and-figures.md)

## Context

ADR 0110 deepened the Wikipedia capture to prose, links, and figures, and the
566-article library it produced is what exposed the next gap. The user read one
of their own saved scrolls and said the logic symbols were *atrocious*.

**A quarter of the library was unreadable.** MediaWiki's `explaintext` extract
has no way to render a `<math>` tag, so it emits the MathML presentation
fallback — one symbol per indented line — and then the real TeX in a
`{\displaystyle …}` wrapper:

```text
      P
      →
      Q
    {\displaystyle P\to Q}
```

Both halves are content; only the second is *readable*. The library held
**8,280** of these across **142 of 566** scrolls. `binary-relation.md` alone
had 522. On `modus-ponens.md` a single sentence about algebraic semantics
spanned roughly 280 lines of token soup.

**This is not a Wikipedia problem wearing a Wikipedia hat.** The repo's purpose
is an agent-readable knowledgebase that a human can also interact with. A
formula that renders as a column of loose glyphs fails both readers at once.

## Decision

**Math renders as KaTeX**, in the delimiters every common Markdown viewer
understands: `$$…$$` for a formula that stood alone as its own paragraph,
`$…$` for one that sat inside a sentence.

**Normalization happens at render time, not fetch time.** The captured extract
stays verbatim in SQLite — that is what `content_hash` covers and what `verify`
re-checks — so re-rendering never moves a custody hash, and a better normalizer
later just re-renders from the store. This is the §2.4 *raw is sacred* rule
applied to a presentation concern: the scroll body is a **view** of the
capture, not a second copy of it.

**The normalizer is source-agnostic** (`scrolls.mathtext.normalize_math`).
Nothing in it is Wikipedia-specific, and text with no marker is returned
unchanged.

**An inline formula rejoins its sentence.** 6,541 of the 8,280 blocks sat
mid-sentence, with the prose split into fragments around them. Emitting the
formula in place and leaving the fragments as separate lines would keep the
text technically complete and still unreadable.

**Fallback detection is a shape heuristic, and a deliberately narrow one.** A
line counts as fallback when it is whitespace-only-but-nonempty or indented two
or more spaces, and the rule is consulted *only* for lines directly adjacent to
a `{\displaystyle}` marker. A truly empty line is never fallback — it is the
paragraph break that distinguishes display math from inline. Verified across
all 8,280 blocks: none contains an interior blank line.

**Every literal dollar in a body is escaped.** Making `$` a delimiter puts
prose currency in math scope. The library holds **990** literal dollars across
**115** scrolls — 65 in `Nvidia` alone, and 10 scrolls carry both dollars and
math — so an unescaped pair would swallow the sentence between them.

**URLs are written as CommonMark autolinks** (`<url>`) for the same reason.
Links render outside the normalizer's reach, and **12** captured URLs contain a
dollar, one of them a `$$` that would have opened a display math block. An
autolink keeps the URL byte-exact, keeps it clickable, and takes it out of math
scope. All 222,893 captured URLs are autolink-safe: no whitespace, no angle
brackets, all absolute schemes.

## Consequences

**Verified over the whole live library**, 2026-08-19: 566 scrolls re-rendered,
0 failures, **1,716 display** and **6,522 inline** formulas, **0** unprocessed
blocks left, **0** files with unbalanced delimiters once autolinked URLs are
excluded, `doctor` 0 issues. Scrolls total 42 MB against 44 MB before — the
extract shrank 14.2% because the fallback was pure duplication.

**No prose was lost.** The 8,795-word drop is 8,067 occurrences of the literal
markers `displaystyle`/`textstyle` plus fallback duplicates of words that
survive inside the TeX — traced word by word, including the 15 `where` losses,
each of which is a `\text{where }` rendered into the fallback.

**Every environment in the corpus is KaTeX-supported**: `aligned` (113),
`bmatrix` (101), `cases` (17), `pmatrix` (16), `array` (11), `alignedat` (8),
`matrix` (5), `vmatrix` (4). No unsupported construct appears.

**Two hazards were found only by running against live data**, both now pinned
by tests. Brace balancing must skip escaped braces, or `\left\{` ends the
formula early — 3 blocks depend on it. And 15 formulas end in a TeX control
space (`\ `); stripping it bares a backslash that escapes the closing `$`,
silently turning the delimiter into a literal dollar.

**Three `\displaystyle` occurrences legitimately survive** inside emitted TeX,
in fraction denominators such as `{\frac {…}{\displaystyle \int …}}`. That is
valid LaTeX, KaTeX renders it, and it is not an unprocessed block.

**A re-render has no bulk CLI path.** `scrolls md` with no argument renders
only items at stage `fetched`, and `maintain` regenerates KB views rather than
scrolls, so improving the renderer means looping over ids. Left as-is here and
recorded as the next gap to close.

**Deferred**: inline link anchors remain out of reach for the same reason ADR
0110 gave — `explaintext` strips link markup — and the fallback shape heuristic
carries the same maintenance posture as the chrome filter: it tracks a
slow-moving upstream convention, and a change upstream shows up as a block left
untouched rather than as damage.
