"""The bundle-format briefing-parity contract (roadmap H401) — one completeness-asserted invariant.

The eighth **contract-consolidation** cell (after H388's whole-MCP determinism
contract, H395's round-trip contract, H396's regeneration-safety contract, H397's
intra-CLI surface-parity matrix, H398's completeness-honesty contract, H399's
re-import idempotency contract, and H400's CLI↔MCP read-parity matrix). Where H400
pins that a read's custody payload is identical across the two *transports*, this pins
that a custody briefing fact is identical across the two portable *forms* of a
shareable bundle — the Markdown `export bundle` and the `--format html` bundle.

The claim (custody-vision §2.4, the PRD "shareable custody bundle parity" success
metric): *every* custody briefing fact a bundle carries — the scope headline, the
rank-strength headline, the weakest-source attention pointer, the at-risk-work
pointer, the import-conflict count, the archive-integrity alarm, the content-duplicate
count, the whole-library posture verdict, the per-source refresh pointer, the
per-source custody breakdown, and (for a `--concept` bundle) the synthesized-summary
provenance — renders in **both** forms, carrying the **same fact**. The two forms meet
at one shared primitive per line (`build_bundle` folds `render_custody_attention`;
`build_bundle_html` folds `_attention_html` — both distil the *same* `weakest_source`
over the same `custody_counts_by_source`), so parity holds **by construction** today;
this contract pins that "≡" once over an enumerated briefing-line registry rather than
re-stating it per line, so a future divergence (a fact dropped from one form, or a
count that disagrees) fails *its* line's leg.

This **lifts** the scattered per-line Markdown↔HTML convergence guards in
`test_bundle.py` (the `test_bundle_html_*_converges_with_the_markdown_form` /
`test_bundle_html_*_count_matches_markdown` pairs) to a single matrix; those per-line
tests stay as deeper regression guards (the H395/H400 discipline — the consolidation
adds the matrix, it does not delete the per-line teeth).

Two faces, the H388/H396/H397/H400 shape:

1. **The completeness keystone** — `_BRIEFING_LINES` (the enumerated lines, each with
   its Markdown and HTML emitter function) must cover **every** briefing-line emitter
   the two builders call. The live emitter set is read off the builders' own ASTs
   (`build_bundle`/`build_bundle_html`): every module-level function each calls, minus
   a *named* `_STRUCTURAL` set (the scope-gather/data-fold/custody-block helpers that
   are not briefing-line emitters). So a *new* briefing line added to one form fails
   the keystone until it is registered — and registering it declares the *other* form's
   emitter, whose leg then fails until that form carries it too. The "forced into both
   forms" mechanism: the two portable forms can never silently diverge.

2. **The matrix guard** — over one composite fixture that makes *every* briefing line
   non-vacuous (multi-source + drift + at-risk work + conflict + corrupt archive +
   content-duplicate pair + refresh debt + a concept summary), render both forms and
   assert each registered line's fact is **present in both** and **equal across them**,
   normalising the Markdown `_..._`/`` ` `` emphasis against the HTML `<p>`/`<li>`/
   `<code>`/entity wrappers. Two sabotages prove teeth and isolation: a line dropped
   from the HTML form, and a line whose HTML count is tampered, each fail *only* that
   line's leg.
"""

import ast
import dataclasses
import html as html_mod
import inspect
import re
import sqlite3

import pytest

import scrolls.bundle as bundle
from scrolls.bundle import build_bundle, build_bundle_html
from scrolls.classify import ENGINE as RULES_ENGINE
from scrolls.classify import RULESET_FINGERPRINT
from scrolls.cli import main
from scrolls.custody import CustodyEvent, conflict_event, record_events
from scrolls.items import ScrollItem, adopt_incoming, insert_item
from scrolls.kb import ConceptSummary, save_concept_summary
from scrolls.kb_llm import ENGINE as SUMMARY_ENGINE
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# --- normalising the two forms to one canonical fact -------------------------

_TAG = re.compile(r"<[^>]+>")


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _flat_md(line: str) -> str:
    """One Markdown briefing line → its canonical text.

    Drop the wrapping `_..._` emphasis and the `**bold**`/`` `code` `` spans the
    HTML form renders as `<em>`/`<strong>`/`<code>` (and which therefore vanish when
    the HTML side strips tags), then collapse whitespace. A literal angle-bracket
    placeholder (the `<S>` in the refresh command template) is left intact — the HTML
    side carries it escaped (`&lt;S&gt;`) and unescapes back to the same `<S>`.
    """
    return _flat(line.strip().strip("_").replace("**", "").replace("`", ""))


