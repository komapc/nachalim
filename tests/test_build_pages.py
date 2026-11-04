#!/usr/bin/env python3
"""The generated stream pages: every link leads somewhere, and only real content gets indexed."""
import html
import json
import pathlib
import re
import sys
import tempfile
import unittest
from urllib.parse import unquote

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_pages  # noqa: E402

BASE = build_pages.BASE


class BuildPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = pathlib.Path(cls.tmp.name)
        cls.builder = build_pages.Builder(cls.out)
        cls.builder.build()
        cls.info = cls.builder.info

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def read(self, entry):
        return (self.out / "n" / entry["s"] / "index.html").read_text(encoding="utf-8")

    def exists(self, path):
        return (self.out / unquote(path).lstrip("/") / "index.html").exists()

    def test_every_stream_has_a_page(self):
        self.assertEqual(sum(1 for path in (self.out / "n").rglob("index.html")), len(self.info) + 1)

    def test_internal_links_resolve(self):
        for page in (self.out / "n").rglob("index.html"):
            for href in re.findall(r'href="(/n/[^"]+)"', page.read_text(encoding="utf-8")):
                self.assertTrue(self.exists(html.unescape(href)), f"{page}: {href}")

    def test_home_links_resolve(self):
        home = (build_pages.SITE / "index.html").read_text(encoding="utf-8")
        links = re.findall(r'href="(/n/[^"]*)"', home)
        self.assertGreater(len(links), 10)
        for href in links:
            if href != "/n/":
                self.assertTrue(self.exists(html.unescape(href)), href)

    def test_sitemap_matches_noindex(self):
        sitemap = (self.out / "sitemap.xml").read_text(encoding="utf-8")
        urls = {html.unescape(url) for url in re.findall(r"<loc>([^<]+)</loc>", sitemap)}
        for entry in self.info.values():
            url = BASE + build_pages.stream_path(entry["s"])
            page = self.read(entry)
            if build_pages.is_indexable(entry):
                self.assertIn(url, urls)
                self.assertNotIn("noindex", page)
            else:
                self.assertNotIn(url, urls)
                self.assertIn('content="noindex, follow"', page)

    def test_stream_page_content(self):
        yarkon = self.builder.by_slug["נחל-ירקון"]
        page = self.read(yarkon)
        self.assertIn("<h1>נחל ירקון</h1>", page)
        self.assertIn("הים התיכון", page)
        self.assertIn("he.wikipedia.org/wiki/", page)
        self.assertIn("CC BY-SA", page)
        self.assertIn("cloudflareinsights", page)
        self.assertIn('src="/consent.js"', page)
        self.assertIn(f'href="/#{build_pages.quote(yarkon["s"], safe="")}"', page)

    def test_structured_data_parses(self):
        for entry in self.info.values():
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', self.read(entry), re.S):
                json.loads(block)

    def test_titles_are_unique(self):
        titles = [re.search(r"<title>(.*?)</title>", self.read(entry)).group(1) for entry in self.info.values() if build_pages.is_indexable(entry)]
        self.assertEqual(len(titles), len(set(titles)))

    def test_flow_ends_like_the_map(self):
        steps = self.builder.flow_steps(self.builder.by_slug["נחל-דן"])
        self.assertEqual(steps[-1][0], "ים המלח")


if __name__ == "__main__":
    unittest.main()
