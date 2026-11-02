"use strict";

const DRAINAGE = {
  med: { label: "הים התיכון", color: "#1f78c1" },
  jordan: { label: "הירדן והכנרת", color: "#0b9a8d" },
  dead: { label: "ים המלח", color: "#c9662b" },
  gulf: { label: "מפרץ אילת", color: "#8e4fb8" },
  unknown: { label: "מוצא לא זוהה", color: "#7d8a8e" },
};

const SINK_NAMES = {
  med: "הים התיכון",
  gulf: "מפרץ אילת",
  dead: "ים המלח",
  kinneret: "הכנרת",
  hula: "אגמון החולה",
};

const FLOW_LABELS = {
  perennial: "נחל איתן: זורם כל השנה",
  mixed: "איתן בחלקו",
  intermittent: "נחל אכזב: זורם בעיקר בחורף",
};

const details = document.getElementById("details");
const dryToggle = document.getElementById("dry");
const search = document.getElementById("q");
const results = document.getElementById("results");

const ISRAEL = L.latLngBounds([29.47, 34.24], [33.36, 35.92]);
const BASEMAP_STYLE = "https://tiles.openfreemap.org/styles/positron";
const SHIELD_LAYER = /shield/;

const map = L.map("map", {
  preferCanvas: true,
  zoomSnap: 0.25,
  maxZoom: 15,
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

let info = {};
let layer = null;
let selected = null;
let filter = null;
let showDry = true;
const layersById = new Map();
const idBySlug = new Map();

const flows = (flow) => flow === "perennial" || flow === "mixed";

function weightFor(km, zoom) {
  const base = km >= 50 ? 3 : km >= 15 ? 2.2 : km >= 5 ? 1.5 : 1;
  return base + Math.max(0, zoom - 9) * 0.3;
}

function styleFor(feature) {
  const { i, d, k, f } = feature.properties;
  const zoom = map.getZoom();
  const entry = info[i];
  const color = DRAINAGE[d].color;
  let opacity = k < 3 && zoom < 9.5 ? 0.35 : 0.85;
  let weight = weightFor(k, zoom);
  if (filter && d !== filter) opacity = 0.08;
  if (selected !== null) {
    const sameBasin = entry.r === info[selected].r;
    if (i === selected) {
      opacity = 1;
      weight += 3;
    } else if (sameBasin) {
      opacity = 0.95;
      weight += 0.6;
    } else {
      opacity = Math.min(opacity, 0.15);
    }
  }
  const dashArray = !flows(f) && zoom >= 10 && i !== selected ? "6 6" : null;
  return { color, weight, opacity, dashArray, lineCap: "round", lineJoin: "round" };
}

function restyle() {
  if (layer) layer.setStyle(styleFor);
  if (selected !== null) layersById.get(selected).bringToFront();
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

function riverLink(id) {
  return el("button", { class: "link", type: "button", onclick: () => select(id, true) }, info[id].n);
}

function flowPath(id) {
  const steps = [];
  let current = id;
  while (info[current].p !== null) {
    current = info[current].p;
    steps.push(riverLink(current));
  }
  const sink = info[current].sink;
  const jordan = Object.keys(info).find((key) => info[key].n === "נהר הירדן");
  if (sink === "kinneret" || sink === "hula") {
    steps.push(SINK_NAMES[sink]);
    if (sink === "hula") steps.push("הכנרת");
    if (jordan !== undefined) steps.push(riverLink(Number(jordan)));
    steps.push(SINK_NAMES.dead);
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
}

function renderRiver(id) {
  const entry = info[id];
  const root = info[entry.r];
  const drainage = DRAINAGE[entry.d];
  details.replaceChildren();
  details.scrollTop = 0;
  details.append(el("div", { class: "back" }, el("button", { class: "link", type: "button", onclick: clearSelection }, "→ לכל הנחלים")));
  details.append(el("h2", {}, entry.n));
  if (entry.en) details.append(el("p", { class: "en", lang: "en", dir: "ltr", style: "text-align:right" }, entry.en));
  details.append(el("div", { class: "basin-tag" }, el("span", { class: "swatch", style: `background:${drainage.color}` }), drainage.label));

  const facts = el("dl", { class: "facts" });
  const addFact = (term, ...value) => facts.append(el("dt", {}, term), el("dd", {}, ...value));
  const stats = basinStats(entry.r);
  if (entry.d === "unknown") {
    addFact("אגן", "לא זוהה");
  } else {
    addFact("אגן", entry.r === id ? `אגן ${entry.n}` : el("button", { class: "link", type: "button", onclick: () => select(entry.r, true) }, `אגן ${root.n}`));
  }
  if (stats.count > 1) addFact("גודל האגן", `${stats.count.toLocaleString("he-IL")} נחלים, כ־${formatKm(stats.km)} ק״מ`);
  addFact("אורך", `כ־${formatKm(entry.k)} ק״מ`);
  addFact("זרימה", FLOW_LABELS[entry.f] || "אין מידע");
  details.append(facts);

  const steps = flowPath(id);
  details.append(el("h3", {}, "לאן הוא זורם"));
  if (steps.length) {
    const flow = el("ol", { class: "flow" });
    for (const step of steps) flow.append(el("li", {}, step));
    details.append(flow);
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

function select(id, zoomTo) {
  if (!showDry && !flows(info[id].f)) setShowDry(true);
  selected = id;
  renderRiver(id);
  restyle();
  history.replaceState(null, "", `#${encodeURIComponent(info[id].s)}`);
  if (zoomTo) map.fitBounds(layersById.get(id).getBounds(), { padding: [40, 40], maxZoom: 13 });
}

function clearSelection() {
  selected = null;
  renderOverview();
  restyle();
  history.replaceState(null, "", location.pathname + location.search);
}

function openFromHash() {
  const slug = decodeURIComponent(location.hash.slice(1));
  if (idBySlug.has(slug)) select(idBySlug.get(slug), true);
}

function normalize(text) {
  return text.replace(/[֑-ׇ]/g, "").replace(/^(נחל|נהר|ואדי|וואדי)\s+/, "").replace(/^ה/, "");
}

function renderSearch() {
  const query = normalize(search.value.trim());
  results.replaceChildren();
  results.hidden = !query;
  if (!query) return;
  const matches = Object.entries(info)
    .filter(([, entry]) => normalize(entry.n).includes(query))
    .sort(([, a], [, b]) => normalize(b.n).startsWith(query) - normalize(a.n).startsWith(query) || b.k - a.k)
    .slice(0, 30);
  if (!matches.length) {
    results.append(el("li", { class: "note", style: "padding:.4rem .5rem" }, "לא נמצאו נחלים"));
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

dryToggle.addEventListener("change", () => {
  setShowDry(dryToggle.checked);
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
map.on("click", () => {
  if (selected !== null) clearSelection();
});
window.addEventListener("hashchange", openFromHash);

Promise.all([
  fetch("data/rivers.geojson").then((response) => response.json()),
  fetch("data/info.json").then((response) => response.json()),
]).then(([geojson, infoData]) => {
  info = infoData;
  for (const [id, entry] of Object.entries(info)) idBySlug.set(entry.s, Number(id));
  layer = L.geoJSON(geojson, {
    style: styleFor,
    onEachFeature(feature, line) {
      layersById.set(feature.properties.i, line);
      line.bindTooltip(feature.properties.n, { sticky: true, direction: "top" });
      line.on("click", (event) => {
        L.DomEvent.stopPropagation(event);
        select(feature.properties.i, false);
      });
    },
  }).addTo(map);
  const dryCount = Object.values(info).filter((entry) => !flows(entry.f)).length;
  document.getElementById("dry-count").textContent = `(${dryCount.toLocaleString("he-IL")})`;
  renderOverview();
  openFromHash();
}).catch(() => {
  details.textContent = "טעינת הנתונים נכשלה. נסו לרענן את הדף.";
});
