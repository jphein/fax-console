Week 2, run 11: review fixes in `faxconsole/`. Read `AGENTS.md` first. Never edit `legacy/`, `tests/test_sandbox_guard.py` or `tests/conftest.py`. All existing tests must stay green.

**Keep a work log.** As in runs 8–10: after each numbered item, append one line to `WORKLOG.md` at the repo root, with the item, the files and the test count.

**1. The public replay surface (do this first).** Replay mode is the public demo, so no response may carry anything derived from the machine it runs on. That covers the hostname, runtime paths, IP addresses and user names. Recorded fixture data is fine: the CDR's spool paths and the TEST-NET addresses in the fixtures.
- Today `/api/fax` returns `inbox` and `spool` as `/tmp/faxconsole-replay-XXXX/...`, and a replay `POST /api/fax/send` returns `pdf` and `tif` under the same temp dir.
- In replay mode, show the temp dir as a neutral token, such as `replay:` in place of the directory. The legacy JSON keeps its keys; only the values change.
- Add a test that scans every replay GET route, plus one dry-run send, and fails on the temp dir, the hostname (monkeypatch `socket.gethostname` to a fictional `pbx7.example.net`), or any absolute path under `/tmp`, `/home` or `/etc`. A short allowlist covers the recorded fixture values, each with a comment.

**2. Headers.** Send `X-Content-Type-Options: nosniff` on every response, the JSON API included, not only the static files.

**3. `server.py`:**
- Give the handler a socket timeout, so a client that connects and sends nothing cannot hold a worker forever. Test it over a socketpair.
- If `pool.submit` raises (the pool is shut down), release the permit and close the socket.

**4. `__main__.py`:**
- `build()` returns the parsed arguments too, so `main()` stops re-parsing argv with a second parser.
- Create the server inside the `try`, so a failed bind still runs cleanup. Test it with a `FaxServer` that raises, and check that the temp dir is removed.

**5. Replay spool.** `ReplayTransport(spool_dir=…)` and `Config.spool` must name the same directory. Today renders land in the temp dir's root while `Config.spool` says `…/spool`.

**6. `faxcli`:**
- Define `TRUNK` once: `cli.py` and `api.py` each define it today.
- Rename `faxcli/numbers.py` to `faxcli/phone_numbers.py`. It shadows the stdlib `numbers` module when a file in `faxcli/` runs as a script. Update every import, and delete the old file; git commands are not available to you, so write the new file and remove the old one.

**7. Test speed.** The adapter tests in `tests/test_faxconsole_adapter.py` each wait out a 2 s read timeout. Read to EOF instead, as the bounded-queue tests in `tests/test_part1_review.py` do.

`.venv/bin/python -m pytest -q` must show 0 failures, and `.venv/bin/ruff check .` must be clean. End with a short summary: what changed for each numbered item, the test count before and after, and anything you disagree with, with the reason.
