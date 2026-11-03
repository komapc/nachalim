#!/usr/bin/env python3
"""Connect outlets over OSM ways that do not join end to end, and draw Wadi Rum to the Gulf.

Usage: join_outlets.py RAW_WAYS RAW_OUTSIDE_DIR OUT_JSON
build_outside.py walks ways only from end to end and in their digitised direction, but
in Sinai the ways meet mid-way or point upstream. This finds the shortest way along them,
touching vertices and ignoring direction. A pair with no such path stops with an error.
Only Wadi Rum leaves the ways, where OSM has no line: see RUM_DEM and RUM_GAP.
The result is committed, so a rebuild does not need this script.

Writes JSON read by build_outside.py, every line a list of [lon, lat]:
  streams  {name: line} from where a stream ends to its outlet
  joins    {name: line} over a break inside one stream's course
"""
import collections
import heapq
import json
import pathlib
import sys

from build_rivers import length_km, read_json

ARISH_TOP = (34.15412, 30.69379)  # the upper end of the mapped Wadi al-Arish
STREAMS = {
    "נחל קדש ברנע": ((34.1597, 30.6697), ARISH_TOP),
    "נחל לוץ": ((34.16061, 30.64911), ARISH_TOP),
    "נחל בתור": ((34.0081, 30.43915), ARISH_TOP),
}
JOINS = {"נחל בתור": ((34.12199, 30.30198), (34.07304, 30.34018))}
KINDS = {"river", "stream", "wadi"}
RUM = "ואדי רם"
# Flow route on the filled Copernicus GLO-30 model, from Wadi Rum's north end to Wadi al Uitm.
RUM_DEM = [
    (35.45471, 29.67749), (35.45600, 29.67900), (35.45400, 29.68000), (35.45400, 29.68100),
    (35.45100, 29.68400), (35.44900, 29.68300), (35.44300, 29.68800), (35.44400, 29.68900),
    (35.44300, 29.69000), (35.44400, 29.69100), (35.44400, 29.69700), (35.44100, 29.70000),
    (35.44100, 29.70200), (35.43800, 29.70400), (35.43700, 29.70600), (35.43400, 29.70600),
    (35.43100, 29.70800), (35.42900, 29.70600), (35.42100, 29.70700), (35.41900, 29.70400),
    (35.41600, 29.70600), (35.41100, 29.70000), (35.40900, 29.70300), (35.41000, 29.70400),
    (35.41000, 29.70600), (35.40900, 29.70700), (35.40700, 29.70700), (35.40600, 29.70600),
    (35.40600, 29.70300), (35.40100, 29.70200), (35.39800, 29.70600), (35.39700, 29.70600),
    (35.39600, 29.70400), (35.39400, 29.70600), (35.39300, 29.70400), (35.39100, 29.70700),
    (35.38900, 29.70600), (35.38700, 29.70800), (35.38300, 29.70900), (35.38200, 29.71000),
    (35.38300, 29.71100), (35.38000, 29.71300), (35.38100, 29.71400), (35.38100, 29.71700),
    (35.38000, 29.71800), (35.37800, 29.71600), (35.37700, 29.71700), (35.37600, 29.71600),
    (35.37400, 29.71600), (35.37100, 29.71900), (35.36400, 29.71900), (35.36300, 29.72000),
    (35.36200, 29.71900), (35.36000, 29.72000), (35.35800, 29.71800), (35.35400, 29.71700),
    (35.35200, 29.71900), (35.34800, 29.71700), (35.34700, 29.71800), (35.34300, 29.71700),
    (35.34100, 29.71900), (35.34000, 29.71800), (35.33800, 29.72000), (35.33300, 29.72100),
    (35.32900, 29.72400), (35.32700, 29.72200), (35.32200, 29.72100), (35.32100, 29.72000),
    (35.31700, 29.72000), (35.31300, 29.71800), (35.30900, 29.71800), (35.30400, 29.71400),
    (35.30300, 29.71600), (35.30000, 29.71600), (35.29600, 29.71100), (35.28900, 29.70600),
    (35.28100, 29.70600), (35.28000, 29.70700), (35.27900, 29.70600), (35.27700, 29.70700),
    (35.27400, 29.70400), (35.27400, 29.70200), (35.27200, 29.70000), (35.26900, 29.69400),
    (35.26100, 29.68700), (35.26000, 29.68400), (35.25600, 29.68000), (35.25400, 29.68000),
    (35.24900, 29.67700), (35.24700, 29.67400), (35.24600, 29.67600), (35.24400, 29.67600),
    (35.24300, 29.67400), (35.23800, 29.67000), (35.23300, 29.66900), (35.23200, 29.66800),
    (35.23300, 29.66700), (35.23300, 29.66400), (35.23200, 29.66300), (35.22800, 29.66300),
    (35.22600, 29.66000), (35.22400, 29.65900), (35.22600, 29.65800), (35.22400, 29.65700),
    (35.22173, 29.65583),
]
RUM_UITM = (RUM_DEM[-1], (35.02521, 29.66494))  # Wadi al Uitm, down to the Arava
RUM_GAP = (35.01847, 29.66828)  # the nearest Arava way, 750 m across the plain
RUM_SEA = (34.97169, 29.54524)  # where that way network meets the coast


def graph(ways_path, outside_dir):
    edges = collections.defaultdict(dict)
    for path in [ways_path, *sorted(pathlib.Path(outside_dir).glob("*.json"))]:
        for way in read_json(path)["elements"]:
            if way.get("geometry") and way.get("tags", {}).get("waterway") in KINDS:
                points = [(round(p["lon"], 5), round(p["lat"], 5)) for p in way["geometry"]]
                for a, b in zip(points, points[1:]):
                    edges[a][b] = edges[b][a] = length_km([a, b])
    return edges


def shortest(edges, start, end):
    if start not in edges or end not in edges:
        sys.exit(f"not on a way: {start if start not in edges else end}")
    distance, previous, queue = {start: 0}, {}, [(0, start)]
    while queue:
        km, node = heapq.heappop(queue)
        if node == end:
            path = [end]
            while path[-1] != start:
                path.append(previous[path[-1]])
            return [list(point) for point in reversed(path)]
        if km > distance[node]:
            continue
        for other, step in edges[node].items():
            if km + step < distance.get(other, float("inf")):
                distance[other], previous[other] = km + step, node
                heapq.heappush(queue, (km + step, other))
    sys.exit(f"no path along ways from {start} to {end}")


def main():
    ways_path, outside_dir, out_path = sys.argv[1:4]
    edges = graph(ways_path, outside_dir)
    result = {
        "streams": {name: shortest(edges, *ends) for name, ends in STREAMS.items()},
        "joins": {name: shortest(edges, *ends) for name, ends in JOINS.items()},
    }
    uitm = shortest(edges, *RUM_UITM)
    arava = shortest(edges, RUM_GAP, RUM_SEA)
    result["streams"][RUM] = [list(point) for point in RUM_DEM[:-1]] + uitm + arava
    pathlib.Path(out_path).write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf8")
    for kind, lines in result.items():
        for name, line in lines.items():
            print(kind, name, round(length_km(line), 1), "km")


if __name__ == "__main__":
    main()
