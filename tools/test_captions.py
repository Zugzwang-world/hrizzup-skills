"""captions.py's cues, its checks of the narration against the script, and its exit codes. No Whisper and no audio are needed here:
what Whisper heard is supplied, and the real listening is proved by the samples (skills/*/examples/captions.json).
"""

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHARED = os.path.join(ROOT, "shared", "scripts")
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

import importlib.util  # noqa: E402

import catalogue  # noqa: E402,F401

spec = importlib.util.spec_from_file_location("captions_cues_under_test", os.path.join(SHARED, "captions.py"))
captions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(captions)
ORIGINAL_ENSURE_MODEL = captions.ensure_model

import hrizzup_script as script  # noqa: E402


def units_for(text, step=0.35, gap_after=None, start=0.3):
    """Timed units for a text: each word `step` seconds, with a longer gap after the words in `gap_after` ({index: seconds})."""
    gap_after = gap_after or {}
    found, clock = [], start
    for number, word in enumerate(text.split()):
        found.append({"shown": word, "start": round(clock, 3), "end": round(clock + step, 3), "paragraph": 0, "matched": True})
        clock += step + gap_after.get(number, 0.05)
    return found


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = captions.main(argv)
    return code, json.loads(out.getvalue().strip().split("\n")[-1]), err.getvalue()


class Lines(unittest.TestCase):
    def test_words_wrap_at_32_characters_and_two_lines_at_most(self):
        self.assertEqual(captions.wrap_lines("a short line".split()), ["a short line"])
        self.assertEqual(captions.wrap_lines("This is an illustrative sample made from".split()), ["This is an illustrative sample", "made from"])
        self.assertIsNone(captions.wrap_lines(("word " * 20).split()))
        self.assertEqual(captions.wrap_lines(["x" * 40]), ["x" * 40])  # one word that is too long is a line of its own
        self.assertEqual(captions.wrap_lines(["a" * 32, "b" * 32]), ["a" * 32, "b" * 32])
        self.assertIsNone(captions.wrap_lines(["a" * 32, "b" * 32, "c"]))


