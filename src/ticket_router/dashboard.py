"""
Stakeholder dashboard.

A local web app for classifying tickets and understanding model performance.
The scorecard, category accuracy, precision/recall, confusion, and calibration
read from the predictions table in BigQuery. The classifier (Classify view)
calls Vertex AI live. Launch with `python scripts/dashboard.py` and open
http://127.0.0.1:8000. Binds to localhost only.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ticket_router.classifier import TicketClassifier
from ticket_router.config import get_settings
from ticket_router.logging_config import configure_logging, get_logger
from ticket_router.routing import decide_route

logger = get_logger(__name__)


class SimRequest(BaseModel):
    text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    from google.cloud import bigquery

    app.state.settings = settings
    app.state.bq = bigquery.Client(project=settings.google_cloud_project)
    app.state.bq_mod = bigquery
    app.state.classifier = TicketClassifier(settings)
    yield


app = FastAPI(title="Ticket Router Dashboard", lifespan=lifespan)


def _query(app: FastAPI, sql: str) -> list[dict]:
    job_config = app.state.bq_mod.QueryJobConfig(
        maximum_bytes_billed=app.state.settings.max_bytes_billed
    )
    rows = app.state.bq.query(sql, job_config=job_config).result()
    return [dict(r) for r in rows]


@app.get("/api/meta")
def meta(request: Request):
    s = request.app.state.settings
    return {
        "source": s.incident_source_table,
        "predictions": s.predictions_table,
        "model": s.gemini_model,
    }


@app.get("/api/stats")
def stats(request: Request):
    settings = request.app.state.settings
    table = settings.predictions_table
    try:
        overall = _query(
            request.app,
            f"""
            SELECT
              COUNT(*) AS total,
              COUNTIF(predicted_category IS NULL) AS failed,
              AVG(confidence) AS avg_conf,
              COUNTIF(category_match) AS matches,
              COUNTIF(category_match IS NOT NULL) AS scored,
              COUNTIF(auto_routed) AS auto_routed
            FROM `{table}`
            """,
        )[0]
        by_cat = _query(
            request.app,
            f"""
            SELECT
              predicted_category AS category,
              COUNT(*) AS n,
              COUNTIF(category_match) AS matches,
              COUNTIF(category_match IS NOT NULL) AS scored,
              AVG(confidence) AS avg_conf
            FROM `{table}`
            WHERE predicted_category IS NOT NULL
            GROUP BY predicted_category
            ORDER BY n DESC
            """,
        )
    except Exception as exc:
        return {"exists": False, "table": table, "error": str(exc)}

    return {"exists": True, "table": table, "overall": overall, "by_category": by_cat}


@app.get("/api/predictions")
def predictions(request: Request, filter: str = "all", limit: int = 100):
    settings = request.app.state.settings
    table = settings.predictions_table
    where = "WHERE category_match = FALSE" if filter == "disagree" else ""
    limit = max(1, min(limit, 500))
    try:
        rows = _query(
            request.app,
            f"""
            SELECT number, ticket_excerpt, predicted_category, confidence,
                   human_category, category_match, assignment_group, auto_routed
            FROM `{table}`
            {where}
            ORDER BY predicted_at DESC
            LIMIT {limit}
            """,
        )
    except Exception as exc:
        return {"exists": False, "error": str(exc), "rows": []}
    return {"exists": True, "rows": rows}


@app.get("/api/evaluation")
def evaluation(request: Request):
    settings = request.app.state.settings
    table = settings.predictions_table
    try:
        rows = _query(
            request.app,
            f"""
            SELECT predicted_category, human_category, confidence, category_match
            FROM `{table}`
            WHERE predicted_category IS NOT NULL
            """,
        )
    except Exception as exc:
        return {"exists": False, "error": str(exc)}
    from ticket_router.evaluation import compute_metrics, top_confusions

    m = compute_metrics(rows)
    m["top_confusions"] = top_confusions(m["confusion"])
    m["exists"] = True
    return m


@app.post("/api/simulate")
async def simulate(req: SimRequest, request: Request):
    text = req.text.strip()
    if not text:
        return {"error": "Enter some ticket text to classify."}
    analysis = await request.app.state.classifier.analyze(text)
    decision = decide_route(analysis.category, analysis.priority, analysis.confidence)
    return {
        "category": analysis.category.value,
        "confidence": analysis.confidence,
        "priority": analysis.priority.value,
        "eta": analysis.eta.value,
        "tags": list(analysis.tags),
        "assignment_group": decision.assignment_group,
        "auto_routed": decision.auto_routed,
        "reason": decision.reason,
        "draft_response": analysis.draft_response,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return _HTML


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ticket Router</title>
<style>
  :root{
    --bg:#f4f5fa; --sidebar:#171b2e; --sidebar2:#212744; --surface:#ffffff;
    --line:#e7e9f2; --ink:#191e34; --muted:#6b7390; --faint:#9aa1bb;
    --primary:#5566f6; --primary-weak:#eef0ff;
    --good:#12b886; --good-weak:#e4f7f0; --warn:#e8a13a; --warn-weak:#fbf0dd;
    --bad:#e5546a; --bad-weak:#fce8ec;
    --radius:14px; --shadow:0 1px 2px rgba(20,25,55,.04),0 6px 20px rgba(20,25,55,.05);
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{background:var(--bg);color:var(--ink);
    font-family:system-ui,-apple-system,"Segoe UI Variable","Segoe UI",Roboto,sans-serif;
    font-size:14px;line-height:1.5;-webkit-font-smoothing:antialiased}
  .num{font-variant-numeric:tabular-nums}
  .app{display:flex;min-height:100vh}

  /* sidebar */
  .side{width:230px;flex-shrink:0;background:linear-gradient(180deg,var(--sidebar),var(--sidebar2));
    color:#fff;display:flex;flex-direction:column;padding:20px 14px;position:sticky;top:0;height:100vh}
  .brand{display:flex;align-items:center;gap:10px;padding:4px 8px 18px}
  .brand .mark{width:30px;height:30px;border-radius:9px;background:var(--primary);
    display:grid;place-items:center;font-weight:800;color:#fff;font-size:15px}
  .brand b{font-size:15px;letter-spacing:-.01em}
  .brand span{display:block;font-size:11px;color:rgba(255,255,255,.5);font-weight:400}
  nav{display:flex;flex-direction:column;gap:2px;margin-top:6px}
  .nav{display:flex;align-items:center;gap:11px;width:100%;text-align:left;border:0;cursor:pointer;
    background:transparent;color:rgba(255,255,255,.72);padding:10px 12px;border-radius:10px;
    font:inherit;font-weight:500;transition:background .15s,color .15s}
  .nav:hover{background:rgba(255,255,255,.06);color:#fff}
  .nav.active{background:rgba(255,255,255,.10);color:#fff}
  .nav .dot{width:7px;height:7px;border-radius:50%;background:currentColor;opacity:.55}
  .nav.active .dot{background:var(--primary);opacity:1;box-shadow:0 0 0 4px rgba(85,102,246,.25)}
  .side .foot{margin-top:auto;font-size:11px;color:rgba(255,255,255,.4);padding:10px 8px;line-height:1.6}

  /* content */
  .main{flex:1;min-width:0;display:flex;flex-direction:column}
  .top{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;
    padding:18px 30px;border-bottom:1px solid var(--line);background:rgba(255,255,255,.7);
    backdrop-filter:blur(6px);position:sticky;top:0;z-index:5}
  .top h1{margin:0;font-size:19px;letter-spacing:-.02em}
  .top .meta{display:flex;gap:8px;flex-wrap:wrap}
  .pillchip{background:var(--surface);border:1px solid var(--line);border-radius:999px;
    padding:5px 11px;font-size:11.5px;color:var(--muted)}
  .pillchip b{color:var(--ink);font-weight:600}
  .view{padding:26px 30px 70px;display:none;animation:fade .25s ease}
  .view.active{display:block}
  @keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
  @media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}

  .eyebrow{text-transform:uppercase;letter-spacing:.09em;font-size:11px;font-weight:700;
    color:var(--faint);margin:0 0 12px}
  .section+.section{margin-top:30px}
  .card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:var(--shadow);padding:18px}
  .grid{display:grid;gap:16px}
  .kpis{grid-template-columns:repeat(4,1fr)}
  .kpi .lab{font-size:12px;color:var(--muted)}
  .kpi .big{font-size:32px;font-weight:700;letter-spacing:-.02em;margin-top:5px}
  .kpi .sub{font-size:12px;color:var(--faint);margin-top:2px}

  /* classify hero */
  .hero{display:grid;grid-template-columns:1.1fr .9fr;gap:18px;align-items:stretch}
  textarea{width:100%;min-height:150px;border:1px solid var(--line);border-radius:11px;
    padding:14px;font:inherit;resize:vertical;background:#fbfcfe;color:var(--ink)}
  textarea:focus{outline:2px solid var(--primary);outline-offset:1px;border-color:transparent}
  .chips{display:flex;flex-wrap:wrap;gap:7px;margin:11px 0}
  .chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:6px 11px;
    font-size:12px;color:var(--muted);cursor:pointer;transition:.15s}
  .chip:hover{border-color:var(--primary);color:var(--primary);background:var(--primary-weak)}
  .btn{background:var(--primary);color:#fff;border:0;border-radius:10px;padding:11px 18px;
    font:inherit;font-weight:650;cursor:pointer;transition:.15s}
  .btn:hover{filter:brightness(1.05)}
  .btn:disabled{opacity:.55;cursor:default}
  .resultcard{display:flex;flex-direction:column;justify-content:center;align-items:center;
    text-align:center;gap:4px}
  .resultcard.empty{color:var(--faint);font-size:13px}
  .gauge{position:relative;width:160px;height:160px}
  .gauge .lab{position:absolute;inset:0;display:flex;flex-direction:column;justify-content:center;align-items:center}
  .gauge .lab .v{font-size:30px;font-weight:750;letter-spacing:-.02em}
  .gauge .lab .t{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
  .bigcat{font-size:23px;font-weight:700;letter-spacing:-.01em;margin-top:6px}
  .metaline{font-size:12.5px;color:var(--muted)}
  .tags{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin-top:4px}
  .tag{background:var(--primary-weak);color:var(--primary);border-radius:7px;padding:3px 9px;font-size:12px}
  .route{margin-top:10px;font-size:12.5px;border-radius:9px;padding:8px 12px;width:100%}
  .route.hold{background:var(--warn-weak);color:#9a6418}
  .route.auto{background:var(--good-weak);color:#0a7a5a}
  .reply{margin-top:10px;font-size:12.5px;color:var(--muted);text-align:left;width:100%}

  /* bars */
  .row{display:grid;grid-template-columns:160px 1fr 56px;gap:12px;align-items:center;
    margin-bottom:10px;font-size:13px}
  .track{height:9px;background:#eef0f6;border-radius:6px;overflow:hidden}
  .track>div{height:100%;border-radius:6px;transition:width .5s ease}
  .muted{color:var(--muted)}.faint{color:var(--faint)}

  /* tables */
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--faint);font-weight:700}
  tr:last-child td{border-bottom:0}
  tbody tr:hover{background:#fafbff}
  .badge{font-size:11px;font-weight:650;padding:3px 9px;border-radius:999px;white-space:nowrap;display:inline-block}
  .b-good{background:var(--good-weak);color:#0a7a5a}
  .b-warn{background:var(--warn-weak);color:#9a6418}
  .b-na{background:#eef0f6;color:var(--muted)}
  .seg{display:inline-flex;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#fff}
  .seg button{border:0;background:#fff;padding:8px 14px;font:inherit;cursor:pointer;color:var(--muted)}
  .seg button.on{background:var(--primary);color:#fff}
  .empty{color:var(--faint);font-size:13px}
  .empty code{background:#eef0f6;padding:2px 6px;border-radius:5px;color:var(--ink)}
  .hint{font-size:12px;color:var(--faint);margin-top:10px}

  @media(max-width:900px){
    .side{position:static;width:100%;height:auto;flex-direction:row;align-items:center;overflow-x:auto}
    .brand{padding:0 12px 0 4px}.app{flex-direction:column}.side .foot{display:none}
    nav{flex-direction:row}.hero{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}
  }
</style>
</head>
<body>
<div class="app">
  <aside class="side">
    <div class="brand"><div class="mark">T</div><div><b>Ticket Router</b><span>AI triage console</span></div></div>
    <nav>
      <button class="nav active" data-v="classify"><span class="dot"></span>Classify</button>
      <button class="nav" data-v="overview"><span class="dot"></span>Overview</button>
      <button class="nav" data-v="diagnostics"><span class="dot"></span>Diagnostics</button>
      <button class="nav" data-v="tickets"><span class="dot"></span>Tickets</button>
    </nav>
    <div class="foot" id="foot">loading…</div>
  </aside>

  <div class="main">
    <div class="top">
      <h1 id="title">Classify a ticket</h1>
      <div class="meta" id="topmeta"></div>
    </div>

    <!-- CLASSIFY -->
    <section class="view active" id="view-classify">
      <div class="hero">
        <div class="card">
          <div class="eyebrow">Try it</div>
          <textarea id="simtext" placeholder="Paste or type a support ticket…"></textarea>
          <div class="chips" id="examples"></div>
          <button class="btn" id="simbtn" onclick="runSim()">Classify ticket</button>
        </div>
        <div class="card resultcard empty" id="simresult">
          Type a ticket and classify it to see the category, confidence, and routing decision.
        </div>
      </div>
    </section>

    <!-- OVERVIEW -->
    <section class="view" id="view-overview">
      <div class="section">
        <div class="eyebrow">At a glance</div>
        <div class="grid kpis" id="kpis"></div>
      </div>
      <div class="section">
        <div class="eyebrow">Accuracy by category</div>
        <div class="card" id="catbreak"><div class="empty">loading…</div></div>
      </div>
    </section>

    <!-- DIAGNOSTICS -->
    <section class="view" id="view-diagnostics">
      <div class="section">
        <div class="eyebrow">Precision and recall</div>
        <div class="card" id="prtable"><div class="empty">loading…</div></div>
      </div>
      <div class="section">
        <div class="eyebrow">Where the model gets confused</div>
        <div class="card" id="confusion"><div class="empty">loading…</div></div>
      </div>
      <div class="section">
        <div class="eyebrow">Is confidence trustworthy?</div>
        <div class="card" id="calibration"><div class="empty">loading…</div></div>
      </div>
    </section>

    <!-- TICKETS -->
    <section class="view" id="view-tickets">
      <div class="eyebrow">Classified tickets</div>
      <div style="margin-bottom:14px">
        <div class="seg">
          <button id="f-all" class="on" onclick="loadRows('all')">All</button>
          <button id="f-dis" onclick="loadRows('disagree')">Disagreements</button>
        </div>
      </div>
      <div class="card" style="padding:0;overflow:hidden" id="tablewrap"><div class="empty" style="padding:18px">loading…</div></div>
    </section>
  </div>
</div>

<script>
const EXAMPLES = [
  "Can't connect to the state VPN after the latest update and I have a meeting in 20 minutes.",
  "The shared network drive will not map for anyone on the Finance floor this morning.",
  "Requesting a replacement laptop, my current one will not power on at all.",
  "The permitting application is timing out whenever we run a search since about 8am.",
  "Please set up a new desk phone line for a new hire in Suite 300."
];
function pct(n){return n==null?"n/a":(n*100).toFixed(0)+"%";}
function esc(s){return (s==null?"":String(s)).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
function color(r){return r==null?"#cdd3df":r>=.75?"var(--good)":r>=.5?"var(--warn)":"var(--bad)";}

function gauge(conf){
  const r=64, c=2*Math.PI*r, off=c*(1-conf), col=color(conf);
  return `<div class="gauge"><svg width="160" height="160" viewBox="0 0 160 160">
    <circle cx="80" cy="80" r="${r}" fill="none" stroke="#eef0f6" stroke-width="13"/>
    <circle cx="80" cy="80" r="${r}" fill="none" stroke="${col}" stroke-width="13"
      stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="${off}"
      transform="rotate(-90 80 80)"/></svg>
    <div class="lab"><div class="v num">${pct(conf)}</div><div class="t">confidence</div></div></div>`;
}

/* nav */
document.querySelectorAll(".nav").forEach(b=>b.onclick=()=>setView(b.dataset.v));
const TITLES={classify:"Classify a ticket",overview:"Performance overview",diagnostics:"Model diagnostics",tickets:"Classified tickets"};
let loaded={};
function setView(v){
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.v===v));
  document.querySelectorAll(".view").forEach(s=>s.classList.toggle("active",s.id==="view-"+v));
  document.getElementById("title").textContent=TITLES[v];
  if(v==="overview"&&!loaded.stats){loaded.stats=1;loadStats();}
  if(v==="diagnostics"&&!loaded.eval){loaded.eval=1;loadEval();}
  if(v==="tickets"&&!loaded.rows){loaded.rows=1;loadRows("all");}
}

async function loadMeta(){
  const d=await (await fetch("/api/meta")).json();
  document.getElementById("topmeta").innerHTML=
    `<span class="pillchip">model <b>${esc(d.model)}</b></span>`+
    `<span class="pillchip">source <b>${esc((d.source||"").split(".").pop())}</b></span>`;
  document.getElementById("foot").innerHTML="reads from your<br>predictions table<br>·<br>simulator calls<br>Vertex AI live";
}

async function loadStats(){
  const d=await (await fetch("/api/stats")).json();
  const k=document.getElementById("kpis"), cb=document.getElementById("catbreak");
  if(!d.exists){
    k.innerHTML='<div class="card empty" style="grid-column:1/-1">No predictions yet. Run a batch to populate the table:<br><br><code>py scripts/run_batch.py --limit 150</code></div>';
    cb.innerHTML='<div class="empty">No data yet.</div>';return;
  }
  const o=d.overall, mr=o.scored?o.matches/o.scored:null;
  const card=(lab,big,sub)=>`<div class="card kpi"><div class="lab">${lab}</div><div class="big num">${big}</div><div class="sub">${sub}</div></div>`;
  k.innerHTML=
    card("Tickets classified",o.total,(o.failed||0)+" could not be classified")+
    card("Agreement with humans",mr==null?"—":pct(mr),(o.matches||0)+" of "+(o.scored||0)+" scored")+
    card("Avg confidence",o.avg_conf?pct(o.avg_conf):"—","model self-reported")+
    card("Held for triage",o.total?pct(1-(o.auto_routed||0)/o.total):"—","rest would auto-route");
  cb.innerHTML=d.by_category.map(c=>{
    const r=c.scored?c.matches/c.scored:null;
    return `<div class="row"><div>${esc(c.category)} <span class="faint num">(${c.n})</span></div>
      <div class="track"><div style="width:${r==null?0:(r*100).toFixed(0)}%;background:${color(r)}"></div></div>
      <div class="muted num">${pct(r)}</div></div>`;
  }).join("");
}

async function loadEval(){
  const d=await (await fetch("/api/evaluation")).json();
  const pr=document.getElementById("prtable"),cf=document.getElementById("confusion"),cal=document.getElementById("calibration");
  if(!d.exists||!d.per_category||!d.per_category.length){
    pr.innerHTML=cf.innerHTML=cal.innerHTML='<div class="empty">No scored data yet.</div>';return;
  }
  pr.innerHTML='<table><thead><tr><th>Category</th><th>Tickets</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead><tbody>'+
    d.per_category.map(c=>`<tr><td>${esc(c.category)}</td><td class="muted num">${c.support}</td>
      <td class="num">${pct(c.precision)}</td><td class="num">${pct(c.recall)}</td><td class="num">${pct(c.f1)}</td></tr>`).join("")+
    '</tbody></table><div class="hint">Precision: when the model says X, how often it is right. Recall: of real X tickets, how many it caught.</div>';
  cf.innerHTML=!d.top_confusions.length?'<div class="empty">No notable confusion.</div>':
    d.top_confusions.map(t=>`<div style="margin-bottom:10px"><b>${esc(t.category)}</b> <span class="faint">gets sent to</span> `+
      t.misses.map(x=>`<span class="badge b-warn">${esc(x.predicted)} ${pct(x.share)}</span>`).join(" ")+'</div>').join("");
  cal.innerHTML=d.calibration.map(b=>`<div class="row"><div>conf ${esc(b.band)} <span class="faint num">(${b.n})</span></div>
      <div class="track"><div style="width:${b.accuracy==null?0:(b.accuracy*100).toFixed(0)}%;background:${color(b.accuracy)}"></div></div>
      <div class="muted num">${pct(b.accuracy)}</div></div>`).join("")+
    '<div class="hint">If the bars rise top to bottom toward high confidence, the model knows when it is unsure and the confidence gate is meaningful.</div>';
}

async function loadRows(f){
  document.getElementById("f-all").classList.toggle("on",f==="all");
  document.getElementById("f-dis").classList.toggle("on",f==="disagree");
  const d=await (await fetch("/api/predictions?filter="+f+"&limit=100")).json();
  const w=document.getElementById("tablewrap");
  if(!d.exists||!d.rows.length){w.innerHTML='<div class="empty" style="padding:18px">No tickets to show.</div>';return;}
  w.innerHTML='<table><thead><tr><th>Number</th><th>Ticket</th><th>Predicted</th><th>Human</th><th>Match</th></tr></thead><tbody>'+
    d.rows.map(x=>{
      let b='<span class="badge b-na">no label</span>';
      if(x.category_match===true)b='<span class="badge b-good">agree</span>';
      else if(x.category_match===false)b='<span class="badge b-warn">differs</span>';
      return `<tr><td class="num">${esc(x.number)}</td><td>${esc((x.ticket_excerpt||"").slice(0,150))}</td>
        <td><b>${esc(x.predicted_category)||"—"}</b><div class="faint num">${x.confidence!=null?pct(x.confidence):""}</div></td>
        <td>${esc(x.human_category)||"—"}</td><td>${b}</td></tr>`;
    }).join("")+'</tbody></table>';
}

async function runSim(){
  const btn=document.getElementById("simbtn"),out=document.getElementById("simresult");
  const text=document.getElementById("simtext").value.trim();
  if(!text)return;
  btn.disabled=true;btn.textContent="Classifying…";
  try{
    const d=await (await fetch("/api/simulate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text})})).json();
    out.classList.remove("empty");
    if(d.error){out.innerHTML='<div class="empty">'+esc(d.error)+'</div>';return;}
    const routed=d.auto_routed?["auto","Would auto-route to its category queue"]:["hold","Held for a human to review"];
    out.innerHTML=gauge(d.confidence)+
      `<div class="bigcat">${esc(d.category)}</div>`+
      `<div class="metaline">priority ${esc(d.priority)} · ETA ${esc(d.eta)}</div>`+
      `<div class="tags">${d.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join("")}</div>`+
      `<div class="route ${routed[0]}">${routed[1]}</div>`+
      `<div class="reply"><b>Suggested reply:</b> ${esc(d.draft_response)}</div>`;
  }catch(e){
    out.classList.remove("empty");
    out.innerHTML='<div class="empty">Something went wrong calling the model. Check the terminal.</div>';
  }finally{btn.disabled=false;btn.textContent="Classify ticket";}
}

// init
document.getElementById("examples").innerHTML=EXAMPLES.map((e,i)=>`<span class="chip" onclick="document.getElementById('simtext').value=EXAMPLES[${i}]">${esc(e.slice(0,42))}…</span>`).join("");
loadMeta();
</script>
</body>
</html>
"""
