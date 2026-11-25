#!/usr/bin/env python3
"""Tests of scripts/names.json and the way build_rivers.py applies it. Standard library only."""
import json
import pathlib
import sys
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_rivers  # noqa: E402


def way(way_id, tags, pts):
    return {"id": way_id, "tags": tags, "pts": pts, "entity": None}


class NamesFile(unittest.TestCase):
    def test_every_rule_is_sourced_and_kept_by_the_name_filter(self):
        rules = json.loads((SCRIPTS / "names.json").read_text(encoding="utf-8"))
        seen = set()
        for rule in rules:
            self.assertRegex(rule["name"], build_rivers.NAME_RE)
            self.assertTrue(rule["source"].startswith("https://"))
            self.assertTrue(rule["quote"])
            self.assertTrue(rule["ways"])
            self.assertFalse(seen & set(rule["ways"]), "a way is named twice")
            seen |= set(rule["ways"])


class ApplyNames(unittest.TestCase):
    RULE = {"name": "נחל בדיקה", "source": "https://example.org", "quote": "q", "ways": [2]}

    def test_names_the_listed_way_and_gives_its_stream_the_last_id(self):
        ways = [way(2, {"waterway": "stream"}, [(35.0, 32.0), (35.001, 32.0)]),
                way(1, {"waterway": "stream", "name": "נחל אחר"}, [(35.1, 32.0), (35.101, 32.0)])]
        build_rivers.apply_names(ways, [self.RULE])
        entities, _ = build_rivers.build_entities(ways)
        self.assertEqual([e["name"] for e in entities], ["נחל אחר", "נחל בדיקה"])

    def test_a_way_missing_from_the_download_stops_the_build(self):
        with self.assertRaises(SystemExit):
            build_rivers.apply_names([way(3, {"waterway": "stream"}, [(35.0, 32.0), (35.001, 32.0)])], [self.RULE])

    def test_a_way_that_has_a_name_stops_the_build(self):
        for tags in ({"name": "نهر"}, {"name:he": "נחל אחר"}):
            ways = [way(2, {"waterway": "stream", **tags}, [(35.0, 32.0), (35.001, 32.0)])]
            with self.assertRaises(SystemExit):
                build_rivers.apply_names(ways, [self.RULE])


if __name__ == "__main__":
    unittest.main()
