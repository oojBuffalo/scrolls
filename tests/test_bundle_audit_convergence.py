"""H415 — the bundle-briefing ↔ live-audit convergence contract.

The twenty-second **contract-consolidation** cell and the *portable-vs-live*
sibling of H401's two-form bundle-parity matrix. Where H401 pins that a custody
briefing fact reads identically across the two portable *forms* of a shareable
bundle (Markdown ≡ HTML, `test_bundle_format_parity.py`), this pins that the same
fact equals what the **live audit** (`doctor`/`status`) reports for the **same
scope** — so a recipient reading the portable briefing sees exactly what the
sender's audit would report (custody-vision §2.4/§2.6, the PRD "fidelity/
provenance travel with every result" success metric, cap 9).

The claim: *every* custody fact a shareable `export bundle` briefing renders has a
whole-scope live-audit counterpart it equals by construction —

  - `_Custody:_`   fidelity holdings ≡ `custody.tiers`
  - `_Attention:_`                    ≡ `weakest_source(custody.by_source)`
  - `_At-risk work:_`                 ≡ `custody.works.most_at_risk`/`at_risk`
  - `_Conflicts:_`                    ≡ `custody.conflicts.items`
  - `_Archive:_`                      ≡ `custody.archive.mismatched`
  - `_Duplicates:_`                   ≡ `custody.content_duplicates.total_{groups,items}`
  - `_Posture:_`                      ≡ `custody.posture.verdict`
  - `_Refresh:_`                      ≡ `custody.enrichment/summaries.by_source`

The two sides meet at one shared primitive per fact (`build_bundle` folds
`custody_headline`/`render_custody_attention`/`render_at_risk_works`/… over the
gathered scope; `doctor.run_doctor` folds the *same* `custody_counts`/
`weakest_source`/`at_risk_signal`/`unresolved_conflicts`/`archive_integrity_block`/
`content_duplicate_groups`/`stale_*_counts_by_source`/`_assess_custody_posture`
over the whole library), so convergence holds **by construction** when the bundle
scope *is* the whole library; this contract pins that "≡" once over an enumerated
briefing-line registry rather than re-stating it per line, so a future **surface**
divergence — a briefing line re-deriving a count differently from the audit — fails
*its* line's leg.

Two roadmap corrections (the H404/H407/H409/H412/H413 precedent — the live code is
the authority over the roadmap's prose):

  - **`at_risk` *is* an audit-basis line.** The H415 roadmap bullet list enumerated
    seven ties and omitted `_At-risk work:_`, but `works.render_at_risk_works`
    folds the *same* `at_risk_signal` over the *same* `works_over` that doctor's
    `custody.works` reads (`doctor._check_at_risk_works`), so it converges
    field-for-field — it is tied to `custody.works`, not exempt.
  - **`by_source` *is* exempt** (`_NO_AUDIT_BASIS`), but not for "no audit twin" —
    doctor carries `custody.by_source`. It is a per-source *decomposition*, not a
    single whole-scope fact; its per-source tie to `custody.by_source` is already
    pinned by `tests/test_custody_convergence.py` (H104/H123), and the headline's
    whole-scope `tiers` tie stands for the aggregate here.

Two faces, the H388/H394/H397/H401/H413 shape:

1. **The completeness keystone** — `_AUDIT_BASIS` (each briefing line tied to its
   live-audit projection) ∪ a *named* `_NO_AUDIT_BASIS` exemption set must
   partition H401's `_BRIEFING_LINES` registry (cross-imported) *exactly*, so a
   *new* briefing line added to the bundle fails until it declares an audit basis
   or is named exempt (the H400 "partition the live surface exactly" mechanism, on
   the briefing-line ↔ audit axis).

2. **The matrix guard** — over the H401 composite fixture rendered as a
   **whole-library-scope** bundle (every fixture title carries "database", so the
   `database` query covers the whole library — the *decisive choice*: a scoped
   bundle has no whole-library audit twin, the named exemption boundary), every
   audit-basis line's fact extracted from the rendered briefing equals the
   `run_doctor` custody projection. The sabotage: a briefing line folding a
   tampered count (distinct from the audit fold) desyncs *only* its line.
"""

