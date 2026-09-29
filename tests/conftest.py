"""conftest.py — shared fixtures, the subprocess/os.system guard and the network guard.

Any test that accidentally reaches subprocess.run, subprocess.Popen, or
os.system will fail immediately rather than spawning a real process.
Any test that binds or connects an IP socket fails the same way: tests talk
to the server over AF_UNIX socketpairs only, and never reach a network.
"""
import os
import socket
import subprocess

import pytest

_IP_FAMILIES = (socket.AF_INET, socket.AF_INET6)


@pytest.fixture(autouse=True)
def _block_ip_sockets(monkeypatch, request):
    """Fail the test if its code binds or connects an IPv4/IPv6 socket.

    The sandbox's packet filter denies loopback, but it cannot see a bind or a listen,
    and it allows the public internet (Bob reaches its API that way). So "tests never
    open a TCP port" and "tests never reach a network" are enforced here, for every test.
    pytest.fail raises a BaseException, which production code's `except OSError` or
    `except Exception` cannot swallow. AF_UNIX sockets and socketpair() are untouched.
    """
    real = {name: getattr(socket.socket, name) for name in ("bind", "connect", "connect_ex")}

    def guard(name):
        def blocked(self, address, *args, **kwargs):
            if self.family in _IP_FAMILIES:
                pytest.fail(f"socket.{name}({address!r}) on an IP socket in test "
                            f"{request.node.nodeid!r}: tests use AF_UNIX socketpairs only")
            return real[name](self, address, *args, **kwargs)
        return blocked

    for name in real:
        monkeypatch.setattr(socket.socket, name, guard(name))
    yield


@pytest.fixture(autouse=True)
def _block_real_subprocesses(monkeypatch, request):
    """Fail the test if its code calls subprocess.run, subprocess.Popen, or os.system.

    pytest.fail raises a BaseException, so production code's `except Exception` (the transports
    turn errors into failed Readings) cannot swallow it: a guard that can be caught cannot fail.

    Tests marked ``allow_subprocesses`` may install their own fake for
    subprocess.run — but Popen and os.system remain blocked even for them.
    The sandbox_guard tests call subprocess intentionally via their own
    fixtures and are excluded entirely.
    """
    # Skip the guard for tests in test_sandbox_guard.py (they run guards themselves)
    if request.fspath.basename == "test_sandbox_guard.py":
        yield
        return

    def _blocked_popen(*args, **kwargs):
        pytest.fail(
            f"subprocess.Popen called unexpectedly in test {request.node.nodeid!r}: {args!r}"
        )

    def _blocked_system(cmd):
        pytest.fail(
            f"os.system called unexpectedly in test {request.node.nodeid!r}: {cmd!r}"
        )

    # Popen and os.system are blocked for everyone (including allow_subprocesses tests)
    monkeypatch.setattr(subprocess, "Popen", _blocked_popen)
    monkeypatch.setattr(os, "system", _blocked_system)

    if request.node.get_closest_marker("allow_subprocesses"):
        # Tests with this marker install their own fake for subprocess.run
        yield
        return

    def _blocked_run(*args, **kwargs):
        pytest.fail(
            f"subprocess.run called unexpectedly in test {request.node.nodeid!r}: {args!r}"
        )

    monkeypatch.setattr(subprocess, "run", _blocked_run)
    yield
