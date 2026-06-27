"""The CLI↔MCP write-act parity contract (roadmap H406) — one completeness-asserted invariant.

The thirteenth **contract-consolidation** cell, the **write-side** sibling of H400's
CLI↔MCP read-parity matrix. Where H400 pins that every read tool reads one item's
custody axes identically across the (CLI command, MCP tool) twin, this pins that every
custody-safe MCP *write* tool produces the **same durable custody effect** as its CLI
act twin over the same library — so a custody-safe write is transport-agnostic (the same
library mutation whichever surface drives it; custody-vision §2.4, raw-is-sacred — no MCP
write destroys or overwrites raw, the H364 holdings-immutability line on the *effect*
axis). The scattered per-tool effect tests (`verify_scroll` records drift, `compile_library`
returns the CLI payload, `run_maintenance` converges with `maintain --no-recheck`, the
feed-op tests) are lifted to one matrix pinned over a write-act twin registry.

The six offline custody-safe writes and their CLI act twins:

- ``verify_scroll`` ≡ ``verify`` — the **same typed `custody_events` row appended**
  (the durable ledger event, not just the transient return), behind the shared
  `live_recapture` seam (patched offline so the diff is deterministic).
- ``run_maintenance`` ≡ ``maintain --no-recheck`` — the **same report disposition +
  recorded snapshot/trend** (`assemble_report` over `skipped_recheck_report`, the H383
  offline-by-default convergence; the MCP pass *is* `--no-recheck`).
- ``compile_library`` ≡ ``kb`` — the **same `{relpath → sha256}` whole-tree hash of the
  compiled `library/`** (the H363 deterministic-compile axis; both call `compile_kb`).
- ``follow_feed``/``unfollow_feed``/``sync_feeds`` ≡ ``follow``/``unfollow``/``sync`` —
  the **same subscription-row effect** (the roster after the act, behind the patched
  feed-fetch seams `feeds._get_text`/`feeds._get_conditional`), plus, for sync, the same
  detected items.

The seventh custody-safe write, ``ingest_url``, is the one **network-write exemption**:
its effect is a live capture pinned by its own fake-API tests (`test_mcp.py`
`test_ingest_url_*`), not an offline effect twin — so it is named, never silently dropped.

Two faces, the H388/H394/H396/H397/H400 shape:

1. **The completeness keystone** — `_WRITE_TWINS` (the effect-checked twins) ∪ the named
   `_NETWORK_WRITE_EXEMPT` set must partition `_MCP_SAFE_WRITE_TOOLS` (H364) *exactly*, so
   a *new* MCP write tool fails the contract until it declares a CLI act twin (checked
   here) or the network exemption. Each declared CLI act twin's path is also held to the
   live CLI registry — the five pure writes to `_CLI_WRITE_COMMANDS` (H394), the dual-mode
   ``maintain`` (whose read mode `maintain --history` H394 read-classified, driven here in
   its `--no-recheck` write-pass mode) to `_CLI_READ_PATHS` — so a twin can never name a
   phantom command. The "fails until *both* contracts register it" tie, on the write axis.

2. **The matrix guard** — over the shared wide read-surface fixture
   (`seed_read_surface_determinism_mix`), each twin's CLI custody effect equals its MCP
   custody effect on the wire (timestamps normalised — two separate wall-clock acts
   legitimately stamp different `checked_at`/`recorded_at`/`added_at`, but the custody
   content — the event verb/hashes, the snapshot scalars, the compiled bytes, the roster
   membership — must agree). The sabotage proves the teeth and the isolation: an MCP
   `verify_scroll` that records a *different verb* than the CLI `verify` fails *only* the
   `verify_scroll` twin's leg, not its siblings.
"""

import dataclasses
import hashlib
import json
import re

import pytest

import scrolls.cli as cli
import scrolls.feeds as feeds
import scrolls.mcp_server as mcp_server
from scrolls.cli import main
from scrolls.custody import item_events
from scrolls.feeds import list_subscriptions
from scrolls.items import ScrollItem, list_items
from scrolls.maintain import log_path, read_log
from scrolls.paths import get_paths
from scrolls.sources.http import ConditionalText

