"""Release regressions: result caps never turn into unbounded reads."""
import pytest

from scrolls.cli import main
from scrolls import mcp_server
from scrolls.facets import compute_facets
from scrolls.related import find_related
from scrolls.search import search_items


@pytest.mark.parametrize("limit", ["-1", str(2**63)])
@pytest.mark.parametrize("args", [
    ["list"], ["search", "sqlite"], ["context", "sqlite"],
    ["facets"], ["history", "missing"], ["fetch"],
    ["verify", "--all"], ["maintain"], ["related", "missing"],
])
def test_cli_rejects_invalid_caps_before_accessing_library(monkeypatch, tmp_path, args, limit):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "absent"))
    with pytest.raises(SystemExit) as exc:
        main([*args, "--limit", limit])
    assert exc.value.code == 2
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("limit", [-1, 2**63])
@pytest.mark.parametrize("call", [
    lambda n: mcp_server.list_scrolls(limit=n),
    lambda n: mcp_server.search_scrolls("sqlite", limit=n),
    lambda n: mcp_server.get_context_bundle("sqlite", limit=n),
    lambda n: mcp_server.list_facets(limit=n),
    lambda n: mcp_server.get_scroll_history("missing", limit=n),
    lambda n: mcp_server.get_related_scrolls("missing", limit=n),
    lambda n: mcp_server.get_maintenance_history(limit=n),
])
def test_mcp_rejects_invalid_caps(monkeypatch, tmp_path, call, limit):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "absent"))
    with pytest.raises(ValueError, match="limit must be"):
        call(limit)


@pytest.mark.parametrize("limit", [-1, 2**63])
def test_query_engines_validate_even_without_a_database(tmp_path, limit):
    db = tmp_path / "absent.sqlite"
    for call in (
        lambda: search_items(db, "sqlite", limit=limit),
        lambda: compute_facets(db, limit=limit),
        lambda: find_related(db, "missing", limit=limit),
    ):
        with pytest.raises(ValueError, match="limit must be"):
            call()


def test_zero_remains_a_valid_empty_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "absent"))
    assert mcp_server.list_scrolls(limit=0) == []
    assert mcp_server.search_scrolls("sqlite", limit=0) == []
    assert mcp_server.get_maintenance_history(limit=0) == []
