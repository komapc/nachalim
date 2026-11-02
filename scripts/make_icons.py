#!/usr/bin/env python3
"""Render PNG and ICO favicons from site/favicon.svg. Needs Playwright."""
import pathlib
import struct

from playwright.sync_api import sync_playwright

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"


def render(page, svg, size):
    page.set_viewport_size({"width": size, "height": size})
    page.set_content(f'<!doctype html><style>*{{margin:0}}svg{{display:block;width:{size}px;height:{size}px}}</style>{svg}')
    return page.screenshot(omit_background=True)


def write_ico(path, images):
    """An ICO file may hold PNG images directly."""
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        blobs += data
    path.write_bytes(header + entries + blobs)


def main():
    svg = (SITE / "favicon.svg").read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        (SITE / "apple-touch-icon.png").write_bytes(render(page, svg, 180))
        (SITE / "favicon-192.png").write_bytes(render(page, svg, 192))
        write_ico(SITE / "favicon.ico", [(size, render(page, svg, size)) for size in (16, 32, 48)])
        browser.close()


if __name__ == "__main__":
    main()