from read_surface_fixture import seed_read_surface_determinism_mix

# The write registries the H364/H394 contracts hold to the live MCP / argparse surfaces.
# Keying the twin classification to `_MCP_SAFE_WRITE_TOOLS` makes a *new* MCP write tool
# force a twin-or-exempt decision here (it first fails H364 until classified custody-safe,
# then this contract until it declares a CLI act twin); checking each declared CLI twin
# path against `_CLI_WRITE_COMMANDS`/`_CLI_READ_PATHS` ties the other half to argparse.
from test_cli_determinism import _CLI_READ_PATHS, _CLI_WRITE_COMMANDS  # noqa: E402
from test_mcp import _MCP_SAFE_WRITE_TOOLS  # noqa: E402


@pytest.fixture
def scrolls_home(monkeypatch, tmp_path):
    # the base env; each twin runs over its *own* fresh sub-home so the CLI and MCP
    # acts never share state (a write parity claim must compare two clean libraries)
    root = tmp_path / "scrolls-home"
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    return root


# --- the deterministic offline seams -----------------------------------------

# A small RSS feed the patched fetchers return, so `follow`/`sync` validate and register
# entries without the network — two http(s)-linked posts (the linkless item is dropped).
_FEED_URL = "https://blog.example.com/feed.xml"
_FEED_TEXT = """\
<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>A Weblog</title>
    <link>https://blog.example.com/</link>
    <item>
      <title>Post one</title>
      <link>https://blog.example.com/2026/post-one/</link>
      <pubDate>Tue, 02 Jun 2026 10:00:00 GMT</pubDate>
    </item>
    <item><title>Linkless item is dropped</title></item>
    <item>
      <title>Post two</title>
      <link>https://blog.example.com/2026/post-two/</link>
    </item>
  </channel>
</rss>
"""

# A hash-bearing, event-free fixture item to verify (the drifted `web:hub` already carries
# events; `arxiv:dba` carries a captured hash and a clean ledger, so the appended event is
# unambiguously the act's own).
_VERIFY_ID = "arxiv:dba"


def _recapture_drift(item: ScrollItem) -> ScrollItem:
    """A deterministic re-capture that always reports a changed body → `drifted`."""
    return ScrollItem(**{**dataclasses.asdict(item), "content_hash": "sha256:reverified"})


@pytest.fixture
def offline_seams(monkeypatch):
    """Patch every network edge the write twins reach so both transports run offline
    and *deterministically* — the verify re-capture (in both module namespaces) and the
    feed fetch/conditional-GET seams (module-level defaults both `follow`/`sync` read)."""
    monkeypatch.setattr(cli, "live_recapture", _recapture_drift)
    monkeypatch.setattr(mcp_server, "live_recapture", _recapture_drift)
    monkeypatch.setattr(feeds, "_get_text", lambda url: _FEED_TEXT)
    monkeypatch.setattr(
        feeds, "_get_conditional",
        lambda url, etag, last_modified: ConditionalText(text=_FEED_TEXT),
    )


# --- timestamp-normalised wire comparison ------------------------------------

_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def _denoise(value):
    """Replace every ISO-8601 wall-clock string with a sentinel, recursively.

    Two separate acts stamp `checked_at`/`recorded_at`/`added_at`/`last_synced_at` from
    `datetime.now`/`_utcnow` at different instants — a legitimate difference, not a custody
    desync. Everything else (the event verb/hashes, the snapshot scalars, the compiled
    sha256s, the roster ids/urls, item stages) is content and passes through unchanged.
    """
    if isinstance(value, dict):
        return {key: _denoise(member) for key, member in value.items()}
    if isinstance(value, (list, tuple)):
        return [_denoise(member) for member in value]
    if isinstance(value, str) and _TS.match(value):
        return "<timestamp>"
    return value


