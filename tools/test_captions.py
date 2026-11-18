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
import test_media as built  # noqa: E402

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

    def m4a(self, name, seconds=9.0, codec=b"mp4a"):
        """A synthetic .m4a with real boxes and a duration (nothing here plays it): what `--audio` must be."""
        moov = built.box(b"moov", built.mvhd(1000, int(seconds * 1000)) + built.trak(b"soun", codec))
        return self.write(name, built.ftyp(b"M4A ") + moov + built.mdat(), binary=True)


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

    SCRIPT = "One two three.\n\nFour five six."

    def timings(self, paragraphs=None, seconds=9.0):
        paragraphs = paragraphs or [{"index": 0, "start": 0.3, "end": 4.0, "shown": "One two three."}, {"index": 1, "start": 4.6, "end": 9.0, "shown": "Four five six."}]
        return self.write("t.json", json.dumps({"seconds": seconds, "paragraphs": paragraphs}))

    def test_the_timings_file_must_be_the_scripts_and_the_narrations(self):
        parsed = script.parse(self.SCRIPT)
        self.assertEqual(captions.read_paragraph_times(self.timings(), parsed, 9.0), [(0.3, 4.0), (4.6, 9.0)])
        self.assertEqual(captions.read_paragraph_times(self.timings(), parsed, 9.04), [(0.3, 4.0), (4.6, 9.0)])  # within 0.05 s of the audio's length
        with self.assertRaises(captions.InputError) as caught:
            captions.read_paragraph_times(self.timings(), script.parse("One two three.\n\nFour five six.\n\nSeven."), 9.0)
        self.assertIn("another script", str(caught.exception))
        for bad in ("{", "[]", json.dumps({"paragraphs": [{"start": "x", "end": 1, "shown": "a"}], "seconds": 1}), json.dumps({"other": 1})):
            with self.assertRaises(captions.InputError):
                captions.read_paragraph_times(self.write("b.json", bad), script.parse("a"), 1.0)

    def test_timings_of_a_script_with_other_words_but_as_many_paragraphs_are_refused(self):
        other = [{"index": 0, "start": 0.3, "end": 4.0, "shown": "One two three."}, {"index": 1, "start": 4.6, "end": 9.0, "shown": "Seven eight nine."}]
        with self.assertRaises(captions.InputError) as caught:
            captions.read_paragraph_times(self.timings(other), script.parse(self.SCRIPT), 9.0)
        self.assertIn("paragraph 2", str(caught.exception))
        self.assertIn("another script", str(caught.exception))

    def test_timings_of_another_narration_are_refused(self):
        parsed = script.parse(self.SCRIPT)
        for audio in (9.06, 8.9, 61.1):
            with self.subTest(audio=audio):
                with self.assertRaises(captions.InputError) as caught:
                    captions.read_paragraph_times(self.timings(), parsed, audio)
                self.assertIn("another narration", str(caught.exception))


class Arguments(Folder):
    def parse(self, *argv):
        return captions.make_parser().parse_args(list(argv))

    def files(self):
        return self.m4a("n.m4a"), self.write("script.txt", "Hello there.")

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

    def test_the_narration_must_be_an_aac_m4a_or_mp4_read_by_the_repositorys_own_parser(self):
        """`--audio` goes to PyAV, which follows a playlist and opens any container it knows: it is read here first."""
        script_path = self.write("script.txt", "Hello there.")
        playlist = b"#EXTM3U\n#EXTINF:1,\nhttp://example.com/a.aac\n"
        looks = {
            "a playlist": self.write("list.m4a", playlist, binary=True), "a playlist named .m3u8": self.write("list.m3u8", playlist, binary=True),
            "a playlist named .mp4": self.write("list.mp4", playlist, binary=True), "an mp3": self.write("n.mp3", b"ID3" + bytes(64), binary=True),
            "a wav": self.write("n.wav", b"RIFF" + bytes(40), binary=True), "junk named .m4a": self.write("junk.m4a", b"audio", binary=True),
            "an empty .m4a": self.write("empty.m4a", b"", binary=True), "ALAC sound": self.m4a("alac.m4a", codec=b"alac"),
            "a video with no sound": self.write("silent.mp4", built.ftyp() + built.box(b"moov", built.mvhd(1000, 9000) + built.trak(b"vide", b"avc1", 1080, 1920)) + built.mdat(), binary=True),
        }
        for label, path in looks.items():
            with self.subTest(label):
                args = self.parse("--audio", path, "--script", script_path, "--out", self.path("c.json"))
                with self.assertRaises(captions.InputError) as caught:
                    captions.check_arguments(args)
                self.assertIn("--audio", str(caught.exception))
                with mock.patch.object(captions, "listen") as listening:  # and nothing is listened to
                    code, line, _err = run_main(["--audio", path, "--script", script_path, "--out", self.path("c.json")])
                self.assertEqual((code, line["ok"]), (2, False))
                listening.assert_not_called()
        good = self.m4a("good.m4a", 9.0)
        _out, _srt, seconds = captions.check_arguments(self.parse("--audio", good, "--script", script_path, "--out", self.path("c.json")))
        self.assertEqual(seconds, 9.0)
        mp4 = self.write("v.mp4", built.ftyp() + built.video_moov(9000) + built.mdat(), binary=True)  # a video with AAC sound
        self.assertEqual(captions.check_arguments(self.parse("--audio", mp4, "--script", script_path, "--out", self.path("c.json")))[2], 9.0)

    def test_the_help_names_only_the_formats_it_takes(self):
        text = captions.make_parser().format_help()
        self.assertNotIn(".mp3", text)
        self.assertNotIn(".wav", text)
        self.assertIn(".m4a", text)

    def test_a_missing_audio_or_script_is_bad_input_with_the_json_line(self):
        code, line, _err = run_main(["--audio", self.path("none.m4a"), "--script", self.path("none.txt"), "--out", self.path("c.json")])
        self.assertEqual((code, line["ok"]), (2, False))
        self.assertIn("none.m4a", line["problem"])


