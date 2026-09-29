"""tests/test_faxconsole_routes.py — route-level tests through handle().

Every route is exercised against a ReplayTransport backed by the existing
fixtures.  No TCP port is opened.  The send tests are in
test_faxconsole_send.py; this file focuses on read routes and the 404.
"""
from __future__ import annotations

import json
from pathlib import Path

from faxcli.transport import ReplayTransport
from faxconsole.routes import Config, Response, handle

FIXTURE_DIR = Path("tests/fixtures")


def _transport(**kwargs) -> ReplayTransport:
    return ReplayTransport(
        fixture_dir=FIXTURE_DIR / "asterisk",
        cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
        **kwargs,
    )


def _config(**kwargs) -> Config:
    defaults = {"transport": _transport(), "inbox": "/tmp/faxconsole-inbox-test",
                "spool": "/var/spool/asterisk/fax"}
    defaults.update(kwargs)
    return Config(**defaults)


def _get(path: str, config: Config | None = None) -> Response:
    return handle("GET", path, {}, b"", config or _config())


# ---------------------------------------------------------------------------
# GET /api/fax/status
# ---------------------------------------------------------------------------

class TestStatusRoute:
    def test_status_code_200(self):
        r = _get("/api/fax/status")
        assert r.status == 200

    def test_content_type_json(self):
        r = _get("/api/fax/status")
        assert r.content_type == "application/json"

    def test_body_is_valid_json(self):
        r = _get("/api/fax/status")
        obj = json.loads(r.body)
        assert isinstance(obj, dict)

    def test_has_required_fields(self):
        obj = json.loads(_get("/api/fax/status").body)
        for field in ("ok", "spandsp", "trunk_registered", "trunk_available",
                      "obi100_registered", "active_sessions", "stats", "gs"):
            assert field in obj, f"missing field: {field}"

    def test_ok_true_with_good_fixtures(self):
        obj = json.loads(_get("/api/fax/status").body)
        assert obj["ok"] is True

    def test_stats_is_dict(self):
        obj = json.loads(_get("/api/fax/status").body)
        assert isinstance(obj["stats"], dict)

    def test_active_sessions_is_list(self):
        obj = json.loads(_get("/api/fax/status").body)
        assert isinstance(obj["active_sessions"], list)

    def test_matches_golden(self):
        golden = json.loads((FIXTURE_DIR / "golden" / "status.json").read_text())
        obj = json.loads(_get("/api/fax/status").body)
        # Every field in the golden must be present and equal
        for k, v in golden.items():
            assert obj[k] == v, f"field {k!r}: got {obj[k]!r}, want {v!r}"

    def test_ok_false_when_asterisk_fails(self):
        """When all asterisk readings fail, ok must be False."""
        failing_transport = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
            fail_commands={
                "fax show stats", "fax show sessions",
                "pjsip show endpoint voipms-fax", "pjsip show registrations",
                "pjsip show endpoint 2007", "module show like res_fax",
            },
        )
        cfg = _config(transport=failing_transport)
        obj = json.loads(_get("/api/fax/status", cfg).body)
        assert obj["ok"] is False


# ---------------------------------------------------------------------------
# GET /api/fax/log
# ---------------------------------------------------------------------------

class TestLogRoute:
    def test_status_code_200(self):
        r = _get("/api/fax/log")
        assert r.status == 200

    def test_body_has_ok_and_rows(self):
        obj = json.loads(_get("/api/fax/log").body)
        assert "ok" in obj
        assert "rows" in obj
        assert isinstance(obj["rows"], list)

    def test_default_limit(self):
        obj = json.loads(_get("/api/fax/log").body)
        assert len(obj["rows"]) <= 20

    def test_custom_limit(self):
        obj = json.loads(_get("/api/fax/log?limit=3").body)
        assert len(obj["rows"]) <= 3

    def test_matches_golden(self):
        golden = json.loads((FIXTURE_DIR / "golden" / "log.json").read_text())
        obj = json.loads(_get("/api/fax/log?limit=25").body)
        assert obj["ok"] == golden["ok"]
        # Row count and first row's key fields
        assert len(obj["rows"]) == len(golden["rows"])
        for i, (g_row, a_row) in enumerate(zip(golden["rows"], obj["rows"], strict=True)):
            for key in ("number", "direction", "disposition", "file"):
                assert a_row[key] == g_row[key], f"row {i} field {key!r}"

    def test_row_has_required_fields(self):
        obj = json.loads(_get("/api/fax/log").body)
        if obj["rows"]:
            row = obj["rows"][0]
            for field in ("start_local", "direction", "number", "disposition", "billsec", "file"):
                assert field in row, f"missing field: {field}"

    def test_ok_false_when_cdr_fails(self):
        failing_t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
            fail_cdr=True,
        )
        cfg = _config(transport=failing_t)
        obj = json.loads(_get("/api/fax/log", cfg).body)
        assert obj["ok"] is False


