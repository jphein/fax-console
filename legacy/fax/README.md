# fax — send PDFs as faxes from the house PBX

A small CLI (and the code behind the Telephony Console's Fax panel) that turns a PDF into a
Group-4 TIFF and sends it through Asterisk on `pbx` over the VoIP.ms trunk. No fax
machine, no ATA, no third-party fax service.

```
fax send doc.pdf 2025550142 --wait 90     # convert, spool, dial, report the outcome
fax send doc.pdf 2025550142 --dry-run     # convert and spool only
fax status                                # trunk, modules, OBi100, counters
fax log                                   # every fax call in the CDR, newest first
fax test                                  # send the test page to Faxbeep (public inbox)
```

Add `--json` for machine-readable output (the console uses it) and `--local` when running on
`pbx` itself (auto-detected by hostname).

## How it works

1. `gs` renders the PDF to a 204×196 dpi Group-4 TIFF, letter size.
2. The TIFF is copied to `/var/spool/asterisk/fax/` on `pbx` (owned by `asterisk`).
3. Asterisk originates the call: `channel originate PJSIP/1NNNNNNNNNN@voipms-fax application SendFax <tif>,f`.
4. `--wait` polls until the trunk channel is gone, then reads the outcome from `fax show stats`
   (the completed/failed counters), because a CDR says ANSWERED for a failed fax too.

Measured 2026-09-27 03:58 PDT: Faxbeep (1-972-532-9272) received the test page; 42-second call;
`Completed FAXes` went 0 → 1. Details and the things that did not work are in `docs/route.md`.

## Install

On the workstation (or any LAN host with ssh to `pbx`): `ln -s ~/Projects/fax/bin/fax ~/.local/bin/fax`.
On `pbx` (needed by the console): `scripts/deploy.sh` installs `/usr/local/bin/fax` and
`/usr/local/lib/fax/cli.py`, and makes sure `ghostscript` is present.

## Rules

- **Never fax a real recipient from an agent without the owner's word for that specific send.**
  `fax test` is the only send an agent may run on its own; its destination is a public tester.
- N11 numbers are refused. 911 is blocked on this trunk anyway (no E911).
- The MX922 fax machine still works too: dial **8 + 1 + number** from it (the OBi100 ATA route,
  G.711 pass-through). The 9-prefix route runs Asterisk's T.38 gateway and fails; see docs.

## Files

| Path | What |
|---|---|
| `fax/cli.py` | the CLI |
| `bin/fax` | wrapper |
| `scripts/deploy.sh` | install on `pbx` |
| `docs/route.md` | the measured findings behind the route choice |
| `docs/test-page.pdf` | the page `fax test` sends |

Related: `~/Projects/pbx` (Asterisk configs, the `[from-fax]` dialplan, the OBi100 notes) and
`~/Projects/2g/tools/telephony-console.py` (the web panel).

## License

AGPL-3.0-or-later © 2026 Jeffrey Pine Hein. See [LICENSE](LICENSE).
