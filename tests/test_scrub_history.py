"""scripts/scrub-check.sh --history, the binary review and the private deny-list (drift-gems).

A public repository publishes its whole history. A value committed once and deleted later is
still public, and so is a commit message, an author line, a tag, a file name and a merge
resolution. A binary or a PDF cannot be fully text-scanned, and a fax page is exactly where a
name hides, so each one needs a person's review, recorded by blob id. Each rule gets a case that
must be caught and one that must pass. Dirty values are assembled at runtime so that this file
passes the scrub itself.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scrub-check.sh"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def j(*parts: str) -> str:
    return "".join(parts)


PHONE = j("202 ", "555 ", "0299")      # outside the fictional 555-01xx block, and not assigned


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=repo, env={**os.environ, **GIT_ENV, **(env or {})},
                          check=True, capture_output=True, text=True).stdout


def scrub(repo: Path, *args: str, script: Path = SCRIPT, deny: Path | None = None,
          stdin: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "CI": "1",
           "FAX_CONSOLE_SCRUB_DENY": str(deny) if deny else str(repo / "no-such-deny.txt")}
    return subprocess.run(["bash", str(script), *args], cwd=repo, env=env, capture_output=True,
                          text=True, check=False, input=stdin)


def blob(repo: Path, rel: str) -> str:
    return git(repo, "hash-object", rel).strip()


def reviewed_copy(tmp: Path, *blob_ids: str) -> Path:
    """A copy of the gate whose REVIEWED_BINARIES lists these blobs, as a person's review would."""
    out = tmp / "scrub-check.sh"
    shutil.copy(SCRIPT, out)
    entries = "".join(f'    "{b}": "test fixture, reviewed",\n' for b in blob_ids)
    out.write_text(out.read_text(encoding="utf-8").replace(
        "REVIEWED_BINARIES = {\n", "REVIEWED_BINARIES = {\n" + entries), encoding="utf-8")
    return out


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "ok.txt").write_text("nothing to see\n", encoding="utf-8")
    git(r, "add", "ok.txt")
    git(r, "commit", "-q", "-m", "clean start")
    return r


def commit(repo: Path, rel: str, data: bytes | str, msg: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data) if isinstance(data, bytes) else p.write_text(data, encoding="utf-8")
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", msg)


# ---------------------------------------------------------------- history: lines and messages
def test_clean_history_passes(repo):
    r = scrub(repo, "--history")
    assert r.returncode == 0, r.stdout + r.stderr


def test_history_catches_a_value_that_was_deleted(repo):
    commit(repo, "cfg.env", j("BOB_API_KEY", "=", "abcdef123456\n"), "oops")
    git(repo, "rm", "-q", "cfg.env")
    git(repo, "commit", "-q", "-m", "remove it")
    assert scrub(repo).returncode == 0                   # HEAD is clean...
    r = scrub(repo, "--history")                         # ...history is not
    assert r.returncode == 1 and "cfg.env:1: [credential]" in r.stdout
    # A finding is exactly its place and its rule, never any of the value (a short piece of it could
    # appear in a commit id by chance, so the lines are matched whole).
    lines = r.stdout.strip().splitlines()
    assert lines and all(re.fullmatch(r"[0-9a-f]{7}:cfg\.env:1: \[[a-z-]+\]", x) for x in lines), r.stdout
    assert "abcdef" not in r.stdout + r.stderr and "123456" not in r.stdout + r.stderr


def test_history_catches_a_commit_message(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "faxed " + PHONE)
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "<commit message>:1: [phone-number]" in r.stdout


def test_a_merge_message_quoting_full_commit_ids_passes(repo):
    """GitHub's pull_request merge commit, "Merge <head> into <base>", whose head id held a 10-digit
    run: the Oracle's CI false positive on PR #6. A number beside the ids is still caught."""
    head = j("cafe", "202", "555", "0299", "beef" * 6, "cc")
    msg = f"Merge {head} into {'0123abcd' * 5}"
    git(repo, "commit", "-q", "--allow-empty", "-m", msg)
    r = scrub(repo, "--history")
    assert r.returncode == 0, r.stdout + r.stderr
    git(repo, "commit", "-q", "--allow-empty", "-m", msg + ", call " + PHONE)
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "<commit message>:1: [phone-number]" in r.stdout


def test_a_control_byte_does_not_hide_the_rest_of_a_message(repo):
    git(repo, "commit", "-q", "--allow-empty", "-m", "ok\x01 then " + PHONE)
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "[phone-number]" in r.stdout


