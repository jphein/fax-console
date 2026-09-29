"""A planted .pyc steered the export (the Oracle, on PR 20).

Python trusts a __pycache__ entry whose header claims the source's mtime and size, and loads it instead of the
source. Bob can write faxconsole/__pycache__, so a planted .pyc could put other content on the public site, or
let test.sh report green for code that is not the committed code. scripts/test.sh and scripts/export-static.sh
run Python with PYTHONPYCACHEPREFIX on the sandbox's fresh /tmp, so the tree's __pycache__ is never read.

The plant test proves both sides: without a prefix the plant wins (the positive control), and with one the
committed source does.
"""
import importlib.util
import marshal
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _plant(pkg: Path, committed: str, planted: str) -> None:
    """A package whose __init__.py says *committed*, and an in-tree .pyc that says *planted* while
    claiming the source's own mtime and size, so Python takes it as up to date."""
    pkg.mkdir()
    src = pkg / "__init__.py"
    src.write_text(f"X = {committed!r}\n")
    os.utime(src, (1_700_000_000, 1_700_000_000))
    st = src.stat()
    cache = pkg / "__pycache__"
    cache.mkdir()
    header = (importlib.util.MAGIC_NUMBER + (0).to_bytes(4, "little")
              + int(st.st_mtime).to_bytes(4, "little") + (st.st_size & 0xFFFFFFFF).to_bytes(4, "little"))
    code = marshal.dumps(compile(f"X = {planted!r}\n", str(src), "exec"))
    (cache / f"__init__.{sys.implementation.cache_tag}.pyc").write_bytes(header + code)


def _import_x(cwd: Path, prefix: str | None) -> str:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPYCACHEPREFIX"}
    if prefix:
        env["PYTHONPYCACHEPREFIX"] = prefix
    r = subprocess.run([sys.executable, "-c", "import plantpkg; print(plantpkg.X)"], cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=30, check=True)
    return r.stdout.strip()


def test_a_planted_pyc_wins_without_a_prefix_and_loses_with_one(tmp_path):
    _plant(tmp_path / "plantpkg", committed="committed", planted="planted")
    assert _import_x(tmp_path, None) == "planted"                     # the positive control: the plant works
    assert _import_x(tmp_path, str(tmp_path / "prefix")) == "committed"


@pytest.mark.parametrize("script", ["scripts/test.sh", "scripts/export-static.sh"])
def test_the_runners_set_the_prefix(script):
    assert "PYTHONPYCACHEPREFIX=/tmp/pycache" in (ROOT / script).read_text(), script


def test_this_suite_runs_with_the_prefix():
    """scripts/test.sh exports it. CI runs pytest directly, on a fresh checkout that holds no plant."""
    if os.environ.get("CI"):
        pytest.skip("CI checks out a fresh tree, so no __pycache__ can be planted in it")
    assert os.environ.get("PYTHONPYCACHEPREFIX") == "/tmp/pycache"
    assert sys.pycache_prefix == "/tmp/pycache"
