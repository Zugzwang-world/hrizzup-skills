"""timeline_card.py's reading of updates, times and rows: everything that needs no picture.

The drawing itself needs Pillow, which the repository's check doesn't install; it is proved by the
sample card (skills/timeline/examples/card.png), made by the command and described in its README.
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "timeline", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import importlib.util  # noqa: E402

import catalogue  # noqa: E402

spec = importlib.util.spec_from_file_location("timeline_card_under_test", os.path.join(SCRIPTS, "timeline_card.py"))
card = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card)

UTC = timezone.utc


def utc(*parts):
    return datetime(*parts, tzinfo=UTC)


def example_brief():
    with open(os.path.join(ROOT, "skills", "timeline", "examples", "brief.md"), encoding="utf-8") as f:
        return f.read()


BRIEF = """# A story

Summary.

## Timeline

- 2026-11-02 01:30 UTC: First headline. A second sentence with detail.
- 2026-11-02 06:05 UTC: Only a headline, with its closing full stop.
- 2026-11-02 09:40 UTC (corrects an earlier update): Correction: a thing was wrong. More.
- Older updates are left out of this brief: read them with the updates call.
- 2026-11-03 03:50 UTC (corrects the 2026-11-02 06:05 update): Correction: the right thing. Detail.

## Sources

