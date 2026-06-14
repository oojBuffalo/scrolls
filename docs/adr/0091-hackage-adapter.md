# 0091: Hackage via the cabal manifest; the Haskell sibling of the package family

Date: 2026-06-13

Status: accepted

## Context

The package-registry family reached its ninth member with NuGet (ADR 0090),
and that ADR named **Hackage** (Haskell) and CPAN (Perl) as the remaining
candidates. Until now a `hackage.haskell.org/package/<name>` URL fell through
to the generic `web` adapter (ADR 0001), which scrapes a JS-rendered page and
discards the structured metadata Hackage already holds — the curated category,
the license, the repository link, and the package's own prose description.

Hackage exposes that metadata with no auth, no API host, and no version
selection: a plain `GET hackage.haskell.org/package/<name>/<name>.cabal`
returns the **latest version's cabal manifest** (RubyGems' inline-latest
economy, ADR 0040). The cabal is not JSON — it is the family's first
indentation-structured `field: value` manifest — so the one new thing this
adapter writes is a small cabal parser. Two facts, confirmed against the live
service before committing:

1. **Identity is the package name, case-sensitive.** Hackage names are
   case-sensitive (`QuickCheck`, `HUnit`) and the cabal endpoint only resolves
   the exact case, so the source id is preserved **verbatim** — npm/RubyGems'
   rule (ADR 0035/0040), not the case-folding the lowercase-canonical
   registries use. A `/package/<name>-<version>` page (the trailing
   dotted-numeric stripped, while a hyphen-before-a-letter like `aeson-pretty`
   stays part of the name) and a subpage dedupe to the name.

2. **The cabal carries a prose body and a curated category — richer than the
   metadata-only registries.** The cabal's `description` is a real prose body,
   so it becomes the searchable `extracted_text` (the `.`-only line is
   cabal/haddock's blank-line marker), with `synopsis` the short `summary` —
   the arXiv abstract+body split (ADR 0010) applied to a manifest, where
   RubyGems/Hex are honestly metadata-only. The `category` field is
   comma-separated curated keywords → `concepts` like github repo topics /
   PyPI keywords (ADR 0007/0034), so a Haskell package joins the KB concept
   graph. The cabal carries no upload date (that lives in a separate Hackage
   API), so `published_at` is honestly left as the feed seed — Go/NuGet's
   honest-empty posture (ADR 0042/0090).

## Decision

Add a host-claimed `hackage` source and a keyless single-request adapter
(`sources/hackage.py`), the tenth of the package-registry family.

- **Detection** (`detect._hackage_id`). Claim `hackage.haskell.org`/`www.`
  `/package/<name>[-version]`; identity is the name verbatim, the trailing
  `-<dotted-numeric>` version stripped. The browse list is the *plural*
  `/packages/`, so only the singular `/package/<name>` carries a fetchable id.
- **Fetch** (`hackage.fetch_item`). `GET /package/<name>/<name>.cabal` →
  parse the **cabal manifest** (`_parse_cabal`): top-level package fields sit
  at column 0 (a value may continue on more-indented lines); a column-0 line
  with no `field:` shape is a *section* header (`library`, `executable foo`,
  `source-repository head`) whose indented body is **not** read as package
  fields — only the `source-repository` block's `location` is taken; full-line
  `--` comments are dropped; the first occurrence of a field wins. Map:
  `name` → title (canonical); `author` (its `<email>` stripped) → author;
  `synopsis` → summary; `description` (the `.` line → a blank line) →
  `extracted_text`; `category` (comma-split) → concepts; `license` → the one
  tag, **verbatim** (an SPDX id on modern cabals, a legacy cabal id like `BSD2`
  on older ones — mapping them would need a per-id table for little gain);
  `homepage` + the repository `location` → links (the `.git`/`git+` folded so
  the repository resolves to a saved github repo, the **package↔repo edge**);
  canonical URL `https://hackage.haskell.org/package/<name>`. The cabal text is
  kept as `raw_text`.
- **Classification**: `hackage → tool` like every package (ADR 0004).
- A cabal with no `name` field is not a package manifest → FetchError.

## Consequences

- Haskell joins Scrolls, its categories joining the KB concept graph. The
  cabal's `description` makes a Hackage scroll searchable on its prose body,
  not just metadata — the first registry adapter whose own manifest carries a
  body (Go's go.mod is a dependency manifest, not prose). Live-verified
  keyless ingest: `aeson` (SPDX `BSD-3-Clause`, `Text, Web, JSON` →
  concepts, the `.git` repo deduped with the homepage), `lens` (legacy `BSD2`
  kept verbatim, `Data, Lenses, Generics`), and case-sensitive `QuickCheck`
  (`BSD3`, the github repo edge).
- The family now spans Python, JavaScript, Rust, PHP, Ruby, Go, Dart/Flutter,
  Elixir/Erlang, .NET, and Haskell — ten registries. **CPAN** (Perl, via the
  rich MetaCPAN JSON API, with a module→distribution resolve for `/pod/`
  URLs) is the obvious remaining candidate, unclaimed until a saved URL needs
  it.
- The cabal parser is deliberately small — it reads the top-level fields and
  the one `source-repository` block a scroll needs, not the full cabal grammar
  (conditionals, common stanzas, build-depends). A field it doesn't recognize
  is simply ignored, so a future need (e.g. `maintainer`, `stability`) is a
  one-line addition. Defers: the Hackage upload date (a second request), and
  the legacy-cabal-license → SPDX normalization.
