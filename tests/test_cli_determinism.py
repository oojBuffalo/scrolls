"""H394 — the CLI read-surface determinism contract.

The CLI sibling of H388's whole MCP read-surface determinism contract, and the
first **contract-consolidation** cell. Where H388 retired the per-tool MCP
determinism twins, this retires the per-command CLI determinism twins (H375
`doctor`, H376 `context`, H377 `maintain`, H378 `bundle html`, H379 `export
items` each shipped as a hand-written cell): one completeness-asserted guard
over *every* CLI JSON read command at once, byte-identical across two
same-process reads AND across a `PYTHONHASHSEED` subprocess pair.

The **completeness keystone** (`_CLI_READ_COMMANDS` + the classified
write/exempt split, the argparse-subcommand analogue of `_MCP_READ_TOOLS` /
H364): every registered subcommand must be a classified read or write, so a
*new* read subcommand fails the contract until it is given a determinism call —
coverage holds by construction, the M2/H364 registry-completeness mechanism
lifted to the CLI determinism axis (the mechanism that ends the per-command
twin treadmill).

Determinism rationale (the H375/H388 precedent): a `set` leaking into any read
fold (an unsorted by_source / works / graph ordering) iterates the *same* way
twice within one process, so a same-process pair stays green over it; only two
processes seeded with different `PYTHONHASHSEED`s surface the divergence — the
decisive, load-bearing half of the guard.
"""

import argparse
import contextlib
import io
import json
import os
import subprocess
import sys

import pytest

from scrolls.cli import build_parser, main
from scrolls.paths import get_paths

from read_surface_fixture import seed_read_surface_determinism_mix


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    """Point the library root at a temp dir so tests never touch ~/.scrolls."""
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# (command-path, argv) for every CLI determinism-covered read command, args
# resolved from the shared read-surface mix. Each argv drives that command's
# heaviest order-sensitive fold (a multi-hit query, the full-budget bundle, the
# trend envelope, the multi-prior archive). The path set MUST equal the
# registered reads (the completeness keystone asserted below).
_CLI_READ_COMMANDS = (
    (("search",), ["search", "database"]),
    (("list",), ["list"]),
    (("facets",), ["facets"]),
    (("works",), ["works"]),
    (("graph",), ["graph"]),
    (("related",), ["related", "arxiv:dba"]),
    (("doctor",), ["doctor"]),
    (("context",), ["context", "database", "--budget", "full"]),
    (("status",), ["status"]),
    (("history",), ["history", "web:hub"]),
    # `maintain` is a write by default (the recheck pass); its
    # determinism-covered *read* mode is `--history [--trend]`, the CLI home of
    # the MCP `get_maintenance_history` read tool — so the call exercises that
    # read mode. `--history` reads recorded runs (the `recorded_at` is stamped
    # once at prepare time, so two reads of the one shared library see the same
    # fixed timestamps — no wall-clock line to drop).
    (("maintain",), ["maintain", "--history", "--trend"]),
    (("archive", "list"), ["archive", "list"]),
    (("archive", "show"), ["archive", "show", "web:archived", "--all"]),
    (("show",), ["show", "arxiv:dba"]),
)

_CLI_READ_PATHS = frozenset(path for path, _ in _CLI_READ_COMMANDS)


def _key(path):
    """The flat string key for a command path — `("archive", "list")` → "archive list"."""
    return " ".join(path)


# Every other registered subcommand, classified so the keystone's union is
# total. Writes mutate the library (or hit the network). The exempt reads are
# deterministic but carry no library-wide order-sensitive fold this contract
# pins — a stateless parse, a static layout, a single-item passthrough — or are
# pinned elsewhere (the export transports: H368/H378/H379/H384/H390 determinism
# + the H395 round-trip cell), each with its reason.
_CLI_WRITE_COMMANDS = frozenset({
    ("add",), ("agent", "install"), ("classify",), ("fetch",), ("follow",),
    ("ingest",), ("init",), ("kb",), ("reconcile",), ("rm",), ("set",),
    ("sync",), ("unfollow",), ("verify",),
    ("archive", "prune"), ("archive", "restore"),
    ("import", "archive"), ("import", "bookmarks"), ("import", "bundle"),
    ("import", "events"), ("import", "fieldtheory"), ("import", "google-takeout"),
    ("import", "items"), ("import", "opml"), ("import", "pocket"),
})
_CLI_EXEMPT_READS = {
    ("detect",): "stateless URL→source parse, no library fold",
    ("paths",): "static library layout, no fold",
    ("md",): "single-item markdown passthrough, no cross-item fold",
    ("media",): "single-item media listing, no cross-item fold",
    ("mcp",): "starts a stdio server, not a JSON read",
    ("archive", "diff"): "pairwise held-vs-prior diff; archive determinism rides H385",
    ("export", "archive"): "transport: determinism H390, round-trip H395",
    ("export", "bookmarks"): "transport: bookmarks export, round-trip H395",
    ("export", "bundle"): "transport: determinism H368/H378, round-trip H395",
    ("export", "events"): "transport: determinism H384, round-trip H395",
    ("export", "items"): "transport: determinism H379, round-trip H395",
    ("export", "opml"): "transport: OPML feed export, round-trip H395",
}


