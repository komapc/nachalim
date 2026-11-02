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

A basin here is the set of streams that reach the same top-level stream. Streams whose outlet cannot be traced are shown as unidentified rather than guessed.

## Licences

- Stream geometry: © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright). `site/data/rivers.geojson` and the derived topology in `site/data/info.json` are a derivative database under the same licence.
- Summaries in `site/data/info.json`: Hebrew Wikipedia, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- Base map: © OpenStreetMap. Leaflet: BSD-2-Clause.
