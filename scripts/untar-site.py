#!/usr/bin/env python3
"""untar-site.py TAR|- OUT: extract the static export (faxconsole.export) on the host, regular files only.

The stream comes from code that ran in the OS sandbox, so no member may reach outside OUT. Only regular
files are extracted. Each name must be relative and made of plain segments, or be .nojekyll at the top.
Anything else refuses the whole export, and nothing is written: a link, a device, a directory entry, an
absolute or dotted name, or a name seen twice. OUT must be new or empty, with no symlink on its path.
Sizes and counts are capped, since the demo is a few files of JSON.
Like all host tooling here, it runs under python3 -I.
"""
import os
import re
import sys
import tarfile

SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")
MAX_FILE = 1 << 20      # 1 MiB
MAX_TOTAL = 8 << 20     # 8 MiB
MAX_FILES = 200


def check_name(name):
    if name == ".nojekyll":
        return
    if not all(SEGMENT.fullmatch(part) for part in name.split("/")):
        raise ValueError(f"untar-site: refusing member name {name!r}")


def read_members(src):
    """Every member, validated, before anything is written."""
    files, total = {}, 0
    with tarfile.open(fileobj=src, mode="r|") as tar:
        for m in tar:
            if not m.isreg():
                raise ValueError(f"untar-site: refusing {m.name!r}: not a regular file")
            check_name(m.name)
            if m.name in files:
                raise ValueError(f"untar-site: refusing {m.name!r}: it appears twice")
            if m.size > MAX_FILE or total + m.size > MAX_TOTAL or len(files) >= MAX_FILES:
                raise ValueError("untar-site: refusing: larger than a static demo can be")
            data = tar.extractfile(m).read()
            total += len(data)
            files[m.name] = data
    return files


def main(argv):
    if len(argv) != 2:
        print("usage: untar-site.py TAR|- OUT", file=sys.stderr)
        return 2
    src_path, out = argv
    try:
        if src_path == "-":
            files = read_members(sys.stdin.buffer)
        else:
            with open(src_path, "rb") as src:
                files = read_members(src)
    except (ValueError, tarfile.TarError, OSError) as e:
        print(e, file=sys.stderr)
        return 2
    if not files:
        print("untar-site: refusing: the export is empty", file=sys.stderr)
        return 2
    if os.path.realpath(out) != os.path.abspath(out):
        print(f"untar-site: refusing: a symlink is on the path to {out}", file=sys.stderr)
        return 2
    if os.path.lexists(out) and (not os.path.isdir(out) or os.listdir(out)):
        print(f"untar-site: refusing: {out} must be a new or empty directory", file=sys.stderr)
        return 2
    os.makedirs(out, exist_ok=True)
    for name, data in files.items():
        path = os.path.join(out, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "xb") as f:         # exclusive: nothing is overwritten
            f.write(data)
        os.chmod(path, 0o644)
    print(f"untar-site: {len(files)} files in {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
