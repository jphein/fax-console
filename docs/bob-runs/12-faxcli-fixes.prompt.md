Week 2, run 12: deliberate fixes to behaviours `faxcli` kept from legacy, plus three hardening items. Read these first:
- `AGENTS.md`;
- `docs/analysis.md` §9, which covers finding A, the first deliberate change: an unreadable PBX now reports `ok: false` with `why` and `unread`, where legacy said `ok: true`;
- the `faxcli/` package.

Never edit `legacy/`, `tests/test_sandbox_guard.py` or `tests/conftest.py`. All other existing tests must stay green, except the ones this run deliberately changes. For each of those, say which in the work log.

**Keep a work log.** As in runs 8–11: after each numbered item, append one line to `WORKLOG.md` at the repo root, with the item, the files and the test count.

**Every behaviour change is deliberate, and each one gets:**
- a test that runs the frozen legacy code on the same input and records what legacy did, so the divergence is visible, not hidden;
- a test that pins the new behaviour;
- an entry in a new `docs/changes.md`: what legacy did, what faxcli does now and why, and the tests that pin it.

**1. A failed originate.** Legacy reports `ok: true` when `channel originate` fails. Make `send()` raise `SendError`, carrying the transport's `why`. The CLI prints the error and exits non-zero. The JSON of a successful send stays the same.

**2. A failed "before" stats read.** When the first `fax show stats` read fails, legacy counts the outcome's delta from zero, so any fax the PBX handled earlier looks like this one. Mark the outcome as unmeasured instead, using the same "unread" convention as finding A, so the result never claims a delta it did not measure.

**3. An empty CDR `file` field.** It matches any send, because every path ends with the empty string. An empty or missing `file` must match nothing.

**4. Hardening:**
- The non-local render goes to a predictable path under `/tmp`, which another user could pre-create or symlink. Use `tempfile.mkdtemp` and clean it up.
- In `SshTransport`, put `--` before the host, so a host from `FAX_EXCHANGE_HOST` that starts with `-` cannot become an ssh option. Pin it in the argv tests.
- `LocalTransport.read_cdr` ignores its `limit`. Honour it, and test it.

`.venv/bin/python -m pytest -q` must show 0 failures, and `.venv/bin/ruff check .` must be clean. End with a short summary: what changed for each numbered item, the test count before and after, and anything you disagree with, with the reason.
