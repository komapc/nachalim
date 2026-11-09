"use strict";

// The whole interface: the map, the side panel and the links between them. The data
// files and their keys are described in the README.

// ---- Constants ----

// Analytics event; gtag exists only after the visitor agreed, see consent.js.
const track = (name, params) => window.gtag?.("event", name, params);

// Line colours by where the water ends up. make_og.py repeats the colours.
const DRAINAGE = {
  med: { label: "הים התיכון", color: "#1f78c1" },
  jordan: { label: "הירדן והכנרת", color: "#0b9a8d" },
  dead: { label: "ים המלח", color: "#c9662b" },
  gulf: { label: "מפרץ אילת", color: "#8e4fb8" },
  closed: { label: "אגן סגור: מלחת יטבתה", color: "#b8960c" },
  unknown: { label: "מוצא לא ידוע", color: "#7d8a8e" },
};

const SINK_NAMES = {
  med: "הים התיכון",
  gulf: "מפרץ אילת",
  dead: "ים המלח",
  kinneret: "הכנרת",
  hula: "אגמון החולה",
  arish: "ואדי אל-עריש",
  yotvata: "מלחת יטבתה",
};

const OUTLET_SOURCES = {
  wiki: "המוצא לפי ויקיפדיה, כי קו הנחל במפה נקטע.",
  dem: "קו הנחל במפה נקטע, והמוצא הוסק מגובה השטח (מודל הגובה Copernicus).",
  osm: "קו הנחל במפה נקטע, והמוצא נקבע לפי המשך הוואדיות במפה הפתוחה (OpenStreetMap).",
  route: "ההמשך עד המפרץ משורטט: כ-34 ק\"מ לפי גובה השטח (מודל הגובה Copernicus), ומשם לפי ואדי יותם במפה הפתוחה (OpenStreetMap).",
};

const FLOW_LABELS = {
  perennial: "נחל איתן: זורם כל השנה",
  mixed: "איתן בחלקו",
  intermittent: "נחל אכזב: זורם בעיקר בחורף",
};

const AQUIFER_SOURCE = "https://www.jewishvirtuallibrary.org/groundwater-basins-in-israel";

const details = document.getElementById("details");
const dryToggle = document.getElementById("dry");
const search = document.getElementById("q");
const results = document.getElementById("results");

const ISRAEL = L.latLngBounds([29.47, 34.24], [33.36, 35.92]);
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
const SHIELD_LAYER = /shield/;
const JORDAN_SLUG = "נהר-הירדן";

// How far a line fades when something else is the subject of the map.
const OPACITY_DIMMED = 0.15;
const OPACITY_QUIET = 0.3;

// ---- Map and base map ----

const map = L.map("map", {
  preferCanvas: true,
  zoomControl: false,
  zoomSnap: 0.25,
  wheelPxPerZoomLevel: 120, // the default moves more than a whole level per notch of a mouse wheel
  maxZoom: 18,
  maxBounds: ISRAEL.pad(0.04),
  maxBoundsViscosity: 1,
  renderer: L.canvas({ tolerance: 7 }),
});

// The furthest zoom-out is the one where all of Israel just fits.
function fitIsrael() {
  const wasAtLimit = map.getZoom() <= map.getMinZoom();
  map.options.minZoom = 0; // getBoundsZoom clamps to the current limit
  const minZoom = map.getBoundsZoom(ISRAEL);
  map.setMinZoom(minZoom);
  if (wasAtLimit) map.fitBounds(ISRAEL, { animate: false });
}
map.fitBounds(ISRAEL, { animate: false });
map.setMinZoom(map.getBoundsZoom(ISRAEL));
map.on("resize", fitIsrael);

L.control.zoom({ zoomInTitle: "הגדלה", zoomOutTitle: "הקטנה" }).addTo(map);

// Back to the whole country. It leaves an open card open.
const HomeControl = L.Control.extend({
  options: { position: "topleft" },
  onAdd() {
    const bar = L.DomUtil.create("div", "leaflet-bar");
    const button = L.DomUtil.create("a", "home-control", bar);
    button.href = "#";
    button.role = "button";
    button.title = "הצגת כל הארץ";
    button.setAttribute("aria-label", button.title);
    button.textContent = "⌂";
    L.DomEvent.disableClickPropagation(bar);
    L.DomEvent.on(button, "click", (event) => {
      L.DomEvent.preventDefault(event);
      map.fitBounds(ISRAEL);
    });
    return bar;
  },
});
new HomeControl().addTo(map);

