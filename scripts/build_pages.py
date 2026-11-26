#!/usr/bin/env python3
"""Writes the static pages search engines read, from site/data, using only the standard library.

  site/n/<slug>/index.html  a stream: basin, length, flow, way to the sea, tributaries, summary
  site/n/index.html         every stream, by where the water ends up
  site/basin/<slug>/index.html  a drainage basin with at least MIN_BASIN streams: every stream in it
  site/basin/index.html     every such basin, by where the water ends up
  site/glossary/index.html  the words of the map and the summaries, from scripts/glossary.json
  site/sitemap.xml          the home page, the lists, the basins, the glossary, and the streams worth indexing

Run by .github/workflows/pages.yml before the upload. The output is not committed.
Labels are read from app.js, so the pages say what the map says.
"""
import html
import json
import pathlib
import re
import shutil
import sys
from urllib.parse import quote

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
GLOSSARY = ROOT / "scripts/glossary.json"
BASE = "https://nachalim.lipu.dev"
JORDAN_SLUG = "נהר-הירדן"
MIN_SUMMARY = 80  # a shorter Wikipedia summary only repeats the facts around it
TOP_TRIBS_IN_DESCRIPTION = 3
MIN_BASIN = 3  # a basin of one or two streams says no more than the stream page
# Names that Hebrew writes with the article after "אגן"; the rest keep the full name, "אגן נחל שורק".
BASIN_NAMES = {"נהר-הירדן": "הירדן", "נחל-ירקון": "הירקון", "נחל-קישון": "הקישון"}
SHORT_FLOW = {"perennial": "נחל איתן", "mixed": "איתן בחלקו", "intermittent": "נחל אכזב"}
LINKED_TERMS = ("אגן ניקוז", "מי תהום")  # the stream pages link these, and the flow terms above, to the glossary
E = html.escape


def js_table(source, name):
    """The `key: "text"` or `key: { label: "text" ... }` lines of a constant object in app.js."""
    body = re.search(rf"const {name} = \{{\n(.*?)\n\}};", source, re.S).group(1)
    table = dict(re.findall(r'^\s*(\w+): (?:\{ label: )?"((?:[^"\\]|\\.)*)"', body, re.M))
    if not table:
        raise ValueError(f"no entries read from {name} in app.js")
    return {key: value.replace('\\"', '"') for key, value in table.items()}


def stream_path(slug):
    return f"/n/{quote(slug, safe='')}/"


def basin_path(slug):
    return f"/basin/{quote(slug, safe='')}/"


def term_id(term):
    return term.replace(" ", "-")


def glossary_path(term):
    return "/glossary/#" + quote(term_id(term), safe="")


# In glossary.json a definition links words as [[shown words|target]], or [[target]] when the words are the target.
# The target is another term, "n:<slug>" for a stream, or "w:<title>" for a Hebrew Wikipedia article.
TERM_LINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
WIKI_SITES = {"he": "he.wikipedia.org", "en": "en.wikipedia.org", "ru": "ru.wikipedia.org"}
MAP_PIN = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 2a7 7 0 0 0-7 7c0 5.2 7 13 7 13s7-7.8 '
           '7-13a7 7 0 0 0-7-7zm0 9.6A2.6 2.6 0 1 1 12 6.4a2.6 2.6 0 0 1 0 5.2z"/></svg>')


def plain_text(text):
    return TERM_LINK.sub(lambda m: m.group(1), text)


def link_target(m):
    return m.group(2) or m.group(1)


def wiki_url(lang, title):
    return f"https://{WIKI_SITES[lang]}/wiki/" + quote(title.replace(" ", "_"), safe="")


def pinned(link, slug, name):
    """A link to a stream's page and a small pin that opens the map on it, kept on one line."""
    return (f'<span class="pinned">{link}<a class="map-pin" href="/#{E(quote(slug, safe=""))}" title="הצגה על המפה" '
            f'aria-label="{E(name)} על המפה">{MAP_PIN}</a></span>')


def format_km(km):
    return f"{km:.1f}" if km < 10 else f"{int(km + .5):,}"


def is_indexable(entry):
    return len(entry.get("x") or "") >= MIN_SUMMARY or bool(entry["c"])


