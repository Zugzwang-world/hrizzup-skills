"""infographic.py's reading of its spec and its layout maths: everything that needs no picture and no matplotlib.

The drawing itself needs Pillow and matplotlib, which the repository's check doesn't install; it is proved by the
sample (skills/infographic/examples/infographic.png), made by the command and described in its README.
"""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import unittest

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

    def test_numbers_as_text(self):
        self.assertEqual([info.fmt_number(v) for v in (450, 450.0, 12.5, 0.1 + 0.2, 1e3, 7.005)], ["450", "450", "12.5", "0.3", "1000", "7"])
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
        self.assertTrue(layout["points"][0]["below"])  # the line rises away from the first point: its label goes below
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

    def test_help_ends_with_an_example_that_names_the_command(self):
        tail = "\n".join(info.make_parser().format_help().strip().split("\n")[-6:]).lower()
        self.assertIn("example", tail)
        self.assertIn("infographic.py", tail)


if __name__ == "__main__":
    unittest.main()