def test_an_added_line_that_starts_like_a_header_is_content(repo):
    commit(repo, "notes.txt", "first\n", "notes")
    commit(repo, "notes.txt", "first\n++ call " + PHONE + "\n+++ b/also " + PHONE + "\n", "more")
    r = scrub(repo, "--history")
    assert r.returncode == 1
    assert "notes.txt:2: [phone-number]" in r.stdout and "notes.txt:3: [phone-number]" in r.stdout


def test_history_scans_a_merge_resolution(repo):
    commit(repo, "f.txt", "base\n", "base")
    git(repo, "switch", "-q", "-c", "side")
    commit(repo, "f.txt", "side\n", "side")
    git(repo, "switch", "-q", "main")
    commit(repo, "f.txt", "main\n", "main")
    subprocess.run(["git", "merge", "-q", "side"], cwd=repo, env={**os.environ, **GIT_ENV},
                   capture_output=True, check=False)                    # conflicts, on purpose
    (repo / "f.txt").write_text("resolved, call " + PHONE + "\n", encoding="utf-8")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-q", "--no-edit")
    commit(repo, "f.txt", "resolved\n", "tidy")                          # and deleted again
    assert scrub(repo).returncode == 0
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "f.txt:1: [phone-number]" in r.stdout


@pytest.mark.parametrize("attr", ["*.txt binary", "*.txt -diff"])
def test_gitattributes_cannot_hide_text_from_history(repo, attr):
    commit(repo, ".gitattributes", attr + "\n", "attributes")
    commit(repo, "notes.txt", "call " + PHONE + "\n", "a number")
    commit(repo, "notes.txt", "nothing\n", "gone again")
    assert scrub(repo).returncode == 0
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "notes.txt:1: [phone-number]" in r.stdout


@pytest.mark.parametrize("name", ['we"ird.txt', "tab\there.txt"])
def test_a_quoted_name_under_binary_is_still_read(repo, name):
    commit(repo, ".gitattributes", "*.txt binary\n", "attributes")
    commit(repo, name, "call " + PHONE + "\n", "a number")
    commit(repo, name, "nothing\n", "gone again")
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "[phone-number]" in r.stdout


def test_a_module_named_like_the_standard_library_is_a_finding(repo):
    for rel in ("json.py", "tests/re.py", "scripts/subprocess.py", "hashlib/__init__.py",
                "faxcli/json.py", "mymod.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x = 1\n", encoding="utf-8")
    r = scrub(repo)
    flagged = {x.split(":")[0] for x in r.stdout.splitlines() if "[stdlib-shadow]" in x}
    assert flagged == {"json.py", "tests/re.py", "scripts/subprocess.py", "hashlib/__init__.py"}
    git(repo, "add", "json.py")
    assert "json.py: [stdlib-shadow]" in scrub(repo, "--staged").stdout


def test_a_sourceless_pyc_or_extension_shadows_too_even_when_git_ignores_it(repo):
    """Python imports what is on disk: a json.pyc that .gitignore hides still shadows json for
    `python -m` at the root (the Oracle via Aurora, PR #8). Bytecode in __pycache__ never does."""
    commit(repo, ".gitignore", "*.pyc\n*.so\n__pycache__/\n", "ignore bytecode")
    for rel in ("json.pyc", "re.cpython-314-x86_64-linux-gnu.so", "tests/subprocess.pyc",
                "scripts/hashlib/__init__.pyc", "__pycache__/json.cpython-314.pyc", "faxcli/json.pyc",
                "mymod.pyc"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(b"\x00fake bytecode")
    r = scrub(repo)
    flagged = {x.split(":")[0] for x in r.stdout.splitlines() if "[stdlib-shadow]" in x}
    assert flagged == {"json.pyc", "re.cpython-314-x86_64-linux-gnu.so", "tests/subprocess.pyc",
                       "scripts/hashlib/__init__.pyc"}, r.stdout
    git(repo, "add", "-f", "json.pyc")
    assert "json.pyc: [stdlib-shadow]" in scrub(repo, "--staged").stdout


def test_a_symlink_named_like_the_standard_library_is_a_finding(repo):
    """A committed symlink json -> an in-repo package is imported as json from the root, and git lists
    it as the bare path "json" (the Oracle, PR #9). A symlink with another name is fine."""
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "json").symlink_to("pkg")
    (repo / "mymod").symlink_to("pkg")
    r = scrub(repo)
    flagged = {x.split(":")[0] for x in r.stdout.splitlines() if "[stdlib-shadow]" in x}
    assert flagged == {"json"}, r.stdout
    git(repo, "add", "json", "mymod", "pkg/__init__.py")
    assert "json: [stdlib-shadow]" in scrub(repo, "--staged").stdout


