Week 2, run 6: extract the Fax panel's back end and the PBX status readers from the legacy console into a new stdlib package, `faxconsole/`. Read these first:
- `AGENTS.md`;
- `docs/console-slice.md`, the map of exactly what to extract, with excerpt line numbers (e:);
- `docs/analysis.md` §9, finding F (unbounded threads);
- the `faxcli/` package, which you wrote in runs 4 and 5.

Never edit `legacy/`, `faxcli/`'s public behaviour, or `tests/test_sandbox_guard.py`.

**Design (decided; follow it):**
1. **Import `faxcli`; do not shell out to it.** The legacy `fax_cli()` (e:2010–2027) spawned the CLI "so the CLI and this panel cannot disagree" (e:1993–2003). A shared package gives the same guarantee without a process. `fax_state` and `fax_send` (e:2030–2090) become calls into `faxcli` with a `faxcli.transport.Transport`.
2. **The PBX readers** `read_trunk` (e:1009–1021), `read_calls` (e:1024–1104) and `read_sip_endpoints` (e:1108–1136) move to `faxconsole/pbx.py`. They are pure parsers over `transport.asterisk(...)` Readings. Legacy `ast()` returned `None` on failure, and the pages rendered that as "not probed"; keep exactly that meaning, as a failed `Reading`.
   - `read_calls` is MIXED. Keep its Asterisk instrument. Its cellular-core instrument (the call to the elided `vty(MSC_VTY, …)`) becomes an optional injected callable that defaults to "not probed". Keep the legacy result shape: `instruments`, `value`, `cellular`, `impossible`.
3. **The server core is a pure function**, `handle(method, path, headers, body) -> Response`, with no sockets. A thin adapter on `http.server` wraps it, using a **fixed-size worker pool**, never a thread per request (that fixes analysis §9 F).
   - **Tests must never open a TCP port.** Inside the sandbox, loopback is blocked on purpose. Test `handle()` directly, and test the adapter over `socket.socketpair()` (AF_UNIX).
4. **Routes:**
   - `GET /api/fax/status` returns the faxcli status JSON, and `GET /api/fax/log?limit=N` the log JSON.
   - `GET /api/fax` returns the **legacy** combined shape of `fax_state` (e:2030–2037: `ok, status, log, why, src, spool, inbox`), so the old page keeps working.
   - `GET /api/pbx/trunk`, `/api/pbx/calls` and `/api/pbx/endpoints` return the reader dicts. Each carries `ok` and `src`, as the legacy readers did.
   - `POST /api/fax/send` is a multipart PDF upload. Port `_multipart` (e:2040–2055) and the legacy validation, size cap and explicit `confirm=yes`. The write gate is the X-Auth-Token check (legacy `write_authorized`, e:2914–2951, with `hmac.compare_digest`, failing closed when no token is set).
   - `GET /api/version` returns the realm-sigil contract. Port `version_dict`, `generate_name` and the word lists (e:350–455), with the name `fax.realm.watch`.
   - Unknown paths get a 404 with the path HTML-escaped (legacy `html_escape`, e:2656).
5. **Modes.** `python3 -m faxconsole --replay DIR [--port 8093]` serves the recorded fixtures through `faxcli.transport.ReplayTransport`. In replay mode, `POST /api/fax/send` always runs as a **dry run**: it renders into a temporary spool, never dials, and says `"replay": true` with a detail of "replay: nothing is dialled". `--local` and ssh use the real transports, and no test runs them. The server binds 127.0.0.1 by default.

**Tests** (pytest, `tests/test_faxconsole_*.py`), 40 or more. They cover:
- every route through `handle()`: the status codes, and the JSON shapes against the faxcli goldens;
- the legacy `/api/fax` shape;
- characterization: import the frozen `legacy/console/telephony-console.py` read-only with `importlib`. Its module-level code does not bind a port, but it runs two things at import:
  - `BUILD = _build_info()` (e:431; the function is at e:404), which calls `git` through `subprocess.run`. So install a refusing fake `subprocess.run` BEFORE the import, or conftest's guard raises mid-import.
  - `VOIPMS = VoipMsPoller()` (e:1006), which reads cache paths and tolerates their absence.

  Feed its `read_trunk`, `read_calls` and `read_sip_endpoints` the same fixture text through a fake `ast`, and assert that yours agree field by field;
- the send path: gate refusals (no token configured, a wrong token, `confirm` missing, oversize, not a PDF) and a replay dry run that writes only inside a temp dir;
- 404 escaping, and the version contract;
- the adapter over socketpair, including a request that exceeds the pool (it queues rather than spawning).

No test may spawn a process or open a TCP socket; conftest already blocks processes.

**Tooling:** add `faxconsole` to `pyproject.toml` packages. `.venv/bin/python -m pytest -q` must show 0 failures, and `.venv/bin/ruff check .` must be clean. Then give a short summary: the files, the test count, and any legacy behaviour you found surprising, with its e: line number.
