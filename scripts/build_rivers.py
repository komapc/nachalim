#!/usr/bin/env python3
"""Build river entities with downstream parents and basins from raw OSM exports.

Usage: build_rivers.py WAYS_JSON SINKS_JSON OUT_DIR
Writes to OUT_DIR, standard library only:
  rivers.json   attributes and geometry, the input of the next pipeline steps
  skipped.json  way names that NAME_RE rejected, with counts: review it for streams
                the filter should have kept

An entity is one named stream: OSM ways with the same name that lie close together
or share a Wikidata item. Its parent is the entity its flow runs into; a stream with
no parent is a root and ends in a sink (a sea or lake), or in None if the walk found
neither. The steps run in the order listed in main().
"""
import collections
import json
import math
import pathlib
import re
import sys

NAME_RE = re.compile(r"^(נחל|נהר|ואדי|וואדי|ערוץ|יובל|עין)\b|הירדן|ירמוך")
SNAP_M = 120  # a way ending this close to another one is taken to flow into it
SAME_STREAM_M = 3000  # same-named ways this close are pieces of one stream
OVERRIDES_PATH = pathlib.Path(__file__).with_name("overrides.json")


def read_json(path):
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, separators=(",", ":"))


def is_hebrew(text):
    return any("֐" <= c <= "׿" for c in text)


def name_of(tags):
    name = tags.get("name:he") or tags.get("name", "")
    name = re.sub("[\u0591-\u05c7]", "", name)  # strip niqqud
    return name.strip() if is_hebrew(name) else None


def dist_m(a, b):
    """Equirectangular distance between (lon, lat) points, in metres."""
    x = math.radians(b[0] - a[0]) * math.cos(math.radians((a[1] + b[1]) / 2))
    y = math.radians(b[1] - a[1])
    return math.hypot(x, y) * 6371000


def length_km(points):
    return sum(dist_m(p, q) for p, q in zip(points, points[1:])) / 1000


def simplify(points, tolerance=0.00015):
    """Douglas-Peucker in degrees; keeps endpoints."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        ax, ay = points[lo]
        bx, by = points[hi]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-12
        best, at = 0, None
        for i in range(lo + 1, hi):
            d = abs(dy * (points[i][0] - ax) - dx * (points[i][1] - ay)) / norm
            if d > best:
                best, at = d, i
        if at is not None and best > tolerance:
            keep[at] = True
            stack += [(lo, at), (at, hi)]
    return [p for p, k in zip(points, keep) if k]


class Grid:
    """Bucket points for fixed-radius lookups."""

    def __init__(self, cell=0.01):
        self.cell = cell
        self.buckets = collections.defaultdict(list)

    def _key(self, p):
        return int(p[0] // self.cell), int(p[1] // self.cell)

    def add(self, p, value):
        self.buckets[self._key(p)].append((p, value))

    def near(self, p, radius_m):
        reach = math.ceil(radius_m / 111000 / self.cell / 0.8)
        cx, cy = self._key(p)
        for ix in range(cx - reach, cx + reach + 1):
            for iy in range(cy - reach, cy + reach + 1):
                for q, value in self.buckets.get((ix, iy), ()):
                    if dist_m(p, q) <= radius_m:
                        yield q, value


def load_ways(path):
    ways = []
    for el in read_json(path)["elements"]:
        geom = el.get("geometry")
        if not geom or len(geom) < 2:
            continue
        pts = [(round(g["lon"], 6), round(g["lat"], 6)) for g in geom]
        ways.append({"id": el["id"], "tags": el["tags"], "pts": pts, "entity": None})
    return ways


# Lake extents as (min_lon, min_lat, max_lon, max_lat): OSM bounds of the lake
# relations, widened for the receded Dead Sea shore and its southern basin.
LAKES = {
    "kinneret": (35.50, 32.69, 35.665, 32.91),
    "dead": (35.33, 30.95, 35.62, 31.80),
    "hula": (35.585, 33.085, 35.635, 33.12),
}
COAST_RADIUS_M = 2500
# When a stream's ways end in different places, the lowest final sink wins.
SINK_RANK = {"dead": 0, "gulf": 0, "yotvata": 0, "med": 0, "kinneret": 1, "hula": 2}
PARENT_RANK = 3  # a parent stream counts for less than reaching a sink directly
DEAD_END_RANK = 6


def load_sinks(path):
    """Return {"med"|"gulf": Grid of coastline points}."""
    grids = {"med": Grid(0.02), "gulf": Grid(0.02)}
    for el in read_json(path)["elements"]:
        if el.get("tags", {}).get("natural") != "coastline":
            continue
        for g in el.get("geometry", []):
            p = (g["lon"], g["lat"])
            grids["gulf" if p[1] < 29.8 and p[0] > 34.6 else "med"].add(p, 1)
    return grids


def classify_sink(point, grids):
    """Name the sink at a stream's last point, or None if it is not near any."""
    lon, lat = point
    for sink, (x0, y0, x1, y1) in LAKES.items():
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            return sink
    for sink, grid in grids.items():
        if next(grid.near(point, COAST_RADIUS_M), None):
            return sink
    if lat < 29.95 and 34.95 <= lon < 35.2:
        # Yotvata basin: a closed depression, 30 m deep on Copernicus GLO-30 (floor 48 m,
        # lowest rim 77 m) and described as having no outlet. Floods do not reach the sea.
        if lat >= 29.74:
            return "yotvata"
        # Southern Arava: streams fade out on the valley floor, south of the divide.
        return "gulf"
    return None


