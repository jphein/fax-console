# The fax route, measured (2026-09-26/27)

## What works
| Route | Result |
|---|---|
| **Asterisk `SendFax` from a TIFF, `voipms-fax` endpoint, option `f`** | Faxbeep received the page. 42 s call, `Completed FAXes` 0→1 (03:58 PDT 9/27). This is what `fax send` does. |
| MX922 → OBi100 (ext 2007) → dial **8** + 1 + number (`_8.` in `[from-fax]`, `FAXOPT(gateway)=no`, plain G.711) | Faxbeep received the page 10:41 PDT 9/26. 48 s, 18/2381 packets lost, 10 ms jitter. |

## What does not
| Route | Symptom | Why |
|---|---|---|
| MX922 → dial **9** (`FAXOPT(gateway)=yes`, Asterisk T.38 gateway) | MX922 reports "Busy" after fax tones; call ~25–40 s | The gateway waits `t38timeout=5000` for voip.ms to accept T.38; it never does; Asterisk then sends the OBi only ~150 audio packets and silence (X-RTP-Stat on the BYE: PR=150 vs PS=1994). |
| `SendFax` without `f` | 10 s call, "Audio FAX not allowed on channel … T.38 negotiation failed; aborting" | same: no T.38 at voip.ms |
| `channel originate … application SendFax(/path,f)` | "No such application 'SendFax(/path'" | CLI syntax is `application <app> <args>` with a space |
| HP's test line 1-888-473-2963 | "Busy" even when the path is fine | unreliable public tester; use Faxbeep (1-972-532-9272, results at faxbeep.com) |

## Also learned
- **Ubuntu's AppArmor profile for ghostscript (`/etc/apparmor.d/gs`) denies reading PDFs outside its
  allow-list**, even in /tmp: `apparmor="DENIED" operation="open" profile="gs"`. The symptom is
  ghostscript's `/undefinedfilename … Last OS error: Permission denied`, which reads like a file
  permission problem and is not. Fix: `/etc/apparmor.d/local/gs` allowing the console upload dir
  (read) and the fax spool (rw); `scripts/deploy.sh` installs it.
- The OBi100 (192.0.2.131, final firmware 1.3.0) dropped off the network twice on 9/26, both
  around DHCP renewal time; fix applied: infinite lease on its static reservation in the router
  (backup `/etc/dhcp-uci-backup-20260926-170137.conf`). Power cycle brings it back.
- The MX922's clock was unset (header printed 01/04/2013) and it has no sender ID; the ADF loads
  face-up.
- Asterisk's `debug.log` stops being written after logrotate until `asterisk -rx 'logger reload'`.
- voip.ms charges nothing extra for fax over SIP. Their "Virtual Fax" is a separate portal/email
  product that needs its own fax DID.

## Not built yet: inbound
Inbound calls to 202-555-0100 ring DESKGROUP (including ext 2007, so the MX922 answers a fax
by ear). A software inbound path would add fax detection (`faxdetect=yes` on the trunk or a
`ReceiveFax` branch in `[from-pstn]`) writing TIFFs to the spool and a `fax inbox` subcommand.
