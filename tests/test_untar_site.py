"""scripts/untar-site.py: the host extracts the static export (faxconsole/export.py) as regular files only.

The tar stream comes from code that ran in the OS sandbox. So one bad member refuses the whole export and
nothing is written, and the destination must be new or empty, with no symlink on its path.
"""
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

from faxconsole import export as ex

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("untar_site", ROOT / "scripts" / "untar-site.py")
untar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(untar)


@pytest.fixture(scope="module")
def site():
    return ex.export("tests/fixtures")


def _tar(members):
    """A tar of (name, kind, data) members: kind is file, symlink, dir, hardlink, chardev or fifo."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, kind, data in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                info.type = {"symlink": tarfile.SYMTYPE, "dir": tarfile.DIRTYPE, "hardlink": tarfile.LNKTYPE,
                             "chardev": tarfile.CHRTYPE, "fifo": tarfile.FIFOTYPE}[kind]
                info.linkname = data.decode()
                tar.addfile(info)
    return buf.getvalue()


def _untar(tmp_path, data, out):
    src = tmp_path / "site.tar"
    src.write_bytes(data)
    return untar.main([str(src), str(out)])


def test_untar_extracts_a_good_export(tmp_path, site):
    buf = io.BytesIO()
    ex.write_tar(site, buf)
    out = tmp_path / "site"
    assert _untar(tmp_path, buf.getvalue(), out) == 0
    got = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert got == site


@pytest.mark.parametrize("members", [
    [("../escape.json", "file", b"x")],
    [("/abs.json", "file", b"x")],
    [("api/./x.json", "file", b"x")],
    [("api", "symlink", b"/etc")],
    [("api", "dir", b""), ("api/x.json", "file", b"x")],
    [("a.json", "file", b"x"), ("a.json", "file", b"y")],
    [(".hidden", "file", b"x")],
    [("api", "hardlink", b"ok.json")],
    [("dev", "chardev", b"")],
    [("pipe", "fifo", b"")],
    [("big.json", "file", b"x" * (untar.MAX_FILE + 1))],
    [(f"f{i}.json", "file", b"{}") for i in range(untar.MAX_FILES)],
])
def test_untar_refuses_anything_but_plain_files(tmp_path, members):
    """One bad member refuses the whole export, and nothing is written."""
    out = tmp_path / "site"
    assert _untar(tmp_path, _tar([("ok.json", "file", b"{}")] + members), out) == 2
    assert not out.exists()


def test_untar_refuses_a_directory_that_holds_files(tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    (out / "old.json").write_text("{}")
    assert _untar(tmp_path, _tar([("ok.json", "file", b"{}")]), out) == 2


def test_untar_refuses_a_symlink_on_the_path_to_out(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    assert _untar(tmp_path, _tar([("ok.json", "file", b"{}")]), tmp_path / "link" / "site") == 2
    assert not (real / "site").exists()
