"""tests/test_faxconsole_pbx.py — characterization tests for faxconsole.pbx.

Each test feeds the same fixture text to both the frozen legacy functions
(imported read-only via importlib) and our new implementations, then
asserts field-for-field agreement.

The legacy module calls ``subprocess.run`` at import time via ``_build_info``
(e:419–431) and instantiates ``VoipMsPoller`` (e:1006).  We install a
refusing fake ``subprocess.run`` BEFORE the import so the conftest guard
cannot fire mid-import.
"""
from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from faxcli.transport import ReplayTransport
from faxconsole.pbx import read_calls, read_sip_endpoints, read_trunk

FIXTURE_DIR = Path("tests/fixtures")
LEGACY_PATH = Path("legacy/console/telephony-console.py")


# ---------------------------------------------------------------------------
# Import the legacy module with a fake subprocess.run and a stub for ast()
# ---------------------------------------------------------------------------

def _load_legacy_module():
    """Import the legacy console once, with subprocess.run stubbed out."""
    mod_name = "_legacy_console_pbx_test"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    # Fake subprocess.run that succeeds silently (for _build_info's git calls)
    fake_result = MagicMock()
    fake_result.stdout = ""
    fake_result.returncode = 1  # not 0 so build falls back to "dev"

    original_run = subprocess.run

    def _fake_run(*args, **kwargs):
        return fake_result

    subprocess.run = _fake_run
    try:
        spec = importlib.util.spec_from_file_location(mod_name, str(LEGACY_PATH))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    finally:
        subprocess.run = original_run

    return mod


# We import lazily in each test so the module is loaded once.
_LEGACY = None


def _legacy():
    global _LEGACY
    if _LEGACY is None:
        _LEGACY = _load_legacy_module()
    return _LEGACY


def _make_ast(text_map: dict[str, str | None]):
    """Return a fake ast() that returns from text_map (None means failure)."""
    def _ast(cmd, timeout=10):
        return text_map.get(cmd)
    return _ast


# ---------------------------------------------------------------------------
# read_trunk characterization
# ---------------------------------------------------------------------------

class TestReadTrunkCharacterization:
    def _fixture_text(self) -> str:
        return (FIXTURE_DIR / "asterisk" / "pjsip_show_registrations.txt").read_text()

    def _run_legacy(self, text: str | None):
        leg = _legacy()
        old_ast = leg.ast
        leg.ast = _make_ast({"pjsip show registrations": text})
        try:
            return leg.read_trunk()
        finally:
            leg.ast = old_ast

    def _run_new(self, text: str | None):
        if text is None:
            t = ReplayTransport(
                fixture_dir=FIXTURE_DIR / "asterisk",
                fail_commands={"pjsip show registrations"},
            )
        else:
            t = ReplayTransport(fixture_dir=FIXTURE_DIR / "asterisk")
        return read_trunk(t)

    def test_ok_field_agrees(self):
        txt = self._fixture_text()
        assert self._run_legacy(txt)["ok"] == self._run_new(txt)["ok"]

    def test_status_field_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert leg.get("status") == new.get("status")

    def test_name_field_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert leg.get("name") == new.get("name")

    def test_expires_field_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert leg.get("expires") == new.get("expires")

    def test_raw_field_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert leg.get("raw") == new.get("raw")

    def test_failure_ok_false_agrees(self):
        """Both return ok=False when ast returns None."""
        leg = self._run_legacy(None)
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            fail_commands={"pjsip show registrations"},
        )
        new = read_trunk(t)
        assert leg["ok"] is False
        assert new["ok"] is False

    def test_src_field_present(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert "src" in leg
        assert "src" in new


# ---------------------------------------------------------------------------
# read_calls characterization
# ---------------------------------------------------------------------------

class TestReadCallsCharacterization:
    def _fixture_text(self) -> str:
        return (FIXTURE_DIR / "asterisk" / "core_show_channels.txt").read_text()

    def _run_legacy(self, text: str | None):
        leg = _legacy()
        old_ast = leg.ast
        # Stub vty to raise (simulates "not probed")
        old_vty = getattr(leg, "vty", None)
        leg.ast = _make_ast({"core show channels": text})
        # vty raises so the cellular block uses except branch
        leg.vty = MagicMock(side_effect=RuntimeError("not probed"))
        try:
            return leg.read_calls()
        finally:
            leg.ast = old_ast
            if old_vty is not None:
                leg.vty = old_vty
            else:
                del leg.vty

    def _run_new(self, text: str | None):
        if text is None:
            t = ReplayTransport(
                fixture_dir=FIXTURE_DIR / "asterisk",
                fail_commands={"core show channels"},
            )
        else:
            t = ReplayTransport(fixture_dir=FIXTURE_DIR / "asterisk")
        return read_calls(t)  # vty_fn=None → not probed

    def test_instruments_list_length_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert len(leg["instruments"]) == len(new["instruments"])

    def test_value_field_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert leg["value"] == new["value"]

    def test_impossible_field_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert leg["impossible"] == new["impossible"]

    def test_asterisk_instrument_ok_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        leg_ast = next(i for i in leg["instruments"] if i["name"] == "Asterisk channels")
        new_ast = next(i for i in new["instruments"] if i["name"] == "Asterisk channels")
        assert leg_ast["ok"] == new_ast["ok"]

    def test_asterisk_instrument_value_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        leg_ast = next(i for i in leg["instruments"] if i["name"] == "Asterisk channels")
        new_ast = next(i for i in new["instruments"] if i["name"] == "Asterisk channels")
        assert leg_ast.get("value") == new_ast.get("value")

    def test_failure_agrees(self):
        """Both report Asterisk instrument ok=False when ast returns None."""
        leg = self._run_legacy(None)
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            fail_commands={"core show channels"},
        )
        new = read_calls(t)
        leg_ast = next(i for i in leg["instruments"] if i["name"] == "Asterisk channels")
        new_ast = next(i for i in new["instruments"] if i["name"] == "Asterisk channels")
        assert leg_ast["ok"] is False
        assert new_ast["ok"] is False


