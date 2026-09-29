"""tests/test_faxconsole_page.py — tests for the faxconsole static page and routes.

All tests go through handle() directly — no TCP sockets, no real network.
"""
from __future__ import annotations

import json
import re

import pytest

from faxconsole.__main__ import build
from faxconsole.routes import handle

# ---------------------------------------------------------------------------
# Shared fixture: a replay config (wires everything without touching a network)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def replay_config():
    """Build a replay Config and clean up afterwards."""
    config, cleanup, _args = build(["--replay", "tests/fixtures"])
    try:
        yield config
    finally:
        cleanup()


def _get(path, config):
    """Call handle() for a GET request and return the Response."""
    return handle("GET", path, {}, b"", config)


# ---------------------------------------------------------------------------
# 1. Static route: GET /
# ---------------------------------------------------------------------------

def test_root_status(replay_config):
    r = _get("/", replay_config)
    assert r.status == 200


def test_root_content_type(replay_config):
    r = _get("/", replay_config)
    assert r.content_type.startswith("text/html")


def test_root_csp(replay_config):
    r = _get("/", replay_config)
    assert r.extra_headers is not None
    csp = r.extra_headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp


def test_root_xcto(replay_config):
    r = _get("/", replay_config)
    assert r.extra_headers is not None
    assert r.extra_headers.get("X-Content-Type-Options") == "nosniff"


# ---------------------------------------------------------------------------
# 2. Static route: GET /app.css
# ---------------------------------------------------------------------------

def test_css_status(replay_config):
    r = _get("/app.css", replay_config)
    assert r.status == 200


def test_css_content_type(replay_config):
    r = _get("/app.css", replay_config)
    assert r.content_type.startswith("text/css")


def test_css_csp(replay_config):
    r = _get("/app.css", replay_config)
    assert r.extra_headers is not None
    assert "default-src 'self'" in r.extra_headers.get("Content-Security-Policy", "")


# ---------------------------------------------------------------------------
# 3. Static route: GET /app.js
# ---------------------------------------------------------------------------

def test_js_status(replay_config):
    r = _get("/app.js", replay_config)
    assert r.status == 200


def test_js_content_type(replay_config):
    r = _get("/app.js", replay_config)
    assert "javascript" in r.content_type


def test_js_csp(replay_config):
    r = _get("/app.js", replay_config)
    assert r.extra_headers is not None
    assert "default-src 'self'" in r.extra_headers.get("Content-Security-Policy", "")


# ---------------------------------------------------------------------------
# 4. Static route: GET /favicon.svg
# ---------------------------------------------------------------------------

def test_favicon_status(replay_config):
    r = _get("/favicon.svg", replay_config)
    assert r.status == 200


def test_favicon_content_type(replay_config):
    r = _get("/favicon.svg", replay_config)
    assert r.content_type == "image/svg+xml"


def test_favicon_is_valid_svg(replay_config):
    r = _get("/favicon.svg", replay_config)
    body = r.body.decode("utf-8", "replace")
    assert "<svg" in body
    assert "xmlns" in body
    assert "</svg>" in body


# ---------------------------------------------------------------------------
# 5. Legacy element ids in HTML
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def html_body(replay_config):
    return _get("/", replay_config).body.decode("utf-8", "replace")


def test_html_id_live(html_body):
    assert 'id="live"' in html_body


def test_html_id_voipms(html_body):
    assert 'id="voipms"' in html_body


def test_html_id_fax(html_body):
    assert 'id="fax"' in html_body


def test_html_id_faxform(html_body):
    assert 'id="faxform"' in html_body


def test_html_id_faxnum(html_body):
    assert 'id="faxnum"' in html_body


def test_html_id_faxlabel(html_body):
    assert 'id="faxlabel"' in html_body


def test_html_id_faxfile(html_body):
    assert 'id="faxfile"' in html_body


def test_html_id_faxconfirm(html_body):
    assert 'id="faxconfirm"' in html_body


def test_html_id_faxsend(html_body):
    assert 'id="faxsend"' in html_body


