Raise test coverage of the modern code with meaningful tests. Read `AGENTS.md` first and follow it exactly: fictional data only, no network, no PBX, no changes to `legacy/`.

Current line coverage (coverage.py over the suite):
- faxcli/transport.py 72%
- faxconsole/pbx.py 73%
- faxcli/cli.py 76%
- faxcli/tiff.py 81%
- faxconsole/__main__.py 83%

## Task
- Add tests (new files under `tests/`, named `test_<module>_coverage.py`) that bring each of these modules to at least 90%.
- Each test must assert behaviour (return values, raised errors, the exact command or JSON produced, files written), never just "it ran".
- Prefer the error and edge paths that are untested today:
  - transport timeouts and failures;
  - malformed input;
  - empty or oversize files;
  - CLI argument errors and exit codes;
  - the PBX adapter's failure replies.
- Use the existing fakes and fixtures in `tests/conftest.py` and the other tests. Read them first.
- Don't change production code. If a test exposes a real bug, mark the test `xfail` with a one-line reason naming the bug, and list it in your summary.

## How to check
Run `.venv/bin/python -m pytest -q tests` (it must stay green, apart from test_planted_bytecode::test_this_suite_runs_with_the_prefix, which needs scripts/test.sh) and `.venv/bin/python -m coverage run -m pytest -q tests && .venv/bin/python -m coverage report --include='faxcli/*,faxconsole/*'`.

## Done when
All five modules are at 90% or above, or you explain exactly which lines can't be covered without the network or PBX. End with the before/after coverage table and any bugs found.
