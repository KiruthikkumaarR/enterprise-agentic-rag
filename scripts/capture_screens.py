"""Capture high-resolution portfolio screenshots from the static demo (served at http://127.0.0.1:8200).

Usage:  python scripts/capture_screens.py
Writes kiruthikportfolio.com/assets/img/*.jpg
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "kiruthikportfolio.com" / "assets" / "img"
SITE = "http://127.0.0.1:8200"


def shot(page, name, wait=1200):
    """Save a retina capture as a 1600px-wide WebP (what the site references)."""
    from PIL import Image
    page.wait_for_timeout(wait)
    page.evaluate("document.getElementById('replay-banner')?.remove()")
    tmp = IMG / (name + ".png")
    page.screenshot(path=str(tmp))
    im = Image.open(tmp)
    im.resize((1600, round(im.height * 1600 / im.width)), Image.LANCZOS).save(IMG / name.replace(".jpg", ".webp"), "WEBP", quality=82, method=6)
    tmp.unlink()
    print("saved", name.replace(".jpg", ".webp"))


def ask(page, q, wait=1800):
    page.fill("#q", q)
    page.press("#q", "Enter")
    page.wait_for_timeout(wait)


def main():
    IMG.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme="dark")
        page = ctx.new_page()

        page.goto(f"{SITE}/demo/")
        shot(page, "portal-login.jpg", 3500)

        page.evaluate("document.querySelector('#demo').open = true")
        page.wait_for_timeout(400)
        page.click(".demo-item:has-text('ceo')")
        page.click("#login-btn")
        page.wait_for_timeout(2000)
        ask(page, "What is the indicative enterprise value of Project Nordlys?")
        ask(page, "Who is the account manager for Bilbao Packaging S.L.?")
        shot(page, "portal-assistant.jpg")

        page.locator(".msg-ai .source").first.click()
        shot(page, "portal-citation.jpg", 1500)
        page.keyboard.press("Escape")

        ask(page, "Show me the top 10 customers by annual revenue as a chart", 2500)
        shot(page, "portal-chart.jpg", 1500)

        page.click("#nav button[data-v='dashboards']")
        shot(page, "portal-dashboard.jpg", 3000)

        page.click("#nav button[data-v='galaxy']")
        shot(page, "portal-galaxy.jpg", 5000)

        page.click("#nav button[data-v='reports']")
        shot(page, "portal-reports.jpg", 2000)

        og = browser.new_context(viewport={"width": 1200, "height": 630}, device_scale_factor=1, color_scheme="dark").new_page()
        og.goto(f"{SITE}/")
        og.wait_for_timeout(3000)
        og.screenshot(path=str(IMG / "og.jpg"), type="jpeg", quality=88)
        print("saved og.jpg")
        browser.close()


if __name__ == "__main__":
    main()
