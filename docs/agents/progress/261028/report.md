# Release readiness report — 2026-10-28

## Verdict

The core is a release candidate after the hardening changes in ADR 0116.
The final Python matrix, installed-package checks, and public-source
verification pass. A blanket
claim that every optional integration has been tested live is not supported.
Account-based collections and paid LLM calls remain fixture-tested.

The audit starts from integration commit `e27118670ef5ad32302cbc7861a14260e0b5f5f8`.
Changes are uncommitted. Metadata remains `0.1.0`; no tag, publication, push,
or change to main was performed. Existing worktrees and the owner's library
were left alone.

## Verification results

- **Offline suite:** **4,886 passed on each supported Python version**:
  3.11.12 in 88.70 s, 3.12.10 in 85.80 s, and 3.13.5 in 77.71 s. Each has
  one expected network-guard warning and no failures. External networking stays
  blocked by pytest-socket; loopback is allowed for HTTP/OAuth fixtures.
- **CLI coverage:** all 52 leaf command help paths exercised; behavioral
  coverage follows the command matrix below.
- **MCP:** actual stdio initialization, tool discovery, and all 24 tools
  exercised on empty and populated disposable libraries, including error paths.
- **Packaging:** fresh locked dependency installation, wheel and source archive
  builds, wheel rebuilt from the source archive, and a fresh installed-wheel
  run passed. The final wheel exercised 19 CLI workflows, all 52 help leaves,
  all 24 MCP tools, invalid-cap errors, zero caps, and a symlink refusal.
- **Public sources:** all 39 public registered source keys passed a
  representative live normalized capture. X was not accessed live.
- **Live custody flow:** real CLI ingest of Wikipedia, arXiv, GitHub, a web
  article, and a PDF; all five verified unchanged. Re-ingest preserved the
  held export. Model-complete item and event exports restored byte-identically;
  a scoped PDF bundle adopted its hash-checked media sidecar. Both libraries
  ended with zero audit findings and custody score 100.
- **Scale smoke:** 1,000 items with 2 KB bodies restored byte-identical item
  exports and scrolls. Render/index: 3.30 s; KB: 0.19 s; doctor: 0.30 s;
  selective search: 0.024 s; a capped 1,000-match search: 0.27 s. These are
  local measurements, not a performance guarantee.