def test_html_id_faxmsg(html_body):
    assert 'id="faxmsg"' in html_body


def test_html_id_faxlog(html_body):
    assert 'id="faxlog"' in html_body


def test_html_id_foot(html_body):
    assert 'id="foot"' in html_body


def test_html_id_fresh(html_body):
    """freshness() writes to id=fresh; it must exist in the HTML."""
    assert 'id="fresh"' in html_body


# ---------------------------------------------------------------------------
# 6. Favicon link in HTML
# ---------------------------------------------------------------------------

def test_html_favicon_link(html_body):
    assert 'href="/favicon.svg"' in html_body
    assert 'type="image/svg+xml"' in html_body


# ---------------------------------------------------------------------------
# 7. Both colour schemes present in CSS
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def css_body(replay_config):
    return _get("/app.css", replay_config).body.decode("utf-8", "replace")


def test_css_has_light_theme(css_body):
    # Light theme: :root without a media query, defining --bg
    assert "--bg:#f4efe4" in css_body


def test_css_has_dark_theme_media(css_body):
    # Dark theme via @media (prefers-color-scheme:dark)
    assert "prefers-color-scheme:dark" in css_body


def test_css_has_dark_theme_vars(css_body):
    # Dark --bg must be distinct from light --bg
    assert "--bg:#101317" in css_body


# ---------------------------------------------------------------------------
# 8. No external URLs in any static file
# ---------------------------------------------------------------------------

_EXTERNAL_RE = re.compile(r"https?://")


def test_no_external_urls_in_html(html_body):
    assert not _EXTERNAL_RE.search(html_body), "index.html must not contain http(s):// URLs"


def test_no_external_urls_in_css(css_body):
    assert not _EXTERNAL_RE.search(css_body), "app.css must not contain http(s):// URLs"


def test_no_external_urls_in_js(replay_config):
    js = _get("/app.js", replay_config).body.decode("utf-8", "replace")
    assert not _EXTERNAL_RE.search(js), "app.js must not contain http(s):// URLs"


def test_no_external_urls_in_favicon(replay_config):
    svg = _get("/favicon.svg", replay_config).body.decode("utf-8", "replace")
    # xmlns="http://www.w3.org/2000/svg" is a required XML namespace declaration,
    # not a remote resource. Strip namespace-style attributes before checking.
    stripped = re.sub(r'xmlns(?::\w+)?="[^"]*"', "", svg)
    assert not _EXTERNAL_RE.search(stripped), "favicon.svg must not contain http(s):// resource URLs"


# ---------------------------------------------------------------------------
# 9. Every fetch("/api/…") path in app.js answers through handle() (non-404)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def js_api_routes(replay_config):
    """Extract every /api/… path from fetch() calls in app.js."""
    js = _get("/app.js", replay_config).body.decode("utf-8", "replace")
    return re.findall(r'fetch\("(/api/[^"]+)"', js)


def test_js_api_routes_found(js_api_routes):
    """We must find at least the four expected routes."""
    assert len(js_api_routes) >= 4


# Routes that are POST-only: a GET on them returns 404 by design.
_POST_ONLY = {"/api/fax/send"}


def test_js_api_routes_non_404(js_api_routes, replay_config):
    """Every GET /api/… path in app.js (that is not POST-only) must answer non-404."""
    for route in js_api_routes:
        path = route.split("?")[0]
        if path in _POST_ONLY:
            continue
        r = _get(path, replay_config)
        assert r.status != 404, f"Route {path!r} from app.js returned 404"


# ---------------------------------------------------------------------------
# 10. Replay-mode banner / field
# ---------------------------------------------------------------------------

def test_replay_banner_element_present(html_body):
    """The replay banner element must be present in the HTML (JS shows/hides it)."""
    assert 'id="replay-banner"' in html_body


def test_version_replay_field(replay_config):
    """GET /api/version in replay mode must include replay=True."""
    r = _get("/api/version", replay_config)
    assert r.status == 200
    d = json.loads(r.body)
    assert d.get("replay") is True


# ---------------------------------------------------------------------------
# 11. Unknown path still gets 404
# ---------------------------------------------------------------------------

