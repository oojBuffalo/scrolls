"""Suite-wide test isolation.

Every command upgrades the library at `$SCROLLS_HOME`, else `~/.scrolls`,
before it runs (ADR 0119), so a test that calls `main()` without choosing a
library would migrate the developer's real one. Each test starts with its own
empty root instead; a test that sets `$SCROLLS_HOME` itself still wins, and one
that means to exercise the default unsets it.
"""

import pytest


@pytest.fixture(autouse=True)
def isolated_library(monkeypatch, tmp_path):
    """Point `$SCROLLS_HOME` at a per-test directory, never the real library.

    Args:
        monkeypatch: Restores the environment after the test.
        tmp_path: The test's own temporary directory.
    """
    monkeypatch.setenv("SCROLLS_HOME", str(tmp_path / "default-library"))
