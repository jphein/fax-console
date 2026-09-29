# Inbound fax: design (not built)

**Written 2026-09-27 overnight.** The rule for this work: **build only on a path that can't
disturb the house number's normal ringing.** Nothing below is deployed. Every option that touches
202-555-0100 is marked, and the safe one comes first.

## How inbound works today (read from pbx, 2026-09-27 01:40 PDT)

- voip.ms delivers every call for DID **202-555-0100** to the `[voipms]` endpoint, context `from-pstn`.
- `[from-pstn]` answers `_X.` by starting **MixMonitor** (recording both directions to
  `/var/spool/asterisk/monitor/pstn-*.wav`), then rings `${DESKGROUP}` for 20 s, then voicemail 9000.
- `DESKGROUP` includes ext 2007, the OBi100, whose jack feeds the MX922's LINE port. So the MX922
  already **answers a fax by ear** if it's set to auto-answer or fax/tel mode and nobody picks up.
- A stale **PSTN loop test** is still active: `_X./2025550100` answers calls whose caller ID is our
  own number and plays tt-monkeys forever. It dates from 2026-09-03 ("REMOVE WHEN DONE").

## ⋯ [baseline elision: one section on an unrelated house-PBX matter (call recording) removed] ⋯

## Options, safest first

### A. A second DID only for fax (recommended; can't touch the house number)
- Order one more voip.ms DID: about **$1.35/mo** per-minute, and **no E911 needed** since it's fax-only. That's
  **the owner's purchase.**
- Point it at a new sub-account or a URI that lands in a new context `[from-fax-did]`:
  ```
  [from-fax-did]
  exten => _X.,1,NoOp(Inbound fax to ${EXTEN} from ${CALLERID(num)})
   same => n,Set(FAXOPT(ecm)=yes)
   same => n,Set(FAXFILE=/var/spool/asterisk/fax/in-${STRFTIME(,,%Y%m%d-%H%M%S)}-${CALLERID(num)}.tif)
   same => n,Answer()
   same => n,ReceiveFax(${FAXFILE},f)        ; f = G.711 audio; voip.ms refuses T.38
   same => n,Hangup()
  exten => h,1,System(/usr/local/bin/fax-inbound-hook "${FAXFILE}" "${FAXOPT(status)}" "${FAXOPT(pages)}" "${CALLERID(num)}")
  ```
- `fax-inbound-hook` converts the TIFF to PDF (`tiff2pdf`), files it in
  `/var/spool/asterisk/fax/inbox/`, and emails or notifies the owner (gnome-speaks + Slack DM).
- **Zero changes to `[from-pstn]`**, so the house line rings exactly as now.
- Testing is safe: send from `fax send` to the new DID (outbound on `voipms-fax`, inbound on the
  new DID), with no public tester needed.

### B. voip.ms Virtual Fax (no Asterisk work; also a new number)
voip.ms's own fax-to-email product: a fax DID at about $1.99/mo plus about 2.9¢/min. Faxes arrive as PDF
email. It's the easiest, but faxes live in voip.ms's portal, not ours. It's also the owner's purchase.

### C. Fax detection on the house number (NOT recommended, and it touches the house line)
`faxdetect=cng` on the `[voipms]` endpoint, plus an `exten => fax` branch in `[from-pstn]` running
`ReceiveFax`. Risks: detection listens to the first seconds of **every** house call. False
positives send a caller to fax tones. And any mistake in `from-pstn` breaks all inbound calls.
Only with the owner present and a rollback copy ready.

### D. Leave it as is (costs nothing today)
The MX922 already receives faxes on the house line if set to fax/tel auto-switch, but the house
line has to ring it to reach the machine. That's fine for occasional faxes. Paper only, no PDF.

## CLI once A is built

- `fax inbox`: list received faxes (time, from, pages, status).
- `fax show <n>`: open the PDF.
- `fax status` gains a "last inbound" line.

## Decision for the owner

1. **Recording:** remove MixMonitor from the live dialplan and review/delete the 231 MB spool? `yes / keep`
2. **Inbound fax:** `A` (new $1.35/mo DID, built by an agent, house line untouched) / `B` (voip.ms
   Virtual Fax) / `D` (leave it; MX922 by ear).
