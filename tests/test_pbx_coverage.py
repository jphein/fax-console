"""tests/test_pbx_coverage.py — edge-path coverage for faxconsole.pbx.

Targets lines untouched by the existing suite:
  - read_trunk: no registration row in the output (line 50 — the ok=True / status=None branch)
  - read_calls with vty_fn provided: successful probe with blocks (lines 85-111),
    vty_fn raises (lines 113-117), and cellular > Asterisk (impossible=True, line 130-134)
"""
from __future__ import annotations

from pathlib import Path

from faxcli.transport import ReplayTransport
from faxconsole.pbx import read_calls, read_trunk

# ---------------------------------------------------------------------------
# read_trunk — no registration row in the output
# ---------------------------------------------------------------------------

class TestReadTrunkNoRow:
    def test_empty_output_returns_ok_true_status_none(self, tmp_path):
        """An empty asterisk output must return ok=True with status=None."""
        ast_dir = tmp_path / "asterisk"
        ast_dir.mkdir()
        (ast_dir / "pjsip_show_registrations.txt").write_text(
            "No registrations at all\n"
        )
        t = ReplayTransport(fixture_dir=ast_dir)
        result = read_trunk(t)
        assert result["ok"] is True
        assert result["status"] is None
        assert "why" in result  # "no registration row in output"

    def test_blank_output_also_ok_true_status_none(self, tmp_path):
        """A fixture with only whitespace must also return ok=True / status=None."""
        ast_dir = tmp_path / "asterisk"
        ast_dir.mkdir()
        (ast_dir / "pjsip_show_registrations.txt").write_text("   \n")
        t = ReplayTransport(fixture_dir=ast_dir)
        result = read_trunk(t)
        assert result["ok"] is True
        assert result["status"] is None


# ---------------------------------------------------------------------------
# Minimal "show connection" VTY output — no subscriber identifiers
# ---------------------------------------------------------------------------

# Two blocks: one with cc (call-control) tag, one signalling only.
# MSISDN values are in the fictional 555-0100..0199 range.
_VTY_TWO_BLOCKS = (
    "Connection #0: Serving host-A\n"
    " MSISDN-2025550111\n"
    " RAN connection state: CONNECTED\n"
    " Use count: 1 (cc)\n"
    "Connection #1: Serving host-B\n"
    " MSISDN-2025550122\n"
    " RAN connection state: CONNECTED\n"
    " Use count: 1 (signalling)\n"
)

# Three blocks: two carrying call-control, one signalling only.
_VTY_THREE_BLOCKS = (
    "Connection #0: Serving host-A\n"
    " MSISDN-2025550111\n"
    " RAN connection state: CONNECTED\n"
    " Use count: 1 (cc)\n"
    "Connection #1: Serving host-B\n"
    " MSISDN-2025550122\n"
    " RAN connection state: CONNECTED\n"
    " Use count: 1 (cc)\n"
    "Connection #2: Serving host-C\n"
    " MSISDN-2025550133\n"
    " RAN connection state: CONNECTED\n"
    " Use count: 1 (signalling)\n"
)

_VTY_NO_CONNECTIONS = "\n"


def _make_transport(tmp_path: Path, active_calls: int = 0) -> ReplayTransport:
    """ReplayTransport backed by a minimal fixture directory."""
    ast_dir = tmp_path / "asterisk"
    ast_dir.mkdir(parents=True, exist_ok=True)
    (ast_dir / "core_show_channels.txt").write_text(
        f"{active_calls} active calls\n"
        "0 calls processed\n"
    )
    return ReplayTransport(fixture_dir=ast_dir)


# ---------------------------------------------------------------------------
# read_calls — vty_fn provided, successful probe with connections
# ---------------------------------------------------------------------------

