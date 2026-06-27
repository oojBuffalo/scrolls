"""The facet-aggregate drill contract (roadmap H411) — one completeness-asserted invariant.

The eighteenth **contract-consolidation** cell (after H388's whole-MCP
determinism contract … H410's stale-set drill) and the *aggregate↔enumeration*
completion of H403's browse-filter drill matrix. Where H403 pins that **drilling**
from the unfiltered browse surface by a custody/rank filter returns exactly the
rows that surface carries at the filter's value, this pins the dual: that the
**aggregate** an agent browses by — `scrolls facets <dimension>` — is a faithful
*index* into the rows it can then drill. For *every* facet value, the count the
discovery surface reports equals exactly the number of rows the matching
`list`/`search` value-filter enumerates at that value (the PRD "filter
consistency / completeness honesty" success metric, cap 7).

The claim, for *every* facet dimension that carries a row filter
(`sources`/`categories`/`tags`/`concepts`/`fidelity`/`drift`/`content-duplicate`):
`count_facets(field)[value] == len(list --<filter> value) == len(search alpha
--<filter> value)`. So an agent that reads "23 items are `drifted`" off the
aggregate and then drills `list --drift drifted` is promised exactly 23 rows — the
facet vocabulary never over- or under-counts what the filter can show.

Two faces, the H388/H394/H403 shape:

1. **The completeness keystone** — `_FACET_DRILLS` (each drillable dimension × its
   `list`/`search` filter) ∪ a *named* `_NO_DRILL_FACETS` set partition the live
   `facets` field choices *exactly*, so a *new* facet dimension fails the contract
   until it declares a drill (or is named no-drill). The one named exemption is
   `method`: the classification-method aggregate has no `--method` row filter
   (provenance is a re-derivable enrichment view, not a browse filter). A second
   keystone holds each declared drill flag to the live `list`/`search` subparser
   optionals (the H394 registry-completeness mechanism on the facet axis).

   **Roadmap correction (the H404/H407 precedent):** the H411 spec's parenthetical
   listed a `stages` dimension and omitted `method` — but the live `facets.FIELDS`
   carries *no* `stages` dimension (`--stage` scopes the *other* facets, it is not
   itself enumerated), and `method` is the genuine no-drill exemption. The keystone
   is driven off the live vocabulary, not the prose, so the registry matches the code.

2. **The drill matrix** — over one wide non-vacuous fixture (four sources, four
   classification methods, the unclassified pool, two tag/concept groups with case
   variants, every fidelity tier, every drift posture, and a content-duplicate
   pair), every (dimension, value) count equals both the `list` and the `search`
   drill it indexes; and a sabotage that inflates one dimension's facet counter
   desyncs *only* that dimension's two legs (the `_fidelity_counts` derivation,
   distinct from `list_items`/`search_items`' own `fidelity_tier` filter).
"""

import argparse
import dataclasses
import json

import pytest

import scrolls.facets as facets
from scrolls.cli import build_parser, main
from scrolls.custody import CustodyEvent, record_events
from scrolls.facets import FIELDS as FACET_FIELDS
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths

# Every title carries this token so `search QUERY` enumerates the whole library —
# the same scope `list` (and the unscoped `facets` counts) read, so the search
# drill, the list drill, and the facet count share one denominator.
QUERY = "alpha"


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


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


_RULES = {"classified_by": "rules-v1", "classified_basis": "domain"}
_LLM = {"classified_by": "llm-v1", "classified_model": "claude-x"}


