// The 3D module (Three.js, ~690 KB) is loaded on demand: after first paint for the background globe (desktop only),
// or when the Knowledge Galaxy is opened.
let scene3d = null;
const loadScene = () => (scene3d ??= import("/static/js/scene.js"));

const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const LEVEL = { 1: "All staff", 2: "Department", 3: "Management", 4: "Executive" };
const ICON = {
  assistant: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l1.9 4.6L18.5 9.5l-4.6 1.9L12 16l-1.9-4.6L5.5 9.5l4.6-1.9z"/><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/></svg>',
  documents: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/></svg>',
  galaxy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="2.5"/><ellipse cx="12" cy="12" rx="10" ry="4" transform="rotate(-25 12 12)"/><circle cx="19" cy="7" r="1"/><circle cx="5" cy="17" r="1"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v4h16v-4"/></svg>',
  insights: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
  users: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 010 7M18 14.8c1.8.8 3 2.6 3.5 5.2"/></svg>',
  audit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4z"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18"><path d="M5 12h13M13 6l6 6-6 6"/></svg>',
  dash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="8" height="10" rx="2"/><rect x="13" y="3" width="8" height="6" rx="2"/><rect x="13" y="11" width="8" height="10" rx="2"/><rect x="3" y="15" width="8" height="6" rx="2"/></svg>',
  report: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4M7 13l3-3 3 2 4-5"/></svg>',
  cloud: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M7 18a5 5 0 01-.6-9.96A6 6 0 0118 8.5a4.5 4.5 0 01-.5 9.5"/><path d="M12 12v9M9 15l3-3 3 3"/></svg>',
};

let me = null, bg = null, galaxy = null, docsCache = null;
const thread = [];

// ------------------------------------------------------------------ API
async function api(path, opts = {}) {
  const init = { credentials: "same-origin", ...opts, headers: { "X-HIS-Request": "1", ...(opts.headers || {}) } };
  if (opts.json !== undefined) { init.body = JSON.stringify(opts.json); init.headers["Content-Type"] = "application/json"; delete init.json; }
  const r = await fetch(path, init);
  if (r.status === 401 && path !== "/api/login" && path !== "/api/me") { showLogin(); throw new Error("Your session has expired - please sign in again."); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail; } catch {} throw new Error(typeof m === "string" ? m : "Request failed"); }
  return r.status === 204 ? null : r.json();
}

