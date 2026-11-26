import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import indexnow  # noqa: E402

BASE = "https://nachalim.lipu.dev"


class ChangedUrls(unittest.TestCase):
    def test_lists_new_changed_and_gone_pages(self):
        with tempfile.TemporaryDirectory() as d:
            site = Path(d)
            pages = {"/": b"home", "/n/%D7%90/": b"new text", "/glossary/": b"same"}
            for path, body in pages.items():
                f = indexnow.page_file(site, BASE + path)
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(body)
            (site / "sitemap.xml").write_text("".join(f"<loc>{BASE}{p}</loc>" for p in pages), encoding="utf-8")
            live = {BASE + "/": b"home", BASE + "/n/%D7%90/": b"old text", BASE + "/glossary/": b"same",
                    BASE + "/sitemap.xml": f"<loc>{BASE}/</loc><loc>{BASE}/n/gone/</loc>".encode()}
            changed = indexnow.changed_urls(site, fetch=live.get)
        self.assertEqual(changed, [BASE + "/n/%D7%90/", BASE + "/n/gone/"])

    def test_page_file_decodes_hebrew(self):
        self.assertEqual(indexnow.page_file("site", BASE + "/n/%D7%90/"), Path("site/n/א/index.html"))
        self.assertEqual(indexnow.page_file("site", BASE + "/"), Path("site/index.html"))


if __name__ == "__main__":
    unittest.main()
