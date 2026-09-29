#!/usr/bin/env python3
"""fax — send a PDF as a fax through the house PBX, and read back what happened.

Runs in two places:
  * on the workstation (or any LAN host): `fax send doc.pdf 2025550142` converts locally, copies the
    TIFF to pbx over ssh and originates the call there.
  * on pbx itself (`--local`, or auto-detected by hostname): no ssh, same code path.
    The Telephony Console's Fax panel shells out to `fax ... --json --local`.

How the call is placed (measured 2026-09-27 03:58 PDT, Faxbeep received the page, 42 s):
  asterisk -rx 'channel originate PJSIP/<1NNNNNNNNNN>@voipms-fax application SendFax <tif>,f'
  * `voipms-fax` is the trunk view with T.38 enabled; voip.ms never accepts the T.38
    re-INVITE, so the `f` option (allow audio/G.711 fax) is what makes it work. Without `f`
    res_fax aborts: "Audio FAX not allowed on channel … T.38 negotiation failed".
  * app and args are separated by a SPACE on the CLI. `SendFax(file,f)` with parentheses is
    parsed as an application named "SendFax(file" and fails with "No such application".
  * TIFF: Group-4, 204x196 dpi, letter; ghostscript `tiffg4` device.

Never fax a real recipient from an agent without the owner's word for that specific send. The
`test` subcommand goes to Faxbeep (1-972-532-9272), a public tester whose inbox is public.
"""
import argparse, csv, datetime as dt, json, os, re, shlex, socket, subprocess, sys, time

EXCHANGE = os.environ.get("FAX_EXCHANGE_HOST", "pbx")
SPOOL = "/var/spool/asterisk/fax"
CDR = "/var/log/asterisk/cdr-csv/Master.csv"
TRUNK = "voipms-fax"
TEST_NUMBER = "19725329272"          # Faxbeep, public test receiver
CDR_COLS = ["accountcode", "src", "dst", "dcontext", "clid", "channel", "dstchannel",
            "lastapp", "lastdata", "start", "answer", "end", "duration", "billsec",
            "disposition", "amaflags", "uniqueid", "userfield"]
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8"]


def on_exchange():
    return socket.gethostname().split(".")[0] == "pbx"


def norm_number(s):
    d = re.sub(r"\D", "", s or "")
    if len(d) == 10:
        d = "1" + d
    if len(d) != 11 or not d.startswith("1"):
        raise SystemExit(f"number must be 10 or 11 digits (got {s!r})")
    if d[1:4] in ("911", "988", "211", "311", "411", "511", "611", "711", "811"):
        raise SystemExit("refusing to fax an N11 number")
    return d


def run(argv, local, sudo=False, timeout=60, check=True):
    """Run argv on pbx (via ssh unless local). Returns CompletedProcess."""
    if sudo:
        argv = ["sudo", "-n"] + argv
    if not local:
        argv = SSH + [EXCHANGE, " ".join(shlex.quote(a) for a in argv)]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(argv[:6])}…\n{r.stderr.strip()}")
    return r


def asterisk(cmd, local):
    # asterisk.ctl is 755: the asterisk user (the console) needs no sudo; the owner over ssh does.
    sudo = not (local and _is_asterisk_user())
    r = run(["asterisk", "-rx", cmd], local, sudo=sudo, check=False)
    return r.stdout if r.returncode == 0 else ""


def _is_asterisk_user():
    try:
        import pwd
        return pwd.getpwuid(os.geteuid()).pw_name == "asterisk"
    except Exception:
        return False


def pdf_to_tiff(pdf, tif):
    subprocess.run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=tiffg4", "-r204x196",
                    "-dFIXEDMEDIA", "-dPDFFitPage", "-sPAPERSIZE=letter",
                    f"-sOutputFile={tif}", pdf], check=True, timeout=120)
    return tiff_pages(tif)


def tiff_pages(path):
    """Count IFDs in a TIFF (pages) without libtiff."""
    import struct
    try:
        with open(path, "rb") as f:
            h = f.read(8)
            bo = "<" if h[:2] == b"II" else ">"
            off = struct.unpack(bo + "I", h[4:8])[0]; n = 0
            while off and n < 10000:
                f.seek(off); cnt = struct.unpack(bo + "H", f.read(2))[0]
                f.seek(off + 2 + cnt * 12); off = struct.unpack(bo + "I", f.read(4))[0]; n += 1
            return n
    except Exception:
        return 0


