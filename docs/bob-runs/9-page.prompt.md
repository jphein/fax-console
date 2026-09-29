Week 2, run 9. Port the console page's PBX pieces, so `faxconsole` serves its own page. Read these first:
- `AGENTS.md`;
- `docs/console-slice.md` §7, which lists the JS functions, routes and element ids to port;
- in `legacy/console/telephony-console.py`:
  - `TOKENS_CSS` (e:62–277), the design tokens, which already carry a dark and a light theme;
  - the three sections of `PAGE` (e:1603–1643): Live state, PSTN account, and Fax;
  - the helpers `esc`, `st`, `prov` and `kb` (e:1647–1660);
  - the renderers `renderVoipms` and `loadVoipms` (e:1662–1733), `tileTrunk` and `tileCalls` (e:1735–1766), and `renderFax`, `loadFax` and the send handler (e:1799–1860);
  - the wiring: `LAST_OK`, `ago`, `freshness` and `load` (e:1862–1989).

Never edit `legacy/`, `tests/test_sandbox_guard.py` or `tests/conftest.py`. All existing tests must stay green.

**Keep a work log.** After each numbered item, append one line to `WORKLOG.md` at the repo root: the item, the files, and the test count. In run 8 this worked: you finished under the cap, with your summary.

**1. Static files** in `faxconsole/static/`, shipped as package data (update `pyproject.toml`):
- `index.html`: the three sections, keeping every legacy element id (`live`, `voipms`, `fax`, `faxform`, `faxnum`, `faxlabel`, `faxfile`, `faxconfirm`, `faxsend`, `faxmsg`, `faxlog`, `foot`). Add a freshness chip, `id="fresh"`: legacy `freshness()` writes to it, but it lived in the navigation bar that the excerpt elides. Add a password field for the write token;
- `app.css`: the tokens and the rules these sections use;
- `app.js`: the ported functions;
- `favicon.svg`: a simple fax glyph that reads at 16 px in both themes.

Keep the legacy comments that carry a rule, such as "NEVER READ is not $0.00", "STALE is a separate axis from LOW", or three-state registration.

**2. The JS** uses only this service's routes:
- `load()` reads `/api/pbx/trunk` and `/api/pbx/calls` for the Live-state tiles, instead of the legacy `/api/state`;
- `loadVoipms()` reads `/api/voipms`, and `loadFax()` reads `/api/fax`;
- the footer shows `/api/version`;
- the send handler replaces legacy `authFetch` with a plain `fetch` that sends `X-Auth-Token` from the password field. Keep the token in memory only.

Also:
- In replay mode, show a banner: "Replay: recorded data; a send is a dry run and nothing is dialled". The page learns the mode from a field that `handle()` provides.
- No external resources at all: no CDN, no web fonts, no remote images.

**3. Dark and light.** Use CSS custom properties, with `@media (prefers-color-scheme: dark)`, and give `body` an explicit background. Both themes must keep the status colours distinguishable.

**4. Routes in `handle()`:**
- `GET /` serves `index.html`, and `GET /app.css`, `/app.js` and `/favicon.svg` serve the others, each with the right `Content-Type`;
- the HTML carries `<link rel="icon" href="/favicon.svg" type="image/svg+xml">`;
- every page response carries a `Content-Security-Policy` of `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`, plus `X-Content-Type-Options: nosniff`:
  - there is no inline script and no inline event handler, so legacy's `onsubmit="return false"` becomes JS in `app.js`;
  - inline `style=` attributes may stay, because the legacy renderers use them throughout;
- unknown paths still get the escaped 404.

**5. Tests** in `tests/test_faxconsole_page.py`, 20 or more, all through `handle()`:
- each static route: the status, `Content-Type` and CSP;
- every legacy id is present in the HTML;
- the favicon link and a valid SVG;
- both colour schemes in the CSS;
- no `http://` or `https://` URL in any static file;
- every `fetch("/api/…")` path found in `app.js` answers through `handle()` with something other than 404, on a replay config from `faxconsole.__main__.build(["--replay", "tests/fixtures"])` (call its `cleanup()` in a `finally`);
- the replay-mode field is present.

`.venv/bin/python -m pytest -q` must show 0 failures, and `.venv/bin/ruff check .` must be clean. End with a short summary: what changed for each numbered item, the test count before and after, and anything you disagree with, with the reason.
