"""The facet scope-composition convergence contract (roadmap H417).

The *scope*-axis sibling of H411's value-drill. Where H411
(`test_facet_aggregate_drill`) pins the **unscoped** count↔rows tie — every
`facets <dim>` count equals the rows the matching `list --<filter>` drill
enumerates — this pins the dual on the *scope* axis: that **scoping** a facet
aggregate equals **aggregating over the scoped drill**. For *every* facet
dimension and *every* scope facet, ``facets <dim> --<scope> V`` reports exactly
the same dimension recomputed over only the rows ``list --<scope> V`` returns. So
the discovery aggregate an agent browses by is a faithful index into the *scoped*
rows it then drills — not just into the whole library (the PRD "filter
consistency / completeness honesty" success metric, cap 7).

The claim, for *every* facet dimension D and *every* scope facet S with value V::

    facets D --S V  ==  the D-distribution over the items `list --S V` returns

and, for the two-facet composition, ``facets D --SA A --SB B`` equals D over the
``list --SA A --SB B`` intersection — so an ANDed scope narrows the aggregate the
same way it narrows the rows (the clause-ordering/precedence case a single-facet
test misses).

Two faces, the H388/H394/H411 shape:

1. **The completeness keystone** — ``_SCOPE_FACETS`` (the scope optionals shared
   by the live `facets` and `list` subparsers, each tied to its `items.item_filters`
   clause) is asserted ≡ the live shared scope vocabulary, minus the one named
   non-scope shared optional ``--limit`` (pagination, not a filter). So a *new*
   scope facet — added to both `facets` and `list` — fails the contract until it
   declares a composition tie. A second keystone holds the registry to
   `item_filters`' parameters and `compute_facets`' scope kwargs (the H394
   registry-completeness mechanism on the scope axis).

2. **The composition matrix** — over the H411 ``_seed_facet_drill_mix`` (four
   sources, four classification methods, the unclassified pool, two tag/concept
   groups, every fidelity tier, every drift posture, a content-duplicate pair),
   every (dimension, scope facet, value) scoped aggregate equals the dimension
   recomputed over the scoped rows; and a sabotage that drops one scope clause
   from the *facets* path (an unscoped fold behind a scoped call) desyncs *only*
   that scope facet's legs — never `list` (which keeps its own clause), so the
   independent oracle stays correct and catches the divergence.

The oracle never passes two colliding flags (``--source X --source Y``): it reads
each dimension value's whole-library id set once (the H411 ``list --<filter>``
drill, or — for the no-filter `method` dimension — the classification marker the
`list` rows already carry) and intersects it with the scope's id set in Python.
That id-intersection is a genuinely distinct code path from `compute_facets`'
single scoped SQL/Counter fold, so it has teeth against a dropped scope clause.
"""

import dataclasses
import inspect
import json

import pytest

import scrolls.facets as facets
from scrolls.cli import main
from scrolls.facets import FIELDS as FACET_FIELDS
from scrolls.facets import compute_facets
from scrolls.items import item_filters
from scrolls.paths import get_paths

# The H411 fixture + drill registry + subparser introspection — reused verbatim
# (the H417 precondition: "the H411 fixture", and the blessed cross-`test_` import
# pattern, e.g. `from test_cli_determinism import _CLI_READ_PATHS`).
from test_facet_aggregate_drill import (  # noqa: E402
    _FACET_DRILLS,
    _seed_facet_drill_mix,
    _subparser_optionals,
)


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# --- the scope-facet registry — the completeness keystone --------------------


@dataclasses.dataclass(frozen=True)
class _ScopeFacet:
    """One scope optional shared by `facets`/`list` and how to enumerate its values.

    `flag` is the `--flag` on both subparsers; `filter_param` is the
    `items.item_filters` parameter it drives. `facet_field` names the `facets`
    dimension whose entries enumerate this scope's present values (`None` for
    `--stage`, which is a scope filter with no facet dimension of its own — H411's
    "`--stage` scopes the other facets, it is not itself enumerated"); when it is
    `None`, values come from the `list` rows' `row_field` instead. `value_key` is
    the facet-entry key supplying the scope value (`slug` for concepts, which
    `--concept` matches by slug).
    """

    flag: str
    filter_param: str
    facet_field: str | None
    value_key: str = "value"
    row_field: str | None = None