def _registered_cli_command_paths():
    """Every registered leaf subcommand path, walked from the live argparse tree —
    the source of truth the completeness keystone holds the classification to."""

    def walk(parser, prefix=()):
        paths = set()
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, sub in action.choices.items():
                    sub_paths = walk(sub, prefix + (name,))
                    paths |= sub_paths or {prefix + (name,)}
        return paths

    return walk(build_parser())


def _prepare_cli_read_surface_library():
    """init + seed + two offline maintenance passes — the shared setup the CLI
    determinism reads run against, so the verify ledger, the archive store, and a
    non-trivial maintenance trend all exist for every read command.
    `maintain --no-recheck` skips the live re-capture edge (no network), so this
    is offline; two passes give a real custody trajectory for
    `maintain --history --trend`."""
    main(["init"])
    seed_read_surface_determinism_mix(get_paths())
    main(["maintain", "--no-recheck"])  # two passes → a real trend
    main(["maintain", "--no-recheck"])


def _read_outputs_same_process(capsys):
    """Run every CLI read command once in-process; return {flat-key: stdout}."""
    outputs = {}
    for path, argv in _CLI_READ_COMMANDS:
        rc = main(list(argv))
        captured = capsys.readouterr()
        assert rc == 0, f"{_key(path)} exited {rc}: {captured.err}"
        outputs[_key(path)] = captured.out
    return outputs


def _assert_cli_read_surface_non_vacuous(out):
    """Every leak-prone read returned a multi-element fold, so the byte-identity
    claims are real (a mis-ordered empty fold would pass too). Keyed by flat key."""
    search = json.loads(out["search"])
    assert len(search) >= 3 and len({h["source"] for h in search}) >= 2
    assert len(json.loads(out["list"])) >= 8
    assert json.loads(out["facets"])["facets"]["sources"]
    assert len(json.loads(out["works"])["works"]) >= 2
    graph = json.loads(out["graph"])
    assert len(graph["nodes"]) >= 3 and len(graph["edges"]) >= 2
    assert len(graph["stats"]["custody"]["by_source"]) >= 3
    assert json.loads(out["related"])  # arxiv:dba has neighbours
    doctor = json.loads(out["doctor"])
    assert sorted(doctor["custody"]["by_source"]) == ["arxiv", "crossref", "web", "x"]
    assert doctor["custody"]["works"]["most_at_risk"] is not None
    assert doctor["custody"]["archive"]["events"]
    status = json.loads(out["status"])
    assert sorted(status["by_source"]) == ["arxiv", "crossref", "web", "x"]
    assert len(json.loads(out["history"])) >= 2  # the drifted item's ledger
    maintain = json.loads(out["maintain"])
    assert len(maintain["runs"]) == 2
    assert maintain["trend"]["posture"] != "insufficient-history"
    assert json.loads(out["archive list"])["count"] >= 1
    assert json.loads(out["archive show"].splitlines()[0])["id"] == "web:archived"
    assert "Scrolls Context Bundle" in out["context"]  # markdown, not JSON
    assert json.loads(out["show"])["id"] == "arxiv:dba"


def test_cli_read_surface_classifies_every_registered_command():
    """The completeness keystone (roadmap H394): every registered subcommand is a
    classified read or write/exempt, so a *new* read subcommand fails the contract
    until it is added to `_CLI_READ_COMMANDS` (and given a determinism call) — the
    H364 registry-completeness mechanism on the CLI determinism axis. The read,
    write, and exempt sets are disjoint and cover the live argparse registry."""
    registered = _registered_cli_command_paths()
    classified = set(_CLI_READ_PATHS) | set(_CLI_WRITE_COMMANDS) | set(_CLI_EXEMPT_READS)
    assert classified == registered, (
        f"classification drift: unclassified={registered - classified}, "
        f"unknown={classified - registered}"
    )
    # disjoint: no command is in two buckets (so the union count is total)
    assert (
        len(_CLI_READ_PATHS) + len(_CLI_WRITE_COMMANDS) + len(_CLI_EXEMPT_READS)
        == len(registered)
    )
    # the determinism call list covers exactly the read paths, and each argv
    # routes to its declared command path (a leaked typo would skip its command)
    assert {path for path, _ in _CLI_READ_COMMANDS} == set(_CLI_READ_PATHS)
    for path, argv in _CLI_READ_COMMANDS:
        assert tuple(argv[: len(path)]) == path, (path, argv)