# ---------------------------------------------------------------------------
# GET /api/fax (legacy combined shape)
# ---------------------------------------------------------------------------

class TestFaxStateRoute:
    def test_status_code_200(self):
        r = _get("/api/fax")
        assert r.status == 200

    def test_has_all_legacy_fields(self):
        obj = json.loads(_get("/api/fax").body)
        for field in ("ok", "status", "log", "why", "src", "spool", "inbox"):
            assert field in obj, f"missing field: {field}"

    def test_status_is_dict(self):
        obj = json.loads(_get("/api/fax").body)
        assert isinstance(obj["status"], dict)

    def test_log_is_list(self):
        obj = json.loads(_get("/api/fax").body)
        assert isinstance(obj["log"], list)

    def test_spool_and_inbox_are_strings(self):
        obj = json.loads(_get("/api/fax").body)
        assert isinstance(obj["spool"], str)
        assert isinstance(obj["inbox"], str)

    def test_inbox_matches_config(self):
        cfg = _config(inbox="/tmp/custom-inbox")
        obj = json.loads(_get("/api/fax", cfg).body)
        assert obj["inbox"] == "/tmp/custom-inbox"

    def test_ok_is_bool(self):
        obj = json.loads(_get("/api/fax").body)
        assert isinstance(obj["ok"], bool)

    def test_log_limit_is_25(self):
        """Legacy fax_state uses log --limit 25 (e:2032)."""
        obj = json.loads(_get("/api/fax").body)
        assert len(obj["log"]) <= 25


# ---------------------------------------------------------------------------
# GET /api/pbx/trunk
# ---------------------------------------------------------------------------

class TestPbxTrunkRoute:
    def test_status_200(self):
        assert _get("/api/pbx/trunk").status == 200

    def test_has_ok_and_src(self):
        obj = json.loads(_get("/api/pbx/trunk").body)
        assert "ok" in obj
        assert "src" in obj

    def test_ok_true_with_fixture(self):
        obj = json.loads(_get("/api/pbx/trunk").body)
        assert obj["ok"] is True

    def test_has_status_field(self):
        obj = json.loads(_get("/api/pbx/trunk").body)
        assert "status" in obj

    def test_ok_false_when_asterisk_fails(self):
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
            fail_commands={"pjsip show registrations"},
        )
        cfg = _config(transport=t)
        obj = json.loads(_get("/api/pbx/trunk", cfg).body)
        assert obj["ok"] is False


# ---------------------------------------------------------------------------
# GET /api/pbx/calls
# ---------------------------------------------------------------------------

class TestPbxCallsRoute:
    def test_status_200(self):
        assert _get("/api/pbx/calls").status == 200

    def test_has_instruments(self):
        obj = json.loads(_get("/api/pbx/calls").body)
        assert "instruments" in obj
        assert isinstance(obj["instruments"], list)

    def test_has_value_and_cellular(self):
        obj = json.loads(_get("/api/pbx/calls").body)
        assert "value" in obj
        assert "cellular" in obj

    def test_has_impossible_flag(self):
        obj = json.loads(_get("/api/pbx/calls").body)
        assert "impossible" in obj

    def test_impossible_false_with_fixture(self):
        obj = json.loads(_get("/api/pbx/calls").body)
        assert obj["impossible"] is False

    def test_asterisk_instrument_present(self):
        obj = json.loads(_get("/api/pbx/calls").body)
        names = [i["name"] for i in obj["instruments"]]
        assert "Asterisk channels" in names

    def test_msc_not_probed_without_vty(self):
        """Without vty_fn the MSC instrument is ok=False, why='not probed'."""
        obj = json.loads(_get("/api/pbx/calls").body)
        msc = next(i for i in obj["instruments"] if i["name"] == "MSC connections")
        assert msc["ok"] is False
        assert "not probed" in msc["why"]