import re

import pytest

import scrolls.bundle as bundle
from scrolls.bundle import build_bundle
from scrolls.cli import main
from scrolls.custody import weakest_source
from scrolls.doctor import run_doctor
from scrolls.items import list_items
from scrolls.paths import get_paths

# The H401 keystone registry, composite fixture, and Markdown line flatteners —
# cross-imported so a *new* briefing line first fails H401's keystone (until it is
# registered in `_BRIEFING_LINES`) and then *this* contract (until it declares its
# audit basis). The recency contract's `from test_cli_determinism import …`
# cross-import precedent.
from test_bundle_format_parity import (  # noqa: E402
    _BRIEFING_LINES,
    _md_marker,
    _seed_every_briefing_line,
)


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# --- per-line fact extractors: the briefing side (parsed off the rendered bundle)
# and the audit side (projected off the `run_doctor` custody block). Each pair reads
# the *same* fact through the two surfaces; the matrix asserts they agree.


def _brief_tiers(md_doc):
    """`_Custody:_` fidelity holdings → `{tier: count}` (non-zero tiers only — the
    headline shows only non-zero tiers, in canonical order)."""
    line = _md_marker("Custody:")(md_doc)
    return {tier: int(n) for tier, n in re.findall(r"(full|partial|reference) (\d+)", line)}


def _audit_tiers(custody):
    return {tier: count for tier, count in custody["tiers"].items() if count}


def _brief_attention(md_doc):
    """`_Attention:_` → `(weakest source, loss reason)`."""
    line = _md_marker("Attention:")(md_doc)
    m = re.search(r"source (\S+) carries the most drift \((.+?)\)", line)
    return (m.group(1), m.group(2)) if m else None


def _audit_attention(custody):
    flagged = weakest_source(custody["by_source"])
    return (flagged["source"], flagged["reason"]) if flagged else None


def _brief_at_risk(md_doc):
    """`_At-risk work:_` → `(work doi/key, at-risk count)`."""
    line = _md_marker("At-risk work:")(md_doc)
    m = re.search(r"At-risk work: (\S+) — .+?; (\d+) work\(s\) at risk", line)
    return (m.group(1), int(m.group(2))) if m else None


def _audit_at_risk(custody):
    works = custody["works"]
    entry = works["most_at_risk"]
    return (entry["doi"], works["at_risk"]) if entry else None


def _brief_conflicts(md_doc):
    """`_Conflicts:_` → the unresolved-conflict item count."""
    line = _md_marker("Conflicts:")(md_doc)
    m = re.search(r"Conflicts: (\d+) item\(s\)", line)
    return int(m.group(1)) if m else None


def _audit_conflicts(custody):
    return custody["conflicts"]["items"]


def _brief_archive(md_doc):
    """`_Archive:_` → the integrity-mismatch prior count."""
    line = _md_marker("Archive:")(md_doc)
    m = re.search(r"Archive: (\d+) prior\(s\) fail integrity", line)
    return int(m.group(1)) if m else None


def _audit_archive(custody):
    return custody["archive"]["mismatched"]


def _brief_duplicates(md_doc):
    """`_Duplicates:_` → `(group count, item count)`."""
    line = _md_marker("Duplicates:")(md_doc)
    m = re.search(
        r"Duplicates: (\d+) group\(s\) of byte-identical content \((\d+) item\(s\)\)",
        line,
    )
    return (int(m.group(1)), int(m.group(2))) if m else None


def _audit_duplicates(custody):
    cd = custody["content_duplicates"]
    return (cd["total_groups"], cd["total_items"])


def _brief_posture(md_doc):
    """`_Posture:_` → the whole-library posture verdict."""
    line = _md_marker("Posture:")(md_doc)
    m = re.search(r"Posture: (\w+)", line)
    return m.group(1) if m else None


