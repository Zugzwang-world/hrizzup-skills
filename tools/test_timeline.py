"""timeline_card.py's reading of updates, times and rows: everything that needs no picture.

The drawing itself needs Pillow, which the repository's check doesn't install; it is proved by the
sample card (skills/timeline/examples/card.png), made by the command and described in its README.
"""

import argparse
import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import types
import unittest
import zoneinfo
from datetime import datetime, timezone
from unittest import mock

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
EXAMPLES = os.path.join(ROOT, "skills", "timeline", "examples")


def utc(*parts):
    return datetime(*parts, tzinfo=UTC)


def example(name):
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
        return f.read()


def example_updates():
    return json.loads(example("updates.json"))


def item(at, headline, corrects=None, ident=None):
    return {"at": at, "headline": headline, "corrects": corrects, "id": ident}


# brief.ts's exact wording: the note when the oldest updates give way, the marks on a correction, the headline
# written with a full stop when it had none, then a space and the body.
BRIEF = """# A story

Summary.

## Timeline

- 3 earlier updates are left out: read them with GET /api/v1/social/stories/01a199e9-d180-75ec-8a81-134dd403419a/updates
- 2026-11-02 01:30 UTC: First headline. A second sentence with detail.
- 2026-11-02 06:05 UTC: Only a headline, with its closing full stop.
- 2026-11-02 09:40 UTC (corrects an earlier update): Correction: a thing was wrong. More.
- 2026-11-03 03:50 UTC (corrects the 2026-11-02 06:05 update): Correction: the right thing. Detail.

## Sources

- 2026-11-09 03:50 UTC: not in the timeline, so not a row
"""


