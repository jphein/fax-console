"""The static page, rendered: app.js runs under node in static mode, on a stub DOM and the exported files.

This is what a visitor of the public demo sees. It is checked for any freshness the copy never measured:
"live", "N s ago", "in N s", "in N days", "right now" or "polled every" (finding A; the lead and the Oracle,
on PR 16).
A test that only reads app.js's source cannot see a reordered branch. This one runs it.
Node is on the workstation and on CI's runners. Without it the test is skipped locally, and it fails in CI.
"""
import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from faxconsole import export as ex

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None and not os.environ.get("CI"), reason="node runs app.js")

# argv: SITE_DIR APP_JS. Prints one JSON object: what each element shows, and every URL the page asked for.
HARNESS = r"""
const fs = require("fs"), path = require("path"), vm = require("vm");
const [site, appJs] = process.argv.slice(2);
const html = fs.readFileSync(path.join(site, "index.html"), "utf8");
const attr = name => (html.match(new RegExp(`<html[^>]*\\bdata-${name}="([^"]*)"`)) || [])[1];
const quote = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
const els = {};
function makeEl(id) {
  let h = "";
  return { id, className: "", title: "", value: "", checked: false, disabled: false, style: {}, files: [],
    onclick: null,
    get innerHTML() { return h; }, set innerHTML(v) { h = String(v); },
    get textContent() { return h.replace(/<[^>]*>/g, " "); }, set textContent(v) { h = quote(v); },
    appendChild(n) { h += n.html; return n; }, addEventListener() {},
    querySelector() { return null; }, querySelectorAll() { return []; } };
}
const requested = [], wait = setTimeout;
globalThis.document = {
  documentElement: { dataset: { static: attr("static"), recorded: attr("recorded") } },
  getElementById: id => els[id] || (els[id] = makeEl(id)),
  createTextNode: t => ({ html: quote(t) }),
};
globalThis.fetch = async (url, opts) => {
  requested.push(String(url) + (opts && opts.method ? " " + opts.method : ""));
  const body = fs.readFileSync(path.join(site, String(url).split("?")[0]), "utf8");   // a missing file throws
  return { ok: true, status: 200, json: async () => JSON.parse(body), text: async () => body };
};
globalThis.setInterval = () => 0;
globalThis.setTimeout = () => 0;
globalThis.console = { log() {}, info() {}, warn() {}, error() {} };
vm.runInThisContext(fs.readFileSync(appJs, "utf8"), { filename: "app.js" });
wait(() => {
  const text = {}, markup = {}, titles = {};
  for (const [id, e] of Object.entries(els)) {
    text[id] = e.textContent.replace(/\s+/g, " ").trim();
    markup[id] = e.innerHTML;
    titles[id] = e.title;
  }
  const chip = els.fresh || makeEl("fresh");
  process.stdout.write(JSON.stringify({ text, markup, titles, requested,
    chip: { text: chip.textContent.trim(), title: chip.title },
    sendDisabled: (els.faxsend || {}).disabled === true }));
}, 300);
"""
# A freshness a static copy cannot have measured.
CLAIMS = re.compile(r"\blive\b|\b\d+\s*[smh]\s+ago\b|\bin\s+\d+\s*(?:s|m|h|days?)\b|\bright now\b"
                    r"|\bpolled every\b", re.I)


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    site = tmp_path_factory.mktemp("site")
    for name, data in ex.export("tests/fixtures").items():
        p = site / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    harness = site.parent / "render.js"
    harness.write_text(HARNESS)
    app_js = ROOT / "faxconsole" / "static" / "app.js"
    r = subprocess.run([NODE or "node", str(harness), str(site), str(app_js)],
                       capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


@pytest.fixture(scope="module")
def site_html():
    return ex.export("tests/fixtures")["index.html"].decode("utf-8")


def test_the_chip_gives_the_capture_time_never_live(rendered):
    chip = rendered["chip"]
    assert chip["text"] == "PBX data recorded 2026-09-28 22:25 PDT", chip      # tests/fixtures/capture.json
    assert "Nothing on this page is live" in chip["title"], chip


CHIP_DISCLAIMER = "Nothing on this page is live."      # the one sentence allowed to say "live"
SHOWN_ATTRS = re.compile(r"""\b(?:title|aria-label|placeholder|alt|value)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
INLINE = "b|i|em|strong|span|a|code|small|abbr|sub|sup|mark|u|s|q|kbd|var|cite"
INLINE_TAGS = re.compile(rf"</?(?:{INLINE})\b[^>]*>", re.I)


def views(markup):
    """What a reader can see in some markup, entities decoded (the Oracle, on PR 16):
    - the text with tags removed, so li<b></b>ve reads "live";
    - the text with tags as spaces;
    - the text as a browser lays it out, with inline tags removed and block tags as spaces, so
      <h3>calls</h3><span>li<b></b>ve</span> reads "calls live";
    - the attributes a browser shows, quoted either way."""
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    out = [re.sub(r"<[^>]*>", "", markup), re.sub(r"<[^>]*>", " ", markup),
           re.sub(r"<[^>]*>", " ", INLINE_TAGS.sub("", markup))]
    out += [a or b for a, b in SHOWN_ATTRS.findall(markup)]
    return [html.unescape(t) for t in out]


def claims(texts):
    return sorted({m.group(0) for t in texts for m in CLAIMS.finditer(t.replace(CHIP_DISCLAIMER, ""))})


def test_no_tile_claims_a_freshness_it_did_not_measure(rendered):
    found = {}
    for el, markup in rendered["markup"].items():
        if c := claims(views(markup) + [rendered["titles"][el]]):
            found[el] = c
    assert not found, found


def test_the_exported_page_itself_claims_no_freshness(site_html):
    """app.js is not the whole page: index.html's own markup is scanned too, text and shown attributes."""
    assert not claims(views(site_html)), claims(views(site_html))


def test_every_request_is_a_relative_json_file(rendered):
    urls = rendered["requested"]
    assert urls and all(re.fullmatch(r"api/[a-z/]+\.json", u) for u in urls), urls


def test_the_tiles_rendered_and_sending_is_off(rendered):
    text = rendered["text"]
    assert text.get("live") and text.get("voipms") and text.get("fax"), sorted(text)
    assert "Fax could not be read" not in text["fax"] and "Last poll error" not in text["voipms"], text
    assert rendered["sendDisabled"] is True
    # The VoIP.ms fixtures are synthesized, never captured: the tile must say so and never call them recorded
    # (the Oracle, on PR 16). Without its static branch it read "never", which no countdown pattern catches.
    assert "a synthesized sample: VoIP.ms was never recorded" in text["voipms"], text["voipms"][:200]
    assert "recording" not in text["voipms"] and "as recorded" not in text["voipms"], text["voipms"][:200]
    assert "the VoIP.ms values are a synthesized sample" in text["foot"], text["foot"][:200]
