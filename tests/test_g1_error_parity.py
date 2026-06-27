"""The could-not-check (G1) error-parity contract (roadmap H414).

The *error-path* sibling of H400's CLI↔MCP read-parity matrix. Where H400 pins
that every read a library exposes on both transports reads its *clean* answer
identically across the (CLI command, MCP tool) twin, this pins the *failure*
shape: every read that answers about a **specific target** surfaces a
could-not-check as the **same honest, typed error** across its twin — never a
silent empty result (the M2 G1 axis, custody-vision §2.6; the PRD "completeness
honesty / could-not-check ≠ empty" success metric, cap 7).

Two kinds of target a read can fail to resolve:

1. **An unknown id** — `show`/`get_scroll`, `related`/`get_related_scrolls`,
   `history`/`get_scroll_history`, `works <ref>`/`get_works`,
   `archive show`/`get_archived`. Both transports run the *same*
   `resolve_item_id` → `get_item` lookup and raise the *same* `ValueError`
   string; the CLI wraps it into its ``{"error": …}`` stderr envelope (exit 1),
   MCP surfaces it as a raised `ValueError`. So the messages are byte-identical
   by construction — this contract pins that "≡" so a future divergence (one
   transport swallowing the miss into an empty result) fails *its* twin's leg.

2. **An unknown closed-vocab value** — `--fidelity`/`--drift`/`--strength` on
   `search`/`list`/`related` (+ the MCP twins). A bad value is rejected as a
   *typed* error on both transports, never a silent empty neighbourhood/result.

**Roadmap correction (the H404/H407/H409/H412/H413 precedent).** The H414 spec
said *both* axes assert "CLI (stderr error envelope, exit 1) and MCP (raised
`ValueError`) carry the same error class/message." That is true for the **id**
axis but *not* the **vocab** axis: a bad `--fidelity`/`--drift`/`--strength`
value is caught by argparse `choices` (`SystemExit(2)`, a usage message on
stderr) *before* the library is ever touched — it never reaches the JSON
``{"error": …}`` envelope (exit 1) the engine `ValueError` would produce. So on
the vocab axis the two transports reject at *different layers* (CLI argparse vs
MCP engine), and the meaningful cross-transport parity is **structural**: both
enforce the *same closed vocabulary* (the CLI argparse `choices` tuple equals the
engine vocabulary constant the MCP path validates against), so a value rejected
by one is rejected by the other — and *neither* ever returns a silent empty.

Four faces, the H388/H394/H396/H397/H400 shape:

1. **The completeness keystone** — `_G1_TWINS` (the id-resolving + vocab-validating
   read twins) ∪ a named `_NO_G1_AXIS` set (reads with no specific target to miss:
   whole-library reads, the free-text-query bundle, and the MCP-only renders with
   no CLI twin) must partition `_MCP_READ_TOOLS` (H388) *exactly*, so a *new* read
   tool fails the contract until it declares its error parity (or a named
   exemption). Each declared CLI twin is held to the live CLI read registry
   (`_CLI_READ_PATHS`/H394), and every G1 twin is tied to H400's twin universe
   (it is not `_MCP_ONLY` — there *is* a CLI side to compare).

2. **The id matrix** — over a real non-empty library, each id twin's unknown-id
   error reads identically across CLI and MCP; a sabotage that swallows the miss
   into an empty result on one surface fails *only* that twin's leg.

3. **The vocab matrix** — each (surface, closed-vocab option) leg rejects a bad
   value loudly on both transports (MCP `ValueError` naming the value, CLI
   argparse `SystemExit(2)` usage), never a silent empty; a sabotage that swallows
   a bad value on one surface fails *only* that surface's legs.

4. **The structural vocabulary parity** — the CLI argparse `choices` for each
   (surface, option) equals the engine vocabulary constant, so both transports
   reject the same value-set (the only cross-transport parity the vocab axis can
   carry, given the layer split above).
"""

import json

import pytest

import scrolls.mcp_server as mcp_server
from scrolls.cli import build_parser, main
from scrolls.custody import DRIFT_POSTURES, FIDELITY_TIERS
from scrolls.items import ScrollItem, insert_item
from scrolls.paths import get_paths
from scrolls.related import RELATION_STRENGTH_BANDS
from scrolls.search import STRENGTH_BANDS