function toast(msg, kind = "ok") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`; t.textContent = msg; $("#toasts").append(t);
  setTimeout(() => { t.style.transition = "opacity .4s"; t.style.opacity = 0; setTimeout(() => t.remove(), 400); }, 3600);
}

const fmtDate = ts => new Date(ts * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
const initials = n => n.split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join("").toUpperCase();
const levelBadge = l => `<span class="badge lvl-${l}">${LEVEL[l]}</span>`;
const roleBadge = r => `<span class="badge role-${r}">${r[0].toUpperCase() + r.slice(1)}</span>`;
function countUp(el, to, dec = 0) {
  const t0 = performance.now(), from = 0;
  (function step(t) { const k = Math.min(1, (t - t0) / 900), e = 1 - Math.pow(1 - k, 3); el.textContent = (from + (to - from) * e).toLocaleString(undefined, { maximumFractionDigits: dec, minimumFractionDigits: dec }); if (k < 1) requestAnimationFrame(step); })(t0);
}
function tilt(el, amount = 6) {
  el.addEventListener("pointermove", e => { const r = el.getBoundingClientRect(), x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
    el.style.transform = `perspective(900px) rotateX(${-y * amount}deg) rotateY(${x * amount}deg) translateY(-2px)`; });
  el.addEventListener("pointerleave", () => { el.style.transform = ""; });
}

// ------------------------------------------------------------------ login
async function showLogin() {
  me = null; $("#app").classList.add("hidden"); $("#login").classList.remove("hidden"); bg?.setMode("login"); bg?.resume(); closeOverlays();
  try {
    const accts = await fetch("/api/demo-accounts").then(r => r.ok ? r.json() : null);
    if (accts) {
      $("#demo").classList.remove("hidden");
      $("#demo-list").innerHTML = accts.map((a, i) => `<button type="button" class="demo-item" data-i="${i}"><div class="avatar" style="width:30px;height:30px;font-size:11px;border-radius:9px">${esc(initials(a.full_name))}</div>
        <div class="who"><b>${esc(a.username)}</b><small>${esc(a.full_name)} · ${esc(a.title)}</small></div>${roleBadge(a.role)}</button>`).join("");
      $("#demo-list").onclick = e => { const b = e.target.closest(".demo-item"); if (!b) return; const a = accts[+b.dataset.i]; $("#u").value = a.username; $("#p").value = a.password; $("#login-btn").focus(); };
    }
  } catch {}
  setTimeout(() => $("#u").focus(), 300);
}
const card = $(".card-login");
$("#login").addEventListener("pointermove", e => { if (innerWidth < 980) return; const x = e.clientX / innerWidth - .5, y = e.clientY / innerHeight - .5; card.style.transform = `rotateY(${x * -3}deg) rotateX(${y * 3}deg)`; });
$("#login-form").addEventListener("submit", async e => {
  e.preventDefault();
  const btn = $("#login-btn"); btn.disabled = true; btn.textContent = "Verifying…"; $("#login-error").textContent = "";
  try { me = await api("/api/login", { method: "POST", json: { username: $("#u").value, password: $("#p").value } }); $("#p").value = ""; enterApp(); }
  catch (err) { $("#login-error").textContent = err.message; card.animate([{ transform: "translateX(0)" }, { transform: "translateX(-8px)" }, { transform: "translateX(8px)" }, { transform: "translateX(0)" }], { duration: 300 }); }
  finally { btn.disabled = false; btn.textContent = "Sign in securely"; }
});
$("#logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); thread.length = 0; docsCache = null; showLogin(); });

// ------------------------------------------------------------------ app shell
const VIEWS = {
  assistant: { title: "AI Assistant", sub: "Ask anything about the documents you are cleared to see", icon: "assistant", render: renderAssistant },
  documents: { title: "Document Library", sub: "Browse, preview and download company documents", icon: "documents", render: renderDocuments },
  galaxy: { title: "Knowledge Galaxy", sub: "Your accessible documents in 3D, clustered by department", icon: "galaxy", render: renderGalaxy },
  upload: { title: "Upload", sub: "Add a document - it is parsed, classified and searchable within seconds", icon: "upload", render: renderUpload },
  dashboards: { title: "Dashboards", sub: "Live charts from the company data your role can access", icon: "dash", render: renderDashboards },
  reports: { title: "Reports", sub: "One-click PowerPoint decks and Excel workbooks, built from source records", icon: "report", render: renderReports },
  insights: { title: "Insights", sub: "Your knowledge base at a glance", icon: "insights", render: renderInsights },
  users: { title: "Users & Access", sub: "Manage accounts, roles and clearance", icon: "users", render: renderUsers, admin: true },
  audit: { title: "Audit Log", sub: "Every question, download, upload and access decision", icon: "audit", render: renderAudit, admin: true },
};
let current = "assistant";

function enterApp() {
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden"); bg?.setMode("app");
  $("#me-avatar").textContent = initials(me.full_name); $("#me-name").textContent = me.full_name; $("#me-title").textContent = `${me.title} · ${me.department}`;
  $("#me-badges").innerHTML = `${roleBadge(me.role)} <span class="badge lvl-${Math.min(me.clearance, 4)}" title="Highest classification you can read">${esc(LEVEL[me.clearance] || "Department")} clearance</span>`;
  const nav = $("#nav"); nav.innerHTML = "";
  const groups = [["Workspace", ["assistant", "documents", "galaxy", "upload"]], ["Analytics", ["dashboards", "reports", "insights"]], ["Administration", ["users", "audit"]]];
  for (const [label, keys] of groups) {
    const ks = keys.filter(k => !VIEWS[k].admin || me.can_manage_users); if (!ks.length) continue;
    nav.insertAdjacentHTML("beforeend", `<div class="nav-label">${label}</div>`);
    for (const k of ks) nav.insertAdjacentHTML("beforeend", `<button data-v="${k}">${ICON[VIEWS[k].icon]}<span>${VIEWS[k].title}</span></button>`);
  }
  nav.onclick = e => { const b = e.target.closest("button[data-v]"); if (b) go(b.dataset.v); };
  go("assistant");
}

function go(v) {
  if (galaxy) { galaxy.dispose(); galaxy = null; }
  destroyCharts();
  current = v; const V = VIEWS[v];
  document.querySelectorAll("#nav button").forEach(b => b.classList.toggle("active", b.dataset.v === v));
  $("#view-title").textContent = V.title; $("#view-sub").textContent = V.sub; $("#view-actions").innerHTML = "";
  const view = $("#view"); view.className = "view"; view.innerHTML = ""; void view.offsetWidth; view.classList.add("view-enter");
  V.render(view);
  if (v === "galaxy") bg?.pause(); else bg?.resume();
}

// ------------------------------------------------------------------ assistant
async function renderAssistant(view) {
  view.innerHTML = `<div class="assistant">
    <div class="hero" id="hero"><div class="orb"></div><h2>${greeting()}, ${esc(me.full_name.split(" ")[0])}</h2>
      <p>I answer only from company documents you are cleared to read, and every sentence is verified and cited to its exact page.</p>
      <div class="suggestions" id="sugg"></div></div>
    <div class="thread" id="thread"></div>
    <div class="composer"><div class="composer-box"><textarea id="q" rows="1" placeholder="Ask about policies, numbers, people, products…" maxlength="600"></textarea>
      <button class="btn primary" id="send" aria-label="Ask">${ICON.send}</button></div>
      <div class="hint">Enter to send · Shift+Enter for a new line · Answers come only from your documents, never the internet</div></div></div>`;
  const q = $("#q");
  q.addEventListener("input", () => { q.style.height = "auto"; q.style.height = Math.min(160, q.scrollHeight) + "px"; });
  q.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q.value); } });
  $("#send").addEventListener("click", () => ask(q.value));
  for (const m of thread) appendMessage(m);
  $("#hero").classList.toggle("hidden", thread.length > 0);
  const s = await api("/api/suggestions").catch(() => []);
  $("#sugg").innerHTML = s.map(x => `<button class="suggestion">${esc(x)}</button>`).join("");
  $("#sugg").onclick = e => { const b = e.target.closest(".suggestion"); if (b) ask(b.textContent); };
  setTimeout(() => q.focus(), 200);
}
const greeting = () => { const h = new Date().getHours(); return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; };

async function ask(text) {
  text = text.trim(); if (text.length < 3) return;
  const q = $("#q"); q.value = ""; q.style.height = "auto"; $("#hero")?.classList.add("hidden");
  const um = { role: "user", text }; thread.push(um); appendMessage(um);
  const th = $("#thread");
  const wait = document.createElement("div"); wait.className = "panel msg-ai thinking";
  wait.innerHTML = `<div class="spinner"></div><div class="steps"><span class="step on">Searching</span><span class="step">Ranking evidence</span><span class="step">Writing answer</span><span class="step">Verifying claims</span></div>`;
  th.append(wait); wait.scrollIntoView({ behavior: "smooth", block: "end" });
  const steps = [...wait.querySelectorAll(".step")]; let i = 0;
  const timer = setInterval(() => { if (i < steps.length - 1) { steps[i].classList.replace("on", "done"); steps[++i].classList.add("on"); } }, 380);
  $("#send").disabled = true;
  try {
    const r = await api("/api/ask", { method: "POST", json: { question: text } });
    const am = { role: "ai", ...r }; thread.push(am); wait.remove(); appendMessage(am);
  } catch (err) { wait.remove(); toast(err.message, "bad"); }
  finally { clearInterval(timer); if ($("#send")) $("#send").disabled = false; }
}

function appendMessage(m) {
  const th = $("#thread"); if (!th) return;
  const el = document.createElement("div");
  if (m.role === "user") { el.className = "msg-user"; el.textContent = m.text; }
  else if (m.kind === "chart") {
    const r = m.chart;
    el.className = "panel msg-ai";
    el.innerHTML = `<div class="msg-head"><span class="ai-dot">${ICON.spark}</span><b>Halvorsen Assistant</b><span class="status verified">Chart · computed</span>
        <div class="cc-actions"><button data-x="pptx">PowerPoint</button><button data-x="xlsx">Excel</button><button data-x="pin">Pin</button></div></div>
      <div class="answer" style="font-size:15px"><b>${esc(r.title)}</b></div>
      <div class="chat-chart"><canvas></canvas></div>
      <div class="msg-meta"><span>📊 Computed from <b>${esc(r.source_title)}</b> (${r.rows_used.toLocaleString()} records) - no number written by AI</span>
        <span>${levelBadge(m.level || 1)}</span><span>${esc(m.insight)}</span><span>⏱ ${m.timings.total.toFixed(2)} s</span></div>`;
    th.append(el); drawChart(el.querySelector("canvas"), r);
    el.querySelector(".cc-actions").addEventListener("click", e => chartAction(e, r));
    el.scrollIntoView({ behavior: "smooth", block: "end" });
    return;
  }
  else {
    el.className = "panel msg-ai";
    const label = { verified: "Verified", partially_verified: "Partially verified", abstained: "Not in your documents", unverified_fallback: "Could not verify", no_evidence: "No evidence" }[m.status] || m.status;
    const answer = esc(m.answer_raw).replace(/\[S(\d+)\]/g, (x, n) => { const s = m.sources[n - 1]; return s ? `<button class="cite" data-s="${n - 1}">${esc(s.title)} · ${s.doc_type === "csv" ? "row" : s.doc_type === "md" ? "§" : "p."} ${s.page}</button>` : ""; });
    const cited = new Set([...m.answer_raw.matchAll(/\[S(\d+)\]/g)].map(x => +x[1] - 1));
    const verified = (m.claims || []).filter(c => c.supported).length;
    el.innerHTML = `<div class="msg-head"><span class="ai-dot">${ICON.spark}</span><b>Halvorsen Assistant</b><span class="status ${esc(m.status)}">${esc(label)}</span></div>
      <div class="answer">${answer}</div>
      ${m.sources.length && m.status !== "abstained" ? `<div class="sources">${m.sources.map((s, i) => cited.has(i) ? `<button class="source" data-s="${i}"><span class="n">S${i + 1}</span>
        <span class="t"><b>${esc(s.title)}</b><small>${esc(s.section)} · ${s.doc_type === "csv" ? "row" : s.doc_type === "md" ? "section" : "page"} ${s.page}</small></span>${levelBadge(s.level)}</button>` : "").join("")}</div>` : ""}
      <div class="msg-meta"><span>⏱ ${m.timings.total.toFixed(2)} s</span><span>${m.sources.length} passage(s) considered</span>
        ${m.claims?.length ? `<span>✓ ${verified}/${m.claims.length} claim(s) verified by NLI</span>` : ""}${m.regenerations ? `<span>↻ regenerated ${m.regenerations}×</span>` : ""}</div>`;
    el.addEventListener("click", e => { const b = e.target.closest("[data-s]"); if (b) openSource(m, +b.dataset.s); });
  }
  th.append(el); el.scrollIntoView({ behavior: "smooth", block: "end" });
}

function openSource(m, i) {
  const s = m.sources[i], claims = (m.claims || []).filter(c => c.citations.includes(i + 1));
  let text = esc(s.text);
  new Set(claims.flatMap(c => c.claim.match(/\d[\d,.]*\d|\d/g) || [])).forEach(v => { text = text.split(esc(v)).join(`<mark>${esc(v)}</mark>`); });
  openDrawer(`<div class="drawer-head"><div><div class="muted" style="font-size:12px">Source S${i + 1}</div><h2>${esc(s.title)}</h2>
    <div class="doc-meta">${levelBadge(s.level)} ${s.departments.map(d => `<span class="chip">${esc(d)}</span>`).join(" ")}
    <span class="chip">${s.doc_type === "csv" ? "row" : s.doc_type === "md" ? "section" : "page"} ${s.page}</span></div></div><button class="x" data-close>×</button></div>
    ${claims.length ? `<p class="muted">Supports: ${claims.map(c => `“${esc(c.claim)}”`).join(" ")}</p>` : ""}
    <pre>${text}</pre>${s.doc_type === "pdf" ? `<img alt="Page ${s.page} of ${esc(s.title)}" src="/api/documents/${encodeURIComponent(s.doc)}/page/${s.page}.png">` : ""}
    <p><a class="btn sm" href="/api/documents/${encodeURIComponent(s.doc)}/download">Download original</a></p>`);
}

// ------------------------------------------------------------------ overlays
function openDrawer(html) { $("#drawer").innerHTML = html; $("#drawer").classList.add("open"); $("#scrim").classList.add("open"); }
function openModal(html, wide = false) { const m = $("#modal"); m.innerHTML = html; m.classList.toggle("wide", wide); m.classList.add("open"); $("#scrim").classList.add("open"); }
function closeOverlays() { $("#drawer").classList.remove("open"); $("#modal").classList.remove("open"); $("#scrim").classList.remove("open"); }
$("#scrim").addEventListener("click", closeOverlays);
document.addEventListener("click", e => { if (e.target.closest("[data-close]")) closeOverlays(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeOverlays(); });

// ------------------------------------------------------------------ documents
async function loadDocs(force = false) { if (!docsCache || force) docsCache = await api("/api/documents"); return docsCache; }

async function renderDocuments(view) {
  view.innerHTML = `<div class="toolbar"><input class="input search" id="dq" placeholder="Search titles, owners, descriptions…">
    <select class="input" id="dd"><option value="">All departments</option></select>
    <div class="seg" id="dl"><button class="on" data-l="0">All</button><button data-l="1">All staff</button><button data-l="2">Department</button><button data-l="3">Management</button><button data-l="4">Executive</button></div></div>
    <div id="dcount" class="muted" style="margin-bottom:10px"></div><div class="grid" id="dgrid"></div>`;
  const docs = await loadDocs();
  const depts = [...new Set(docs.flatMap(d => d.departments))].sort();
  $("#dd").insertAdjacentHTML("beforeend", depts.map(d => `<option>${esc(d)}</option>`).join(""));
  let lvl = 0;
  const draw = () => {
    const q = $("#dq").value.toLowerCase(), dep = $("#dd").value;
    const list = docs.filter(d => (!lvl || d.level === lvl) && (!dep || d.departments.includes(dep)) && (!q || `${d.title} ${d.description} ${d.owner} ${d.category}`.toLowerCase().includes(q)));
    $("#dcount").textContent = `${list.length} of ${docs.length} documents you can access`;
    $("#dgrid").className = "grid stagger";
    $("#dgrid").innerHTML = list.length ? list.map(d => `<article class="panel doc" data-doc="${esc(d.doc)}">
      <div class="doc-top"><div class="ftype ${esc(d.type)}">${esc(d.type)}</div><div><h3>${esc(d.title)}</h3><div class="doc-meta" style="margin-top:6px">${levelBadge(d.level)}${d.departments.map(x => `<span class="chip">${esc(x)}</span>`).join("")}</div></div></div>
      <p>${esc(d.description)}</p>
      <div class="doc-foot"><span>${esc(d.owner)}</span>·<span>${esc(d.created)}</span><span class="spacer"></span><span title="Indexed passages">${d.chunks}</span></div>
      <div style="display:flex;gap:6px"><button class="btn sm" data-a="preview">Preview</button><a class="btn sm ghost" href="/api/documents/${encodeURIComponent(d.doc)}/download">Download</a>
        ${d.can_delete && d.source === "upload" ? `<button class="btn sm ghost danger" data-a="delete">Delete</button>` : ""}</div></article>`).join("") : `<div class="empty">No documents match.</div>`;
    document.querySelectorAll(".doc").forEach(el => tilt(el, 4));
  };
  $("#dq").addEventListener("input", draw); $("#dd").addEventListener("change", draw);
  $("#dl").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; lvl = +b.dataset.l; $("#dl").querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b)); draw(); });
  $("#dgrid").addEventListener("click", async e => {
    const b = e.target.closest("[data-a]"); if (!b) return; const doc = docs.find(d => d.doc === b.closest(".doc").dataset.doc);
    if (b.dataset.a === "preview") previewDoc(doc);
    if (b.dataset.a === "delete" && confirm(`Delete "${doc.title}"? It will be removed from search immediately.`)) {
      try { await api(`/api/documents/${encodeURIComponent(doc.doc)}`, { method: "DELETE" }); toast("Document deleted"); await loadDocs(true); go("documents"); } catch (err) { toast(err.message, "bad"); }
    }
  });
  draw();
}

async function previewDoc(d) {
  openModal(`<div class="drawer-head"><div><h2>${esc(d.title)}</h2><div class="doc-meta">${levelBadge(d.level)} <span class="chip">${esc(d.type)}</span> <span class="chip">${esc(d.owner)}</span></div></div><button class="x" data-close>×</button></div><div class="spinner"></div>`, true);
  try {
    const p = await api(`/api/documents/${encodeURIComponent(d.doc)}/preview`);
    const body = p.kind === "table"
      ? `<div class="table-wrap panel" style="max-height:60vh"><table><thead><tr>${p.rows[0].map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${p.rows.slice(1).map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div><p class="muted">Showing ${p.rows.length - 1} of ${p.total_rows.toLocaleString()} rows.</p>`
      : `<pre style="white-space:pre-wrap;max-height:62vh;overflow:auto;font:12.5px/1.6 var(--mono);padding:16px;border-radius:12px;background:rgba(0,0,0,.3);border:1px solid var(--line)">${esc(p.text)}</pre>`;
    $("#modal .spinner").outerHTML = body + `<p><a class="btn sm primary" href="/api/documents/${encodeURIComponent(d.doc)}/download">Download original</a></p>`;
  } catch (err) { toast(err.message, "bad"); closeOverlays(); }
}

// ------------------------------------------------------------------ galaxy
async function renderGalaxy(view) {
  view.innerHTML = `<div class="panel galaxy-wrap"><canvas id="galaxy"></canvas><div class="panel galaxy-legend" id="glegend"></div>
    <div class="panel galaxy-help">Drag to rotate · scroll to zoom · click a star to preview</div><div class="panel galaxy-tip hidden" id="gtip"></div></div>`;
  const [docs, { createGalaxy, DEPT_COLORS }] = await Promise.all([loadDocs(), loadScene()]);
  const depts = [...new Set(docs.map(d => d.departments[0]))];
  $("#glegend").innerHTML = depts.map(d => `<div><i style="background:${DEPT_COLORS[d]}"></i>${esc(d)} (${docs.filter(x => x.departments[0] === d).length})</div>`).join("") +
    `<div class="muted" style="margin-top:6px">Ring: <span class="lvl-3">Management</span> / <span class="lvl-4">Executive</span></div>`;
  const tip = $("#gtip");
  galaxy = createGalaxy($("#galaxy"), docs, {
    onHover: (d, x, y) => { if (!d) return tip.classList.add("hidden");
      tip.classList.remove("hidden"); tip.style.left = x + "px"; tip.style.top = y + "px";
      tip.innerHTML = `<b>${esc(d.title)}</b><div style="margin:6px 0">${levelBadge(d.level)}</div><span class="muted">${esc(d.description)}</span>`; },
    onClick: d => previewDoc(d),
  });
}

// ------------------------------------------------------------------ upload
async function renderUpload(view) {
  const meta = await api("/api/meta");
  let file = null, depts = new Set([me.department]), level = 2;
  view.innerHTML = `<div class="upload stagger">
    <label class="drop" id="drop">${ICON.cloud}<b>Drop a document here or click to browse</b><span class="muted">PDF, DOCX, CSV or Markdown · up to 25 MB</span>
      <input type="file" id="file" accept=".pdf,.docx,.csv,.md"></label>
    <div class="panel form-grid">
      <label class="field full"><span>Title</span><input class="input" id="ut" maxlength="160" placeholder="e.g. Q3 Supplier Review"></label>
      <div class="field full"><span>Classification - who can read it</span><div class="levels" id="ul">${[1, 2, 3, 4].map(l => `<button type="button" class="lvl-${l}" data-l="${l}" ${me.upload_levels.includes(l) ? "" : "disabled"}><b>${LEVEL[l]}</b><small>${{ 1: "Everyone", 2: "Selected departments", 3: "Managers & executives", 4: "Executives only" }[l]}</small></button>`).join("")}</div></div>
      <div class="field full"><span>Departments</span><div class="dept-picks" id="ud">${meta.departments.map(d => `<button type="button" data-d="${esc(d)}">${esc(d)}</button>`).join("")}</div></div>
      <label class="field"><span>Category</span><input class="input" id="uc" maxlength="60" placeholder="e.g. Report"></label>
      <label class="field"><span>Description</span><input class="input" id="ux" maxlength="400" placeholder="One line summary"></label>
      <div class="full"><div class="progress hidden" id="up"><i></i></div></div>
      <div class="full" style="display:flex;justify-content:flex-end"><button class="btn primary" id="ugo">Upload & index</button></div></div></div>`;
  const sync = () => {
    $("#ul").querySelectorAll("button").forEach(b => b.classList.toggle("on", +b.dataset.l === level));
    $("#ud").querySelectorAll("button").forEach(b => b.classList.toggle("on", depts.has(b.dataset.d)));
  };
  $("#ul").onclick = e => { const b = e.target.closest("button:not(:disabled)"); if (b) { level = +b.dataset.l; sync(); } };
  $("#ud").onclick = e => { const b = e.target.closest("button"); if (!b) return; depts.has(b.dataset.d) ? depts.delete(b.dataset.d) : depts.add(b.dataset.d); sync(); };
  const setFile = f => { file = f; if (!f) return; $("#drop b").textContent = f.name; $("#drop .muted").textContent = `${(f.size / 1024).toFixed(0)} KB · ready`; if (!$("#ut").value) $("#ut").value = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " "); };
  $("#file").addEventListener("change", e => setFile(e.target.files[0]));
  const drop = $("#drop");
  ["dragenter", "dragover"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => setFile(e.dataTransfer.files[0]));
  $("#ugo").addEventListener("click", async () => {
    if (!file) return toast("Choose a file first", "bad");
    if (!$("#ut").value.trim()) return toast("Give the document a title", "bad");
    const fd = new FormData();
    fd.append("file", file); fd.append("title", $("#ut").value); fd.append("level", level); fd.append("departments", JSON.stringify([...depts]));
    fd.append("category", $("#uc").value || "Uploaded"); fd.append("description", $("#ux").value);
    const bar = $("#up"); bar.classList.remove("hidden"); bar.firstElementChild.style.width = "35%"; $("#ugo").disabled = true; $("#ugo").textContent = "Parsing & embedding…";
    try {
      const r = await api("/api/upload", { method: "POST", body: fd });
      bar.firstElementChild.style.width = "100%"; docsCache = null;
      toast(`“${r.title}” indexed - ${r.chunks} passages, ${r.level_label}`);
      setTimeout(() => go("documents"), 700);
    } catch (err) { toast(err.message, "bad"); bar.classList.add("hidden"); }
    finally { $("#ugo").disabled = false; $("#ugo").textContent = "Upload & index"; }
  });
  sync();
}

// ------------------------------------------------------------------ insights
async function renderInsights(view) {
  const s = await api("/api/stats");
  const kpis = [["Documents you can access", s.visible_documents, `of ${s.total_documents} in the company`], ["Indexed passages", s.visible_chunks, "searchable by the assistant"],
    ["Your questions", s.my_questions, s.my_questions ? `avg ${s.my_avg_latency}s per answer` : "ask your first question"]];
  if (s.org_questions !== undefined) kpis.push(["Company questions", s.org_questions, s.org_verified_rate != null ? `${(s.org_verified_rate * 100).toFixed(0)}% fully verified` : "—"], ["Active accounts", s.active_users, `avg answer ${s.org_avg_latency}s`]);
  const max = Math.max(...Object.values(s.by_department));
  const levels = Object.entries(s.by_level), total = levels.reduce((a, [, v]) => a + v, 0) || 1, colors = ["#3fcf8e", "#5b8cff", "#f2b84b", "#ff6b7d"];
  let acc = 0;
  const arcs = levels.map(([k, v], i) => { const a0 = acc / total * Math.PI * 2, a1 = (acc += v) / total * Math.PI * 2; if (!v) return "";
    const large = a1 - a0 > Math.PI ? 1 : 0, p = (a) => [70 + 56 * Math.sin(a), 70 - 56 * Math.cos(a)];
    const [x0, y0] = p(a0), [x1, y1] = p(a1 - 0.0001);
    return `<path d="M${x0} ${y0} A56 56 0 ${large} 1 ${x1} ${y1}" stroke="${colors[i]}" stroke-width="18" fill="none" stroke-linecap="butt" style="stroke-dasharray:400;stroke-dashoffset:400;animation:dash 1.2s ${i * .15}s var(--ease) forwards"/>`; }).join("");
  view.innerHTML = `<style>@keyframes dash{to{stroke-dashoffset:0}}</style>
    <div class="kpis stagger">${kpis.map(([l, v, sub]) => `<div class="panel kpi"><small>${esc(l)}</small><b data-n="${v}">0</b><span>${esc(sub)}</span></div>`).join("")}</div>
    <div class="charts stagger"><div class="panel chart"><h3>Accessible documents by department</h3><div class="bars">${Object.entries(s.by_department).map(([d, n]) =>
      `<div class="bar-row"><span>${esc(d)}</span><div class="bar"><i data-w="${n / max * 100}"></i></div><b>${n}</b></div>`).join("")}</div></div>
      <div class="panel chart"><h3>By classification</h3><div class="donut-wrap"><svg width="140" height="140" viewBox="0 0 140 140">${arcs}<text x="70" y="66" text-anchor="middle" fill="#e8eefc" font-size="26" font-weight="700">${total}</text><text x="70" y="86" text-anchor="middle" fill="#7584a6" font-size="11">documents</text></svg>
        <div class="donut-legend">${levels.map(([k, v], i) => `<div><i style="background:${colors[i]}"></i>${esc(k)} · <b>${v}</b></div>`).join("")}</div></div></div></div>
    <div class="panel recent"><h3>Recently added</h3>${s.recent.map(r => `<div class="recent-row"><span class="t">${esc(r.title)}</span>${levelBadge(r.level)}<span class="muted">${esc(r.owner)}</span><span class="muted">${esc(r.created)}</span></div>`).join("")}</div>`;
  view.querySelectorAll("[data-n]").forEach(el => countUp(el, +el.dataset.n));
  requestAnimationFrame(() => setTimeout(() => view.querySelectorAll("[data-w]").forEach(el => el.style.width = el.dataset.w + "%"), 80));
  view.querySelectorAll(".kpi").forEach(el => tilt(el, 6));
}

// ------------------------------------------------------------------ users
async function renderUsers(view) {
  const [users, meta] = await Promise.all([api("/api/admin/users"), api("/api/meta")]);
  $("#view-actions").innerHTML = `<button class="btn primary" id="newu">+ New user</button>`;
  $("#newu").onclick = () => {
    openModal(`<h2>Create user</h2><form id="uf" class="form-grid" style="padding:0">
      <label class="field"><span>Username</span><input class="input" name="username" pattern="[a-z0-9._-]{3,32}" required placeholder="firstname.lastname"></label>
      <label class="field"><span>Full name</span><input class="input" name="full_name" required></label>
      <label class="field"><span>Job title</span><input class="input" name="title" required></label>
      <label class="field"><span>Department</span><select class="input" name="department">${meta.departments.map(d => `<option>${esc(d)}</option>`).join("")}</select></label>
      <label class="field"><span>Role</span><select class="input" name="role"><option>employee</option><option>manager</option><option>admin</option>${me.role === "executive" ? "<option>executive</option>" : ""}</select></label>
      <label class="field"><span>Initial password</span><input class="input" name="password" type="password" minlength="8" required></label>
      <div class="full" style="display:flex;gap:8px;justify-content:flex-end"><button type="button" class="btn ghost" data-close>Cancel</button><button class="btn primary">Create</button></div></form>`);
    $("#uf").onsubmit = async e => { e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
      try { await api("/api/admin/users", { method: "POST", json: f }); toast(`User ${f.username} created`); closeOverlays(); go("users"); } catch (err) { toast(err.message, "bad"); } };
  };
  view.innerHTML = `<div class="panel table-wrap"><table><thead><tr><th>User</th><th>Department</th><th>Role</th><th>Last sign-in</th><th>Active</th><th></th></tr></thead><tbody>
    ${users.map(u => `<tr data-u="${esc(u.username)}"><td><div style="display:flex;gap:10px;align-items:center"><div class="avatar" style="width:32px;height:32px;font-size:12px;border-radius:10px">${esc(initials(u.full_name))}</div>
      <div><b>${esc(u.full_name)}</b><div class="muted mono" style="font-size:12px">${esc(u.username)} · ${esc(u.title)}</div></div></div></td><td>${esc(u.department)}</td><td>${roleBadge(u.role)}</td>
      <td class="muted">${u.last_login ? fmtDate(u.last_login) : "never"}</td><td><button class="switch ${u.active ? "on" : ""}" data-a="toggle" aria-label="Active"></button></td>
      <td><button class="btn sm ghost" data-a="reset">Reset password</button></td></tr>`).join("")}</tbody></table></div>`;
  view.querySelector("tbody").addEventListener("click", async e => {
    const b = e.target.closest("[data-a]"); if (!b) return; const u = b.closest("tr").dataset.u;
    try {
      if (b.dataset.a === "toggle") { const on = !b.classList.contains("on"); await api(`/api/admin/users/${encodeURIComponent(u)}`, { method: "PATCH", json: { active: on } }); b.classList.toggle("on", on); toast(`${u} ${on ? "activated" : "deactivated"}`); }
      if (b.dataset.a === "reset") { const pw = prompt(`New password for ${u} (min 8 characters)`); if (pw) { await api(`/api/admin/users/${encodeURIComponent(u)}`, { method: "PATCH", json: { password: pw } }); toast(`Password reset for ${u}`); } }
    } catch (err) { toast(err.message, "bad"); }
  });
}

// ------------------------------------------------------------------ audit
async function renderAudit(view) {
  const a = await api("/api/admin/activity");
  let tab = "queries";
  const draw = () => {
    view.innerHTML = `<div class="tabs seg"><button data-t="queries" class="${tab === "queries" ? "on" : ""}">Questions (${a.queries.length})</button><button data-t="activity" class="${tab === "activity" ? "on" : ""}">Activity (${a.activity.length})</button></div>
      <div class="panel table-wrap view-enter">${tab === "queries"
        ? `<table><thead><tr><th>Time</th><th>User</th><th>Question</th><th>Outcome</th><th>Latency</th></tr></thead><tbody>${a.queries.map(q => `<tr><td class="muted">${fmtDate(q.ts)}</td><td class="mono">${esc(q.username)}</td><td>${esc(q.question)}</td><td><span class="status ${esc(q.status)}">${esc(q.status.replace(/_/g, " "))}</span></td><td class="muted">${q.latency.toFixed(2)} s</td></tr>`).join("")}</tbody></table>`
        : `<table><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Detail</th></tr></thead><tbody>${a.activity.map(x => `<tr><td class="muted">${fmtDate(x.ts)}</td><td class="mono">${esc(x.username)}</td><td><span class="chip ${x.action.includes("denied") || x.action.includes("blocked") ? "lvl-4" : ""}">${esc(x.action)}</span></td><td class="muted">${esc(x.detail)}</td></tr>`).join("")}</tbody></table>`}</div>`;
    view.querySelector(".tabs").onclick = e => { const b = e.target.closest("button"); if (b) { tab = b.dataset.t; draw(); } };
  };
  draw();
}

// ------------------------------------------------------------------ charts
const PALETTE = ["#3fd6c4", "#5b8cff", "#f2b84b", "#ff6b7d", "#b48cff", "#3fcf8e", "#64d2ff", "#ffa45b", "#9fb3d9", "#d4f06b"];
let charts = [];
function destroyCharts() { charts.forEach(c => c.destroy()); charts = []; }
const fmtNum = (v, unit) => {
  if (unit === "%") return v.toFixed(1) + "%";
  if (unit === "EUR m") return "€" + v.toLocaleString(undefined, { maximumFractionDigits: 1 }) + "m";
  if (unit === "EUR") return "€" + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return v.toLocaleString(undefined, { maximumFractionDigits: 1 });
};
function drawChart(canvas, r) {
  if (!window.Chart) return;
  const kind = r.spec.chart, circ = kind === "pie" || kind === "doughnut";
  if (kind === "table") {
    canvas.parentElement.innerHTML = `<div class="chart-table"><table><thead><tr><th>${esc(r.spec.x || "")}</th>${r.datasets.map(d => `<th>${esc(d.label)}</th>`).join("")}</tr></thead>
      <tbody>${r.labels.map((l, i) => `<tr><td>${esc(l)}</td>${r.datasets.map(d => `<td>${fmtNum(d.data[i], r.unit)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    return;
  }
  const ctx = canvas.getContext("2d");
  const datasets = r.datasets.map((d, i) => {
    const c = PALETTE[i % PALETTE.length];
    if (circ) return { label: d.label, data: d.data, backgroundColor: r.labels.map((_, k) => PALETTE[k % PALETTE.length]), borderColor: "#0a1020", borderWidth: 2, hoverOffset: 10 };
    if (kind === "line") {
      const g = ctx.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 300); g.addColorStop(0, c + "55"); g.addColorStop(1, c + "00");
      return { label: d.label, data: d.data, borderColor: c, backgroundColor: r.datasets.length === 1 ? g : c, fill: r.datasets.length === 1, tension: .35, pointRadius: 2.5, pointHoverRadius: 5, borderWidth: 2.2 };
    }
    return { label: d.label, data: d.data, backgroundColor: c + "cc", hoverBackgroundColor: c, borderRadius: 6, maxBarThickness: 46 };
  });
  const grid = { color: "rgba(140,170,230,.09)" }, ticks = { color: "#8d9abb", font: { size: 11 } };
  const chart = new Chart(canvas, {
    type: circ ? kind : (kind === "line" ? "line" : "bar"),
    data: { labels: r.labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, indexAxis: kind === "hbar" ? "y" : "x",
      animation: { duration: 1000, easing: "easeOutQuart" }, cutout: kind === "doughnut" ? "62%" : undefined,
      plugins: {
        legend: { display: circ || r.datasets.length > 1, position: circ ? "right" : "bottom", labels: { color: "#aab6d3", boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { size: 11 } } },
        tooltip: { backgroundColor: "rgba(10,16,32,.95)", borderColor: "rgba(140,170,230,.3)", borderWidth: 1, padding: 10,
          callbacks: { label: c => ` ${c.dataset.label}: ${fmtNum(c.parsed.y ?? c.parsed.x ?? c.parsed, r.unit)}` } },
      },
      scales: circ ? {} : {
        x: { grid: kind === "hbar" ? grid : { display: false }, ticks: { ...ticks, maxRotation: 0, autoSkip: true, callback(v) { const l = this.getLabelForValue ? this.getLabelForValue(v) : v; return kind === "hbar" ? fmtNum(+v, r.unit) : (String(l).length > 14 ? String(l).slice(0, 13) + "…" : l); } } },
        y: { grid: kind === "hbar" ? { display: false } : grid, ticks: { ...ticks, callback(v) { if (kind === "hbar") { const l = this.getLabelForValue(v); return String(l).length > 22 ? String(l).slice(0, 21) + "…" : l; } return fmtNum(+v, r.unit); } }, beginAtZero: true },
      },
    },
  });
  charts.push(chart);
}
async function download(path, opts, fallbackName) {
  const res = await fetch(path, { credentials: "same-origin", ...opts, headers: { "X-HIS-Request": "1", "Content-Type": "application/json", ...(opts?.headers || {}) } });
  if (!res.ok) { let m = res.statusText; try { m = (await res.json()).detail; } catch {} throw new Error(m); }
  const name = (res.headers.get("content-disposition") || "").match(/filename="([^"]+)"/)?.[1] || fallbackName;
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: name }); document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
  return name;
}
async function chartAction(e, r) {
  const b = e.target.closest("[data-x]"); if (!b) return;
  const x = b.dataset.x, body = JSON.stringify({ spec: { ...r.spec, title: r.title } });
  try {
    if (x === "pptx" || x === "xlsx") { b.disabled = true; const n = await download(`/api/export/chart.${x}`, { method: "POST", body }, `chart.${x}`); toast(`Downloaded ${n}`); }
    if (x === "pin") { await api("/api/widgets", { method: "POST", json: { spec: { ...r.spec, title: r.title } } }); toast("Pinned to My charts"); }
    if (x === "unpin") { await api(`/api/widgets/${r.widget_id}`, { method: "DELETE" }); toast("Removed from My charts"); b.closest(".chart-card").remove(); }
  } catch (err) { toast(err.message, "bad"); } finally { b.disabled = false; }
}
function chartCard(r, pinned = false) {
  const el = document.createElement("div");
  el.className = "panel chart-card";
  el.innerHTML = `<div class="cc-head"><div><h3>${esc(r.title)}</h3><small>${esc(r.source_title)} · ${r.rows_used.toLocaleString()} records</small></div>
    <div class="cc-actions"><button data-x="pptx" title="Export as PowerPoint slide">PPT</button><button data-x="xlsx" title="Export data to Excel">Excel</button>
    ${pinned ? `<button data-x="unpin">Remove</button>` : `<button data-x="pin" title="Add to My charts">Pin</button>`}</div></div>
    <div class="cc-body"><canvas></canvas></div>${r.insight ? `<div class="cc-insight">${esc(r.insight)}</div>` : ""}`;
  el.querySelector(".cc-actions").addEventListener("click", e => chartAction(e, r));
  return el;
}
function insightOf(r) {
  const d = r.datasets.length > 1 && r.spec.series ? r.labels.map((_, i) => r.datasets.reduce((a, ds) => a + (ds.data[i] || 0), 0)) : (r.datasets[0]?.data || []);
  if (!d.length) return "";
  const tag = r.datasets.length > 1 && r.spec.series ? " total" : "";
  if (r.spec.chart === "line" && d.length > 1 && d[0]) { const ch = (d.at(-1) - d[0]) / Math.abs(d[0]) * 100; return `${r.labels.at(-1)}${tag}: ${fmtNum(d.at(-1), r.unit)} (${ch >= 0 ? "+" : ""}${ch.toFixed(0)}% vs ${r.labels[0]})`; }
  const i = d.indexOf(Math.max(...d)), tot = d.reduce((a, b) => a + b, 0);
  return `Highest: ${r.labels[i]} at ${fmtNum(d[i], r.unit)}${["sum", "count"].includes(r.spec.agg) && tot && !r.spec.top ? ` (${(d[i] / tot * 100).toFixed(0)}% of total)` : ""}`;
}

