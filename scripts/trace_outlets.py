#!/usr/bin/env python3
"""Trace outlets the OSM network does not connect, downhill on Copernicus GLO-30.

Usage: trace_outlets.py RAW_OUTSIDE_DIR RIVERS_JSON OUT_JSON
Needs rasterio and numpy. The result is committed, so a normal rebuild does not
need this script or the elevation data.
"""
import heapq
import json
import pathlib
import sys

import numpy as np
import rasterio
from rasterio.enums import Resampling

FACTOR = 8  # about 240 m cells: enough for valleys, and a few megabytes of reads
STEP = FACTOR / 3600
SINAI = (33.3, 30.0, 35.0, 31.4)
JORDAN = (34.8, 29.0, 36.0, 30.0)
WALK_ENDS = {"נחל לבן": [33.848, 31.145], "נחל בתור": [34.008, 30.439]}
# OSM has a break here between the stream's lines and the rest of its course.
JOINS = {"נחל בתור": [34.12199, 30.30198]}


def tile_url(lat, lon):
    name = f"Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM"
    return f"/vsicurl/https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"


def load(box):
    west, south, east, north = box
    rows, cols = round((north - south) / STEP), round((east - west) / STEP)
    grid = np.full((rows, cols), np.nan, "f4")
    for lat in range(int(south), int(np.ceil(north))):
        for lon in range(int(west), int(np.ceil(east))):
            with rasterio.open(tile_url(lat, lon)) as src:
                size_y, size_x = round(src.height / FACTOR), round(src.width / FACTOR)
                data = src.read(1, out_shape=(size_y, size_x), resampling=Resampling.average)
            for row in range(size_y):
                i = int((north - (lat + 1 - (row + .5) / size_y)) / STEP)
                if 0 <= i < rows:
                    j = ((lon + (np.arange(size_x) + .5) / size_x - west) / STEP).astype(int)
                    keep = (j >= 0) & (j < cols)
                    grid[i, j[keep]] = data[row, keep]
    return grid


def flood(grid, box, start, is_target):
    """Priority flood from start; returns the lowest-barrier path to a target."""
    west, _, _, north = box
    cell = lambda p: (int((north - p[1]) / STEP), int((p[0] - west) / STEP))
    point = lambda c: [round(west + (c[1] + .5) * STEP, 4), round(north - (c[0] + .5) * STEP, 4)]
    first = cell(start)
    seen, previous, order = {first}, {}, 0
    queue = [(float(grid[first]), order, first)]
    while queue:
        height, _, here = heapq.heappop(queue)
        if here != first and is_target(here, height):
            path = [here]
            while path[-1] in previous:
                path.append(previous[path[-1]])
            return [point(c) for c in reversed(path)]
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                near = (here[0] + di, here[1] + dj)
                if near in seen or not (0 <= near[0] < grid.shape[0] and 0 <= near[1] < grid.shape[1]):
                    continue
                if np.isnan(grid[near]):
                    continue
                seen.add(near)
                previous[near] = here
                order += 1
                heapq.heappush(queue, (float(grid[near]), order, near))
    raise RuntimeError(f"no outlet found from {start}")


def main():
    outside_dir, rivers_path, out_path = sys.argv[1:4]
    rivers = json.load(open(rivers_path, encoding="utf-8"))
    mouth = {r["name"]: r["mouth"] for r in rivers if r["parent"] is None}
    arish = []
    for way in json.load(open(pathlib.Path(outside_dir) / "west.json", encoding="utf-8"))["elements"]:
        if "Arish" in way.get("tags", {}).get("name:en", ""):
            arish.append([[p["lon"], p["lat"]] for p in way["geometry"]])
    west, _, _, north = SINAI
    grid = load(SINAI)
    cells = {(int((north - p[1]) / STEP), int((p[0] - west) / STEP)) for line in arish for p in line}
    on_arish = lambda cell, height: cell in cells
    at_sea = lambda cell, height: height <= 1
    traces = {"arish": arish, "arish_gaps": [], "streams": {}}
    # Join the OSM pieces of Wadi al-Arish from its head to the sea.
    pieces = sorted(arish, key=lambda line: min(p[1] for p in line))
    for piece, following in zip(pieces, pieces[1:]):
        ends = {(int((north - p[1]) / STEP), int((p[0] - west) / STEP)) for p in following}
        low = max((piece[0], piece[-1]), key=lambda p: p[1])
        if (int((north - low[1]) / STEP), int((low[0] - west) / STEP)) in ends:
            continue  # the pieces already touch
        traces["arish_gaps"].append(flood(grid, SINAI, low, lambda c, h, e=ends: c in e))
    last = max((pieces[-1][0], pieces[-1][-1]), key=lambda p: p[1])
    traces["arish_gaps"].append(flood(grid, SINAI, last, at_sea))
    for name in ("נחל לוץ", "נחל קדש ברנע"):
        traces["streams"][name] = flood(grid, SINAI, mouth[name], on_arish)
    # These two continue along OSM ways first, as far as build_outside.py walks them.
    for name, end in WALK_ENDS.items():
        traces["streams"][name] = flood(grid, SINAI, end, on_arish)
    traces["joins"] = {}
    for name, start in JOINS.items():
        target = (int((north - mouth[name][1]) / STEP), int((mouth[name][0] - west) / STEP))
        traces["joins"][name] = flood(grid, SINAI, start, lambda c, h, t=target: c == t)
    jordan = load(JORDAN)
    traces["streams"]["ואדי רם"] = flood(jordan, JORDAN, mouth["ואדי רם"], at_sea)
    del traces["arish"]  # kept in raw/outside; build_outside.py reads the OSM pieces there
    json.dump(traces, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
