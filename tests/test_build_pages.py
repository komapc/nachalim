#!/usr/bin/env python3
"""The generated stream and basin pages: every link leads somewhere, and only real content gets indexed."""
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
        pages = [*(self.out / "n").rglob("index.html"), *(self.out / "basin").rglob("index.html")]
        for page in pages:
            for href in re.findall(r'href="(/(?:n|basin)/[^"]*)"', page.read_text(encoding="utf-8")):
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

    def read_basin(self, root):
        return (self.out / "basin" / root["s"] / "index.html").read_text(encoding="utf-8")

    def test_every_large_basin_has_a_page(self):
        self.assertGreater(len(self.builder.basins), 10)
        for root_id, members in self.builder.members.items():
            exists = (self.out / "basin" / self.info[root_id]["s"] / "index.html").exists()
            self.assertEqual(exists, root_id in self.builder.basins, self.info[root_id]["n"])
            if exists:
                self.assertGreaterEqual(len(members), build_pages.MIN_BASIN)

    def test_basin_page_lists_every_stream(self):
        for root_id, members in self.builder.basins.items():
            page = self.read_basin(self.info[root_id])
            for entry in members:
                self.assertIn(f'href="{html.escape(build_pages.stream_path(entry["s"]))}"', page)

    def test_basin_page_content(self):
        root = self.builder.by_slug["נחל-ירקון"]
        page = self.read_basin(root)
        self.assertIn("<title>אגן הירקון: כל הנחלים במפה</title>", page)
        self.assertIn("<h1>אגן הירקון</h1>", page)
        self.assertIn('<html lang="he" dir="rtl">', page)
        self.assertIn(f'<link rel="canonical" href="{BASE}{build_pages.basin_path(root["s"])}">', page)
        self.assertIn(f'href="/#{build_pages.quote(root["s"], safe="")}"', page)
        self.assertIn("הים התיכון", page)
        self.assertNotIn("noindex", page)

    def test_stream_pages_link_their_basin(self):
        for entry_id, entry in self.info.items():
            root = self.info[str(entry["r"])]
            href = f'href="{html.escape(build_pages.basin_path(root["s"]))}"'
            if str(entry["r"]) in self.builder.basins:
                self.assertIn(href, self.read(entry), entry["n"])
            else:
                self.assertNotIn(href, self.read(entry), entry["n"])

    def test_basin_index_links_every_basin(self):
        page = (self.out / "basin" / "index.html").read_text(encoding="utf-8")
        links = set(re.findall(r'href="(/basin/[^"]+/)"', page))
        self.assertEqual(links, {html.escape(build_pages.basin_path(self.info[root]["s"])) for root in self.builder.basins})
        self.assertIn('href="/basin/"', (self.out / "n" / "index.html").read_text(encoding="utf-8"))

    def test_basins_in_sitemap(self):
        sitemap = (self.out / "sitemap.xml").read_text(encoding="utf-8")
        urls = {html.unescape(url) for url in re.findall(r"<loc>([^<]+)</loc>", sitemap)}
        self.assertIn(BASE + "/basin/", urls)
        for root_id in self.builder.basins:
            self.assertIn(BASE + build_pages.basin_path(self.info[root_id]["s"]), urls)

    def test_basin_titles_are_unique_and_data_parses(self):
        pages = list((self.out / "basin").rglob("index.html"))
        titles = [re.search(r"<title>(.*?)</title>", page.read_text(encoding="utf-8")).group(1) for page in pages]
        self.assertEqual(len(titles), len(set(titles)))
        for page in pages:
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page.read_text(encoding="utf-8"), re.S):
                json.loads(block)

    def test_flow_ends_like_the_map(self):
        steps = self.builder.flow_steps(self.builder.by_slug["נחל-דן"])
        self.assertEqual(steps[-1][0], "ים המלח")


if __name__ == "__main__":
    unittest.main()