def test_cli_read_surface_is_byte_identical_across_two_same_process_reads(scrolls_home, capsys):
    # roadmap H394: every CLI read command serializes to byte-identical stdout
    # across two reads of one unchanged library — the *whole CLI read surface* is a
    # reproducible artifact, pinned once. The same-process face; the cross-seed
    # pair below catches the set-iteration leak this one (under a single fixed hash
    # seed) structurally cannot.
    _prepare_cli_read_surface_library()
    capsys.readouterr()  # drain the prepare output

    first = _read_outputs_same_process(capsys)
    second = _read_outputs_same_process(capsys)

    _assert_cli_read_surface_non_vacuous(first)
    for path, _ in _CLI_READ_COMMANDS:
        assert first[_key(path)] == second[_key(path)], f"{_key(path)} not stable"


def _cli_read_surface_driver(sabotage_set_size=64):
    """A standalone driver (run under a fresh interpreter) that invokes every CLI
    read command from the single source of truth `_CLI_READ_COMMANDS`, capturing
    each command's stdout, and writes `json.dumps([[key, out], ...])` (order
    preserved, no set in the harness itself). When `SCROLLS_DETERMINISM_SABOTAGE`
    names a command it appends a `list(set(...))` leak to that command's output —
    an order fixed within one process but varying across `PYTHONHASHSEED`, the
    exact regression the cross-seed face exists to catch."""
    leak = "{'k%d' % i for i in range(" + str(sabotage_set_size) + ")}"
    calls = [[_key(path), argv] for path, argv in _CLI_READ_COMMANDS]
    return (
        "import sys, os, io, json, contextlib\n"
        "from scrolls.cli import main\n"
        "calls = " + repr(calls) + "\n"
        "sabotage = os.environ.get('SCROLLS_DETERMINISM_SABOTAGE')\n"
        "parts = []\n"
        "for key, argv in calls:\n"
        "    buf = io.StringIO()\n"
        "    with contextlib.redirect_stdout(buf):\n"
        "        rc = main(list(argv))\n"
        "    assert rc == 0, key + ' rc=' + str(rc)\n"
        "    out = buf.getvalue()\n"
        "    if key == sabotage:\n"
        "        out = out + json.dumps(list(" + leak + "))\n"
        "    parts.append([key, out])\n"
        "sys.stdout.write(json.dumps(parts))\n"
    )


def _run_cli_read_surface(home, seed, *, sabotage=None):
    env = {**os.environ, "SCROLLS_HOME": str(home), "PYTHONHASHSEED": seed}
    if sabotage is not None:
        env["SCROLLS_DETERMINISM_SABOTAGE"] = sabotage
    result = subprocess.run(
        [sys.executable, "-c", _cli_read_surface_driver()],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_cli_read_surface_is_deterministic_across_hash_seeds(scrolls_home):
    # roadmap H394: the whole CLI read surface emits byte-identical output across
    # two processes with *different* `PYTHONHASHSEED`s — the cross-process face the
    # same-process pair structurally cannot see. One subprocess pair covers every
    # read command at once (the consolidation that retires the per-command
    # cross-seed twins): a `set` leaking into *any* read fold iterates the same way
    # twice under one fixed seed, so the same-process read stays green over it; only
    # two differently-seeded processes surface the divergence. The same shared
    # `SCROLLS_HOME` for both seeds (no copy) so `status`/`paths`-bearing `root`
    # strings and the recorded-run timestamps match by construction.
    _prepare_cli_read_surface_library()

    out_a = _run_cli_read_surface(scrolls_home, "0")  # hash randomization off
    out_b = _run_cli_read_surface(scrolls_home, "1")  # a different fixed seed

    # non-vacuity: the subprocess really produced the populated surface
    parsed = dict(json.loads(out_a))
    _assert_cli_read_surface_non_vacuous(parsed)
    assert {_key(path) for path, _ in _CLI_READ_COMMANDS} <= set(parsed)

    assert out_a == out_b


def test_cli_read_surface_determinism_guard_has_teeth(scrolls_home):
    # roadmap H394 sabotage: a `set`-fold leaked into one CLI read (`works`) must
    # (1) stay invisible to two reads under the *same* seed — proving the
    # cross-seed dimension is the load-bearing half, not redundant — and (2) be
    # caught by the cross-seed pair, proving the contract above is non-vacuous. So
    # the same set leak the per-command twins each caught for one command is caught
    # here for any read command, by construction.
    _prepare_cli_read_surface_library()

    same_seed_a = _run_cli_read_surface(scrolls_home, "0", sabotage="works")
    same_seed_b = _run_cli_read_surface(scrolls_home, "0", sabotage="works")
    # (1) a single fixed seed cannot see the leak — the same-process blind spot
    assert same_seed_a == same_seed_b

    cross_seed = _run_cli_read_surface(scrolls_home, "1", sabotage="works")
    # (2) two differently-seeded processes do — the contract has teeth
    assert same_seed_a != cross_seed
