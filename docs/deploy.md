# Deploying the replay demo

The public demo is `faxconsole` in **replay mode**: it serves the recorded fixtures, a send is always a dry run, and nothing reaches a PBX or the network. This page records how it is meant to run. The last section says why each setting is there.

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

- Read timeouts, because the app's handler timeout is an **idle** timeout, not a deadline: a client that trickles bytes can hold a worker for longer. For Caddy, that is `servers { timeouts { read_header 10s  read_body 30s  idle 60s } }`.
- A body cap a little above the app's 15 MB PDF limit, for Caddy `request_body { max_size 16MB }`. The app already answers 401 or 413 before reading any body (the review of PR 8, M1). The cap keeps an oversized upload from reaching the app at all.
- HSTS on the public name. The app itself sends a CSP and `nosniff`.

## Register and check

- The health endpoint is `/api/version`, the realm-sigil contract. In replay mode it reports `replay: true` and `host: "replay"`, never the machine's name.
- Before announcing, fetch every GET route and one dry-run send from the deployed URL. None may show a runtime path, the hostname, or an IP address outside the documentation ranges.

## Why

The review of PR 8 found three ways the demo could expose or exhaust its host:
- an unauthenticated POST whose declared size the server would reserve;
- machine paths in error text;
- an idle-only handler timeout.

The app fixes the first two. The proxy settings above cover the third, and they back up the first.
