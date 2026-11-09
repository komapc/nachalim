#!/usr/bin/env python3
"""Checks of the data pipeline that need no downloads."""
import json
import pathlib
import random
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_pages  # noqa: E402
import build_rivers  # noqa: E402
import enrich_wiki  # noqa: E402

INFO = json.loads((ROOT / "site" / "data" / "info.json").read_text(encoding="utf-8"))


class Overrides(unittest.TestCase):
    def test_every_rule_names_a_stream(self):
        names = {entry["n"] for entry in INFO.values()}
        build_rivers.check_overrides(build_rivers.read_json(build_rivers.OVERRIDES_PATH), names)

    def test_rule_for_unknown_stream_stops_the_build(self):
        with self.assertRaises(SystemExit) as stop:
            build_rivers.check_overrides([{"name": "נחל אין", "flow": "mixed"}], {"נחל יש"})
        self.assertIn("נחל אין", str(stop.exception))

    def test_rule_for_unknown_parent_stops_the_build(self):
        with self.assertRaises(SystemExit):
            build_rivers.check_overrides([{"name": "נחל יש", "parent": "נחל אין"}], {"נחל יש"})


class Slugs(unittest.TestCase):
    def test_namesakes_keep_their_numbers_in_any_order(self):
        rivers = [{"name": "נחל א", "km": km, "mouth": [35.0, 31.0 + i]} for i, km in enumerate((2.0, 9.0, 2.0, 5.0))]
        random.Random(1).shuffle(rivers)
        enrich_wiki.assign_slugs(rivers)
        first = {(r["km"], tuple(r["mouth"])): r["slug"] for r in rivers}
        rivers.reverse()
        enrich_wiki.assign_slugs(rivers)
        self.assertEqual(first, {(r["km"], tuple(r["mouth"])): r["slug"] for r in rivers})
        self.assertEqual(first[(9.0, (35.0, 32.0))], "נחל-א")

    def test_two_streams_with_one_folder_stop_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder = build_pages.Builder(pathlib.Path(tmp))
            first, second = list(builder.info)[:2]
            builder.info[second] = dict(builder.info[second], s=builder.info[first]["s"])
            with self.assertRaises(SystemExit) as stop:
                builder.build()
            self.assertIn(builder.info[first]["s"], str(stop.exception))


if __name__ == "__main__":
    unittest.main()