def _flat_html(inner: str) -> str:
    """The inner HTML of one element → its canonical text.

    Strip tags **first** (so `<code>`/`<strong>`/`<em>` wrappers vanish) and only then
    unescape entities, so an escaped placeholder (`&lt;S&gt;`) becomes the literal
    `<S>` the Markdown form carries rather than being eaten as a tag.
    """
    return _flat(html_mod.unescape(_TAG.sub("", inner)))


# --- per-line fact extractors (driven by the registry) -----------------------


def _md_marker(marker: str):
    """Extract the first Markdown briefing line whose canonical text starts with
    `marker` (the line label, e.g. ``Attention:``)."""

    def get(doc: str):
        for raw in doc.splitlines():
            flat = _flat_md(raw)
            if flat.startswith(marker):
                return flat
        return None

    return get


def _html_class(cls: str, *, starts: str | None = None):
    """Extract the first ``<p class="cls">`` whose canonical text starts with `starts`
    (defaulting to any) — the HTML twin's stable per-line hook. `starts` disambiguates
    the scope-headline `<p>` from the per-source-breakdown header, which share the
    ``custody-headline`` class."""
    pat = re.compile(rf'<p class="{re.escape(cls)}">(.*?)</p>', re.S)

    def get(doc: str):
        for m in pat.finditer(doc):
            flat = _flat_html(m.group(1))
            if starts is None or flat.startswith(starts):
                return flat
        return None

    return get


def _md_by_source(doc: str):
    """The Markdown per-source breakdown as a frozenset of canonical bullet texts
    (the `_By source:_` header's bullets, sans the `- ` marker)."""
    bullets, in_region = set(), False
    for raw in doc.splitlines():
        flat = _flat_md(raw)
        if flat == "By source:":
            in_region = True
            continue
        if in_region:
            if flat.startswith("- "):
                bullets.add(flat[2:])
            elif bullets:  # a blank *after* the bullets ends the region
                break
            # else: skip the blank line `render_custody_by_source` puts under the header
    return frozenset(bullets) or None


def _html_by_source(doc: str):
    """The HTML per-source breakdown as a frozenset of canonical ``<li>`` texts."""
    m = re.search(r'<ul class="custody-by-source">(.*?)</ul>', doc, re.S)
    if not m:
        return None
    items = re.findall(r"<li>(.*?)</li>", m.group(1), re.S)
    return frozenset(_flat_html(li) for li in items) or None


def _md_concept(doc: str):
    """The Markdown concept summary as a tuple of its canonical lines (the summary +
    its `Summary by … (members fingerprint …)` provenance)."""
    facts = [
        _flat_md(raw)
        for raw in doc.splitlines()
        if _flat_md(raw).startswith(("Concept summary", "Summary by"))
    ]
    return tuple(facts) or None


def _html_concept(doc: str):
    """The HTML concept summary as a tuple of its canonical ``<section>`` paragraphs."""
    m = re.search(r'<section class="concept-summary">(.*?)</section>', doc, re.S)
    if not m:
        return None
    paras = re.findall(r"<p[^>]*>(.*?)</p>", m.group(1), re.S)
    return tuple(_flat_html(p) for p in paras) or None


# --- the briefing-line registry — the completeness keystone ------------------

# Every custody briefing fact both bundle forms carry, with its Markdown emitter
# (`md_fn`), its HTML emitter (`html_fn`), the render context that makes it non-vacuous
# (`render`: the query bundle, or a `concept`-scoped bundle), and how its fact is read
# out of each rendered form. The `md_fn`/`html_fn` names are the keystone's teeth: they
# are asserted to be *exactly* the briefing-line emitters the builders call (below).
_BRIEFING_LINES = {
    "headline": dict(
        md_fn="custody_headline", html_fn="custody_headline", render="query",
        md_get=_md_marker("Custody:"),
        html_get=_html_class("custody-headline", starts="Custody:")),
    "strength": dict(
        md_fn="_strength_headline", html_fn="_strength_headline", render="query",
        md_get=_md_marker("Strength:"), html_get=_html_class("rank-strength")),
    "attention": dict(
        md_fn="render_custody_attention", html_fn="_attention_html", render="query",
        md_get=_md_marker("Attention:"), html_get=_html_class("custody-attention")),
    "at_risk": dict(
        md_fn="render_at_risk_works", html_fn="_at_risk_html", render="query",
        md_get=_md_marker("At-risk work:"), html_get=_html_class("custody-at-risk")),
    "conflicts": dict(
        md_fn="render_custody_conflicts", html_fn="_conflicts_html", render="query",
        md_get=_md_marker("Conflicts:"), html_get=_html_class("custody-conflicts")),
    "archive": dict(
        md_fn="_archive_integrity_lines", html_fn="_archive_integrity_html",
        render="query",
        md_get=_md_marker("Archive:"), html_get=_html_class("custody-archive")),
    "duplicates": dict(
        md_fn="render_content_duplicates", html_fn="_content_duplicates_html",
        render="query",
        md_get=_md_marker("Duplicates:"), html_get=_html_class("custody-duplicates")),
    "posture": dict(
        md_fn="render_posture", html_fn="_posture_html", render="query",
        md_get=_md_marker("Posture:"), html_get=_html_class("custody-posture")),
    "refresh": dict(
        md_fn="render_custody_refresh", html_fn="_refresh_html", render="query",
        md_get=_md_marker("Refresh:"), html_get=_html_class("custody-refresh")),
    "by_source": dict(
        md_fn="render_custody_by_source", html_fn="_by_source_html", render="query",
        md_get=_md_by_source, html_get=_html_by_source),
    "concept": dict(
        md_fn="_concept_summary_block", html_fn="_concept_summary_html",
        render="concept",
        md_get=_md_concept, html_get=_html_concept),
}

