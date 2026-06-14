# 0092: Maven Central via the flat repository (maven-metadata.xml + POM); the JVM sibling of the package family

Date: 2026-06-14

Status: accepted

## Context

A developer's saved internet — Scrolls' core audience (IDEAS.md §11) — is full
of package pages, and the package-registry family now spans ten ecosystems:
PyPI, npm, crates.io, Packagist, RubyGems, Go, pub.dev, Hex, NuGet, and Hackage
(ADR 0034–0036, 0039, 0040, 0042, 0088–0091). The conspicuous remaining gap was
the **JVM** — the single largest library ecosystem in existence (Java, Kotlin,
Scala, Clojure, Groovy, and every Android dependency publish to Maven Central) —
with no adapter. Until now a saved Maven artifact URL fell through to the generic
`web` adapter (ADR 0001): `trafilatura` over a JS-rendered index page captures a
description but discards the structured facts — the license, the repository link,
the publish date — that make a clean scroll.

Three decisions shaped the design; all were probed against the live service
before committing — the registry ADRs' discipline.

1. **The flat repository over the search API.** Maven Central has a Solr search
   API (`search.maven.org/solrsearch`), but it is rate-limited and returns
   index summaries, not the artifact manifest. The canonical Maven 2 repository
   (`repo1.maven.org/maven2`) is instead a permanent, keyless **static file
   tree** — exactly the surface a build tool resolves against — reachable in two
   plain requests with no auth and no runtime dependency:
   - `GET /<group-path>/<artifact>/maven-metadata.xml` →
     `<versioning>` with a `<release>` pointer, the full `<versions>` list, and
     a `<lastUpdated>` timestamp (plain XML, always one document).
   - `GET /<group-path>/<artifact>/<version>/<artifact>-<version>.pom` → the
     POM, the manifest that becomes the scroll (plain XML).

   This is exactly the Go (ADR 0042) and NuGet (ADR 0090) "version index + a
   manifest file" shape: stdlib ElementTree, no gzip, no pagination, no API key.

2. **Identity is the Maven coordinate `groupId:artifactId`, verbatim.** A Maven
   artifact is addressed by two parts — a reverse-DNS `groupId`
   (`com.google.guava`) and an `artifactId` (`guava`) — joined here in the
   registry's own coordinate notation with a colon (`maven:com.google.guava:guava`),
   distinct from Packagist's `vendor/name` slash (ADR 0039). The repository is a
   literal, case-sensitive file tree, so the coordinate is preserved **verbatim**
   (the npm/RubyGems/Hackage rule, ADR 0035/0040/0091, not the case-folding
   PyPI/crates rule). The reverse-DNS group is **path-encoded** to address the
   directory — its dots become slashes (`com.google.guava` → `com/google/guava`)
   — the structural cousin of Go's request case-encoding (ADR 0042).

3. **Latest *release*, from the version index.** maven-metadata.xml's
   `<release>` is exactly the latest non-SNAPSHOT release Maven itself resolves,
   and crucially it gets **stable build classifiers** right where a naive
   heuristic does not: Guava's versions are all `-jre`/`-android` suffixed
   (`33.4.0-jre`), so "a hyphen marks a pre-release" would wrongly skip every
   one. `<release>` is therefore preferred outright, with a SNAPSHOT-excluded
   numeric ranking (ADR 0039) the fallback only for an artifact with no
   `<release>` pointer.

Two facts then shaped the mapping, and they are where Maven *diverges* from its
recent siblings:

4. **`concepts` empty by design.** A POM has no keyword/topic facet, so a Maven
   artifact contributes nothing to the KB concept graph — `concepts` empty like
   RubyGems, Go, and Hex (ADR 0040/0042/0089), the registry's data (not the
   adapter) deciding whether a package can join the graph. This is the opposite
   of NuGet (ADR 0090), whose `<tags>` made .NET a concept producer; the JVM
   joins as a metadata-and-edges source, not a concept source.

5. **The publish date lives in the index, not the manifest.** A POM carries no
   reliable upload date, but maven-metadata.xml's `<lastUpdated>`
   (`yyyyMMddHHmmss`, UTC) records the artifact's last deploy — for a release
   artifact, its latest release. So `published_at` is read from the *version
   index*, making Maven the only adapter whose date comes from outside its own
   content manifest, rather than left empty as NuGet's was (ADR 0090).

## Decision

Add a host-claimed `maven` source and a keyless two-request adapter
(`src/scrolls/sources/maven.py`), the eleventh of the package-registry family.

