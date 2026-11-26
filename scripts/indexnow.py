#!/usr/bin/env python3
"""Tell Bing, Yandex and the other IndexNow engines which pages a deploy changed.

  indexnow.py diff site changed.txt   before the deploy: compare the built pages
                                      with the live ones and list the URLs that
                                      are new, changed or gone
  indexnow.py ping changed.txt        after the deploy: send that list

Only pages in the sitemap are compared. A page the live site cannot serve counts
as changed. Neither step fails the deploy: a network error is printed and skipped.
"""
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

HOST = "nachalim.lipu.dev"
KEY = "483e472b63ec64808ac4046f1b87eeb1"
ENDPOINT = "https://api.indexnow.org/indexnow"
UA = "nachalim-indexnow/1.0"


def sitemap_urls(xml):
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def page_file(site, url):
    """The built file a sitemap URL serves: /n/x/ -> site/n/x/index.html."""
    path = unquote(urlparse(url).path).lstrip("/")
    return Path(site) / path / "index.html"


def fetch(url):
    """The live bytes at url, or None if it cannot be fetched."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
            return r.read()
    except (urllib.error.URLError, OSError):
        return None


def changed_urls(site, fetch=fetch):
    """URLs of the new build that differ from the live site, plus live ones it drops."""
    urls = sitemap_urls((Path(site) / "sitemap.xml").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(16) as pool:
        live = dict(zip(urls, pool.map(fetch, urls)))
    changed = [u for u in urls if live[u] != page_file(site, u).read_bytes()]
    old = fetch(f"https://{HOST}/sitemap.xml")
    gone = [u for u in sitemap_urls(old.decode("utf-8")) if u not in live] if old else []
    return changed + gone


def ping(urls):
    body = json.dumps({"host": HOST, "key": KEY, "keyLocation": f"https://{HOST}/{KEY}.txt",
                       "urlList": urls}).encode()
    req = urllib.request.Request(ENDPOINT, data=body, headers={
        "Content-Type": "application/json; charset=utf-8", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def main(argv):
    if len(argv) == 4 and argv[1] == "diff":
        urls = changed_urls(argv[2])
        Path(argv[3]).write_text("".join(u + "\n" for u in urls), encoding="utf-8")
        print(f"{len(urls)} changed pages")
    elif len(argv) == 3 and argv[1] == "ping":
        listed = Path(argv[2])
        urls = listed.read_text(encoding="utf-8").split() if listed.exists() else []
        if not urls:
            print("nothing to send")
            return 0
        try:
            print(f"IndexNow: {len(urls)} URLs -> {ping(urls)}")
        except (urllib.error.URLError, OSError) as e:
            print(f"IndexNow failed: {e}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
