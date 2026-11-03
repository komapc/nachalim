#!/usr/bin/env python3
"""Connect outlets over OSM ways that do not join end to end.

Usage: join_outlets.py RAW_WAYS RAW_OUTSIDE_DIR OUT_JSON
build_outside.py walks ways only from end to end and in their digitised direction, but
in Sinai the ways meet mid-way or point upstream. This finds the shortest way along them,
touching vertices and ignoring direction. It never leaves the ways: a pair with no such
path stops with an error. The result is committed, so a rebuild does not need this script.

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
    pathlib.Path(out_path).write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf8")
    for kind, lines in result.items():
        for name, line in lines.items():
            print(kind, name, round(length_km(line), 1), "km")


if __name__ == "__main__":
    main()