def _on_the_wire(value):
    """The JSON form a surface emits, timestamps normalised — the honest effect basis.

    The CLI prints through `json.dumps` (arrays are `list`s); MCP returns native objects
    (a `tuple` is a JSON array only once serialized). Normalise both through JSON so a
    `tuple`/`list` array difference is not a false desync (the H400 normalisation, on the
    write-effect axis)."""
    return json.dumps(_denoise(value), sort_keys=True)


# --- the durable custody-effect readers --------------------------------------


def _ledger_effect(paths):
    """The verified item's `custody_events` rows — the durable ledger, not the return."""
    return [dataclasses.asdict(event) for event in item_events(paths.db_path, _VERIFY_ID)]


def _roster_effect(paths):
    """The subscription roster — the durable subscription-row effect of a feed op."""
    return [dataclasses.asdict(sub) for sub in list_subscriptions(paths.db_path)]


def _tree_hashes(root):
    """Map every file under `root` to its sha256, keyed by POSIX relpath (the H363
    whole-tree-hash idiom) — the compiled-`library/` effect of a recompile."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _compile_effect(paths):
    return _tree_hashes(paths.library_dir)


def _maintain_effect(paths, result):
    """The maintenance pass's report disposition (the act's return/stdout) *and* the
    recorded snapshot/trend (the durable log) — the H383 convergence on both axes."""
    return {"report": result, "log": read_log(log_path(paths))}


def _sync_effect(paths):
    """The roster's post-sync state *and* the detected items the feed registered."""
    return {
        "roster": _roster_effect(paths),
        "items": sorted(item.id for item in list_items(paths.db_path)),
    }


# --- the write-twin registry — the completeness keystone ---------------------


def _follow_first():
    """Pre-state for the unfollow/sync twins: a subscription to act on (offline)."""
    feeds.follow_feed(_FEED_URL)


# Each MCP custody-safe write tool, its CLI act twin, any pre-state, the two transports'
# drivers, and the durable custody-effect reader. The CLI driver runs through `main` and
# returns its parsed JSON stdout; the MCP driver calls the tool and returns its dict.
_WRITE_TWINS = {
    "verify_scroll": {
        "label": "verify_scroll ≡ verify",
        "cli_path": ("verify",),
        "setup": lambda: None,
        "cli": lambda capsys: _cli_act(["verify", _VERIFY_ID], capsys),
        "mcp": lambda: mcp_server.verify_scroll(_VERIFY_ID),
        "effect": lambda paths, result: _ledger_effect(paths),
    },
    "run_maintenance": {
        "label": "run_maintenance ≡ maintain --no-recheck",
        # dual-mode command: H394 read-classified `maintain` for its `--history` read,
        # driven here in its `--no-recheck` write-pass mode (see the keystone test).
        "cli_path": ("maintain",),
        "setup": lambda: None,
        "cli": lambda capsys: _cli_act(["maintain", "--no-recheck"], capsys),
        "mcp": lambda: mcp_server.run_maintenance(),
        "effect": _maintain_effect,
    },
    "compile_library": {
        "label": "compile_library ≡ kb",
        "cli_path": ("kb",),
        "setup": lambda: None,
        "cli": lambda capsys: _cli_act(["kb"], capsys),
        "mcp": lambda: mcp_server.compile_library(),
        "effect": lambda paths, result: _compile_effect(paths),
    },
    "follow_feed": {
        "label": "follow_feed ≡ follow",
        "cli_path": ("follow",),
        "setup": lambda: None,
        "cli": lambda capsys: _cli_act(["follow", _FEED_URL], capsys),
        "mcp": lambda: mcp_server.follow_feed(_FEED_URL),
        "effect": lambda paths, result: _roster_effect(paths),
    },
    "unfollow_feed": {
        "label": "unfollow_feed ≡ unfollow",
        "cli_path": ("unfollow",),
        "setup": _follow_first,
        "cli": lambda capsys: _cli_act(["unfollow", _FEED_URL], capsys),
        "mcp": lambda: mcp_server.unfollow_feed(_FEED_URL),
        "effect": lambda paths, result: _roster_effect(paths),
    },
    "sync_feeds": {
        "label": "sync_feeds ≡ sync",
        "cli_path": ("sync",),
        "setup": _follow_first,
        "cli": lambda capsys: _cli_act(["sync"], capsys),
        "mcp": lambda: mcp_server.sync_feeds(),
        "effect": lambda paths, result: _sync_effect(paths),
    },
}