# The module-level functions each builder calls that are **not** briefing-line emitters:
# the scope gather, the scope-note, the per-source/conflict/refresh data folds the
# emitters read, the per-scroll entry renderers, and the sentinel-fenced custody/events/
# archive blocks + the HTML document wrapper. Named so a *new* briefing line cannot hide
# here — anything a builder calls that is neither registered nor named structural fails
# the keystone (the H400 "partition the live surface exactly" mechanism, on the
# briefing-line-emitter axis).
_STRUCTURAL = {
    "_gather_scope",            # the query+facets+custody scope gather (both forms)
    "_scope_note",              # the title scope provenance note (both forms)
    "custody_counts_by_source",  # the by-source/attention data fold (MD reads it once)
    "latest_conflict_events",   # the conflict-ledger data fold (MD)
    "_refresh_debt_by_source",  # the enrichment/summary stale-debt fold (MD)
    "_briefing_entry",          # the per-scroll Markdown entry (not a briefing *line*)
    "_briefing_entry_html",     # the per-scroll HTML entry
    "_custody_details_html",    # the embedded <details> custody/events/archive blocks
    "_items_block",             # the lossless @generated items JSONL block (both forms)
    "_events_block",            # the @generated custody-events JSONL block (both forms)
    "_archive_block",           # the optional @generated prior-content archive block
    "archived_records",         # the --with-archive record fetch (both forms)
    "_html_document",           # the self-contained HTML5 document wrapper
}


def _module_fn_calls(fn) -> set[str]:
    """Every bundle module-level function `fn` calls (read off its AST).

    A bare-name call (`ast.Name`) whose name resolves to a callable attribute of the
    `bundle` module — so builtins (`len`/`enumerate`) and method calls
    (`lines.append`/`html.escape`) are excluded, leaving exactly the helper functions
    the builder composes its output from. This is the *live* briefing-line-emitter
    surface the keystone holds the registry to.
    """
    tree = ast.parse(inspect.getsource(fn))
    return {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and callable(getattr(bundle, node.func.id, None))
    }


def test_briefing_line_registry_covers_every_emitter_in_both_builders():
    """The keystone: `_BRIEFING_LINES`' Markdown + HTML emitters are *exactly* the
    briefing-line functions the two builders call (every call minus the named
    `_STRUCTURAL` helpers) — so a *new* briefing line in either form fails until it is
    registered, and registering it forces its twin emitter into the other form."""
    md_calls = _module_fn_calls(bundle.build_bundle)
    html_calls = _module_fn_calls(bundle.build_bundle_html)

    md_fns = {line["md_fn"] for line in _BRIEFING_LINES.values()}
    html_fns = {line["html_fn"] for line in _BRIEFING_LINES.values()}

    # every briefing-line emitter is registered, and every registered emitter is a real
    # call — the both-directions equality (a dropped registration *or* a phantom both fail)
    assert md_calls - _STRUCTURAL == md_fns
    assert html_calls - _STRUCTURAL == html_fns

    # the structural set is exactly the non-briefing helpers the builders call (no stale
    # name lingers, no real emitter is mis-classified as structural)
    assert _STRUCTURAL == (md_calls | html_calls) - md_fns - html_fns
    # …and every structural name is a real bundle function (a typo fails here)
    assert all(callable(getattr(bundle, name, None)) for name in _STRUCTURAL)

    # sanity: the registry is the eleven briefing facts the spec names, non-trivial
    assert set(_BRIEFING_LINES) == {
        "headline", "strength", "attention", "at_risk", "conflicts", "archive",
        "duplicates", "posture", "refresh", "by_source", "concept",
    }


