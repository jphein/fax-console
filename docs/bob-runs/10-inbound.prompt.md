Week 2, run 10. Turn the inbound-fax design into generated configuration and tests. Nothing is deployed and nothing touches a PBX: every function returns text. Read these first:
- `AGENTS.md`;
- `legacy/fax/docs/inbound.md`, the design; option A, a second DID only for fax, is the recommended one;
- `docs/analysis.md` §8(d), your own plan for this step, and §9 item 5, the review's correction to it.

Never edit `legacy/`, `tests/test_sandbox_guard.py` or `tests/conftest.py`. All existing tests must stay green.

**Keep a work log.** As in runs 8 and 9: after each numbered item, append one line to `WORKLOG.md` at the repo root, with the item, the files and the test count.

**1. `faxcli/inbound.py`.** `render_dialplan(config) -> str` renders option A's `[from-fax-did]` context from a small frozen dataclass: the context name, the DID, the spool directory and the hook path. It writes nothing and runs nothing. Use fictional values only. The fax DID is `202-555-0177`. It is deliberately not `202-555-0100`, the house number's stand-in: option A is a second number, and nothing may touch the house line.

**2. Untrusted input.** Treat every channel variable the caller controls as untrusted. For each one, decide what it can reach in the rendered dialplan, such as a file name or a command line, and make the rendering safe against hostile input. Explain your choice in a comment and in your summary.

**3. `render_hook(config) -> str`.** Render the `fax-inbound-hook` script that the dialplan's `h` extension calls. It:
- converts the TIFF to PDF (`tiff2pdf`);
- files the PDF in the inbox;
- runs an optional notify command from the config, with the fax's facts as separate arguments and never through a shell.

It must be safe with the same untrusted inputs. It is generated text only.

**4. The CLI.** `fax inbound --render` prints the dialplan, then the hook, to stdout. It never writes a file.

**5. Tests** in `tests/test_inbound.py`, 15 or more:
- the structure: `exten =>`, `ReceiveFax` with the `f` option, `FAXOPT(ecm)` and the `h` extension;
- a golden of the rendered dialplan;
- hostile caller IDs: a quote, a semicolon, `$(…)`, a backtick, `../` and a newline. None may reach a path or a command unescaped.

Asterisk has no offline syntax check that the sandbox or CI could run (see §9 item 5), so the tests check structure and the golden.

`.venv/bin/python -m pytest -q` must show 0 failures, and `.venv/bin/ruff check .` must be clean. End with a short summary: what changed for each numbered item, the test count before and after, and anything you disagree with, with the reason.