def _seed_facet_drill_mix(db):
    """A wide library where every facet dimension carries ≥2 drillable values.

    So the drill below is real (an all-one-value library would pass a mis-derived
    count too). Each axis spans its vocabulary:

    - **sources** — `web` (3), `arxiv` (2), `wikipedia` (1), `crossref` (1);
    - **categories** — `tutorial` (3), `research` (1), `opinion` (1), and the
      unclassified pool reported as `""` (2);
    - **fidelity** — `full` (5, raw/extracted + hash, captured), `partial` (1,
      extracted-only, no hash), `reference` (1, a title-only pointer);
    - **drift** — all five postures: `verified`, `unverified`, `drifted`, `rotted`,
      `error`;
    - **method** — `rules-v1` (3), `llm-v1` (1), `user-set` (1, a category with no
      engine stamp), `unclassified` (2, no category);
    - **tags** — `Python`/`python` case-folds to one group (3 items), `ML` (2);
    - **concepts** — `Databases`/`databases` merges by slug (3), `Machine Learning`
      (2);
    - **content-duplicate** — `web:dup1`/`web:dup2` are byte-identical (one
      `content_hash`) → the only duplicate pair; every other item is unique.
    """
    insert_item(db, _item(
        "web:dup1", "Alpha database dup one",
        extracted_text="same dup body", raw_text="<raw>dup</raw>",
        content_hash="sha256:dup", stage="rendered",
        category="tutorial", provenance=_RULES,
        tags=("Python",), concepts=("Databases",)))
    insert_item(db, _item(
        "web:dup2", "Alpha database dup two",
        extracted_text="same dup body", raw_text="<raw>dup</raw>",
        content_hash="sha256:dup", stage="rendered",
        category="tutorial", provenance=_RULES,
        tags=("python",), concepts=("databases",)))
    insert_item(db, _item(
        "web:partial", "Alpha partial note",
        extracted_text="alpha partial body",
        category="tutorial", provenance=_RULES,
        tags=("Python",), concepts=("Databases",)))
    insert_item(db, _item(
        "arxiv:ml", "Alpha learning paper", source="arxiv",
        url="https://arxiv.org/abs/ml", extracted_text="alpha ml body",
        raw_text="<raw>ml</raw>", content_hash="sha256:ml", stage="rendered",
        category="research", provenance=_LLM,
        tags=("ML",), concepts=("Machine Learning",)))
    insert_item(db, _item(
        "arxiv:op", "Alpha opinion essay", source="arxiv",
        url="https://arxiv.org/abs/op", extracted_text="alpha op body",
        raw_text="<raw>op</raw>", content_hash="sha256:op", stage="rendered",
        category="opinion",  # a hand-set category, no provenance → user-set
        tags=("ML",), concepts=("Machine Learning",)))
    insert_item(db, _item(
        "wikipedia:bare", "Alpha wiki page", source="wikipedia",
        url="https://en.wikipedia.org/wiki/Alpha", raw_text="<raw>wk</raw>",
        content_hash="sha256:wk", stage="rendered"))  # no category → unclassified
    insert_item(db, _item(
        "crossref:ref", "Alpha crossref pointer", source="crossref",
        url="https://example.org/crossref-ref"))  # reference tier, unclassified
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


# --- the facet-drill registry — the completeness keystone --------------------


@dataclasses.dataclass(frozen=True)
class _FacetDrill:
    """One facet dimension and how to drill a value of it on `list`/`search`.

    `flag` is the `--flag` on both subparsers. `kind` chooses the drill semantics:
    `value` (a `--flag VALUE` filter selects exactly that value's rows) or `flag`
    (a `store_true` flag selecting one named value — `flag_value` — its complement
    carrying no inverse filter). `arg_key` is the facet-entry key supplying the
    drill argument: `value` for most, but `slug` for `concepts` (the `--concept`
    filter matches by slug, and the facet entry exposes it).
    """

    field: str
    flag: str
    kind: str
    flag_value: str | None = None
    arg_key: str = "value"

    def drill_flags(self, entry: dict) -> list[str] | None:
        """The argv flags to drill this facet entry, or None if it is not drillable
        (the `unique` complement of a `flag`-kind dimension)."""
        if self.kind == "flag":
            return [self.flag] if entry["value"] == self.flag_value else None
        return [self.flag, str(entry[self.arg_key])]


_FACET_DRILLS = {
    "sources": _FacetDrill("sources", "--source", "value"),
    "categories": _FacetDrill("categories", "--category", "value"),
    "tags": _FacetDrill("tags", "--tag", "value"),
    "concepts": _FacetDrill("concepts", "--concept", "value", arg_key="slug"),
    "fidelity": _FacetDrill("fidelity", "--fidelity", "value"),
    "drift": _FacetDrill("drift", "--drift", "value"),
    "content-duplicate": _FacetDrill(
        "content-duplicate", "--content-duplicate", "flag", flag_value="duplicate"),
}