_SCOPE_FACETS = {
    "--source": _ScopeFacet("--source", "source", "sources"),
    "--category": _ScopeFacet("--category", "category", "categories"),
    "--stage": _ScopeFacet("--stage", "stage", None, row_field="stage"),
    "--tag": _ScopeFacet("--tag", "tag", "tags"),
    "--concept": _ScopeFacet("--concept", "concept", "concepts", value_key="slug"),
}

# The one optional `facets`/`list` share that is *not* a scope filter — named, never
# a silent drop: `--limit` paginates each surface (per-dimension cap on `facets`,
# row cap on `list`); it narrows no item set, so it carries no `item_filters` clause.
_NON_SCOPE_SHARED = {"--limit"}


# --- thin CLI read helpers (each runs one `main` then drains capsys) ----------


def _facet_entries(field, scope_flags, capsys):
    """The `facets <field> <scope_flags>` entries (no cap) — the scoped aggregate."""
    assert main(["facets", field, "--limit", "1000", *scope_flags]) == 0
    return json.loads(capsys.readouterr().out)["facets"][field]


def _scoped_facet(field, scope_flags, capsys):
    """`facets <field> <scope_flags>` as a ``{value: count}`` dict."""
    return {e["value"]: e["count"] for e in _facet_entries(field, scope_flags, capsys)}


def _list_rows(flags, capsys):
    """The rows `list --limit 1000 <flags>` enumerates (the scoped/drilled set)."""
    assert main(["list", "--limit", "1000", *flags]) == 0
    return json.loads(capsys.readouterr().out)


def _list_ids(flags, capsys):
    """The id *set* `list --limit 1000 <flags>` enumerates."""
    return {row["id"] for row in _list_rows(flags, capsys)}


def _method_bucket_of_row(row):
    """The classification-method bucket of one `list` row (the `_method_bucket` dual).

    `facets method` buckets by the engine that stamped the category
    (`classification_view(provenance)["by"]`), else `user-set`/`unclassified`. A
    `list` row carries that same view as its `classification` marker (omitted on
    honest absence), so the bucket is recoverable row-side — the independent oracle
    for the one dimension with no row filter to drill.
    """
    classification = row.get("classification")
    if classification is not None:
        return classification["by"]
    return "user-set" if row.get("category") is not None else "unclassified"


def _value_id_sets(field, capsys):
    """``{value: set(item ids)}`` for dimension `field` over the *whole* library.

    The per-value id sets the scoped oracle intersects with a scope. Drillable
    dimensions read each value's ids from its H411 `list --<filter>` drill;
    `method` (no row filter) buckets the whole-library `list` rows by their
    classification marker; content-duplicate's non-drillable `unique` complement
    is the held set minus the duplicates.
    """
    if field == "method":
        sets: dict[str, set[str]] = {}
        for row in _list_rows([], capsys):
            sets.setdefault(_method_bucket_of_row(row), set()).add(row["id"])
        return sets

    drill = _FACET_DRILLS[field]
    sets = {}
    for entry in _facet_entries(field, [], capsys):
        flags = drill.drill_flags(entry)
        if flags is None:  # the `unique` complement — filled from the total below
            continue
        sets[entry["value"]] = _list_ids(flags, capsys)
    if field == "content-duplicate":
        sets["unique"] = _list_ids([], capsys) - sets.get("duplicate", set())
    return sets


def _expected_from(value_ids_for_field, scope_ids):
    """Dimension D recomputed over the scoped rows: ``{v: |ids(v) ∩ scope_ids|}``,
    with empty buckets dropped (the `GROUP BY`/`Counter` omit-when-zero shape)."""
    return {
        value: hit
        for value, ids in value_ids_for_field.items()
        if (hit := len(ids & scope_ids))
    }