# --- the matrix guard --------------------------------------------------------


def _make_item(item_id, title, body, **overrides):
    base = dict(
        id=item_id, source="wikipedia", url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00", title=title,
        raw_text=f"<raw>{body}</raw>", extracted_text=body,
        summary=body.split(".")[0] + ".", content_hash="deadbeef",
        provenance={"fetched_at": "2026-06-12T00:00:00+00:00", "via": "test"},
        markdown_path=f"scrolls/wikipedia/{item_id}.md", stage="rendered")
    base.update(overrides)
    return ScrollItem(**base)


def _ref_item(item_id, title, doi, **overrides):
    item = _make_item(item_id, title, "ignored",
                      links=(f"https://doi.org/{doi}",), **overrides)
    return dataclasses.replace(
        item, raw_text=None, extracted_text=None, summary=None, content_hash=None)


def _rules_provenance(ruleset):
    return {"fetched_at": "2026-06-12T00:00:00+00:00", "via": "test",
            "classified_by": RULES_ENGINE, "classified_basis": "documentation-url",
            "classified_ruleset": ruleset}


def _event(item_id, status, observed):
    return CustodyEvent(item_id=item_id, checked_at="2026-06-14T00:00:00+00:00",
                        status=status, prior_hash="deadbeef", observed_hash=observed)


def _seed_every_briefing_line(db):
    """One library that makes *every* briefing line non-vacuous under a `database`
    query (and a `Databases` concept for the summary line).

    Every content_hash is distinct except the intended duplicate pair (so the
    `_Duplicates:_` count is exactly one group of two, not a side-effect of the default
    fixture hash), and every title carries "database" so the query covers the whole
    scope. The shapes: a multi-source drift (attention + by-source + headline), an
    unresolved import conflict, a corrupt archived prior, a byte-identical pair, an
    all-reference at-risk work beside a safely-held one, stale enrichment + a stale
    concept summary (refresh + concept), and — always — the whole-library posture.
    """
    # multi-source drift → headline / strength / by-source / weakest-source attention
    insert_item(db, _make_item("web:full", "Full database", "A full database.",
        source="web", url="https://web.example/full", content_hash="h-webfull"))
    insert_item(db, _make_item("web:moved", "Moved database", "A moved database.",
        source="web", url="https://web.example/moved", content_hash="h-webmoved"))
    insert_item(db, _make_item("arxiv:1", "Arxiv database paper", "A database paper.",
        source="arxiv", url="https://arxiv.org/abs/1", content_hash="h-arxiv1"))
    record_events(db, [_event("web:full", "unchanged", "h-webfull")])
    record_events(db, [_event("web:moved", "drifted", "cafe1234")])

    # an unresolved import conflict (incoming hash ≠ the held copy's current hash)
    insert_item(db, _make_item("wikipedia:en:SQLite", "SQLite database", "Body.",
        content_hash="h-sqlite"))
    record_events(db, [conflict_event(
        "wikipedia:en:SQLite", held_hash="h-sqlite", incoming_hash="h-sqlite-in",
        now="2026-06-22T00:00:00+00:00")])

    # a corrupt archived prior (prior_hash tampered ≠ snapshot) → archive integrity
    held = _make_item("wikipedia:en:Postgres", "Postgres database", "Body.",
                      content_hash="h-pg-v1")
    insert_item(db, held)
    adopt_incoming(db, dataclasses.replace(
        held, extracted_text="a later capture", content_hash="h-pg-v2"),
        archived_at="2026-06-22T00:00:00+00:00")
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("UPDATE item_archive SET prior_hash = ? WHERE item_id = ?",
                     ("sha256:tampered", "wikipedia:en:Postgres"))
    conn.close()

    # a byte-identical pair (one group of two) → content duplicates
    insert_item(db, _make_item("wikipedia:en:A", "Alpha database", "Body A.",
        content_hash="h-dup"))
    insert_item(db, _make_item("wikipedia:en:B", "Beta database", "Body B.",
        content_hash="h-dup"))

    # an all-reference work (no full+unmoved copy) → at-risk work; + a safely-held work
    insert_item(db, _ref_item("arxiv:zref", "Zeta database preprint", "10.3000/z",
        source="arxiv", url="https://arxiv.org/abs/zref"))
    insert_item(db, _ref_item("crossref:10.3000/z", "Zeta database record", "10.3000/z",
        source="crossref", url="https://doi.org/10.3000/z"))
    insert_item(db, _make_item("arxiv:yfull", "Ypsilon database preprint",
        "A full database body.", source="arxiv", url="https://arxiv.org/abs/yfull",
        links=("https://doi.org/10.2000/y",), content_hash="h-yfull"))
    insert_item(db, _ref_item("crossref:10.2000/y", "Ypsilon database record",
        "10.2000/y", source="crossref", url="https://doi.org/10.2000/y"))

    # stale enrichment ({web}) + a stale concept summary ({arxiv, web}) → refresh
    insert_item(db, _make_item("web:old-class", "Old database doc", "An old database doc.",
        source="web", url="https://web.example/old", content_hash="h-oldclass",
        category="documentation", provenance=_rules_provenance("oldfingerprint")))
    insert_item(db, _make_item("web:db1", "Web database", "A web database.",
        source="web", url="https://web.example/db1", content_hash="h-db1",
        concepts=("Databases",)))
    insert_item(db, _make_item("arxiv:db2", "Arxiv database", "An arxiv database.",
        source="arxiv", url="https://arxiv.org/abs/db2", content_hash="h-db2",
        concepts=("Databases",)))
    save_concept_summary(db, ConceptSummary(
        slug="databases", display="Databases", summary="Old synthesis.",
        members_hash="stalefingerprint", engine=SUMMARY_ENGINE, model="claude-test",
        generated_at="2026-06-12T00:00:00+00:00"))


