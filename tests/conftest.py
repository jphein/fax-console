"""conftest.py — shared fixtures and subprocess/os.system guard.

Any test that accidentally reaches subprocess.run, subprocess.Popen, or
os.system will fail immediately rather than spawning a real process.
"""
import os
import subprocess

import pytest


@pytest.fixture(autouse=True)
def _block_real_subprocesses(monkeypatch, request):
    """Raise AssertionError if test code calls subprocess.run, subprocess.Popen, or os.system.

    Tests marked ``allow_subprocesses`` may install their own fake for
    subprocess.run — but Popen and os.system remain blocked even for them.
    The sandbox_guard tests call subprocess intentionally via their own
    fixtures and are excluded entirely.
    """
    # Skip the guard for tests in test_sandbox_guard.py (they run guards themselves)
    if "test_sandbox_guard" in request.fspath.basename:
        yield
        return

    def _blocked_popen(*args, **kwargs):
        raise AssertionError(
            f"subprocess.Popen called unexpectedly in test {request.node.nodeid!r}: {args!r}"
        )

    def _blocked_system(cmd):
        raise AssertionError(
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
        raise AssertionError(
            f"subprocess.run called unexpectedly in test {request.node.nodeid!r}: {args!r}"
        )

    monkeypatch.setattr(subprocess, "run", _blocked_run)
    yield