# The facet dimensions with an aggregate but *no* `list`/`search` row filter —
# each named, never a silent skip. `method` buckets the library by the engine that
# produced each category (`rules-v1`/`llm-v1`/`user-set`/`unclassified`); there is
# no `--method` filter because provenance is a re-derivable enrichment *view*
# (roadmap H20/H21), not a browse filter the agent narrows by.
_NO_DRILL_FACETS = {
    "method": "classification-method aggregate; no `--method` row filter "
              "(provenance is a re-derivable enrichment view, not a browse filter)",
}


def _subparser_optionals(command):
    """The `--flag` optionals of one live subparser (minus argparse's `--help`)."""
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    cmd = sub.choices[command]
    flags = set()
    for action in cmd._actions:
        for opt in action.option_strings:
            if opt.startswith("--") and opt != "--help":
                flags.add(opt)
    return flags


def _live_facet_fields():
    """The live `facets` subparser field choices — the source-of-truth vocabulary."""
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    field_arg = next(a for a in sub.choices["facets"]._actions if a.dest == "field")
    return set(field_arg.choices)


# --- keystone 1: the registry covers the live facet vocabulary ---------------


def test_facet_drill_registry_partitions_the_live_facet_vocabulary():
    """`_FACET_DRILLS` (the drillable dimensions) ∪ `_NO_DRILL_FACETS` partition the
    live `facets` field choices *exactly* — so a *new* facet dimension fails the
    contract until it declares a drill or is named no-drill. The H394
    registry-completeness mechanism on the facet axis."""
    live = _live_facet_fields()
    # the source-of-truth vocabulary is the live argparse choices == facets.FIELDS
    assert live == set(FACET_FIELDS)
    drill = set(_FACET_DRILLS)
    no_drill = set(_NO_DRILL_FACETS)
    assert drill.isdisjoint(no_drill)
    assert drill | no_drill == live, (
        f"unclassified={live - drill - no_drill}"
    )
    # the load-bearing distinction the registry encodes (sanity, not a tautology):
    # `method` is the one dimension with an aggregate but no row filter
    assert "method" in no_drill
    assert "--method" not in (
        _subparser_optionals("list") | _subparser_optionals("search")
    )
    # every drill dimension's `field` names itself (the registry key is the field)
    assert all(key == drill_.field for key, drill_ in _FACET_DRILLS.items())


def test_every_facet_drill_flag_exists_on_list_and_search():
    """Each declared drill flag is a real optional on *both* the `list` and `search`
    subparsers — so the registry can never point a dimension at a flag the surface
    does not carry (the H403 flag-existence tie on the facet axis)."""
    list_flags = _subparser_optionals("list")
    search_flags = _subparser_optionals("search")
    for drill in _FACET_DRILLS.values():
        assert drill.flag in list_flags, (drill.field, drill.flag, "missing on list")
        assert drill.flag in search_flags, (drill.field, drill.flag, "missing on search")


# --- the drill matrix --------------------------------------------------------


def _facet_entries(field, capsys):
    """The `facets <field>` entries (no cap) — the aggregate an agent browses by."""
    assert main(["facets", field, "--limit", "1000"]) == 0
    payload = json.loads(capsys.readouterr().out)
    return payload["facets"][field]


def _list_count(flags, capsys):
    """How many rows `list --limit 1000 <flags>` enumerates — the drillable rows."""
    assert main(["list", "--limit", "1000", *flags]) == 0
    return len(json.loads(capsys.readouterr().out))


def _search_count(flags, capsys):
    """How many rows `search QUERY --limit 1000 <flags>` enumerates."""
    assert main(["search", QUERY, "--limit", "1000", *flags]) == 0
    return len(json.loads(capsys.readouterr().out))


