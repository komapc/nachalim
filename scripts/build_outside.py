#!/usr/bin/env python3
"""Continue streams past the data box, through OSM ways and traced outlets.

Usage: build_outside.py RAW_WAYS RAW_OUTSIDE_DIR RIVERS_JSON INFO_JSON TRACES_JSON OUT_GEOJSON
Writes lines only for streams that really leave the box. Standard library only.
"""
import collections
import json
import pathlib
import sys

from build_rivers import length_km, simplify

BOX = (34.2, 29.45, 35.95, 33.45)
MIN_KM = 1
ARISH = "ואדי אל-עריש"


def key(point):
    return (round(point["lon"], 5), round(point["lat"], 5))


def in_box(point):
    return BOX[0] <= point[0] <= BOX[2] and BOX[1] <= point[1] <= BOX[3]


def load_ways(ways_path, outside_dir):
    ways = {}
    for path in [ways_path, *sorted(pathlib.Path(outside_dir).glob("*.json"))]:
        for way in json.load(open(path, encoding="utf-8"))["elements"]:
            if way.get("geometry"):
                ways[way["id"]] = {"tags": way.get("tags", {}), "pts": [key(p) for p in way["geometry"]]}
    return ways


def owners(ways, rivers):
    """A way belongs to a mapped stream when both of its ends are on that stream."""
    on_river = collections.defaultdict(set)
    for river in rivers:
        for line in river["lines"]:
            for point in line:
                on_river[tuple(point)].add(river["id"])
    owned = {}
    for way_id, way in ways.items():
        shared = on_river.get(way["pts"][0], set()) & on_river.get(way["pts"][-1], set())
        if shared:
            owned[way_id] = min(shared)
    return owned


class Network:
    def __init__(self, ways, owned):
        self.ways, self.owned = ways, owned
        self.starting, self.ending = collections.defaultdict(list), collections.defaultdict(list)
        for way_id, way in ways.items():
            self.starting[way["pts"][0]].append(way_id)
            self.ending[way["pts"][-1]].append(way_id)

    def downstream(self, start, own):
        points, here, seen = [], start, set()
        while True:
            options = [w for w in self.starting[here] if w not in seen and self.owned.get(w, own) == own]
            if not options:
                return points
            best = max(options, key=lambda w: (self.ways[w]["tags"].get("waterway") == "river", length_km(self.ways[w]["pts"])))
            seen.add(best)
            points += self.ways[best]["pts"]
            here = self.ways[best]["pts"][-1]

    def upstream(self, start):
        """The longest unmapped path that ends at start."""
        memo = {}

        def longest(node, depth=0):
            if node in memo or depth > 400:
                return memo.get(node, (0, []))
            memo[node] = (0, [])  # breaks cycles from mis-digitised directions
            best = (0, [])
            for way_id in self.ending[node]:
                if way_id in self.owned:
                    continue
                pts = self.ways[way_id]["pts"]
                km, path = longest(pts[0], depth + 1)
                if km + length_km(pts) > best[0]:
                    best = (km + length_km(pts), path + pts)
            memo[node] = best
            return best

        return longest(start)[1]


def feature(points, slug, name, source):
    line = [[round(x, 5), round(y, 5)] for x, y in simplify([tuple(p) for p in points])]
    return {"type": "Feature", "properties": {"s": slug, "n": name, "src": source},
            "geometry": {"type": "LineString", "coordinates": line}}


def main():
    sys.setrecursionlimit(5000)
    ways_path, outside_dir, rivers_path, info_path, traces_path, out_path = sys.argv[1:7]
    rivers = json.load(open(rivers_path, encoding="utf-8"))
    info = json.load(open(info_path, encoding="utf-8"))
    traces = json.load(open(traces_path, encoding="utf-8"))
    ways = load_ways(ways_path, outside_dir)
    network = Network(ways, owners(ways, rivers))
    features = []
    for river in rivers:
        slug = info[str(river["id"])]["s"]
        if river["parent"] is None and river["mouth"]:
            # The mapped lines can stop before the mouth: keep the walk that passes it.
            mouth = (round(river["mouth"][0], 5), round(river["mouth"][1], 5))
            walks = [network.downstream(tuple(line[-1]), river["id"]) for line in river["lines"]]
            through = [walk for walk in walks if mouth in walk]
            points = max(through, key=length_km) if through else network.downstream(mouth, river["id"])
            if not through and river["name"] in traces["joins"]:
                features.append(feature(max(walks, key=length_km), slug, river["name"], "osm"))
                features.append(feature(traces["joins"][river["name"]], slug, river["name"], "dem"))
            # A stream draining to Sinai is drawn from its mouth, even inside the box.
            leaves = river["sink"] == "arish" or not all(in_box(p) for p in points)
            if length_km(points) >= MIN_KM and leaves:
                features.append(feature(points, slug, river["name"], "osm"))
        heads = {tuple(line[0]) for line in river["lines"]}
        points = max((network.upstream(head) for head in heads), key=length_km, default=[])
        if length_km(points) >= MIN_KM and not all(in_box(p) for p in points):
            features.append(feature(points, slug, river["name"], "osm"))
        if river["parent"] is None and river["name"] in traces["streams"]:
            features.append(feature(traces["streams"][river["name"]], slug, river["name"], "dem"))
    for way in ways.values():
        if "Arish" in way["tags"].get("name:en", ""):
            features.append(feature(way["pts"], None, ARISH, "osm"))
    for gap in traces["arish_gaps"]:
        features.append(feature(gap, None, ARISH, "dem"))
    json.dump({"type": "FeatureCollection", "features": features}, open(out_path, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    summary = collections.Counter()
    for f in features:
        summary[f["properties"]["n"], f["properties"]["src"]] += round(length_km(f["geometry"]["coordinates"]))
    print(summary.most_common())


if __name__ == "__main__":
    main()