# The one network-write tool whose effect is a live capture — pinned by its own fake-API
# tests (`test_mcp.py` `test_ingest_url_*`), not an offline effect twin. Named so a *new*
# MCP write tool can never be silently dropped (it must be a twin or earn this exemption).
_NETWORK_WRITE_EXEMPT = {
    "ingest_url": "live capture (network); effect pinned by the fake-API ingest tests",
}


def _cli_act(argv, capsys):
    """Run a CLI act through `main`, drain its stdout, and return the parsed JSON."""
    rc = main(argv)
    out = capsys.readouterr().out
    # verify-drift / maintain-no-issues / feed ops all exit 0; surface a real failure
    assert rc == 0, f"{' '.join(argv)} exited {rc}"
    return json.loads(out)


# --- the keystone tests ------------------------------------------------------


def test_write_twin_registry_partitions_the_mcp_write_surface():
    """Every custody-safe MCP write tool is an effect-checked twin or the *named* network
    exemption — so a *new* MCP write tool fails until it declares a CLI act twin (or the
    exemption). The H364 registry-completeness mechanism on the write-parity axis."""
    checked = set(_WRITE_TWINS)
    exempt = set(_NETWORK_WRITE_EXEMPT)
    assert checked.isdisjoint(exempt)
    assert checked | exempt == set(_MCP_SAFE_WRITE_TOOLS)
    # sanity: the checked matrix is the six offline custody-safe writes the spec names,
    # non-trivial (a registry that quietly emptied itself would still pass the partition)
    assert checked == {
        "verify_scroll", "run_maintenance", "compile_library",
        "follow_feed", "unfollow_feed", "sync_feeds",
    }


def test_every_declared_cli_act_twin_is_a_registered_command():
    """Each CLI act twin a registry entry names is a *registered* CLI command — the five
    pure writes in `_CLI_WRITE_COMMANDS` (H394), and the dual-mode `maintain` in
    `_CLI_READ_PATHS` (H394 read-classified it for its `--history` read, but it is driven
    here in its `--no-recheck` write-pass mode). So the twin registry can never drift to a
    command that isn't real — the other half of the "fails until *both* contracts register
    it" tie (the MCP half is the partition above)."""
    paths = {name: twin["cli_path"] for name, twin in _WRITE_TWINS.items()}
    # the dual-mode maintain twin is the *only* one whose CLI path is a read command
    dual_mode = {name for name, path in paths.items() if path in _CLI_READ_PATHS}
    assert dual_mode == {"run_maintenance"}
    # every other declared twin names a registered *write* command
    write_twins = {name for name, path in paths.items() if path in _CLI_WRITE_COMMANDS}
    assert write_twins == set(_WRITE_TWINS) - {"run_maintenance"}
    # together: every declared CLI act path is a registered command (no phantom command)
    assert set(paths.values()) <= (set(_CLI_WRITE_COMMANDS) | set(_CLI_READ_PATHS))
    # and the twins name distinct CLI commands (no two twins collide on one command)
    assert len(set(paths.values())) == len(paths)


# --- the matrix guard --------------------------------------------------------


def _run_twin(monkeypatch, root, twin, transport, capsys):
    """Seed a fresh sub-home, apply the twin's pre-state, drive the act over `transport`,
    and read its durable custody effect — the per-transport leg of the parity comparison."""
    monkeypatch.setenv("SCROLLS_HOME", str(root))
    assert main(["init"]) == 0
    seed_read_surface_determinism_mix(get_paths())
    capsys.readouterr()
    twin["setup"]()
    capsys.readouterr()
    result = twin["cli"](capsys) if transport == "cli" else twin["mcp"]()
    capsys.readouterr()
    return twin["effect"](get_paths(), result)