def test_the_gate_never_imports_a_module_planted_in_the_repo(repo):
    marker = repo.parent / "imported"
    for name in ("json", "re", "subprocess", "hashlib", "os"):
        (repo / f"{name}.py").write_text(f"open({str(marker)!r}, 'a').write('{name}')\n", encoding="utf-8")
    r = scrub(repo)
    assert r.returncode == 1 and "json.py: [stdlib-shadow]" in r.stdout
    assert not marker.exists()                         # python -I: the repo root is not on sys.path


def test_history_of_a_named_ref(repo):
    git(repo, "switch", "-q", "-c", "side")
    commit(repo, "s.env", j("BOB_API_KEY", "=", "abcdef123456\n"), "side secret")
    git(repo, "switch", "-q", "main")
    assert scrub(repo, "--history").returncode == 0
    assert scrub(repo, "--history", "side").returncode == 1          # what a push of side publishes
    assert scrub(repo, "--history", "no-such-ref").returncode == 2


def test_a_typechange_is_scanned_when_staged(repo):
    (repo / "link").symlink_to("ok.txt")
    git(repo, "add", "link")
    git(repo, "commit", "-q", "-m", "a link")
    (repo / "link").unlink()
    (repo / "link").write_text("call " + PHONE + "\n", encoding="utf-8")
    git(repo, "add", "link")
    r = scrub(repo, "--staged")
    assert r.returncode == 1 and "link:1: [phone-number]" in r.stdout


def test_history_covers_only_what_this_ref_publishes(repo):
    git(repo, "switch", "-q", "-c", "side")
    commit(repo, "s.env", j("BOB_API_KEY", "=", "abcdef123456\n"), "side secret")
    git(repo, "switch", "-q", "main")
    assert scrub(repo, "--history").returncode == 0       # another branch is not main's history
    git(repo, "switch", "-q", "side")
    assert scrub(repo, "--history").returncode == 1       # its own CI run catches it


# ---------------------------------------------------------------- names, identities, tags
def test_a_finding_never_prints_the_name_that_holds_the_value(repo):
    commit(repo, j("docs/call-", "202-555-", "0299.txt"), "fine\n", "a name")
    r = scrub(repo)
    assert r.returncode == 1 and "[phone-number]" in r.stdout and "0299" not in r.stdout
    assert "<file name> docs/call-***.txt" in r.stdout


def test_file_names_are_published_too(repo):
    commit(repo, j("docs/call-", "202-555-", "0299.txt"), "fine\n", "a name")
    assert "<file name>" in scrub(repo).stdout
    git(repo, "rm", "-q", j("docs/call-", "202-555-", "0299.txt"))
    git(repo, "commit", "-q", "-m", "renamed away")
    assert scrub(repo).returncode == 0
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "<file name>" in r.stdout and "[phone-number]" in r.stdout


def test_an_unconfigured_identity_leaks_the_host_name(repo):
    local = {"GIT_AUTHOR_EMAIL": j("t@devbox", ".lan"), "GIT_COMMITTER_EMAIL": j("t@", "devbox")}
    git(repo, "commit", "-q", "--allow-empty", "-m", "from a fresh machine", env=local)
    r = scrub(repo, "--history")
    assert r.returncode == 1
    assert "<author e-mail>: [machine-local-identity]" in r.stdout and "[lan-hostname]" in r.stdout
    assert "<committer e-mail>: [machine-local-identity]" in r.stdout


def test_only_the_owners_address_is_exempt(repo, tmp_path):
    deny = tmp_path / "deny.txt"
    deny.write_text("corp-mail\n", encoding="utf-8")
    alice = j("alice@", "corp-mail.com")
    ident = {"GIT_AUTHOR_EMAIL": alice, "GIT_COMMITTER_EMAIL": alice}
    git(repo, "commit", "-q", "--allow-empty", "-m", "by alice", env=ident)
    r = scrub(repo, "--history", deny=deny)                             # not the owner: every rule applies
    assert r.returncode == 1 and "<author e-mail>:1: [deny-list#1]" in r.stdout
    owner = tmp_path / "owner-gate.sh"
    shutil.copy(SCRIPT, owner)
    digest = hashlib.sha256(alice.encode()).hexdigest()
    owner.write_text(owner.read_text(encoding="utf-8").replace(
        "PUBLIC_IDENTITY_SHA256 = {\n", f'PUBLIC_IDENTITY_SHA256 = {{\n    "{digest}": "test owner",\n'),
        encoding="utf-8")
    assert scrub(repo, "--history", deny=deny, script=owner).returncode == 0    # the owner's is published
    git(repo, "commit", "-q", "--allow-empty", "-m", j("see alice@", "corp-mail.com"))
    r = scrub(repo, "--history", deny=deny, script=owner)                # in a message it is a leak
    assert r.returncode == 1 and "[email]" in r.stdout and "[deny-list#1]" in r.stdout


