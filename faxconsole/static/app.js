/* faxconsole app.js — ported from legacy/console/telephony-console.py PAGE template.
   No external resources. No inline event handlers (CSP: script-src 'self'). */

/* ---- helpers ------------------------------------------------------------- */
const esc = s => String(s==null?"":s).replace(/[&<>"']/g,
  c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const st = (k,t) => `<span class="st st-${k}"><i></i>${esc(t)}</span>`;
const prov = (label,cmd,raw) => !cmd ? "" :
  `<details class="prov"><summary>${esc(label||"how this was read")}</summary>`+
  `<span class="src">${esc(cmd)}</span>`+
  (raw?`<span class="src">${esc(raw)}</span>`:"")+`</details>`;
const kb = n => n<1024?n+" B":n<1048576?(n/1024).toFixed(0)+" KB":(n/1048576).toFixed(1)+" MB";

/* ---- replay mode ---------------------------------------------------------
   The page learns the mode from a field that handle() provides.
   In replay mode a send is a dry run and nothing is dialled. */
let REPLAY_MODE = false;

/* ---- wiring: LAST_OK, ago, freshness ------------------------------------- */
/* The last SUCCESSFUL read. Not the last attempt -- the distinction is the
   whole point: an attempt that failed tells you nothing about the network,
   only about the console. */
let LAST_OK = null;
function ago(ms){
  const t = Math.round((Date.now()-ms)/1000);
  if(t < 60) return t+"s ago";
  if(t < 3600) return Math.round(t/60)+"m ago";
  return Math.round(t/3600)+"h ago";
}
function freshness(ok, why){
  const el = document.getElementById("fresh");
  if(!el) return;
  if(ok){
    el.className = "rs-chip";
    el.innerHTML = "<i class=\"rs-mark ok\" aria-hidden=\"true\"></i>";
    el.appendChild(document.createTextNode("live"));
    el.title = "This snapshot was read by the request that drew the page.";
    return;
  }
  /* NOT a red alarm and NOT silence. The values on screen were true when they
     were read; what is unknown is whether they still are. Say exactly that,
     and say HOW OLD -- "ever" and "now" are the two this page must not blur. */
  /* FILLED, not hollow -- corrected when this moved to the shared block. The
     data on screen WAS measured; what is in doubt is its age, not its
     existence. Hollow is reserved for "nothing was measured at all", and
     spending it here would have left nothing to say that with. */
  el.className = "rs-chip stale";
  el.innerHTML = "<i class=\"rs-mark stale\" aria-hidden=\"true\"></i>";
  el.appendChild(document.createTextNode(
    LAST_OK ? ("stale \u00b7 last read " + ago(LAST_OK)) : "never read"));
  el.title = "The refresh is failing, so everything below is as it was at the "
           + "timestamp shown, not as it is now. Reason: " + why;
}

/* ---- VoIP.ms renderer ---------------------------------------------------- */
/* prov helper — voipms_seen tracks whether we have ever rendered a real snapshot */
let VOIPMS_SEEN = false;
function renderVoipms(v){
  const el = document.getElementById("voipms");
  if(!el) return;
  if(!v){ return; }
  const bal = v.balance;
  /* ⛔ NEVER READ: the poller has not completed a fetch. NOT "$0.00".
     A balance of zero and a balance nobody has fetched are opposite facts and
     both render as a small number if you let them. */
  if(bal === null || bal === undefined){
    el.innerHTML = `<div class="card">${st("unread","balance not read yet")}
      <div class="cs-amb">${v.polling
        ? "The background poller is running; the first VoIP.ms fetch takes up to "
          + "five minutes. This is not zero &mdash; it is <b>not yet known</b>."
        : "<b>The poller is not running.</b> Nothing will refresh this."}
        ${v.error?"<br>Last error: "+esc(v.error):""}</div>
      ${prov("source","voip.ms API, background poll")}</div>`;
    return;
  }
  VOIPMS_SEEN = true;
  /* ⚠️ STALE IS A SEPARATE AXIS FROM LOW. A stale balance may be fine and may be
     catastrophic, and the page cannot tell which — so it reports both and lets
     neither hide the other. */
  const low = v.balance_low === true;
  const age = v.age===null||v.age===undefined ? "never"
            : (v.age<90 ? v.age+"s ago"
               : (v.age<5400 ? Math.round(v.age/60)+"m ago"
                             : Math.round(v.age/3600)+"h ago"));
  const months = (v.months_left===null||v.months_left===undefined)
               ? "" : `<div class="vm-sub">about <b>${v.months_left}</b> months of line
                       rental at the current DID fee &mdash; call minutes are extra and
                       are noise beside it.</div>`;
  const bill = (v.days_to_billing===null||v.days_to_billing===undefined)
             ? "" : `<div class="vm-sub">next billing in <b>${v.days_to_billing}</b>
                     days${v.did_next_billing?` (${esc(v.did_next_billing)})`:""}.</div>`;
  /* ⚠️ THREE-STATE, like SMS `bound`: null means the poller has not fetched the
     registration section, which is NOT "not registered". */
  const reg = v.registered === true ? st("ok","registered with VoIP.ms")
            : (v.registered === false ? st("bad","NOT registered with VoIP.ms")
               : st("idle","registration not fetched yet"));
  /* ⭐ TWO INDEPENDENT WITNESSES TO ONE FACT, and the page says when they differ.
     asterisk's own view is on the PSTN trunk tile; this is VoIP.ms's view of us.
     A self-consistent instrument cannot detect its own staleness. */
  const agree = v.registered === null || v.registered === undefined ? ""
    : (v.agrees_with_asterisk === false
        ? `<div class="cs-amb">&#9888; <b>VoIP.ms and asterisk disagree about this
           trunk.</b> One of the two is stale or the registration is flapping;
           neither view alone can tell you which.</div>` : "");
  el.innerHTML = `<div class="cs-sum">${reg}
      <span class="cs-win">balance read ${esc(age)}${v.stale?" &middot; STALE":""}</span></div>
    <div class="card">
      <div class="vm-bal${low?" vm-low":""}">$${bal.toFixed(2)}</div>
      <div class="vm-sub">VoIP.ms balance${low
        ? ` &mdash; <b>below the $${v.low_threshold.toFixed(2)} alert threshold</b>` : ""}.</div>
      ${months}${bill}
    </div>
    ${agree}
    ${v.did_description?`<div class="vm-sub">DID: ${esc(v.did_description)}${
       v.did_sms_enabled?" &middot; SMS enabled":""}${v.did_e911?" &middot; E911":""}</div>`:""}
    ${v.error?`<div class="cs-amb">Last poll error: ${esc(v.error)}</div>`:""}
    ${prov("source","voip.ms API, polled every 300s in the background")}`;
}
async function loadVoipms(){
  try{ renderVoipms(await (await fetch("/api/voipms")).json()); }
  catch(e){
    const el=document.getElementById("voipms");
    if(el && !VOIPMS_SEEN)
      el.innerHTML=`<div class="card">${st("unread","balance not read")}
        <div class="cs-amb">${esc(String(e&&e.message||e))}</div></div>`;
  }
}

/* ---- Live-state tiles ---------------------------------------------------- */
function tileTrunk(t){
  if(!t.ok) return `<div class="tile"><h3>PSTN trunk</h3>
    <div class="big">${st("unread","not probed")}</div>
    <div class="kv"><span>why</span><span>${esc(t.why)}</span></div>${prov("source",t.src)}</div>`;
  const reg = t.status==="Registered";
  return `<div class="tile"><h3>PSTN trunk</h3>
    <div class="big">${t.status?(reg?st("ok","registered"):st("bad",t.status)):st("warn","no registration row")}</div>
    ${t.name?`<div class="kv"><span>trunk</span><span>${esc(t.name)}</span></div>`:""}
    ${t.uri?`<div class="kv"><span>server</span><span>${esc(t.uri)}</span></div>`:""}
    ${t.expires?`<div class="kv"><span>renews in</span><span>${esc(t.expires)}s</span></div>`:""}
    ${prov("source",t.src,t.raw)}</div>`;
}
function tileCalls(c){
  const insts = c.instruments||[];
  const head = c.value===null ? st("unread","not probed")
    : c.impossible ? st("warn","more cellular connections than calls")
    : c.value===0 ? st("ok","no calls in progress")
    : st("ok", c.value+" in progress");
  return `<div class="tile"><h3>Active calls</h3><div class="big">${head}</div>
    ${insts.map(i=>`<div class="kv"><span>${esc(i.name)}</span><span>${
      i.ok? (i.value===null?"—":i.value) : "not probed"}</span></div>`).join("")}
    ${insts.filter(i=>i.note).map(i=>`<div style="font-family:var(--serif);
      font-size:.85rem;color:var(--ink2);margin-top:7px">${esc(i.note)}</div>`).join("")}
    <div style="font-family:var(--serif);font-size:.85rem;color:var(--ink2);margin-top:8px">
      Asterisk counts every call; the MSC counts only the cellular ones, so the
      second number is a <em>subset</em> of the first and is normally lower.
      ${c.impossible?"<b>Right now it is higher, which should not be possible.</b>":""}
    </div>
    ${insts.map(i=>prov(i.name,i.src,i.raw||i.why)).join("")}</div>`;
}

/* ---- Fax renderer -------------------------------------------------------- */
function renderFax(d){
  const el=document.getElementById("fax"), lg=document.getElementById("faxlog");
  if(!d||!d.ok){
    el.innerHTML=`<div class="banner bad"><b>Fax could not be read</b><code>${esc(d&&d.src||"/api/fax")}</code> — ${esc(d&&d.why||"?")}</div>`;
    lg.innerHTML=""; return;
  }
  const s=d.status, st_=s.stats||{};
  el.innerHTML=`<div class="grid">
    <div class="card"><div class="lbl">Trunk</div>
      ${s.trunk_registered?st("ok","registered"):st("bad","not registered")}
      ${s.trunk_available?st("ok","reachable"):st("warn","unreachable")}
      <div class="sub">voipms-fax · G.711 · T.38 refused by carrier</div></div>
    <div class="card"><div class="lbl">Engine</div>
      ${s.spandsp?st("ok","spandsp loaded"):st("bad","spandsp missing")}
      ${s.gs?st("ok","ghostscript"):st("bad","no ghostscript")}
      <div class="sub">${(s.active_sessions||[]).length} active session${(s.active_sessions||[]).length===1?"":"s"}</div></div>
    <div class="card"><div class="lbl">Since Asterisk started</div>
      <div class="mono">${st_["Transmit Attempts"]||0} attempted · ${st_["Completed FAXes"]||0} completed · ${st_["Failed FAXes"]||0} failed</div>
      <div class="sub">fax show stats</div></div>
    <div class="card"><div class="lbl">Fax machine (MX922 via OBi100)</div>
      ${s.obi100_registered?st("ok","ext 2007 registered"):st("na","ext 2007 absent")}
      <div class="sub">dial 8 + 1 + number from the machine</div></div>
  </div>`;
  const rows=d.log||[];
  lg.innerHTML=`<div class="scroll"><table><thead><tr>
    <th>Started</th><th>Dir</th><th>Number</th><th>Call</th><th class="mono">Secs</th><th>File</th></tr></thead><tbody>
    ${rows.map(r=>`<tr>
      <td class="mono">${esc((r.start_local||r.start||"").slice(5,16))}</td>
      <td>${esc(r.direction)}</td>
      <td class="mono">${esc(r.number||"—")}</td>
      <td class="disp-${esc(String(r.disposition||"").replace(/[^A-Z]/g,""))}">${esc(r.disposition)}</td>
      <td class="mono">${esc(r.billsec)}</td>
      <td class="mono">${esc(r.file||"")}</td></tr>`).join("")}
    </tbody></table></div>
    <p style="font-family:var(--serif);color:var(--ink2);font-size:.9rem;margin-top:10px">
    Fax calls from the CDR, newest first. <b>ANSWERED means the line connected;</b> delivery is
    what the counters above say, and <code>fax send --wait</code> reports it per send.</p>`;
}
async function loadFax(){
  try{ renderFax(await (await fetch("/api/fax",{cache:"no-store"})).json()); }
  catch(e){ renderFax({ok:false,src:"/api/fax",why:String(e)}); }
}

/* ---- Send handler --------------------------------------------------------
   Replaces legacy authFetch: sends X-Auth-Token from the password field.
   Token is read from the DOM on each click and never persisted anywhere. */
document.getElementById("faxsend").onclick = async () => {
  const b=document.getElementById("faxsend"), m=document.getElementById("faxmsg");
  const f=document.getElementById("faxfile").files[0];
  if(!f){ m.className="msg bad"; m.textContent="pick a PDF first"; return; }
  if(!document.getElementById("faxconfirm").checked){ m.className="msg bad"; m.textContent="tick the confirmation first"; return; }
  const fd=new FormData();
  fd.append("number",document.getElementById("faxnum").value);
  fd.append("label",document.getElementById("faxlabel").value);
  fd.append("confirm","yes");
  fd.append("file",f,f.name);
  /* Read token from the password field on click; never stored elsewhere. */
  const tok=(document.getElementById("token")||{}).value||"";
  b.disabled=true; m.className="msg"; m.textContent="converting and dialing…";
  try{
    const j=await (await fetch("/api/fax/send",{method:"POST",
      headers:{"X-Auth-Token":tok}, body:fd})).json();
    m.className="msg "+(j.ok?"good":"bad");
    m.textContent=(j.ok?"sent to Asterisk — ":"not sent — ")+(j.detail||"");
    if(j.ok){ document.getElementById("faxconfirm").checked=false; setTimeout(loadFax,5000); setTimeout(loadFax,60000); }
  }catch(e){ m.className="msg bad"; m.textContent="not sent — "+e; }
  b.disabled=false;
};

/* Prevent default form submit (was onsubmit="return false" in legacy) */
document.getElementById("faxform").addEventListener("submit", e => e.preventDefault());

/* ---- load() — main poll loop --------------------------------------------- */
async function load(){
  let trunk, calls;
  try{
    /* load() reads /api/pbx/trunk and /api/pbx/calls for the Live-state tiles,
       instead of the legacy /api/state. */
    [trunk, calls] = await Promise.all([
      fetch("/api/pbx/trunk",{cache:"no-store"}).then(r=>r.json()),
      fetch("/api/pbx/calls",{cache:"no-store"}).then(r=>r.json()),
    ]);
  }catch(e){
    /* Leave the previous snapshot on screen -- it is the best information
       available and blanking it would destroy the only record of what the
       network was doing. But STOP CALLING IT CURRENT. */
    freshness(false, String(e && e.message || e));
    return;
  }
  LAST_OK = Date.now();
  freshness(true);
  document.getElementById("live").innerHTML = tileTrunk(trunk)+tileCalls(calls);
  Promise.allSettled([loadVoipms(), loadFax()]);

  /* Footer: version line */
  fetch("/api/version").then(r=>r.json()).then(v=>{
    const foot=document.getElementById("foot");
    if(foot) foot.textContent=
      "Every live value on this page carries the command that produced it — "
      +"open how this was read on any tile. Where a state could not be read "
      +"it says not probed rather than guessing, because a wrong green dot is "
      +"believed and an honest gap is not."
      +(v&&v.version?" \u00b7 v"+v.version:"");
  }).catch(()=>{});
}

/* ---- startup ------------------------------------------------------------- */
(async () => {
  /* Check replay mode from the server */
  try{
    const v = await fetch("/api/version").then(r=>r.json());
    if(v && v.replay){
      REPLAY_MODE = true;
      const banner=document.getElementById("replay-banner");
      if(banner) banner.style.display="block";
    }
  }catch(_){}
  load();
  setInterval(load, 20000);
})();
