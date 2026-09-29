# Work log

## Run 12

**Item 1 — Failed originate raises SendError.**
`faxcli/api.py`, `faxcli/cli.py` (SendError already defined); `tests/test_run12.py` (4 tests).
793 tests total (772 before + 21 new).

**Item 2 — Failed "before" stats read → UNMEASURED outcome.**
`faxcli/api.py`, `faxcli/outcome.py`; `tests/test_run12.py` (5 tests).
793 tests total.

**Item 3 — Empty CDR file field matches nothing.**
`faxcli/api.py`; `tests/test_run12.py` (3 tests).
793 tests total.

**Item 4a — Non-local render uses tempfile.mkdtemp.**
`faxcli/api.py`; `tests/test_run12.py` (2 tests).
793 tests total.

**Item 4b — '--' before host in SshTransport._ssh.**
`faxcli/transport.py`; `tests/test_run12.py` (4 tests).
793 tests total.

**Item 4c — LocalTransport.read_cdr honours limit.**
`faxcli/transport.py`; `tests/test_run12.py` (3 tests).
793 tests total.

**Docs — docs/changes.md created.**
`docs/changes.md`; records all run-12 deliberate divergences plus Finding A from run 8.
793 tests total.

**ReplayTransport — channel originate handled gracefully.**
`faxcli/transport.py`; `ReplayTransport.asterisk` now returns success for `channel originate …`
commands (dynamic TIFF path cannot be pre-recorded as a fixture).
793 tests total.