class Reading(unittest.TestCase):
    def test_the_example_brief(self):
        title, items, earlier = card.parse_brief(example("brief.md"))
        self.assertTrue(title.startswith("Delhi NCR's air turns 'severe'"))
        self.assertEqual((len(items), earlier), (4, 0))
        self.assertEqual(items[0]["at"], utc(2026, 11, 2, 1, 30))
        self.assertEqual(items[0]["headline"], "Air quality across Delhi NCR falls to 'severe' as readings pass 450")
        self.assertEqual(items[1]["headline"], "Schools across Delhi NCR move classes online until Friday")  # no second sentence
        self.assertEqual(items[3]["corrects"]["at"], utc(2026, 11, 2, 6, 5))
        self.assertTrue(items[3]["headline"].startswith("Correction: only Delhi's primary schools moved online"))
        self.assertIsNone(items[0]["corrects"])

    def test_every_shape_the_brief_builder_writes(self):
        _title, items, _earlier = card.parse_brief(BRIEF)
        self.assertEqual([i["headline"] for i in items], [
            "First headline", "Only a headline, with its closing full stop", "Correction: a thing was wrong", "Correction: the right thing"])
        self.assertIs(items[2]["corrects"], card.UNKNOWN_TARGET)  # "(corrects an earlier update)"
        self.assertEqual(items[3]["corrects"], {"id": None, "at": utc(2026, 11, 2, 6, 5)})

    def test_the_note_about_older_updates_is_read_not_dropped(self):
        for line, count in (("- 3 earlier updates are left out: read them with GET /api/v1/social/stories/x/updates", 3),
                            ("- 1 earlier update is left out: read it with GET /api/v1/social/stories/x/updates", 1)):
            brief = "# T\n\n## Timeline\n\n%s\n- 2026-11-02 01:30 UTC: A headline.\n" % line
            _title, items, earlier = card.parse_brief(brief)
            self.assertEqual((len(items), earlier), (1, count), line)

    def test_only_the_timeline_section_counts(self):
        _title, items, _earlier = card.parse_brief(BRIEF)
        self.assertEqual(len(items), 4)  # the line under ## Sources isn't a row

    def test_no_timeline(self):
        for brief in ("# Title\n\n## Sources\n\n- https://example.com/\n", "# T\n\n## Timeline\n\n- No updates yet\n"):
            with self.assertRaises(card.InputError):
                card.parse_brief(brief)

    def test_the_headline_ends_at_the_first_sentence(self):
        self.assertEqual(card.split_headline("One. Two. Three."), "One")
        self.assertEqual(card.split_headline("Just one."), "Just one")
        self.assertEqual(card.split_headline("No stop"), "No stop")
        self.assertEqual(card.split_headline("Version 2.5 is out. More."), "Version 2.5 is out")
        self.assertEqual(card.split_headline("It was 3. Then it rained."), "It was 3")  # a number is not an abbreviation

    def test_abbreviations_and_initials_do_not_end_a_headline(self):
        # the example updates' own "No. 3" headlines, as brief.ts writes them (a full stop is added)
        self.assertEqual(card.split_headline("Australia's No. 3 reaches a half-century from 61 balls."),
                         "Australia's No. 3 reaches a half-century from 61 balls")
        self.assertEqual(card.split_headline("India's No. 3 brings up a century from 104 balls."),
                         "India's No. 3 brings up a century from 104 balls")
        self.assertEqual(
            card.split_headline("India win by four wickets with 11 balls to spare. Chasing 289, India got home in the 49th "
                                "over. The No. 3's century anchored the chase."),
            "India win by four wickets with 11 balls to spare")
        for text, headline in (
                ("Govt announces Rs. 500 crore relief. Details follow.", "Govt announces Rs. 500 crore relief"),
                ("Mr. Rao and Mrs. Rao arrive. More.", "Mr. Rao and Mrs. Rao arrive"),
                ("Dr. Singh meets the U.S. envoy. More.", "Dr. Singh meets the U.S. envoy"),
                ("J. Smith resigns. More.", "J. Smith resigns"),
                ("Talks at St. Stephen's end. More.", "Talks at St. Stephen's end"),
                ("India vs. Australia is on. More.", "India vs. Australia is on"),
                ("Aid, food, water etc. reach the camp. More.", "Aid, food, water etc. reach the camp")):
            self.assertEqual(card.split_headline(text), headline, text)

    def test_month_abbreviations_do_not_end_a_headline(self):
        self.assertEqual(card.split_headline("Schools stay shut till Jan. 5. More."), "Schools stay shut till Jan. 5")
        for month in ("Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec"):
            self.assertEqual(card.split_headline("Exams from %s. 9 are cancelled. More." % month),
                             "Exams from %s. 9 are cancelled" % month, month)

    def test_a_question_or_an_exclamation_ends_a_headline_and_stays(self):
        self.assertEqual(card.split_headline("Is the air safe? Doctors say stay indoors."), "Is the air safe?")
        self.assertEqual(card.split_headline("Schools shut! Parents are confused."), "Schools shut!")
        self.assertEqual(card.split_headline("Waiting for word… More follows."), "Waiting for word…")
        self.assertEqual(card.split_headline("Is the air safe?"), "Is the air safe?")  # no body: kept whole, with its mark

    def test_a_closing_abbreviation_without_a_body_keeps_its_dot(self):
        self.assertEqual(card.split_headline("Talks with the U.S."), "Talks with the U.S.")

    def test_the_example_brief_never_cuts_a_headline_at_an_abbreviation(self):
        for line, headline in (
                ("- 2026-11-05 08:40 UTC: Australia's No. 3 reaches a half-century from 61 balls.", "Australia's No. 3 reaches a half-century from 61 balls"),
                ("- 2026-11-05 14:10 UTC: India's No. 3 brings up a century from 104 balls.", "India's No. 3 brings up a century from 104 balls")):
            _title, items, _earlier = card.parse_brief("# T\n\n## Timeline\n\n%s\n" % line)
            self.assertEqual(items[0]["headline"], headline)


