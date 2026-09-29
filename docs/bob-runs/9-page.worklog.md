# WORKLOG

## Run 9 — 2026-10-xx — Port the console page's PBX pieces

**1. Static files** — created `faxconsole/static/index.html`, `faxconsole/static/app.css`,
`faxconsole/static/app.js`, `faxconsole/static/favicon.svg`; updated `pyproject.toml`
with `[tool.setuptools.package-data] faxconsole = ["static/*"]`.
Tests before: 377. Tests after: 418.

**2. JS routes and replay mode** — `app.js` calls `/api/pbx/trunk`, `/api/pbx/calls`
(Live state), `/api/voipms`, `/api/fax`, `/api/fax/send` (send handler), `/api/version`
(footer + replay detection). Uses `X-Auth-Token` from the password field; token kept in
memory only. Replay banner shown when `/api/version` returns `replay: true`.
Files: `faxconsole/static/app.js`.

**3. Dark and light themes** — CSS custom properties with `:root` (light), `@media
(prefers-color-scheme:dark)` and `:root[data-theme="dark"]` blocks. All token values
and status colours carried from `TOKENS_CSS`. Both themes define every colour.
Files: `faxconsole/static/app.css`.

**4. Routes in `handle()`** — added `GET /`, `GET /app.css`, `GET /app.js`,
`GET /favicon.svg` serving from `faxconsole/static/` via `importlib.resources`.
Every page response carries `Content-Security-Policy` and `X-Content-Type-Options`.
`Response` gained an `extra_headers` field; `server.py` sends them. `_route_version`
now accepts config and includes `replay` in the JSON.
Files: `faxconsole/routes.py`, `faxconsole/server.py`.

**5. Tests** — `tests/test_faxconsole_page.py`, 41 tests (≥ 20 required):
status/Content-Type/CSP for each static route; all legacy element ids; favicon link
and valid SVG; both colour schemes in CSS; no `http(s)://` in any static file; every
`fetch("/api/…")` path in `app.js` answers non-404 via replay config; replay banner
and `replay` field in version; 404 still works; password field present.
All 418 tests pass; ruff clean.