- **Remote CI baseline:** [the exact starting commit passed CI](https://github.com/oojBuffalo/scrolls/actions/runs/40053296209).
  This does not attest to the uncommitted hardening changes.

## Feature coverage

The complete offline suite covers each feature family. The extra probes below
exercise process, filesystem, network, packaging, and recovery boundaries that
a help-only check cannot prove.

| Feature | Commands or surface | Verification |
| --- | --- | --- |
| Setup, identity, configuration | init, status, paths, detect, version | CLI/path/config/URL tests; installed-package and live CLI smoke |
| Capture pipeline | add, ingest, fetch, md, md --all | Every adapter fixture; 39 live source keys; repeated-ingest and held-fetch preservation regressions |
| Media and document extraction | media, per-type limits, oversize, PDF text | Media/document/PDF/sidecar tests; collision/shared-owner/path regressions; real PDF restore |
| Classification and overrides | classify rules/LLM/stale/batch, set | Rules, LLM fixtures, provenance, confidence, override, stale-selector and parity tests |
| Retrieval and scope | search, list, show, facets, related, graph, works, context budgets | Focused and cross-surface suites; zero/negative/overflow caps; 1,000-item scoped search |
| Feed subscriptions | follow, sync, unfollow; OPML import/export | RSS/Atom/HTTP validator fixtures; malformed-entry continuation regression |
| Saved collections and login | sync collection discovery; X bookmarks; Wikipedia reading lists; x login/logout | Collection, browser-cookie, OAuth, CLI fixtures; pinned-profile account-selection regressions |
| Third-party imports | browser bookmarks, Google Takeout, Pocket, OPML | Dedicated import tests and CLI idempotence/error coverage |
| Portable custody | items/events/archive/bundle import/export; bookmarks/OPML export | Round-trip, conflict, archive, bundle, media-manifest and malformed-record suites; live full/scoped restore |
| Drift and history | verify selectors, history | Live five-source verification plus fixture drift/rot/error; append-only and parity invariants |
| Conflict and recovery | reconcile; archive list/show/restore/diff/prune | Adoption, recovery selectors, dry-run, retention, wrong-identity and stale-view regressions |
| Integrity and maintenance | doctor --fix; maintain scopes/history/trend | Missing/stale/unsafe artifacts, FTS, custody posture, repair suggestions, convergence and dogfood tests |
| Compiled views and annotations | kb deterministic/LLM/stale; agent install | KB/generated/LLM fixtures; slug collisions, member dedupe, tombstone identity and symlink regressions |
| Agent protocol | mcp, all 24 tools | Actual stdio protocol on empty/populated installed libraries; CLI/MCP parity suites |
| Schema and distribution | SQLite migrations, wheel, source distribution | Database migration/future-schema tests; fresh locked install, wheel-from-sdist, installed CLI/MCP checks |

## Reproduced release defects corrected

| Defect | Corrected behavior |
| --- | --- |
| Re-ingest/fetch silently replaced held raw captures | Ingest reuses held content; fetch directs the caller to verify |
| Imported paths could overwrite outside files or delete db.sqlite | Typed import checks plus runtime subtree and symlink guards |
| Shared/colliding paths could overwrite or remove another item's file | Independent filename allocation and shared-owner preservation |
| Null/wrong-type import fields made later commands crash | Shared model validation rejects malformed backups before writes; valid unknown-size media still round-trips |
| Archive snapshot identity differed from the item being restored | Imports and legacy restore/show/diff paths reject the mismatch |
| Adopt/restore left stale scrolls that doctor called healthy | Stale bytes are reported, lower custody integrity, and regenerate with --fix |
| Negative limits uncapped SQLite searches; huge limits crashed | Shared CLI/MCP validation rejects invalid caps; zero stays valid |
| KB slug collisions reassigned user notes or overwrote groups | Existing group identity/path is retained; collisions allocate distinct pages |
| Merged tag/concept spellings counted a member more than once | Each member is counted once per normalized group |
| One malformed feed URL aborted valid entries | Bad entries are counted and skipped without losing valid entries |
| gzip HTTP content reached extractors as compressed gibberish | Shared decoding honors Content-Encoding and decoded byte limits; corruption is a transport error |
| Five adapters crashed on non-object API envelopes | Malformed envelopes become typed per-item failures |
| Auto/Firefox selection ignored a pinned browser profile | A requested profile is honored without falling back to a different account |
| Generated pages followed filesystem symlinks on read/regeneration | Controlled library/agent paths fail before touching external targets |

## Source matrix

Each live result is one representative capture, not an assertion that every
URL variant or authenticated route remains operational.

| Source | Fixture coverage | Live result |
| --- | --- | --- |
| arxiv | `tests/test_arxiv.py` | passed |
| biorxiv | `tests/test_biorxiv.py` | passed |
| bitbucket | `tests/test_bitbucket.py` | passed |
| bluesky | `tests/test_bluesky.py` | passed |
| crates | `tests/test_crates.py` | passed |
| crossref | `tests/test_doi.py`, `tests/test_crossref.py`, `tests/test_datacite.py`, `tests/test_csl.py` | passed |
| devto | `tests/test_devto.py` | passed |
| discourse | `tests/test_discourse.py` | passed |
| gist | `tests/test_gist.py` | passed |
| gitea | `tests/test_gitea.py` | passed |
| github | `tests/test_github.py` | passed |
| gitlab | `tests/test_gitlab.py` | passed |
| go | `tests/test_go.py` | passed |
| hackage | `tests/test_hackage.py` | passed |
| hackernews | `tests/test_hackernews.py` | passed |
| hex | `tests/test_hex.py` | passed |
| huggingface | `tests/test_huggingface.py` | passed |
| lemmy | `tests/test_threadiverse.py`, `tests/test_lemmy.py`, `tests/test_piefed.py` | passed |
| lobsters | `tests/test_lobsters.py` | passed |
| mastodon | `tests/test_mastodon.py` | passed |
| maven | `tests/test_maven.py` | passed |
| medrxiv | `tests/test_biorxiv.py` | passed |
| misskey | `tests/test_misskey.py` | passed |
| npm | `tests/test_npm.py` | passed |
| nuget | `tests/test_nuget.py` | passed |
| openlibrary | `tests/test_openlibrary.py` | passed |
| packagist | `tests/test_packagist.py` | passed |
| pdf | `tests/test_pdf.py` | passed |
| pub | `tests/test_pub.py` | passed |
| pubmed | `tests/test_pubmed.py` | passed |
| pypi | `tests/test_pypi.py` | passed |
| rfc | `tests/test_rfc.py` | passed |
| rubygems | `tests/test_rubygems.py` | passed |
| stackexchange | `tests/test_stackexchange.py` | passed |
| web | `tests/test_web.py` | passed |
| wikidata | `tests/test_wikidata.py` | passed |
| wikipedia | `tests/test_wikipedia.py` | passed |
| x | `tests/test_x_fetch.py`, `tests/test_x_bookmarks.py`, `tests/test_x_graphql.py`, `tests/test_x_api.py`, `tests/test_x_oauth.py`, `tests/test_x_session.py` | not_run |
| youtube | `tests/test_youtube.py` | passed |
| zenodo | `tests/test_zenodo.py` | passed |

Crossref's DataCite/CSL fallbacks and Lemmy's PieFed fallback have fixture
coverage, without separate live probes in this run. GitHub/GitLab optional
private-token routes were not accessed.

## Remaining release gates and limits

- **Authorized live integrations:** X browser/API sessions, Wikipedia saved
  reading lists, browser Keychain extraction, and paid Anthropic classify/KB
  calls. Fixture tests cover their behavior; this run used no private accounts.
- **Final remote commit:** review and commit the changes, run the final commit
  through GitHub CI, choose a version/support statement, then tag and publish.
- **Platform and failure scope:** local runtime evidence is macOS on Python
  3.11–3.13. The baseline GitHub workflow covers Ubuntu. Windows, concurrent
  writers, and power-loss fault injection were not exercised.

JSONL carries records rather than media bytes. A complete media restore needs
its captured files or the opt-in bundle sidecar. Automatic sidecar lookup uses
the bundle stem (`briefing.md` → `briefing.media/`); an arbitrary sidecar path
must be passed explicitly with `import bundle --media DIR`.

Raw sources and private credentials are not included in this report. Temporary
harness evidence is under `/private/tmp/scrolls-v1-adapter-audit/`,
`/private/tmp/scrolls-v1-live-smoke-complete/`, and
`/private/tmp/scrolls-final-acceptance/run2/` on the validation machine.

## Reproduction and artifacts

The full offline check is `uv run --locked pytest -q`. The verification
checkout used the project's locked dependencies and loopback-enabled execution
for the local HTTP/OAuth fixtures. No public network access is needed by tests.

| Runtime | Result | Local full log |
| --- | --- | --- |
| Python 3.11.12 | 4,886 passed | `/private/tmp/scrolls-v1-python311-final-tests.log` |
| Python 3.12.10 | 4,886 passed | `/private/tmp/scrolls-v1-python312-final-tests.log` |
| Python 3.13.5 | 4,886 passed | final command output in this session |

The installed wheel and source archive are under
`/private/tmp/scrolls-v1-final-dist/`; installed behavior is recorded in
`/private/tmp/scrolls-v1-final-installed-smoke.json`. They retain the current
0.1.0 version and are local validation artifacts, not published releases.
