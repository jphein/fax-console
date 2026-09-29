"""The static replay demo for GitHub Pages: faxconsole/export.py.

The demo is public the moment Pages builds it, so these tests hold three things:
- every GET route is in it;
- the page runs static, reading relative JSON, with sending off;
- nothing derived from the machine is in it.
(scripts/untar-site.py, which extracts it on the host, has tests/test_untar_site.py.)
"""
import inspect
import io
import json
import re
import socket
import tarfile
import time
from pathlib import Path

import pytest

from faxconsole import export as ex
from faxconsole import routes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def site():
    return ex.export("tests/fixtures")


def test_every_get_route_of_the_dispatcher_is_exported():
    get_block = inspect.getsource(routes.handle).split('if method == "POST"')[0]
    served = set(re.findall(r'route == "(/api/[^"]+)"', get_block))
    assert served and served == set(ex.GET_API_ROUTES), served ^ set(ex.GET_API_ROUTES)


def test_the_site_holds_every_file(site):
    want = {ex.api_file(r) for r in ex.GET_API_ROUTES} | {"index.html", ".nojekyll", *ex.PAGE_ASSETS}
    assert set(site) == want


def test_each_api_file_is_the_routes_json_and_shows_no_failure(site):
    """The fixtures are complete, so no view of the public demo may show a failed read."""
    for route in ex.GET_API_ROUTES:
        obj = json.loads(site[ex.api_file(route)])
        assert isinstance(obj, dict) and obj, route
        assert obj.get("ok", True) is True and not obj.get("why") and not obj.get("error"), (route, obj)


def test_the_page_is_static_and_keeps_its_csp(site):
    html = site["index.html"].decode()
    assert '<html lang="en" data-static="1" data-recorded="2026-09-28 22:25 PDT">' in html   # capture.json
    assert "a send is a dry run" not in html and "this static copy cannot send" in html
    assert "<h2>Recorded state</h2>" in html and "<h2>Live state</h2>" not in html
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', html)
    assert m and "script-src 'self'" in m.group(1) and "frame-ancestors" not in m.group(1)
    assert 'href="/' not in html and 'src="/' not in html          # Pages serves it under /fax-console/


def test_app_js_reads_every_get_through_api():
    js = (ROOT / "faxconsole" / "static" / "app.js").read_text()
    assert re.findall(r'fetch\("/api/[^"]*"', js) == ['fetch("/api/fax/send"'], "a GET fetch skips api()"
    assert 'const api = p => STATIC ? "api" + p.slice(4) + ".json" : p;' in js
    assert 'document.getElementById("faxsend").disabled=true' in js
    # What the static page actually renders is tested by running app.js: tests/test_static_page_render.py


# realm-sigil's README: "Static sites omit server-only fields". Spelled out here, not taken from the
# code under test, so emptying the export's own list is caught.
SIGIL_SERVER_ONLY = {"started", "uptime", "runtime", "os", "host", "pid"}


def test_the_version_is_the_static_sigil(site):
    v = json.loads(site["api/version.json"])
    assert v["replay"] is True and v["name"]
    assert not SIGIL_SERVER_ONLY & set(v), SIGIL_SERVER_ONLY & set(v)


def test_the_capture_label_is_derived_from_captured_at():
    # one source of truth: capture.json's captured_at and zone give the README's 2026-09-28 22:25 PDT
    assert ex.capture("tests/fixtures")[1] == "2026-09-28 22:25 PDT"


def test_two_exports_are_byte_identical(site):
    """The export is dated by the fixtures' capture time, never by its own clock. So a re-export of the
    published commit reproduces the live site byte for byte, and Lucid's check can compare them."""
    time.sleep(1.1)                                               # a clock read anywhere would now differ
    again = ex.export("tests/fixtures")
    one, two = io.BytesIO(), io.BytesIO()
    ex.write_tar(site, one)
    ex.write_tar(again, two)
    assert one.getvalue() == two.getvalue(), sorted(n for n in site if site[n] != again.get(n))


def test_the_synthesized_voipms_json_carries_no_time(site):
    """tests/fixtures/voipms is synthesized, never captured: no fetch time, nothing computed from a clock."""
    v = json.loads(site["api/voipms.json"])
    unmeasured = {"age", "stale", "days_to_billing", "polling", "fetched_at"}     # not the code's list
    assert not unmeasured & set(v), unmeasured & set(v)


def test_nothing_from_the_machine(site):
    host = socket.gethostname()
    for name, data in site.items():
        text = data.decode("utf-8", "replace")
        for bad in ("/tmp/", "/home/", str(ROOT), host):
            assert bad not in text, (name, bad)


def test_the_tar_stream_is_regular_files_with_fixed_metadata(site):
    one, two = io.BytesIO(), io.BytesIO()
    ex.write_tar(site, one)
    ex.write_tar(site, two)
    assert one.getvalue() == two.getvalue()                           # the same export, the same bytes
    one.seek(0)
    with tarfile.open(fileobj=one) as tar:
        members = tar.getmembers()
    assert [m.name for m in members] == sorted(site)
    assert all(m.isreg() and m.mode == 0o644 and m.mtime == 0 for m in members)