class Items(unittest.TestCase):
    def test_the_updates_call_as_it_is(self):
        items, more = card.read_items(example_updates())
        self.assertEqual((len(items), more), (4, False))
        self.assertEqual({i["id"] for i in items} >= {"01a19f94-ede0-724c-8617-706149fba27c"}, True)
        correction = next(i for i in items if i["headline"].startswith("Correction"))
        self.assertEqual(correction["corrects"]["id"], "01a19ae2-d780-7a89-96fb-aeeefeab4196")
        self.assertEqual(correction["corrects"]["at"], utc(2026, 11, 2, 6, 5))

    def test_a_bare_list_works_too_and_a_next_page_is_noticed(self):
        answer = example_updates()
        self.assertEqual(card.read_items(answer["updates"])[1], False)
        answer["next"] = "eyJ0IjoiMjAyNi0xMS0wMiJ9"
        self.assertEqual(card.read_items(answer)[1], True)

    def test_a_correction_whose_target_is_not_in_the_answer_is_a_correction_with_no_target(self):
        # withdrawn (brief.ts writes "corrects an earlier update"), or on an older page: never a refusal
        for more in (None, "eyJ0IjoiMjAyNi0xMS0wMiJ9"):
            answer = {"updates": [{"id": "b", "reportedAt": "2026-11-02T02:00:00Z", "headline": "x", "corrects": "gone"},
                                  {"reportedAt": "2026-11-02T01:00:00Z", "headline": "y", "corrects": "also gone"}], "next": more}
            items, flag = card.read_items(answer)
            self.assertIs(items[0]["corrects"], card.UNKNOWN_TARGET)
            self.assertIs(items[1]["corrects"], card.UNKNOWN_TARGET)
            self.assertEqual(flag, more is not None)

    def test_a_row_that_corrects_itself_names_no_target(self):
        items, _more = card.read_items([{"id": "a", "reportedAt": "2026-11-02T02:00:00Z", "headline": "x", "corrects": "a"}])
        self.assertIs(items[0]["corrects"], card.UNKNOWN_TARGET)

    def test_times(self):
        items, _more = card.read_items([{"at": "2026-11-02T07:00:00+05:30", "headline": "x"},
                                        {"reportedAt": "2026-11-02T01:30:00", "headline": "y"}])
        self.assertEqual(items[0]["at"], utc(2026, 11, 2, 1, 30))
        self.assertEqual(items[1]["at"], utc(2026, 11, 2, 1, 30))  # no zone means UTC

    def test_refused(self):
        ok = {"reportedAt": "2026-11-02T01:30:00Z", "headline": "x"}
        for bad in ([], {}, {"updates": "no"}, [1], [{"reportedAt": "2026-11-02T01:30:00Z"}], [{"reportedAt": "yesterday", "headline": "x"}],
                    [{"headline": "x"}], [dict(ok, headline="x" * 301)], [dict(ok, corrects=5)], [dict(ok, id=5)],
                    [dict(ok, id="a"), dict(ok, id="a")]):
            with self.assertRaises(card.InputError, msg=repr(bad)[:60]):
                card.read_items(bad)

    def test_the_newest_are_kept_oldest_first(self):
        items = [item(utc(2026, 11, 2, h), str(h)) for h in (5, 1, 3, 2, 4)]
        kept, left_out = card.select(items, 3)
        self.assertEqual([i["headline"] for i in kept], ["3", "4", "5"])
        self.assertEqual(left_out, 2)
        kept, left_out = card.select(items, 6)
        self.assertEqual((len(kept), left_out), (5, 0))

    def test_updates_of_one_instant_are_ordered_by_id_whatever_the_input_order(self):
        a, b = item(utc(2026, 11, 2, 1), "a", ident="01"), item(utc(2026, 11, 2, 1), "b", ident="02")
        self.assertEqual([i["id"] for i in card.select([b, a], 6)[0]], ["01", "02"])
        self.assertEqual([i["id"] for i in card.select([a, b], 6)[0]], ["01", "02"])


