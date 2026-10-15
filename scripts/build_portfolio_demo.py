"""Copy the portal frontend into the portfolio as a static replay demo (kiruthikportfolio.com/demo/).

The frontend code is copied as-is; only absolute asset/API paths are rewritten so it runs from a static host,
the replay layer is loaded first, and a banner explains that answers are recorded from the real system.
Run after scripts/record_portfolio_demo.py.
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "portal" / "static"
DST = ROOT / "kiruthikportfolio.com" / "demo"

BANNER = """<div id="replay-banner" style="position:fixed;z-index:60;left:50%;top:10px;transform:translateX(-50%);display:flex;gap:10px;align-items:center;
padding:8px 14px;border-radius:99px;background:rgba(10,16,32,.92);border:1px solid rgba(63,214,196,.45);font-size:12px;color:#aab6d3;box-shadow:0 10px 30px rgba(0,0,0,.4);max-width:calc(100vw - 24px)">
<span style="width:8px;height:8px;border-radius:50%;background:#f2b84b;flex:none"></span>
<span><b style="color:#e8eefc">Interactive replay</b><span class="rb-long"> - real outputs recorded from the system, served without a server.</span> <a href="../" style="color:#3fd6c4">Back to portfolio</a></span></div>
<style>@media (max-width: 600px) { #replay-banner .rb-long { display: none; } #replay-banner { white-space: nowrap; } }</style>"""


def main():
    for d in ("css", "js", "vendor"):
        (DST / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(SRC / "css" / "portal.css", DST / "css" / "portal.css")
    for f in ("three.module.min.js", "chart.umd.min.js"):
        shutil.copy(SRC / "vendor" / f, DST / "vendor" / f)
    shutil.copy(ROOT / "portal" / "replay" / "replay.js", DST / "js" / "replay.js")

    scene = (SRC / "js" / "scene.js").read_text().replace("/static/vendor/three.module.min.js", "../vendor/three.module.min.js")
    (DST / "js" / "scene.js").write_text(scene)

    app = (SRC / "js" / "app.js").read_text()
    subs = {
        '"/static/js/scene.js"': '"./scene.js"',
        'src="/api/documents/${encodeURIComponent(s.doc)}/page/${s.page}.png"': 'src="${pageUrl(s.doc, s.page)}"',
        'href="/api/documents/${encodeURIComponent(s.doc)}/download"': 'href="${fileUrl(s.doc)}" download',
        'href="/api/documents/${encodeURIComponent(d.doc)}/download"': 'href="${fileUrl(d.doc)}" download',
    }
    for a, b in subs.items():
        assert a in app, f"pattern not found in app.js: {a}"
        app = app.replace(a, b)
    (DST / "js" / "app.js").write_text(app)

    html = (SRC / "index.html").read_text()
    subs = {'href="/static/css/portal.css"': 'href="css/portal.css"',
            '<script src="/static/vendor/chart.umd.min.js" defer></script>': '<script src="js/replay.js"></script>\n<script src="vendor/chart.umd.min.js" defer></script>',
            'src="/static/js/app.js"': 'src="js/app.js"',
            '<meta name="viewport"': ('<meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\'; '
                                     'style-src \'self\' \'unsafe-inline\'; img-src \'self\' data: blob:; font-src \'self\'; connect-src \'self\'; '
                                     'media-src \'self\'; object-src \'none\'; base-uri \'self\'; form-action \'none\'; upgrade-insecure-requests">\n'
                                     '<meta name="referrer" content="strict-origin-when-cross-origin">\n<meta name="viewport"'),
            "<title>Halvorsen Intelligence Portal</title>": "<title>Live demo · Enterprise Agentic RAG · Kiruthikkumaar Radhakrishnan</title>",
            "</body>": BANNER + "\n</body>"}
    for a, b in subs.items():
        assert a in html, f"pattern not found in index.html: {a}"
        html = html.replace(a, b)
    (DST / "index.html").write_text(html)
    print("demo built ->", DST)


if __name__ == "__main__":
    main()