def _audit_posture(custody):
    return custody["posture"]["verdict"]


def _brief_refresh(md_doc):
    """`_Refresh:_` → `(stale-classification sources, stale-summary sources)`."""
    line = _md_marker("Refresh:")(md_doc)

    def _sources(label):
        m = re.search(rf"{label} stale in (.+?) — ", line)
        return frozenset(m.group(1).split(", ")) if m else frozenset()

    return (_sources("classifications"), _sources("summaries"))


def _audit_refresh(custody):
    return (
        frozenset(custody["enrichment"]["by_source"]),
        frozenset(custody["summaries"]["by_source"]),
    )


# --- the audit-basis registry — the completeness keystone --------------------

# Every custody briefing line whose fact has a whole-scope live-audit counterpart,
# mapped to its briefing-side extractor (`brief`) and its audit-side projection
# (`audit`). The matrix guard asserts `brief(bundle) == audit(doctor.custody)` per
# line over the whole-library-scope fixture.
_AUDIT_BASIS = {
    "headline": dict(brief=_brief_tiers, audit=_audit_tiers),
    "attention": dict(brief=_brief_attention, audit=_audit_attention),
    "at_risk": dict(brief=_brief_at_risk, audit=_audit_at_risk),
    "conflicts": dict(brief=_brief_conflicts, audit=_audit_conflicts),
    "archive": dict(brief=_brief_archive, audit=_audit_archive),
    "duplicates": dict(brief=_brief_duplicates, audit=_audit_duplicates),
    "posture": dict(brief=_brief_posture, audit=_audit_posture),
    "refresh": dict(brief=_brief_refresh, audit=_audit_refresh),
}

# The briefing lines with no *whole-scope single audit fact* to converge against —
# each named (the H400/H413 named-exemption discipline, never a silent skip).
_NO_AUDIT_BASIS = {
    "strength": "the rank-explainability headline (match_strength bands, H312/H317) "
                "— a *ranking* fact, not a custody-audit fact; doctor/status' custody "
                "block carries no rank-strength counterpart (its cross-surface "
                "convergence is the H407 rank-axis matrix, not an audit tie).",
    "by_source": "the per-source custody *breakdown* — a decomposition of the "
                 "headline, not a single whole-scope fact; its per-source tie to "
                 "doctor's `custody.by_source` is already pinned by "
                 "test_custody_convergence (H104/H123), and the headline's "
                 "whole-scope `tiers` tie stands for the aggregate here.",
    "concept": "the synthesized concept-summary provenance (the members-fingerprint "
               "freshness, H35) — renders only in a `--concept` bundle and has no "
               "whole-scope audit counterpart (doctor counts *stale summaries* in "
               "`custody.summaries`, never renders a summary's provenance string).",
}


def _convergence_failures(md_doc, custody):
    """The set of audit-basis lines whose briefing fact disagrees with the live-audit
    projection — empty when every line converges; exactly the sabotaged line when a
    fold is tampered."""
    failures = set()
    for key, line in _AUDIT_BASIS.items():
        if line["brief"](md_doc) != line["audit"](custody):
            failures.add(key)
    return failures


# --- keystone: the audit basis partitions the briefing-line registry ----------


def test_audit_basis_partitions_the_briefing_line_registry():
    """`_AUDIT_BASIS` ∪ the named `_NO_AUDIT_BASIS` exemptions partition H401's
    `_BRIEFING_LINES` registry exactly — so a *new* briefing line fails until it
    declares an audit basis or is named exempt (the H400 registry-completeness
    mechanism on the briefing-line ↔ audit axis)."""
    assert set(_AUDIT_BASIS).isdisjoint(_NO_AUDIT_BASIS)
    assert set(_AUDIT_BASIS) | set(_NO_AUDIT_BASIS) == set(_BRIEFING_LINES)

    # sanity: the eight custody facts the spec ties (incl. the roadmap-corrected
    # `at_risk`), and the three named exemptions — non-trivial and as documented
    assert set(_AUDIT_BASIS) == {
        "headline", "attention", "at_risk", "conflicts", "archive",
        "duplicates", "posture", "refresh",
    }
    assert set(_NO_AUDIT_BASIS) == {"strength", "by_source", "concept"}


