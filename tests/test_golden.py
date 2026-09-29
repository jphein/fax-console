"""Golden tests: main() driven by ReplayTransport must produce exactly the
recorded golden JSON objects (tests/fixtures/golden/).
"""
import io
import json
from pathlib import Path

import pytest

from faxcli.cli import main
from faxcli.transport import ReplayTransport

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden"


def run_main(args, transport):
    """Run main() and return the parsed JSON object printed to stdout."""
    buf = io.StringIO()
    rc = main(args, transport=transport, stdout=buf)
    assert rc == 0, f"main() returned {rc}"
    output = buf.getvalue().strip()
    assert output, "main() printed nothing"
    return json.loads(output)


class TestGoldenStatus:
    @pytest.fixture(scope="class")
    def golden(self):
        return json.loads((GOLDEN / "status.json").read_text())

    @pytest.fixture(scope="class")
    def result(self):
        transport = ReplayTransport()
        return run_main(["--json", "status"], transport)

    def test_ok(self, result, golden):
        assert result["ok"] == golden["ok"]

    def test_spandsp(self, result, golden):
        assert result["spandsp"] == golden["spandsp"]

    def test_trunk_registered(self, result, golden):
        assert result["trunk_registered"] == golden["trunk_registered"]

    def test_trunk_available(self, result, golden):
        assert result["trunk_available"] == golden["trunk_available"]

    def test_obi100_registered(self, result, golden):
        assert result["obi100_registered"] == golden["obi100_registered"]

    def test_active_sessions(self, result, golden):
        assert result["active_sessions"] == golden["active_sessions"]

    def test_stats(self, result, golden):
        assert result["stats"] == golden["stats"]

    def test_gs(self, result, golden):
        assert result["gs"] == golden["gs"]

    def test_full_object(self, result, golden):
        """The full JSON object must equal the golden, key for key."""
        assert result == golden


class TestGoldenLog:
    @pytest.fixture(scope="class")
    def golden(self):
        return json.loads((GOLDEN / "log.json").read_text())

    @pytest.fixture(scope="class")
    def result(self):
        transport = ReplayTransport()
        return run_main(["--json", "log", "--limit", "400"], transport)

    def test_ok(self, result, golden):
        assert result["ok"] == golden["ok"]

    def test_row_count(self, result, golden):
        assert len(result["rows"]) == len(golden["rows"])

    def test_row_fields_present(self, result, golden):
        required = {"start_local", "direction", "number", "disposition", "billsec", "file"}
        for row in result["rows"]:
            assert required <= set(row.keys())

    def test_full_object(self, result, golden):
        """Every row and derived field must match the golden exactly."""
        assert result == golden


class TestStatusFailureReporting:
    """Pin the deliberate behaviour change: when reads fail, ok must be false."""

    def test_failed_read_sets_ok_false(self):
        transport = ReplayTransport(fail_commands={"fax show stats"})
        buf = io.StringIO()
        rc = main(["--json", "status"], transport=transport, stdout=buf)
        assert rc == 0
        obj = json.loads(buf.getvalue())
        assert obj["ok"] is False

    def test_failed_read_includes_why(self):
        transport = ReplayTransport(fail_commands={"fax show stats"})
        buf = io.StringIO()
        main(["--json", "status"], transport=transport, stdout=buf)
        obj = json.loads(buf.getvalue())
        assert "why" in obj
        assert "fax show stats" in obj["why"]

    def test_failed_read_includes_unread_list(self):
        transport = ReplayTransport(fail_commands={"fax show stats"})
        buf = io.StringIO()
        main(["--json", "status"], transport=transport, stdout=buf)
        obj = json.loads(buf.getvalue())
        assert "unread" in obj
        assert "fax show stats" in obj["unread"]

    def test_multiple_failures_listed(self):
        transport = ReplayTransport(fail_commands={"fax show stats", "pjsip show registrations"})
        buf = io.StringIO()
        main(["--json", "status"], transport=transport, stdout=buf)
        obj = json.loads(buf.getvalue())
        assert obj["ok"] is False
        assert len(obj["unread"]) >= 2

    def test_all_reads_succeed_keeps_ok_true(self):
        transport = ReplayTransport()
        buf = io.StringIO()
        main(["--json", "status"], transport=transport, stdout=buf)
        obj = json.loads(buf.getvalue())
        assert obj["ok"] is True
        assert "why" not in obj
        assert "unread" not in obj