// A diagram under the streams. Their canvas covers this pane and would catch any click
// first, so the polygons are not interactive and clickMap tests the point against them.
map.createPane("aquifers").style.zIndex = 350;
const aquiferRenderer = L.svg({ pane: "aquifers" });

maplibregl.setRTLTextPlugin(new URL("vendor/maplibre/mapbox-gl-rtl-text.js", location.href).href, true);

// Show Hebrew place names only: a place without one simply has no label.
function hebrewOnly(style) {
  // Large country and region names would sit on top of the streams.
  style.layers = style.layers.filter((styleLayer) => !/^label_(country|state)/.test(styleLayer.id));
  for (const styleLayer of style.layers) {
    if (styleLayer.layout?.["text-field"] && !SHIELD_LAYER.test(styleLayer.id)) {
      styleLayer.layout["text-field"] = ["get", "name:he"];
    }
  }
  return style;
}

fetch(BASEMAP_STYLE)
  .then((response) => response.json())
  .then((style) => {
    L.maplibreGL({
      style: hebrewOnly(style),
      attribution: '<a href="https://openfreemap.org">OpenFreeMap</a> &copy; <a href="https://www.openmaptiles.org/">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);
  });

// ---- State ----

// The panel follows from selected and aquifer, of which at most one is set:
//   neither   the overview
//   selected  a stream's card, by id
//   aquifer   an aquifer's card, by entry
// showAllAquifers only adds the aquifers to the map. They are also drawn while one is open.
let info = {}; // id -> stream, from info.json
let layer = null;
let outsideLayer = null;
const outsideBySlug = new Map();
let selected = null;
let filter = null; // drainage key chosen in the legend
let showDry = true;
let aquifers = [];
let aquifer = null;
let aquiferShape = null; // the open aquifer's outline, drawn over allAquifersLayer
let showAllAquifers = false;
let allAquifersLayer = null;
const aquiferBySlug = new Map();
const layersById = new Map();
const idBySlug = new Map();

// ---- Line styles ----

const flows = (flow) => flow === "perennial" || flow === "mixed";

function weightFor(km, zoom) {
  const base = km >= 50 ? 3 : km >= 15 ? 2.2 : km >= 5 ? 1.5 : 1;
  return base + Math.max(0, zoom - 9) * 0.3;
}

// With all aquifers shown and nothing selected, they are the subject of the map.
function riversQuiet() {
  return showAllAquifers && selected === null && !aquifer;
}

function styleFor(feature) {
  const { i, d, k, f } = feature.properties;
  const zoom = map.getZoom();
  const entry = info[i];
  const color = DRAINAGE[d].color;
  let opacity = k < 3 && zoom < 9.5 ? 0.35 : 0.85;
  let weight = weightFor(k, zoom);
  if (filter && d !== filter) opacity = 0.08;
  if (riversQuiet()) opacity = Math.min(opacity, OPACITY_QUIET);
  if (aquifer) {
    if (aquifer.rivers.includes(entry.s)) {
      opacity = 1;
      weight += 2;
    } else {
      opacity = Math.min(opacity, OPACITY_DIMMED);
    }
  }
  if (selected !== null) {
    const sameBasin = entry.r === info[selected].r;
    if (i === selected) {
      opacity = 1;
      weight += 3;
    } else if (sameBasin) {
      opacity = 0.95;
      weight += 0.6;
    } else {
      opacity = Math.min(opacity, OPACITY_DIMMED);
    }
  }
  const dashArray = !flows(f) && zoom >= 10 && i !== selected ? "6 6" : null;
  return { color, weight, opacity, dashArray, lineCap: "round", lineJoin: "round" };
}

// Lines past the data edge follow their stream's state, and are thinner.
function outsideStyle(feature) {
  const { s } = feature.properties;
  const entry = s ? info[idBySlug.get(s)] : null;
  const dry = entry ? !flows(entry.f) : true;
  const drainage = entry ? entry.d : "med";
  let opacity = 0.7;
  let weight = 1.6 + Math.max(0, map.getZoom() - 9) * 0.25;
  if (!showDry && dry) opacity = 0;
  if (filter && drainage !== filter) opacity = 0.08;
  if (riversQuiet()) opacity = Math.min(opacity, OPACITY_QUIET);
  if (aquifer) opacity = Math.min(opacity, OPACITY_DIMMED);
  if (selected !== null) {
    const current = info[selected];
    const sameBasin = entry ? entry.r === current.r : current.sink === "arish";
    if (sameBasin) {
      opacity = 1;
      weight += 1;
    } else {
      opacity = Math.min(opacity, OPACITY_DIMMED);
    }
  }
  return { color: DRAINAGE[drainage].color, weight, opacity, lineCap: "round" };
}

// Brings the map in line with the state. Call it after any change to the state.
function restyle() {
  if (layer) layer.setStyle(styleFor);
  if (outsideLayer) outsideLayer.setStyle(outsideStyle);
  syncAllAquifers();
  if (allAquifersLayer) {
    allAquifersLayer.eachLayer((part) => {
      if (part.aquifer) part.setStyle(allAquifersStyle(part.aquifer));
    });
  }
  if (selected !== null) layersById.get(selected).bringToFront();
  syncNameLabels();
}

// ---- Stream names ----

// A MapLibre layer of its own, above the stream lines, so that lines cannot cover a name.
// Longer streams get a name first. MapLibre zoom levels are one below Leaflet's.
const NAME_TIERS = [
  { id: "names-short", minKm: 0, minZoom: 11.5 },
  { id: "names-medium", minKm: 5, minZoom: 10 },
  { id: "names-long", minKm: 15, minZoom: 8.5 },
  { id: "names-longest", minKm: 40, minZoom: 6 },
];
// Darker than the lines, to read as text, and coloured to differ from the names of places.
const NAME_PAINT = {
  "text-color": ["match", ["get", "d"],
    "med", "#0f5288", "jordan", "#06645c", "dead", "#8a3f17", "gulf", "#62307f", "closed", "#6f5a06", "#4a5356"],
  "text-halo-color": "#fff",
  "text-halo-width": 2.5,
};
let nameMap = null;
let namesReady = false;

function nameLayout(size, font) {
  return {
    "text-field": ["get", "n"],
    "text-font": [font],
    "text-size": size,
    "text-padding": 6,
  };
}

// One point per stream, halfway along its longest line, so that a name stays horizontal.
function namePoints(geojson) {
  const features = geojson.features.map(({ properties, geometry }) => {
    const line = geometry.coordinates.reduce((a, b) => (b.length > a.length ? b : a));
    return { type: "Feature", properties, geometry: { type: "Point", coordinates: line[Math.floor(line.length / 2)] } };
  });
  return { type: "FeatureCollection", features };
}

function addNameLabels(geojson) {
  map.createPane("names").style.zIndex = 450;
  map.getPane("names").style.pointerEvents = "none";
  const labels = L.maplibreGL({
    pane: "names",
    attributionControl: false,
    style: {
      version: 8,
      glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
      sources: { streams: { type: "geojson", data: namePoints(geojson) } },
      layers: [
        ...NAME_TIERS.map(({ id, minZoom }) => ({
          id, type: "symbol", source: "streams", minzoom: minZoom,
          layout: nameLayout(13, "Noto Sans Regular"), paint: NAME_PAINT,
        })),
        {
          id: "names-selected", type: "symbol", source: "streams", filter: ["==", ["get", "i"], -1],
          layout: { ...nameLayout(15, "Noto Sans Bold"), "text-allow-overlap": true }, paint: NAME_PAINT,
        },
      ],
    },
  }).addTo(map);
  nameMap = labels.getMaplibreMap();
  nameMap.on("load", () => {
    namesReady = true;
    syncNameLabels();
  });
}

// Names follow what stands out on the map: a dimmed stream has none.
function namedStreams() {
  return Object.entries(info).filter(([, entry]) => {
    if (!showDry && !flows(entry.f)) return false;
    if (filter && entry.d !== filter) return false;
    if (aquifer) return aquifer.rivers.includes(entry.s);
    if (selected !== null) return entry.r === info[selected].r;
    return true;
  }).map(([id]) => Number(id));
}

function syncNameLabels() {
  if (!namesReady) return;
  const named = ["in", ["get", "i"], ["literal", namedStreams()]];
  for (const { id, minKm } of NAME_TIERS) {
    nameMap.setFilter(id, ["all", [">=", ["get", "k"], minKm], named]);
  }
  nameMap.setFilter("names-selected", ["==", ["get", "i"], selected ?? -1]);
}

// ---- Panel helpers ----

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

// Leaflet puts tooltip text in as HTML, and the names come from OpenStreetMap.
function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function linkButton(text, onclick) {
  return el("button", { class: "link", type: "button", onclick }, text);
}

function riverLink(id) {
  return linkButton(info[id].n, () => select(id, true));
}

// Empties the panel for a card and adds the way back to the overview.
function startCard() {
  details.replaceChildren();
  details.scrollTop = 0;
  details.append(el("div", { class: "back" }, linkButton("→ לכל הנחלים", clearSelection)));
}

// The steps from a stream to the sea: links to parent streams, then plain sink names.

function flowPath(id) {
  const steps = [];
  let current = id;
  while (info[current].p !== null) {
    current = info[current].p;
    steps.push(riverLink(current));
  }
  const sink = info[current].sink;
  const jordan = idBySlug.get(JORDAN_SLUG);
  if (sink === "kinneret" || sink === "hula") {
    steps.push(SINK_NAMES[sink]);
    if (sink === "hula") steps.push("הכנרת");
    if (jordan !== undefined) steps.push(riverLink(jordan));
    steps.push(SINK_NAMES.dead);
  } else if (sink === "arish") {
    steps.push(SINK_NAMES.arish, SINK_NAMES.med);
  } else if (sink) {
    steps.push(SINK_NAMES[sink]);
  }
  return steps;
}

function basinStats(rootId) {
  let count = 0;
  let km = 0;
  for (const entry of Object.values(info)) {
    if (entry.r === rootId) {
      count += 1;
      km += entry.k;
    }
  }
  return { count, km };
}

const formatKm = (km) => (km < 10 ? km.toFixed(1) : Math.round(km).toLocaleString("he-IL"));

// ---- Overview ----

function renderOverview() {
  details.replaceChildren();
  const counts = {};
  const visible = Object.values(info).filter((entry) => showDry || flows(entry.f));
  for (const entry of visible) counts[entry.d] = (counts[entry.d] || 0) + 1;
  const total = visible.length.toLocaleString("he-IL");
  details.append(el("p", { class: "summary" }, `${total} נחלים על המפה. לחצו על נחל כדי לגלות לאיזה אגן הוא שייך, לאן הוא נשפך ומי יובליו.`));
  details.append(el("h3", {}, "לאן הנחלים זורמים"));
  const legend = el("ul", { class: "legend" });
  for (const [key, { label, color }] of Object.entries(DRAINAGE)) {
    if (key === "unknown" && !counts.unknown) continue;
    legend.append(el("li", {}, el("button", {
      type: "button",
      "aria-pressed": String(filter === key),
      onclick: () => {
        filter = filter === key ? null : key;
        restyle();
        renderOverview();
      },
    }, el("span", { class: "swatch", style: `background:${color}` }), label, el("small", {}, String(counts[key] || 0)))));
  }
  details.append(legend);
  if (counts.unknown) details.append(el("p", { class: "note" }, "באפור: נחלים שלא מצאנו לאן הם זורמים."));
  details.append(el("h3", {}, "סוגי הקווים"));
  const lineKey = el("ul", { class: "line-key" });
  const addLine = (kind, text) => lineKey.append(el("li", {}, el("span", { class: `line-sample line-${kind}` }), el("span", {}, text)));
  addLine("solid", "קו רצוף: נחל איתן או נחל שזורם בחלקו.");
  if (showDry) addLine("dashed", "קו מקווקו: נחל אכזב או נחל ללא מידע על זרימה. מופיע רק בהגדלה של המפה; במבט רחוק גם הוא רצוף.");
  if (outsideLayer) addLine("thin", "קו דק: המשך הנחל מחוץ לתחום המפה.");
  details.append(lineKey);
  if (aquifers.length) {
    details.append(el("h3", {}, "מי תהום: אקוויפרים"));
    details.append(el("p", { class: "note" }, "אקוויפר הוא שכבת סלע נקבובית או סדוקה שמים נעים בתוכה. הגבולות סכמטיים."));
    const toggleInput = el("input", { type: "checkbox", id: "all-aquifers" });
    toggleInput.checked = showAllAquifers;
    toggleInput.addEventListener("change", () => setShowAllAquifers(toggleInput.checked));
    details.append(el("label", { class: "toggle" }, toggleInput, el("span", {}, "הצג את כל האקוויפרים על המפה")));
    if (showAllAquifers) details.append(el("p", { class: "note" }, "לחצו על אזור במפה כדי לפתוח אותו."));
    const list = el("ul", { class: "legend" });
    for (const entry of aquifers) {
      list.append(el("li", {}, el("button", { type: "button", onclick: () => selectAquifer(entry) },
        aquiferSwatch(entry), entry.name)));
    }
    details.append(list);
  }
}

// ---- Aquifers ----

// The name without "basin" or "aquifer", for labels and chips.
function shortName(entry) {
  return entry.name.replace(/^(אגן|אקוויפר)\s+/, "");
}

function aquiferSwatch(entry) {
  return el("span", { class: "swatch swatch-aquifer", style: `background:${entry.color}40;border-color:${entry.color}` });
}

// The file keeps GeoJSON order, [lng, lat]; Leaflet wants [lat, lng].
function aquiferLatLngs(entry) {
  return entry.ring.map(([lng, lat]) => [lat, lng]);
}

function allAquifersStyle(entry) {
  const [opacity, fillOpacity] = aquifer ? [0.6, 0.05] : selected !== null ? [0.35, 0.03] : [0.9, 0.13];
  return { color: entry.color, weight: 1.5, opacity, fillOpacity };
}

function setShowAllAquifers(on) {
  showAllAquifers = on;
  if (on) track("show_all_aquifers");
  if (selected === null && !aquifer) renderOverview();
  restyle();
}

// Shown on request, and while an aquifer is open so the others stay in reach.
function syncAllAquifers() {
  const wanted = showAllAquifers || aquifer;
  if (!wanted && allAquifersLayer) {
    allAquifersLayer.remove();
    allAquifersLayer = null;
  }
  if (wanted && !allAquifersLayer) {
    allAquifersLayer = L.layerGroup(aquifers.map((entry) => {
      const shape = L.polygon(aquiferLatLngs(entry), { pane: "aquifers", renderer: aquiferRenderer, interactive: false, ...allAquifersStyle(entry) });
      shape.aquifer = entry;
      return shape;
    })).addTo(map);
    for (const entry of aquifers) {
      L.tooltip({ permanent: true, direction: "center", className: "aquifer-label", pane: "tooltipPane" })
        .setLatLng(entry.label ? [entry.label[1], entry.label[0]] : L.latLngBounds(aquiferLatLngs(entry)).getCenter())
        .setContent(escapeHtml(shortName(entry)))
        .addTo(allAquifersLayer);
    }
    if (aquiferShape) aquiferShape.bringToFront();
  }
}

// Ray casting: a point is inside if a ray from it crosses the ring an odd number of times.
function ringContains(ring, lng, lat) {
  let inside = false;
  ring.forEach(([x0, y0], index) => {
    const [x1, y1] = ring[(index + 1) % ring.length];
    if (y0 > lat !== y1 > lat && lng < x0 + ((lat - y0) / (y1 - y0)) * (x1 - x0)) inside = !inside;
  });
  return inside;
}

function aquiferAt(latlng) {
  return aquifers.find((entry) => ringContains(entry.ring, latlng.lng, latlng.lat));
}

// When true, a click on the map is about aquifers rather than streams.
function aquifersInFocus() {
  return selected === null && (showAllAquifers || aquifer);
}

// A click on an aquifer opens it. Outside all of them, close.
function clickMap(latlng) {
  if (aquifersInFocus()) {
    const here = aquiferAt(latlng);
    if (here) {
      if (here !== aquifer) selectAquifer(here);
      return;
    }
  }
  if (selected !== null || aquifer) clearSelection();
}

// Quieted streams lie all over the aquifers, so they must not catch the clicks meant for them.
function clickStream(event, slug, open) {
  L.DomEvent.stopPropagation(event);
  if (aquifersInFocus() && !aquifer?.rivers.includes(slug)) clickMap(event.latlng);
  else open();
}

function showAquiferShape(entry) {
  if (aquiferShape) aquiferShape.remove();
  aquiferShape = entry && L.polygon(aquiferLatLngs(entry), {
    pane: "aquifers",
    renderer: aquiferRenderer,
    interactive: false,
    color: entry.color,
    weight: 2,
    fillOpacity: 0.16,
  }).addTo(map);
}

function renderAquifer(entry) {
  startCard();
  const switcher = el("nav", { class: "chips", "aria-label": "מעבר בין אקוויפרים" });
  for (const other of aquifers) {
    const attrs = { type: "button", onclick: () => selectAquifer(other) };
    if (other === entry) attrs["aria-current"] = "true";
    switcher.append(el("button", attrs, shortName(other)));
  }
  details.append(switcher);
  details.append(el("p", { class: "note" }, "אפשר גם ללחוץ על אקוויפר אחר במפה."));
  details.append(el("h2", {}, entry.name));
  details.append(el("div", { class: "basin-tag" }, aquiferSwatch(entry), "אקוויפר · גבולות סכמטיים"));
  const facts = el("dl", { class: "facts" });
  const addFact = (term, value) => facts.append(el("dt", {}, term), el("dd", {}, value));
  addFact("סלע", entry.rock);
  if (entry.recharge) addFact("העשרה", entry.recharge);
  if (entry.production) addFact("הפקה", entry.production);
  if (entry.discharge) addFact("ספיקת מעיינות", entry.discharge);
  details.append(facts);
  details.append(el("p", { class: "summary aquifer-note" }, entry.note));
  details.append(el("h3", {}, "נחלים שמקבלים ממנו מים"));
  if (entry.rivers.length) {
    const list = el("ul", { class: "tribs" });
    // A stream split into several OSM pieces is highlighted whole but listed once.
    const names = new Set();
    for (const slug of entry.rivers) {
      const id = idBySlug.get(slug);
      if (names.has(info[id].n)) continue;
      names.add(info[id].n);
      list.append(el("li", {}, riverLink(id)));
    }
    details.append(list);
    details.append(el("p", { class: "note" }, "רשימה חלקית: רק נחלים שמצאנו להם תימוכין."));
  } else {
    details.append(el("p", { class: "note" }, entry.empty));
  }
  details.append(el("p", { class: "note" }, "מקור: ", el("a", { href: AQUIFER_SOURCE, target: "_blank", rel: "noopener" }, "המכון הגיאולוגי, דרך Jewish Virtual Library"), ". הנתונים מתחילת שנות ה־2000."));
  switcher.querySelector("[aria-current]").scrollIntoView({ block: "nearest", inline: "center" });
}

function selectAquifer(entry) {
  selected = null;
  aquifer = entry;
  filter = null;
  showAquiferShape(entry);
  renderAquifer(entry);
  track("select_aquifer", { aquifer: entry.id });
  restyle();
  history.replaceState(null, "", `#${entry.id}`);
  // Move only when needed: staying put keeps the other aquifers in view.
  if (!map.getBounds().contains(aquiferShape.getBounds())) map.fitBounds(aquiferShape.getBounds(), { padding: [30, 30] });
}

// ---- Stream card ----

function renderRiver(id) {
  const entry = info[id];
  const root = info[entry.r];
  const drainage = DRAINAGE[entry.d];
  startCard();
  details.append(el("h2", {}, entry.n));
  if (entry.en) details.append(el("p", { class: "en", lang: "en", dir: "ltr" }, entry.en));
  details.append(el("div", { class: "basin-tag" }, el("span", { class: "swatch", style: `background:${drainage.color}` }), drainage.label));

  const facts = el("dl", { class: "facts" });
  const addFact = (term, ...value) => facts.append(el("dt", {}, term), el("dd", {}, ...value));
  const stats = basinStats(entry.r);
  if (entry.d === "unknown") {
    addFact("אגן", "לא זוהה");
  } else {
    addFact("אגן", entry.r === id ? `אגן ${entry.n}` : linkButton(`אגן ${root.n}`, () => select(entry.r, true)));
  }
  if (stats.count > 1) addFact("גודל האגן", `${stats.count.toLocaleString("he-IL")} נחלים, כ־${formatKm(stats.km)} ק״מ`);
  addFact("אורך", `כ־${formatKm(entry.k)} ק״מ`);
  addFact("זרימה", FLOW_LABELS[entry.f] || "אין מידע");
  const source = aquifers.find((candidate) => candidate.rivers.includes(entry.s));
  if (source) addFact("מקור המים", linkButton(source.name, () => selectAquifer(source)));
  details.append(facts);

  const steps = flowPath(id);
  details.append(el("h3", {}, "לאן הוא זורם"));
  if (steps.length) {
    const flow = el("ol", { class: "flow" });
    for (const step of steps) flow.append(el("li", {}, step));
    details.append(flow);
    if (entry.v) details.append(el("p", { class: "note" }, OUTLET_SOURCES[entry.v]));
    if (entry.d === "closed") details.append(el("p", { class: "note" }, "מלחת יטבתה היא שקע סגור: מי השיטפונות נאגרים בה ומתאדים או מחלחלים, ואינם מגיעים לים."));
  } else {
    details.append(el("p", { class: "note summary" }, "לא הצלחנו לזהות את מוצא הנחל מתוך הנתונים."));
  }

  if (entry.c.length) {
    details.append(el("h3", {}, `יובלים (${entry.c.length})`));
    const list = el("ul", { class: "tribs" });
    for (const child of entry.c) list.append(el("li", {}, riverLink(child)));
    details.append(list);
  }

  if (entry.x) {
    details.append(el("h3", {}, "מוויקיפדיה"));
    details.append(el("p", { class: "summary" }, entry.x));
    const url = `https://he.wikipedia.org/wiki/${encodeURIComponent(entry.w.replaceAll(" ", "_"))}`;
    details.append(el("p", {}, el("a", { href: url, target: "_blank", rel: "noopener" }, "לערך המלא")));
  }
}

// ---- Changing the state ----

function setShowDry(value) {
  showDry = value;
  dryToggle.checked = value;
  for (const [id, line] of layersById) {
    if (flows(info[id].f)) continue;
    if (value) layer.addLayer(line);
    else layer.removeLayer(line);
  }
  restyle();
}

// Opens a stream's card. zoomTo also fits the map to it, with its lines past the border.
function select(id, zoomTo) {
  if (!showDry && !flows(info[id].f)) setShowDry(true);
  selected = id;
  aquifer = null;
  showAquiferShape(null);
  renderRiver(id);
  track("select_river", { river: info[id].s });
  restyle();
  history.replaceState(null, "", `#${encodeURIComponent(info[id].s)}`);
  if (zoomTo) {
    const bounds = L.latLngBounds(layersById.get(id).getBounds());
    for (const line of outsideBySlug.get(info[id].s) || []) bounds.extend(line.getBounds());
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
  }
}

function clearSelection() {
  selected = null;
  aquifer = null;
  showAquiferShape(null);
  renderOverview();
  restyle();
  history.replaceState(null, "", location.pathname + location.search);
}

// The page's address is #slug, of a stream or an aquifer.
function openFromHash() {
  let slug;
  try {
    slug = decodeURIComponent(location.hash.slice(1));
  } catch {
    return; // a broken address opens nothing
  }
  if (idBySlug.has(slug)) select(idBySlug.get(slug), true);
  else if (aquiferBySlug.has(slug)) selectAquifer(aquiferBySlug.get(slug));
}

// ---- Search ----

// Compare without niqqud, a leading "stream of" or the definite article.
// A query of only "נחל" thus becomes empty and lists nothing, until more is typed.
function normalize(text) {
  return text.replace(/[֑-ׇ]/g, "").replace(/^(נחל|נהר|ואדי|וואדי)(\s+|$)/, "").replace(/^ה/, "");
}

let searchTimer;

function renderSearch() {
  const query = normalize(search.value.trim());
  results.replaceChildren();
  results.hidden = !query;
  clearTimeout(searchTimer);
  if (!query) return;
  const matches = Object.entries(info)
    .filter(([, entry]) => normalize(entry.n).includes(query))
    .sort(([, a], [, b]) => normalize(b.n).startsWith(query) - normalize(a.n).startsWith(query) || b.k - a.k)
    .slice(0, 30);
  // Wait for a pause, so a word counts once and not once per keystroke.
  searchTimer = setTimeout(() => track("search", { search_term: query.slice(0, 40), result_count: matches.length }), 1500);
  if (!matches.length) {
    results.append(el("li", { class: "note" }, "לא נמצאו נחלים"));
    return;
  }
  for (const [id, entry] of matches) {
    results.append(el("li", {}, el("button", {
      type: "button",
      onclick: () => {
        search.value = "";
        results.hidden = true;
        select(Number(id), true);
      },
    }, entry.n, el("small", {}, DRAINAGE[entry.d].label))));
  }
}

// ---- Wiring and loading ----

dryToggle.addEventListener("change", () => {
  setShowDry(dryToggle.checked);
  if (aquifer) return;
  if (selected === null) renderOverview();
  else if (!showDry && !flows(info[selected].f)) clearSelection();
});
search.addEventListener("input", renderSearch);
search.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    search.value = "";
    results.hidden = true;
  }
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".search")) results.hidden = true;
});
map.on("zoomend", restyle);
map.on("click", (event) => clickMap(event.latlng));
window.addEventListener("hashchange", openFromHash);