// ------------------------------------------------------------------ dashboards
let dashTab = null;
async function renderDashboards(view) {
  $("#view-actions").innerHTML = `<button class="btn primary" id="build">+ Build a chart</button>`;
  $("#build").onclick = openBuilder;
  view.innerHTML = `<div class="kpis stagger" id="dk"></div><div class="dash-tabs" id="dt"></div><div class="chart-grid stagger" id="dg"></div>`;
  const { tabs, kpis } = await api("/api/dashboard/tabs");
  $("#dk").innerHTML = kpis.map(k => `<div class="panel kpi"><small>${esc(k.label)}</small><b>${esc(k.display)}</b><span>${esc(k.source)}</span></div>`).join("");
  view.querySelectorAll(".kpi").forEach(el => tilt(el, 6));
  if (!dashTab || !tabs.includes(dashTab)) dashTab = tabs[1] || tabs[0];
  const drawTabs = () => { $("#dt").innerHTML = tabs.map(t => `<button class="${t === dashTab ? "on" : ""}">${esc(t)}</button>`).join(""); };
  drawTabs();
  $("#dt").onclick = e => { const b = e.target.closest("button"); if (!b) return; dashTab = b.textContent; drawTabs(); loadTab(); };
  async function loadTab() {
    destroyCharts();
    const grid = $("#dg"); grid.innerHTML = `<div class="spinner"></div>`;
    const list = await api(`/api/dashboard?tab=${encodeURIComponent(dashTab)}`);
    grid.innerHTML = ""; grid.className = "chart-grid stagger";
    if (!list.length) grid.innerHTML = `<div class="empty">${dashTab === "My charts" ? "No pinned charts yet - build one, or ask the assistant for a chart and press Pin." : "No charts available."}</div>`;
    for (const r of list) { r.insight = insightOf(r); const card = chartCard(r, dashTab === "My charts"); grid.append(card); drawChart(card.querySelector("canvas"), r); }
  }
  loadTab();
}

