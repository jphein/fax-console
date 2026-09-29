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

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLING_TESTS = {os.path.join(TESTS_DIR, f) for f in ("test_sandbox_guard.py", "test_scrub_history.py",
                                                       "test_scrub_rules.py", "test_bob_usage.py",
                                                       "test_bob_run.py", "test_bob_lock_check.py",
                                                       "test_static_page_render.py")}   # runs app.js in node


_IP_FAMILIES = (socket.AF_INET, socket.AF_INET6)
_TRIPS = []                  # every network use, from any thread, for the whole session: (test, what)
_CURRENT = ["<before the first test>"]


def _trip(what):
    """Record, then fail. The record is what makes a swallowed failure visible: in a pool worker whose
    future is discarded (as the server's pool does) the Failed lands in the future, and in a plain thread
    it only warns. The per-test and session teardowns assert on the record (the review of PR 8)."""
    _TRIPS.append((_CURRENT[0], what))
    pytest.fail(f"{what} in test {_CURRENT[0]!r}: tests use AF_UNIX socketpairs only, and no network")


@pytest.fixture(autouse=True, scope="session")
def _network_guard_for_the_whole_session():
    """Bind, connect, send and name resolution on IPv4/IPv6 are refused for the whole session, so a daemon
    thread that outlives its test is still guarded.

    The sandbox's packet filter cannot see a bind or a listen, and it allows the public internet, which is
    how Bob reaches its API. So the rules "tests never open a TCP port" and "tests never reach a network"
    are enforced here. AF_UNIX sockets and socketpair() are untouched.
    """
    # listen() on an unbound IP socket autobinds a real port (the Oracle's delta on PR 8)
    names = ("bind", "connect", "connect_ex", "sendto", "sendmsg", "listen")
    real = {name: getattr(socket.socket, name) for name in names}

    def guard(name):
        def blocked(self, *args, **kwargs):
            if self.family in _IP_FAMILIES:
                _trip(f"socket.{name}(...{args[-1:]!r}) on an IP socket")
            return real[name](self, *args, **kwargs)
        return blocked

    mp = pytest.MonkeyPatch()
    for name in names:
        mp.setattr(socket.socket, name, guard(name))
    for resolver in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
        mp.setattr(socket, resolver, lambda host, *a, _r=resolver, **k: _trip(f"socket.{_r}({host!r})"))
    yield
    mp.undo()
    late = [t for t in _TRIPS if t[0].startswith("<after ")]
    assert not late, f"network use after a test had ended (a thread that outlived it): {late}"


@pytest.fixture(autouse=True)
def _block_ip_sockets(request):
    """Attribute network use to this test, and fail it at teardown even when a thread swallowed the Failed."""
    _CURRENT[0] = request.node.nodeid
    start = len(_TRIPS)
    yield
    mine = _TRIPS[start:]
    _CURRENT[0] = f"<after {request.node.nodeid}>"
    assert not mine, (f"network use in this test (possibly inside a thread whose failure was "
                      f"swallowed): {mine}")


@pytest.fixture(autouse=True)
def _block_real_subprocesses(monkeypatch, request):
    """Fail the test if its code calls subprocess.run, subprocess.Popen, or os.system.

    pytest.fail raises a BaseException, so production code's `except Exception` (the transports
    turn errors into failed Readings) cannot swallow it: a guard that can be caught cannot fail.

    Tests marked ``allow_subprocesses`` may install their own fake for
    subprocess.run — but Popen and os.system remain blocked even for them.
    The tooling tests (TOOLING_TESTS) call subprocess intentionally, on throwaway
    repositories, and are excluded entirely.
    """
    # Skip the guard for the tests of the repository's own tooling: they run the sandbox hooks, the
    # scrub gate and the Bob wrapper as processes, on throwaway repositories and files, by design.
    # The guard is for the package's tests, which must never reach a real PBX.
    if str(request.fspath) in TOOLING_TESTS:              # these files, here: not any namesake
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