def cmd_send(a):
    local = a.local or on_exchange()
    number = norm_number(a.number)
    if not os.path.isfile(a.pdf):
        raise SystemExit(f"no such file: {a.pdf}")
    if a.pdf.lower().endswith(".pdf") and open(a.pdf, "rb").read(5) != b"%PDF-":
        raise SystemExit("not a PDF")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", a.label or os.path.splitext(os.path.basename(a.pdf))[0])[:40]
    name = f"{stamp}-{label}-{number}.tif"
    localtif = os.path.join("/tmp" if not local else SPOOL, name)
    pages = pdf_to_tiff(a.pdf, localtif)
    spooled = os.path.join(SPOOL, name)
    if not local:
        run(["scp", "-q", "-o", "BatchMode=yes", localtif, f"{EXCHANGE}:/tmp/{name}"], local=True)
        run(["install", "-o", "asterisk", "-g", "asterisk", "-m", "644", f"/tmp/{name}", spooled], local, sudo=True)
        run(["rm", "-f", f"/tmp/{name}"], local, check=False)
        os.unlink(localtif)
    if a.dry_run:
        out = {"ok": True, "dry_run": True, "number": number, "pages": pages, "tif": spooled}
        return emit(a, out, f"dry run: {pages} page(s) spooled as {spooled}; not dialed")
    cli = f"channel originate PJSIP/{number}@{TRUNK} application SendFax {spooled},f"
    before = parse_stats(asterisk("fax show stats", local))
    out = asterisk(cli, local)
    job = {"ok": True, "number": number, "label": label, "pages": pages, "tif": spooled,
           "originate": out.strip(), "started": dt.datetime.now().isoformat(timespec="seconds")}
    if a.wait:
        job["result"] = wait_for(spooled, local, a.wait, before)
    return emit(a, job, f"dialing {number} with {pages} page(s) → {spooled}" +
                (f"\nresult: {job['result'].get('outcome','?')} · call {job['result'].get('disposition','?')} {job['result'].get('billsec','?')}s"
                 if a.wait else "\nuse `fax log` to see the outcome"))


def wait_for(tif, local, seconds, before):
    """Poll until no fax channel is up, then judge by the fax counters (the only instrument
    that reports a fax outcome; the CDR says ANSWERED for a failed fax too) and attach the
    CDR row for the call."""
    end = time.time() + seconds
    time.sleep(4)
    while time.time() < end:
        chans = asterisk("core show channels concise", local)
        if TRUNK not in chans:
            break
        time.sleep(3)
    after = parse_stats(asterisk("fax show stats", local))
    d = lambda k: after.get(k, 0) - before.get(k, 0)
    outcome = ("SENT" if d("Completed FAXes") > 0 else
               "FAILED" if d("Failed FAXes") > 0 else "UNKNOWN")
    res = {"outcome": outcome, "completed_delta": d("Completed FAXes"), "failed_delta": d("Failed FAXes")}
    for row in fax_rows(local, 100):
        if tif.endswith(row.get("file", "\0")):
            res.update({k: row[k] for k in ("start", "answer", "end", "billsec", "disposition")})
            break
    return res


def cdr_rows(local, limit=200):
    if local:
        try:
            with open(CDR, newline="") as f:
                rows = list(csv.reader(f))
        except OSError:
            return []
    else:
        r = run(["tail", "-n", str(limit), CDR], local, sudo=True, check=False)
        rows = list(csv.reader(r.stdout.splitlines()))
    out = []
    for r in rows[-limit:]:
        if len(r) >= len(CDR_COLS):
            out.append(dict(zip(CDR_COLS, r)))
    return out


def fax_rows(local, limit=200):
    rows = [r for r in cdr_rows(local, limit)
            if r["lastapp"].lower() in ("sendfax", "receivefax") or r["dcontext"] == "from-fax"
            or TRUNK in r["channel"] or TRUNK in r["dstchannel"]]
    for r in rows:
        if r["lastapp"] == "AppDial2":          # the failed originate's stub leg
            continue
        m = re.search(r"([^,/]+\.tiff?)", r["lastdata"])
        r["file"] = m.group(1) if m else ""
        r["direction"] = "in" if r["lastapp"].lower() == "receivefax" else "out"
        if r["dcontext"] == "from-fax":          # MX922 via the OBi: dialed 8/9 + number
            r["number"] = re.sub(r"^[89]", "", r["dst"])
        elif r["dst"] == "s":                   # CLI originate: number is in the TIFF name
            m2 = re.search(r"-(1\d{10})\.tiff?$", r["file"]); r["number"] = m2.group(1) if m2 else "?"
        else:
            r["number"] = r["dst"] or r["src"]
        r["start_local"] = utc_to_local(r["start"])
    rows = [r for r in rows if r["lastapp"] != "AppDial2"]
    rows.reverse()
    return rows


