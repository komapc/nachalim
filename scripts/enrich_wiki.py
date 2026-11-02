#!/usr/bin/env python3
"""Attach Hebrew Wikipedia summaries and write the site's data files.

Usage: enrich_wiki.py RIVERS_JSON CACHE_JSON OUT_DIR
Links come from the OSM wikidata/wikipedia tags. A river without a tag is matched
on its exact page title only if its name is unique, the page is not a
disambiguation page, and any page coordinates lie near the river.
"""
import collections
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

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
    from build_rivers import dist_m
    return any(dist_m(coord, p) <= MAX_MATCH_KM * 1000 for line in lines for p in line)


def trim(text):
    text = " ".join(text.split())
    if len(text) <= SUMMARY_CHARS:
        return text
    cut = text[:SUMMARY_CHARS]
    end = cut.rfind(". ")
    return cut[:end + 1] if end > 200 else cut.rstrip() + "…"


def drainage(river, rivers):
    root = rivers[river["root"]]
    if root["name"] == "נהר הירדן" or root["sink"] in ("kinneret", "hula"):
        return "jordan"
    return root["sink"] or "unknown"


def main():
    rivers_path, cache_path, out_dir = sys.argv[1:4]
    rivers = json.load(open(rivers_path, encoding="utf-8"))
    cache_file = pathlib.Path(cache_path)
    cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}

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
    cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    slugs = collections.Counter()
    features, info = [], {}
    children = collections.defaultdict(list)
    for river in rivers:
        if river["parent"] is not None:
            children[river["parent"]].append(river["id"])
    for river in rivers:
        slugs[river["name"]] += 1
        base = river["name"].replace(" ", "-")
        river["slug"] = base if slugs[river["name"]] == 1 else f"{base}-{slugs[river['name']]}"

    linked = 0
    for river in rivers:
        page = cache["page"].get(river["_title"]) if river["_title"] else None
        usable = page and page.get("extract") and not page.get("disambiguation")
        if usable and not river["_tagged"]:
            coord = page.get("coord")
            usable = bool(coord) and near(coord, river["lines"])
        entry = {"s": river["slug"], "n": river["name"], "d": drainage(river, rivers),
                 "r": river["root"], "p": river["parent"], "k": river["km"], "sink": rivers[river["root"]]["sink"],
                 "c": sorted(children[river["id"]], key=lambda i: -rivers[i]["km"])}
        if river["tags"].get("name:en"):
            entry["en"] = river["tags"]["name:en"]
        total = river["km"] or 1
        if river["perennial_km"] / total > 0.5:
            entry["f"] = "perennial"
        elif river["perennial_km"] > 0:
            entry["f"] = "mixed"
        elif river["intermittent_km"] / total > 0.5:
            entry["f"] = "intermittent"
        if usable:
            linked += 1
            entry["w"] = page["title"]
            entry["x"] = trim(page["extract"])
        info[river["id"]] = entry
        features.append({"type": "Feature", "id": river["id"],
                         "properties": {"i": river["id"], "d": entry["d"], "k": river["km"], "n": river["name"]},
                         "geometry": {"type": "MultiLineString", "coordinates": river["lines"]}})

    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rivers.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "info.json").write_text(json.dumps(info, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rivers)} rivers, {linked} with Wikipedia summaries")
    print(collections.Counter(e["d"] for e in info.values()))


if __name__ == "__main__":
    main()