# The read registries the H388/H394/H400 contracts hold to the live MCP / argparse
# surfaces. Keying the twin classification to `_MCP_READ_TOOLS` makes a *new* MCP
# read tool force a G1-or-exempt decision here (it first fails H388 until
# registered, then H400 until twinned, then this contract until classified);
# `_MCP_ONLY` ties every G1 twin to a CLI side it can be compared against.
from test_cli_determinism import _CLI_READ_PATHS  # noqa: E402
from test_cli_mcp_parity import _MCP_ONLY as _H400_MCP_ONLY  # noqa: E402
from test_mcp import _MCP_READ_TOOLS  # noqa: E402


# --- The fixture: a real, non-empty, fully offline library -------------------
#
# The could-not-check inputs (an unknown id, a bad vocab value) don't depend on
# the library's custody shape — only that a *real* library was checked and the
# target genuinely missed. A held anchor (`_HELD_ID`) lets the `related` vocab
# legs pass id-resolution and reach the closed-vocab validation.

_HELD_ID = "web:held"
_UNKNOWN_ID = "web:does-not-exist"
_BAD_VALUE = "nonesuch"  # in no closed vocabulary
_QUERY = "alpha"  # matches the seeded text (irrelevant once the vocab is rejected)


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


def _item(item_id, **overrides):
    base = dict(
        id=item_id,
        source=item_id.split(":")[0],
        url=f"https://example.org/{item_id}",
        saved_at="2026-06-12T00:00:00+00:00",
        title=item_id,
        extracted_text="alpha beta gamma delta",
        summary="alpha beta gamma delta",
        stage="fetched",
    )
    base.update(overrides)
    return ScrollItem(**base)


@pytest.fixture
def populated(scrolls_home):
    """A non-empty offline library: a held anchor plus a second source.

    Deliberately populated so a could-not-check proves the surface *looked at a
    real library and the target missed* — not merely that the store was empty.
    """
    main(["init"])
    db = get_paths().db_path
    insert_item(db, _item(_HELD_ID))
    insert_item(db, _item("arxiv:other", url="https://arxiv.org/abs/other"))
    return db


# --- The twin registries — the completeness keystone -------------------------

# The id-resolving read twins: each answers about one item id and raises the same
# `ValueError` on a miss across both transports (the CLI argv prefix, and the MCP
# callable taking the id). `get_works`'s targeted form is `works <ref>` /
# `get_works(item=…)`; `archive show` / `get_archived` carry their own
# "no archived prior capture" miss message (still byte-identical across transports).
_ID_TWINS = {
    "get_scroll": {
        "cli": ("show",),
        "mcp": lambda item_id: mcp_server.get_scroll(item_id),
    },
    "get_related_scrolls": {
        "cli": ("related",),
        "mcp": lambda item_id: mcp_server.get_related_scrolls(item_id),
    },
    "get_scroll_history": {
        "cli": ("history",),
        "mcp": lambda item_id: mcp_server.get_scroll_history(item_id),
    },
    "get_works": {
        "cli": ("works",),
        "mcp": lambda item_id: mcp_server.get_works(item=item_id),
    },
    "get_archived": {
        "cli": ("archive", "show"),
        "mcp": lambda item_id: mcp_server.get_archived(item_id),
    },
}

# The vocab-validating read twins: each carries closed-vocab `--fidelity`/`--drift`
# (and, where it ranks, `--strength`) options, with the engine vocabulary constant
# the MCP path validates against. `list` does not rank, so it carries no
# `--strength`; `search` and `related` use distinct strength vocabularies
# (`STRENGTH_BANDS` vs `RELATION_STRENGTH_BANDS`), both ("strong","moderate","weak").
_VOCAB_TWINS = {
    "search_scrolls": {
        "cli": ("search",),
        "options": {
            "fidelity": FIDELITY_TIERS,
            "drift": DRIFT_POSTURES,
            "strength": STRENGTH_BANDS,
        },
        "cli_vocab": lambda opt, val: ["search", _QUERY, "--" + opt, val],
        "mcp_vocab": lambda opt, val: mcp_server.search_scrolls(_QUERY, **{opt: val}),
    },
    "list_scrolls": {
        "cli": ("list",),
        "options": {"fidelity": FIDELITY_TIERS, "drift": DRIFT_POSTURES},
        "cli_vocab": lambda opt, val: ["list", "--" + opt, val],
        "mcp_vocab": lambda opt, val: mcp_server.list_scrolls(**{opt: val}),
    },
    "get_related_scrolls": {
        "cli": ("related",),
        "options": {
            "fidelity": FIDELITY_TIERS,
            "drift": DRIFT_POSTURES,
            "strength": RELATION_STRENGTH_BANDS,
        },
        "cli_vocab": lambda opt, val: ["related", _HELD_ID, "--" + opt, val],
        "mcp_vocab": lambda opt, val: mcp_server.get_related_scrolls(
            _HELD_ID, **{opt: val}
        ),
    },
}

