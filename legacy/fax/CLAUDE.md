# fax — working notes for Claude

Send-only fax CLI for the house PBX. Read `README.md` first; this file is the rules and the seams.

## Rules
- **No real-recipient send without the owner's explicit word for that send.** Agents may run `fax test`
  (Faxbeep, a public inbox) and `--dry-run` freely. A real filing, for example, goes only
  when the owner says "send it".
- Nothing here holds secrets. Asterisk access is `ssh pbx` + `sudo asterisk -rx` (the owner has
  passwordless sudo there). The console runs as the `asterisk` user and needs no sudo.
- Every ssh call: `-o BatchMode=yes`. The pbx/2g repos found that BatchMode alone can still
  raise a GUI passphrase dialog on the owner's desktop under some conditions; this CLI is run
  interactively or by the console on pbx, so it does not export SSH_ASKPASS_REQUIRE —
  if it ever runs unattended from the workstation, add `export SSH_ASKPASS_REQUIRE=never`.

## Seams
- **Asterisk side** (`~/Projects/pbx`): endpoint `voipms-fax` (T.38 view of the VoIP.ms trunk),
  `res_fax` + `res_fax_spandsp`, spool `/var/spool/asterisk/fax`, CDR
  `/var/log/asterisk/cdr-csv/Master.csv` (UTC). Dialplan `[from-fax]` is the MX922/OBi100 route.
- **Web side** (`~/Projects/2g/tools/telephony-console.py`, Fax panel): shells out to
  `/usr/local/bin/fax --local --json {status,log,send}`. Keep the JSON shapes stable:
  `status` → {ok, spandsp, trunk_registered, trunk_available, obi100_registered,
  active_sessions[], stats{}, gs}; `log` → {ok, rows[]} with start_local, direction, number,
  disposition, billsec, file; `send --wait` → {ok, number, pages, tif, result{outcome,…}}.
- **Deploy**: `scripts/deploy.sh` (scp + `sudo install`). The console's deploy is separate
  (2g `scripts/deploy-console.sh`).

## What is measured, not assumed
- voip.ms never accepts the T.38 re-INVITE; `SendFax(...,f)` (allow audio) is required.
  Without `f`: "Audio FAX not allowed on channel … T.38 negotiation failed; aborting."
- CLI originate syntax: app and args separated by a SPACE. Parentheses make Asterisk look for an
  application literally named `SendFax(/path`.
- A CDR disposition of ANSWERED is not a delivered fax. `fax show stats` counters are.
- Inbound fax is NOT built. The DID rings DESKGROUP (incl. the OBi/MX922, which answers faxes as
  a machine). A `ReceiveFax` path would need a dialplan branch + fax detection; see docs/route.md.

## Conventions
- Findings → `docs/`; scratch → gitignored `scratch/`. No test framework; validate with
  `fax test --wait 90` and `fax status`. Stage selectively; never `git add -A`.
- If this grows a web face of its own, register it as `fax.realm.watch` with realm-sigil.
