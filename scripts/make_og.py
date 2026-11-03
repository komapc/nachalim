#!/usr/bin/env python3
"""Render site/og.png, the 1200x630 link preview, from the stream data. Needs Playwright."""
import json
import pathlib

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The same colours as DRAINAGE in site/app.js: change them together.
COLORS = {"med": "#1f78c1", "jordan": "#0b9a8d", "dead": "#c9662b", "gulf": "#8e4fb8", "closed": "#b8960c", "unknown": "#7d8a8e"}
LEGEND = [("med", "הים התיכון"), ("jordan", "הירדן והכנרת"), ("dead", "ים המלח"), ("gulf", "מפרץ אילת")]
WIDTH, HEIGHT = 1200, 630
LAT = (29.45, 33.42)
LON = (34.1, 36.0)
MAP_HEIGHT = HEIGHT - 40
SCALE = MAP_HEIGHT / (LAT[1] - LAT[0])
X_FACTOR = 0.85  # cos(latitude), keeps the country's proportions


def paths(features):
    out = []
    for feature in sorted(features, key=lambda f: f["properties"]["k"]):
        km = feature["properties"]["k"]
        width = 3 if km >= 50 else 2 if km >= 15 else 1.2
        for line in feature["geometry"]["coordinates"]:
            points = " ".join(f"{(x - LON[0]) * SCALE * X_FACTOR:.1f},{(LAT[1] - y) * SCALE:.1f}" for x, y in line)
            out.append(f'<polyline points="{points}" stroke="{COLORS[feature["properties"]["d"]]}" stroke-width="{width}"/>')
    return "".join(out)


def main():
    data = json.loads((ROOT / "site/data/rivers.geojson").read_text(encoding="utf-8"))
    map_width = (LON[1] - LON[0]) * SCALE * X_FACTOR
    legend = "".join(f'<li><i style="background:{COLORS[key]}"></i>{label}</li>' for key, label in LEGEND)
    html = f"""<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><style>
    * {{ margin: 0; box-sizing: border-box; }}
    body {{ width: {WIDTH}px; height: {HEIGHT}px; display: flex; align-items: center; background: #f6f8f7; color: #1b2a2f; font-family: "Noto Sans Hebrew", Arial, sans-serif; overflow: hidden; }}
    .text {{ flex: 1; padding: 0 80px 0 30px; }}
    h1 {{ font-size: 92px; line-height: 1.05; }}
    p {{ margin-top: 22px; font-size: 36px; line-height: 1.3; color: #40545a; }}
    ul {{ margin-top: 36px; padding: 0; list-style: none; display: grid; grid-template-columns: auto auto; gap: 12px 28px; justify-content: start; font-size: 28px; }}
    li {{ display: flex; align-items: center; gap: 12px; }}
    i {{ width: 34px; height: 8px; border-radius: 4px; }}
    svg {{ flex: none; margin-inline-end: 30px; }}
    polyline {{ fill: none; stroke-linecap: round; stroke-linejoin: round; }}
    </style><body>
    <div class="text"><h1>נחלי ישראל</h1><p>מפה אינטראקטיבית: לחצו על נחל וגלו לאן הוא זורם</p><ul>{legend}</ul></div>
    <svg width="{map_width:.0f}" height="{MAP_HEIGHT}" viewBox="0 0 {map_width:.0f} {MAP_HEIGHT}" dir="ltr">{paths(data["features"])}</svg>
    </body></html>"""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.set_content(html)
        page.wait_for_timeout(300)
        page.screenshot(path=str(ROOT / "site/og.png"))
        browser.close()


if __name__ == "__main__":
    main()