class Listening(Folder):
    """The whole command, with the model and the listening stood in for."""

    SCRIPT = "Readings in {AQI|A Q I} passed 450 today.\n\nSchools in Noida stay open."

    def setup_run(self, heard, seconds=9.0, packages=True, script_text=None):
        audio = self.m4a("n.m4a", seconds)
        script_path = self.write("script.txt", script_text or self.SCRIPT)
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
        self.assertEqual(line["checks"][0]["differences"], [])
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
        self.assertIn("said '450' (four hundred fifty), heard 'five hundred'", line["problem"])  # a number heard as another
        self.assertIn("said 'Noida', heard 'noyda'", line["problem"])
        self.assertIn("said 'open.', heard 'shut'", line["problem"])
        self.assertIn("a number was heard as another", line["problem"])
        self.assertIn("the voice itself says it wrong", line["problem"])
        self.assertIn("the recogniser's spelling, not the voice: leave it", line["problem"])
        self.assertEqual(len(line["checks"][0]["differences"]), 3)  # every difference is in the checks, on a fail too
        self.assertFalse(line["checks"][0]["ok"])
        self.assertFalse(os.path.exists(self.path("captions.json")) or os.path.exists(self.path("captions.srt")))

    def test_the_limit_is_the_callers_to_move(self):
        wrong = list(self.GOOD)
        wrong[5] = ("tonight", 3.0, 3.5)  # one word of 11 changed: a rate of 0.09
        argv = self.setup_run(wrong)
        self.assertEqual(run_main(argv + ["--max-wer", "0.05"])[0], 1)
        self.assertEqual(run_main(argv + ["--max-wer", "0.15"])[0], 0)

    # ---- the gate exists to catch the voice failing: a sentence skipped, a number said wrong ----
    LONG = ("Before dawn on Monday readings in Delhi and Noida passed 450, the worst of the season so far. "
            "Doctors advise people with breathing problems to stay indoors. "
            "The emergency rules stop building work and keep diesel trucks out of Delhi.\n\n"
            "On Tuesday a correction said only primary schools have moved online. Schools in Noida stay open.")

    def long_heard(self, drop=None, change=None, drop_tail=0):
        words = []
        clock = 0.3
        for word in self.LONG.replace("\n\n", " ").split():
            words.append([word, clock, clock + 0.3])
            clock += 0.35
        if change:
            for number, word in enumerate(words):
                if word[0].rstrip(",.") == change[0]:
                    words[number][0] = change[1]
        if drop:
            words = [w for w in words if w[0] not in drop]
        if drop_tail:
            words = words[:-drop_tail]
        return [tuple(w) for w in words], clock + 1.0

    def test_a_dropped_sentence_fails_even_when_the_word_error_rate_is_under_the_limit(self):
        heard, seconds = self.long_heard(drop_tail=5)  # the last sentence ("Schools in Noida stay open."), five words of fifty-six
        code, line, _err = run_main(self.setup_run(heard, seconds, script_text=self.LONG))
        self.assertEqual(code, 1, line)
        rate = line["checks"][0]["wordErrorRate"]
        self.assertLess(rate, 0.15)  # a rate that would pass, were it not for the run of missing words
        self.assertGreaterEqual(line["checks"][0]["longestRunNotHeard"], 3)
        self.assertIn("script words in a row weren't heard", line["problem"])
        self.assertNotIn("word error rate", line["problem"].split("Where they part")[0])
        self.assertIn("heard nothing there", line["problem"])
        self.assertFalse(os.path.exists(self.path("captions.json")))

    def test_two_words_in_a_row_not_heard_are_a_name_or_two_not_a_failure(self):
        heard, seconds = self.long_heard(drop={"Delhi", "and"})
        code, line, _err = run_main(self.setup_run(heard, seconds, script_text=self.LONG))
        self.assertEqual(code, 0, line)
        self.assertEqual(line["checks"][0]["longestRunNotHeard"], 2)

    def test_a_number_heard_as_a_different_number_fails_however_few_words_it_is(self):
        heard, seconds = self.long_heard(change=("450", "500"))
        code, line, _err = run_main(self.setup_run(heard, seconds, script_text=self.LONG))
        self.assertEqual(code, 1, line)
        self.assertLess(line["checks"][0]["wordErrorRate"], 0.15)  # one word of thirty-odd: the rate alone would pass it
        self.assertEqual(line["checks"][0]["numbersHeardWrong"], ["said '450,' (four hundred fifty), heard 'five hundred'"])
        self.assertIn("a number was heard as another", line["problem"])

    def test_a_number_heard_in_either_way_of_writing_it_passes(self):
        for written in ("450", "four hundred fifty", "four hundred and fifty"):
            heard, seconds = self.long_heard(change=("450", written))
            code, line, _err = run_main(self.setup_run(heard, seconds, script_text=self.LONG))
            self.assertEqual(code, 0, (written, line))

    def test_a_name_that_is_respelt_is_heard_either_way(self):
        text = "This is a sample made from {Hrizzup's|Hrizz-up's} example story. It has some more words in it to read aloud."
        spoken = text.replace("{Hrizzup's|Hrizz-up's}", "Hrizz up's")
        for label, wording in (("as shown", text.replace("{Hrizzup's|Hrizz-up's}", "Hrizzup's")), ("as spoken", spoken)):
            words = wording.split()
            heard = [(w, 0.3 + 0.3 * n, 0.5 + 0.3 * n) for n, w in enumerate(words)]
            code, line, _err = run_main(self.setup_run(heard, 8.0, script_text=text))
            with self.subTest(label):
                self.assertEqual(code, 0, line)
                self.assertEqual(line["checks"][0]["differences"], [])

    def test_a_name_neither_way_costs_one_word_not_two(self):
        text = "This is a sample made from {Hrizzup's|Hrizz-up's} example story. It has some more words in it to read aloud."
        words = text.replace("{Hrizzup's|Hrizz-up's}", "H. Rezaup's").split()
        heard = [(w, 0.3 + 0.3 * n, 0.5 + 0.3 * n) for n, w in enumerate(words)]
        code, line, _err = run_main(self.setup_run(heard, 8.0, script_text=text))
        self.assertEqual(code, 0, line)
        self.assertEqual(line["checks"][0]["differences"], ["said \"Hrizzup's\", heard \"h rezaup's\""])  # every difference, on a pass too
        self.assertEqual(line["checks"][0]["scriptWords"], 19)  # the name is one of the script's words, not two
        self.assertAlmostEqual(line["checks"][0]["wordErrorRate"], 1 / 19, places=3)

    def test_every_difference_is_in_the_checks_on_a_pass_and_in_the_captions_file(self):
        heard, seconds = self.long_heard(change=("Noida", "Noyda"))
        code, line, _err = run_main(self.setup_run(heard, seconds, script_text=self.LONG))
        self.assertEqual(code, 0, line)
        self.assertEqual(len(line["checks"][0]["differences"]), 2)  # Noida appears twice
        with open(self.path("captions.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["differences"], line["checks"][0]["differences"])

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
        timings = self.write("timings.json", json.dumps({"seconds": 9.0, "paragraphs": [
            {"index": 0, "start": 1.1, "end": 3.2, "shown": "Readings in AQI passed 450 today."}, {"index": 1, "start": 5.2, "end": 6.9, "shown": "Schools in Noida stay open."}]}))
        code, line, _err = run_main(argv + ["--timings", timings])
        self.assertEqual(code, 0, line)
        with open(os.path.join(self.dir, "captions.json"), encoding="utf-8") as f:
            document = json.load(f)
        self.assertTrue(document["paragraphTimesFromVoice"])
        first = document["words"][0]
        self.assertEqual(first["start"], 1.1)  # Readings was heard at 0.4, before the paragraph was spoken
        self.assertEqual(document["words"][6]["start"], 5.2)  # and Schools, heard at 5.0, waits for its paragraph
        code, line, _err = run_main(argv + ["--timings", self.write("t2.json", json.dumps({"seconds": 9.0, "paragraphs": []}))])
        self.assertEqual(code, 2)
        self.assertIn("another script", line["problem"])
        other = json.dumps({"seconds": 9.0, "paragraphs": [{"index": 0, "start": 1.1, "end": 3.2, "shown": "Other words."}, {"index": 1, "start": 5.2, "end": 6.9, "shown": "Schools in Noida stay open."}]})
        code, line, _err = run_main(argv + ["--timings", self.write("t3.json", other)])  # as many paragraphs, not this script's words
        self.assertEqual(code, 2)
        self.assertIn("paragraph 1", line["problem"])
        later = json.dumps({"seconds": 12.0, "paragraphs": [{"index": 0, "start": 1.1, "end": 3.2, "shown": "Readings in AQI passed 450 today."}, {"index": 1, "start": 5.2, "end": 6.9, "shown": "Schools in Noida stay open."}]})
        code, line, _err = run_main(argv + ["--timings", self.write("t4.json", later)])  # this script's, another narration's
        self.assertEqual(code, 2)
        self.assertIn("another narration", line["problem"])
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