let loaded = false;
Promise.all([
  fetch("data/rivers.geojson").then((response) => response.json()),
  fetch("data/info.json").then((response) => response.json()),
  // The stream map must keep working if this optional layer fails to load.
  fetch("data/aquifers.json").then((response) => response.json()).catch(() => []),
  fetch("data/outside.geojson").then((response) => response.json()).catch(() => null),
]).then(([geojson, infoData, aquiferData, outside]) => {
  loaded = true;
  info = infoData;
  aquifers = aquiferData;
  for (const entry of aquifers) aquiferBySlug.set(entry.id, entry);
  for (const [id, entry] of Object.entries(info)) idBySlug.set(entry.s, Number(id));
  if (outside) {
    outsideLayer = L.geoJSON(outside, {
      style: outsideStyle,
      onEachFeature(feature, line) {
        const { s, n } = feature.properties;
        if (s) {
          if (!outsideBySlug.has(s)) outsideBySlug.set(s, []);
          outsideBySlug.get(s).push(line);
        }
        line.bindTooltip(escapeHtml(s ? `המשך של ${n}` : n), { sticky: true, direction: "top" });
        line.on("click", (event) => clickStream(event, null, () => {
          if (s) select(idBySlug.get(s), false);
        }));
      },
    }).addTo(map);
    // Panning reaches these lines; the zoom limit still stops at all of Israel.
    map.setMaxBounds(ISRAEL.pad(0.04).extend(outsideLayer.getBounds().pad(0.02)));
  }
  layer = L.geoJSON(geojson, {
    style: styleFor,
    onEachFeature(feature, line) {
      layersById.set(feature.properties.i, line);
      line.bindTooltip(escapeHtml(feature.properties.n), { sticky: true, direction: "top" });
      line.on("click", (event) => clickStream(event, info[feature.properties.i].s, () => select(feature.properties.i, false)));
    },
  }).addTo(map);
  addNameLabels(geojson);
  const dryCount = Object.values(info).filter((entry) => !flows(entry.f)).length;
  document.getElementById("dry-count").textContent = `(${dryCount.toLocaleString("he-IL")})`;
  renderOverview();
  openFromHash();
}).catch((error) => {
  // Only a failed download says so; a bug after it must not wipe the panel.
  if (!loaded) details.textContent = "טעינת הנתונים נכשלה. נסו לרענן את הדף.";
  console.error(error);
});
