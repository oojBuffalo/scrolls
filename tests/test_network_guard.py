"""The suite runs with the external network structurally blocked (issue #11).

Offline safety used to rest on every test remembering to monkeypatch the
right seam, and that convention failed twice (ADR 0112's live HTTP 400;
H433's test silently reaching live X). The pytest addopts make the block
structural: only loopback and unix sockets stay open, for the tests that
run real localhost servers. These tests prove the guard has teeth.
"""

import socket

import pytest
import pytest_socket


def test_external_connections_are_blocked_suite_wide():
    with pytest.raises(pytest_socket.SocketConnectBlockedError):
        # A fixed public IP, no DNS: the guard raises before any packet.
        socket.create_connection(("93.184.216.34", 80), timeout=1)


def test_loopback_stays_available_for_local_server_fixtures():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname(), timeout=1)
        client.close()
    finally:
        server.close()