def _scope_values(scope, capsys):
    """The scope facet's present values to drill — from its facet dimension, or (for
    `--stage`, which has no dimension) the distinct values the `list` rows carry."""
    if scope.facet_field is not None:
        return [
            str(e[scope.value_key])
            for e in _facet_entries(scope.facet_field, [], capsys)
        ]
    return sorted({row[scope.row_field] for row in _list_rows([], capsys)})


def _composition_failures(capsys):
    """The (scope flag, dimension) cells whose scoped facet aggregate disagrees with
    the dimension recomputed over the scoped rows. The matrix asserts this is empty;
    the sabotage asserts it is exactly the cells it broke."""
    value_ids = {field: _value_id_sets(field, capsys) for field in FACET_FIELDS}
    failures = set()
    for scope in _SCOPE_FACETS.values():
        for value in _scope_values(scope, capsys):
            scope_flags = [scope.flag, value]
            scope_ids = _list_ids(scope_flags, capsys)
            for field in FACET_FIELDS:
                actual = _scoped_facet(field, scope_flags, capsys)
                expected = _expected_from(value_ids[field], scope_ids)
                if actual != expected:
                    failures.add((scope.flag, field))
    return failures


# --- keystone 1: the registry covers the live shared scope vocabulary --------


def test_scope_facet_registry_partitions_the_shared_facets_list_optionals():
    """`_SCOPE_FACETS` (the scope filters) ∪ the named `_NON_SCOPE_SHARED`
    (`--limit`) partition the optionals the live `facets` and `list` subparsers
    *share* — so a *new* scope optional added to both fails the contract until it
    declares a composition tie (the H394 registry-completeness mechanism on the
    scope axis)."""
    shared = _subparser_optionals("facets") & _subparser_optionals("list")
    flags = {sf.flag for sf in _SCOPE_FACETS.values()}
    assert flags.isdisjoint(_NON_SCOPE_SHARED)
    assert flags | _NON_SCOPE_SHARED == shared, (
        f"unclassified shared optionals = {shared - flags - _NON_SCOPE_SHARED}"
    )
    # every registry key names its own flag (the key is the flag)
    assert all(key == sf.flag for key, sf in _SCOPE_FACETS.items())
    # the load-bearing distinction the registry encodes (sanity, not a tautology):
    # `--limit` is the one shared optional that scopes nothing
    assert "--limit" in shared
    assert item_filters(None, None, None, None, None) == ([], [])


def test_each_scope_facet_drives_an_item_filters_clause():
    """The registry's `filter_param`s are exactly `items.item_filters`' parameters
    and `compute_facets`' scope kwargs (the shared clause builder both surfaces fold
    through), and each scope facet alone produces exactly one clause referencing its
    own column — so the registry can never name a scope `compute_facets` does not
    honor or a clause `item_filters` does not build."""
    item_filter_params = set(inspect.signature(item_filters).parameters)
    registry_params = {sf.filter_param for sf in _SCOPE_FACETS.values()}
    assert item_filter_params == registry_params

    compute_scope_kwargs = set(inspect.signature(compute_facets).parameters) - {
        "db_path",
        "field",
        "limit",
    }
    assert compute_scope_kwargs == registry_params

    # each scope facet, set alone, yields exactly one clause naming its own column
    probe = {
        "source": "web",
        "category": "tutorial",
        "stage": "rendered",
        "tag": "Python",
        "concept": "databases",
    }
    column_token = {
        "source": "items.source",
        "category": "items.category",
        "stage": "items.stage",
        "tag": "items.tags",
        "concept": "items.concepts",
    }
    for sf in _SCOPE_FACETS.values():
        kwargs = {param: None for param in item_filter_params}
        kwargs[sf.filter_param] = probe[sf.filter_param]
        clauses, _params = item_filters(**kwargs)
        assert len(clauses) == 1, (sf.flag, clauses)
        assert column_token[sf.filter_param] in clauses[0], (sf.flag, clauses)


# --- the composition matrix --------------------------------------------------


