#!/usr/bin/env python3
"""Attach Hebrew Wikipedia summaries and write the site's data files.

Usage: enrich_wiki.py RIVERS_JSON CACHE_JSON OUT_DIR
Links come from the OSM wikidata/wikipedia tags. A river without a tag is matched
on its exact page title only if its name is unique, the page is not a
disambiguation page, and its page coordinates lie near the river.

Writes OUT_DIR/rivers.geojson and OUT_DIR/info.json (keys explained in the README).
Network replies are kept in CACHE_JSON: delete it to fetch fresh summaries.
"""
import collections
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from build_rivers import dist_m, read_json, write_json

UA = "nachalim-build (github.com/komapc/nachalim)"
SUMMARY_CHARS = 700
MAX_MATCH_KM = 25


def get(url, params):
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    request = urllib.request.Request(f"{url}?{query}", headers={"User-Agent": UA})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            time.sleep(int(error.headers.get("Retry-After") or 5 * 2 ** attempt))
        except OSError:
            time.sleep(5 * 2 ** attempt)
    raise RuntimeError(f"failed: {url}")


def chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def sitelinks(qids):
    titles = {}
    for batch in chunks(qids, 50):
        data = get("https://www.wikidata.org/w/api.php", {
            "action": "wbgetentities", "ids": "|".join(batch),
            "props": "sitelinks", "sitefilter": "hewiki"})
        for qid, entity in data.get("entities", {}).items():
            link = entity.get("sitelinks", {}).get("hewiki")
            if link:
                titles[qid] = link["title"]
        time.sleep(1.5)
    return titles


def pages(titles):
    found = {}
    for batch in chunks(titles, 20):
        params = {"action": "query", "titles": "|".join(batch), "redirects": 1,
                  "prop": "extracts|pageprops|coordinates", "exintro": 1, "explaintext": 1,
                  "exlimit": 20, "ppprop": "disambiguation", "colimit": 50}
        while True:
            data = get("https://he.wikipedia.org/w/api.php", params)
            query = data.get("query", {})
            alias = {r["from"]: r["to"] for r in query.get("redirects", [])}
            alias.update({n["from"]: n["to"] for n in query.get("normalized", [])})
            by_title = {p["title"]: p for p in query.get("pages", []) if not p.get("missing")}
            for title in batch:
                resolved = title
                while resolved in alias:
                    resolved = alias[resolved]
                page = by_title.get(resolved)
                if page:
                    entry = found.setdefault(title, {"title": page["title"]})
                    if page.get("extract"):
                        entry["extract"] = page["extract"]
                    if "pageprops" in page:
                        entry["disambiguation"] = True
                    if page.get("coordinates"):
                        entry["coord"] = [page["coordinates"][0]["lon"], page["coordinates"][0]["lat"]]
            if "continue" not in data:
                break
            params = {**params, **data["continue"]}
        time.sleep(1.5)
    return found


def near(coord, lines):
    return any(dist_m(coord, p) <= MAX_MATCH_KM * 1000 for line in lines for p in line)


ARABIC = re.compile("[\u0600-\u06ff]")
ARABIC_NOTE = re.compile(r"\s*\([^()]*(?:[\u0600-\u06ff]|בערבית|ערבית:)[^()]*\)")
PERENNIAL = re.compile(r"(?:נחל|נהר) איתן|הנחל האיתן")
INTERMITTENT = re.compile(r"נחל אכזב|נחלי האכזב|נחל עונתי")


def strip_arabic(text):
    """Drop parentheticals giving Arabic names, then any sentence still in Arabic."""
    text = ARABIC_NOTE.sub("", text)
    return " ".join(s for s in re.split(r"(?<=\.)\s+", text) if not ARABIC.search(s) and "בערבית" not in s)


def wiki_flow(extract):
    """Classify from the opening of the article, where it defines the stream."""
    opening = " ".join(re.split(r"(?<=\.)\s+", strip_arabic(extract))[:2])
    perennial, intermittent = PERENNIAL.search(opening), INTERMITTENT.search(opening)
    if perennial and intermittent:
        return "mixed"
    return "perennial" if perennial else "intermittent" if intermittent else None


def osm_flow(river):
    total = river["km"] or 1
    if river["perennial_km"] > 0:
        return "perennial" if river["perennial_km"] / total > 0.5 else "mixed"
    return "intermittent" if river["intermittent_km"] / total > 0.5 else None