_G1_TWINS = set(_ID_TWINS) | set(_VOCAB_TWINS)

# Reads with *no specific target to miss* — they answer about the whole library or
# carry no id/closed-vocab to resolve, so there is no could-not-check to compare:
#   - whole-library aggregates/rosters/ledgers (no anchoring target);
#   - the free-text-query bundle (a blank query's could-not-check is pinned in
#     `test_completeness.py`; it has no id to resolve);
#   - the MCP-only compiled-page renders + rosters (no CLI twin to compare against,
#     so no cross-transport error parity — exactly H400's `_MCP_ONLY`).
_NO_G1_AXIS = {
    "list_facets": "whole-library aggregate; no specific target to miss",
    "get_link_graph": "whole-library link structure; no anchoring id",
    "get_library_health": "whole-library audit; no specific target",
    "get_maintenance_history": "whole-library maintenance ledger; no target",
    "list_archived": "whole-library archive roster; no target (one item is `get_archived`)",
    "get_context_bundle": "free-text-query bundle; no id to resolve — the blank-query "
    "could-not-check is pinned in test_completeness.py",
    "get_concept_page": "MCP-only compiled `library/concepts/*` render; no CLI twin",
    "get_tag_page": "MCP-only compiled `library/tags/*` render; no CLI twin",
    "list_sources": "MCP-only source roster; no CLI read twin",
    "list_feed_subscriptions": "MCP-only feed roster; no CLI read twin",
}


def _vocab_legs():
    """Every (tool, option, engine-constant) closed-vocab leg, sorted."""
    legs = []
    for tool, spec in _VOCAB_TWINS.items():
        for opt, constant in spec["options"].items():
            legs.append((tool, opt, constant))
    return sorted(legs, key=lambda leg: (leg[0], leg[1]))


def test_g1_twin_registry_partitions_the_mcp_read_surface():
    """Every MCP read tool is a G1 twin or a *named* `_NO_G1_AXIS` exemption — so a
    *new* read tool fails until it declares its error parity. The H388/H400
    registry-completeness mechanism on the could-not-check axis."""
    g1 = set(_G1_TWINS)
    exempt = set(_NO_G1_AXIS)
    # the two classes are disjoint ...
    assert g1.isdisjoint(exempt)
    # ... and together cover the live MCP read surface exactly (H388)
    assert g1 | exempt == set(_MCP_READ_TOOLS)

    # sanity: the matrices are the targeted reads the spec names, non-trivial (an
    # emptied registry would pass the partition only if `_NO_G1_AXIS` absorbed them)
    assert set(_ID_TWINS) == {
        "get_scroll",
        "get_related_scrolls",
        "get_scroll_history",
        "get_works",
        "get_archived",
    }
    assert set(_VOCAB_TWINS) == {"search_scrolls", "list_scrolls", "get_related_scrolls"}


def test_every_g1_twin_has_a_cli_side_to_compare():
    """Each G1 twin is *not* MCP-only (H400's `_MCP_ONLY`) — there is a CLI command
    to compare its error against — and each declared CLI twin path is a *registered*
    CLI read (`_CLI_READ_PATHS`/H394), so the registry can never name a phantom
    command. The "fails until *both* contracts register it" tie (the MCP half is the
    partition above)."""
    assert set(_G1_TWINS).isdisjoint(_H400_MCP_ONLY)
    # every MCP-only read is therefore a named no-G1 exemption (no CLI twin → no parity)
    assert set(_H400_MCP_ONLY) <= set(_NO_G1_AXIS)

    live = {" ".join(path) for path in _CLI_READ_PATHS}
    declared = {" ".join(spec["cli"]) for spec in _ID_TWINS.values()}
    declared |= {" ".join(spec["cli"]) for spec in _VOCAB_TWINS.values()}
    assert declared <= live