# --- the matrix guard --------------------------------------------------------


def test_every_briefing_line_equals_the_live_audit(scrolls_home):
    """Over the H401 composite fixture rendered as a whole-library-scope bundle, every
    audit-basis briefing line's fact equals the `run_doctor` custody projection —
    `_Custody:_` ≡ `tiers`, `_Attention:_` ≡ `weakest_source`, `_At-risk work:_` ≡
    `works`, `_Conflicts:_` ≡ `conflicts`, `_Archive:_` ≡ `archive`, `_Duplicates:_`
    ≡ `content_duplicates`, `_Posture:_` ≡ `posture`, `_Refresh:_` ≡
    `enrichment/summaries`. The one invariant a recipient relies on: the portable
    briefing reads exactly what the sender's audit reports."""
    main(["init"])
    db = get_paths().db_path
    _seed_every_briefing_line(db)
    md_doc = build_bundle(db, "database")
    custody = run_doctor(get_paths())["custody"]

    # the decisive choice: the bundle scope *is* the whole library — every fixture
    # title carries "database", so the query gathers every held item and the briefing
    # fold and the audit fold cover the same set (a scoped bundle has no whole-library
    # audit twin — the `_NO_AUDIT_BASIS` boundary)
    headline = _md_marker("Custody:")(md_doc)
    scope_n = int(re.search(r"Custody: (\d+) scroll", headline).group(1))
    assert scope_n == len(list_items(db)) > 0

    # the fixture is non-vacuous: every audit-basis line actually renders in the
    # bundle (a convergence check over an absent line would be a vacuous None == None),
    # and its audit twin is the matching non-default value
    for key, line in _AUDIT_BASIS.items():
        assert line["brief"](md_doc) is not None, f"{key} did not render in the bundle"

    # the audit itself is non-vacuous on every axis (so each leg has a real value to
    # land on, not a skeleton default)
    assert custody["posture"]["verdict"] == "at_risk"  # at-risk work + archive tamper
    assert _audit_tiers(custody).keys() >= {"full", "reference"}
    assert _audit_attention(custody) is not None
    assert _audit_at_risk(custody)[1] >= 1
    assert _audit_conflicts(custody) >= 1
    assert _audit_archive(custody) >= 1
    assert _audit_duplicates(custody) == (1, 2)
    assert all(_audit_refresh(custody))  # both source sets non-empty

    assert _convergence_failures(md_doc, custody) == set()


def test_a_briefing_line_folding_a_tampered_count_fails_only_that_line(
    scrolls_home, monkeypatch
):
    """Sabotage (the *tampered-count* corner): a briefing line that folds a count
    distinct from the audit fold desyncs *only* its own leg — the matrix is comparing
    the *fact*, not merely presence, and the audit side (`run_doctor`, a distinct
    module path from `bundle`) is untouched, so the divergence isolates to the
    offending line. This is the cross-surface drift the contract catches that the
    per-form H401 matrix cannot see: a briefing that disagrees with the live audit a
    recipient could re-run."""
    main(["init"])
    db = get_paths().db_path
    _seed_every_briefing_line(db)

    custody = run_doctor(get_paths())["custody"]
    assert _convergence_failures(build_bundle(db, "database"), custody) == set()

    # the `_Duplicates:_` fold renders an invented count (9 groups / 99 items) the
    # whole-library `content_duplicate_groups` audit (1 group / 2 items) never reports
    monkeypatch.setattr(
        bundle,
        "render_content_duplicates",
        lambda items, db_path=None: [
            "_Duplicates: 9 group(s) of byte-identical content (99 item(s))._", ""
        ],
    )
    assert _convergence_failures(build_bundle(db, "database"), custody) == {"duplicates"}