# ---------------------------------------------------------------------------
# read_sip_endpoints characterization
# ---------------------------------------------------------------------------

class TestReadSipEndpointsCharacterization:
    def _fixture_text(self) -> str:
        return (FIXTURE_DIR / "asterisk" / "pjsip_show_endpoints.txt").read_text()

    def _run_legacy(self, text: str | None):
        leg = _legacy()
        old_ast = leg.ast
        leg.ast = _make_ast({"pjsip show endpoints": text})
        try:
            return leg.read_sip_endpoints()
        finally:
            leg.ast = old_ast

    def _run_new(self, text: str | None):
        if text is None:
            t = ReplayTransport(
                fixture_dir=FIXTURE_DIR / "asterisk",
                fail_commands={"pjsip show endpoints"},
            )
        else:
            t = ReplayTransport(fixture_dir=FIXTURE_DIR / "asterisk")
        return read_sip_endpoints(t)

    def test_ok_field_agrees(self):
        txt = self._fixture_text()
        assert self._run_legacy(txt)["ok"] == self._run_new(txt)["ok"]

    def test_rows_count_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert len(leg["rows"]) == len(new["rows"])

    def test_infra_count_agrees(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        assert len(leg["infra"]) == len(new["infra"])

    def test_row_extensions_agree(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        leg_exts = sorted(r["ext"] for r in leg["rows"])
        new_exts = sorted(r["ext"] for r in new["rows"])
        assert leg_exts == new_exts

    def test_infra_names_agree(self):
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        leg_names = sorted(r["ext"] for r in leg["infra"])
        new_names = sorted(r["ext"] for r in new["infra"])
        assert leg_names == new_names

    def test_contact_status_agrees(self):
        """For endpoints with a Contact line, the status values must agree."""
        txt = self._fixture_text()
        leg = self._run_legacy(txt)
        new = self._run_new(txt)
        leg_contacts = {r["ext"]: r.get("contact") for r in leg["rows"]}
        new_contacts = {r["ext"]: r.get("contact") for r in new["rows"]}
        for ext in leg_contacts:
            lc = leg_contacts[ext]
            nc = new_contacts.get(ext)
            if lc is not None:
                assert nc is not None, f"ext {ext}: new has no contact"
                assert lc["status"] == nc["status"], f"ext {ext}: status differs"

    def test_failure_agrees(self):
        leg = self._run_legacy(None)
        t = ReplayTransport(
            fixture_dir=FIXTURE_DIR / "asterisk",
            fail_commands={"pjsip show endpoints"},
        )
        new = read_sip_endpoints(t)
        assert leg["ok"] is False
        assert new["ok"] is False
