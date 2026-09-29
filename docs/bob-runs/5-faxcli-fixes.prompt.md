You wrote `faxcli/` in the previous run, and a reviewer has read it. The architecture is right: pure parsers, `Reading`, `ReplayTransport`, the deliberate `ok: false` change, and the golden and characterization tests. Keep all of that. Fix the findings below, then prove each fix with a test. Read `AGENTS.md` first. Never edit `legacy/` or `tests/test_sandbox_guard.py`. You run in an OS sandbox; nothing here may reach a network or a PBX.

**Two production regressions.** The tests missed both because `ReplayTransport` bypasses them.
1. **`SshTransport._ssh` joins the remote command without quoting** (`faxcli/transport.py`, `" ".join(argv)`). The remote shell splits `asterisk -rx fax show stats` into separate words, so Asterisk runs `-rx fax`. Legacy quoted every argument (`legacy/fax/fax/cli.py:55`, `shlex.quote`). Restore that.
2. **`LocalTransport` always prefixes `sudo -n`.** Legacy skips sudo when the effective user is `asterisk` (`legacy/fax/fax/cli.py:62-74`). That is how the console runs on the PBX, and there `sudo -n` fails, so every read would fail. Restore the rule behind an injectable user check, so tests don't depend on the real user.

**Parity and seams.**
3. **The host.** Read it from `FAX_EXCHANGE_HOST`, defaulting to `pbx` (`legacy/fax/fax/cli.py:24`). Use the same host for the ssh reads and for every step of `send`: the copy, the install and the cleanup. The "running on the PBX" check compares against that same name.
4. **`send` must go through the seam.** It currently calls ghostscript, `scp`, `ssh … install` and `rm` directly through `subprocess` in `faxcli/cli.py`. Move that I/O behind the transport: render, spool (copy plus install, or a local write) and cleanup. Then `send --dry-run` and `send` run under `ReplayTransport`, which renders and spools into a directory the test passes in. The JSON shapes stay exactly as they are.
5. **`fax test`** defaults to a page that is not in this repo (`docs/test-page.pdf`). The neutral test page lives at `demo/test-page.pdf` (it arrives with another branch, so tests must pass `--pdf` explicitly). Default to `demo/test-page.pdf`, and fail with a clear message if it is missing. Never point at any other document.

**Tests that would have caught 1–4.** Use a capturing fake `subprocess.run` inside the test. Cover:
- `"fax show stats"` arrives at ssh as ONE quoted remote argument;
- the host override;
- no sudo as the `asterisk` user, and sudo otherwise;
- `TimeoutExpired` becomes a failed `Reading`;
- `send --dry-run` under replay writes its TIFF into the test's directory and prints the legacy dry-run shape.

Also fix `TestCmdSendDryRunCharacterization::test_dry_run_required_fields`. It fails because legacy `--local` writes into the legacy spool path; point legacy's `SPOOL` at `tmp_path` with monkeypatch.

**Hygiene.**
- `tests/conftest.py`: tests marked `allow_subprocesses` must still have `subprocess.Popen` and `os.system` blocked. Only `subprocess.run` is left to the test's own fake.
- `pyproject.toml`: the build backend must be `setuptools.build_meta` (the current value does not exist). Add `extend-exclude = ["legacy"]` to `[tool.ruff]`, because the frozen baseline is not ours to lint.
- Fix every remaining ruff finding in `faxcli/` and `tests/`.
- Fix the pytest warnings "class-scoped fixture defined as instance method".

Finish when `.venv/bin/python -m pytest -q` shows 0 failures and 0 warnings from our files, and `.venv/bin/ruff check .` is clean. Then give a short summary: what changed for each numbered item, the test count before and after, and anything you disagree with in this review, with the reason.