def _drill_failures(capsys):
    """The set of (surface, dimension) cells whose facet count disagrees with the
    rows the matching drill enumerates. The matrix asserts this is empty; the
    sabotage asserts it is exactly the cells it broke."""
    failures = set()
    for field, drill in _FACET_DRILLS.items():
        for entry in _facet_entries(field, capsys):
            flags = drill.drill_flags(entry)
            if flags is None:  # the non-drillable `unique` complement
                continue
            count = entry["count"]
            if count != _list_count(flags, capsys):
                failures.add(("list", field))
            if count != _search_count(flags, capsys):
                failures.add(("search", field))
    return failures


def _assert_fixture_non_vacuous(capsys):
    """Every facet dimension spans ≥2 drillable values, the value-kind dimensions
    partition the 7 held items, and the content-duplicate pair is real — so a
    mis-derived count has a wrong number to land on (not 0 == 0)."""
    held = 7
    counts = {
        field: {e["value"]: e["count"] for e in _facet_entries(field, capsys)}
        for field in FACET_FIELDS
    }
    assert counts["sources"] == {"web": 3, "arxiv": 2, "wikipedia": 1, "crossref": 1}
    assert counts["categories"] == {"tutorial": 3, "research": 1, "opinion": 1, "": 2}
    assert counts["fidelity"] == {"full": 5, "partial": 1, "reference": 1}
    assert counts["drift"] == {
        "verified": 1, "unverified": 3, "drifted": 1, "rotted": 1, "error": 1}
    assert counts["method"] == {
        "rules-v1": 3, "llm-v1": 1, "user-set": 1, "unclassified": 2}
    assert counts["tags"] == {"Python": 3, "ML": 2}
    assert counts["concepts"] == {"Databases": 3, "Machine Learning": 2}
    assert counts["content-duplicate"] == {"duplicate": 2, "unique": 5}

    # the value-kind dimensions (one value per item) partition the whole library
    for field in ("sources", "categories", "fidelity", "drift"):
        assert sum(counts[field].values()) == held, field
    # content-duplicate's two values partition the held set even though only
    # `duplicate` is drillable (the `unique` complement has no inverse filter)
    assert sum(counts["content-duplicate"].values()) == held
    # the search query really enumerates the whole library — the shared denominator
    assert _search_count([], capsys) == held
    assert _list_count([], capsys) == held


def test_every_facet_count_indexes_exactly_its_drillable_rows(scrolls_home, capsys):
    """Over the wide non-vacuous fixture, every (dimension, value) facet count equals
    exactly the number of rows the matching `list` and `search` value-filter
    enumerates — the aggregate-as-faithful-index guarantee, pinned once across the
    whole live facet vocabulary."""
    main(["init"])
    db = get_paths().db_path
    _seed_facet_drill_mix(db)
    capsys.readouterr()

    _assert_fixture_non_vacuous(capsys)

    assert _drill_failures(capsys) == set()


def test_a_facet_counter_double_counting_one_value_fails_only_that_dimension(
    scrolls_home, capsys, monkeypatch
):
    """The sabotage proves the matrix has teeth and isolates to the *dimension*:
    inflating the `fidelity` facet's `full` bucket by one desyncs *only* the two
    fidelity legs (the count an agent browses by over-promises the rows the drill
    can show), not its sources/drift/method/… siblings.

    `facets._fidelity_counts` is the derivation the `fidelity` *aggregate* folds
    through — a distinct code path from `list_items`/`search_items`' own
    `fidelity_tier` row filter — so an inflated count diverges from the rows both
    drills enumerate at `full`, on both surfaces, while every other dimension
    (its own counter, its own filter) stays green."""
    main(["init"])
    db = get_paths().db_path
    _seed_facet_drill_mix(db)
    capsys.readouterr()

    # baseline: clean
    assert _drill_failures(capsys) == set()

    real_fidelity_counts = facets._fidelity_counts

    def _inflated(conn, where, params, limit):
        entries = real_fidelity_counts(conn, where, params, limit)
        for entry in entries:
            if entry["value"] == "full":
                entry["count"] += 1
        return entries

    monkeypatch.setattr(facets, "_fidelity_counts", _inflated)

    assert _drill_failures(capsys) == {("list", "fidelity"), ("search", "fidelity")}
