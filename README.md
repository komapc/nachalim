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
PYTHONPATH=scripts python3 scripts/build_outside.py raw/ways.json raw/outside raw/out/rivers.json site/data/info.json scripts/outlet_traces.json site/data/outside.geojson
```

- `build_rivers.py` groups named OpenStreetMap waterways into streams, follows the flow downstream to find each stream's parent, and classifies the outlet. Corrections go in `scripts/overrides.json`.
- `enrich_wiki.py` adds Hebrew Wikipedia summaries and writes `site/data/`.

Flow type comes from `overrides.json`, then the opening of the Hebrew Wikipedia article, then OpenStreetMap tags, whose `intermittent` tag is often wrong. Arabic text is removed from the summaries, and base-map labels are limited to Hebrew names.

`build_outside.py` continues streams past the download box, as thin lines. They follow OpenStreetMap ways where those connect, and otherwise `scripts/outlet_traces.json`, which `trace_outlets.py` traced downhill on the elevation model and which is committed so a rebuild does not need that data. The zoom-out limit still fits Israel; only panning reaches these lines.

A basin here is the set of streams that reach the same top-level stream. Where an OpenStreetMap line stops short of its outlet, `overrides.json` records the outlet with `via`: `wiki` means Hebrew Wikipedia says so, and `dem` means it was traced downhill on the Copernicus GLO-30 elevation model. Those rules apply only to a stream that is still untraced, not to namesakes. A stream whose outlet could not be established stays grey and is explained in the legend, rather than guessed.

## Aquifers

`site/data/aquifers.json` is written by hand and the rebuild scripts do not touch it. The polygons are schematic: they follow the wording of the [basin descriptions](https://www.jewishvirtuallibrary.org/groundwater-basins-in-israel) credited to the Geological Survey of Israel, and were not traced from any published map. A stream is linked to an aquifer only where that source, its Wikipedia summary or a named OpenStreetMap spring supports the link, so the lists are partial.

## Licences

- Stream geometry: © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright). `site/data/rivers.geojson` and the derived topology in `site/data/info.json` are a derivative database under the same licence.
- Summaries in `site/data/info.json`: Hebrew Wikipedia, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- Elevation used to trace outlets (not redistributed): Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA.
- Base map: [OpenFreeMap](https://openfreemap.org), © OpenMapTiles, © OpenStreetMap. Leaflet: BSD-2-Clause. MapLibre GL JS: BSD-3-Clause.
