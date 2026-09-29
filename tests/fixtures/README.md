# Test fixtures: recorded, then scrubbed

`asterisk/*.txt` are the exact outputs of `asterisk -rx '<command>'` on the house PBX
(Asterisk 22.5.2). They were recorded on **2026-09-28 22:25 PDT** with read-only `show` commands
only: nothing was sent, dialled or changed. The file name is the command, with spaces turned
into underscores.

`cdr/Master.csv` is the fax call log in Asterisk's `cdr-csv` format (18 quoted columns, UTC
times):
- the **15 fax-related rows** are recorded (the `from-fax` MX922 calls, the `SendFAX`
  originates, and one `AppDial2` stub leg);
- the **5 other rows** (an inbound call, an echo test, a PSTN outbound call, an internal call,
  a voicemail) are **synthesized** in the same format. They exist so the fax filter has
  something to reject. Real non-fax rows are other people's call metadata, so none is included.

`golden/status.json` and `golden/log.json` are what the real `fax --json status` and
`fax --json log` printed against the same PBX at 22:5x PDT, scrubbed the same way. They are the
end-to-end targets for tests: **the frozen legacy CLI, run on the recorded fixtures above, reproduces
both of them exactly.** The new package must do the same, except for deliberate changes, and those
are tested separately.

## What scrubbing changed
Scrubbing was done by a private substitution list that is kept outside the repository.
- Every phone number other than the two public fax test receivers (Faxbeep and HP) was mapped
  into the fictional `202-555-01xx` block, consistently across rows.
- LAN addresses became `192.0.2.x`, keeping the last octet.
- The VoIP.ms sub-account id became `000000_house`, and the VoIP.ms server name
  `pop1.example.com`.
- One device push token became `REDACTED`.
- The cellular-side endpoint name became `cell-bridge`, as in the rebuilt baseline.
- Replacements that change length absorb the following spaces, so column-sensitive parsers see
  the recorded layout.

Nothing else changed. The captures of `fax show stats`, `fax show sessions`,
`module show like res_fax`, `core show channels` and `core show channels concise` needed no
scrubbing and are byte-for-byte as recorded. `core_show_channels_concise.txt` is empty because
the PBX was idle, which is itself a case the code must handle.

**Checked:** the frozen legacy parsers give identical results on the raw and the scrubbed
captures. `fax status` JSON is equal, and `fax log` returns the same 14 rows with the same
derived fields. So the scrub changed values, not structure.
