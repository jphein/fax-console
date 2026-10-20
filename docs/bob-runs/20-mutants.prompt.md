Two behaviour gaps survived mutation testing of the coverage tests from your last run. Read `AGENTS.md` first. Add tests only; don't change production code.

1. `faxconsole/pbx.py`, around line 105:
   `ncc = sum(1 for v in subs.values() if v["in_call"])`
   With the condition inverted (`if not v["in_call"]`), the WHOLE suite still passes. Add a test that builds a vty reading with several subscribers, some carrying a call and some signalling only. Assert the exact note text, e.g. "2 of 3 carrying call-control; …". It must fail on the inverted condition.

2. `faxcli/cli.py`, around line 242 (the `test` subcommand):
   `if not a.wait:\n        a.wait = 90`
   Inverting it (`if not (not a.wait):`) still passes. Add tests for BOTH branches:
   - no --wait given: the send gets wait == 90;
   - an explicit wait (e.g. --wait 30): it is kept at 30, not overwritten.
   Read how `main()` parses `test` arguments (its default for --wait) so the "not given" case really is not given.

Check each new test by temporarily applying the inversion in your working copy, confirming the test fails, and then restoring the file exactly. Leave `git diff faxconsole faxcli` empty at the end.

Done when `.venv/bin/python -m pytest -q tests/test_pbx_coverage.py tests/test_cli_coverage.py` passes and you've confirmed each test fails on its mutant. Put the new tests in those two files.