# --- The id matrix: same typed error across transports -----------------------


def _cli_error_or_none(argv, capsys):
    """The CLI error message for a could-not-check, or None if it didn't fail loudly.

    A loud could-not-check is exit 1, empty stdout, and a parseable
    ``{"error": …}`` envelope on stderr (the H398 contract). Anything else — a
    success, an empty result, a non-envelope — reads as None (a swallowed miss).
    """
    capsys.readouterr()
    try:
        code = main(list(argv))
    except SystemExit as exc:  # never expected on the id axis; reads as "not exit 1"
        code = exc.code
    captured = capsys.readouterr()
    if code != 1 or captured.out != "":
        return None
    try:
        payload = json.loads(captured.err)
    except (json.JSONDecodeError, ValueError):
        return None
    return payload.get("error")


def _mcp_error_or_none(thunk):
    """The MCP `ValueError` message a could-not-check raises, or None if it returned
    a value instead (the silent-empty regression the contract forbids)."""
    try:
        thunk()
    except ValueError as exc:
        return str(exc)
    return None


def _id_parity_failures(capsys):
    """The set of id twins whose CLI and MCP unknown-id errors disagree.

    A twin "fails" if either transport swallowed the miss (None) or the two typed
    messages differ. The matrix asserts this is empty; the sabotage asserts it is
    exactly the one twin it broke.
    """
    failures = set()
    for tool, spec in _ID_TWINS.items():
        cli_msg = _cli_error_or_none(list(spec["cli"]) + [_UNKNOWN_ID], capsys)
        mcp_msg = _mcp_error_or_none(lambda spec=spec: spec["mcp"](_UNKNOWN_ID))
        if cli_msg is None or mcp_msg is None or cli_msg != mcp_msg:
            failures.add(tool)
    return failures


def test_unknown_id_is_the_same_typed_error_on_both_transports(populated, capsys):
    """Over a real non-empty library, each id twin reports an unknown id with the
    *same* typed message on CLI (``{"error": …}`` exit 1) and MCP (`ValueError`) —
    `show`≡`get_scroll`, `related`≡`get_related_scrolls`, `history`≡
    `get_scroll_history`, `works <ref>`≡`get_works`, `archive show`≡`get_archived`.

    The decisive choice (the spec's): compare the *typed* message, not mere
    non-zero exit — a generic catch-all that lost the `no such item: X` distinction
    would fail even while still exiting non-zero."""
    assert _id_parity_failures(capsys) == set()

    # sanity: the parity is over a *real* miss message, not 0 == 0 — the shared
    # lookup names the resolved id, so the message is non-empty and id-bearing.
    msg = _mcp_error_or_none(lambda: mcp_server.get_scroll(_UNKNOWN_ID))
    assert msg and _UNKNOWN_ID in msg


def test_one_surface_swallowing_the_unknown_id_error_fails_only_its_leg(
    populated, capsys, monkeypatch
):
    """The sabotage proves the id matrix has teeth and is *isolating*: one surface
    swallowing the miss into an empty result (a silent could-not-check) fails *only*
    that twin's leg, never its siblings.

    `mcp_server.get_scroll` is the binding the `get_scroll`≡`show` twin reads
    through — distinct from every other twin's MCP function — so wrapping it to
    return ``{}`` on a miss instead of raising desyncs only `get_scroll`."""
    assert _id_parity_failures(capsys) == set()

    real_get_scroll = mcp_server.get_scroll

    def _swallow(item_id):
        try:
            return real_get_scroll(item_id)
        except ValueError:
            return {}  # a silent could-not-check — the exact regression G1 forbids

    monkeypatch.setattr(mcp_server, "get_scroll", _swallow)

    assert _id_parity_failures(capsys) == {"get_scroll"}


# --- The vocab matrix: a typed rejection on both transports ------------------


def _cli_rejects_vocab(argv, capsys):
    """True iff the CLI rejected a bad closed-vocab value loudly: argparse
    `SystemExit(2)`, an ``invalid choice`` usage message on stderr, empty stdout —
    never a silent empty result."""
    capsys.readouterr()
    try:
        code = main(list(argv))
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code == 2 and captured.out == "" and "invalid choice" in captured.err


