"""conftest.py — shared fixtures and subprocess/os.system guard.

Any test that accidentally reaches subprocess.run, subprocess.Popen, or
os.system will fail immediately rather than spawning a real process.
"""
import os
import subprocess

import pytest


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