class TestReadCallsVtyFn:
    def test_vty_fn_with_connections_adds_msc_instrument(self, tmp_path):
        """When vty_fn returns connection blocks, MSC instrument must be ok=True."""
        t = _make_transport(tmp_path)
        result = read_calls(t, vty_fn=lambda _msc, _cmd: _VTY_TWO_BLOCKS)

        msc = next(i for i in result["instruments"] if i["name"] == "MSC connections")
        assert msc["ok"] is True
        assert msc["value"] == 2

    def test_vty_fn_with_connections_populates_subscribers(self, tmp_path):
        """Subscriber dict must be populated from the MSISDN rows."""
        t = _make_transport(tmp_path)
        result = read_calls(t, vty_fn=lambda _msc, _cmd: _VTY_TWO_BLOCKS)

        subs = result["subscribers"]
        assert "2025550111" in subs
        assert "2025550122" in subs

    def test_vty_fn_with_connections_in_call_flag(self, tmp_path):
        """The subscriber with the 'cc' tag must have in_call=True."""
        t = _make_transport(tmp_path)
        result = read_calls(t, vty_fn=lambda _msc, _cmd: _VTY_TWO_BLOCKS)

        subs = result["subscribers"]
        assert subs["2025550111"]["in_call"] is True
        assert subs["2025550122"]["in_call"] is False

    def test_vty_fn_with_connections_sets_note(self, tmp_path):
        """When there are connections, the MSC instrument must have a note."""
        t = _make_transport(tmp_path)
        result = read_calls(t, vty_fn=lambda _msc, _cmd: _VTY_TWO_BLOCKS)

        msc = next(i for i in result["instruments"] if i["name"] == "MSC connections")
        assert "note" in msc
        assert "call-control" in msc["note"]

    def test_vty_fn_no_connections(self, tmp_path):
        """When vty_fn returns no blocks, value must be 0 and no note."""
        t = _make_transport(tmp_path)
        result = read_calls(t, vty_fn=lambda _msc, _cmd: _VTY_NO_CONNECTIONS)

        msc = next(i for i in result["instruments"] if i["name"] == "MSC connections")
        assert msc["ok"] is True
        assert msc["value"] == 0
        assert "note" not in msc

    def test_vty_fn_raises_is_ok_false(self, tmp_path):
        """When vty_fn raises, the MSC instrument must be ok=False."""
        t = _make_transport(tmp_path)
        result = read_calls(
            t,
            vty_fn=lambda _msc, _cmd: (_ for _ in ()).throw(RuntimeError("vty down")),
        )

        msc = next(i for i in result["instruments"] if i["name"] == "MSC connections")
        assert msc["ok"] is False
        assert "vty down" in msc["why"]

    def test_impossible_flag_when_cellular_exceeds_asterisk(self, tmp_path):
        """impossible=True when cellular connections > Asterisk active calls."""
        # Asterisk shows 0 active calls, VTY shows 2 connections → impossible
        t = _make_transport(tmp_path, active_calls=0)
        result = read_calls(t, vty_fn=lambda _msc, _cmd: _VTY_TWO_BLOCKS)

        assert result["value"] == 0
        assert result["cellular"] == 2
        assert result["impossible"] is True

    def test_impossible_false_when_cellular_does_not_exceed(self, tmp_path):
        """impossible=False when Asterisk >= cellular (normal situation)."""
        # Asterisk shows 5 active calls, VTY shows 2 connections
        t = _make_transport(tmp_path, active_calls=5)
        result = read_calls(t, vty_fn=lambda _msc, _cmd: _VTY_TWO_BLOCKS)

        assert result["value"] == 5
        assert result["cellular"] == 2
        assert result["impossible"] is False

    def test_note_counts_in_call_subscribers_exactly(self, tmp_path):
        """Note must report exactly the count of subscribers with in_call=True.

        Three subscribers, two carrying call-control (cc tag), one signalling only.
        The exact note text is checked so that inverting the in_call condition
        (``if not v["in_call"]``) produces ncc=1 instead of 2 and the test fails.
        """
        t = _make_transport(tmp_path, active_calls=5)
        result = read_calls(t, vty_fn=lambda _msc, _cmd: _VTY_THREE_BLOCKS)

        msc = next(i for i in result["instruments"] if i["name"] == "MSC connections")
        assert msc["ok"] is True
        assert msc["value"] == 3
        assert msc["note"] == (
            "2 of 3 carrying call-control; the "
            "rest are signalling only (location update, SMS)"
        )