def test_tag_messages_on_this_history_are_scanned(repo):
    git(repo, "tag", "-a", "v1", "-m", "release, call " + PHONE)
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "tag v1:<message>:1: [phone-number]" in r.stdout
    git(repo, "tag", "-d", "v1")
    git(repo, "switch", "-q", "-c", "other")
    git(repo, "commit", "-q", "--allow-empty", "-m", "elsewhere")
    git(repo, "tag", "-a", "v2", "-m", "release, call " + PHONE)
    git(repo, "switch", "-q", "main")
    assert scrub(repo, "--history").returncode == 0                      # not on this history


# ---------------------------------------------------------------- binaries and PDFs
def test_history_catches_a_deleted_image(repo):
    commit(repo, "scan.png", b"\x89PNG\r\n\x1a\n\0a fax page", "add scan")
    git(repo, "rm", "-q", "scan.png")
    git(repo, "commit", "-q", "-m", "drop scan")
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "scan.png: [binary-needs-review] .png blob" in r.stdout


def test_every_binary_needs_review_until_its_blob_is_listed(repo, tmp_path):
    (repo / "docs").mkdir()
    (repo / "docs" / "page.tif").write_bytes(b"II*\0 a fax page")
    (repo / "blob.bin").write_bytes(b"\0\1\2\3")
    r = scrub(repo)
    assert r.returncode == 1
    assert "docs/page.tif: [binary-needs-review] .tif" in r.stdout
    assert "blob.bin: [binary-needs-review] .bin" in r.stdout            # not only media
    reviewed = reviewed_copy(tmp_path, blob(repo, "docs/page.tif"), blob(repo, "blob.bin"))
    assert scrub(repo, script=reviewed).returncode == 0
    # the review names the bytes, not the path: a different page in the same place is new
    (repo / "docs" / "page.tif").write_bytes(b"II*\0 another fax page")
    r = scrub(repo, script=reviewed)
    assert r.returncode == 1 and "docs/page.tif: [binary-needs-review]" in r.stdout