- **Detection** (`detect._maven_artifact_id`, `detect._maven_repo_id`). Two URL
  grammars detect alike:
  - The **`/artifact/<group>/<artifact>[/<version>]`** browse grammar of the
    official UIs (`central.sonatype.com`, `search.maven.org`) and the popular
    third-party index (`mvnrepository.com`) — unambiguous, the version segment
    ignored (the registry-family pattern).
  - The **raw repository** path (`repo1.maven.org`, `repo.maven.apache.org`)
    `/maven2/<group-path>/<artifact>/…`, where the reverse-DNS group is a slash
    path that must be reassembled. The version directory is the tell: the first
    segment after `maven2` that starts with a digit is a version, so the segment
    before it is the artifact and everything before that the dotted group (so a
    legacy single-segment group like `junit/junit/4.13.2/…` works too). With no
    version a trailing file (`maven-metadata.xml`, a `.pom`/`.jar`) is dropped;
    a bare directory listing is claimed only at the reverse-DNS shape (≥3
    segments), leaving a 2-segment group listing unclaimed, and any residual
    group/artifact boundary ambiguity degrades to a benign failed fetch (the Go
    sub-package posture, ADR 0042).

  Identity is the coordinate kept verbatim; `mvnrepository.com` indexes several
  repositories, so an artifact it lists that is not on Central degrades to a
  failed fetch (honest, not a wrong scroll).
- **Fetch** (`maven.fetch_item`). Split the coordinate; path-encode the group;
  `GET …/maven-metadata.xml` → choose `<release>` (else the ranked fallback) and
  read `<lastUpdated>`; `GET …/<version>/<artifact>-<version>.pom` → parse
  `<project>` **namespace-agnostically** (POMs declare the
  `…/POM/4.0.0` namespace but some omit it, so children match by *local* name —
  the nuspec lesson, ADR 0090). Map: `<name>` else the coordinate → title;
  `<organization><name>` else the first `<developers><developer><name>` →
  author; `<description>` → summary (no `extracted_text`); `concepts` empty;
  `<licenses><license><name>` → tags, verbatim (Maven license names are
  freeform — the Hackage rule, ADR 0091); `<url>` + the `<scm>` repository →
  links (the `<scm><url>` or, failing that, the `scm:<tool>:<url>`
  `<connection>`/`<developerConnection>` with the ssh `git@host:path` and
  `git://` forms normalized to https and `.git` stripped — the **package↔repo
  edge**); canonical URL `https://central.sonatype.com/artifact/<group>/<artifact>`;
  `published_at` from the index `<lastUpdated>`, degrading to the feed seed. The
  POM text is kept as `raw_text`.
- **Classification**: `maven → tool` like every package (ADR 0004).
- The POM **is** the metadata, so its failure (a non-200, non-XML body) is a
  FetchError — there is no metadata-only scroll to degrade to, unlike Go's
  optional `go.mod` (ADR 0042).

## Consequences

- The JVM ecosystem joins Scrolls; a saved `central.sonatype.com`,
  `search.maven.org`, `mvnrepository.com`, or raw `repo1.maven.org` URL becomes a
  clean metadata-and-edges scroll instead of a `web` scrape. Verified offline
  against trimmed real payloads (`tests/test_maven.py`): `com.google.guava:guava`
  (the `-jre`/`-android` classifier versions, `<release>` preferred over the
  ranking, the project `<url>` and `<scm>` deduped to one github edge, the
  freeform Apache license name as the one tag, `<lastUpdated>` → `published_at`),
  the group-path encoding of the request, the namespace-agnostic POM parse, and
  the ssh-connection normalization.
- The eleventh keyless registry; the family now spans Python, JavaScript, Rust,
  PHP, Ruby, Go, Dart/Flutter, Elixir/Erlang, .NET, Haskell, and the JVM. **CPAN**
  (Perl, via the rich MetaCPAN JSON API), **CRAN** (R), and **conda-forge**
  remain reachable on the same pattern, none claimed until a saved URL needs one.
- Defers **parent-POM inheritance**: a multi-module child POM that inherits its
  `<description>`/`<licenses>`/`<scm>` from a `<parent>` yields a thinner scroll
  rather than a parent-resolution request chain — the obvious enrichment if
  empty-field scrolls prove common in practice. Also defers the artifact's jar
  README extraction (npm/crates' tarball trick, ADR 0035), the `<packaging>` type
  as a tag, per-version dates, and self-hosted/private Maven repositories
  (JitPack, GitHub Packages, Artifactory) — the self-hosted-GitLab posture
  (ADR 0055).