def _twin_effect_disagreements(monkeypatch, tmp_path, capsys):
    """The set of twins whose CLI custody effect disagrees with its MCP one (on the wire).

    The matrix guard asserts this is empty; the sabotage asserts it is exactly the one
    twin it broke. Each twin runs over two *fresh* sub-homes (one per transport), so the
    two acts never share state — a true two-library write parity comparison."""
    failures = set()
    for name, twin in _WRITE_TWINS.items():
        cli_effect = _run_twin(monkeypatch, tmp_path / f"{name}-cli", twin, "cli", capsys)
        mcp_effect = _run_twin(monkeypatch, tmp_path / f"{name}-mcp", twin, "mcp", capsys)
        if _on_the_wire(cli_effect) != _on_the_wire(mcp_effect):
            failures.add(name)
    return failures


def test_every_write_twin_agrees_on_its_custody_effect(
    scrolls_home, offline_seams, monkeypatch, tmp_path, capsys
):
    """Over the wide non-vacuous fixture, each custody-safe write's CLI effect equals its
    MCP effect — `verify`≡`verify_scroll` (the appended ledger event), `maintain`≡
    `run_maintenance` (the report + recorded snapshot/trend), `kb`≡`compile_library` (the
    compiled-tree hash), `follow`/`unfollow`/`sync`≡their MCP twins (the roster) — the one
    invariant the scattered per-tool effect tests pinned piecemeal."""
    # sanity: each effect is non-vacuous (a mis-recorded effect has a wrong value to land
    # on, not 0 == 0). Verified over a throwaway home so the matrix runs on clean ones.
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "sanity"))
    main(["init"])
    seed_read_surface_determinism_mix(get_paths())
    capsys.readouterr()
    assert any(item.id == _VERIFY_ID and item.content_hash
               for item in list_items(get_paths().db_path))      # a hash to verify
    assert item_events(get_paths().db_path, _VERIFY_ID) == []     # a clean ledger
    feeds.follow_feed(_FEED_URL)
    assert len(list_subscriptions(get_paths().db_path)) == 1      # a roster to read
    mcp_server.compile_library()
    assert len(_tree_hashes(get_paths().library_dir)) >= 3        # a multi-page tree

    assert _twin_effect_disagreements(monkeypatch, tmp_path, capsys) == set()


def test_an_mcp_write_recording_a_different_verb_fails_only_that_twin(
    scrolls_home, offline_seams, monkeypatch, tmp_path, capsys
):
    """The sabotage proves the matrix has teeth and is *isolating*: an MCP `verify_scroll`
    that records a *different verb* than the CLI `verify` fails *only* the `verify_scroll`
    twin's leg, not its siblings (the maintenance/compile/feed effects are untouched).

    `mcp_server.verify_item` is the binding `verify_scroll` records its event through — a
    *distinct* module binding from `cli.verify_item` (the `verify` twin). So mutating the
    MCP-recorded verb desyncs only `verify_scroll`≡`verify`; the other twins, whose effects
    flow through `compile_kb`/`assemble_report`/`feeds`, stay byte-identical to their CLI
    sides. This is the regression the cross-transport matrix catches that a single tool's
    own effect test misses."""
    # baseline: every twin agrees
    assert _twin_effect_disagreements(monkeypatch, tmp_path / "base", capsys) == set()

    real_verify_item = mcp_server.verify_item

    def _wrong_verb(item, recapture, *, now):
        event = real_verify_item(item, recapture, now=now)
        return dataclasses.replace(event, status="rotted")  # a different ledger verb

    monkeypatch.setattr(mcp_server, "verify_item", _wrong_verb)

    assert _twin_effect_disagreements(monkeypatch, tmp_path / "sab", capsys) == {
        "verify_scroll"
    }
