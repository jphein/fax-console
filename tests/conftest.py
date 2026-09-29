"""conftest.py — shared fixtures and subprocess/os.system guard.

Any test that accidentally reaches subprocess.run, subprocess.Popen, or
os.system will fail immediately rather than spawning a real process.
"""
import os
import subprocess

import pytest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLING_TESTS = {os.path.join(TESTS_DIR, f) for f in ("test_sandbox_guard.py", "test_scrub_history.py",
                                                       "test_scrub_rules.py", "test_bob_usage.py",
                                                       "test_bob_run.py")}


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