def build_entities(ways):
    """Group ways into streams. Returns (entities, Counter of rejected names)."""
    by_name = collections.defaultdict(list)
    skipped = collections.Counter()
    for way in ways:
        name = name_of(way["tags"])
        if not name:
            continue
        if NAME_RE.search(name):
            by_name[name].append(way)
        else:
            skipped[name] += 1

    entities = []
    for name, members in by_name.items():
        parent = list(range(len(members)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, a in enumerate(members):
            for j in range(i + 1, len(members)):
                b = members[j]
                same_qid = a["tags"].get("wikidata") and a["tags"].get("wikidata") == b["tags"].get("wikidata")
                ends = ((a["pts"][0], b["pts"][0]), (a["pts"][0], b["pts"][-1]),
                        (a["pts"][-1], b["pts"][0]), (a["pts"][-1], b["pts"][-1]))
                if same_qid or any(dist_m(p, q) <= SAME_STREAM_M for p, q in ends):
                    parent[find(i)] = find(j)
        groups = collections.defaultdict(list)
        for i, way in enumerate(members):
            groups[find(i)].append(way)
        for group in groups.values():
            entity = {"name": name, "ways": group, "idx": len(entities)}
            for way in group:
                way["entity"] = entity["idx"]
            entities.append(entity)
    return entities, skipped


class Network:
    """The waterway graph, for following the flow from one way to the next."""

    def __init__(self, ways):
        self.ways = ways
        self.at_node = collections.defaultdict(list)
        self.grid = Grid()
        for w, way in enumerate(ways):
            last = len(way["pts"]) - 1
            for i, p in enumerate(way["pts"]):
                if i < last:
                    self.at_node[p].append((w, i))
                    self.grid.add(p, (w, i))

    def downstream(self, point, exclude):
        """Ways continuing from point. Exact topology first, then a short snap."""
        found = [c for c in self.at_node.get(point, ()) if c[0] not in exclude]
        if found:
            return found
        return [v for _, v in self.grid.near(point, SNAP_M) if v[0] not in exclude]

    def rank(self, candidate, own):
        """Prefer staying on this stream, then any named stream, then rivers over streams."""
        way = self.ways[candidate[0]]
        kind = way["tags"].get("waterway")
        return (way["entity"] == own, way["entity"] is not None,
                kind == "river", kind in ("stream", "wadi"))

    def walk(self, way_index, own):
        """Follow flow from a way's end. Returns (next_entity, final_point)."""
        seen = {way_index}
        point = self.ways[way_index]["pts"][-1]
        for _ in range(5000):
            candidates = self.downstream(point, seen)
            if not candidates:
                return None, point
            best = max(candidates, key=lambda c: self.rank(c, own))
            way = self.ways[best[0]]
            if way["entity"] is not None and way["entity"] != own:
                return way["entity"], point
            seen.add(best[0])
            point = way["pts"][-1]
        return None, point


def outlet_rank(option):
    target, sink, _ = option
    if sink:
        return SINK_RANK[sink]
    return PARENT_RANK if target is not None else DEAD_END_RANK


def resolve(entities, ways, grids):
    """Set each entity's parent, sink and mouth by walking downstream from its ways."""
    net = Network(ways)
    options = collections.defaultdict(list)
    for w, way in enumerate(ways):
        own = way["entity"]
        if own is None:
            continue
        target, end = net.walk(w, own)
        sink = classify_sink(end, grids) if target is None else None
        options[own].append((target, sink, end))
    for entity in entities:
        entity["parent"], entity["sink"], entity["mouth"] = min(options[entity["idx"]], key=outlet_rank)

    # Break any cycles created by mis-digitised flow direction.
    for entity in entities:
        seen, node = set(), entity
        while node["parent"] is not None:
            if node["idx"] in seen:
                node["parent"] = None
                break
            seen.add(node["idx"])
            node = entities[node["parent"]]
    # Cycle breaking can leave a root with no sink: classify its own mouth.
    for entity in entities:
        if entity["parent"] is None and entity["sink"] is None:
            entity["sink"] = classify_sink(entity["mouth"], grids)


def merge_same_name(entities):
    """Fold a fragment into its parent when both carry the same name."""
    alive = {e["idx"]: e for e in entities}
    moved = {}

    def live(idx):
        while idx not in alive:
            idx = moved[idx]
        return idx

    for entity in entities:
        parent = entity["parent"]
        if parent is None:
            continue
        parent = live(parent)
        if parent != entity["idx"] and alive[parent]["name"] == entity["name"]:
            alive[parent]["ways"] += entity["ways"]
            moved[entity["idx"]] = parent
            del alive[entity["idx"]]
    for entity in alive.values():
        if entity["parent"] is not None:
            entity["parent"] = live(entity["parent"])
    return moved


def apply_overrides(entities):
    """Apply scripts/overrides.json, the hand-made corrections, by stream name."""
    by_name = collections.defaultdict(list)
    for entity in entities:
        by_name[entity["name"]].append(entity)
    for rule in read_json(OVERRIDES_PATH):
        for entity in by_name.get(rule["name"], []):
            # Outlet research applies only to the untraced stream, not to namesakes.
            if "via" in rule:
                if entity["parent"] is not None or entity["sink"]:
                    continue
                entity["via"] = rule["via"]
            if "parent" in rule:
                targets = by_name.get(rule["parent"], [])
                entity["parent"] = min(targets, key=lambda t: dist_m(entity["mouth"], t["mouth"]))["idx"] if targets else None
            if "sink" in rule:
                entity["sink"] = rule["sink"]
                entity["parent"] = None
            if "flow" in rule:
                entity["flow"] = rule["flow"]


def summarize(entity, entities):
    """The rivers.json record of one entity."""
    root = entity
    while root["parent"] is not None:
        root = entities[root["parent"]]
    tags = collections.Counter()
    total = wet = dry = 0
    for way in entity["ways"]:
        for key in ("wikidata", "wikipedia", "name:en"):
            if way["tags"].get(key):
                tags[(key, way["tags"][key])] += 1
        km = length_km(way["pts"])
        total += km
        if way["tags"].get("intermittent") == "no" or way["tags"].get("seasonal") == "no":
            wet += km
        elif way["tags"].get("intermittent") == "yes":
            dry += km
    best = {}  # the most common value of each tag
    for (key, value), _ in tags.most_common():
        best.setdefault(key, value)
    return {
        "id": entity["idx"], "name": entity["name"],
        "parent": entity["parent"],
        "root": root["idx"], "sink": root["sink"],
        "km": round(total, 1), "perennial_km": round(wet, 1), "intermittent_km": round(dry, 1),
        "mouth": entity["mouth"], "tags": best, "flow": entity.get("flow"), "via": entity.get("via"),
        "lines": [[[round(x, 5), round(y, 5)] for x, y in simplify(w["pts"])] for w in entity["ways"]],
    }


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    ways_path, sinks_path, out_dir = sys.argv[1:4]
    ways = load_ways(ways_path)
    grids = load_sinks(sinks_path)
    entities, skipped = build_entities(ways)
    resolve(entities, ways, grids)
    moved = merge_same_name(entities)
    entities = [e for e in entities if e["idx"] not in moved]
    remap = {e["idx"]: i for i, e in enumerate(entities)}
    for e in entities:
        e["idx"] = remap[e["idx"]]
        if e["parent"] is not None:
            e["parent"] = remap[e["parent"]]
    apply_overrides(entities)

    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    write_json(f"{out_dir}/rivers.json", [summarize(e, entities) for e in entities])
    write_json(f"{out_dir}/skipped.json", skipped.most_common())


if __name__ == "__main__":
    main()
