Week 2, run 13: the independent review's findings in `faxconsole/` and `faxcli/`. Read `AGENTS.md` first. Never edit `legacy/`, `tests/test_sandbox_guard.py` or `tests/conftest.py`. All existing tests must stay green.

**Keep a work log.** After each numbered item, append one line to `WORKLOG.md` at the repo root, with the item, the files and the test count. Runs 11 and 12 reached their caps mid-item, so start with item 1 and finish each item, tests included, before starting the next.

**1. (Must fix) Read no POST body before the gate.** `faxconsole/server.py`'s `do_POST` reads the whole body, and only then does `routes.py` check the token and the size. Legacy did both first ("FIRST, before any route matching or body read": `legacy/console/telephony-console.py` e:2953–2961).
- An anonymous client can declare a huge `Content-Length`: `rfile.read(n)` reserves n bytes. Three 400 MB requests grew the process from 41 MB to 1.43 GB.
- In `do_POST`, before reading anything, run the same token check the write gate uses, then check the declared length against the cap: `max_bytes` plus a small multipart allowance. Answer 401 or 413 without reading the body. Then read the body in bounded chunks, never more than the cap.
- Tests over a socketpair (`FaxServer(..., bind=False)` and `process_request`, as `tests/test_part1_review.py` does):
  - a POST with no token that declares 50 MB and sends no body gets its 401 at once;
  - an authorized POST that declares more than the cap gets 413 without its body being read.

**2. (Must fix) In replay mode, error text leaks machine paths.** Replay mode is the public demo, and the rule covers every response, errors included. Today:
- `/api/fax/log` and `/api/fax` carry a `why` such as `[Errno 2] No such file or directory: '<replay dir>/cdr/Master.csv'`;
- `/api/voipms` carries an error naming `<replay dir>/voipms`;
- a send made after the temp spool vanished carries a `detail` of `render failed: [Errno 2] ... '<replay root>/spool/...'`;
- `could not store the PDF: {e}` and the adapter's 500 body, which is `str(exc)`, leak the same way.

In replay mode, pass every `why`, `detail` and `error` string through one masker. The replay root and the replay fixture dir become `replay:`, and any other absolute path becomes its file name; `routes._public_path` shows the idea.

Extend `tests/test_replay_surface.py`:
- run `build(["--replay", <an absolute dir holding only asterisk/>])` and check every GET, and a send made after the spool dir was removed: no absolute path, no replay dir and no temp dir, error paths included;
- make its path search find a path anywhere inside a string, not only when the path is a whole JSON string;
- cover `/api/voipms`.

**3. Live-mode details:**
- `routes.py` passes `local=True` to `send()` in every mode, so under `--ssh` the render goes into `/var/spool` on the console host. Pass `local=True` only for a `LocalTransport`.
- `scp` in `SshTransport` needs `--` before its operands, as ssh has.
- `GET /api/fax/log?limit=<huge>` makes `deque(maxlen)` raise `OverflowError`, which becomes a 500. Clamp `limit` in the route (for example 1–1000). Also, `ReplayTransport` returns every row for a limit of 0 or less, while Local and Ssh return none: make replay agree.

**4. `ReplayTransport.which_gs` fabricates a success,** "/usr/bin/gs". That is finding A's pattern: the replay status shows ghostscript as present when nothing was measured. Serve the recorded fixture if `tests/fixtures/asterisk/` has one, otherwise report it unread.

**5. Small items:**
- `api.send` can still raise an untyped `OSError` (from `open(pdf)` or `mkdtemp`); raise it as `SendError`.
- `api.py`'s docstring still cites `faxcli.numbers`.

`.venv/bin/python -m pytest -q` must show 0 failures, and `.venv/bin/ruff check .` must be clean. End with a short summary: what changed for each numbered item, the test count before and after, and anything you disagree with, with the reason.