- 2026-11-09 03:50 UTC: not in the timeline, so not a row
"""


class Reading(unittest.TestCase):
    def test_the_example_brief(self):
        title, items = card.parse_brief(example_brief())
        self.assertTrue(title.startswith("Delhi NCR's air turns 'severe'"))
        self.assertEqual(len(items), 4)
        self.assertEqual(items[0]["at"], utc(2026, 11, 2, 1, 30))
        self.assertEqual(items[0]["headline"], "Air quality across Delhi NCR falls to 'severe' as readings pass 450")
        self.assertEqual(items[1]["headline"], "Schools across Delhi NCR move classes online until Friday")  # no second sentence
        self.assertEqual(items[3]["corrects"], utc(2026, 11, 2, 6, 5))
        self.assertTrue(items[3]["headline"].startswith("Correction: only Delhi's primary schools moved online"))
        self.assertIsNone(items[0]["corrects"])

    def test_every_shape_the_brief_builder_writes(self):
        _title, items = card.parse_brief(BRIEF)
        self.assertEqual([i["headline"] for i in items], [
            "First headline", "Only a headline, with its closing full stop", "Correction: a thing was wrong", "Correction: the right thing"])
        self.assertIs(items[2]["corrects"], card.UNKNOWN_TARGET)  # "(corrects an earlier update)"
        self.assertEqual(items[3]["corrects"], utc(2026, 11, 2, 6, 5))

    def test_only_the_timeline_section_counts(self):
        _title, items = card.parse_brief(BRIEF)
        self.assertEqual(len(items), 4)  # the line under ## Sources isn't a row; nor is the note about older updates

    def test_no_timeline(self):
        with self.assertRaises(card.InputError):
            card.parse_brief("# Title\n\n## Sources\n\n- https://example.com/\n")

    def test_the_headline_ends_at_the_first_sentence(self):
        self.assertEqual(card.split_headline("One. Two. Three."), "One")
        self.assertEqual(card.split_headline("Just one."), "Just one")
        self.assertEqual(card.split_headline("No stop"), "No stop")
        self.assertEqual(card.split_headline("Version 2.5 is out. More."), "Version 2.5 is out")


class Items(unittest.TestCase):
    def test_a_correction_finds_its_target_by_id_by_time_or_not_at_all(self):
        items = card.read_items([
            {"id": "a", "at": "2026-11-02T01:30:00Z", "headline": "One"},
            {"id": "b", "reportedAt": "2026-11-02T03:00:00Z", "headline": "Two", "corrects": "a"},
            {"at": "2026-11-02T04:00:00Z", "headline": "Three", "corrects": "2026-11-02T01:30:00Z"},
            {"at": "2026-11-02T05:00:00Z", "headline": "Four", "corrects": "no such update"},
            {"at": "2026-11-02T06:00:00Z", "headline": "Five", "corrects": None},
        ])
        self.assertEqual(items[1]["corrects"], utc(2026, 11, 2, 1, 30))
        self.assertEqual(items[2]["corrects"], utc(2026, 11, 2, 1, 30))
        self.assertIs(items[3]["corrects"], card.UNKNOWN_TARGET)
        self.assertIsNone(items[4]["corrects"])

    def test_times(self):
        items = card.read_items([{"at": "2026-11-02T07:00:00+05:30", "headline": "x"}, {"at": "2026-11-02T01:30:00", "headline": "y"}])
        self.assertEqual(items[0]["at"], utc(2026, 11, 2, 1, 30))
        self.assertEqual(items[1]["at"], utc(2026, 11, 2, 1, 30))  # no zone means UTC

    def test_refused(self):
        for bad in ([], {}, [1], [{"at": "2026-11-02T01:30:00Z"}], [{"at": "yesterday", "headline": "x"}], [{"headline": "x"}],
                    [{"at": "2026-11-02T01:30:00Z", "headline": "x" * 301}], [{"at": "2026-11-02T01:30:00Z", "headline": "x", "corrects": 5}]):
            with self.assertRaises(card.InputError, msg=repr(bad)[:60]):
                card.read_items(bad)

    def test_the_newest_are_kept_oldest_first(self):
        items = [{"at": utc(2026, 11, 2, h), "headline": str(h), "corrects": None, "id": None} for h in (5, 1, 3, 2, 4)]
        kept, left_out = card.select(items, 3)
        self.assertEqual([i["headline"] for i in kept], ["3", "4", "5"])
        self.assertEqual(left_out, 2)
        kept, left_out = card.select(items, 6)
        self.assertEqual((len(kept), left_out), (5, 0))


class Times(unittest.TestCase):
    def test_zones(self):
        self.assertEqual(card.parse_zone("UTC"), UTC)
        self.assertEqual(card.parse_zone("+05:30").utcoffset(None).total_seconds(), 5.5 * 3600)
        self.assertEqual(card.parse_zone("-0330").utcoffset(None).total_seconds(), -3.5 * 3600)
        for bad in ("Mars/Base", "+24:00", "", "5"):
            with self.assertRaises(card.InputError, msg=bad):
                card.parse_zone(bad)

    def test_a_named_zone_shows_its_own_abbreviation(self):
        zone = card.parse_zone("Asia/Kolkata")
        self.assertEqual(card.date_text(utc(2026, 11, 2, 1, 30), zone, False), "2 Nov")
        self.assertEqual(card.time_text(utc(2026, 11, 2, 1, 30), zone), "07:00 IST")
        self.assertEqual(card.date_text(utc(2026, 11, 2, 1, 30), zone, True), "2 Nov 2026")

    def test_a_late_time_moves_to_the_next_day(self):
        zone = card.parse_zone("+05:30")
        self.assertEqual(card.date_text(utc(2026, 12, 31, 20, 0), zone, False), "1 Jan")


class Rows(unittest.TestCase):
    def texts(self, items, left_out=0, tz="Asia/Kolkata"):
        return card.build_texts(items, left_out, "A title", card.parse_zone(tz))

    def test_the_example_card(self):
        _title, items = card.parse_brief(example_brief())
        texts, groups = self.texts(items)
        self.assertEqual(texts["when1"], "2 Nov\n07:00 IST")
        self.assertEqual(texts["what2"], "Schools across Delhi NCR move classes online until Friday")
        self.assertEqual(texts["mark2"], "Corrected 3 Nov, 09:20 IST")  # the corrected row says so too
        self.assertNotIn("mark1", texts)
        self.assertNotIn("mark3", texts)
        self.assertEqual(texts["when4"], "3 Nov\n09:20 IST")
        self.assertEqual(texts["mark4"], "Corrects the 2 Nov, 11:35 IST update")
        self.assertTrue(texts["what4"].startswith("Only Delhi's primary schools moved online"))  # "Correction:" is in the mark
        self.assertEqual(texts["subtitle"], "Latest update: 3 Nov 2026, 09:20 IST")
        self.assertNotIn("more", texts)
        self.assertEqual(texts["note"], "Sources are attached to the post.")
        self.assertEqual(len(groups), 3)

    def test_an_unknown_target_is_still_a_correction(self):
        _title, items = card.parse_brief(BRIEF)
        texts, _groups = self.texts(items, tz="UTC")
        self.assertEqual(texts["mark3"], "Correction")

    def test_a_row_that_corrects_and_is_corrected_says_both_briefly(self):
        items = [
            {"at": utc(2026, 11, 2, 1), "headline": "First claim", "corrects": None, "id": None},
            {"at": utc(2026, 11, 3, 1), "headline": "Correction: second claim", "corrects": utc(2026, 11, 2, 1), "id": None},
            {"at": utc(2026, 11, 4, 1), "headline": "Correction: third claim", "corrects": utc(2026, 11, 3, 1), "id": None},
        ]
        texts, _groups = self.texts(items, tz="UTC")
        self.assertEqual(texts["mark1"], "Corrected 3 Nov, 01:00 UTC")
        self.assertEqual(texts["mark2"], "Corrects 2 Nov, 01:00 UTC. Corrected 4 Nov, 01:00 UTC")
        self.assertEqual(texts["mark3"], "Corrects the 3 Nov, 01:00 UTC update")

    def test_the_earliest_correction_is_the_one_named(self):
        items = [
            {"at": utc(2026, 11, 2, 1), "headline": "Claim", "corrects": None, "id": None},
            {"at": utc(2026, 11, 3, 1), "headline": "Correction: one", "corrects": utc(2026, 11, 2, 1), "id": None},
            {"at": utc(2026, 11, 4, 1), "headline": "Correction: two", "corrects": utc(2026, 11, 2, 1), "id": None},
        ]
        self.assertEqual(self.texts(items, tz="UTC")[0]["mark1"], "Corrected 3 Nov, 01:00 UTC")

    def test_a_target_that_is_not_on_the_card_or_not_known_marks_no_other_row(self):
        items = [
            {"at": utc(2026, 11, 2, 1), "headline": "Claim", "corrects": None, "id": None},
            {"at": utc(2026, 11, 3, 1), "headline": "Correction: of an older one", "corrects": utc(2026, 10, 1, 1), "id": None},
            {"at": utc(2026, 11, 4, 1), "headline": "Correction: of something", "corrects": card.UNKNOWN_TARGET, "id": None},
        ]
        texts, _groups = self.texts(items, tz="UTC")
        self.assertNotIn("mark1", texts)
        self.assertEqual(texts["mark2"], "Corrects the 1 Oct, 01:00 UTC update")
        self.assertEqual(texts["mark3"], "Correction")

    def test_how_many_are_left_out(self):
        _title, items = card.parse_brief(BRIEF)
        self.assertEqual(self.texts(items, 1)[0]["more"], "1 earlier update is not shown")
        self.assertEqual(self.texts(items, 7)[0]["more"], "7 earlier updates are not shown")

    def test_the_year_is_shown_only_when_it_changes(self):
        one = [{"at": utc(2026, 12, 31, 1), "headline": "a", "corrects": None, "id": None},
               {"at": utc(2027, 1, 2, 1), "headline": "b", "corrects": None, "id": None}]
        self.assertTrue(self.texts(one, tz="UTC")[0]["when1"].startswith("31 Dec 2026"))
        self.assertTrue(self.texts(one[1:], tz="UTC")[0]["when1"].startswith("2 Jan\n"))

    def test_a_correction_keeps_a_headline_that_does_not_start_with_the_word(self):
        self.assertEqual(card.plain_correction("Correction: only X"), "Only X")
        self.assertEqual(card.plain_correction("correction : only X"), "Only X")
        self.assertEqual(card.plain_correction("The figure was wrong"), "The figure was wrong")


class Template(unittest.TestCase):
    def load(self):
        with open(os.path.join(ROOT, "skills", "timeline", "assets", "templates", "timeline-card.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_the_template_follows_the_design(self):
        self.assertEqual(catalogue.template_problems("timeline-card", self.load()), [])

    def test_it_has_a_slot_for_everything_the_script_fills(self):
        slots = {t["slot"] for t in self.load()["texts"]}
        _title, items = card.parse_brief(BRIEF)
        texts, _groups = card.build_texts(items, 3, "T", card.parse_zone("UTC"))
        self.assertLessEqual(set(texts), slots)

    def test_spread_rows_never_overlap_or_leave_the_card(self):
        template = self.load()
        for count in range(1, card.ROWS + 1):
            spread = card.spread_rows(template, count)
            slots = {t["slot"]: t["box"] for t in spread["texts"]}
            self.assertEqual(sorted(s for s in slots if s.startswith("what")), ["what%d" % r for r in range(1, count + 1)])
            for kind in ("when", "mark", "what"):
                for row in range(1, count + 1):
                    box = slots["%s%d" % (kind, row)]
                    self.assertTrue(0 <= box[1] < box[3] <= 1, (count, kind, row, box))
            for row in range(1, count):
                self.assertLessEqual(slots["what%d" % row][3], slots["what%d" % (row + 1)][1] + 1e-9, (count, row))
                self.assertLessEqual(slots["mark%d" % row][3], slots["when%d" % (row + 1)][1] + 1e-9, (count, row))
            self.assertLessEqual(slots["what%d" % count][3], slots["note"][1] if "note" in slots else 1)

    def test_six_rows_are_the_template_itself(self):
        template = self.load()
        spread = card.spread_rows(template, 6)
        self.assertEqual(len(template["texts"]), len(spread["texts"]))
        for a, b in zip(template["texts"], spread["texts"]):
            for x, y in zip(a["box"], b["box"]):
                self.assertAlmostEqual(x, y)

    def test_spreading_leaves_the_template_alone(self):
        template = self.load()
        before = copy.deepcopy(template)
        card.spread_rows(template, 3)
        self.assertEqual(template, before)


class Command(unittest.TestCase):
    def run_card(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = card.main(argv)
        return code, json.loads(out.getvalue().strip().split("\n")[-1])

    def test_bad_input_exits_2_with_the_json_line_and_before_anything_is_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = os.path.join(folder, "none.json")
            code, report = self.run_card(["--items", missing, "--out", os.path.join(folder, "c.png")])
            self.assertEqual(code, 2)
            self.assertEqual(set(report), {"ok", "outputs", "checks", "problem"})
            self.assertFalse(report["ok"])

    def test_the_card_never_overwrites_an_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "items.png")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[]\n")
            code, report = self.run_card(["--items", path, "--out", path])
            self.assertEqual(code, 2)
            self.assertIn("overwrite", report["problem"])

    def test_the_out_name_and_max_items_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "items.json")
            with open(source, "w", encoding="utf-8") as f:
                json.dump([{"at": "2026-11-02T01:30:00Z", "headline": "x"}], f)
            self.assertEqual(self.run_card(["--items", source, "--out", os.path.join(folder, "c.gif")])[0], 2)
            self.assertEqual(self.run_card(["--items", source, "--out", os.path.join(folder, "c.png"), "--max-items", "7"])[0], 2)
            self.assertEqual(self.run_card(["--items", source, "--out", os.path.join(folder, "c.png"), "--tz", "Mars/Base"])[0], 2)


if __name__ == "__main__":
    unittest.main()
