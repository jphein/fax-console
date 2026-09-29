# Week 2 plan: extract the Fax panel into `faxconsole/`

The map of what to extract, with excerpt line numbers, is [`console-slice.md`](console-slice.md). It
was derived from the excerpt's syntax tree. IBM Bob does the extraction in recorded runs; each run is
committed "by Bob (run N)", with reviewer fixes as separate commits. Nothing here touches a real PBX.

## Design decisions (made; each reversible)
1. **The console imports `faxcli` instead of shelling out to it.** The legacy comment defends the shell-out
   (console e:1997): "a copy of its logic here would drift". An installed package removes the copy, so both
   programs run the same code. `fax_cli()` goes away; its callers call `faxcli` functions with a
   `Transport`.
2. **No AMI.** `asterisk -rx` stays behind the existing `faxcli.transport.Transport` seam. AMI would need a
   manager.conf change on the PBX, and the PBX is never touched. The console's three Asterisk reads (Lucid
   §4) are `pjsip show registrations`, `core show channels` and `pjsip show endpoints`. All three are
   already recorded fixtures, so replay mode needs nothing new for them.
3. **Stdlib only.** The server core is a pure function, `handle(method, path, headers, body) -> Response`;
   a thin `http.server` adapter wraps it.
   - **Tests never open a TCP port.** Inside the sandbox, loopback is denied by the BPF filter, by design.
     Tests call `handle()` directly, and the adapter is tested over `socket.socketpair()` (AF_UNIX, outside
     the IP filter).
   - The server bounds its threads, fixing analysis §9 F: a fixed worker pool, not a thread per request.
4. **Replay mode is the public demo.** `python3 -m faxconsole --replay tests/fixtures` serves on
   127.0.0.1:8093. It is read-only in effect: `POST /api/fax/send` runs as a dry run under replay, is marked
   "replay: nothing is dialled", and renders into a temporary spool. The live mode keeps the legacy write
   gate (the X-Auth-Token and an explicit confirm) and adds nothing new that can dial.
5. **VoIP.ms is replayable too.** The poller gets injectable HTTP, clock and cache path, and a fixture mode.
   Its fixtures are **synthesized** from the documented response shapes, with fictional values. Real API
   responses are never captured: that would need the account's credentials and would expose it.
6. **The MIXED `read_calls`** (Lucid §8) keeps its Asterisk half. The cellular-core cross-check becomes an
   optional instrument that reports "not probed", with a stub.
7. **`/api/version`** ports the excerpt's realm-sigil `version_dict()` (e:434) as `fax.realm.watch`.
   Registering it in status.realm.watch is a week-3 deploy step, and the lead's.
8. **Keep the legacy JSON.** `GET /api/fax` still returns the legacy combined shape (`fax_state`), so the old
   page JS works. The new endpoints are `/api/fax/status`, `/api/fax/log` and `/api/pbx/{trunk,calls,endpoints}`,
   plus `/api/voipms`.

## Bob runs (estimates from runs 1–5: ~0.1 per tool call; reading costs about 1 per 1,000 lines)
| Run | Scope | Cap |
|---|---|---|
| 6 | `faxconsole/` core: `handle()`, routes (fax status, log, legacy /api/fax, pbx trunk/calls/endpoints, version), transports reused from `faxcli`, the adapter with a bounded pool, `--replay`; tests via `handle()` plus socketpair; characterization against the legacy readers (`read_trunk`, `read_calls` Asterisk half, `read_sip_endpoints`) on the same fixtures | 8 |
| 7 | The VoIP.ms poller: injectable HTTP, clock and cache path; bounded lifecycle; replay fixtures (synthesized); `_voipms_scrub` kept; characterization of `snapshot()` against legacy | 6 |
| 8 | The page: the Fax panel, PBX tiles and VoIP.ms panel ported from PAGE (Lucid §7 ids and functions), dark and light (the legacy tokens already have both), favicon, served by `handle()`; tests on routes and ids | 8 |
| 9 | Inbound-fax dialplan as generated config and tests only (`docs/inbound.md` option A); never deployed | 4 |
| 10 | Review fixes | 6 |
| | **Total cap** | **32** (fits about 55; headroom for one re-run) |

Each run is one commit, "by Bob (run N)", with `Assisted-by: IBM Bob`. Reviewer fixes are separate commits;
the pairing is kept (lead). An Oracle review goes on any PR that touches the sandbox, the gate, the
transport, the write path or CI.

## Risks
- **Loopback-denied tests:** handled by decision 3; the run 6 prompt says so explicitly.
- **The page port is large** (PAGE is 42,551 chars). Run 8 gets the functions and ids list, not the whole
  template to re-read.
- **Replay writes:** the send dry run renders into a temp dir, and nothing is written outside it (a test
  asserts this).