def _vocab_failures(capsys):
    """The set of (tool, option) legs whose bad-value rejection isn't typed-and-loud
    on *both* transports. A leg fails if MCP returned instead of raising (or raised
    without naming the value) or the CLI didn't reject loudly."""
    failures = set()
    for tool, spec in _VOCAB_TWINS.items():
        for opt in spec["options"]:
            mcp_msg = _mcp_error_or_none(
                lambda spec=spec, opt=opt: spec["mcp_vocab"](opt, _BAD_VALUE)
            )
            mcp_ok = mcp_msg is not None and _BAD_VALUE in mcp_msg
            cli_ok = _cli_rejects_vocab(spec["cli_vocab"](opt, _BAD_VALUE), capsys)
            if not (mcp_ok and cli_ok):
                failures.add((tool, opt))
    return failures


def test_bad_vocab_value_is_a_typed_rejection_on_both_transports(populated, capsys):
    """Every `--fidelity`/`--drift`/`--strength` leg rejects a bad value loudly on
    both transports — MCP a `ValueError` naming the value, CLI an argparse
    `SystemExit(2)` usage — never a silent empty result. (Roadmap correction: the
    CLI rejects at the argparse layer, exit 2, *not* the JSON envelope exit 1 the
    spec assumed; the engine `ValueError` it would raise is unreachable behind
    `choices`.)"""
    assert _vocab_failures(capsys) == set()

    # sanity: the legs span all three options across the ranking surfaces (8 legs)
    assert _vocab_legs() == sorted(
        [
            ("search_scrolls", "fidelity", FIDELITY_TIERS),
            ("search_scrolls", "drift", DRIFT_POSTURES),
            ("search_scrolls", "strength", STRENGTH_BANDS),
            ("list_scrolls", "fidelity", FIDELITY_TIERS),
            ("list_scrolls", "drift", DRIFT_POSTURES),
            ("get_related_scrolls", "fidelity", FIDELITY_TIERS),
            ("get_related_scrolls", "drift", DRIFT_POSTURES),
            ("get_related_scrolls", "strength", RELATION_STRENGTH_BANDS),
        ],
        key=lambda leg: (leg[0], leg[1]),
    )


def test_one_surface_swallowing_a_bad_vocab_value_fails_only_its_legs(
    populated, capsys, monkeypatch
):
    """The vocab sabotage proves isolation: one surface swallowing a bad value into
    an empty list fails *only* that surface's legs.

    `mcp_server.search_scrolls` is the binding the `search` vocab legs validate
    through — distinct from `list_scrolls`/`get_related_scrolls` — so wrapping it to
    return ``[]`` on a bad value desyncs only `search_scrolls`'s three legs."""
    assert _vocab_failures(capsys) == set()

    real_search = mcp_server.search_scrolls

    def _swallow(query, **kwargs):
        try:
            return real_search(query, **kwargs)
        except ValueError:
            return []  # a silent could-not-check on a bad vocab value

    monkeypatch.setattr(mcp_server, "search_scrolls", _swallow)

    assert _vocab_failures(capsys) == {
        ("search_scrolls", "fidelity"),
        ("search_scrolls", "drift"),
        ("search_scrolls", "strength"),
    }


# --- The structural vocabulary parity ----------------------------------------


def _option_choices(subcommand, option):
    """The argparse `choices` tuple for `--option` on a single-level subcommand."""
    import argparse

    parser = build_parser()
    sub = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ).choices[subcommand]
    action = next(a for a in sub._actions if option in a.option_strings)
    return tuple(action.choices) if action.choices is not None else None


def test_cli_argparse_choices_equal_the_engine_vocabulary():
    """The CLI's declarative `choices` for each `--fidelity`/`--drift`/`--strength`
    equals the engine vocabulary constant the MCP path validates against — so both
    transports reject the *same* value-set. This is the only cross-transport parity
    the vocab axis can carry (the messages differ by layer); a drift between the CLI
    literal and the engine constant (one accepts a value the other rejects) fails
    here."""
    for tool, spec in _VOCAB_TWINS.items():
        subcommand = spec["cli"][0]
        for opt, constant in spec["options"].items():
            choices = _option_choices(subcommand, "--" + opt)
            assert choices == tuple(constant), (tool, opt, choices, constant)