class Times(unittest.TestCase):
    def test_the_default_is_india_time(self):
        args = card.make_parser().parse_args(["--items", "x.json", "--out", "c.png"])
        self.assertEqual(args.tz, "Asia/Kolkata")
        self.assertEqual(card.DEFAULT_ZONE, "Asia/Kolkata")

    def test_zones(self):
        self.assertEqual(card.parse_zone("UTC"), UTC)
        self.assertEqual(card.parse_zone("+05:30").utcoffset(None).total_seconds(), 5.5 * 3600)
        self.assertEqual(card.parse_zone("-0330").utcoffset(None).total_seconds(), -3.5 * 3600)
        for bad in ("+24:00", "5"):
            with self.assertRaises((card.InputError, card.NoZoneData), msg=bad):
                card.parse_zone(bad)

    def test_a_named_zone_shows_its_own_abbreviation(self):
        zone = card.parse_zone("Asia/Kolkata")
        self.assertEqual(card.date_text(utc(2026, 11, 2, 1, 30), zone, False), "2 Nov")
        self.assertEqual(card.time_text(utc(2026, 11, 2, 1, 30), zone), "07:00 IST")
        self.assertEqual(card.date_text(utc(2026, 11, 2, 1, 30), zone, True), "2 Nov 2026")

    def test_a_late_time_moves_to_the_next_day(self):
        zone = card.parse_zone("+05:30")
        self.assertEqual(card.date_text(utc(2026, 12, 31, 20, 0), zone, False), "1 Jan")

    def test_india_and_utc_work_without_any_time_zone_data(self):
        with mock.patch("zoneinfo.ZoneInfo", side_effect=zoneinfo.ZoneInfoNotFoundError("no data")), \
                mock.patch("zoneinfo.available_timezones", return_value=set()):
            zone = card.parse_zone("Asia/Kolkata")
            self.assertEqual(card.time_text(utc(2026, 11, 2, 1, 30), zone), "07:00 IST")  # the zone still shows
            self.assertEqual(card.date_text(utc(2026, 11, 2, 20, 0), zone, False), "3 Nov")
            self.assertEqual(card.parse_zone("UTC"), UTC)

    def test_another_name_without_data_exits_3_naming_the_fix(self):
        with mock.patch("zoneinfo.ZoneInfo", side_effect=zoneinfo.ZoneInfoNotFoundError("no data")), \
                mock.patch("zoneinfo.available_timezones", return_value=set()):
            with self.assertRaises(card.NoZoneData) as caught:
                card.parse_zone("Europe/London")
            self.assertIn("tzdata", str(caught.exception))
            with tempfile.TemporaryDirectory() as folder:
                source = os.path.join(folder, "u.json")
                with open(source, "w", encoding="utf-8") as f:
                    json.dump(example_updates(), f)
                code, report = run_main(["--items", source, "--out", os.path.join(folder, "c.png"), "--tz", "Europe/London"])
            self.assertEqual(code, 3)
            self.assertIn("tzdata", report["problem"])

    def test_a_wrong_name_where_there_is_data_is_bad_input(self):
        with self.assertRaises(card.InputError):
            card.parse_zone("Mars/Base")