def utc_to_local(s):
    """The CDR is written in UTC (pbx runs Etc/UTC); show the owner's local time."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(os.environ.get("FAX_TZ", "America/Los_Angeles"))
        t = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        return t.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s


def parse_stats(text):
    d = {}
    for line in text.splitlines():
        m = re.match(r"\s*([A-Za-z0-9. ]+?)\s*:\s*(\d+)\s*$", line)
        if m:
            k = m.group(1).strip()
            d.setdefault(k, int(m.group(2)))
    return d


def cmd_status(a):
    local = a.local or on_exchange()
    stats = parse_stats(asterisk("fax show stats", local))
    sessions = [l for l in asterisk("fax show sessions", local).splitlines() if l.startswith("PJSIP")]
    trunk = asterisk("pjsip show endpoint voipms-fax", local)
    reg = asterisk("pjsip show registrations", local)
    obi = asterisk("pjsip show endpoint 2007", local)
    mods = asterisk("module show like res_fax", local)
    out = {"ok": True,
           "spandsp": "res_fax_spandsp" in mods,
           "trunk_registered": "Registered" in reg,
           "trunk_available": bool(re.search(r"Contact:.*voipms.*Avail", trunk)),
           "obi100_registered": bool(re.search(r"Contact:.*2007@.*Avail", obi)),
           "active_sessions": sessions,
           "stats": stats,
           "gs": bool(run(["which", "gs"], local, check=False).stdout.strip())}
    text = (f"spandsp: {'loaded' if out['spandsp'] else 'MISSING'} · trunk registered: {out['trunk_registered']} "
            f"· trunk reachable: {out['trunk_available']} · OBi100 (MX922) registered: {out['obi100_registered']} "
            f"· ghostscript: {out['gs']}\n"
            f"sent: {stats.get('Transmit Attempts', 0)} attempted, {stats.get('Completed FAXes', 0)} completed, "
            f"{stats.get('Failed FAXes', 0)} failed (since Asterisk started) · active now: {len(sessions)}")
    return emit(a, out, text)


def cmd_log(a):
    local = a.local or on_exchange()
    rows = fax_rows(local, a.limit)
    if a.json:
        return emit(a, {"ok": True, "rows": rows}, "")
    print(f"{'started (local)':16} {'dir':3} {'number':12} {'call':10} {'secs':>4}  file")
    for r in rows[:a.limit]:
        print(f"{r['start_local'][5:16]:16} {r['direction']:3} {r['number']:12} {r['disposition']:10} {r['billsec']:>4}  {r['file']}")
    print("'call ANSWERED' means the line connected; whether pages went through is in `fax status` counters or --wait on send.")
    if not rows:
        print("no fax calls in the CDR")


def cmd_test(a):
    a.number = TEST_NUMBER
    a.label = "faxtest"
    if not a.pdf:
        a.pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "test-page.pdf")
    a.wait = a.wait or 90
    print("sending the test page to Faxbeep (public inbox: faxbeep.com)")
    return cmd_send(a)


def emit(a, obj, text):
    if getattr(a, "json", False):
        print(json.dumps(obj))
    else:
        print(text)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="fax", description=__doc__.split("\n")[0])
    p.add_argument("--local", action="store_true", help="run on this host (pbx) without ssh")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    s = p.add_subparsers(dest="cmd", required=True)
    q = s.add_parser("send", help="send a PDF");         q.add_argument("pdf"); q.add_argument("number")
    q.add_argument("--label"); q.add_argument("--wait", type=int, default=0, metavar="SECS", help="wait for the outcome")
    q.add_argument("--dry-run", action="store_true", help="convert and spool, do not dial"); q.set_defaults(fn=cmd_send)
    q = s.add_parser("status", help="trunk, modules, counters");           q.set_defaults(fn=cmd_status)
    q = s.add_parser("log", help="fax calls from the CDR");               q.add_argument("--limit", type=int, default=20); q.set_defaults(fn=cmd_log)
    q = s.add_parser("test", help="send the test page to Faxbeep");       q.add_argument("--pdf"); q.add_argument("--wait", type=int, default=90)
    q.add_argument("--dry-run", action="store_true"); q.set_defaults(fn=cmd_test, label=None)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
