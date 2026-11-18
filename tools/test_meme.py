"""meme.py's reading of its command line and its templates: everything that needs no picture.

The drawing itself needs Pillow, which the repository's check doesn't install; it is proved by the sample meme
(skills/meme/examples/meme.png), made by the command and described in its README.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPTS = os.path.join(ROOT, "skills", "meme", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import importlib.util  # noqa: E402

import catalogue  # noqa: E402

spec = importlib.util.spec_from_file_location("meme_under_test", os.path.join(SCRIPTS, "meme.py"))
meme = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meme)

TEMPLATES = os.path.join(ROOT, "skills", "meme", "assets", "templates")


def load(name):
    with open(os.path.join(TEMPLATES, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = meme.main(argv)
    return code, json.loads(out.getvalue().strip().split("\n")[-1])


class Reading(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(meme.parse_size("1080x1350"), (1080, 1350))
        self.assertEqual(meme.parse_size(" 1080X1080 "), (1080, 1080))
        for bad in ("1920x1080", "1080", "1080x", "big", "1080x1350x2", "0x0", "-1080x1080"):
            with self.assertRaises(meme.InputError, msg=bad):
                meme.parse_size(bad)

    def test_focus(self):
        self.assertEqual(meme.parse_focus("0.5,0.35"), (0.5, 0.35))
        self.assertEqual(meme.parse_focus("0,1"), (0.0, 1.0))
        for bad in ("0.5", "a,b", "1.5,0.5", "-0.1,0.5", "0.5,0.5,0.5", "", "nan,0.5"):
            with self.assertRaises(meme.InputError, msg=bad):
                meme.parse_focus(bad)

    def test_a_text_is_one_clean_line(self):
        self.assertEqual(meme.clean_text("  Monday's   update \n then a line  ", "--text"), "Monday's update then a line")
        for bad in ("", "   ", "a\x07b", "x" * (meme.MAX_TEXT + 1), "\x00"):
            with self.assertRaises(meme.InputError, msg=repr(bad)):
                meme.clean_text(bad, "--text")
        self.assertEqual(len(meme.clean_text("x" * meme.MAX_TEXT, "--text")), meme.MAX_TEXT)

    def test_each_template_takes_the_texts_it_has(self):
        for template in meme.TEMPLATE_IDS:
            slots = [t["slot"] for t in load(template)["texts"]]
            self.assertEqual(meme.texts_for(template, "one", "two" if "text2" in slots else None, slots)["text"], "one")
        with self.assertRaises(meme.InputError):
            meme.texts_for("caption-bar", "one", "two", ["text"])  # a bar has one text
        for template in meme.NEEDS_TEXT2:
            with self.assertRaises(meme.InputError):
                meme.texts_for(template, "one", None, ["text", "text2"])
        self.assertEqual(meme.texts_for("top-bottom", "one", None, ["text", "text2"]), {"text": "one"})  # the bottom is optional


class Templates(unittest.TestCase):
    def test_every_template_follows_the_design(self):
        for name in meme.TEMPLATE_IDS:
            self.assertEqual(catalogue.template_problems(name, load(name)), [], name)

    def test_the_four_templates_are_the_ones_on_disk(self):
        self.assertEqual(sorted(f[:-5] for f in os.listdir(TEMPLATES)), sorted(meme.TEMPLATE_IDS))

    def test_each_offers_the_meme_sizes_and_the_slots_the_script_fills(self):
        for name in meme.TEMPLATE_IDS:
            template = load(name)
            self.assertEqual([tuple(s) for s in template["sizes"]], list(meme.SIZES), name)
            slots = {t["slot"] for t in template["texts"]}
            self.assertLessEqual(slots, {"text", "text2"}, name)
            self.assertIn("text", slots, name)
            self.assertEqual("text2" in slots, name != "caption-bar", name)

    def test_the_label_template_needs_a_picture_and_the_rest_do_not(self):
        required = {name: load(name)["picture"]["required"] for name in meme.TEMPLATE_IDS}
        self.assertEqual(required, {"caption-bar": False, "top-bottom": False, "two-panel": False, "label": True})

    def test_text_over_the_picture_never_reaches_the_signature_strip(self):
        for name in meme.TEMPLATE_IDS:
            template = load(name)
            top = template["signature"]["box"][1]
            for text in template["texts"]:
                self.assertLessEqual(text["box"][3], top, (name, text["slot"]))
            self.assertLessEqual(template["picture"]["box"][3], top, name)  # the signature is on paper, not on the picture


class Command(unittest.TestCase):
    def test_bad_input_exits_2_with_the_json_line_and_before_anything_is_imported(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report = run_main(["--template", "two-panel", "--text", "a", "--text2", "b", "--size", "10x10",
                                     "--out", os.path.join(folder, "m.png")])
            self.assertEqual(code, 2)
            self.assertEqual(set(report), {"ok", "outputs", "checks", "problem"})
            self.assertFalse(report["ok"])
            code, report = run_main(["--template", "label", "--text", "a", "--focus", "9,9", "--out", os.path.join(folder, "m.png")])
            self.assertEqual(code, 2)
            self.assertIn("focus", report["problem"])

    def test_a_missing_output_folder_and_a_bad_name_exit_2(self):
        with tempfile.TemporaryDirectory() as folder:
            code, report = run_main(["--template", "caption-bar", "--text", "a", "--out", os.path.join(folder, "none", "m.png")])
            self.assertEqual(code, 2)
            self.assertIn("folder", report["problem"])
            code, _report = run_main(["--template", "caption-bar", "--text", "a", "--out", os.path.join(folder, "m.gif")])
            self.assertEqual(code, 2)

    def test_the_meme_never_overwrites_an_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "picture.png")
            with open(path, "wb") as f:
                f.write(b"not a picture")
            code, report = run_main(["--template", "caption-bar", "--text", "a", "--image", path, "--out", path])
            self.assertEqual(code, 2)
            self.assertIn("overwrite", report["problem"])
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"not a picture")

    def test_an_unknown_template_is_refused_by_the_parser(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            meme.main(["--template", "poster", "--text", "a", "--out", "m.png"])

    def test_help_ends_with_an_example_that_names_the_command(self):
        text = meme.make_parser().format_help().strip().split("\n")
        tail = "\n".join(text[-6:]).lower()
        self.assertIn("example", tail)
        self.assertIn("meme.py", tail)


if __name__ == "__main__":
    unittest.main()