def _render_both_forms(db):
    """The two portable forms of the query bundle and of the concept bundle."""
    return {
        "query": (build_bundle(db, "database"), build_bundle_html(db, "database")),
        "concept": (build_bundle(db, "database", concept="Databases"),
                    build_bundle_html(db, "database", concept="Databases")),
    }


def _parity_failures(forms):
    """The set of briefing lines whose fact is absent from a form or disagrees across
    the two — empty when every line carries the same fact in both forms."""
    failures = set()
    for key, line in _BRIEFING_LINES.items():
        md_doc, html_doc = forms[line["render"]]
        md_fact = line["md_get"](md_doc)
        html_fact = line["html_get"](html_doc)
        if md_fact is None or html_fact is None or md_fact != html_fact:
            failures.add(key)
    return failures


def test_every_briefing_line_renders_the_same_fact_in_both_forms(scrolls_home):
    """Over the composite fixture, each registered briefing line is present in **both**
    the Markdown and the HTML bundle and carries the **same fact** — the one invariant
    the scattered per-line `*_converges_with_the_markdown_form` tests pinned piecemeal."""
    main(["init"])
    db = get_paths().db_path
    _seed_every_briefing_line(db)
    forms = _render_both_forms(db)

    # the fixture is non-vacuous: every briefing line actually renders in the Markdown
    # form (a parity check that compared two absent facts would be a vacuous 0 == 0)
    for key, line in _BRIEFING_LINES.items():
        md_doc, _ = forms[line["render"]]
        assert line["md_get"](md_doc) is not None, f"{key} did not render in Markdown"

    assert _parity_failures(forms) == set()


def test_a_briefing_line_dropped_from_the_html_form_fails_only_that_line(
    scrolls_home, monkeypatch
):
    """Sabotage (the *dropped-from-one-form* corner): an HTML emitter that returns no
    line desyncs *only* its own leg — the matrix catches the form-divergence the
    completeness keystone forbids shipping, isolated to the offending line."""
    main(["init"])
    db = get_paths().db_path
    _seed_every_briefing_line(db)
    assert _parity_failures(_render_both_forms(db)) == set()  # baseline: all agree

    monkeypatch.setattr(bundle, "_conflicts_html", lambda db_path, items: [])
    assert _parity_failures(_render_both_forms(db)) == {"conflicts"}


def test_a_briefing_line_with_a_tampered_html_count_fails_only_that_line(
    scrolls_home, monkeypatch
):
    """Sabotage (the *different-count* corner): an HTML emitter that renders the line
    but with a wrong count desyncs *only* its own leg — the matrix is comparing the
    *fact*, not merely presence."""
    main(["init"])
    db = get_paths().db_path
    _seed_every_briefing_line(db)

    def _wrong_duplicates(items):
        return ['<p class="custody-duplicates">Duplicates: 9 group(s) of '
                "byte-identical content (99 item(s)).</p>"]

    monkeypatch.setattr(bundle, "_content_duplicates_html", _wrong_duplicates)
    assert _parity_failures(_render_both_forms(db)) == {"duplicates"}