async function openBuilder() {
  const cat = await api("/api/catalog");
  const names = Object.keys(cat);
  if (!names.length) return toast("No datasets available for your role", "bad");
  openModal(`<div class="drawer-head"><div><h2>Build a chart</h2><p class="muted" style="margin:0">Pick data you are cleared to see; numbers are computed from the source records.</p></div><button class="x" data-close>×</button></div>
    <div class="builder"><div>
      <label class="field"><span>Dataset</span><select class="input" id="bds">${names.map(n => `<option value="${n}">${esc(cat[n].title)}</option>`).join("")}</select></label>
      <label class="field"><span>Group by</span><select class="input" id="bx"></select></label>
      <label class="field"><span>Split by (optional)</span><select class="input" id="bs"></select></label>
      <label class="field"><span>Measure</span><select class="input" id="bm"></select></label>
      <label class="field"><span>Aggregation</span><select class="input" id="ba"><option value="sum">Sum</option><option value="mean">Average</option><option value="count">Count</option><option value="max">Maximum</option><option value="min">Minimum</option></select></label>
      <label class="field"><span>Chart type</span><select class="input" id="bc"><option value="bar">Column</option><option value="hbar">Bar (horizontal)</option><option value="line">Line</option><option value="doughnut">Doughnut</option><option value="pie">Pie</option><option value="table">Table</option></select></label>
      <label class="field"><span>Show top N (optional)</span><input class="input" id="bt" type="number" min="1" max="50" placeholder="all"></label>
    </div><div><div class="panel preview"><canvas id="bp"></canvas></div><p class="muted" id="bi" style="font-size:12px"></p>
      <div style="display:flex;gap:8px;justify-content:flex-end"><button class="btn sm" data-b="pptx">PowerPoint</button><button class="btn sm" data-b="xlsx">Excel</button><button class="btn sm primary" data-b="pin">Pin to My charts</button></div></div></div>`, true);
  let current = null;
  const fill = () => {
    const c = cat[$("#bds").value];
    $("#bx").innerHTML = c.dims.map(d => `<option>${d}</option>`).join("");
    $("#bs").innerHTML = `<option value="">-</option>` + c.dims.map(d => `<option>${d}</option>`).join("");
    $("#bm").innerHTML = [...c.measures, "count"].map(m => `<option>${m}</option>`).join("");
    $("#ba").value = c.measures.length ? "sum" : "count";
  };
  const preview = async () => {
    const spec = { dataset: $("#bds").value, x: $("#bx").value, series: $("#bs").value || null, metric: $("#bm").value, agg: $("#bm").value === "count" ? "count" : $("#ba").value,
      chart: $("#bc").value, top: +$("#bt").value || null };
    try {
      destroyCharts(); const r = await api("/api/chart", { method: "POST", json: { spec } }); current = r;
      const box = $(".builder .preview"); box.innerHTML = `<canvas id="bp"></canvas>`; drawChart($("#bp"), r);
      $("#bi").textContent = `${r.title} · ${r.rows_used.toLocaleString()} records from ${r.source_doc} · ${insightOf(r)}`;
    } catch (err) { $("#bi").textContent = err.message; }
  };
  fill(); preview();
  $("#bds").onchange = () => { fill(); preview(); };
  ["#bx", "#bs", "#bm", "#ba", "#bc", "#bt"].forEach(id => $(id).addEventListener("change", preview));
  $("#modal").querySelector(".builder").addEventListener("click", async e => {
    const b = e.target.closest("[data-b]"); if (!b || !current) return;
    const fake = document.createElement("i"); fake.dataset.x = b.dataset.b;
    await chartAction({ target: fake }, current);
    if (b.dataset.b === "pin") { closeOverlays(); if (current_view() === "dashboards") { dashTab = "My charts"; go("dashboards"); } }
  });
}
const current_view = () => current;

