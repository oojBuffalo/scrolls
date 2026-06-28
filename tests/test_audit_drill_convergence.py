"""The audit-aggregate ↔ browse-drill convergence contract (roadmap H418).

One completeness-asserted invariant — the twenty-fifth **contract-consolidation**
cell and the *audit*-side sibling of H411's *facet*-side drill. Where H411 ties the
browse **aggregate** (`facets <dim>`) to the rows the matching `list`/`search`
value-filter enumerates, this ties the **custody audit** (`doctor`/
`get_library_health`) to the same drill rows: every count the audit reports equals
exactly the number of rows the matching `list` browse filter enumerates, so an
agent that reads a number off the audit and then drills `list` is promised exactly
that many rows.

The claim, for *every* drillable count-bearing field of the live `run_doctor`
custody block:

- `custody.tiers[tier]` ≡ `len(list --fidelity tier)` (full/partial/reference);
- `custody.drift[posture]` ≡ `len(list --drift posture)` (the ledger word
  `unchanged` is the posture `verified`, the one vocabulary remap — H42/H123);
- `custody.enrichment.stale` ≡ `len(list --stale-classification)` (H185);
- `custody.content_duplicates.total_items` ≡ `len(list --content-duplicate)` (H328).

— on **both** the CLI `doctor` and the MCP `get_library_health` transports (the
twin spreads the same `run_doctor` custody block, H381/H410).

Two faces, the H388/H394/H403/H410/H411 shape:

1. **The completeness keystone** — an `_AUDIT_DRILL` registry of (custody count
   field → `list` drill) ∪ a *named* `_NO_DRILL` set must partition *exactly* the
   set of integer count leaves the live `run_doctor` custody block carries (walked
   off a real empty-library audit, the structural skeleton), so a *new* custody
   count field fails the contract until it declares a drill tie or is named
   non-drillable (the H411 registry-completeness mechanism on the audit axis). The
   non-drillable counts are the rollups/complements with no single `list` filter:
   the integrity `score`/`issues`, the cross-posture `drift.checked`/`coverage`,
   the conflict/works/archive aggregates (cross-source or recovery-store axes, not
   held-item filters), the classified/current/unfingerprinted enrichment
   complements, and the whole `summaries` block (a *concept*-axis count — see the
   roadmap correction).

   **Roadmap correction (the H404/H407/H409/H412/H413/H415/H416/H417 precedent):**
   the H418 spec listed `summaries.stale ≡ len(list --stale-summary)` as a fifth
   tie, but H410 already established `custody.summaries.stale` counts stale
   *concepts*, not members (`_StaleAudit(count=None)` for `stale_summary`), while
   `list --stale-summary` enumerates the member items of those concepts — the two
   are different cardinalities (one stale concept can have many members). So
   `summaries.stale` is **non-drillable** (a concept-axis count with no item-count
   tie); the `--stale-summary` member drill is H410's job, not an audit-count tie.

2. **The drill matrix** — over one fixture non-vacuous on every drillable axis
   (all three fidelity tiers, all five drift postures, a content-duplicate pair,
   and a stale-classification set), each (transport, field) audit count equals the
   rows the matching `list` filter enumerates; and a sabotage that double-counts
   one tier in the doctor audit fold desyncs *only* that field's two legs (both
   transports, which share the patched `run_doctor`), never its drill (the `list`
   filter reads an independent SQL fold) nor its sibling counts.

Test-only, no production change — every audit count is already convergent with its
browse filter (one custody primitive per axis); this pins the family as one
contract that auto-covers a *new* audit count.
"""

import dataclasses
import json

import pytest

import scrolls.doctor as doctor
import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.custody import CustodyEvent, record_events
from scrolls.doctor import run_doctor
from scrolls.items import ScrollItem, insert_item, list_items
from scrolls.paths import get_paths


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# --- the fixture: non-vacuous on every drillable audit axis ------------------

# A rules classification stamped under a *superseded* ruleset, so the live ruleset
# reads it stale (`is_stale_classification` → True) — the `_mark_stale_classified`
# provenance shape (`classify.ENGINE` + a fingerprint != `RULESET_FINGERPRINT`).
_STALE_RULES = {
    "classified_by": "rules-v1",
    "classified_basis": "title-pattern",
    "classified_ruleset": "deadbeef0000",
}