def test_unknown_path_404(replay_config):
    r = _get("/this/does/not/exist", replay_config)
    assert r.status == 404


def test_unknown_path_404_csp(replay_config):
    r = _get("/this/does/not/exist", replay_config)
    assert r.extra_headers is not None
    assert "default-src 'self'" in r.extra_headers.get("Content-Security-Policy", "")


# ---------------------------------------------------------------------------
# 12. Password field present (write token)
# ---------------------------------------------------------------------------

def test_html_token_field(html_body):
    """A password field for the write token must be in the HTML."""
    assert 'type="password"' in html_body
    assert 'id="token"' in html_body


# ---------------------------------------------------------------------------
# 13. The public replay demo names no host (review of run 9)
# ---------------------------------------------------------------------------

def test_version_names_no_host_in_replay(replay_config, monkeypatch):
    """Replay mode is the public demo: /api/version must not publish the machine's name."""
    import socket
    monkeypatch.setattr(socket, "gethostname", lambda: "pbx7.example.net")   # a fictional stand-in
    body = _get("/api/version", replay_config).body.decode()
    assert "pbx7.example.net" not in body
    assert json.loads(body)["host"] == "replay"


def test_version_keeps_host_when_live(monkeypatch, tmp_path):
    """Live mode keeps the sigil contract's real host, for the LAN status page."""
    import socket
    from pathlib import Path

    from faxcli.transport import ReplayTransport
    from faxconsole.routes import Config
    monkeypatch.setattr(socket, "gethostname", lambda: "pbx7.example.net")
    fx = Path("tests/fixtures")
    cfg = Config(transport=ReplayTransport(fixture_dir=fx / "asterisk", cdr_path=fx / "cdr" / "Master.csv",
                                           spool_dir=str(tmp_path)), inbox=str(tmp_path / "inbox"))
    assert json.loads(_get("/api/version", cfg).body)["host"] == "pbx7.example.net"


# ---------------------------------------------------------------------------
# 14. Review of run 9: what the tests above could not see
# ---------------------------------------------------------------------------

def test_html_has_no_inline_script_or_handlers(html_body):
    """Under script-src 'self' an inline script or on*= handler is silently blocked by the browser,
    and the page breaks with no error in any test. So the markup must carry none."""
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html_body), "inline <script> without src"
    assert not re.search(r"\son[a-z]+\s*=", html_body, re.IGNORECASE), "inline event handler"


def test_csp_script_src_is_exactly_self(replay_config):
    """A substring check passes "script-src 'self' 'unsafe-inline'" too: parse the directive."""
    csp = _get("/", replay_config).extra_headers["Content-Security-Policy"]
    directives = {d.split()[0]: d.split()[1:] for d in csp.split(";") if d.strip()}
    assert directives["script-src"] == ["'self'"]
    assert directives["default-src"] == ["'self'"]


def test_js_get_routes_answer_200(js_api_routes, replay_config):
    """Non-404 would pass a 500 or a 503: every GET the page makes must succeed in replay mode."""
    for route in js_api_routes:
        path = route.split("?")[0]
        if path in _POST_ONLY:
            continue
        assert _get(path, replay_config).status == 200, path


def test_favicon_dark_rule_follows_defaults(replay_config):
    """At equal specificity the later rule wins, so the dark override must come after the defaults."""
    svg = _get("/favicon.svg", replay_config).body.decode()
    style = svg[svg.index("<style>"):svg.index("</style>")]
    assert style.index(".body") < style.index("@media (prefers-color-scheme: dark)")


def test_css_declares_color_scheme_in_both_themes(css_body):
    """Without color-scheme, native inputs and the file button stay light on the dark theme."""
    compact = re.sub(r"\s+", "", css_body)
    # declarations only: "prefers-color-scheme:dark" in the media query itself must not count
    decl = lambda v: len(re.findall(r"(?<!prefers-)color-scheme:" + v, compact))  # noqa: E731
    assert decl("light") >= 1
    assert decl("dark") >= 2    # in the media query's block and in the explicit data-theme block
