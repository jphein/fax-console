"""conftest.py — shared fixtures and subprocess/os.system guard.

Any test that accidentally reaches subprocess.run or os.system will fail
immediately rather than spawning a real process.
"""
import os
import subprocess
import sys

import pytest


@pytest.fixture(autouse=True)
def _block_real_subprocesses(monkeypatch, request):
    """Raise AssertionError if test code calls subprocess.run or os.system.

    Tests that genuinely exercise the transport (which call subprocess) must
    opt out with the ``allow_subprocesses`` mark.  The sandbox_guard tests
    call subprocess intentionally via their own fixtures and are excluded.
    """
    if request.node.get_closest_marker("allow_subprocesses"):
        yield
        return
    # Skip the guard for tests in test_sandbox_guard.py (they run guards themselves)
    if "test_sandbox_guard" in request.fspath.basename:
        yield
        return

    def _blocked_run(*args, **kwargs):
        raise AssertionError(
            f"subprocess.run called unexpectedly in test {request.node.nodeid!r}: {args!r}"
        )

    def _blocked_system(cmd):
        raise AssertionError(
            f"os.system called unexpectedly in test {request.node.nodeid!r}: {cmd!r}"
        )

    monkeypatch.setattr(subprocess, "run", _blocked_run)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError(f"subprocess.Popen called in {request.node.nodeid!r}")
    ))
    monkeypatch.setattr(os, "system", _blocked_system)
    yield
