"""Exercise fixture ownership against actual loopback socket states."""
import os
import socket

import pytest

from scripts.run_openui_browser_checks import ensure_fixture_port_free


def test_port_probe_rejects_an_actual_listener():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(SystemExit, match=f'Port {port} is occupied'):
            ensure_fixture_port_free(port)


def test_port_probe_leaves_a_free_port_available_for_the_fixture():
    with socket.socket() as temporary:
        temporary.bind(('127.0.0.1', 0))
        port = temporary.getsockname()[1]
    ensure_fixture_port_free(port)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', port))
        listener.listen()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX TIME_WAIT bind semantics')
def test_port_probe_allows_the_previous_fixture_time_wait_socket():
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        port = listener.getsockname()[1]
        with socket.create_connection(('127.0.0.1', port), timeout=2) as client:
            accepted, _ = listener.accept()
            accepted.close()  # The server actively closes, so its port owns TIME_WAIT.
            assert client.recv(1) == b''
    # Confirm the exact failing preflight state before testing the fix.
    with socket.socket() as plain_probe, pytest.raises(OSError):
        plain_probe.bind(('127.0.0.1', port))
    ensure_fixture_port_free(port)