class Cues(unittest.TestCase):
    TEXT = ("This is an illustrative sample made from Hrizzup's example story. Readings in Delhi, Noida and Gurugram passed 450 "
            "before dawn on Monday, the worst of the season so far. Doctors advise people with breathing problems to stay indoors.")

    def cues(self, text=None, **kwargs):
        units = units_for(text or self.TEXT, **kwargs)
        return units, captions.make_cues(units, units[-1]["end"] + 0.5)

    def test_every_cue_holds_two_lines_of_32_characters_and_runs_0_8_to_3_5_seconds(self):
        units, cues = self.cues()
        for cue in cues:
            self.assertLessEqual(len(cue["lines"]), 2)
            self.assertTrue(all(len(line) <= 32 for line in cue["lines"]), cue)
            self.assertGreaterEqual(cue["end"] - cue["start"], 0.8 - 1e-9, cue)
            self.assertLessEqual(cue["end"] - cue["start"], 3.5 + 1e-9, cue)

    def test_the_cues_show_every_word_once_in_order(self):
        units, cues = self.cues()
        shown = " ".join(" ".join(c["lines"]) for c in cues)
        self.assertEqual(shown, " ".join(u["shown"] for u in units))

    def test_cues_are_in_order_and_never_overlap(self):
        _units, cues = self.cues()
        for before, after in zip(cues, cues[1:]):
            self.assertLessEqual(before["end"], after["start"] + 1e-9)
            self.assertLess(before["start"], after["start"])

    def test_a_cue_starts_with_its_first_word_and_stays_a_little_after_its_last(self):
        units, cues = self.cues()
        self.assertEqual(cues[0]["start"], units[0]["start"])
        last_word_end = units[-1]["end"]
        self.assertGreaterEqual(cues[-1]["end"], last_word_end)
        self.assertLessEqual(cues[-1]["end"], last_word_end + captions.LINGER_SECONDS + 1e-9)

    def test_a_sentence_end_breaks_the_cue(self):
        units, cues = self.cues("Short one here. Another short one.")
        self.assertEqual([" ".join(c["lines"]) for c in cues], ["Short one here.", "Another short one."])

    def test_a_pause_over_0_6_seconds_breaks_the_cue(self):
        units = units_for("one two three four", gap_after={1: 0.7})
        cues = captions.make_cues(units, 9.0)
        self.assertEqual([" ".join(c["lines"]) for c in cues], ["one two", "three four"])
        units = units_for("one two three four", gap_after={1: 0.5})
        self.assertEqual(len(captions.make_cues(units, 9.0)), 1)

    def test_a_long_sentence_is_cut_evenly_and_never_leaves_one_word_on_its_own(self):
        units = units_for("This is an illustrative sample made from Hrizzup's example story.")
        cues = captions.make_cues(units, 9.0)
        self.assertEqual(len(cues), 2)
        self.assertTrue(all(len(" ".join(c["lines"]).split()) >= 3 for c in cues), cues)

    def test_a_long_sentence_is_cut_after_a_comma_where_there_is_one(self):
        units = units_for("Before dawn on Monday, AQI readings in Delhi, Noida and Gurugram passed 450.")
        cues = captions.make_cues(units, 12.0)
        self.assertEqual([" ".join(c["lines"]) for c in cues], ["Before dawn on Monday, AQI readings in Delhi,", "Noida and Gurugram passed 450."])

    def test_a_slow_speaker_is_cut_at_3_5_seconds(self):
        units = units_for("one two three four five six seven eight nine ten", step=0.6)
        cues = captions.make_cues(units, 12.0)
        self.assertGreater(len(cues), 1)
        for cue in cues:
            self.assertLessEqual(cue["end"] - cue["start"], 3.5 + 1e-9)

    def test_a_very_short_cue_is_held_to_0_8_seconds_where_the_next_is_not_yet_due(self):
        units = units_for("Yes. Then a long pause and more words follow here.", gap_after={0: 0.9, 1: 0.0})
        cues = captions.make_cues(units, 20.0)
        self.assertEqual(" ".join(cues[0]["lines"]), "Yes.")
        self.assertGreaterEqual(cues[0]["end"] - cues[0]["start"], 0.8 - 1e-9)

    def test_a_cue_never_runs_into_the_next_even_if_that_leaves_it_short(self):
        units = units_for("Go. Stop.", step=0.2, gap_after={0: 0.0})
        cues = captions.make_cues(units, 3.0)
        self.assertEqual(len(cues), 2)
        self.assertLessEqual(cues[0]["end"], cues[1]["start"] + 1e-9)

    def test_a_word_with_two_forms_is_one_unit_and_shown_whole(self):
        units = [{"shown": "Rs 450 crore", "start": 0.0, "end": 1.2, "paragraph": 0, "matched": True},
                 {"shown": "a year.", "start": 1.3, "end": 1.8, "paragraph": 0, "matched": True}]
        cues = captions.make_cues(units, 3.0)
        self.assertEqual(" ".join(cues[0]["lines"]), "Rs 450 crore a year.")

    def test_one_unit_longer_than_a_cue_is_allowed_on_a_cue_of_its_own(self):
        units = [{"shown": "x" * 70, "start": 0.0, "end": 1.0, "paragraph": 0, "matched": True}]
        cues = captions.make_cues(units, 2.0)
        self.assertEqual(len(cues), 1)

    def test_the_end_of_the_narration_bounds_the_last_cue(self):
        units = units_for("The end.", start=0.0)
        cues = captions.make_cues(units, units[-1]["end"] + 0.05)
        self.assertLessEqual(cues[-1]["end"], units[-1]["end"] + 0.05 + 1e-9)


class SubRip(unittest.TestCase):
    def test_times_and_cues(self):
        self.assertEqual(captions.srt_time(0), "00:00:00,000")
        self.assertEqual(captions.srt_time(3661.0075), "01:01:01,008")
        self.assertEqual(captions.srt_time(59.9996), "00:01:00,000")
        text = captions.srt_text([{"start": 0.0, "end": 1.5, "lines": ["One line"]}, {"start": 2.0, "end": 3.25, "lines": ["Two", "lines"]}])
        self.assertEqual(text, "1\n00:00:00,000 --> 00:00:01,500\nOne line\n\n2\n00:00:02,000 --> 00:00:03,250\nTwo\nlines\n")
        self.assertTrue(text.endswith("\n") and not text.endswith("\n\n"))


