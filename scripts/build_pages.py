#!/usr/bin/env python3
"""Writes the static pages search engines read, from site/data, using only the standard library.

  site/n/<slug>/index.html  a stream: basin, length, flow, way to the sea, tributaries, summary
  site/n/index.html         every stream, by where the water ends up
  site/basin/<slug>/index.html  a drainage basin with at least MIN_BASIN streams: every stream in it
  site/basin/index.html     every such basin, by where the water ends up
  site/sitemap.xml          the home page, the lists, the basins, and the streams worth indexing

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
BASE = "https://nachalim.lipu.dev"
JORDAN_SLUG = "נהר-הירדן"
MIN_SUMMARY = 80  # a shorter Wikipedia summary only repeats the facts around it
TOP_TRIBS_IN_DESCRIPTION = 3
MIN_BASIN = 3  # a basin of one or two streams says no more than the stream page
# Names that Hebrew writes with the article after "אגן"; the rest keep the full name, "אגן נחל שורק".
BASIN_NAMES = {"נהר-הירדן": "הירדן", "נחל-ירקון": "הירקון", "נחל-קישון": "הקישון"}
SHORT_FLOW = {"perennial": "נחל איתן", "mixed": "איתן בחלקו", "intermittent": "נחל אכזב"}
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
        self.consent = re.search(r'<script src="consent\.js"[^>]*></script>', home).group(0).replace('src="consent.js"', 'src="/consent.js"')

    def entry(self, entry_id):
        return self.info[str(entry_id)]

    def link(self, entry):
        return f'<a href="{E(stream_path(entry["s"]))}">{E(entry["n"])}</a>'

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
    <a href="https://lipu.dev/" lang="en" dir="ltr">lipu.dev</a></p>
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
        if entry["d"] == "unknown":
            facts.append(("אגן", "לא זוהה"))
        else:
            if own_root and str(entry_id) not in self.basins:
                facts.append(("אגן", E(self.basin_name(entry))))
            else:
                facts.append(("אגן", self.basin_link(entry["r"])))
        count, km = self.basin_stats(entry["r"])
        if count > 1:
            facts.append(("גודל האגן", f"{count:,} נחלים, כ־{format_km(km)} ק״מ"))
        facts.append(("אורך", f"כ־{format_km(entry['k'])} ק״מ"))
        facts.append(("זרימה", E(self.flows.get(entry.get("f"), "אין מידע"))))
        source = next((a for a in self.aquifers if entry["s"] in a["rivers"]), None)
        if source:
            facts.append(("מקור המים", f'<a href="/#{E(quote(source["id"], safe=""))}">{E(source["name"])}</a>'))
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
               '    <p><a class="to-map" href="/">למפה האינטראקטיבית</a> · <a href="/basin/">הנחלים לפי אגני ניקוז</a></p>']
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
               '    <p><a class="to-map" href="/">למפה האינטראקטיבית</a> · <a href="/n/">כל הנחלים</a></p>']
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

    def build(self):
        pages = self.site / "n"
        basins = self.site / "basin"
        for folder in (pages, basins):
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
        urls = [BASE + "/", BASE + "/n/", BASE + "/basin/"]
        (pages / "index.html").write_text(self.list_page(), encoding="utf-8")
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