class Rows(unittest.TestCase):
    def texts(self, items, left_out=0, tz="Asia/Kolkata", **more):
        return card.build_texts(items, left_out, "A title", card.parse_zone(tz), **more)

    def test_the_example_card_from_the_updates_call(self):
        items, more = card.read_items(example_updates())
        kept, left_out = card.select(items, 6)
        texts, groups = self.texts(kept, left_out, more=more, everyone=items)
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

    def test_the_brief_and_the_updates_call_make_the_same_card(self):
        title, from_brief, _earlier = card.parse_brief(example("brief.md"))
        items, _more = card.read_items(example_updates())
        a = self.texts(card.select(from_brief, 6)[0], 0, everyone=from_brief)[0]
        b = self.texts(card.select(items, 6)[0], 0, everyone=items)[0]
        self.assertEqual(a, b)

    def test_an_unknown_target_is_still_a_correction(self):
        _title, items, _earlier = card.parse_brief(BRIEF)
        texts, _groups = self.texts(items, tz="UTC")
        self.assertEqual(texts["mark3"], "Correction")

    def test_a_row_that_corrects_and_is_corrected_says_both_briefly(self):
        items, _more = card.read_items([
            {"id": "a", "reportedAt": "2026-11-02T01:00:00Z", "headline": "First claim"},
            {"id": "b", "reportedAt": "2026-11-03T01:00:00Z", "headline": "Correction: second claim", "corrects": "a"},
            {"id": "c", "reportedAt": "2026-11-04T01:00:00Z", "headline": "Correction: third claim", "corrects": "b"}])
        texts, _groups = self.texts(card.select(items, 6)[0], tz="UTC")
        self.assertEqual(texts["mark1"], "Corrected 3 Nov, 01:00 UTC")
        self.assertEqual(texts["mark2"], "Corrects 2 Nov, 01:00 UTC. Corrected 4 Nov, 01:00 UTC")
        self.assertEqual(texts["mark3"], "Corrects the 3 Nov, 01:00 UTC update")

    def test_the_earliest_correction_is_the_one_named(self):
        items, _more = card.read_items([
            {"id": "a", "reportedAt": "2026-11-02T01:00:00Z", "headline": "Claim"},
            {"id": "b", "reportedAt": "2026-11-04T01:00:00Z", "headline": "Correction: two", "corrects": "a"},
            {"id": "c", "reportedAt": "2026-11-03T01:00:00Z", "headline": "Correction: one", "corrects": "a"}])
        self.assertEqual(self.texts(card.select(items, 6)[0], tz="UTC")[0]["mark1"], "Corrected 3 Nov, 01:00 UTC")

    def test_another_update_in_the_same_minute_is_not_marked_corrected(self):
        # the reviewer's case: b is in a's minute but is not what c corrects
        items, _more = card.read_items([
            {"id": "a", "reportedAt": "2026-12-31T18:20:00Z", "headline": "First claim about the thing"},
            {"id": "b", "reportedAt": "2026-12-31T18:20:30Z", "headline": "Another update in the same minute, never corrected"},
            {"id": "c", "reportedAt": "2026-12-31T23:50:00Z", "headline": "Correction: the first claim was wrong", "corrects": "a"},
            {"id": "d", "reportedAt": "2027-01-01T03:50:00Z", "headline": "Correction: the new claim was also wrong", "corrects": "c"}])
        texts, _groups = self.texts(card.select(items, 6)[0], tz="UTC")
        self.assertEqual(texts["mark1"], "Corrected 31 Dec 2026, 23:50 UTC")
        self.assertNotIn("mark2", texts)  # b, in a's minute, is left alone
        self.assertEqual(texts["mark3"], "Corrects 31 Dec 2026, 18:20 UTC. Corrected 1 Jan 2027, 03:50 UTC")

    def test_with_only_minutes_and_two_updates_in_one_neither_is_marked(self):
        brief = ("# T\n\n## Timeline\n\n- 2026-11-02 06:05 UTC: One claim.\n- 2026-11-02 06:05 UTC: Another claim.\n"
                 "- 2026-11-03 03:50 UTC (corrects the 2026-11-02 06:05 update): Correction: it was one of them.\n")
        _title, items, _earlier = card.parse_brief(brief)
        texts, _groups = self.texts(card.select(items, 6)[0], tz="UTC", everyone=items)
        self.assertNotIn("mark1", texts)
        self.assertNotIn("mark2", texts)
        self.assertEqual(texts["mark3"], "Corrects the 2 Nov, 06:05 UTC update")  # the correction still says what the brief says

    def test_a_minute_shared_with_an_update_the_card_leaves_out_also_marks_neither(self):
        brief = ("# T\n\n## Timeline\n\n- 2026-11-02 06:05 UTC: One claim.\n- 2026-11-02 06:05 UTC: Another claim.\n"
                 "- 2026-11-03 03:50 UTC (corrects the 2026-11-02 06:05 update): Correction: it was one of them.\n")
        _title, items, _earlier = card.parse_brief(brief)
        kept, left_out = card.select(items, 2)  # the card keeps one of the two claims and the correction
        texts, _groups = self.texts(kept, left_out, tz="UTC", everyone=items)
        self.assertNotIn("mark1", texts)

    def test_a_target_that_is_not_on_the_card_marks_no_other_row(self):
        items = [item(utc(2026, 11, 2, 1), "Claim", ident="a"),
                 item(utc(2026, 11, 3, 1), "Correction: of an older one", {"id": "old", "at": utc(2026, 10, 1, 1)}, "b"),
                 item(utc(2026, 11, 4, 1), "Correction: of something", card.UNKNOWN_TARGET, "c")]
        texts, _groups = self.texts(items, tz="UTC")
        self.assertNotIn("mark1", texts)
        self.assertEqual(texts["mark2"], "Corrects the 1 Oct, 01:00 UTC update")
        self.assertEqual(texts["mark3"], "Correction")

    def test_how_many_are_left_out(self):
        _title, items, _earlier = card.parse_brief(BRIEF)
        self.assertEqual(self.texts(items, 1)[0]["more"], "1 earlier update is not shown")
        self.assertEqual(self.texts(items, 7)[0]["more"], "7 earlier updates are not shown")

    def test_an_answer_with_a_next_page_cannot_say_how_many(self):
        _title, items, _earlier = card.parse_brief(BRIEF)
        self.assertEqual(self.texts(items, 2, more=True)[0]["more"], "2 or more earlier updates are not shown")
        self.assertEqual(self.texts(items, 0, more=True)[0]["more"], "Earlier updates are not shown")

    def test_the_year_is_shown_only_when_it_changes(self):
        one = [item(utc(2026, 12, 31, 1), "a"), item(utc(2027, 1, 2, 1), "b")]
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
        _title, items, _earlier = card.parse_brief(BRIEF)
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


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = card.main(argv)
    return code, json.loads(out.getvalue().strip().split("\n")[-1])


