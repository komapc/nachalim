#!/usr/bin/env python3
"""The stream links in index.html are written by hand: each must still open a stream after a data rebuild."""
import json
import pathlib
import re
import unittest

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"


class AboutLinks(unittest.TestCase):
    def test_links_name_existing_streams(self):
        page = (SITE / "index.html").read_text(encoding="utf-8")
        info = json.loads((SITE / "data/info.json").read_text(encoding="utf-8"))
        slugs = {entry["s"] for entry in info.values()}
        links = re.findall(r'<a href="#([^"]+)">', page)
        self.assertTrue(links)
        self.assertEqual([link for link in links if link not in slugs], [])


if __name__ == "__main__":
    unittest.main()
