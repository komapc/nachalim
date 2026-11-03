#!/usr/bin/env python3
"""Browser tests of clicks on the map. Needs Playwright: python3 -m unittest discover tests

The clicks are real mouse events on purpose. map.fire("click") skips the streams lying
on top of the aquifers, and that hid the bug test_click_on_dimmed_stream_reaches_aquifer
now guards against. The tests run offline: the base map gets an empty style.
"""
import functools
import http.server
import json
import pathlib
import threading
import unittest

from playwright.sync_api import sync_playwright

SITE = pathlib.Path(__file__).resolve().parent.parent / "site"
BROWSER_ARGS = ["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist", "--enable-unsafe-swiftshader"]
EMPTY_STYLE = json.dumps({"version": 8, "sources": {}, "layers": []})
COASTAL = (32.0, 34.8)
YARKON_TANINIM = (32.0, 35.1)
SEA = (32.5, 33.9)  # outside all aquifers
STREAM_ZOOM = 13  # close enough that a click hits one stream, not a neighbour

# Page helper: the middle point of the longest line of a stream chosen by a test.
FIND_POINT = """() => {
  window.middleOf = (id) => {
    const longest = layersById.get(id).getLatLngs().reduce((a, b) => (b.length > a.length ? b : a));
    const { lat, lng } = longest[Math.floor(longest.length / 2)];
    return [lat, lng];
  };
}"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class MapClicks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(QuietHandler, directory=str(SITE))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}/"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(args=BROWSER_ARGS)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.page = self.open_page(1280, 900)

    def tearDown(self):
        self.page.context.close()
        self.assertEqual(self.errors, [])

    def open_page(self, width, height):
        self.errors = []
        context = self.browser.new_context(viewport={"width": width, "height": height})
        context.route("**/*", self.route)
        page = context.new_page()
        page.add_init_script("localStorage.setItem('lipu-consent', 'no')")
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.goto(self.base)
        page.wait_for_selector(".legend button")
        page.evaluate(FIND_POINT)
        return page

    def route(self, route):
        url = route.request.url
        if url.startswith(self.base):
            route.continue_()
        elif "/styles/" in url:
            route.fulfill(content_type="application/json", body=EMPTY_STYLE)
        else:
            route.abort()

    def click_at(self, lat, lng):
        x, y = self.page.evaluate("([lat, lng]) => { const p = map.latLngToContainerPoint([lat, lng]); return [p.x, p.y]; }", [lat, lng])
        box = self.page.locator("#map").bounding_box()
        self.page.mouse.click(box["x"] + x, box["y"] + y)

    def go_to(self, point):
        self.page.evaluate("([lat, lng, zoom]) => void map.setView([lat, lng], zoom, { animate: false })", [*point, STREAM_ZOOM])

    def open_aquifer(self, slug):
        self.page.evaluate("(slug) => void selectAquifer(aquiferBySlug.get(slug))", slug)

    def open_card(self):
        """The ids of what is open: (aquifer, stream)."""
        return tuple(self.page.evaluate("[aquifer && aquifer.id, selected]"))

    def stream_in_other_aquifer(self, open_slug):
        """A long stream of no interest to open_slug, with a point inside exactly one other aquifer."""
        return self.page.evaluate("""(openSlug) => {
          const open = aquiferBySlug.get(openSlug);
          const ids = [...layersById.keys()].sort((a, b) => info[b].k - info[a].k);
          for (const id of ids) {
            if (open.rivers.includes(info[id].s)) continue;
            const [lat, lng] = middleOf(id);
            const here = aquiferAt({ lat, lng });
            if (here && here !== open) return { id, point: [lat, lng], aquifer: here.id };
          }
          return null;
        }""", open_slug)

    def test_click_on_stream_opens_it(self):
        stream = self.stream_in_other_aquifer("carmel")
        self.go_to(stream["point"])
        self.click_at(*stream["point"])
        aquifer, selected = self.open_card()
        self.assertIsNone(aquifer)
        self.assertIsNotNone(selected)

    def test_click_on_dimmed_stream_reaches_aquifer(self):
        stream = self.stream_in_other_aquifer("carmel")
        self.go_to(stream["point"])
        self.click_at(*stream["point"])  # first prove that a stream lies under this point
        self.assertIsNotNone(self.open_card()[1])
        self.page.evaluate("void clearSelection()")
        self.open_aquifer("carmel")
        self.go_to(stream["point"])
        self.click_at(*stream["point"])
        self.assertEqual(self.open_card(), (stream["aquifer"], None))

    def test_click_on_stream_of_open_aquifer_opens_it(self):
        target = self.page.evaluate("""() => {
          const open = aquiferBySlug.get("kinneret");
          const id = open.rivers.map((slug) => idBySlug.get(slug)).sort((a, b) => info[b].k - info[a].k)[0];
          return { id, point: middleOf(id) };
        }""")
        self.open_aquifer("kinneret")
        self.go_to(target["point"])
        self.click_at(*target["point"])
        self.assertEqual(self.open_card()[0], None)
        self.assertIsNotNone(self.open_card()[1])

    def test_click_opens_the_aquifer_there(self):
        self.open_aquifer("carmel")
        seen = []
        for point in (COASTAL, COASTAL, YARKON_TANINIM):
            self.click_at(*point)
            seen.append(self.open_card()[0])
        self.assertEqual(seen, ["coastal", "coastal", "yarkon-taninim"])

    def test_click_outside_aquifers_closes_card(self):
        self.open_aquifer("carmel")
        self.click_at(*SEA)
        self.assertEqual(self.open_card(), (None, None))
        # Leaflet removes a label only after its fade-out.
        self.page.wait_for_function("document.querySelectorAll('.aquifer-label').length === 0")

    def test_other_aquifers_stay_in_reach_without_moving_the_map(self):
        zoom = self.page.evaluate("map.getZoom()")
        self.open_aquifer("carmel")
        self.assertEqual(self.page.locator(".aquifer-label").count(), self.page.evaluate("aquifers.length"))
        self.assertEqual(self.page.evaluate("map.getZoom()"), zoom)

    def test_show_all_aquifers_stays_on_after_closing_card(self):
        self.page.check("#all-aquifers")
        self.click_at(*COASTAL)
        self.assertIsNotNone(self.open_card()[0])
        self.click_at(*SEA)
        self.assertEqual(self.open_card(), (None, None))
        self.assertTrue(self.page.is_checked("#all-aquifers"))

    def test_chips_stay_visible_when_card_scrolls_on_phone(self):
        self.page.context.close()
        self.page = self.open_page(390, 800)
        self.open_aquifer("eastern-mountain")
        panel = self.page.locator("#details")
        panel.evaluate("(node) => { node.scrollTop = node.scrollHeight; }")
        self.assertGreater(panel.evaluate("(node) => node.scrollTop"), 0)
        chips, area = self.page.locator(".chips").bounding_box(), panel.bounding_box()
        self.assertGreaterEqual(chips["y"], area["y"] - 1)
        self.assertLess(chips["y"], area["y"] + area["height"])


if __name__ == "__main__":
    unittest.main()