# ---------------------------------------------------------------------------
# GET /api/pbx/endpoints
# ---------------------------------------------------------------------------

class TestPbxEndpointsRoute:
    def test_status_200(self):
        assert _get("/api/pbx/endpoints").status == 200

    def test_has_ok_src_rows_infra(self):
        obj = json.loads(_get("/api/pbx/endpoints").body)
        for field in ("ok", "src", "rows", "infra"):
            assert field in obj, f"missing field: {field}"

    def test_rows_are_numeric_only(self):
        obj = json.loads(_get("/api/pbx/endpoints").body)
        for row in obj["rows"]:
            assert row["ext"].isdigit(), f"non-numeric ext in rows: {row['ext']!r}"

    def test_infra_are_non_numeric(self):
        obj = json.loads(_get("/api/pbx/endpoints").body)
        for row in obj["infra"]:
            assert not row["ext"].isdigit(), f"numeric ext in infra: {row['ext']!r}"

    def test_ok_false_when_asterisk_fails(self):
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            cdr_path=FIXTURE_DIR / "cdr" / "Master.csv",
            fail_commands={"pjsip show endpoints"},
        )
        cfg = _config(transport=t)
        obj = json.loads(_get("/api/pbx/endpoints", cfg).body)
        assert obj["ok"] is False


# ---------------------------------------------------------------------------
# GET /api/version
# ---------------------------------------------------------------------------

class TestVersionRoute:
    def test_status_200(self):
        assert _get("/api/version").status == 200

    def test_has_all_contract_fields(self):
        obj = json.loads(_get("/api/version").body)
        for field in ("name", "description", "version", "hash", "branch",
                      "dirty", "built", "realm", "repo", "commit_url",
                      "started", "uptime", "runtime", "os", "host", "pid"):
            assert field in obj, f"missing field: {field}"

    def test_name_is_fax_realm_watch(self):
        obj = json.loads(_get("/api/version").body)
        assert obj["name"] == "fax.realm.watch"

    def test_version_contains_hash(self):
        obj = json.loads(_get("/api/version").body)
        assert obj["hash"] in obj["version"]

    def test_uptime_is_non_negative_int(self):
        obj = json.loads(_get("/api/version").body)
        assert isinstance(obj["uptime"], int)
        assert obj["uptime"] >= 0

    def test_generate_name_contract(self):
        from faxconsole.version import generate_name
        # The hash '0000001' should deterministically produce the same name
        # regardless of which side of the implementation we call.
        name = generate_name("0000001")
        assert " · 0000001" in name


# ---------------------------------------------------------------------------
# 404 — unknown paths and HTML escaping
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_unknown_get_returns_404(self):
        r = _get("/api/unknown/path")
        assert r.status == 404

    def test_body_is_json(self):
        r = _get("/no-such-route")
        obj = json.loads(r.body)
        assert "ok" in obj
        assert obj["ok"] is False

    def test_path_is_escaped_in_body(self):
        r = _get("/path/<script>alert(1)</script>")
        body_text = r.body.decode()
        assert "<script>" not in body_text
        assert "&lt;script&gt;" in body_text

    def test_ampersand_escaped(self):
        r = _get("/x&y")
        body_text = r.body.decode()
        assert "&amp;" in body_text

    def test_quote_escaped(self):
        r = _get('/x"y')
        body_text = r.body.decode()
        assert "&quot;" in body_text

    def test_post_unknown_returns_404(self):
        r = handle("POST", "/unknown", {}, b"", _config())
        assert r.status == 404