def _item(item_id, title, **overrides):
    base = dict(
        id=item_id,
        source="web",
        url=f"https://example.com/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=title,
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


def _seed_audit_drill_mix(db):
    """Seven items spanning every drillable audit axis, each a *proper* subset.

    - **fidelity** — `full` (5: raw/extracted + hash, captured), `partial` (1:
      extracted-only, no hash), `reference` (1: title-only pointer);
    - **drift** — all five postures: `verified` (unchanged event), `drifted`,
      `rotted`, `error`, and `unverified` (3 never-checked);
    - **stale-classification** — `web:dup1`/`web:dup2`/`arxiv:ml` carry the
      superseded ruleset (3); the rest are user-set/unclassified (not stale);
    - **content-duplicate** — `web:dup1`/`web:dup2` are byte-identical (one
      `content_hash`) → the only duplicate pair (`total_items` 2).

    So `tiers.full`=5, `tiers.partial`=1, `tiers.reference`=1; `drift.unchanged`=1,
    `drift.drifted`=1, `drift.rotted`=1, `drift.error`=1, `drift.unverified`=3;
    `enrichment.stale`=3; `content_duplicates.total_items`=2 — every drilled count a
    non-empty proper subset of the 7 held items, so a mis-derived count has a wrong
    number to land on (not 0 == 0) and the sabotage's +1 has a true value to diverge
    from.
    """
    insert_item(db, _item(
        "web:dup1", "Alpha database dup one",
        extracted_text="same dup body", raw_text="<raw>dup</raw>",
        content_hash="sha256:dup", stage="rendered",
        category="tutorial", provenance=_STALE_RULES))
    insert_item(db, _item(
        "web:dup2", "Alpha database dup two",
        extracted_text="same dup body", raw_text="<raw>dup</raw>",
        content_hash="sha256:dup", stage="rendered",
        category="tutorial", provenance=_STALE_RULES))
    insert_item(db, _item(
        "web:partial", "Alpha partial note",
        extracted_text="alpha partial body", stage="rendered"))  # partial, unverified
    insert_item(db, _item(
        "arxiv:ml", "Alpha learning paper", source="arxiv",
        url="https://arxiv.org/abs/ml", extracted_text="alpha ml body",
        raw_text="<raw>ml</raw>", content_hash="sha256:ml", stage="rendered",
        category="research", provenance=_STALE_RULES))
    insert_item(db, _item(
        "arxiv:op", "Alpha opinion essay", source="arxiv",
        url="https://arxiv.org/abs/op", extracted_text="alpha op body",
        raw_text="<raw>op</raw>", content_hash="sha256:op", stage="rendered",
        category="opinion"))  # a hand-set category, no provenance → not stale
    insert_item(db, _item(
        "wikipedia:bare", "Alpha wiki page", source="wikipedia",
        url="https://en.wikipedia.org/wiki/Alpha", raw_text="<raw>wk</raw>",
        content_hash="sha256:wk", stage="rendered"))  # full, error
    insert_item(db, _item(
        "crossref:ref", "Alpha crossref pointer", source="crossref",
        url="https://example.org/crossref-ref"))  # reference, unverified
    record_events(db, [
        CustodyEvent("web:dup1", "2026-06-14T00:00:00+00:00", "unchanged",
                     "sha256:dup", "sha256:dup", None),
        CustodyEvent("arxiv:ml", "2026-06-14T00:00:00+00:00", "drifted",
                     "sha256:ml", "sha256:x", None),
        CustodyEvent("arxiv:op", "2026-06-14T00:00:00+00:00", "rotted",
                     "sha256:op", None, "HTTP Error 404"),
        CustodyEvent("wikipedia:bare", "2026-06-14T00:00:00+00:00", "error",
                     "sha256:wk", None, "boom"),
        # dup2, partial, crossref:ref left unverified (no event)
    ])


# --- the audit-drill registry — the completeness keystone --------------------


@dataclasses.dataclass(frozen=True)
class _AuditDrill:
    """One custody count field and the `list` filter that drills it.

    `path` keys into the custody block to the integer scalar (e.g.
    `("tiers", "full")`); `flags` are the `list` argv flags that enumerate exactly
    the rows that count promises.
    """

    path: tuple
    flags: tuple

    def count(self, custody: dict) -> int:
        value = custody
        for key in self.path:
            value = value[key]
        return value


_AUDIT_DRILL = {
    "tiers.full": _AuditDrill(("tiers", "full"), ("--fidelity", "full")),
    "tiers.partial": _AuditDrill(("tiers", "partial"), ("--fidelity", "partial")),
    "tiers.reference": _AuditDrill(("tiers", "reference"), ("--fidelity", "reference")),
    # the ledger word `unchanged` is the posture `verified` (the one remap, H123)
    "drift.unchanged": _AuditDrill(("drift", "unchanged"), ("--drift", "verified")),
    "drift.unverified": _AuditDrill(("drift", "unverified"), ("--drift", "unverified")),
    "drift.drifted": _AuditDrill(("drift", "drifted"), ("--drift", "drifted")),
    "drift.rotted": _AuditDrill(("drift", "rotted"), ("--drift", "rotted")),
    "drift.error": _AuditDrill(("drift", "error"), ("--drift", "error")),
    "enrichment.stale": _AuditDrill(("enrichment", "stale"), ("--stale-classification",)),
    "content_duplicates.total_items": _AuditDrill(
        ("content_duplicates", "total_items"), ("--content-duplicate",)),
}


# The integer count leaves of the custody block with *no* single `list` filter —
# each named, never a silent skip. The non-drillable counts are the rollups,
# complements, and off-item axes:
_NO_DRILL = {
    # integrity rollups distilled across every item — not a row filter
    "score": "integrity percent (0–100), not a row count",
    "issues": "count of items with a custody finding; an integrity rollup, no "
              "single `list` filter (the finding axis rides `doctor` findings)",
    # drift rollups / coverage — across postures or a ratio, not one posture value
    "drift.checked": "total ever-checked (= unchanged+drifted+rotted+error); a "
                     "cross-posture rollup, no single `--drift` value",
    "drift.coverage.verified": "coverage numerator (items with any verdict); a "
                               "ratio numerator, not a posture filter",
    "drift.coverage.total": "coverage denominator (all in-scope items) = the whole "
                            "scope, no narrowing filter",
    # the import-conflict aggregate — a recorded-event rollup, no `list --conflict`
    "conflicts.items": "unresolved-conflict items; a ledger-event rollup, no "
                       "`list` filter (the conflict axis rides `show`/the ledger)",
    # enrichment complements — no inverse browse filter for the non-stale buckets
    "enrichment.classified": "items carrying a category; no `--classified` filter "
                             "(the complement axis is not a browse narrowing)",
    "enrichment.current": "classified under the live ruleset; the stale complement, "
                          "no `--current-classification` browse filter",
    "enrichment.unfingerprinted": "classified before the ruleset stamp (pre-H20); "
                                  "no browse filter for the unknown-freshness bucket",
    # the summaries block — a *concept*-axis count, not held-item rows (H410)
    "summaries.eligible": "concepts eligible for a summary; a concept-axis count, "
                          "not an item filter",
    "summaries.summarized": "concepts with a stored summary; concept-axis",
    "summaries.current": "concepts with a current summary; concept-axis",
    "summaries.stale": "stale *concepts*, not members (H410: `_StaleAudit(count="
                       "None)`); `list --stale-summary` enumerates the member items "
                       "of those concepts, a different cardinality — H418 correction",
    "summaries.never": "concepts never summarized; concept-axis",
    # works — a cross-source aggregate, not a held-item filter
    "works.total": "total works (cross-source canonical clusters); no `list --work` "
                   "count filter",
    "works.at_risk": "at-risk works; a works-axis aggregate, not an item filter",
    # archive — the recovery store, not held items
    "archive.checked": "archived priors checked; the recovery-store axis, not held "
                       "items",
    "archive.mismatched": "archived priors whose advertised hash diverges; "
                          "archive-store axis, no held-item filter",
    # content-duplicate groups — a group-axis count, the item count is the drill
    "content_duplicates.total_groups": "number of duplicate *groups*; a group-axis "
                                       "count, the per-item drill rides `total_items`",
}


def _count_leaves(block: dict, prefix: str = "") -> set:
    """Every integer-scalar leaf path of a custody block (excluding bool/None/str/
    list) — the set of count-bearing fields the keystone partitions. Recurses into
    nested dicts (`drift`/`drift.coverage`/`enrichment`/…); empty `by_source`/lists
    contribute nothing, so the walk over an empty-library audit is the stable
    structural skeleton."""
    leaves = set()
    for key, value in block.items():
        path = f"{prefix}{key}"
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            leaves.add(path)
        elif isinstance(value, dict):
            leaves |= _count_leaves(value, f"{path}.")
    return leaves


# --- keystone: the registry partitions the live custody count leaves ----------


def test_audit_drill_registry_partitions_the_live_custody_count_fields(scrolls_home):
    """`_AUDIT_DRILL` (the drillable counts) ∪ `_NO_DRILL` (the named non-drillable
    counts) partition *exactly* the integer count leaves the live `run_doctor`
    custody block carries — so a *new* custody count field fails the contract until
    it declares a drill tie or is named non-drillable (the H411 registry-completeness
    mechanism on the audit axis). Driven off a real empty-library audit (the
    structural skeleton: all counts present, every `by_source`/list empty), never a
    hand-copy of the block that could drift from the code."""
    main(["init"])
    custody = run_doctor(get_paths())["custody"]
    live = _count_leaves(custody)

    drill = set(_AUDIT_DRILL)
    no_drill = set(_NO_DRILL)
    assert drill.isdisjoint(no_drill)
    assert drill | no_drill == live, (
        f"unclassified custody counts: {live - drill - no_drill}; "
        f"stale registry entries: {(drill | no_drill) - live}"
    )

    # the load-bearing distinctions the registry encodes (sanity, not tautology):
    # every drill path is a real path into the block resolving to an int...
    for key, d in _AUDIT_DRILL.items():
        assert isinstance(d.count(custody), int), key
        assert key == ".".join(d.path)
    # ...and the H418 roadmap correction is pinned: `summaries.stale` is named
    # non-drillable (a concept-axis count), never a member-count drill.
    assert "summaries.stale" in no_drill
    assert "summaries.stale" not in {".".join(d.path) for d in _AUDIT_DRILL.values()}


# --- the drill matrix --------------------------------------------------------


def _list_count(flags, capsys):
    """How many rows `list --limit 1000 <flags>` enumerates — the drillable rows the
    audit count promises. A large limit keeps the page cap from truncating."""
    assert main(["list", "--limit", "1000", *flags]) == 0
    return len(json.loads(capsys.readouterr().out))


def _drill_failures(capsys):
    """The set of (transport, field) cells whose audit count disagrees with the rows
    the matching `list` filter enumerates. The matrix asserts this is empty; the
    sabotage asserts it is exactly the cells it broke. Both transports read off one
    `run_doctor` (the CLI block + the MCP twin's spread), so a doctor-fold sabotage
    fails *both* transports for the field it touches — never its drill (an
    independent SQL fold) nor its siblings."""
    report = run_doctor(get_paths())
    custody = report["custody"]
    health = mcp_server.get_library_health()
    failures = set()
    for field, d in _AUDIT_DRILL.items():
        rows = _list_count(d.flags, capsys)
        if d.count(custody) != rows:
            failures.add(("doctor", field))
        if d.count(health) != rows:
            failures.add(("get_library_health", field))
    return failures


def _assert_fixture_non_vacuous(capsys):
    """Every drilled audit count is a non-empty *proper* subset of the 7 held items,
    so a mis-derived count has a wrong number to land on (not 0 == 0) and the
    sabotage's +1 has a true value to diverge from."""
    held = len(list_items(get_paths().db_path))
    assert held == 7
    custody = run_doctor(get_paths())["custody"]
    for field, d in _AUDIT_DRILL.items():
        count = d.count(custody)
        assert count, f"{field}: empty audit count — fixture vacuous"
        assert count < held, f"{field}: count is the whole library — no off-axis row"
    # the headline tiers/drift/dups land exactly where the fixture intends
    assert custody["tiers"] == {"full": 5, "partial": 1, "reference": 1}
    assert custody["drift"]["unchanged"] == 1
    assert custody["drift"]["unverified"] == 3
    assert custody["enrichment"]["stale"] == 3
    assert custody["content_duplicates"]["total_items"] == 2


def test_every_audit_count_drills_exactly_its_browse_rows(scrolls_home, capsys):
    """Over the fixture non-vacuous on every drillable axis, every (transport, field)
    audit count equals exactly the rows the matching `list` filter enumerates — the
    audit-as-faithful-index guarantee, pinned once across the whole live custody
    count vocabulary on both the CLI `doctor` and the MCP `get_library_health`
    transports."""
    main(["init"])
    _seed_audit_drill_mix(get_paths().db_path)
    capsys.readouterr()

    _assert_fixture_non_vacuous(capsys)

    assert _drill_failures(capsys) == set()


def test_an_audit_fold_double_counting_one_tier_fails_only_that_field(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and isolates to the *field*:
    inflating the `full` tier in the doctor audit fold by one desyncs *only* the
    `tiers.full` legs — the count an agent reads off the audit over-promises the rows
    the `list --fidelity full` drill can show — on *both* transports (which share the
    patched `run_doctor`), never its drill (the `list` filter reads an independent
    `scrolls_fidelity` SQL fold) nor its sibling counts (each its own audit leaf).

    `doctor._check_custody_integrity` is the audit's own tier fold — a distinct code
    path from `list_items`' `--fidelity` SQL filter — so an inflated count diverges
    from the rows the drill enumerates while every other field stays green."""
    main(["init"])
    _seed_audit_drill_mix(get_paths().db_path)
    capsys.readouterr()

    assert _drill_failures(capsys) == set()  # baseline: clean

    real_check = doctor._check_custody_integrity

    def _inflated(paths, report, items, *args, **kwargs):
        real_check(paths, report, items, *args, **kwargs)
        report["custody"]["tiers"]["full"] += 1

    monkeypatch.setattr(doctor, "_check_custody_integrity", _inflated)

    assert _drill_failures(capsys) == {
        ("doctor", "tiers.full"),
        ("get_library_health", "tiers.full"),
    }
