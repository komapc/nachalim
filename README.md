# Nachalim

Interactive map of the streams and rivers (נחלים) of Israel, in Hebrew. Click a stream to see its basin, where it flows, its tributaries and a Wikipedia summary.

## Run locally

```sh
python3 -m http.server 8000 -d site
```

## Rebuild the data

```sh
scripts/fetch_osm.sh
python3 scripts/build_rivers.py raw/ways.json raw/sinks.json raw/out
PYTHONPATH=scripts python3 scripts/enrich_wiki.py raw/out/rivers.json raw/wiki_cache.json site/data
```

- `build_rivers.py` groups named OpenStreetMap waterways into streams, follows the flow downstream to find each stream's parent, and classifies the outlet. Corrections go in `scripts/overrides.json`.
- `enrich_wiki.py` adds Hebrew Wikipedia summaries and writes `site/data/`.

Flow type comes from `overrides.json`, then the opening of the Hebrew Wikipedia article, then OpenStreetMap tags, whose `intermittent` tag is often wrong. Arabic text is removed from the summaries, and base-map labels are limited to Hebrew names.

A basin here is the set of streams that reach the same top-level stream. Streams whose outlet cannot be traced are shown as unidentified rather than guessed.

## Aquifers

`site/data/aquifers.json` is written by hand and the rebuild scripts do not touch it. The polygons are schematic: they follow the wording of the [basin descriptions](https://www.jewishvirtuallibrary.org/groundwater-basins-in-israel) credited to the Geological Survey of Israel, and were not traced from any published map. A stream is linked to an aquifer only where that source, its Wikipedia summary or a named OpenStreetMap spring supports the link, so the lists are partial.

## Licences

- Stream geometry: © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright). `site/data/rivers.geojson` and the derived topology in `site/data/info.json` are a derivative database under the same licence.
- Summaries in `site/data/info.json`: Hebrew Wikipedia, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- Base map: [OpenFreeMap](https://openfreemap.org), © OpenMapTiles, © OpenStreetMap. Leaflet: BSD-2-Clause. MapLibre GL JS: BSD-3-Clause.