def _assert_composition_non_vacuous(capsys):
    """Scoping genuinely narrows — each representative scoped aggregate is a strict
    subset of the whole-library one (so an ignored-scope implementation could not
    pass by accident), and every scope facet has ≥1 value to drill."""
    assert _scoped_facet("sources", [], capsys) == {
        "web": 3, "arxiv": 2, "wikipedia": 1, "crossref": 1
    }
    # scoping categories to one source narrows to that source's categories
    assert _scoped_facet("categories", ["--source", "arxiv"], capsys) == {
        "research": 1, "opinion": 1
    }
    # scoping method to one tag narrows to that tag's methods
    assert _scoped_facet("method", ["--tag", "ML"], capsys) == {
        "llm-v1": 1, "user-set": 1
    }
    # scoping drift to one source narrows the postures
    assert _scoped_facet("drift", ["--source", "web"], capsys) == {
        "verified": 1, "unverified": 2
    }
    # the unclassified pool is reachable as a scope (`--category ""` → IS NULL)
    assert _scoped_facet("sources", ["--category", ""], capsys) == {
        "wikipedia": 1, "crossref": 1
    }
    for scope in _SCOPE_FACETS.values():
        assert _scope_values(scope, capsys), scope.flag


def test_every_scoped_facet_aggregates_exactly_the_scoped_rows(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, every (dimension, scope facet, value) scoped
    aggregate equals the dimension recomputed over the rows the matching `list`
    scope enumerates — the scope-axis aggregate-as-faithful-index guarantee, pinned
    once across the whole live scope-facet × facet-dimension matrix."""
    main(["init"])
    _seed_facet_drill_mix(get_paths().db_path)
    capsys.readouterr()

    _assert_composition_non_vacuous(capsys)

    assert _composition_failures(capsys) == set()


def test_two_scope_facets_anded_aggregate_the_intersection(scrolls_home, capsys):
    """The decisive choice: an ANDed two-facet scope narrows the aggregate the same
    way it narrows the rows. `--stage rendered --source web` is a strict subset of
    *each* single-facet scope (rendered carries arxiv/wiki rows web lacks; web carries
    the `fetched` partial rendered lacks), so a clause-ordering/precedence bug that
    honored only one facet would diverge — invisible to any single-facet leg."""
    main(["init"])
    _seed_facet_drill_mix(get_paths().db_path)
    capsys.readouterr()

    scope_flags = ["--stage", "rendered", "--source", "web"]
    intersection = _list_ids(scope_flags, capsys)
    # non-vacuous: a *strict* subset of each single-facet scope (the AND truly narrows)
    assert intersection < _list_ids(["--stage", "rendered"], capsys)
    assert intersection < _list_ids(["--source", "web"], capsys)
    assert intersection  # ... and is itself non-empty

    for field in FACET_FIELDS:
        value_ids = _value_id_sets(field, capsys)
        assert _scoped_facet(field, scope_flags, capsys) == _expected_from(
            value_ids, intersection
        ), field


def test_dropping_a_scope_clause_desyncs_only_that_scope_facets_legs(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and isolates to the *scope facet*:
    silently dropping the `source` clause from the *facets* path (an unscoped fold
    behind a scoped `facets --source V` call) makes every `--source`-scoped aggregate
    over-report — it counts the whole library where the scoped rows are a strict
    subset — desyncing *all eight* `--source` dimension legs, while the other four
    scope facets (their clauses intact) stay green.

    `compute_facets` folds the scope through `facets.item_filters` (the name it
    imported); `list_items` folds through `scrolls.items`' own binding — a distinct
    object — so patching only the facets binding leaves the `list`-driven oracle
    correctly scoped and able to catch the divergence (the H411 isolated-counter
    sabotage on the scope axis)."""
    main(["init"])
    _seed_facet_drill_mix(get_paths().db_path)
    capsys.readouterr()

    assert _composition_failures(capsys) == set()  # baseline: clean

    real_item_filters = facets.item_filters

    def _drops_source_scope(source, category, stage, tag, concept):
        # the source scope is silently ignored — an unscoped fold behind the call
        return real_item_filters(None, category, stage, tag, concept)

    monkeypatch.setattr(facets, "item_filters", _drops_source_scope)

    assert _composition_failures(capsys) == {
        ("--source", field) for field in FACET_FIELDS
    }
