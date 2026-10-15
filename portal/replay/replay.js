// Replay layer for the static portfolio demo.
// The portal frontend is unchanged except for asset paths: every /api/... call it makes is answered here from
// responses recorded on the real system (scripts/record_portfolio_demo.py). Nothing is generated in the browser.
(function () {
  const realFetch = window.fetch.bind(window);
  const SKEY = "his_demo_user";
  const cache = {};
  const user = () => { try { return sessionStorage.getItem(SKEY); } catch { return window.__demoUser || null; } };
  const setUser = u => { try { u ? sessionStorage.setItem(SKEY, u) : sessionStorage.removeItem(SKEY); } catch { window.__demoUser = u; } };
  const slug = s => s.replace(/[^A-Za-z0-9._-]+/g, "_");
  const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  const err = (status, detail) => json({ detail }, status);
  const load = async p => (cache[p] ??= realFetch(p).then(r => { if (!r.ok) throw new Error(p); return r.json(); }));
  const role = async () => { const u = user(); return u ? load(`data/${u}.json`) : null; };
  const norm = s => s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").split(/\s+/).filter(w => w.length > 2 && !STOP.has(w));
  const STOP = new Set(["what", "the", "and", "for", "show", "me", "chart", "with", "how", "much", "many", "who", "which", "are", "was", "does", "this", "that", "from", "per", "our"]);

  window.pageUrl = (doc, page) => `data/pages/${slug(doc)}__${page}.png`;
  window.fileUrl = doc => `data/files/${doc}`;

  async function route(path, init) {
    const method = (init?.method || "GET").toUpperCase();
    const url = new URL(path, location.href);
    const p = url.pathname.replace(/^.*\/api\//, "/api/");
    const body = init?.body && typeof init.body === "string" ? JSON.parse(init.body) : null;

    if (p === "/api/demo-accounts") return json(await load("data/accounts.json"));
    if (p === "/api/login") {
      const acc = (await load("data/accounts.json")).find(a => a.username === (body.username || "").trim().toLowerCase());
      if (!acc || acc.password !== body.password) return err(401, "invalid username or password (demo: use one of the demo accounts)");
      setUser(acc.username);
      return json((await role()).me);
    }
    if (p === "/api/logout") { setUser(null); return json({ ok: true }); }
    const r = await role();
    if (!r) return err(401, "not signed in");
    switch (true) {
      case p === "/api/me": return json(r.me);
      case p === "/api/suggestions": return json(r.suggestions);
      case p === "/api/documents": return json(r.documents);
      case p === "/api/stats": return json(r.stats);
      case p === "/api/meta": return json(r.meta);
      case p === "/api/reports": return json(r.reports);
      case p === "/api/history": return json([]);
      case p === "/api/dashboard/tabs": return json(r.dashboard_tabs);
      case p === "/api/dashboard": return json(r.dashboards[url.searchParams.get("tab")] || []);
      case p === "/api/admin/users": return r.users ? json(r.users) : err(403, "administrator or executive rights required");
      case p === "/api/admin/activity": return r.activity ? json(r.activity) : err(403, "administrator or executive rights required");
      case p === "/api/ask": return json(answer(r, body.question));
      case /^\/api\/documents\/[^/]+\/preview$/.test(p): {
        const doc = decodeURIComponent(p.split("/")[3]);
        if (!r.documents.some(d => d.doc === doc)) return err(404, "document not found");
        return json(await load(`data/previews/${slug(doc)}.json`));
      }
      case /^\/api\/reports\/[^/]+\.(pptx|xlsx)$/.test(p): {
        const [, id, kind] = p.match(/^\/api\/reports\/([^/]+)\.(pptx|xlsx)$/);
        const res = await realFetch(`data/reports/${user()}__${id}.${kind}`);
        if (!res.ok) return err(404, "This report was not recorded for the demo - the top three reports per role are available.");
        const blob = await res.blob();
        const title = (r.reports.find(x => x.id === id)?.title || id).replace(/[^A-Za-z0-9]+/g, "_");
        return new Response(blob, { status: 200, headers: { "Content-Disposition": `attachment; filename="${title}.${kind}"` } });
      }
      case p.startsWith("/api/export/"): return err(404, "Single-chart export runs on the full system - download a whole report from the Reports page instead.");
      case p === "/api/upload": return err(400, "Uploads are disabled in the online demo (the full system indexes a new document in seconds).");
      case p === "/api/catalog": case p === "/api/chart": case p.startsWith("/api/widgets"):
        return err(400, "The chart builder needs the live system - in the demo, ask the assistant for one of the recorded charts.");
      case p.startsWith("/api/admin/"): return err(400, "Account changes are disabled in the online demo.");
    }
    return err(404, "not available in the demo");
  }

  function answer(r, q) {
    const qn = q.trim().toLowerCase();
    let best = r.answers.find(a => a.question.trim().toLowerCase() === qn), score = best ? 1 : 0;
    if (!best) {
      const qt = new Set(norm(q));
      for (const a of r.answers) {
        const at = new Set(norm(a.question)), inter = [...qt].filter(w => at.has(w)).length;
        const s = inter / Math.max(1, new Set([...qt, ...at]).size);
        if (s > score) { score = s; best = a; }
      }
    }
    if (best && score >= 0.5) return best;
    return { question: q, status: "no_evidence", answer: "", answer_raw:
      "This online demo replays answers recorded on the real system, so it can only answer the suggested questions (and close variants). " +
      "Try one of the suggestions above - including the same question under a different role - or run the project locally to ask anything.",
      sources: [], claims: [], regenerations: 0, timings: { total: 0 } };
  }

  window.fetch = (input, init) => {
    const path = typeof input === "string" ? input : input.url;
    if (/\/api\//.test(path)) return new Promise(res => setTimeout(() => route(path, init).then(res), 280 + Math.random() * 380));
    return realFetch(input, init);
  };
})();
