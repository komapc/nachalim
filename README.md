# Nachalim

Interactive map of the streams and rivers (נחלים) of Israel, in Hebrew, at <https://nachalim.lipu.dev/>. Click a stream to see its basin, where it flows, its tributaries and a Wikipedia summary. Groundwater aquifers can be shown under the streams.

## Run locally

```sh
python3 -m http.server 8000 -d site
```

The site has no build step: `site/` is served as it is, and GitHub Pages deploys it on every push to `main` (`.github/workflows/pages.yml`).

## Layout

| Path | What it is |
| --- | --- |
| `site/app.js` | All of the interface: map, panel, search, links |
| `site/consent.js` | Consent banner. Google Analytics loads only after "allow"; the Measurement ID is `data-ga` in `index.html` |
| `site/data/` | The data the page loads, see below |
| `site/vendor/` | Leaflet and MapLibre, kept in the repository |
| `scripts/` | The data pipeline, and `make_og.py` and `make_icons.py`, which render the link preview and the favicons and need Playwright |
| `raw/` | Downloads and intermediate files, git-ignored |

## Rebuild the data

```sh
scripts/fetch_osm.sh
python3 scripts/build_rivers.py raw/ways.json raw/sinks.json raw/out
python3 scripts/enrich_wiki.py raw/out/rivers.json raw/wiki_cache.json site/data
python3 scripts/build_outside.py raw/ways.json raw/outside raw/out/rivers.json site/data/info.json scripts/outlet_joins.json site/data/outside.geojson
```

With unchanged downloads and Wikipedia cache the output is byte-identical, so after a code change `git diff site/data` shows exactly what the change did.

- `build_rivers.py` groups named OpenStreetMap waterways into streams, follows the flow downstream to find each stream's parent, and classifies the outlet. Corrections go in `scripts/overrides.json`. It also writes `skipped.json`, the way names it rejected.
- `enrich_wiki.py` adds Hebrew Wikipedia summaries and writes `rivers.geojson` and `info.json`. Arabic text is removed from the summaries.
- `build_outside.py` continues streams past the download box, as thin lines. They follow OpenStreetMap ways, except for the stretch of Wadi Rum described below. Where the ways do not join end to end, `scripts/outlet_joins.json` holds the path along them, which `join_outlets.py` finds and which is committed. A line stops where the ways stop: Nahal Lavan about 4 km short of Wadi al-Arish and Wadi al-Arish about 350 m short of the sea. The zoom-out limit still fits Israel; only panning reaches these lines.

Each rule in `overrides.json` names a stream and can set `sink`, `parent`, `flow` and `via`.

## Data decisions

Flow type comes from `overrides.json`, then the opening of the Hebrew Wikipedia article, then OpenStreetMap tags, whose `intermittent` tag is often wrong.

A basin here is the set of streams that reach the same top-level stream. Where an OpenStreetMap line stops short of its outlet, `overrides.json` records the outlet with `via`: `wiki` means Hebrew Wikipedia says so, `dem` means it was traced downhill on the Copernicus GLO-30 elevation model, and `osm` means OpenStreetMap ways lead there past the download box. `route` means the same for Wadi Rum, whose line is also drawn: the only traced line on the map, about 34 km over the Hisma where OpenStreetMap has none, then along OpenStreetMap ways. Those rules apply only to a stream that is still untraced, not to namesakes. A stream whose outlet could not be established would be shown grey and explained in the legend, rather than guessed; at present there are none.

Twelve streams of the southern Arava end in the Yotvata salt flat, shown as a closed basin rather than the Gulf of Eilat. On Copernicus GLO-30 at full 30 m the depression covers about 97 km², with a floor at 48 m and the lowest rim at 77 m, and Hebrew Wikipedia describes the flat as a closed depression. The Evrona flat further south shows no such rim, which fits published work that it is now open, so its streams stay in the Gulf group.

## Data files

`info.json` maps a stream's id to a record with short keys, which keep the file small:

| Key | Meaning |
| --- | --- |
| `s` | Slug, used in the page address |
| `n` | Hebrew name |
| `en` | English name, if known |
| `d` | Drainage, which sets the colour: `med`, `jordan`, `dead`, `gulf`, `closed`, `unknown` |
| `r` | Id of the top-level stream of its basin |
| `p` | Id of the parent stream, `null` for a top-level stream |
| `c` | Ids of its tributaries, longest first |
| `k` | Length in km |
| `sink` | Where its basin ends: `med`, `gulf`, `dead`, `kinneret`, `hula`, `arish`, `yotvata`, or `null` |
| `f` | Flow: `perennial`, `mixed`, `intermittent`, or absent if unknown |
| `v` | How the outlet was established when the line stops short: `wiki`, `dem`, `osm` or `route` |
| `w`, `x` | Wikipedia page title and summary |

`rivers.geojson` holds the geometry, with properties `i` (the id), `d`, `k`, `n` and `f`. `outside.geojson` holds the lines past the box, with `s` and `n`.

`aquifers.json` is written by hand and the rebuild scripts do not touch it. Each aquifer has `id`, `name`, `color`, `ring` (the polygon, as `[lng, lat]`), `label` (where its name goes on the map), `rock`, `note`, `rivers` (slugs of linked streams) and `empty` (the text shown when `rivers` is empty), and optionally `recharge`, `production` and `discharge`.

## Aquifers

The polygons are schematic. They follow the wording of the [basin descriptions](https://www.jewishvirtuallibrary.org/groundwater-basins-in-israel) credited to the Geological Survey of Israel, and their boundaries were adjusted by eye to the basin map in the lecture "מבוא להידרולוגיה ולמשק המים הישראלי" (course on stream restoration, slide 22). So the basins tile the country without gaps or overlaps, as on that map: the coastal and Yarkon-Taninim basins lie side by side, Yarkon-Taninim reaches into the Negev, and the Gaza Strip is left blank. They were not digitised from that map. A stream is linked to an aquifer only where one of these sources, its Wikipedia summary or a named OpenStreetMap spring supports the link, so the lists are partial.

The streams are drawn on a canvas that lies over the aquifers and would catch every click, so the polygons take no clicks at all and `clickMap` in `app.js` tests the point against their rings instead. While an aquifer is open or "show all aquifers" is on:

- a click on an aquifer opens it;
- a click outside all of them closes the card;
- dimmed streams pass their clicks on to the aquifer below (`clickStream`), and only the streams of the open aquifer can be opened from the map.

## Testing

```sh
pip install playwright==1.61.0 && playwright install chromium
python3 -m unittest discover tests
```

`tests/test_map_clicks.py` covers clicks on the map, and runs on every pull request. It serves `site/` itself and needs no network. Add new map tests with real mouse events: `map.fire("click")` skips the streams lying on top and has hidden a bug that way.

After a change to the pipeline, rebuild and read `git diff site/data`.

## Licences

- Stream geometry: © OpenStreetMap contributors, [ODbL](https://www.openstreetmap.org/copyright). `site/data/rivers.geojson` and the derived topology in `site/data/info.json` are a derivative database under the same licence.
- Summaries in `site/data/info.json`: Hebrew Wikipedia, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
- Elevation used to trace outlets (not redistributed): Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA.
- Base map: [OpenFreeMap](https://openfreemap.org), © OpenMapTiles, © OpenStreetMap. Leaflet: BSD-2-Clause. MapLibre GL JS: BSD-3-Clause.