def trim(text):
    text = " ".join(strip_arabic(text).split())
    if len(text) <= SUMMARY_CHARS:
        return text
    cut = text[:SUMMARY_CHARS]
    end = cut.rfind(". ")
    return cut[:end + 1] if end > 200 else cut.rstrip() + "…"


def drainage(river, rivers):
    root = rivers[river["root"]]
    if root["name"] == "נהר הירדן" or root["sink"] in ("kinneret", "hula"):
        return "jordan"
    if root["sink"] == "arish":  # Wadi al-Arish reaches the Mediterranean in Sinai.
        return "med"
    if root["sink"] == "yotvata":
        return "closed"
    return root["sink"] or "unknown"


def fetch_pages(rivers, cache):
    """Set each river's _title and _tagged, and fill the cache with what they need."""
    name_count = collections.Counter(r["name"] for r in rivers)
    qids = sorted({r["tags"]["wikidata"] for r in rivers if "wikidata" in r["tags"]})
    missing = [q for q in qids if q not in cache.setdefault("qid", {})]
    cache["qid"].update({q: None for q in missing})
    cache["qid"].update(sitelinks(missing))

    wanted = {}
    for river in rivers:
        tags = river["tags"]
        title = cache["qid"].get(tags.get("wikidata"))
        if not title and tags.get("wikipedia", "").startswith("he:"):
            title = tags["wikipedia"][3:]
        river["_tagged"] = bool(title)
        if not title and name_count[river["name"]] == 1:
            title = river["name"]
        river["_title"] = title
        if title:
            wanted[title] = True
    missing = [t for t in wanted if t not in cache.setdefault("page", {})]
    cache["page"].update({t: None for t in missing})
    cache["page"].update(pages(missing))


def assign_slugs(rivers):
    """URL keys: the name, with a number from the second stream of that name on."""
    slugs = collections.Counter()
    for river in rivers:
        slugs[river["name"]] += 1
        base = river["name"].replace(" ", "-")
        river["slug"] = base if slugs[river["name"]] == 1 else f"{base}-{slugs[river['name']]}"


def usable_page(river, cache):
    """The river's Wikipedia page, if it has a summary and is really about this river."""
    page = cache["page"].get(river["_title"]) if river["_title"] else None
    if not page or not page.get("extract") or page.get("disambiguation"):
        return None
    if not river["_tagged"] and not (page.get("coord") and near(page["coord"], river["lines"])):
        return None
    return page


def info_entry(river, rivers, children, page):
    """One record of info.json; the short keys keep the file small."""
    entry = {"s": river["slug"], "n": river["name"], "d": drainage(river, rivers),
             "r": river["root"], "p": river["parent"], "k": river["km"], "sink": rivers[river["root"]]["sink"],
             "c": sorted(children[river["id"]], key=lambda i: -rivers[i]["km"])}
    if river["via"]:
        entry["v"] = river["via"]
    if river["tags"].get("name:en"):
        entry["en"] = river["tags"]["name:en"]
    flow = river["flow"] or (wiki_flow(page["extract"]) if page else None) or osm_flow(river)
    if flow:
        entry["f"] = flow
    if page:
        entry["w"] = page["title"]
        entry["x"] = trim(page["extract"])
    return entry


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    rivers_path, cache_path, out_dir = sys.argv[1:4]
    rivers = read_json(rivers_path)
    cache_file = pathlib.Path(cache_path)
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    fetch_pages(rivers, cache)
    cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    assign_slugs(rivers)

    children = collections.defaultdict(list)
    for river in rivers:
        if river["parent"] is not None:
            children[river["parent"]].append(river["id"])

    features, info = [], {}
    linked = 0
    for river in rivers:
        page = usable_page(river, cache)
        linked += bool(page)
        entry = info_entry(river, rivers, children, page)
        info[river["id"]] = entry
        features.append({"type": "Feature", "id": river["id"],
                         "properties": {"i": river["id"], "d": entry["d"], "k": river["km"], "n": river["name"], "f": entry.get("f", "")},
                         "geometry": {"type": "MultiLineString", "coordinates": river["lines"]}})

    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "rivers.geojson", {"type": "FeatureCollection", "features": features})
    write_json(out / "info.json", info)
    print(f"{len(rivers)} rivers, {linked} with Wikipedia summaries")
    print(collections.Counter(e["d"] for e in info.values()))


if __name__ == "__main__":
    main()
