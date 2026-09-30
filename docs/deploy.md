# Deploying the replay demo

The public demo is a **static replay on GitHub Pages**, at https://jphein.github.io/fax-console/. It shows the replay views as recorded from the fictional fixtures, and sending is off. `faxconsole` in **replay mode**, run locally or behind a proxy, is the full demo: it serves the recorded fixtures, a send is always a dry run, and nothing reaches a PBX or the network. This page records how each is meant to run. The last section says why each setting of the server is there.

## The static demo (GitHub Pages)

- `scripts/export-static.sh OUT_DIR` builds it from a clean commit:
  - It exports the commit, never the working tree. HEAD is read once, and `git archive` of the commit's `faxconsole/`, `faxcli/` and `tests/fixtures/` goes to the OS sandbox on stdin, so nothing that changes the tree after the checks can reach the export. A tracked symlink or submodule there refuses.
  - Inside the sandbox, `scripts/export-in-sandbox.sh` extracts the archive into a fresh directory (no `..` members, nothing overwritten, owners and modes not kept), checks that it holds exactly the commit's file count, and runs `faxconsole.export` there. That renders every GET route in replay mode and hands the files over as a tar stream on stdout, so they never land in a directory Bob can write.
  - `scripts/untar-site.py` extracts regular files only, with plain names, into a new directory.
  - The scrub gate then checks every file against the private deny-list.
- The page reads `api/<route>.json` relative to itself, because Pages serves it under `/fax-console/`. The send form is disabled, with a note to run it locally.
- Pages sends no headers, so the page carries its Content-Security-Policy in a meta tag. A meta tag cannot carry `frame-ancestors`, so that one directive is left out.
- The version drops the fields that only a running server has (`started`, `uptime`, `runtime`, `os`, `host`, `pid`), per realm-sigil's static contract.
- `scripts/publish-pages.sh SHA` publishes it, pinned to the commit a review named (SHA is 7 to 40 lowercase hex), and only from `main`. It exports afresh, commits the files to the `gh-pages` branch with git plumbing (the checkout never changes), on top of the remote's `gh-pages` as it is now, scrubs that history against the private deny-list, and pushes. CI ignores `gh-pages`. Pages serves the branch's root, and a `.nojekyll` file keeps the files as they are.
- There is no custom domain. realm.watch names are LAN-only by design, so the demo stays on the default Pages URL.

## Run

```
python3 -m faxconsole --replay /opt/fax-console/fixtures --host 127.0.0.1 --port 8093
```

- Bind loopback only, with a reverse proxy in front.
- Install the fixtures (`tests/fixtures`) **outside `/home`**, for example under `/opt/fax-console/` or the unit's `StateDirectory`. Replay responses mask every runtime path (see "Why" below), but a neutral install path costs nothing.
- `--replay` gives the poller a fixture HTTP, so the demo needs no outbound network at all.

## A systemd unit, hardened

- `DynamicUser=yes`, `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`. Replay's temp dir then lives in the unit's private `/tmp`, and it goes when the unit stops.
- `NoNewPrivileges=yes`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`, `IPAddressDeny=any` and `IPAddressAllow=localhost`.
- `MemoryMax=256M` and `TasksMax=64`, as backstops.
- `Restart=on-failure`. On stop, systemd sends SIGTERM, which `main()` turns into an exit, so the cleanup stops the poller and removes the temp dir.

## The reverse proxy (for example Caddy)

- Read timeouts, because the app's handler timeout is an **idle** timeout, not a deadline: a client that trickles bytes can hold a worker for longer.
- A body cap a little above the app's 15 MB PDF limit. The app already answers 401 or 413 before reading any body (the review of PR 8, M1). The cap keeps an oversized upload from reaching the app at all.
- HSTS on the public name. The app itself sends a CSP and `nosniff`.

For Caddy, with `demo.example.com` standing in for the public name:

```
{
	servers {
		timeouts {
			read_header 10s
			read_body 30s
			idle 60s
		}
	}
}

demo.example.com {
	request_body {
		max_size 16MB
	}
	header Strict-Transport-Security "max-age=31536000"
	reverse_proxy 127.0.0.1:8093
}
```

A Caddyfile needs each `{` at the end of its line and each `}` on a line of its own, so keep these blocks on separate lines, as shown.

## Register and check

- The health endpoint is `/api/version`, the realm-sigil contract. In replay mode it reports `replay: true` and `host: "replay"`, never the machine's name.
- Before announcing, fetch every GET route and one dry-run send from the deployed URL. None may show a runtime path, the hostname, or an IP address outside the documentation ranges.

## Why

The review of PR 8 found three ways the demo could expose or exhaust its host:
- an unauthenticated POST whose declared size the server would reserve;
- machine paths in error text;
- an idle-only handler timeout.

The app fixes the first two. The proxy settings above cover the third, and they back up the first.