class Folder(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = self.folder.name

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, text, binary=False):
        with open(self.path(name), "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as f:
            f.write(text)
        return self.path(name)


class ParagraphTimes(Folder):
    def test_a_word_that_follows_a_pause_is_kept_inside_its_paragraph(self):
        units = [{"shown": "can.", "paragraph": 0, "start": 26.0, "end": 27.56, "matched": True},
                 {"shown": "Schools", "paragraph": 1, "start": 27.56, "end": 29.08, "matched": False},   # Whisper reached back into the silence
                 {"shown": "changed", "paragraph": 1, "start": 29.08, "end": 29.3, "matched": True},
                 {"shown": "twice.", "paragraph": 1, "start": 29.3, "end": 31.0, "matched": True}]  # and one ran on after its paragraph ended
        spans = [(20.26, 27.995), (28.595, 29.76)]
        moved = captions.clamp_to_paragraphs([dict(u) for u in units], spans)
        self.assertEqual((moved[1]["start"], moved[1]["end"]), (28.595, 29.08))
        self.assertEqual((moved[0]["start"], moved[0]["end"]), (26.0, 27.56))  # inside already: untouched
        self.assertEqual(moved[3]["end"], 29.76)  # a word that ran past its paragraph ends with it
        edge = captions.clamp_to_paragraphs([{"shown": "a", "paragraph": 1, "start": 28.57, "end": 29.79}], spans)[0]
        self.assertEqual((edge["start"], edge["end"]), (28.57, 29.79))  # within 0.05 s of its paragraph (the encoder's delay): left alone
        for unit in moved:
            self.assertLessEqual(unit["start"], unit["end"])

    def test_the_timings_file_must_be_the_scripts(self):
        good = self.write("t.json", json.dumps({"paragraphs": [{"index": 0, "start": 0.3, "end": 4.0}, {"index": 1, "start": 4.6, "end": 9.0}]}))
        self.assertEqual(captions.read_paragraph_times(good, 2), [(0.3, 4.0), (4.6, 9.0)])
        with self.assertRaises(captions.InputError) as caught:
            captions.read_paragraph_times(good, 3)
        self.assertIn("another script", str(caught.exception))
        for bad in ("{", "[]", json.dumps({"paragraphs": [{"start": "x", "end": 1}]}), json.dumps({"other": 1})):
            with self.assertRaises(captions.InputError):
                captions.read_paragraph_times(self.write("b.json", bad), 1)


class Arguments(Folder):
    def parse(self, *argv):
        return captions.make_parser().parse_args(list(argv))

    def files(self):
        return self.write("n.m4a", b"audio", binary=True), self.write("script.txt", "Hello there.")

    def test_the_defaults(self):
        audio, script_path = self.files()
        args = self.parse("--audio", audio, "--script", script_path, "--out", self.path("c.json"))
        self.assertEqual((args.max_wer, args.offline, args.srt), (0.15, False, None))
        captions.check_arguments(args)

    def test_each_wrong_argument_is_bad_input(self):
        audio, script_path = self.files()
        cases = {
            "wer": ["--max-wer", "1.5"], "json": ["--out", self.path("c.txt")], "srt": ["--srt", self.path("c.txt")],
            "folder": ["--out", self.path("nope/c.json")], "same": ["--out", script_path.replace(".txt", ".json"), "--srt", script_path.replace(".txt", ".json")],
        }
        for label, extra in cases.items():
            argv = ["--audio", audio, "--script", script_path, "--out", self.path("c.json")] + extra
            with self.subTest(label):
                with self.assertRaises(captions.InputError):
                    captions.check_arguments(captions.make_parser().parse_args(argv))

    def test_an_output_is_never_an_input(self):
        audio, script_path = self.files()
        json_input = self.write("again.json", "{}")
        for argv in (["--out", json_input, "--script", json_input], ["--srt", script_path, "--out", self.path("c.json")]):
            args = self.parse("--audio", audio, *(argv if "--script" in argv else ["--script", script_path] + argv))
            if args.out == json_input:
                args.script = json_input
            with self.assertRaises(captions.InputError) as caught:
                captions.check_arguments(args)
            self.assertIn("overwrite", str(caught.exception) + "overwrite" if "srt" in " ".join(argv) else str(caught.exception))

    def test_a_missing_audio_or_script_is_bad_input_with_the_json_line(self):
        code, line, _err = run_main(["--audio", self.path("none.m4a"), "--script", self.path("none.txt"), "--out", self.path("c.json")])
        self.assertEqual((code, line["ok"]), (2, False))
        self.assertIn("none.m4a", line["problem"])


class Listening(Folder):
    """The whole command, with the model and the listening stood in for."""

    SCRIPT = "Readings in {AQI|A Q I} passed 450 today.\n\nSchools in Noida stay open."

    def setup_run(self, heard, seconds=9.0, packages=True):
        audio = self.write("n.m4a", b"audio", binary=True)
        script_path = self.write("script.txt", self.SCRIPT)
        patches = [
            mock.patch.object(captions, "ensure_model", lambda *a, **k: self.dir),
            mock.patch.object(captions, "listen", lambda *a, **k: ([script.Heard(*h) for h in heard], seconds)),
            mock.patch.dict(sys.modules, {"faster_whisper": types.ModuleType("faster_whisper") if packages else None}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return ["--audio", audio, "--script", script_path, "--out", self.path("captions.json"), "--srt", self.path("captions.srt")]

    GOOD = [("Readings", 0.4, 0.9), ("in", 0.9, 1.0), ("AQI", 1.0, 1.6), ("passed", 1.6, 1.9), ("450", 1.9, 3.0), ("today.", 3.0, 3.5),
            ("Schools", 5.0, 5.5), ("in", 5.5, 5.6), ("Noida", 5.6, 6.1), ("stay", 6.1, 6.4), ("open.", 6.4, 6.9)]

    def test_a_good_reading_writes_the_captions_and_says_so(self):
        argv = self.setup_run(self.GOOD)
        code, line, _err = run_main(argv)
        self.assertEqual(code, 0, line)
        self.assertTrue(line["ok"])
        self.assertEqual([o["path"] for o in line["outputs"]], [self.path("captions.json"), self.path("captions.srt")])
        self.assertEqual(line["checks"][0]["wordErrorRate"], 0.0)
        with open(self.path("captions.json"), encoding="utf-8") as f:
            document = json.load(f)
        self.assertEqual(document["wordErrorRate"], 0.0)
        self.assertEqual(document["seconds"], 9.0)
        self.assertEqual([w["shown"] for w in document["words"]], "Readings in AQI passed 450 today. Schools in Noida stay open.".split())
        by = {w["shown"]: w for w in document["words"]}
        self.assertEqual((by["AQI"]["start"], by["AQI"]["end"]), (1.0, 1.6))  # the shown word, timed by the spoken A Q I
        self.assertEqual((by["450"]["start"], by["450"]["end"]), (1.9, 3.0))  # "four hundred fifty" shared the number's time
        self.assertTrue(all(w["matched"] for w in document["words"]))
        shown = " ".join(" ".join(c["lines"]) for c in document["cues"])
        self.assertEqual(shown, "Readings in AQI passed 450 today. Schools in Noida stay open.")  # the script's words, never Whisper's
        with open(self.path("captions.srt"), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("1\n00:00:00,400 --> "))

    def test_the_numbers_and_spelled_letters_are_not_errors_however_whisper_wrote_them(self):
        spelled = [("Readings", 0.4, 0.9), ("in", 0.9, 1.0), ("A", 1.0, 1.2), ("Q", 1.2, 1.4), ("I", 1.4, 1.6), ("passed", 1.6, 1.9),
                   ("four", 1.9, 2.2), ("hundred", 2.2, 2.5), ("and", 2.5, 2.6), ("fifty", 2.6, 3.0), ("today", 3.0, 3.5)] + self.GOOD[6:]
        code, line, _err = run_main(self.setup_run(spelled))
        self.assertEqual(code, 0, line)
        self.assertEqual(line["checks"][0]["wordErrorRate"], 0.0)

    def test_a_reading_too_far_from_the_script_exits_1_listing_the_words_and_writes_nothing(self):
        wrong = [("Readings", 0.4, 0.9), ("in", 0.9, 1.0), ("AQI", 1.0, 1.6), ("passed", 1.6, 1.9), ("500", 1.9, 3.0), ("today.", 3.0, 3.5),
                 ("Schools", 5.0, 5.5), ("in", 5.5, 5.6), ("Noyda", 5.6, 6.1), ("stay", 6.1, 6.4), ("shut.", 6.4, 6.9)]
        code, line, _err = run_main(self.setup_run(wrong) + ["--max-wer", "0.1"])
        self.assertEqual(code, 1)
        self.assertFalse(line["ok"])
        self.assertIn("said 'four', heard 'five'", line["problem"])  # 450 is four hundred fifty, and 500 five hundred
        self.assertIn("said 'noida', heard 'noyda'", line["problem"])
        self.assertIn("{shown|spoken}", line["problem"])
        self.assertFalse(line["checks"][0]["ok"])
        self.assertFalse(os.path.exists(self.path("captions.json")) or os.path.exists(self.path("captions.srt")))

    def test_the_limit_is_the_callers_to_move(self):
        wrong = list(self.GOOD)
        wrong[4] = ("500", 1.9, 3.0)
        argv = self.setup_run(wrong)
        self.assertEqual(run_main(argv + ["--max-wer", "0.05"])[0], 1)
        self.assertEqual(run_main(argv + ["--max-wer", "0.3"])[0], 0)

    def test_words_that_were_not_heard_are_placed_between_their_neighbours_and_flagged(self):
        missing = [h for h in self.GOOD if h[0] != "stay"]
        code, line, _err = run_main(self.setup_run(missing, ) + ["--max-wer", "0.3"])
        self.assertEqual(code, 0, line)
        with open(self.path("captions.json"), encoding="utf-8") as f:
            words = {w["shown"]: w for w in json.load(f)["words"]}
        self.assertFalse(words["stay"]["matched"])
        self.assertTrue(words["Noida"]["end"] <= words["stay"]["start"] + 1e-9 and words["stay"]["end"] <= words["open."]["start"] + 1e-9)

    def test_without_faster_whisper_it_exits_3_and_says_how_to_install_it(self):
        code, line, _err = run_main(self.setup_run(self.GOOD, packages=False))
        self.assertEqual(code, 3)
        self.assertIn("uv run scripts/captions.py", line["problem"])
        self.assertIn("--require-hashes -r scripts/captions.requirements.txt", line["problem"])

    def test_offline_with_no_model_exits_3_and_says_what_to_do(self):
        argv = self.setup_run(self.GOOD)
        empty = os.path.join(self.dir, "models")
        os.mkdir(empty)
        with mock.patch.object(captions, "ensure_model", ORIGINAL_ENSURE_MODEL), mock.patch.dict(os.environ, {"HRIZZUP_MODELS_DIR": empty}):
            code, line, _err = run_main(argv + ["--offline"])
        self.assertEqual(code, 3)
        for words in ("--offline", "model.bin", "tokenizer.json", "without --offline", "MiB"):
            self.assertIn(words, line["problem"])
        self.assertEqual(os.listdir(empty), [])

    def test_the_command_uses_them_and_says_so(self):
        argv = self.setup_run(self.GOOD)
        timings = self.write("timings.json", json.dumps({"paragraphs": [{"index": 0, "start": 1.1, "end": 3.2}, {"index": 1, "start": 5.2, "end": 6.9}]}))
        code, line, _err = run_main(argv + ["--timings", timings])
        self.assertEqual(code, 0, line)
        with open(os.path.join(self.dir, "captions.json"), encoding="utf-8") as f:
            document = json.load(f)
        self.assertTrue(document["paragraphTimesFromVoice"])
        first = document["words"][0]
        self.assertEqual(first["start"], 1.1)  # Readings was heard at 0.4, before the paragraph was spoken
        self.assertEqual(document["words"][6]["start"], 5.2)  # and Schools, heard at 5.0, waits for its paragraph
        code, line, _err = run_main(argv + ["--timings", self.write("t2.json", json.dumps({"paragraphs": []}))])
        self.assertEqual(code, 2)
        self.assertIn("another script", line["problem"])
        code, line, _err = run_main(argv + ["--timings", os.path.join(self.dir, "none.json")])
        self.assertEqual(code, 2)

    def test_a_script_the_captions_cant_show_is_bad_input(self):
        argv = self.setup_run(self.GOOD)
        self.write("script.txt", "Fine.\n\n\U0001F600")
        code, line, _err = run_main(argv)
        self.assertEqual(code, 2)
        self.assertIn("line 3", line["problem"])


if __name__ == "__main__":
    unittest.main()
