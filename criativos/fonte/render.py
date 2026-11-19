import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
pasta = Path(__file__).parent
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for nome, w, h in (("v1_feed", 1080, 1350), ("v2_story", 1080, 1920), ("v3_quadrado", 1080, 1080)):
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        pg.goto((pasta / f"{nome}.html").as_uri()); pg.wait_for_timeout(400)
        pg.screenshot(path=str(pasta.parent / f"clube_{nome}.png"))
    b.close()
