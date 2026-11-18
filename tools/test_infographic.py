"""infographic.py's reading of its spec and its layout maths: everything that needs no picture and no matplotlib.

The drawing itself needs Pillow and matplotlib, which the repository's check doesn't install; it is proved by the
sample (skills/infographic/examples/infographic.png), made by the command and described in its README.
"""

import contextlib
import copy
import io
import json
import os
import random
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "infographic", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import importlib.util  # noqa: E402

import catalogue  # noqa: E402

spec = importlib.util.spec_from_file_location("infographic_under_test", os.path.join(SCRIPTS, "infographic.py"))
info = importlib.util.module_from_spec(spec)
spec.loader.exec_module(info)

KIT = os.path.join(ROOT, "skills", "infographic")


def template(name):
    with open(os.path.join(KIT, "assets", "templates", name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def example_spec():
    with open(os.path.join(KIT, "examples", "spec.json"), encoding="utf-8") as f:
        return json.load(f)


def measure(text, role, size):
    """A stand-in for a font: every character is 0.55 of the size wide (a bold one a little wider)."""
    return len(text) * size * (0.6 if role == "text-bold" else 0.55)


def wrap(text, role, size, width):
    lines, current = [], ""
    for word in text.split():
        trial = word if not current else current + " " + word
        if measure(trial, role, size) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    return lines + [current]


BARS = {"template": "chart-card", "title": "T", "source": "S",
        "chart": {"type": "bar", "unit": "AQI", "data": [{"label": "Delhi", "value": 462}, {"label": "Noida", "value": 231}]}}


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = info.main(argv)
    return code, json.loads(out.getvalue().strip().split("\n")[-1])


def refused(case, **changes):
    """The spec with some keys changed (None removes one) is refused as bad input."""
    changed = copy.deepcopy(case)
    for key, value in changes.items():
        if value is None:
            changed.pop(key, None)
        else:
            changed[key] = value
    return changed


class Spec(unittest.TestCase):
    def test_the_example_spec_is_valid(self):
        checked = info.validate_spec(example_spec())
        self.assertEqual(checked["template"], "chart-card")
        self.assertEqual(len(checked["chart"]["bands"]), 6)
        self.assertEqual(checked["chart"]["marker"]["value"], 450)

    def test_the_source_is_required_on_every_template(self):
        for case in (BARS, refused(BARS, template="stat-card", chart={"type": "stat", "value": "1", "label": "l"}),
                     {"template": "steps-card", "title": "T", "steps": ["a", "b"], "source": "S"}):
            self.assertTrue(info.validate_spec(case)["source"])
            for bad in (None, "", "   ", 5):
                with self.assertRaises(info.InputError, msg=repr(bad)):
                    info.validate_spec(refused(case, source=bad))

    def test_the_basic_rules(self):
        cases = [
            refused(BARS, template="poster"), refused(BARS, template=None), refused(BARS, title=None), refused(BARS, title="x" * 141),
            refused(BARS, subtitle="x" * 201), refused(BARS, extra=1), refused(BARS, steps=["a", "b"]),
            refused(BARS, image="chart.png"),  # both a chart and an image
            refused(BARS, chart=None),  # neither
            "not an object", ["a list"],
        ]
        for case in cases:
            with self.subTest(case=str(case)[:60]), self.assertRaises(info.InputError):
                info.validate_spec(case)

    def test_an_image_instead_of_a_chart(self):
        checked = info.validate_spec(refused(BARS, chart=None, image="chart.png"))
        self.assertEqual(checked["image"], "chart.png")

    def test_bars_start_at_zero(self):
        data = [{"label": "a", "value": 5}, {"label": "b", "value": -1}]
        for kind in ("bar", "column"):
            with self.assertRaises(info.InputError, msg=kind):
                info.validate_spec(refused(BARS, chart={"type": kind, "data": data}))
        with self.assertRaises(info.InputError):
            info.validate_spec(refused(BARS, chart={"type": "line", "data": data}))  # a line starts at zero unless it says not
        checked = info.validate_spec(refused(BARS, chart={"type": "line", "data": data, "from_zero": False}))
        self.assertFalse(checked["chart"]["from_zero"])
        with self.assertRaises(info.InputError):
            info.validate_spec(refused(BARS, chart={"type": "bar", "data": data[:1], "from_zero": False}))

    def test_data_rules(self):
        one = {"label": "a", "value": 1}
        cases = [
            {"type": "bar", "data": []}, {"type": "bar", "data": "x"}, {"type": "bar", "data": [one, one]},  # a label twice
            {"type": "bar", "data": [{"label": "a", "value": "5"}]}, {"type": "bar", "data": [{"label": "a", "value": True}]},
            {"type": "bar", "data": [{"label": "a", "value": float("inf")}]}, {"type": "bar", "data": [{"label": "a", "value": 0}]},
            {"type": "bar", "data": [{"label": "", "value": 1}]}, {"type": "bar", "data": [dict(one, extra=1)]},
            {"type": "bar", "data": [one] * 1 + [{"label": str(n), "value": 1} for n in range(info.MAX_BARS)]},
            {"type": "column", "data": [{"label": str(n), "value": 1} for n in range(info.MAX_COLUMNS + 1)]},
            {"type": "line", "data": [one]}, {"type": "pie", "data": [one]}, {"type": "bar", "data": [one], "unit": "x" * 13},
            {"type": "bar", "data": [one], "highlight": "nobody"}, {"type": "bar", "data": [one], "highlight": ["a"] * 4},
            {"type": "bar", "data": [one], "colour": "red"},
        ]
        for chart in cases:
            with self.subTest(chart=str(chart)[:70]), self.assertRaises(info.InputError):
                info.validate_spec(refused(BARS, chart=chart))
        good = info.validate_spec(refused(BARS, chart={"type": "bar", "data": [one, {"label": "b", "value": 2, "text": "2 lakh"}], "highlight": "b"}))
        self.assertEqual(good["chart"]["highlight"], ["b"])

    def test_scale_rules(self):
        bands = example_spec()["chart"]["bands"]
        chart = lambda **changes: dict(example_spec()["chart"], **changes)  # noqa: E731
        cases = [
            chart(bands=bands[:1]), chart(bands=bands[:2] + [{"name": "x", "from": 150, "to": 400}]),  # overlaps
            chart(bands=[{"name": "a", "from": 5, "to": 5}, bands[1]]), chart(bands=[{"name": "a", "from": 0}, bands[1]]),
            chart(marker={"value": 900, "label": "off the scale"}), chart(marker={"label": "no value"}),
            chart(marker={"value": 450, "colour": "red"}), chart(extra=1),
        ]
        for case in cases:
            with self.subTest(case=str(case)[:70]), self.assertRaises(info.InputError):
                info.validate_spec(refused(example_spec(), chart=case))
        for edge in (0, 500):
            info.validate_spec(refused(example_spec(), chart=chart(marker={"value": edge, "label": "edge"})))
        info.validate_spec(refused(example_spec(), chart=chart(marker=None)))  # a scale with no marker

    def test_a_stat_card_has_no_subtitle(self):
        stat = {"template": "stat-card", "title": "T", "source": "S", "chart": {"type": "stat", "value": "450+", "label": "l"}}
        info.validate_spec(stat)
        for subtitle in ("A line", "", " "):
            with self.assertRaises(info.InputError, msg=repr(subtitle)) as caught:
                info.validate_spec(dict(stat, subtitle=subtitle))
            self.assertIn("a stat-card has no subtitle: put it in the note", str(caught.exception))
        # the other two templates keep theirs
        self.assertEqual(info.validate_spec(dict(BARS, subtitle="Sub"))["subtitle"], "Sub")
        steps = {"template": "steps-card", "title": "T", "source": "S", "steps": ["a", "b"], "subtitle": "Sub"}
        self.assertEqual(info.validate_spec(steps)["subtitle"], "Sub")

    def test_stat_and_steps_rules(self):
        stat = {"template": "stat-card", "title": "T", "source": "S", "chart": {"type": "stat", "value": "450+", "label": "l", "note": "n"}}
        self.assertEqual(info.validate_spec(stat)["chart"]["note"], "n")
        for bad in (refused(stat, chart={"type": "bar", "data": []}), refused(stat, chart={"type": "stat", "value": "x" * 13, "label": "l"}),
                    refused(stat, chart=None), refused(stat, steps=["a", "b"]), refused(stat, chart={"type": "stat", "value": "1"})):
            with self.assertRaises(info.InputError):
                info.validate_spec(bad)
        steps = {"template": "steps-card", "title": "T", "source": "S", "steps": ["one", "two"]}
        self.assertEqual(info.validate_spec(steps)["steps"], ["one", "two"])
        for bad in (refused(steps, steps=["only one"]), refused(steps, steps=["x"] * 6), refused(steps, steps=["a", 7]),
                    refused(steps, steps=["a", "b" * 201]), refused(steps, steps=None), refused(steps, chart=dict(type="stat"))):
            with self.assertRaises(info.InputError):
                info.validate_spec(bad)

    def test_numbers_as_text_are_never_rounded_further_than_the_source(self):
        cases = ((450, "450"), (450.0, "450"), (12.5, "12.5"), (1e3, "1000"), (7.005, "7.005"), (0.001, "0.001"), (0.004, "0.004"),
                 (0.125, "0.125"), (1e-05, "0.00001"), (123456789.123, "123456789.123"), (-2.50, "-2.5"), (0.1 + 0.2, "0.30000000000000004"),
                 (3, "3"), (-0.0, "0"), (1e21, "1000000000000000000000"), (2.5e-07, "0.00000025"), (100.10, "100.1"))
        for value, text in cases:
            self.assertEqual(info.fmt_number(value), text, value)
        self.assertNotEqual(info.fmt_number(0.001), info.fmt_number(0.004))  # two different values never print the same
        self.assertNotIn("e", info.fmt_number(1.5e-9))
        self.assertEqual(info.value_text({"value": 12.5, "text": None}, "%"), "12.5%")
        self.assertEqual(info.value_text({"value": 462, "text": None}, "AQI"), "462 AQI")
        self.assertEqual(info.value_text({"value": 462, "text": None}, None), "462")
        self.assertEqual(info.value_text({"value": 462, "text": "4.6 lakh"}, "AQI"), "4.6 lakh")

    def test_colours_are_tints_of_the_style(self):
        self.assertEqual(info.mix("#FFFFFF", "#111111", 0), "#FFFFFF")
        self.assertEqual(info.mix("#FFFFFF", "#111111", 1), "#111111")
        self.assertEqual(info.mix("#FFFFFF", "#000000", 0.5), "#808080")
        tints = [info.tint_for(n, 6) for n in range(6)]
        self.assertEqual(tints, sorted(tints))
        self.assertAlmostEqual(tints[0], info.TINT_LOW)
        self.assertAlmostEqual(tints[-1], info.TINT_HIGH)
        self.assertEqual(info.tint_for(0, 1), info.TINT_LOW)


class Layout(unittest.TestCase):
    def test_bars_are_in_proportion_and_start_at_the_same_line(self):
        items = info.validate_spec(BARS)["chart"]["data"]
        layout = info.bar_layout(items, "AQI", 928, 742, measure, wrap)
        first, second = layout["rows"]
        self.assertEqual(first["x0"], second["x0"])
        self.assertAlmostEqual((second["x1"] - second["x0"]) / (first["x1"] - first["x0"]), 0.5, places=6)
        self.assertLess(first["y1"], second["y0"])  # they don't overlap
        self.assertLessEqual(first["x1"] + measure(first["value"], "text-bold", layout["value_size"]), 928)  # the label fits

    def test_a_bar_of_zero_has_no_length_and_a_tiny_one_is_still_seen(self):
        items = [{"label": "a", "value": 0, "text": None}, {"label": "b", "value": 0.0001, "text": None}, {"label": "c", "value": 100, "text": None}]
        rows = info.bar_layout(items, None, 928, 742, measure, wrap)["rows"]
        self.assertEqual(rows[0]["x1"], rows[0]["x0"])
        self.assertGreaterEqual(rows[1]["x1"] - rows[1]["x0"], 4)

    def test_a_long_label_is_wrapped_then_refused_with_how_far_to_shorten(self):
        long = "a very long label that cannot possibly fit in its column even in two lines of small text"
        items = [{"label": long, "value": 1, "text": None}]
        with self.assertRaises(info.TooLong) as caught:
            info.bar_layout(items, None, 928, 742, measure, wrap)
        self.assertIn("shorten", str(caught.exception))
        wrapped = [{"label": "Gurugram, central station", "value": 1, "text": None}]
        self.assertEqual(len(info.bar_layout(wrapped, None, 928, 742, measure, wrap)["rows"][0]["lines"]), 2)

    def test_twelve_bars_with_two_line_labels_never_overlap(self):
        items = [{"label": "Station number %d in the city" % n, "value": n, "text": None} for n in range(1, 13)]
        for height in (742, 594):
            try:
                layout = info.bar_layout(items, None, 928, height, measure, wrap)
            except info.TooLong:
                continue  # refusing is fine; overlapping is not
            rows = layout["rows"]
            for a, b in zip(rows, rows[1:]):
                self.assertLessEqual(len(a["lines"]) * layout["label_size"] * info.LINE, b["centre"] - a["centre"] + 1e-9, height)
                self.assertLess(a["y1"], b["y0"])
        tight = [{"label": "a label that needs two lines to be read", "value": n, "text": None} for n in range(1, 13)]
        with self.assertRaises(info.TooLong):
            info.bar_layout(tight, None, 928, 360, measure, wrap)  # not enough height for twelve rows of any label

    def test_a_scale_band_too_narrow_for_its_label_is_refused(self):
        bands = [{"name": "Wide", "from": 0, "to": 1000}, {"name": "Thin", "from": 1000, "to": 1004}]
        chart = {"type": "scale", "bands": bands, "marker": None, "unit": None}
        with self.assertRaises(info.TooLong) as caught:
            info.scale_layout(chart, 928, 742, measure, wrap)
        self.assertIn("too narrow", str(caught.exception))
        bands[1]["to"] = 1300  # in proportion, wide enough
        info.scale_layout(chart, 928, 742, measure, wrap)

    def test_columns_stand_on_one_line_inside_the_chart(self):
        items = [{"label": l, "value": v, "text": None} for l, v in (("Mon", 10), ("Tue", 20.5), ("Wed", 7))]
        layout = info.column_layout(items, "AQI", 928, 594, measure, wrap)
        columns = layout["cols"]
        self.assertTrue(all(c["y1"] == layout["base"] for c in columns))
        self.assertAlmostEqual((columns[0]["y1"] - columns[0]["y0"]) / (columns[1]["y1"] - columns[1]["y0"]), 10 / 20.5, places=6)
        self.assertTrue(all(0 <= c["y0"] and c["x0"] >= 0 and c["x1"] <= 928 for c in columns))
        for a, b in zip(columns, columns[1:]):
            self.assertLess(a["x1"], b["x0"])

    def test_a_line_keeps_its_points_in_order_and_labels_the_ends(self):
        items = [{"label": "%d Nov" % n, "value": v, "text": None} for n, v in enumerate((120, 455, 430, 380, 300), start=1)]
        layout = info.line_layout(items, "AQI", True, 928, 594, measure, wrap, None)
        xs = [p["x"] for p in layout["points"]]
        self.assertEqual(xs, sorted(xs))
        self.assertEqual(layout["named"], [0, 4])
        self.assertTrue(layout["points"][1]["y"] < layout["points"][0]["y"])  # a higher value is higher up
        self.assertTrue(all(0 <= p["y"] <= layout["base"] for p in layout["points"]))
        first, last = layout["points"][0]["label_at"], layout["points"][-1]["label_at"]
        self.assertEqual((first["align"], first["vertical"]), ("right", "center"))  # beside the first point, on its left
        self.assertEqual((last["align"], last["vertical"]), ("left", "center"))  # and beside the last, on its right
        self.assertLess(first["x"], layout["points"][0]["x"])
        self.assertGreater(last["x"], layout["points"][-1]["x"])
        self.assertEqual(layout["shown"][0], 0)
        self.assertEqual(layout["shown"][-1], 4)

    def test_a_crowded_line_skips_axis_labels_but_keeps_the_last(self):
        items = [{"label": "%d November" % n, "value": n, "text": None} for n in range(1, 25)]
        layout = info.line_layout(items, None, True, 928, 594, measure, wrap, None)
        self.assertLess(len(layout["shown"]), 24)
        self.assertEqual(layout["shown"][-1], 23)
        xs = [layout["points"][n]["x"] for n in layout["shown"]]
        widest = max(measure(i["label"], "text", layout["label_size"]) for i in items)
        for a, b in zip(xs, xs[1:]):
            self.assertGreaterEqual(b - a, widest)

    def test_a_line_that_does_not_start_at_zero_does_not_sit_on_the_axis(self):
        items = [{"label": "a", "value": 90, "text": None}, {"label": "b", "value": 100, "text": None}]
        layout = info.line_layout(items, None, False, 928, 594, measure, wrap, None)
        self.assertLess(layout["low"], 90)
        self.assertLess(layout["points"][0]["y"], layout["base"])

    def test_the_scale_is_in_proportion_and_the_marker_is_inside_its_band(self):
        chart = info.validate_spec(example_spec())["chart"]
        layout = info.scale_layout(chart, 928, 742, measure, wrap)
        heights = [b["y1"] - b["y0"] for b in layout["bands"]]
        self.assertAlmostEqual(heights[0], heights[1], places=6)  # 0-50 and 51-100 both span 50
        self.assertAlmostEqual(heights[2] / heights[0], 2, places=6)
        self.assertAlmostEqual(heights[3], heights[5], places=6)
        self.assertLess(layout["bands"][5]["y1"], layout["bands"][4]["y0"] + 1e-9)  # the highest band is on top
        marker = layout["marker"]
        top = layout["bands"][5]
        self.assertTrue(top["y0"] <= marker["y"] <= top["y1"])
        self.assertEqual(marker["inside"], 5)
        self.assertEqual(marker["value"], "450")
        self.assertAlmostEqual(marker["y"], top["y0"] + (500 - 450) / 100 * heights[5], places=6)
        self.assertLessEqual(layout["bands"][0]["y1"], 742)
        self.assertGreaterEqual(layout["bands"][5]["y0"], 0)
        tints = [b["tint"] for b in layout["bands"]]
        self.assertEqual(tints, sorted(tints))  # light at the bottom, dark at the top

    def test_a_scale_without_a_marker_and_names_too_long_for_their_place(self):
        chart = dict(info.validate_spec(example_spec())["chart"], marker=None)
        self.assertIsNone(info.scale_layout(chart, 928, 594, measure, wrap)["marker"])
        wide = dict(chart, bands=[dict(b, name="N" * 24) for b in chart["bands"]])
        with self.assertRaises(info.TooLong):
            info.scale_layout(wide, 520, 594, measure, wrap)

    def test_steps_spread_over_the_same_space_without_overlap(self):
        base = template("steps-card")
        for count in range(2, info.STEP_ROWS + 1):
            spread, rules = info.spread_steps(base, count)
            slots = {t["slot"]: t["box"] for t in spread["texts"]}
            self.assertEqual(sorted(s for s in slots if s.startswith("step")), ["step%d" % r for r in range(1, count + 1)])
            for row in range(1, count + 1):
                for kind in ("n", "step"):
                    box = slots["%s%d" % (kind, row)]
                    self.assertTrue(0 <= box[1] < box[3] <= 1, (count, kind, row))
                    self.assertLess(box[3], slots["source"][1])
            for row in range(1, count):
                self.assertLessEqual(slots["step%d" % row][3], slots["step%d" % (row + 1)][1] + 1e-9)
            self.assertEqual(len(rules), count - 1)
            for rule, row in zip(rules, range(1, count)):  # each rule falls between two rows
                self.assertTrue(slots["step%d" % row][3] <= rule <= slots["step%d" % (row + 1)][1] + 1e-9, (count, row))
        full, rules = info.spread_steps(base, info.STEP_ROWS)
        for a, b in zip(base["texts"], full["texts"]):
            for x, y in zip(a["box"], b["box"]):
                self.assertAlmostEqual(x, y)  # five steps are the template itself

    def test_spreading_leaves_the_template_alone(self):
        base = template("steps-card")
        before = copy.deepcopy(base)
        info.spread_steps(base, 3)
        self.assertEqual(base, before)


class Colours(unittest.TestCase):
    """Text in a tint of ink has WCAG's 4.5 to 1 against the paper; a mark (a fill, a line) has its 3 to 1 for graphics."""

    STYLES = (
        {"ink": "#111111", "paper": "#FFFFFF", "accent": "#111111"},
        {"ink": "#767676", "paper": "#FFFFFF", "accent": "#767676"},  # the lightest grey that has 4.5 to 1 on white
        {"ink": "#222222", "paper": "#F5F0E6", "accent": "#B3261E"},
        {"ink": "#FFFFFF", "paper": "#111111", "accent": "#FFE600"},  # a dark paper
        {"ink": "#111111", "paper": "#FFFFFF", "accent": "#FFE600"},  # a yellow accent that is unreadable on white
    )

    def test_the_contrast_formula(self):
        self.assertAlmostEqual(info.contrast("#000000", "#FFFFFF"), 21.0, places=6)
        self.assertAlmostEqual(info.contrast("#FFFFFF", "#FFFFFF"), 1.0, places=6)
        self.assertGreaterEqual(info.contrast("#767676", "#FFFFFF"), 4.5)
        self.assertLess(info.contrast("#777777", "#FFFFFF"), 4.6)
        self.assertEqual(info.contrast("#112233", "#FFEEDD"), info.contrast("#FFEEDD", "#112233"))

    def test_text_in_a_tint_that_would_not_read_is_darkened_until_it_does(self):
        paper, ink = "#FFFFFF", "#111111"
        self.assertLess(info.contrast(info.mix(paper, ink, 0.3), paper), 4.5)
        floor = info.readable_share(paper, ink)
        self.assertGreaterEqual(info.contrast(info.mix(paper, ink, floor), paper), 4.5)
        self.assertLess(info.contrast(info.mix(paper, ink, floor - 0.01), paper), 4.5)  # and no darker than it has to be
        self.assertEqual(info.shade(paper, ink, 0.3), info.mix(paper, ink, floor))
        self.assertEqual(info.shade(paper, ink, 0.9), info.mix(paper, ink, 0.9))  # a dark enough shade is left alone

    def test_when_no_lighter_shade_reads_the_full_ink_is_used(self):
        for share in (0.0, 0.14, 0.38, 0.75, 0.99):
            self.assertEqual(info.shade("#FFFFFF", "#767676", share), "#767676", share)  # 4.54 to 1: nothing lighter passes

    def test_a_mark_only_needs_3_to_1_so_it_may_be_lighter_than_text(self):
        paper, ink = "#FFFFFF", "#111111"
        text, mark = info.readable_share(paper, ink), info.readable_share(paper, ink, ratio=info.GRAPHIC_CONTRAST)
        self.assertLess(mark, text)
        self.assertGreaterEqual(info.contrast(info.mix(paper, ink, mark), paper), 3.0)
        self.assertLess(info.contrast(info.mix(paper, ink, mark - 0.01), paper), 3.0)
        self.assertEqual(info.shade(paper, ink, 0.0, ratio=info.GRAPHIC_CONTRAST), info.mix(paper, ink, mark))
        self.assertEqual(info.GRAPHIC_CONTRAST, 3.0)
        self.assertEqual(info.MIN_CONTRAST, 4.5)

    def test_every_shade_of_text_has_4_5_to_1_and_every_fill_3_to_1_in_any_style(self):
        for style in self.STYLES:
            paper, ink = style["paper"], style["ink"]
            self.assertGreaterEqual(info.contrast(ink, paper), 4.5, style)
            for share in (0.5, 0.7, 0.75):  # the lighter text there is
                self.assertGreaterEqual(info.contrast(info.shade(paper, ink, share), paper), 4.5, (style, share))
            for share in (info.TINT_OTHERS, 0.86, 0.5):  # the bars, columns and baseline
                self.assertGreaterEqual(info.contrast(info.shade(paper, ink, share, ratio=info.GRAPHIC_CONTRAST), paper), 3.0, (style, share))
            for count in (2, 3, 6, 8):
                fills = info.band_fills(style, count)
                self.assertEqual(len(fills), count)
                for fill in fills:
                    self.assertGreaterEqual(info.contrast(fill, paper), 3.0, (style, count, fill))

    def test_the_bands_keep_a_wide_ramp_not_one_grey(self):
        fills = info.band_fills(self.STYLES[0], 6)
        self.assertEqual(len(set(fills)), 6)  # six different fills
        self.assertEqual(fills[-1], info.mix("#FFFFFF", "#111111", info.TINT_HIGH))  # near-black at the top
        darkest_to_lightest = [info.contrast(f, "#FFFFFF") for f in fills]
        self.assertEqual(darkest_to_lightest, sorted(darkest_to_lightest))  # light at the bottom, dark at the top
        floor_for_text = info.mix("#FFFFFF", "#111111", info.readable_share("#FFFFFF", "#111111"))
        self.assertLess(info.contrast(fills[0], "#FFFFFF"), info.contrast(floor_for_text, "#FFFFFF"))  # lighter than text may be
        # a wider ramp than the text rule would leave: the neighbours differ more
        text_ramp = [info.mix("#FFFFFF", "#111111", info.tint_for(n, 6, info.readable_share("#FFFFFF", "#111111"))) for n in range(6)]
        self.assertGreater(info.contrast(fills[0], fills[1]), info.contrast(text_ramp[0], text_ramp[1]))

    def test_grey_ink_still_has_bands_you_can_tell_apart(self):
        fills = info.band_fills(self.STYLES[1], 6)  # #767676 on white
        self.assertGreater(len(set(fills)), 1)
        self.assertEqual(fills, sorted(fills, reverse=True))  # lightest first: the hex strings of grey fall as the grey darkens
        # when the ink has less than 3 to 1 on the paper there is no lighter tint that reads: every band is the ink
        self.assertEqual(set(info.band_fills({"ink": "#999999", "paper": "#FFFFFF", "accent": "#999999"}, 4)), {"#999999"})

    def test_the_accent_is_used_only_where_it_reads_on_the_paper(self):
        self.assertEqual(info.accent_on_paper(self.STYLES[0]), "#111111")
        self.assertEqual(info.accent_on_paper(self.STYLES[2]), "#B3261E")  # a dark red reads on cream
        self.assertEqual(info.accent_on_paper(self.STYLES[4]), "#111111")  # yellow on white doesn't: the ink
        self.assertEqual(info.accent_on_paper(self.STYLES[3]), "#FFE600")  # but yellow on a dark paper does
        self.assertEqual(info.accent_on_paper({"ink": "#111111", "paper": "#FFFFFF", "accent": "#D84315"}), "#D84315")  # 4.0 to 1: enough for a mark


class Marker(unittest.TestCase):
    """A scale marker's label stays on the chart, or the card is refused."""

    def chart(self, value, label="The example story's reading"):
        bands = [{"name": n, "from": a, "to": b} for n, a, b in (("Good", 0, 50), ("Satisfactory", 51, 100), ("Moderate", 101, 200),
                                                                 ("Poor", 201, 300), ("Very Poor", 301, 400), ("Severe", 401, 500))]
        return {"type": "scale", "bands": bands, "unit": None, "marker": {"value": value, "label": label}}

    def test_a_low_marker_puts_its_label_over_its_value_not_off_the_bottom(self):
        layout = info.scale_layout(self.chart(45, "Shillong's reading on a clear day"), 928, 742, measure, wrap)
        marker = layout["marker"]
        self.assertEqual(marker["label_at"]["vertical"], "bottom")  # above the value
        tall = len(marker["label_lines"]) * info.MARKER_LABEL * info.LINE
        top, bottom = marker["label_at"]["y"] - tall, marker["label_at"]["y"]
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(bottom, marker["value_y"] - info.MARKER_VALUE * 0.5)  # clear of the big value
        self.assertEqual(marker["value"], "45")

    def test_a_high_marker_keeps_its_label_under_the_value(self):
        marker = info.scale_layout(self.chart(450), 928, 742, measure, wrap)["marker"]
        self.assertEqual(marker["label_at"]["vertical"], "top")
        self.assertGreater(marker["label_at"]["y"], marker["value_y"] + info.MARKER_VALUE * 0.5)

    def test_at_every_value_the_label_is_inside_the_chart_and_clear_of_the_value(self):
        for height in (742, 594):
            for value in range(0, 501, 5):
                marker = info.scale_layout(self.chart(value, "A label long enough to wrap over two or three lines"), 928, height, measure, wrap)["marker"]
                tall = len(marker["label_lines"]) * info.MARKER_LABEL * info.LINE
                at = marker["label_at"]
                top, bottom = (at["y"], at["y"] + tall) if at["vertical"] == "top" else (at["y"] - tall, at["y"])
                self.assertTrue(0 <= top and bottom <= height, (height, value, top, bottom))
                value_top, value_bottom = marker["value_y"] - info.MARKER_VALUE * 0.5, marker["value_y"] + info.MARKER_VALUE * 0.5
                self.assertTrue(bottom <= value_top or top >= value_bottom, (height, value))
                self.assertTrue(all(measure(line, "text", info.MARKER_LABEL) <= marker["right"] for line in marker["label_lines"]))

    def test_a_label_that_fits_nowhere_is_refused_with_how_far_to_shorten(self):
        long = "word " * 40
        with self.assertRaises(info.TooLong) as caught:
            info.scale_layout(self.chart(250, long), 928, 742, measure, wrap)
        self.assertIn("shorten", str(caught.exception))
        with self.assertRaises(info.TooLong):  # not enough height above or below, even for two lines
            info.scale_layout(self.chart(250, "two lines of label words here for it"), 928, 240, measure, wrap)

    def test_a_marker_without_a_label_has_none_to_place(self):
        marker = info.scale_layout(self.chart(45, None), 928, 742, measure, wrap)["marker"]
        self.assertIsNone(marker["label_at"])
        self.assertEqual(marker["label_lines"], [])


class LineLabels(unittest.TestCase):
    """An end point's value goes beside it, any other labelled point above or below it: never across the line."""

    def items(self, values):
        return [{"label": "P%d" % n, "value": v, "text": None} for n, v in enumerate(values, start=1)]

    def box(self, layout, number):
        point, at = layout["points"][number], layout["points"][number]["label_at"]
        wide, tall = measure(point["value"], "text-bold", layout["value_size"]), layout["value_size"] * 1.25
        left = at["x"] - wide if at["align"] == "right" else (at["x"] - wide / 2 if at["align"] == "center" else at["x"])
        top = at["y"] - tall / 2 if at["vertical"] == "center" else (at["y"] - tall if at["vertical"] == "bottom" else at["y"])
        return (left, top, left + wide, top + tall)

    def check(self, values, marked=None, from_zero=True, height=594):
        items = self.items(values)
        try:
            layout = info.line_layout(items, "AQI", from_zero, 928, height, measure, wrap, marked)
        except info.TooLong:
            return None  # refusing is allowed; a label on the line is not
        path = [(p["x"], p["y"]) for p in layout["points"]]
        boxes = [self.box(layout, n) for n in layout["named"]]
        for number, box in zip(layout["named"], boxes):
            self.assertTrue(box[0] >= 0 and box[2] <= 928 and box[1] >= 0 and box[3] <= layout["base"], (values, number, box))
            for a, b in zip(path, path[1:]):
                self.assertFalse(info.segment_hits_box(a, b, box), (values, number, box, a, b))
        for n, first in enumerate(boxes):
            for second in boxes[n + 1:]:
                self.assertFalse(info.boxes_overlap(first, second), values)
        return layout

    def test_the_ends_are_labelled_beside_them_whichever_way_the_line_runs(self):
        for values in ([120, 455, 430, 380, 300], [300, 380, 430, 455, 120], [5, 5, 5], [455, 120], [120, 455], [1, 2, 3, 4, 5, 6, 7]):
            layout = self.check(values)
            self.assertIsNotNone(layout, values)
            first, last = layout["points"][0]["label_at"], layout["points"][-1]["label_at"]
            self.assertEqual((first["align"], first["vertical"]), ("right", "center"), values)
            self.assertEqual((last["align"], last["vertical"]), ("left", "center"), values)

    def test_a_peak_is_labelled_above_and_a_valley_below(self):
        layout = self.check([100, 200, 450, 200, 100], marked=["P3"])
        self.assertEqual(layout["points"][2]["label_at"]["vertical"], "bottom")  # above the peak
        layout = self.check([450, 300, 200, 300, 450], marked=["P3"])
        self.assertEqual(layout["points"][2]["label_at"]["vertical"], "top")  # below the valley
        layout = self.check([300, 380, 430, 455, 120], marked=["P2"])  # rising through the point: a corner, never across
        self.assertIn(layout["points"][1]["label_at"]["vertical"], ("bottom", "top"))

    def test_no_label_is_ever_on_the_line_over_many_shapes_of_data(self):
        rng = random.Random(2026)
        placed = tried = 0
        for _ in range(400):
            count = rng.randint(2, 24)
            values = [rng.choice([0, rng.randint(0, 500), rng.randint(0, 500), rng.randint(400, 500)]) for _ in range(count)]
            if max(values) == 0:
                continue
            marked = ["P%d" % n for n in rng.sample(range(1, count + 1), min(count, rng.randint(0, 3)))]
            layout = self.check(values, marked, height=rng.choice([594, 742]))
            tried += 1
            placed += layout is not None
            if not marked:
                self.assertIsNotNone(layout, values)  # the two ends can always be labelled beside them
        self.assertGreater(placed, tried * 0.7)  # even jagged data can mostly be labelled; the rest is refused, never drawn across

    def test_data_that_cannot_be_labelled_cleanly_is_refused(self):
        # a 24-point zigzag with six highlighted valleys: the line is everywhere a label could go
        self.assertIsNone(self.check([300, 0] * 12, marked=["P%d" % n for n in range(2, 14, 2)]))
        with self.assertRaises(info.TooLong) as caught:
            info.line_layout(self.items([300, 0] * 12), "AQI", True, 928, 594, measure, wrap, ["P%d" % n for n in range(2, 14, 2)])
        self.assertIn("highlight fewer points", str(caught.exception))

    def test_room_is_made_beside_the_ends_for_their_labels(self):
        layout = info.line_layout(self.items([1, 5]), "AQI", True, 928, 594, measure, wrap, None)
        first, last = layout["points"][0], layout["points"][-1]
        wide = measure("1 AQI", "text-bold", layout["value_size"])
        self.assertGreaterEqual(first["x"], wide + 14)
        self.assertLessEqual(last["x"], 928 - measure("5 AQI", "text-bold", layout["value_size"]) - 14)
        self.assertTrue(wide > 0)

    def test_segment_and_box_geometry(self):
        box = (10, 10, 20, 20)
        self.assertTrue(info.segment_hits_box((0, 15), (30, 15), box))  # straight through
        self.assertTrue(info.segment_hits_box((0, 0), (30, 30), box))  # across a corner to corner
        self.assertTrue(info.segment_hits_box((12, 12), (14, 14), box))  # wholly inside
        self.assertFalse(info.segment_hits_box((0, 0), (5, 5), box))  # stops short
        self.assertFalse(info.segment_hits_box((0, 25), (30, 25), box))  # passes below
        self.assertFalse(info.segment_hits_box((25, 0), (25, 30), box))  # passes beside
        self.assertTrue(info.segment_hits_box((0, 25), (30, 25), box, 6))  # clearance counts
        self.assertTrue(info.boxes_overlap((0, 0, 10, 10), (5, 5, 15, 15)))
        self.assertFalse(info.boxes_overlap((0, 0, 10, 10), (10, 0, 20, 10)))  # touching is not overlapping
        self.assertTrue(info.boxes_overlap((0, 0, 10, 10), (10, 0, 20, 10), 2))


class Header(unittest.TestCase):
    """The subtitle follows the title as drawn, and the body starts under the header (M3's last polish)."""

    H = 1350
    SIZE = (1080, 1350)
    # What the drawing module fits: one and two lines at 60 px (a line box is 1.25 of the size), three lines at 48 px.
    HEIGHTS = {1: 75, 2: 150, 3: 180}

    def line(self, size=60):
        return int(round(size * 1.25))  # hrizzup_draw.line_height

    def placed(self, name, title_lines, subtitle=True):
        return info.place_header(template(name), self.SIZE, self.HEIGHTS[title_lines], 40 if subtitle else 0)

    def slot(self, tmpl, name):
        return next(t for t in tmpl["texts"] if t["slot"] == name)["box"]

    def test_the_subtitle_sits_the_normal_gap_under_the_title_as_drawn_whatever_its_length(self):
        for name in ("chart-card", "steps-card"):
            for lines in (1, 2, 3):
                tmpl, _body = self.placed(name, lines)
                title_bottom = self.slot(template(name), "title")[1] * self.H + self.HEIGHTS[lines]
                top = self.slot(tmpl, "subtitle")[1] * self.H
                self.assertAlmostEqual(top - title_bottom, info.HEADER_GAP * self.H, places=6, msg=(name, lines))

    def test_a_one_line_title_no_longer_leaves_two_lines_of_room_before_the_subtitle(self):
        one, _ = self.placed("chart-card", 1)
        two, _ = self.placed("chart-card", 2)
        base = template("chart-card")
        gap_before = (self.slot(base, "subtitle")[1] - self.slot(base, "title")[1]) * self.H - self.line()  # the old gap under one line
        gap_now = (self.slot(one, "subtitle")[1] - self.slot(one, "title")[1]) * self.H - self.line()
        self.assertGreater(gap_before, 120)  # about 150 px, as seen
        self.assertLess(gap_now, 40)
        self.assertAlmostEqual((self.slot(two, "subtitle")[1] - self.slot(one, "subtitle")[1]) * self.H, self.line(), places=6)

    def test_the_subtitle_box_keeps_its_size_and_stays_on_the_card(self):
        base = template("chart-card")
        for lines in (1, 2, 3):
            tmpl, _ = self.placed("chart-card", lines)
            before, after = self.slot(base, "subtitle"), self.slot(tmpl, "subtitle")
            self.assertAlmostEqual(before[3] - before[1], after[3] - after[1], places=9)
            self.assertEqual((before[0], before[2]), (after[0], after[2]))
            drawn_bottom = after[1] * self.H + 40  # the subtitle as drawn (40 px here) ends above the chart place
            self.assertLess(drawn_bottom, tmpl["picture"]["box"][1] * self.H)
            self.assertGreater(after[1], self.slot(tmpl, "title")[1])

    def test_the_chart_place_starts_under_the_header_and_is_taller_when_the_header_is_short(self):
        base_top = template("chart-card")["picture"]["box"][1]
        tops = []
        for lines in (1, 2, 3):
            tmpl, body = self.placed("chart-card", lines)
            top = tmpl["picture"]["box"][1]
            self.assertEqual(top, body if body < base_top else base_top)
            self.assertLessEqual(top, base_top)  # never a shorter chart place than the template's
            tops.append(top)
        self.assertEqual(tops, sorted(tops))  # a longer title pushes the chart down
        self.assertLess(tops[0], base_top)  # and a one-line title gives the chart room
        self.assertEqual(template("chart-card")["picture"]["box"][3], placed_bottom(self.placed("chart-card", 1)[0]))  # its foot is where it was

    def test_without_a_subtitle_the_body_follows_the_title(self):
        with_sub = self.placed("chart-card", 1)[1]
        without = self.placed("chart-card", 1, subtitle=False)[1]
        self.assertLess(without, with_sub)
        self.assertAlmostEqual(without, (0.05 * self.H + self.line() + info.BODY_GAP * self.H) / self.H, places=9)

    def test_the_steps_rows_start_under_the_header_and_the_group_is_centred(self):
        base = template("steps-card")
        for lines in (1, 2, 3):
            tmpl, body = self.placed("steps-card", lines)
            for count in (2, 3, 5):
                spread, rules = info.spread_steps(tmpl, count, body)
                slots = {t["slot"]: t["box"] for t in spread["texts"]}
                first, last = slots["step1"][1], slots["step%d" % count][3]
                self.assertGreaterEqual(first, body - 1e-9, (lines, count))  # under the header
                self.assertLessEqual(last, template("steps-card")["texts"][-3]["box"][3] + 1e-9)  # and above the source
                for row in range(1, count):
                    self.assertLessEqual(slots["step%d" % row][3], slots["step%d" % (row + 1)][1] + 1e-9)
                    self.assertTrue(slots["step%d" % row][3] <= rules[row - 1] <= slots["step%d" % (row + 1)][1] + 1e-9)
                # centred: the spare room above the first row and below the last (with the gap under it) is the same
                top = min(body, self.slot(base, "n1")[1])
                gap = self.slot(base, "n2")[1] - self.slot(base, "n1")[3]
                span = self.slot(base, "n5")[3] - top + gap
                pitch = slots["step2"][1] - slots["step1"][1] if count > 1 else 0
                above, below = first - top, top + span - (first + count * pitch)
                self.assertGreaterEqual(above, -1e-9)
                self.assertAlmostEqual(above, below, places=9, msg=(lines, count))

    def test_two_steps_are_not_left_at_the_top_of_their_space(self):
        tmpl, body = self.placed("steps-card", 2)
        spread, _rules = info.spread_steps(tmpl, 2, body)
        top = next(t for t in spread["texts"] if t["slot"] == "step1")["box"][1]
        self.assertGreater(top, body + 0.02)  # moved down to the middle of the space

    def test_the_stat_block_moves_up_by_half_the_room_the_title_did_not_use(self):
        base = template("stat-card")
        title_bottom = self.slot(base, "title")[3]
        full, _ = info.place_header(base, self.SIZE, (title_bottom - self.slot(base, "title")[1]) * self.H, 0)  # a title that fills its box
        self.assertEqual(self.slot(full, "value"), self.slot(base, "value"))  # nothing to give back
        one, _ = info.place_header(base, self.SIZE, self.line(52), 0)
        moved = (self.slot(base, "value")[1] - self.slot(one, "value")[1]) * self.H
        unused = (title_bottom * self.H - (self.slot(base, "title")[1] * self.H + self.line(52))) / 2
        self.assertAlmostEqual(moved, unused, places=6)
        for name in ("value", "label", "note"):
            a, b = self.slot(base, name), self.slot(one, name)
            self.assertAlmostEqual((a[1] - b[1]), (a[3] - b[3]), places=9)  # each keeps its size
        self.assertGreater(self.slot(one, "value")[1], self.slot(one, "title")[1] + self.line(52) / self.H)  # still under the title
        self.assertLess(self.slot(one, "note")[3], self.slot(one, "source")[1])  # and over the source

    def test_the_template_is_left_alone(self):
        base = template("chart-card")
        before = copy.deepcopy(base)
        info.place_header(base, self.SIZE, 75, 38)
        self.assertEqual(base, before)


def placed_bottom(tmpl):
    return tmpl["picture"]["box"][3]


class Spread(unittest.TestCase):
    """Bars and columns spread to fill their place; when their spacing is capped the group is centred."""

    def bars(self, count, height=742, width=928):
        items = [{"label": "City %d" % n, "value": 100 - n, "text": None} for n in range(count)]
        return info.bar_layout(items, "AQI", width, height, measure, wrap)

    def columns(self, count, height=594, width=928):
        items = [{"label": "C%d" % n, "value": 100 - n, "text": None} for n in range(count)]
        return info.column_layout(items, "AQI", width, height, measure, wrap)

    def test_2_4_and_12_bars_fill_their_place_or_are_centred_in_it(self):
        for height in (742, 594, 877):
            for count in (2, 4, 12):
                layout = self.bars(count, height)
                rows = layout["rows"]
                top_margin, bottom_margin = layout["top"], height - layout["bottom"]
                self.assertAlmostEqual(top_margin, bottom_margin, places=6, msg=(count, height))  # always centred
                self.assertLessEqual(layout["pitch"], info.BAR_PITCH_MAX)
                self.assertAlmostEqual(layout["pitch"], min(height / count, info.BAR_PITCH_MAX), places=6)
                self.assertTrue(all(r["y1"] - r["y0"] <= info.BAR_THICK_MAX + 1e-9 for r in rows))
                self.assertAlmostEqual(rows[1]["centre"] - rows[0]["centre"], layout["pitch"], places=6)
                for a, b in zip(rows, rows[1:]):
                    self.assertLess(a["y1"], b["y0"])
                self.assertTrue(rows[0]["y0"] >= 0 and rows[-1]["y1"] <= height)

    def test_twelve_bars_fill_the_whole_place_and_four_fill_most_of_it(self):
        twelve = self.bars(12)
        self.assertAlmostEqual(twelve["top"], 0, places=6)
        self.assertAlmostEqual(twelve["bottom"], 742, places=6)
        four = self.bars(4)
        self.assertGreater((four["bottom"] - four["top"]) / 742, 0.85)  # not the top half of the place, as before
        self.assertGreater(four["top"], 0)  # centred: some room both above and below
        two = self.bars(2)
        self.assertEqual(two["pitch"], info.BAR_PITCH_MAX)  # capped: the pair is centred, not stretched
        self.assertAlmostEqual(two["top"], (742 - 2 * info.BAR_PITCH_MAX) / 2, places=6)

    def test_a_thick_bar_is_capped_and_a_thin_one_is_in_proportion_to_its_row(self):
        two, twelve = self.bars(2), self.bars(12)
        self.assertEqual(two["rows"][0]["y1"] - two["rows"][0]["y0"], info.BAR_THICK_MAX)
        self.assertAlmostEqual(twelve["rows"][0]["y1"] - twelve["rows"][0]["y0"], twelve["pitch"] * 0.62, places=6)

    def test_the_bars_zero_line_spans_the_group(self):
        layout = self.bars(4)
        self.assertEqual((layout["top"], layout["bottom"]), (layout["rows"][0]["centre"] - layout["pitch"] / 2, layout["rows"][-1]["centre"] + layout["pitch"] / 2))

    def test_2_4_and_8_columns_spread_across_their_place_or_are_centred_in_it(self):
        for width in (928, 800):
            for count in (2, 4, 8):
                layout = self.columns(count, width=width)
                cols = layout["cols"]
                self.assertAlmostEqual(layout["left"], width - layout["right"], places=6, msg=(count, width))  # centred
                self.assertLessEqual(layout["slot"], info.COLUMN_SLOT_MAX)
                self.assertAlmostEqual(layout["slot"], min(width / count, info.COLUMN_SLOT_MAX), places=6)
                self.assertTrue(all(c["x1"] - c["x0"] <= info.COLUMN_WIDTH_MAX + 1e-9 for c in cols))
                self.assertTrue(cols[0]["x0"] >= layout["left"] and cols[-1]["x1"] <= layout["right"])
                for a, b in zip(cols, cols[1:]):
                    self.assertLess(a["x1"], b["x0"])
        eight = self.columns(8)
        self.assertAlmostEqual(eight["left"], 0, places=6)  # eight fill the width
        self.assertAlmostEqual(eight["right"], 928, places=6)
        two = self.columns(2)
        self.assertEqual(two["slot"], info.COLUMN_SLOT_MAX)  # two are a pair in the middle, not far apart
        self.assertGreater(two["left"], 200)


class Templates(unittest.TestCase):
    def test_each_template_follows_the_design_and_is_on_disk(self):
        folder = os.path.join(KIT, "assets", "templates")
        self.assertEqual(sorted(f[:-5] for f in os.listdir(folder)), sorted(info.TEMPLATE_IDS))
        for name in info.TEMPLATE_IDS:
            self.assertEqual(catalogue.template_problems(name, template(name)), [], name)
            self.assertEqual([tuple(s) for s in template(name)["sizes"]], list(info.SIZES), name)

    def test_each_has_the_slots_the_script_fills(self):
        common = {"title", "source"}
        slots = {name: {t["slot"] for t in template(name)["texts"]} for name in info.TEMPLATE_IDS}
        self.assertLessEqual(common | {"subtitle"}, slots["chart-card"])
        self.assertLessEqual(common | {"value", "label", "note"}, slots["stat-card"])
        self.assertLessEqual(common | {"subtitle"} | {"n%d" % n for n in range(1, 6)} | {"step%d" % n for n in range(1, 6)}, slots["steps-card"])
        self.assertIsNotNone(template("chart-card")["picture"])  # the chart's place
        self.assertEqual(template("stat-card")["background"], "accent")

    def test_text_never_reaches_the_signature(self):
        for name in info.TEMPLATE_IDS:
            top = template(name)["signature"]["box"][1]
            for text in template(name)["texts"]:
                self.assertLessEqual(text["box"][3], top, (name, text["slot"]))


def fake_matplotlib():
    """Stand-ins for the modules `Chart` and `draw_chart` import, recording what they are asked."""
    parts = {}
    matplotlib = types.ModuleType("matplotlib")
    matplotlib.rcParamsDefault = {"text.usetex": False, "marker": "default"}
    events = []

    class Context:
        def __init__(self, rc=None):
            events.append(("rc_context", rc))

        def __enter__(self):
            events.append(("enter",))

        def __exit__(self, *args):
            events.append(("exit",))

    matplotlib.rc_context = Context
    style = types.ModuleType("matplotlib.style")
    style.use = lambda path: events.append(("style.use", path))
    matplotlib.style = style
    font_manager = types.ModuleType("matplotlib.font_manager")
    font_manager.FontProperties = mock.Mock(return_value="font")
    font_manager.fontManager = mock.Mock()
    matplotlib.font_manager = font_manager
    agg = types.ModuleType("matplotlib.backends.backend_agg")
    agg.FigureCanvasAgg = mock.Mock()
    figure = types.ModuleType("matplotlib.figure")
    figure.Figure = mock.Mock()
    parts.update({"matplotlib": matplotlib, "matplotlib.style": style, "matplotlib.font_manager": font_manager,
                  "matplotlib.backends": types.ModuleType("matplotlib.backends"), "matplotlib.backends.backend_agg": agg,
                  "matplotlib.figure": figure})
    return parts, events


def fake_draw():
    module = mock.Mock()
    module.font_path.return_value = "font.ttf"

    class DrawError(Exception):
        def __init__(self, message, code=2):
            super().__init__(message)
            self.code = code

    module.DrawError = DrawError
    return module


class DrawingCalls(unittest.TestCase):
    """What the chart asks matplotlib to do, with matplotlib stood in for (so these run in the offline check)."""

    STYLE = {"ink": "#111111", "paper": "#FFFFFF", "accent": "#111111", "display_font": "anton", "text_font": "atkinson-hyperlegible", "signature": ""}

    def test_every_string_is_text_not_maths_and_not_tex(self):
        parts, _events = fake_matplotlib()
        with mock.patch.dict(sys.modules, parts):
            chart = info.Chart(fake_draw(), self.STYLE, 928, 742)
            for text in ("From $5 to $7", "Cost $\\frac{ and $x", "$$", "plain"):
                chart.text(10, 10, text, "text", 20, "#111111")
        calls = chart.axes.text.call_args_list
        self.assertEqual(len(calls), 4)
        for call in calls:
            self.assertIs(call.kwargs["parse_math"], False)
            self.assertIs(call.kwargs["usetex"], False)
        self.assertEqual([c.args[2] for c in calls][:2], ["From $5 to $7", "Cost $\\frac{ and $x"])  # the string itself, untouched

    def test_the_chart_is_drawn_inside_matplotlibs_defaults_plus_the_kits_style(self):
        parts, events = fake_matplotlib()
        drawn = []
        spec = {"type": "bar", "data": [{"label": "a", "value": 1, "text": None}], "unit": None, "highlight": None, "from_zero": True}
        with mock.patch.dict(sys.modules, parts), mock.patch.object(info, "Chart") as chart_class, \
                mock.patch.dict(info.DRAWERS, {"bar": lambda *args: drawn.append(list(events))}):
            info.draw_chart(spec, self.STYLE, fake_draw(), 928, 742)
        matplotlib = parts["matplotlib"]
        self.assertEqual(events[0], ("rc_context", matplotlib.rcParamsDefault))  # not the creator's matplotlibrc
        self.assertEqual(events[1], ("enter",))
        self.assertEqual(events[2], ("style.use", str(info.STYLE_FILE)))
        self.assertTrue(str(info.STYLE_FILE).endswith(os.path.join("assets", "hrizzup.mplstyle")))
        self.assertTrue(info.STYLE_FILE.is_file())
        self.assertEqual(len(drawn), 1)
        self.assertEqual([e[0] for e in drawn[0]], ["rc_context", "enter", "style.use"])  # the drawing is inside it
        self.assertEqual(events[-1], ("exit",))
        chart_class.assert_called_once()

    def test_a_missing_kit_style_is_exit_3_naming_the_fix(self):
        parts, _events = fake_matplotlib()
        draw_module = fake_draw()
        with mock.patch.dict(sys.modules, parts), mock.patch.object(info, "STYLE_FILE", info.KIT / "assets" / "none.mplstyle"):
            with self.assertRaises(draw_module.DrawError) as caught:
                info.draw_chart({"type": "bar", "data": [], "unit": None}, self.STYLE, draw_module, 10, 10)
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("get the kit again", str(caught.exception))


def have(*names):
    try:
        for name in names:
            __import__(name)
        return True
    except ImportError:
        return False


def own_draw():
    """This kit's own copy of hrizzup_draw (each skill's copy looks for fonts beside itself), or None if Pillow is missing."""
    try:
        import importlib.util as util
        found = util.spec_from_file_location("hrizzup_draw_infographic", os.path.join(SCRIPTS, "hrizzup_draw.py"))
        module = util.module_from_spec(found)
        found.loader.exec_module(module)
        return module
    except ImportError:
        return None


@unittest.skipUnless(have("PIL", "fontTools", "matplotlib", "numpy"), "needs Pillow, fontTools, matplotlib and numpy")
class RealDrawing(unittest.TestCase):
    """The chart drawn for real, where the packages are installed (`uv run --with ...`, or the kit's own environment)."""

    def spec(self, label):
        return info.validate_spec({"template": "chart-card", "title": "T", "source": "S", "chart": {
            "type": "bar", "data": [{"label": label, "value": 7}, {"label": "Other", "value": 3}], "unit": "USD"}})["chart"]

    def draw(self, label):
        module = own_draw()
        return info.draw_chart(self.spec(label), module.load_style(None), module, 928, 742)

    def test_dollar_signs_are_not_maths(self):
        import matplotlib
        seen = []
        original = info.Chart.text
        info.Chart.text = lambda self, x, y, text, *rest, **kw: (seen.append(text), original(self, x, y, text, *rest, **kw))[1]
        try:
            picture = self.draw("From $5 to $7")
        finally:
            info.Chart.text = original
        self.assertEqual(picture.size, (928, 742))
        self.assertIn("From $5 to $7", seen)
        self.assertIsNotNone(matplotlib)

    def test_a_string_that_would_break_the_maths_reader_is_drawn_as_it_is(self):
        for label in ("Cost $\\frac{ and $x", "$", "$$", "a $b$ c \\"):
            self.assertEqual(self.draw(label).size, (928, 742), label)

    def test_the_text_objects_have_maths_and_tex_off(self):
        module = own_draw()
        chart = info.Chart(module, module.load_style(None), 200, 100)
        chart.text(5, 5, "$5 to $7", "text", 20, "#111111")
        item = chart.axes.texts[0]
        self.assertFalse(item.get_parse_math())
        self.assertFalse(item.get_usetex())
        self.assertEqual(item.get_text(), "$5 to $7")

    def test_a_creators_matplotlibrc_cannot_turn_tex_on(self):
        import matplotlib
        saved = matplotlib.rcParams["text.usetex"]
        matplotlib.rcParams["text.usetex"] = True  # what a matplotlibrc with text.usetex: True does
        try:
            self.assertEqual(self.draw("Delhi").size, (928, 742))  # without the fix this needs a TeX installation
            self.assertTrue(matplotlib.rcParams["text.usetex"])  # and the creator's own settings are left as they were
        finally:
            matplotlib.rcParams["text.usetex"] = saved

    def test_the_marker_label_of_a_low_band_is_drawn_inside_the_picture(self):
        module = own_draw()
        chart = info.validate_spec(dict(example_spec(), chart=dict(example_spec()["chart"], marker={"value": 45, "label": "Shillong's reading on a clear day"})))["chart"]
        picture = info.draw_chart(chart, module.load_style(None), module, 928, 742)
        bottom_left = picture.crop((0, 742 - 20, 280, 742)).getextrema()  # the foot of the callout's column: empty paper
        self.assertEqual(bottom_left, ((255, 255), (255, 255), (255, 255)))


@unittest.skipUnless(have("PIL", "fontTools"), "needs Pillow and fontTools")
class Pictures(unittest.TestCase):
    """Your own chart as a picture: its transparency goes over the paper, and one that is too big is refused."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="infographic-test-")
        self.addCleanup(__import__("shutil").rmtree, self.folder, True)

    def centre(self):
        """The middle of the chart's place on a card whose title is one short line and which has no subtitle."""
        placed, _body = info.place_header(template("chart-card"), (1080, 1350), 75, 0)
        box = placed["picture"]["box"]
        return int((box[1] + box[3]) / 2 * 1350)

    def run_with_image(self, image, name="own.png", style=None, **options):
        spec = {"template": "chart-card", "title": "T", "source": "S", "image": name}
        with open(os.path.join(self.folder, "spec.json"), "w", encoding="utf-8") as f:
            json.dump(spec, f)
        image.save(os.path.join(self.folder, name), **options)
        argv = ["--spec", os.path.join(self.folder, "spec.json"), "--out", os.path.join(self.folder, "card.png")]
        if style:
            with open(os.path.join(self.folder, "style.json"), "w", encoding="utf-8") as f:
                json.dump(style, f)
            argv += ["--style", os.path.join(self.folder, "style.json")]
        with mock.patch.dict(sys.modules, {"hrizzup_draw": own_draw()}):
            return run_main(argv)

    def test_transparency_goes_over_the_papers_colour(self):
        from PIL import Image
        code, report = self.run_with_image(Image.new("RGBA", (200, 100), (255, 0, 0, 0)), style={"paper": "#EEDDCC"})
        self.assertEqual(code, 0, report)
        card = Image.open(os.path.join(self.folder, "card.png")).convert("RGB")
        self.assertEqual(card.getpixel((540, self.centre())), (0xEE, 0xDD, 0xCC))  # the middle of the chart's place: paper, not black or white

    def test_a_16_bit_grey_picture_is_scaled_not_clipped(self):
        from PIL import Image
        grey = Image.new("I;16", (200, 100))
        grey.putdata([32768] * 200 * 100)
        code, report = self.run_with_image(grey)
        self.assertEqual(code, 0, report)
        card = Image.open(os.path.join(self.folder, "card.png")).convert("RGB")
        self.assertEqual(card.getpixel((540, self.centre())), (128, 128, 128))  # half grey, not white

    def test_a_picture_that_is_not_a_png_jpeg_or_webp_exits_2(self):
        from PIL import Image
        code, report = self.run_with_image(Image.new("F", (20, 20)), name="own.tif")  # a floating-point TIFF
        self.assertEqual(code, 2)
        self.assertIn("use a PNG, JPEG or WebP", report["problem"])

    def test_a_huge_picture_exits_2_before_it_is_decoded(self):
        from PIL import Image
        with mock.patch("PIL.PngImagePlugin.PngImageFile.load", side_effect=AssertionError("decoded the pixels")):
            code, report = self.run_with_image(Image.new("1", (8190, 8190)))
        self.assertEqual(code, 2)
        self.assertIn("megapixels", report["problem"])

    def test_the_card_never_overwrites_its_picture_however_it_is_linked(self):
        from PIL import Image
        spec = {"template": "chart-card", "title": "T", "source": "S", "image": "own.png"}
        with open(os.path.join(self.folder, "spec.json"), "w", encoding="utf-8") as f:
            json.dump(spec, f)
        picture = os.path.join(self.folder, "own.png")
        Image.new("RGB", (50, 50), (1, 2, 3)).save(picture)
        before = open(picture, "rb").read()
        for make_link in (os.symlink, os.link):
            link = os.path.join(self.folder, "out-%s.png" % make_link.__name__)
            try:
                make_link(picture, link)
            except (OSError, NotImplementedError):
                continue
            with mock.patch.dict(sys.modules, {"hrizzup_draw": own_draw()}):
                code, report = run_main(["--spec", os.path.join(self.folder, "spec.json"), "--out", link])
            self.assertEqual((code, "overwrite" in report["problem"]), (2, True), make_link.__name__)
        self.assertEqual(open(picture, "rb").read(), before)


@unittest.skipUnless(have("PIL", "fontTools", "matplotlib", "numpy"), "needs Pillow, fontTools, matplotlib and numpy")
class Looks(unittest.TestCase):
    """What a short chart looks like when drawn: a composed card, not a small chart at the top of a big gap."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="infographic-look-")
        self.addCleanup(__import__("shutil").rmtree, self.folder, True)
        # matplotlib is imported here, not inside the patch below: mock.patch.dict forgets every module imported
        # while it is active, and a package half forgotten and imported again is two packages
        import matplotlib.backends.backend_agg, matplotlib.figure, matplotlib.font_manager, matplotlib.patches, matplotlib.style  # noqa: E401,F401

    def card(self, spec, size="1080x1350"):
        from PIL import Image
        path = os.path.join(self.folder, "spec.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(spec, f)
        out = os.path.join(self.folder, "card.png")
        with mock.patch.dict(sys.modules, {"hrizzup_draw": own_draw()}):
            code, report = run_main(["--spec", path, "--size", size, "--out", out])
        self.assertEqual(code, 0, report)
        return Image.open(out).convert("L")

    def runs(self, image, x0, x1, y0, y1, merge=36):
        """The vertical runs of dark rows between y0 and y1 (rows with a pixel under 140 in x0..x1), nearby ones joined."""
        pixels = image.load()
        dark = [y for y in range(y0, y1) if any(pixels[x, y] < 140 for x in range(x0, x1, 2))]
        runs = []
        for y in dark:
            if runs and y - runs[-1][1] <= merge:
                runs[-1][1] = y
            else:
                runs.append([y, y])
        return runs

    def bars(self, count, title="Readings at 9 am on Monday"):
        return {"template": "chart-card", "title": title, "subtitle": "Air Quality Index", "source": "Illustrative figures",
                "chart": {"type": "bar", "unit": "AQI", "data": [{"label": "City %d" % n, "value": 470 - 7 * n} for n in range(count)]}}

    def test_the_subtitle_follows_a_one_line_title_closely(self):
        runs = self.runs(self.card(self.bars(4)), 76, 1004, 40, 330)
        self.assertEqual(len(runs), 2, runs)  # the title and the subtitle, nothing else up there
        self.assertLess(runs[1][0] - runs[0][1], 80)  # about 40 px; it was about 150

    def test_and_a_two_line_title_too(self):
        runs = self.runs(self.card(self.bars(4, "Readings across Delhi NCR at nine in the morning on Monday 2 November")), 76, 1004, 40, 330)
        self.assertEqual(len(runs), 2, runs)
        self.assertLess(runs[1][0] - runs[0][1], 80)

    def test_four_bars_fill_most_of_their_place_and_the_chart_is_not_left_blank_above_the_source(self):
        card = self.card(self.bars(4))
        axis = self.runs(card, 400, 430, 250, 1140, merge=5)  # the zero line is the long dark run at the bars' left edge
        top, bottom = axis[0][0], axis[-1][1]
        self.assertGreater(bottom - top, 600)  # four bars of 168 px; before, 448
        self.assertLess(1154 - bottom, 170)  # the blank band above the source line: about 300 before

    def test_two_and_twelve_bars_are_composed_too(self):
        two = self.runs(self.card(self.bars(2)), 400, 430, 250, 1140, merge=5)
        top, bottom = two[0][0], two[-1][1]
        self.assertAlmostEqual(bottom - top, 2 * info.BAR_PITCH_MAX, delta=30)  # the pair is not stretched
        twelve = self.runs(self.card(self.bars(12)), 400, 430, 250, 1140, merge=5)
        self.assertGreater(twelve[-1][1] - twelve[0][0], 780)  # twelve fill the place


class Command(unittest.TestCase):
    def write(self, folder, data, name="spec.json"):
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))
        return path

    def test_bad_input_exits_2_with_the_json_line_and_before_anything_is_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "i.png")
            code, report = run_main(["--spec", os.path.join(folder, "none.json"), "--out", out])
            self.assertEqual(code, 2)
            self.assertEqual(set(report), {"ok", "outputs", "checks", "problem"})
            self.assertFalse(report["ok"])
            code, report = run_main(["--spec", self.write(folder, "{not json"), "--out", out])
            self.assertEqual(code, 2)
            self.assertIn("valid JSON", report["problem"])
            code, report = run_main(["--spec", self.write(folder, refused(BARS, source=None)), "--out", out])
            self.assertEqual(code, 2)
            self.assertIn("source", report["problem"])
            code, report = run_main(["--spec", self.write(folder, BARS), "--out", out, "--size", "100x100"])
            self.assertEqual(code, 2)

    def test_the_output_folder_and_name_are_checked_and_an_input_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write(folder, BARS)
            code, report = run_main(["--spec", path, "--out", os.path.join(folder, "none", "i.png")])
            self.assertEqual((code, "folder" in report["problem"]), (2, True))
            self.assertEqual(run_main(["--spec", path, "--out", os.path.join(folder, "i.gif")])[0], 2)
            code, report = run_main(["--spec", path, "--out", path])
            self.assertEqual((code, "overwrite" in report["problem"]), (2, True))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), BARS)

    def test_a_wrong_command_line_is_bad_input_with_the_json_line_not_argparses_own_exit(self):
        for argv in (["--out", "i.png"], ["--bogus"], ["--spec", "s.json"], ["--spec", "s.json", "--out"], ["--spec", "s.json", "--out", "i.png", "--size"]):
            code, report = run_main(argv)
            self.assertEqual(code, 2, argv)
            self.assertFalse(report["ok"])
            self.assertTrue(report["problem"])
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as caught:
            info.main(["--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_a_link_to_an_input_is_the_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write(folder, BARS)
            style = self.write(folder, {"ink": "#111111"}, "style.json")
            for make_link in (os.symlink, os.link):
                for target, flag in ((path, "--spec"), (style, "--style")):
                    link = os.path.join(folder, "i-%s-%s.png" % (make_link.__name__, flag[2:]))
                    try:
                        make_link(target, link)
                    except (OSError, NotImplementedError):
                        continue
                    code, report = run_main(["--spec", path, "--style", style, "--out", link])
                    self.assertEqual((code, "overwrite" in report["problem"]), (2, True), (make_link.__name__, flag))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), BARS)

    def test_whatever_goes_wrong_the_last_line_is_the_json_line(self):
        fake = fake_draw()
        with tempfile.TemporaryDirectory() as folder:
            steps = {"template": "steps-card", "title": "T", "source": "S", "steps": ["a", "b"]}
            argv = ["--spec", self.write(folder, steps), "--out", os.path.join(folder, "i.png")]
            for error, code in ((RuntimeError("boom"), 1), (KeyError("slot"), 1), (ImportError("No module named matplotlib"), 3)):
                fake.load_style = mock.Mock(side_effect=error)
                with mock.patch.dict(sys.modules, {"hrizzup_draw": fake}):
                    got, report = run_main(argv)
                self.assertEqual(got, code, error)
                self.assertFalse(report["ok"])
                self.assertEqual(set(report), {"ok", "outputs", "checks", "problem"})
                self.assertTrue(report["problem"])

    def test_a_stat_card_with_a_subtitle_exits_2_before_anything_is_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            stat = {"template": "stat-card", "title": "T", "subtitle": "dropped", "source": "S", "chart": {"type": "stat", "value": "450+", "label": "l"}}
            code, report = run_main(["--spec", self.write(folder, stat), "--out", os.path.join(folder, "i.png")])
            self.assertEqual(code, 2)
            self.assertIn("a stat-card has no subtitle: put it in the note", report["problem"])

    def test_help_ends_with_an_example_that_names_the_command(self):
        tail = "\n".join(info.make_parser().format_help().strip().split("\n")[-6:]).lower()
        self.assertIn("example", tail)
        self.assertIn("infographic.py", tail)


class Words(unittest.TestCase):
    """What the skill's own words promise matches what the command does (M3's review)."""

    def read(self, *parts):
        with open(os.path.join(ROOT, "skills", "infographic", *parts), encoding="utf-8") as f:
            return f.read()

    def test_the_skill_and_its_guide_say_the_fonts_draw_english_letters_only(self):
        for text in (self.read("SKILL.md"), self.read("references", "infographic-guide.md")):
            self.assertIn("English (Latin) letters", text)
            self.assertIn("Hindi", text)
            self.assertIn("refused for now", text)

    def test_the_skill_file_says_which_specs_take_a_subtitle(self):
        text = self.read("SKILL.md")
        self.assertIn("A `chart-card` and a `steps-card` may have a `\"subtitle\"`; a `stat-card` has none", text)


if __name__ == "__main__":
    unittest.main()