// ------------------------------------------------------------------ reports
async function renderReports(view) {
  view.innerHTML = `<div class="report-grid stagger" id="rg"><div class="spinner"></div></div>`;
  const list = await api("/api/reports");
  $("#rg").innerHTML = list.map(r => `<article class="panel report">${r.recommended ? `<span class="rec">FOR YOU</span>` : ""}
    <div class="ricon">${ICON.report}</div><div><h3>${esc(r.title)}</h3></div><p>${esc(r.description)}</p>
    <div class="doc-meta">${levelBadge(r.level)}<span class="chip">${r.charts} charts</span><span class="chip">KPI slide</span><span class="chip">Sources slide</span></div>
    <div class="actions"><button class="btn sm primary" data-r="${r.id}" data-k="pptx">Download PowerPoint</button><button class="btn sm" data-r="${r.id}" data-k="xlsx">Excel data</button></div></article>`).join("")
    || `<div class="empty">No reports available for your role.</div>`;
  view.querySelectorAll(".report").forEach(el => tilt(el, 4));
  $("#rg").onclick = async e => {
    const b = e.target.closest("[data-r]"); if (!b) return;
    const label = b.textContent; b.disabled = true; b.textContent = "Building…";
    try { const n = await download(`/api/reports/${b.dataset.r}.${b.dataset.k}`, { method: "GET" }, `report.${b.dataset.k}`); toast(`Downloaded ${n}`); }
    catch (err) { toast(err.message, "bad"); } finally { b.disabled = false; b.textContent = label; }
  };
}

// ------------------------------------------------------------------ boot
(async function boot() {
  try { me = await api("/api/me"); enterApp(); } catch { showLogin(); }
  setTimeout(() => $("#boot").classList.add("gone"), 150);
  const light = matchMedia("(max-width: 720px), (prefers-reduced-motion: reduce)").matches || navigator.connection?.saveData;
  if (!light) (window.requestIdleCallback || setTimeout)(() => loadScene().then(m => {
    try { bg = m.createBackground($("#bg")); bg.setMode(me ? "app" : "login"); } catch (e) { console.warn("WebGL unavailable", e); }
  }).catch(() => {}));
})();