def namespace(**given):
    base = dict(items=None, brief=None, out=None, tz="Asia/Kolkata", max_items=6, title=None, style=None)
    base.update(given)
    return argparse.Namespace(**base)


class Command(unittest.TestCase):
    def test_bad_input_exits_2_with_the_json_line_and_before_anything_is_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = os.path.join(folder, "none.json")
            code, report = run_main(["--items", missing, "--out", os.path.join(folder, "c.png")])
            self.assertEqual(code, 2)
            self.assertEqual(set(report), {"ok", "outputs", "checks", "problem"})
            self.assertFalse(report["ok"])

    def test_a_missing_output_folder_is_found_before_any_work_and_exits_2(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "u.json")
            with open(source, "w", encoding="utf-8") as f:
                json.dump(example_updates(), f)
            code, report = run_main(["--items", source, "--out", os.path.join(folder, "no-such-folder", "card.png")])
            self.assertEqual(code, 2)  # not a traceback after the drawing, and not exit 3 for the missing Pillow
            self.assertIn("folder", report["problem"])
            self.assertFalse(os.path.exists(os.path.join(folder, "no-such-folder")))

    def test_the_card_never_overwrites_an_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "items.png")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[]\n")
            code, report = run_main(["--items", path, "--out", path])
            self.assertEqual(code, 2)
            self.assertIn("overwrite", report["problem"])

    def test_a_wrong_command_line_is_bad_input_with_the_json_line_not_argparses_own_exit(self):
        for argv in (["--out", "c.png"], ["--bogus"], ["--items", "x.json"], ["--items", "x.json", "--out", "c.png", "--max-items", "many"]):
            code, report = run_main(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(report["ok"])
            self.assertTrue(report["problem"])
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
            card.main(["--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_a_link_to_an_input_is_the_input(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "items.json")
            with open(source, "w", encoding="utf-8") as f:
                json.dump(example_updates(), f)
            for make_link in (os.symlink, os.link):
                link = os.path.join(folder, "c-%s.png" % make_link.__name__)
                try:
                    make_link(source, link)
                except (OSError, NotImplementedError):
                    continue
                code, report = run_main(["--items", source, "--out", link])
                self.assertEqual((code, "overwrite" in report["problem"]), (2, True), make_link.__name__)
            with open(source, encoding="utf-8") as f:
                self.assertEqual(json.load(f), example_updates())

    def test_whatever_goes_wrong_the_last_line_is_the_json_line(self):
        fake = types.ModuleType("hrizzup_draw")

        class DrawError(Exception):
            code = 2

        fake.DrawError = DrawError
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "items.json")
            with open(source, "w", encoding="utf-8") as f:
                json.dump(example_updates(), f)
            argv = ["--items", source, "--out", os.path.join(folder, "c.png")]
            for error, code in ((RuntimeError("boom"), 1), (KeyError("slot"), 1), (ImportError("No module named x"), 3)):
                fake.load_style = mock.Mock(side_effect=error)
                with mock.patch.dict(sys.modules, {"hrizzup_draw": fake}):
                    got, report = run_main(argv)
                self.assertEqual(got, code, error)
                self.assertFalse(report["ok"])
                self.assertEqual(set(report), {"ok", "outputs", "checks", "problem"})
                self.assertTrue(report["problem"])

    def test_the_out_name_and_max_items_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "items.json")
            with open(source, "w", encoding="utf-8") as f:
                json.dump([{"reportedAt": "2026-11-02T01:30:00Z", "headline": "x"}], f)
            self.assertEqual(run_main(["--items", source, "--out", os.path.join(folder, "c.gif")])[0], 2)
            self.assertEqual(run_main(["--items", source, "--out", os.path.join(folder, "c.png"), "--max-items", "7"])[0], 2)
            self.assertEqual(run_main(["--items", source, "--out", os.path.join(folder, "c.png"), "--tz", "Mars/Base"])[0], 2)

    def test_a_withdrawn_target_marks_the_row_correction_and_a_next_page_keeps_its_line(self):
        update = {"id": "b", "reportedAt": "2026-11-02T01:30:00Z", "headline": "Correction: the figure was wrong", "corrects": "a"}
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "u.json")
            for answer, line in (({"updates": [update], "next": None}, None),
                                 ({"updates": [update], "next": "eyJ0IjoiMjAyNi0xMS0wMiJ9"}, "Earlier updates are not shown")):
                with open(source, "w", encoding="utf-8") as f:
                    json.dump(answer, f)
                _kept, _left, texts, _groups, _zone, _out = card.run(namespace(items=source, out=os.path.join(folder, "c.png")))
                self.assertEqual(texts["mark1"], "Correction")  # no target to name, and no exit 2
                self.assertEqual(texts["what1"], "The figure was wrong")
                self.assertEqual(texts.get("more"), line)

    def test_the_notes_of_a_brief_reach_the_card(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "brief.md")
            with open(source, "w", encoding="utf-8") as f:
                f.write(BRIEF)
            kept, left_out, texts, _groups, _zone, _out = card.run(namespace(brief=source, out=os.path.join(folder, "c.png")))
            self.assertEqual(left_out, 3)  # the brief's own note: three older updates, none of them kept here
            self.assertEqual(texts["more"], "3 earlier updates are not shown")
            self.assertEqual(len(kept), 4)
            _k, left_out, texts, _g, _z, _o = card.run(namespace(brief=source, out=os.path.join(folder, "c.png"), max_items=2))
            self.assertEqual((left_out, texts["more"]), (5, "5 earlier updates are not shown"))  # the note's 3 and the 2 dropped

    def test_the_updates_call_reaches_the_card_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "u.json")
            with open(source, "w", encoding="utf-8") as f:
                f.write(example("updates.json"))
            kept, left_out, texts, _groups, zone, _out = card.run(namespace(items=source, out=os.path.join(folder, "c.png"), title="T"))
            self.assertEqual((len(kept), left_out, texts["title"]), (4, 0, "T"))
            self.assertEqual(texts["mark2"], "Corrected 3 Nov, 09:20 IST")
            self.assertEqual(texts["when1"], "2 Nov\n07:00 IST")  # the default zone, India's, with its name


if __name__ == "__main__":
    unittest.main()
