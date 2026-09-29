# Work log

Each line records one numbered item from the run it belongs to.

---

## Run 10 — inbound-fax dialplan and hook

1. `faxcli/inbound.py` — `InboundConfig` dataclass + `render_dialplan()`: renders `[from-fax-did]` context, uses fictional DID `202-555-0177`. Tests: 481 (56 new).
2. Untrusted input — `CALLERID(num)` wrapped with `FILTER(0-9+() -,…)` in both the `FAXFILE` path and the `System()` call; `SAFE_CALLERID_RE` exported for hook-side defence-in-depth. `faxcli/inbound.py`. Tests: 481.
3. `render_hook()` in `faxcli/inbound.py` — generates `fax-inbound-hook` shell script: `tiff2pdf`, inbox move, optional notify via `exec` (never shell expansion); re-validates caller-ID with `tr -cd '0-9+() -'`; validates `FAXFILE` is inside spool dir with `case`. Tests: 481.
4. `faxcli/cli.py` — `cmd_inbound()` + `inbound` subparser with `--render` flag; prints dialplan then hook to stdout, returns 0, touches nothing on disk or PBX. Tests: 481.
5. `tests/test_inbound.py` — 56 tests: config defaults, dialplan structure (exten =>, ReceiveFax+f, FAXOPT(ecm), h extension, FILTER usage), golden snapshot, 6 × 2 hostile caller-ID parametrized checks (quote, semicolon, `$(…)`, backtick, `../`, newline), `SAFE_CALLERID_RE` accept/reject, hook structure, notify variants, CLI integration. Tests: 481 (425 before, 481 after).