class Builder:
    def __init__(self, site=SITE):
        self.site = pathlib.Path(site)
        app = (SITE / "app.js").read_text(encoding="utf-8")
        self.drainage = js_table(app, "DRAINAGE")
        self.sinks = js_table(app, "SINK_NAMES")
        self.sources = js_table(app, "OUTLET_SOURCES")
        self.flows = js_table(app, "FLOW_LABELS")
        self.closed_note = re.search(r'entry\.d === "closed"\) details\.append\(el\("p", \{ class: "note" \}, "([^"]+)"', app).group(1)
        self.info = json.loads((SITE / "data/info.json").read_text(encoding="utf-8"))
        self.aquifers = json.loads((SITE / "data/aquifers.json").read_text(encoding="utf-8"))
        self.by_slug = {entry["s"]: entry for entry in self.info.values()}
        self.members = {}
        for entry in self.info.values():
            self.members.setdefault(str(entry["r"]), []).append(entry)
        self.basins = {root: members for root, members in self.members.items()
                       if len(members) >= MIN_BASIN and self.entry(root)["d"] != "unknown"}
        names = [entry["n"] for entry in self.info.values()]
        self.shared_names = {name for name in names if names.count(name) > 1}
        home = (SITE / "index.html").read_text(encoding="utf-8")
        self.beacon = re.search(r"<script defer src=\"https://static\.cloudflareinsights\.com/[^>]*></script>", home).group(0)
        self.consent = re.search(r'<script src="https://geo\.lipu\.dev/consent\.js"[^>]*></script>', home).group(0)
        self.glossary = json.loads(GLOSSARY.read_text(encoding="utf-8"))
        self.check_glossary()

    def check_glossary(self):
        """Every example names a stream, basin page or aquifer that exists, and every term the pages link to is defined."""
        ids_by_slug = {entry["s"]: entry_id for entry_id, entry in self.info.items()}
        aquifers = {aquifer["id"] for aquifer in self.aquifers}
        terms = []
        for section in self.glossary:
            for item in section["terms"]:
                terms.append(term_id(item["term"]))
                if not (item.get("en") and item.get("ru")):
                    raise ValueError(f"glossary.json: {item['term']}: needs both en and ru")
                bad = [s for s in item.get("streams", []) if s not in ids_by_slug]
                bad += [s for s in item.get("basins", []) if ids_by_slug.get(s) not in self.basins]
                bad += [a for a in item.get("aquifers", []) if a not in aquifers]
                if bad:
                    raise ValueError(f"glossary.json: {item['term']}: no such stream, basin page or aquifer: {', '.join(bad)}")
        for section in self.glossary:
            for item in section["terms"]:
                targets = [link_target(m) for m in TERM_LINK.finditer(item["text"])]
                streams = {t[2:] for t in targets if t.startswith("n:")}
                targets = {term_id(t) for t in targets if not t.startswith(("n:", "w:"))}
                bad = sorted((targets - set(terms)) | (streams - set(ids_by_slug)))
                if bad or term_id(item["term"]) in targets:
                    raise ValueError(f"glossary.json: {item['term']}: links to itself or to an unknown term or stream: {', '.join(bad)}")
                if set(item.get("wiki", {})) - set(WIKI_SITES):
                    raise ValueError(f"glossary.json: {item['term']}: wiki languages are he, en and ru")
        missing = {term_id(t) for t in (*SHORT_FLOW.values(), *LINKED_TERMS)} - set(terms)
        if len(terms) != len(set(terms)) or missing:
            raise ValueError(f"glossary.json: duplicate terms, or missing {', '.join(sorted(missing))}")

    def entry(self, entry_id):
        return self.info[str(entry_id)]

    def link(self, entry, text=None):
        return f'<a href="{E(stream_path(entry["s"]))}">{E(text or entry["n"])}</a>'

    def flow_steps(self, entry):
        """The way to the sea, as (text, entry or None), like flowPath in app.js."""
        steps = []
        current = entry
        while current["p"] is not None:
            current = self.entry(current["p"])
            steps.append((current["n"], current))
        sink = current["sink"]
        jordan = self.by_slug.get(JORDAN_SLUG)
        if sink in ("kinneret", "hula"):
            steps.append((self.sinks[sink], None))
            if sink == "hula":
                steps.append(("הכנרת", None))
            if jordan:
                steps.append((jordan["n"], jordan))
            steps.append((self.sinks["dead"], None))
        elif sink == "arish":
            steps += [(self.sinks["arish"], None), (self.sinks["med"], None)]
        elif sink:
            steps.append((self.sinks[sink], None))
        return steps

    def basin_stats(self, root_id):
        members = self.members[str(root_id)]
        return len(members), sum(entry["k"] for entry in members)

    def basin_name(self, root):
        return "אגן " + BASIN_NAMES.get(root["s"], root["n"])

    def basin_link(self, root_id):
        """A link to the basin page, or to the top-level stream when the basin is too small for a page."""
        root = self.entry(root_id)
        href = basin_path(root["s"]) if str(root_id) in self.basins else stream_path(root["s"])
        return f'<a href="{E(href)}">{E(self.basin_name(root))}</a>'

    def description(self, entry, steps):
        parts = [SHORT_FLOW.get(entry.get("f"), ""), f"אורך כ-{format_km(entry['k'])} ק״מ"]
        if entry["d"] != "unknown":
            parts.append(self.basin_name(self.entry(entry["r"])))
        text = f"{entry['n']}: " + ", ".join(part for part in parts if part) + "."
        if steps:
            text += " זורם אל " + " ← ".join(step for step, _ in steps[:3]) + "."
        if entry["c"]:
            names = [self.entry(child)["n"] for child in entry["c"][:TOP_TRIBS_IN_DESCRIPTION]]
            text += " יובלים: " + ", ".join(names) + ("." if len(entry["c"]) <= TOP_TRIBS_IN_DESCRIPTION else " ועוד.")
        return text

    def page(self, *, title, description, path, body, crumbs, ld, index=True):
        robots = "" if index else '<meta name="robots" content="noindex, follow">\n  '
        scripts = "".join(
            '<script type="application/ld+json">' + json.dumps(item, ensure_ascii=False).replace("</", "<\\/") + "</script>\n  "
            for item in ld
        )
        trail = " › ".join(f'<a href="{E(href)}">{E(text)}</a>' if href else E(text) for text, href in crumbs)
        return f"""<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{E(title)}</title>
  <meta name="description" content="{E(description)}">
  {robots}<link rel="canonical" href="{E(BASE + path)}">
  <meta property="og:type" content="website">
  <meta property="og:locale" content="he_IL">
  <meta property="og:site_name" content="נחלי ישראל">
  <meta property="og:title" content="{E(title)}">
  <meta property="og:description" content="{E(description)}">
  <meta property="og:url" content="{E(BASE + path)}">
  <meta property="og:image" content="{BASE}/og.png">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="icon" href="/favicon.ico" sizes="48x48">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="stylesheet" href="/style.css">
  <link rel="stylesheet" href="/pages.css">
  {scripts}{self.beacon}
</head>
<body class="page">
  <nav class="crumbs" aria-label="ניווט">{trail}</nav>
  <main>
{body}
  </main>
  <footer>
    <p>הנתונים הופקו אוטומטית ועלולים להכיל טעויות.</p>
    <p>גיאוגרפיה: <a href="https://www.openstreetmap.org/copyright" lang="en" dir="ltr">© OpenStreetMap</a> ·
    תקצירים: <a href="https://he.wikipedia.org/">ויקיפדיה</a>
    (<a href="https://creativecommons.org/licenses/by-sa/4.0/deed.he" lang="en" dir="ltr">CC BY-SA</a>) ·
    <a href="https://lipu.dev/" lang="en" dir="ltr">lipu.dev</a> ·
    <a href="#" data-lipu-consent-open>הגדרות אנליטיקה</a></p>
  </footer>
  {self.consent}
</body>
</html>
"""

    def stream_page(self, entry_id, entry):
        steps = self.flow_steps(entry)
        root = self.entry(entry["r"])
        own_root = str(entry["r"]) == str(entry_id)
        out = [f"    <h1>{E(entry['n'])}</h1>"]
        if entry.get("en"):
            out.append(f'    <p class="en" lang="en" dir="ltr">{E(entry["en"])}</p>')
        out.append(f'    <p class="basin-line">{E(self.drainage[entry["d"]])}</p>')
        out.append(f'    <p><a class="to-map" href="/#{E(quote(entry["s"], safe=""))}">הצגת הנחל על המפה</a></p>')
        facts = []
        basin = f'<a href="{E(glossary_path("אגן ניקוז"))}">אגן</a>'
        if entry["d"] == "unknown":
            facts.append((basin, "לא זוהה"))
        else:
            if own_root and str(entry_id) not in self.basins:
                facts.append((basin, E(self.basin_name(entry))))
            else:
                facts.append((basin, self.basin_link(entry["r"])))
        count, km = self.basin_stats(entry["r"])
        if count > 1:
            facts.append(("גודל האגן", f"{count:,} נחלים, כ־{format_km(km)} ק״מ"))
        facts.append(("אורך", f"כ־{format_km(entry['k'])} ק״מ"))
        flow = E(self.flows.get(entry.get("f"), "אין מידע"))
        if entry.get("f") in SHORT_FLOW:
            flow = f'<a href="{E(glossary_path(SHORT_FLOW[entry["f"]]))}">{flow}</a>'
        facts.append(("זרימה", flow))
        source = next((a for a in self.aquifers if entry["s"] in a["rivers"]), None)
        if source:
            facts.append((f'<a href="{E(glossary_path("מי תהום"))}">מקור המים</a>',
                          f'<a href="/#{E(quote(source["id"], safe=""))}">{E(source["name"])}</a>'))
        out.append('    <dl class="facts">' + "".join(f"<dt>{term}</dt><dd>{value}</dd>" for term, value in facts) + "</dl>")
        out.append("    <h2>לאן הוא זורם</h2>")
        if steps:
            items = "".join(f"<li>{self.link(target) if target else E(text)}</li>" for text, target in steps)
            out.append(f'    <ol class="flow">{items}</ol>')
            if entry.get("v"):
                out.append(f'    <p class="note">{E(self.sources[entry["v"]])}</p>')
            if entry["d"] == "closed":
                out.append(f'    <p class="note">{E(self.closed_note)}</p>')
        else:
            out.append('    <p class="note">לא הצלחנו לזהות את מוצא הנחל מתוך הנתונים.</p>')
        if entry["c"]:
            out.append(f"    <h2>יובלים ({len(entry['c'])})</h2>")
            items = "".join(f"<li>{self.link(self.entry(child))}</li>" for child in entry["c"])
            out.append(f'    <ul class="stream-list">{items}</ul>')
        if entry.get("x"):
            url = "https://he.wikipedia.org/wiki/" + quote(entry["w"].replace(" ", "_"), safe="")
            out.append("    <h2>מוויקיפדיה</h2>")
            out.append(f'    <p class="summary">{E(entry["x"])}</p>')
            out.append(f'    <p><a href="{E(url)}" rel="noopener">לערך המלא</a></p>')
        name = entry["n"]
        shown = f"{name} (כ-{format_km(entry['k'])} ק״מ)" if name in self.shared_names else name
        path = stream_path(entry["s"])
        description = self.description(entry, steps)
        water = {"@context": "https://schema.org", "@type": "RiverBodyOfWater", "name": name, "url": BASE + path, "description": description, "inLanguage": "he"}
        if entry.get("en"):
            water["alternateName"] = entry["en"]
        crumbs = [("נחלי ישראל", "/"), ("כל הנחלים", "/n/"), (name, None)]
        trail = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "נחלי ישראל", "item": BASE + "/"},
            {"@type": "ListItem", "position": 2, "name": "כל הנחלים", "item": BASE + "/n/"},
            {"@type": "ListItem", "position": 3, "name": name},
        ]}
        return self.page(title=f"{shown}: לאן הוא זורם, אורך ואגן ניקוז", description=description, path=path,
                         body="\n".join(out), crumbs=crumbs, ld=[water, trail], index=is_indexable(entry))

    def list_page(self):
        entries = sorted(self.info.values(), key=lambda entry: entry["n"])
        out = ["    <h1>כל נחלי ישראל, לפי אגן ניקוז</h1>",
               f'    <p class="summary">{len(entries):,} נחלים ונהרות בישראל ובאזור, לפי המקום שאליו המים זורמים. לכל נחל יש עמוד עם אגן הניקוז, האורך, היובלים והדרך אל הים.</p>',
               '    <p><a class="to-map" href="/">למפה האינטראקטיבית</a> · <a href="/basin/">הנחלים לפי אגני ניקוז</a> · <a href="/glossary/">מילון מונחים</a></p>']
        perennial = [entry for entry in entries if entry.get("f") == "perennial"]
        out.append(f"    <h2>נחלי איתן ({len(perennial)})</h2>")
        out.append('    <ul class="stream-list">' + "".join(f"<li>{self.link(e)}</li>" for e in perennial) + "</ul>")
        for key, label in self.drainage.items():
            group = [entry for entry in entries if entry["d"] == key]
            if group:
                out.append(f"    <h2>{E(label)} ({len(group)})</h2>")
                out.append('    <ul class="stream-list">' + "".join(f"<li>{self.link(e)}</li>" for e in group) + "</ul>")
        return self.page(title="רשימת נחלי ישראל לפי אגן ניקוז", description=f"רשימה של {len(entries):,} נחלים בישראל: נחלי איתן, והנחלים שזורמים אל הים התיכון, הירדן והכנרת, ים המלח ומפרץ אילת.",
                         path="/n/", body="\n".join(out), crumbs=[("נחלי ישראל", "/"), ("כל הנחלים", None)],
                         ld=[{"@context": "https://schema.org", "@type": "CollectionPage", "name": "רשימת נחלי ישראל לפי אגן ניקוז", "url": BASE + "/n/", "inLanguage": "he"}])

    def basin_page(self, root_id):
        root = self.entry(root_id)
        members = sorted(self.members[str(root_id)], key=lambda entry: (-entry["k"], entry["n"]))
        count, km = self.basin_stats(root_id)
        name = self.basin_name(root)
        steps = self.flow_steps(root)
        perennial = sum(1 for entry in members if entry.get("f") == "perennial")
        intro = (f"{name} הוא אגן הניקוז של {root['n']}. במפה מופיעים בו {count:,} נחלים: {root['n']} עצמו "
                 f"והנחלים שמימיהם מגיעים אליו, באורך כולל של כ־{format_km(km)} ק״מ.")
        if perennial:
            intro += " מתוכם נחל איתן אחד." if perennial == 1 else f" מתוכם {perennial} נחלי איתן."
        if steps:
            intro += f" {root['n']} זורם אל " + " ← ".join(text for text, _ in steps) + "."
        out = [f"    <h1>{E(name)}</h1>",
               f'    <p class="basin-line">{E(self.drainage[root["d"]])}</p>',
               f'    <p class="summary">{E(intro)}</p>']
        if root["d"] == "closed":
            out.append(f'    <p class="note">{E(self.closed_note)}</p>')
        out.append(f'    <p><a class="to-map" href="/#{E(quote(root["s"], safe=""))}">הצגת האגן על המפה</a> · '
                   f'{self.link(root)}</p>')
        if root["c"]:
            out.append(f"    <h2>היובלים של {E(root['n'])} ({len(root['c'])})</h2>")
            out.append('    <ul class="stream-list">' + "".join(f"<li>{self.link(self.entry(child))}</li>" for child in root["c"]) + "</ul>")
        out.append(f"    <h2>כל הנחלים באגן ({count:,})</h2>")
        out.append('    <p class="note">מהארוך לקצר.</p>')
        out.append('    <ul class="basin-list">' + "".join(
            f"<li>{self.link(entry)} <span class=\"km\">כ־{format_km(entry['k'])} ק״מ</span></li>" for entry in members) + "</ul>")
        out.append('    <p><a href="/basin/">כל אגני הניקוז</a> · <a href="/n/">כל הנחלים</a></p>')
        path = basin_path(root["s"])
        title = f"{name}: כל הנחלים במפה"
        top = [self.entry(child)["n"] for child in root["c"][:TOP_TRIBS_IN_DESCRIPTION]]
        description = f"{name}: {count:,} נחלים באורך כולל של כ־{format_km(km)} ק״מ"
        description += (", ביניהם " + ", ".join(top) + "." if top else ".")
        description += " רשימת כל הנחלים באגן הניקוז, עם קישור לכל נחל ולמפה."
        crumbs = [("נחלי ישראל", "/"), ("אגני ניקוז", "/basin/"), (name, None)]
        trail = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "נחלי ישראל", "item": BASE + "/"},
            {"@type": "ListItem", "position": 2, "name": "אגני ניקוז", "item": BASE + "/basin/"},
            {"@type": "ListItem", "position": 3, "name": name},
        ]}
        collection = {"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "url": BASE + path,
                      "description": description, "inLanguage": "he",
                      "about": {"@type": "RiverBodyOfWater", "name": root["n"], "url": BASE + stream_path(root["s"])}}
        return self.page(title=title, description=description, path=path, body="\n".join(out), crumbs=crumbs, ld=[collection, trail])

    def basin_list_page(self):
        roots = sorted(self.basins, key=lambda root: (-len(self.basins[root]), self.entry(root)["n"]))
        total = sum(len(members) for members in self.basins.values())
        out = ["    <h1>אגני הניקוז של נחלי ישראל</h1>",
               f'    <p class="summary">אגן ניקוז הוא השטח שממנו זורמים המים אל נחל ראשי אחד. כאן מופיעים {len(roots)} אגנים '
               f"שיש בהם לפחות {MIN_BASIN} נחלים, ובהם {total:,} נחלים, לפי המקום שאליו המים זורמים בסוף. "
               "לכל אגן יש עמוד עם כל הנחלים שבו.</p>",
               '    <p><a class="to-map" href="/">למפה האינטראקטיבית</a> · <a href="/n/">כל הנחלים</a> · <a href="/glossary/">מילון מונחים</a></p>']
        for key, label in self.drainage.items():
            group = [root for root in roots if self.entry(root)["d"] == key]
            if group:
                out.append(f"    <h2>{E(label)} ({len(group)})</h2>")
                out.append('    <ul class="stream-list">' + "".join(
                    f'<li><a href="{E(basin_path(self.entry(root)["s"]))}">{E(self.basin_name(self.entry(root)))}</a> '
                    f'<span class="km">({len(self.basins[root]):,} נחלים)</span></li>' for root in group) + "</ul>")
        title = "אגני הניקוז של נחלי ישראל: רשימה ומפה"
        description = (f"{len(roots)} אגני ניקוז בישראל, מאגן הירדן ואגן הירקון ועד אגני הנגב והערבה: "
                       "לכל אגן רשימה של הנחלים שבו וקישור למפה.")
        return self.page(title=title, description=description, path="/basin/", body="\n".join(out),
                         crumbs=[("נחלי ישראל", "/"), ("אגני ניקוז", None)],
                         ld=[{"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "url": BASE + "/basin/", "inLanguage": "he"}])

    def linked_text(self, text):
        out, pos = [], 0
        for m in TERM_LINK.finditer(text):
            shown, target = m.group(1), link_target(m)
            if target.startswith("n:"):
                entry = self.by_slug[target[2:]]
                link = pinned(self.link(entry, shown), entry["s"], entry["n"])
            elif target.startswith("w:"):
                link = f'<a href="{E(wiki_url("he", target[2:]))}" rel="noopener">{E(shown)}</a>'
            else:
                link = f'<a href="#{E(quote(term_id(target), safe=""))}">{E(shown)}</a>'
            out += [E(text[pos:m.start()]), link]
            pos = m.end()
        return "".join(out) + E(text[pos:])

    def glossary_page(self):
        aquifers = {aquifer["id"]: aquifer for aquifer in self.aquifers}
        items = [item for section in self.glossary for item in section["terms"]]
        out = ["    <h1>מילון מונחים</h1>",
               '    <p class="summary">המילים שמופיעות במפה, בעמודי הנחלים ובתקצירים מוויקיפדיה, בהסבר קצר. '
               "לכל מונח מופיע גם התרגום לאנגלית ולרוסית, וליד רוב המונחים יש נחלים שבהם אפשר לראות אותם.</p>",
               '    <p><a class="to-map" href="/">למפה האינטראקטיבית</a> · <a href="/n/">כל הנחלים</a> · '
               '<a href="/basin/">הנחלים לפי אגני ניקוז</a></p>',
               '    <p class="toc">' + " · ".join(
                   f'<a href="#{E(quote(term_id(item["term"]), safe=""))}">{E(item["term"])}</a>' for item in items) + "</p>"]
        for section in self.glossary:
            out.append(f"    <h2>{E(section['section'])}</h2>")
            rows = []
            for item in section["terms"]:
                also = "".join(f' <span class="also">{label}: {E(", ".join(item[key]))}</span>'
                               for key, label in (("also", "גם"), ("includes", "כולל")) if item.get(key))
                links = [pinned(self.link(self.by_slug[slug]), slug, self.by_slug[slug]["n"]) for slug in item.get("streams", [])]
                links += [pinned(f'<a href="{E(basin_path(slug))}">{E(self.basin_name(self.by_slug[slug]))}</a>',
                                 slug, self.basin_name(self.by_slug[slug])) for slug in item.get("basins", [])]
                links += [f'<a href="/#{E(quote(key, safe=""))}">{E(aquifers[key]["name"])}</a>'
                          for key in item.get("aquifers", [])]
                examples = f'<p class="examples">לדוגמה: {" · ".join(links)}</p>' if links else ""
                wiki = item.get("wiki", {})
                words = []
                for lang, label in (("en", "Wikipedia"), ("ru", "Википедия")):
                    if lang in wiki:
                        words.append(f'<a lang="{lang}" dir="ltr" href="{E(wiki_url(lang, wiki[lang]))}" title="{label}" '
                                     f'rel="noopener">{E(item[lang])}</a>')
                    else:
                        words.append(f'<span lang="{lang}" dir="ltr">{E(item[lang])}</span>')
                if "he" in wiki:
                    words.append(f'<a href="{E(wiki_url("he", wiki["he"]))}" rel="noopener">ויקיפדיה</a>')
                translation = f'<p class="tr">{" · ".join(words)}</p>'
                rows.append(f'<dt id="{E(term_id(item["term"]))}"><dfn>{E(item["term"])}</dfn>{also}</dt>'
                            f'<dd>{translation}<p>{self.linked_text(item["text"])}</p>{examples}</dd>')
            out.append('    <dl class="glossary">' + "".join(rows) + "</dl>")
        title = "מילון מונחים: נחלים, אגני ניקוז וצורות נוף"
        description = (f"מה זה נחל איתן, נחל אכזב, אגן ניקוז, יובל, נפתול, גב ומכתש: {len(items)} מונחים "
                       "על נחלי ישראל בהסבר קצר, עם תרגום לאנגלית ולרוסית ודוגמאות מהמפה.")
        terms = {"@context": "https://schema.org", "@type": "DefinedTermSet", "name": title, "url": BASE + "/glossary/",
                 "description": description, "inLanguage": "he",
                 "hasDefinedTerm": [{"@type": "DefinedTerm", "name": item["term"], "alternateName": [item["en"], item["ru"]],
                                     "description": plain_text(item["text"]),
                                     "url": BASE + glossary_path(item["term"])} for item in items]}
        return self.page(title=title, description=description, path="/glossary/", body="\n".join(out),
                         crumbs=[("נחלי ישראל", "/"), ("מילון מונחים", None)], ld=[terms])

    def build(self):
        pages = self.site / "n"
        basins = self.site / "basin"
        glossary = self.site / "glossary"
        for folder in (pages, basins, glossary):
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
        urls = [BASE + "/", BASE + "/n/", BASE + "/basin/", BASE + "/glossary/"]
        (pages / "index.html").write_text(self.list_page(), encoding="utf-8")
        (glossary / "index.html").write_text(self.glossary_page(), encoding="utf-8")
        (basins / "index.html").write_text(self.basin_list_page(), encoding="utf-8")
        for entry_id, entry in self.info.items():
            folder = pages / entry["s"]
            if folder.exists():
                sys.exit(f"build_pages.py: two streams share the folder n/{entry['s']}/ (stream {entry_id})")
            folder.mkdir()
            (folder / "index.html").write_text(self.stream_page(entry_id, entry), encoding="utf-8")
            if is_indexable(entry):
                urls.append(BASE + stream_path(entry["s"]))
        for root_id in self.basins:
            folder = basins / self.entry(root_id)["s"]
            if folder.exists():
                sys.exit(f"build_pages.py: two basins share the folder basin/{self.entry(root_id)['s']}/")
            folder.mkdir()
            (folder / "index.html").write_text(self.basin_page(root_id), encoding="utf-8")
            urls.append(BASE + basin_path(self.entry(root_id)["s"]))
        body = "".join(f"  <url><loc>{E(url)}</loc></url>\n" for url in urls)
        (self.site / "sitemap.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{body}</urlset>\n', encoding="utf-8")
        return len(self.info), len(urls)


if __name__ == "__main__":
    builder = Builder(sys.argv[1] if len(sys.argv) > 1 else SITE)
    total, listed = builder.build()
    print(f"{total} stream pages, {len(builder.basins)} basin pages, {listed} URLs in the sitemap")