def tiny_pdf(text: str) -> bytes:
    """A minimal valid one-page PDF showing `text`, readable by pdftotext."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode() if text else b""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 144] /Contents 4 0 R"
             b" /Resources << /Font << /F1 5 0 R >> >> >>"),
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    # A binary comment line (legal in PDF) makes git treat the file as binary, as it does
    # real PDFs with compressed streams, so the history path must read the blob itself.
    out, offsets = bytearray(b"%PDF-1.4\n%\x00\xe2\xe3\xcf\xd3\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, o)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def test_every_pdf_needs_review_even_when_it_reads_clean(repo, tmp_path):
    # A page with no text layer at all (a scan) reads as "clean" to pdftotext: it proves nothing.
    (repo / "scan.pdf").write_bytes(tiny_pdf(""))
    (repo / "page.pdf").write_bytes(tiny_pdf("A plain demo test page"))
    r = scrub(repo)
    assert r.returncode == 1
    assert "scan.pdf: [binary-needs-review] .pdf" in r.stdout
    assert "page.pdf: [binary-needs-review] .pdf" in r.stdout
    reviewed = reviewed_copy(tmp_path, blob(repo, "scan.pdf"), blob(repo, "page.pdf"))
    assert scrub(repo, script=reviewed).returncode == 0


def test_an_unreadable_pdf_is_a_finding(repo):
    (repo / "broken.pdf").write_bytes(b"not really a pdf \0\1")
    r = scrub(repo)
    assert r.returncode == 1 and "broken.pdf: [binary-needs-review] .pdf" in r.stdout


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="needs pdftotext (poppler-utils)")
def test_a_pdfs_text_is_still_scanned(repo, tmp_path):
    commit(repo, "page.pdf", tiny_pdf("A plain demo test page"), "clean page")
    reviewed = reviewed_copy(tmp_path, blob(repo, "page.pdf"))
    assert scrub(repo, "--history", script=reviewed).returncode == 0     # reviewed and clean
    commit(repo, "page.pdf", tiny_pdf("Call " + PHONE), "dirty page")
    r = scrub(repo, "--history", script=reviewed)
    assert r.returncode == 1
    assert "page.pdf: [binary-needs-review]" in r.stdout                  # a new blob needs review
    assert "page.pdf:1: [phone-number]" in r.stdout                       # and its text is scanned


def test_history_flags_an_unreadable_pdf(repo):
    commit(repo, "broken.pdf", b"not really a pdf \0\1", "broken pdf")
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "broken.pdf: [binary-needs-review] .pdf" in r.stdout


def test_one_nul_byte_does_not_hide_a_text_file(repo):
    # The gate before the review read one NUL in the first 8 KB as "binary", skipped the file and
    # exited 0, whatever came after it (the Oracle's repro on PR #4).
    (repo / "notes.txt").write_bytes(b"harmless\n\0\n" + ("call " + PHONE + "\n").encode())
    r = scrub(repo)
    assert r.returncode == 1 and "notes.txt: [binary-needs-review]" in r.stdout
    commit(repo, "notes.txt", (repo / "notes.txt").read_bytes(), "a nul")
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "notes.txt: [binary-needs-review]" in r.stdout
    r = scrub(repo, "--stdin", "t", stdin="ok\0 " + PHONE)       # a prompt with a NUL is refused too
    assert r.returncode == 1 and "<t>: [unreadable-text]" in r.stdout


def test_utf16_text_is_decoded_and_scanned(repo):
    (repo / "notes.txt").write_bytes(("call " + PHONE + "\n").encode("utf-16"))   # with a BOM
    r = scrub(repo)
    assert r.returncode == 1 and "notes.txt:1: [phone-number]" in r.stdout
    (repo / "notes.txt").write_bytes(("call " + PHONE + "\n").encode("utf-16-le"))  # no BOM
    r = scrub(repo)
    assert r.returncode == 1 and "notes.txt: [binary-needs-review]" in r.stdout


# ---------------------------------------------------------------- JSON (Aurora's 23:18 patch)
def test_jsonl_is_scanned_as_decoded_strings(repo):
    decorator = j('{"type": "tool_use", "parameters": {"content": "import pytest\\n\\n@',
                  'pytest.fixture\\ndef x(): pass"}}\n')
    (repo / "run.jsonl").write_text(decorator, encoding="utf-8")
    assert scrub(repo).returncode == 0            # an escaped newline before a decorator is not an address
    real = '{"type": "message", "content": "ok\\n' + j("alice@", "corp-mail.com") + '"}\n'
    (repo / "run.jsonl").write_text(decorator + real, encoding="utf-8")
    r = scrub(repo)
    assert r.returncode == 1 and "run.jsonl:2: [email]" in r.stdout        # the file's own line
    commit(repo, "run.jsonl", decorator + real, "a run")
    git(repo, "rm", "-q", "run.jsonl")
    git(repo, "commit", "-q", "-m", "drop it")
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "run.jsonl:2: [email]" in r.stdout


@pytest.mark.parametrize("name,text", [
    ("cfg.json", '{"db": {"password": "' + j("hunter2", "hunter2") + '"}}\n'),
    ("cfg.json", '{"tokens": ["' + j("q7Rf9L", "mZ2xKp") + '"]}\n'),                  # an array under the key
    ("cfg.json", '{"password": ' + j("8675", "30912") + '}\n'),                       # a number
    ("run.jsonl", '{"api_key": "' + j("q7Rf9L", "mZ2xKp") + '"}\n'),
    ("run.jsonl", '{"BOB_API_KEY": "' + j("abcdef", "1234567") + '"}\n'),
])
def test_a_json_member_named_like_a_secret_is_caught(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8")
    r = scrub(repo)
    assert r.returncode == 1 and "[credential-assignment]" in r.stdout


def test_a_json_blob_in_history_is_decoded_whole(repo):
    commit(repo, "cfg.json", j('{\n  "note": "line\\n@', 'decorator.here",\n  "n": 1\n}\n'), "cfg")
    assert scrub(repo, "--history").returncode == 0
    commit(repo, "cfg.json", '{\n  "note": "mail\\n' + j("alice@", "corp-mail.com") + '"\n}\n', "cfg 2")
    r = scrub(repo, "--history")
    assert r.returncode == 1 and "cfg.json:json-string-2: [email]" in r.stdout


# ---------------------------------------------------------------- the private deny-list
def test_deny_list_matches_ignoring_case(repo, tmp_path):
    deny = tmp_path / "deny.txt"
    deny.write_text("# a comment line is not an entry\nzebrafish-house\n", encoding="utf-8")
    r = scrub(repo, "--stdin", "t", "--require-deny", deny=deny, stdin="the ZEBRAFISH-House host\n")
    assert r.returncode == 1
    assert r.stdout.strip() == "<t>:1: [deny-list#2]"          # where and which entry, nothing else
    for piece in ("ZE", "ze", "se", "15"):                      # no excerpt, no length
        assert piece not in r.stdout


def test_a_private_value_split_across_literals_is_still_caught(repo, tmp_path):
    # A test vector is real-SHAPED and fictional; split with j() it hides from every regex. A
    # private entry that matches the joined literals is therefore always a real value (Lucid, 9/29).
    deny = tmp_path / "deny.txt"
    deny.write_text("zebrafish\\.house\n", encoding="utf-8")
    src = ('VECTOR = j("zebra", "fish.", "house")\n'
           'OTHER = "zebra" + "fish.house"\nTHIRD = ("zebra" "fish.house")\n')
    r = scrub(repo, "--stdin", "t", "--require-deny", deny=deny, stdin=src)
    assert r.returncode == 1
    assert [x for x in r.stdout.splitlines() if x] == [f"<t>:{n}: [deny-list#1]" for n in (1, 2, 3)]
    wrapped = 'V = j(\n    "zebra",\n    "fish.house",\n)\n'              # as a formatter wraps it
    r = scrub(repo, "--stdin", "t", "--require-deny", deny=deny, stdin=wrapped)
    assert r.returncode == 1 and r.stdout.strip() == "<t>:joined: [deny-list#1]"
    mixed = 'W = "zebra" \'fish.house\'\nX = b"zebra" b"fish.house"\n'           # mixed quotes, bytes
    r = scrub(repo, "--stdin", "t", "--require-deny", deny=deny, stdin=mixed)
    assert r.returncode == 1 and r.stdout.split() == ["<t>:1:", "[deny-list#1]", "<t>:2:", "[deny-list#1]"]
    # the generic rules do not join: a real-shaped positive control stays a quiet vector
    r = scrub(repo, "--stdin", "t", "--require-deny", deny=deny, stdin='BAD = j("10.", "0.9.9")\n')
    assert r.returncode == 0


def test_a_deny_list_with_no_entries_is_refused(repo, tmp_path):
    deny = tmp_path / "deny.txt"
    deny.write_text("# only comments\n\n", encoding="utf-8")
    assert scrub(repo, "--stdin", "t", "--require-deny", deny=deny, stdin="x\n").returncode == 2
    r = scrub(repo, "--stdin", "t", deny=deny, stdin="x\n")     # without --require-deny: generic only
    assert r.returncode == 0 and "no entries" in r.stderr


def test_a_missing_deny_list_is_refused_when_required(repo):
    assert scrub(repo, "--stdin", "t", "--require-deny", stdin="x\n").returncode == 2


def test_the_shadow_mode_reads_the_disk_and_nothing_else(repo):
    """test.sh runs `--shadow` before the sandbox (the Oracle's delta on PR 11). It sees what Python would
    import, tracked or not: a json.py, a json symlink, tests/re.py and a scripts/hashlib/ package. It
    scans no content, so a phone number in a file is not its business (the commit gates own that)."""
    (repo / "notes.txt").write_text(f"call {PHONE}\n", encoding="utf-8")
    assert scrub(repo, "--shadow").returncode == 0, "a content finding must not fail --shadow"
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "json.py").write_text("x = 1\n", encoding="utf-8")                    # untracked, unstaged
    (repo / "subprocess").symlink_to("pkg")
    for rel in ("tests/re.py", "scripts/hashlib/__init__.py", "faxcli/json.py", "tests/test_json.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x = 1\n", encoding="utf-8")
    r = scrub(repo, "--shadow")
    flagged = {x.split(":")[0] for x in r.stdout.splitlines() if "[stdlib-shadow]" in x}
    assert r.returncode == 1
    assert flagged == {"json.py", "subprocess", "tests/re.py", "scripts/hashlib/__init__.py"}, r.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root lists a mode-0311 directory anyway")
@pytest.mark.parametrize("rel", ["json", "scripts/hashlib", "tests"])
def test_the_shadow_mode_flags_a_directory_it_cannot_list(repo, rel):
    """A directory that cannot be listed is a finding, never skipped. Python imports json/__init__.py by
    path through a directory it may not list (mode 0311), so a check that skipped what it could not list
    read a planted package as clean (Aurora's audit, after #21). Covered: a package at the root, a package
    in scripts/, and a sys.path directory itself (tests/). The plant is a finding while listable, the
    control."""
    d = repo / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / ("re.py" if rel == "tests" else "__init__.py")).write_text("x = 1\n", encoding="utf-8")
    assert "[stdlib-shadow]" in scrub(repo, "--shadow").stdout                  # seen while listable
    d.chmod(0o311)
    try:
        r = scrub(repo, "--shadow")
        if rel == "json":           # the threat is real: Python imports the plant through what it cannot list
            imp = subprocess.run(["python3", "-c", "import json; print(json.x)"], cwd=repo,
                                 capture_output=True, text=True, check=False)
            assert imp.stdout.strip() == "1", imp.stderr
    finally:
        d.chmod(0o755)
    assert r.returncode == 1 and f"{rel}/: [unlistable]" in r.stdout, r.stdout + r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory anyway")
def test_test_sh_refuses_a_tree_it_cannot_search_for_stray_bytecode(tmp_path):
    """test.sh looks for sourceless bytecode (json.pyc, json.so) before anything runs. A directory that find
    cannot read might hold some, so that refuses too, with a reason; it used to stop only through set -e,
    with exit 1 and no reason (Aurora's audit, after #21). It stops before any test or sandbox runs."""
    repo = tmp_path / "t"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT.parent / "test.sh", repo / "scripts" / "test.sh")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    locked = repo / "locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        r = subprocess.run(["bash", "scripts/test.sh"], cwd=repo, capture_output=True, text=True, timeout=60,
                           check=False)
    finally:
        locked.chmod(0o755)
    assert r.returncode == 2 and "could not all be searched" in r.stderr, r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory anyway")
def test_test_sh_prunes_git_venv_and_pycache_from_its_search(tmp_path):
    """.git, .venv and every __pycache__ are pruned, not walked, so an unreadable directory there cannot block
    the stray-bytecode search (the standing Oracle, on #26). The throwaway repo has no scrub-check.sh, so
    test.sh stops at the next step; what matters is that the search itself passed."""
    repo = tmp_path / "t"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(SCRIPT.parent / "test.sh", repo / "scripts" / "test.sh")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    locked = [repo / ".git" / "locked", repo / ".venv" / "lib" / "locked",
              repo / "pkg" / "__pycache__" / "locked"]
    for d in locked:
        d.mkdir(parents=True)
        d.chmod(0)
    try:
        r = subprocess.run(["bash", "scripts/test.sh"], cwd=repo, capture_output=True, text=True, timeout=60,
                           check=False)
    finally:
        for d in locked:
            d.chmod(0o755)
    assert "could not all be searched" not in r.stderr, r.stderr
    assert "the shadow check itself failed" in r.stderr, r.stderr                # it got past the search


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 directory anyway")
def test_paths_mode_flags_what_it_cannot_read(repo):
    """--paths scans the files it is given and everything under a directory it is given. A subdirectory it
    cannot list, or a file it cannot read, might hold anything, so each is a finding. os.walk skipped an
    unlistable directory silently, and an unreadable file ended the scan with a traceback (Aurora's Oracle,
    after #21). While readable, the number in each is found: the control."""
    base = repo / "prompts"
    (base / "sub").mkdir(parents=True)
    (base / "sub" / "p.md").write_text("call " + PHONE + "\n", encoding="utf-8")
    (base / "q.md").write_text("call " + PHONE + "\n", encoding="utf-8")
    ok = scrub(repo, "--paths", str(base))
    assert ok.returncode == 1 and ok.stdout.count("[phone-number]") == 2, ok.stdout
    (base / "sub").chmod(0)
    (base / "q.md").chmod(0)
    try:
        r = scrub(repo, "--paths", str(base))
    finally:
        (base / "sub").chmod(0o755)
        (base / "q.md").chmod(0o644)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "sub/: [unlistable]" in r.stdout and "q.md: [unreadable]" in r.stdout, r.stdout + r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file anyway")
def test_the_default_scan_flags_a_file_it_cannot_read(repo):
    """The default scan (everything git would publish) reads every file. One it cannot open is a finding
    that says where, not a traceback (the standing Oracle, on #26). While readable, the number in it is
    found: the control."""
    f = repo / "notes.txt"
    f.write_text("call " + PHONE + "\n", encoding="utf-8")
    ok = scrub(repo)
    assert ok.returncode == 1 and "notes.txt:1: [phone-number]" in ok.stdout, ok.stdout
    f.chmod(0)
    try:
        r = scrub(repo)
    finally:
        f.chmod(0o644)
    assert r.returncode == 1 and "notes.txt: [unreadable]" in r.stdout, r.stdout + r.stderr
    assert "Traceback" not in r.stderr, r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root searches a mode-0600 directory anyway")
def test_the_default_scan_flags_a_file_under_a_directory_it_cannot_search(repo):
    """git lists a tracked file whose directory the scan cannot search. stat fails there, so an isfile()
    filter dropped the file silently (the standing Oracle, on #28); it is [unreadable] now. A tracked file
    deleted from the tree has no content and is not a finding. While searchable, the number in the file is
    found: the control."""
    commit(repo, "sub/f.txt", "call " + PHONE + "\n", "a file in sub")
    commit(repo, "gone.txt", "nothing\n", "a file deleted from the tree later")
    (repo / "gone.txt").unlink()
    ok = scrub(repo)
    assert ok.returncode == 1 and "sub/f.txt:1: [phone-number]" in ok.stdout, ok.stdout
    assert "gone.txt" not in ok.stdout, ok.stdout
    (repo / "sub").chmod(0o600)                          # listable, not searchable: stat of sub/f.txt fails
    try:
        r = scrub(repo)
    finally:
        (repo / "sub").chmod(0o755)
    assert r.returncode == 1 and "sub/f.txt: [unreadable]" in r.stdout, r.stdout + r.stderr
    assert "gone.txt" not in r.stdout, r.stdout


@pytest.mark.parametrize("sub", ["node_modules", "__pycache__", ".venv", "deep/.git"])
def test_paths_mode_prunes_only_a_git_directly_under_its_argument(repo, sub):
    """Given a directory, --paths skipped .git, .venv, __pycache__ and node_modules at any depth, so a number
    in one went unseen at export time (Lucid, auditing #27). Only a .git directly under the argument is
    skipped now, since its objects are binary by design: the same number there stays unflagged."""
    base = repo / "site"
    (base / sub).mkdir(parents=True)
    (base / sub / "x.txt").write_text("call " + PHONE + "\n", encoding="utf-8")
    (base / ".git").mkdir()
    (base / ".git" / "y.txt").write_text("call " + PHONE + "\n", encoding="utf-8")
    r = scrub(repo, "--paths", str(base))
    flagged = [x for x in r.stdout.splitlines() if "[phone-number]" in x]
    assert r.returncode == 1 and len(flagged) == 1 and f"{sub}/x.txt" in flagged[0], r.stdout


def test_paths_mode_flags_a_named_file_that_is_missing(repo):
    """A path named on purpose must exist: a missing one is [unreadable], never a quiet pass (a mistyped
    prompt path would otherwise scan as clean)."""
    r = scrub(repo, "--paths", str(repo / "no-such-prompt.md"))
    assert r.returncode == 1 and "no-such-prompt.md: [unreadable]" in r.stdout, r.stdout + r.stderr


def test_a_fifo_where_a_tracked_file_was_never_blocks_the_scan(repo):
    """A tracked path replaced by a FIFO has no content to scan, and opening it would block the scan, and a
    hook with it, for ever (the standing Oracle, on #30). The default scan skips it; --paths named on it
    reports it. Both must finish."""
    commit(repo, "pipe.txt", "x\n", "a file that becomes a FIFO")
    (repo / "pipe.txt").unlink()
    os.mkfifo(repo / "pipe.txt")
    env = {**os.environ, "CI": "1", "FAX_CONSOLE_SCRUB_DENY": str(repo / "no-such-deny.txt")}
    try:
        r = subprocess.run(["bash", str(SCRIPT)], cwd=repo, env=env, capture_output=True, text=True,
                           timeout=60, check=False)
        named = subprocess.run(["bash", str(SCRIPT), "--paths", str(repo / "pipe.txt")], cwd=repo, env=env,
                               capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired:
        pytest.fail("the scan blocked on a FIFO")
    assert r.returncode == 0 and "pipe.txt" not in r.stdout, r.stdout + r.stderr
    assert named.returncode == 1 and "pipe.txt: [unreadable]" in named.stdout, named.stdout + named.stderr


def test_a_tracked_file_whose_directory_became_a_file_is_not_a_finding(repo):
    """git still lists a/b.txt after a/ was replaced by a regular file. The path fails with ENOTDIR, and the
    file is simply absent, so it is not a finding (the standing Oracle, on #30)."""
    commit(repo, "a/b.txt", "x\n", "a file in a/")
    shutil.rmtree(repo / "a")
    (repo / "a").write_text("now a file\n", encoding="utf-8")
    r = scrub(repo)
    assert r.returncode == 0 and "[unreadable]" not in r.stdout, r.stdout + r.stderr


def test_the_default_scan_reads_a_links_text_which_is_what_git_publishes(repo):
    """git publishes a symlink as its target text, not as what it points at, so the default scan reads that
    text. A number in a dangling link is found, and a link that loops is no false finding (the standing
    Oracle, on #30)."""
    os.symlink("call " + PHONE, repo / "lnk")
    os.symlink("loop", repo / "loop")
    r = scrub(repo)
    assert r.returncode == 1 and "lnk:1: [phone-number]" in r.stdout, r.stdout + r.stderr
    assert "loop" not in r.stdout, r.stdout
