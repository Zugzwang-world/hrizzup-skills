"""edit.py, cards.py and still.py: reading their input, the maths of a scene's motion, their exit codes, and (where Pillow, fontTools and
FFmpeg are installed) a small real video, set of cards and still.

The first classes need nothing installed, so the repository's offline check runs them. The drawing and the encoding are proved by the
samples (skills/explainer-video/examples) and by this file's last classes, which run where the packages are (the "Kits on Linux"
workflow, or `uv run --with ...`) and are skipped where they aren't.
"""

import contextlib
import io
import json
import math
import os
import struct
import sys
import tempfile
import unittest
import wave
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXPLAINER = os.path.join(ROOT, "skills", "explainer-video", "scripts")
SHARED = os.path.join(ROOT, "shared", "scripts")
for folder in (EXPLAINER, SHARED):
    if folder not in sys.path:
        sys.path.insert(0, folder)

import importlib.util  # noqa: E402

import catalogue  # noqa: E402
import test_media  # noqa: E402

media = catalogue.media


def load(name, folder):
    spec = importlib.util.spec_from_file_location(name + "_under_test", os.path.join(folder, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


edit = load("edit", EXPLAINER)
cards = load("cards", EXPLAINER)
still = load("still", SHARED)


def have(*names):
    try:
        for name in names:
            __import__(name)
    except ImportError:
        return False
    return True


def real_ffmpeg():
    try:
        return media.find_ffmpeg()
    except media.FfmpegError:
        return None


def run_main(module, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(argv)
    return code, json.loads(out.getvalue().strip().split("\n")[-1]), err.getvalue()


class Folder(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.dir = self.folder.name

    def path(self, *parts):
        return os.path.join(self.dir, *parts)

    def touch(self, *parts, data=b""):
        os.makedirs(os.path.dirname(self.path(*parts)), exist_ok=True)
        with open(self.path(*parts), "wb") as f:
            f.write(data)
        return self.path(*parts)

    def json_file(self, name, document):
        os.makedirs(os.path.dirname(self.path(name)), exist_ok=True)
        with open(self.path(name), "w", encoding="utf-8") as f:
            json.dump(document, f)
        return self.path(name)

    def picture(self, *parts, width=1080, height=1920):
        """A picture file with a real PNG header (a plan reads a picture's shape to choose its `fit`); its pixels aren't there."""
        return self.touch(*parts, data=test_media.png(width, height))

    def m4a(self, name, seconds, codec=b"mp4a"):
        """A synthetic .m4a: its boxes are real, its sound isn't (nothing here plays it)."""
        moov = test_media.box(b"moov", test_media.mvhd(1000, int(seconds * 1000)) + test_media.trak(b"soun", codec))
        return self.touch(name, data=test_media.ftyp(b"M4A ") + moov + test_media.mdat())


# ---------------------------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------------------------

class Plans(Folder):
    def plan(self, scenes, **extra):
        self.picture("cards", "a.png")
        self.picture("cards", "b.png")
        self.touch("c.mp4", data=test_media.ftyp() + test_media.video_moov(6000) + test_media.mdat())  # real boxes: a clip is read from its own bytes
        return self.json_file("plan.json", dict({"scenes": scenes}, **extra))

    def test_a_good_plan_is_read_with_its_defaults_filled_in(self):
        path = self.plan([{"image": "cards/a.png", "seconds": 5}, {"image": "cards/b.png", "seconds": 3.5, "motion": "pan-left", "focus": [0.2, 0.9],
                                                                   "fit": "contain", "text": "  A  line "}, {"clip": "c.mp4", "trim": [2, 6.5]}], transition="fade")
        found = edit.read_plan(path)
        self.assertEqual(found["transition"], "fade")
        first, second, third = found["scenes"]
        self.assertEqual((first["kind"], first["motion"], first["focus"], first["fit"], first["text"]), ("image", "still", (0.5, 0.5), "cover", None))  # a 9:16 card
        self.assertEqual(first["path"], self.path("cards", "a.png"))
        self.assertEqual((second["motion"], second["focus"], second["fit"], second["text"]), ("pan-left", (0.2, 0.9), "contain", "A line"))
        self.assertEqual((third["kind"], third["trim"], third["seconds"]), ("clip", (2.0, 6.5), 4.5))  # a clip's length is its trim

    def test_a_picture_of_another_shape_is_shown_whole_unless_the_plan_says_cover(self):
        """A 1080 x 1350 picture covering the 1080 x 1920 frame would lose 456 pixels each side: its words. So `fit` is `contain`
        unless the picture is the frame's own 9:16 shape, and "cover" stays what a plan can ask for."""
        shapes = {"card": (1080, 1920, "cover"), "a chart": (1080, 1350, "contain"), "a square": (1080, 1080, "contain"),
                  "a landscape": (1920, 1080, "contain"), "a 3:4 photo": (1500, 2000, "contain"), "a 9:16 phone video frame": (720, 1280, "cover"),
                  "nearly 9:16": (1000, 1800, "cover"), "9:19.5": (1080, 2340, "contain")}
        for label, (width, height, fit) in shapes.items():
            with self.subTest(label):
                self.picture("pictures", "p.png", width=width, height=height)
                path = self.json_file("plan.json", {"scenes": [{"image": "pictures/p.png", "seconds": 4}]})
                self.assertEqual(edit.read_plan(path)["scenes"][0]["fit"], fit)
                self.assertEqual(edit.default_fit(width, height), fit)
        self.picture("pictures", "p.png", width=1080, height=1350)
        for given in ("cover", "contain"):  # what the plan says wins
            path = self.json_file("plan.json", {"scenes": [{"image": "pictures/p.png", "seconds": 4, "fit": given}]})
            self.assertEqual(edit.read_plan(path)["scenes"][0]["fit"], given)

    def test_a_clip_is_always_cover_and_a_picture_that_cannot_be_read_is_refused(self):
        self.touch("c.mp4", data=test_media.ftyp() + test_media.video_moov(6000) + test_media.mdat())
        self.assertEqual(edit.read_plan(self.json_file("plan.json", {"scenes": [{"clip": "c.mp4", "seconds": 3}]}))["scenes"][0]["fit"], "cover")
        for name, data in (("p.gif", b"GIF89a"), ("p.png", b"not a picture"), ("p.png", b"")):
            self.touch("pictures", name, data=data)
            path = self.json_file("plan.json", {"scenes": [{"image": "pictures/" + name, "seconds": 4}]})
            with self.assertRaises(edit.InputError) as caught:
                edit.read_plan(path)
            self.assertIn("can't read the picture", str(caught.exception))

    def test_every_rule_is_named_when_it_is_broken(self):
        good = {"image": "cards/a.png", "seconds": 4}
        cases = {
            "image or clip": [{"seconds": 4}], "both": [dict(good, clip="c.mp4")], "keys": [dict(good, colour="red")],
            "motion": [dict(good, motion="spin")], "clip no motion": [{"clip": "c.mp4", "seconds": 3, "motion": "zoom-in"}],
            "fit": [dict(good, fit="stretch")], "clip fit": [{"clip": "c.mp4", "seconds": 3, "fit": "cover"}],
            "focus": [dict(good, focus=[0.5])], "focus range": [dict(good, focus=[1.5, 0.5])], "focus type": [dict(good, focus=["a", "b"])],
            "trim on image": [dict(good, trim=[0, 1])], "trim order": [{"clip": "c.mp4", "trim": [3, 1]}],
            "seconds missing": [{"image": "cards/a.png"}], "seconds small": [dict(good, seconds=0.1)], "seconds type": [dict(good, seconds="4")],
            "seconds bool": [dict(good, seconds=True)], "text long": [dict(good, text="x" * 81)], "text empty": [dict(good, text="  ")],
            "text control": [dict(good, text="a\u0007b")], "dotdot": [dict(good, image="../a.png")], "absolute": [dict(good, image="/etc/passwd")],
            "missing file": [dict(good, image="cards/none.png")], "empty path": [dict(good, image="")], "scene type": ["cards/a.png"],
        }
        for label, scenes in cases.items():
            with self.subTest(label):
                with self.assertRaises(edit.InputError) as caught:
                    edit.read_plan(self.plan(scenes))
                self.assertIn("scene 1", str(caught.exception))

    def test_a_clip_that_only_looks_like_an_mp4_is_refused_before_anything_runs(self):
        self.picture("cards", "a.png")
        look_alikes = {
            "an HLS playlist": b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:4,\nhttp://example.com/segment.ts\n",
            "a playlist of a local file": b"#EXTM3U\n#EXTINF:1,\n/etc/hostname\n",
            "a concat list": b"ffconcat version 1.0\nfile '/etc/hostname'\n",
            "an empty file": b"",
            "audio only": test_media.ftyp(b"M4A ") + test_media.box(b"moov", test_media.mvhd(1000, 4000) + test_media.trak(b"soun", b"mp4a")) + test_media.mdat(),
        }
        for label, data in look_alikes.items():
            with self.subTest(label):
                self.touch("clip.mp4", data=data)
                path = self.json_file("plan.json", {"scenes": [{"image": "cards/a.png", "seconds": 2}, {"clip": "clip.mp4", "seconds": 2}]})
                with self.assertRaises(edit.InputError) as caught:
                    edit.read_plan(path)
                self.assertIn("scene 2", str(caught.exception))
                self.assertIn("clip.mp4", str(caught.exception))
                self.assertIn("an MP4 with a video track", str(caught.exception))

    def test_a_clip_path_that_is_an_address_is_not_a_file_and_is_refused(self):
        for name in ("http://example.com/a.mp4", "concat:a.mp4|b.mp4", "file:/etc/hostname"):
            path = self.json_file("plan.json", {"scenes": [{"clip": name, "seconds": 2}]})
            with self.assertRaises(edit.InputError):
                edit.read_plan(path)

    def test_the_plan_itself_is_checked(self):
        self.picture("cards", "a.png")
        for document, why in (({"scenes": []}, "1 to"), ({"scenes": "x"}, "1 to"), ({}, "scenes"), ({"scenes": [], "extra": 1}, "scenes"),
                              ({"scenes": [{"image": "cards/a.png", "seconds": 2}], "transition": "wipe"}, "transition"), ([], "scenes")):
            with self.subTest(document):
                with self.assertRaises(edit.InputError) as caught:
                    edit.read_plan(self.json_file("p.json", document))
                self.assertIn(why, str(caught.exception))
        many = {"scenes": [{"image": "cards/a.png", "seconds": 1}] * 41}
        with self.assertRaises(edit.InputError):
            edit.read_plan(self.json_file("many.json", many))
        with self.assertRaises(edit.InputError):
            edit.read_plan(self.path("not-there.json"))
        with open(self.path("bad.json"), "w") as f:
            f.write("{nope")
        with self.assertRaises(edit.InputError) as caught:
            edit.read_plan(self.path("bad.json"))
        self.assertIn("valid JSON", str(caught.exception))


class Timing(unittest.TestCase):
    def scenes(self, *seconds):
        return [{"seconds": s} for s in seconds]

    def test_the_last_scene_takes_what_is_left_of_the_narration(self):
        counts, starts, total = edit.schedule(self.scenes(7.0, 12.5, 99.0), 52.5)
        self.assertEqual(total, 1575)
        self.assertEqual(starts, [0, 210, 585])
        self.assertEqual(counts, [210, 375, 990])
        self.assertEqual(sum(counts), total)

    def test_the_video_is_never_shorter_than_its_narration(self):
        for seconds in (52.5, 52.51, 52.49, 10.0333, 57.99):
            counts, _starts, total = edit.schedule(self.scenes(3.0, 5.0), seconds)
            self.assertGreaterEqual(total / edit.FPS, seconds - 1e-9)
            self.assertLess(total / edit.FPS - seconds, 1.0 / edit.FPS + 1e-9)
            self.assertEqual(sum(counts), total)

    def test_at_least_a_second_must_be_left_for_the_last_scene(self):
        edit.schedule(self.scenes(4.0, 1.0), 5.0)
        with self.assertRaises(edit.InputError) as caught:
            edit.schedule(self.scenes(4.5, 1.0), 5.0)
        self.assertIn("at least 1.0 s", str(caught.exception))
        self.assertIn("shorten the earlier scenes", str(caught.exception))
        with self.assertRaises(edit.InputError):
            edit.schedule(self.scenes(10.0, 1.0), 5.0)

    def test_a_single_scene_is_the_whole_video(self):
        counts, starts, total = edit.schedule(self.scenes(1.0), 4.0)
        self.assertEqual((counts, starts, total), ([120], [0], 120))

    def test_the_scene_a_frame_is_in(self):
        starts = [0, 210, 585]
        for frame, scene in ((0, 0), (209, 0), (210, 1), (584, 1), (585, 2), (1574, 2)):
            self.assertEqual(edit.scene_at(starts, frame), scene)

    def test_the_cue_showing_at_a_time(self):
        cues = [{"start": 0.5, "end": 2.0}, {"start": 2.0, "end": 3.0}, {"start": 4.0, "end": 5.0}]
        self.assertEqual(edit.cue_at(cues, 0.2, 0), (None, 0))
        self.assertEqual(edit.cue_at(cues, 0.5, 0), (0, 0))
        self.assertEqual(edit.cue_at(cues, 2.0, 0), (1, 1))
        self.assertEqual(edit.cue_at(cues, 3.5, 1), (None, 2))
        self.assertEqual(edit.cue_at(cues, 4.5, 2), (2, 2))
        self.assertEqual(edit.cue_at(cues, 9.0, 2), (None, 3))

    def test_a_fade_is_half_a_second_centred_on_the_cut_and_only_when_asked_for(self):
        starts = [0, 210, 585]
        self.assertIsNone(edit.fade_window(starts, 210, "cut"))
        self.assertIsNone(edit.fade_window(starts, 100, "fade"))
        self.assertIsNone(edit.fade_window(starts, 5, "fade"))  # the first scene doesn't fade in
        before, after, amount = edit.fade_window(starts, 202, "fade")
        self.assertEqual((before, after), (0, 1))
        self.assertTrue(0.0 < amount < 0.5)
        self.assertEqual(edit.fade_window(starts, 210, "fade")[:2], (0, 1))
        self.assertEqual(edit.fade_window(starts, 217, "fade")[:2], (0, 1))
        self.assertIsNone(edit.fade_window(starts, 218, "fade"))
        self.assertIsNone(edit.fade_window([0], 50, "fade"))
        amounts = [edit.fade_window(starts, f, "fade")[2] for f in range(202, 218)]
        self.assertEqual(amounts, sorted(amounts))
        self.assertTrue(all(0.0 < a < 1.0 for a in amounts))


class Motion(unittest.TestCase):
    SIZE = (1350, 2400)

    def test_ease_starts_and_ends_softly(self):
        self.assertEqual((edit.ease(0), edit.ease(1), edit.ease(0.5)), (0.0, 1.0, 0.5))
        self.assertEqual(edit.ease(-1), 0.0)
        self.assertEqual(edit.ease(2), 1.0)
        samples = [edit.ease(n / 100) for n in range(101)]
        self.assertEqual(samples, sorted(samples))
        self.assertLess(edit.ease(0.05), 0.05)  # slower than a straight line at the start

    def test_a_still_shows_the_whole_picture(self):
        for progress in (0, 0.5, 1):
            self.assertEqual(edit.motion_box("still", progress, self.SIZE, (0.2, 0.8)), (0.0, 0.0, 1350.0, 2400.0))

    def test_a_zoom_goes_from_the_whole_picture_in_to_the_most_the_safe_area_allows(self):
        start = edit.motion_box("zoom-in", 0.0, self.SIZE, (0.5, 0.5))
        end = edit.motion_box("zoom-in", 1.0, self.SIZE, (0.5, 0.5))
        self.assertEqual(start, (0.0, 0.0, 1350.0, 2400.0))
        zoom = 1350 / (end[2] - end[0])
        self.assertAlmostEqual(zoom, edit.zoom_limit())
        self.assertLess(zoom, edit.ZOOM_MAX)  # the cards' words span 88% of their width: 1.12 times would push them off
        self.assertGreater(zoom, 1.10)
        self.assertAlmostEqual(2400 / (end[3] - end[1]), zoom)
        self.assertEqual(edit.motion_box("zoom-out", 0.0, self.SIZE, (0.5, 0.5)), end)
        self.assertEqual(edit.motion_box("zoom-out", 1.0, self.SIZE, (0.5, 0.5)), start)
        widths = [edit.motion_box("zoom-in", n / 50, self.SIZE, (0.5, 0.5))[2] - edit.motion_box("zoom-in", n / 50, self.SIZE, (0.5, 0.5))[0] for n in range(51)]
        self.assertEqual(widths, sorted(widths, reverse=True))

    def test_a_zoom_heads_to_the_focus_as_far_as_the_safe_area_allows(self):
        left = edit.motion_box("zoom-in", 0.4, self.SIZE, (0.3, 0.5))
        right = edit.motion_box("zoom-in", 0.4, self.SIZE, (0.7, 0.5))
        self.assertLess(left[0], right[0])
        # at its limit the words fill the frame's width: there is no room to head sideways, whatever the focus
        ends = {round(edit.motion_box("zoom-in", 1.0, self.SIZE, f)[0], 6) for f in ((0, 0), (1, 1), (0.3, 0.5), (0.5, 0.5), (1, 0.2))}
        self.assertEqual(len(ends), 1)

    def test_a_pan_moves_along_its_axis_by_at_most_6_percent_sideways_and_8_up_or_down_at_a_zoom_that_leaves_room(self):
        for motion, axis, sign, most in (("pan-left", 0, -1, 0.06), ("pan-right", 0, 1, 0.06), ("pan-up", 1, -1, 0.08), ("pan-down", 1, 1, 0.08)):
            with self.subTest(motion):
                start = edit.motion_box(motion, 0.0, self.SIZE, (0.5, 0.5))
                end = edit.motion_box(motion, 1.0, self.SIZE, (0.5, 0.5))
                size = self.SIZE[axis]
                moved = (end[axis] - start[axis]) * sign
                self.assertGreater(moved, 0.03 * size)  # it moves, in the direction its name says
                self.assertLessEqual(moved, most * size + 1e-6)
                zoom = size / (end[2 + axis] - end[axis])
                self.assertLessEqual(zoom, edit.PAN_ZOOM + 1e-9)
                self.assertLess(zoom, edit.PAN_ZOOM)  # a smaller zoom than the design's 1.10, so the travel fits
                other = 1 - axis
                self.assertAlmostEqual(end[other], start[other])  # the other axis doesn't move

    def test_the_safe_area_stays_in_view_clear_of_the_signature_and_the_captions_for_every_motion_and_focus(self):
        """Where the templates put their words (SAFE_AREA, as fractions of the picture) lands, in the frame, in from the sides, below
        the signature's pill and above the captions' band, at every moment of every motion, whatever the focus (the edges included)."""
        width, height = self.SIZE
        left, top, right, bottom = edit.SAFE_AREA
        clear = edit.KEEP_CLEAR
        foci = [(x / 4.0, y / 4.0) for x in range(5) for y in range(5)]
        for motion in edit.MOTIONS:
            for focus in foci:
                for n in range(0, 41):
                    x0, y0, x1, y1 = edit.motion_box(motion, n / 40.0, self.SIZE, focus)
                    with self.subTest(motion=motion, focus=focus, n=n):
                        box_w, box_h = (x1 - x0) / width, (y1 - y0) / height
                        mapped = ((left - x0 / width) / box_w, (top - y0 / height) / box_h, (right - x0 / width) / box_w, (bottom - y0 / height) / box_h)
                        self.assertGreaterEqual(mapped[0], clear[0] - 1e-9)
                        self.assertGreaterEqual(mapped[1], clear[1] - 1e-9)
                        self.assertLessEqual(mapped[2], clear[2] + 1e-9)
                        self.assertLessEqual(mapped[3], clear[3] + 1e-9)

    def test_the_keep_clear_lines_are_the_frames_signature_and_caption_places(self):
        # the pill is drawn at 56 to about 117 px of 1920, the captions' band starts at 1614 px (two lines, the largest size)
        self.assertLess(117 / 1920.0, edit.KEEP_CLEAR[1])
        self.assertGreater(1614 / 1920.0, edit.KEEP_CLEAR[3])
        # and the cards' templates keep their words inside SAFE_AREA
        for kind in ("title", "fact", "list", "quote", "sources"):
            with open(os.path.join(EXPLAINER, "..", "assets", "templates", "card-%s.json" % kind), encoding="utf-8") as f:
                template = json.load(f)
            for text in template["texts"]:
                x0, y0, x1, y1 = text["box"]
                self.assertGreaterEqual(x0, edit.SAFE_AREA[0] - 1e-9, (kind, text["slot"]))
                self.assertGreaterEqual(y0, edit.SAFE_AREA[1] - 1e-9, (kind, text["slot"]))
                self.assertLessEqual(x1, edit.SAFE_AREA[2] + 1e-9, (kind, text["slot"]))
                self.assertLessEqual(y1, edit.SAFE_AREA[3] + 1e-9, (kind, text["slot"]))

    def test_the_box_always_stays_inside_the_picture_and_keeps_its_proportions(self):
        for motion in edit.MOTIONS:
            for focus in ((0.0, 0.0), (1.0, 1.0), (0.5, 0.5), (0.1, 0.9), (0.9, 0.1)):
                for n in range(0, 21):
                    x0, y0, x1, y1 = edit.motion_box(motion, n / 20, self.SIZE, focus)
                    with self.subTest(motion=motion, focus=focus, n=n):
                        self.assertGreaterEqual(x0, -1e-9)
                        self.assertGreaterEqual(y0, -1e-9)
                        self.assertLessEqual(x1, self.SIZE[0] + 1e-9)
                        self.assertLessEqual(y1, self.SIZE[1] + 1e-9)
                        self.assertAlmostEqual((x1 - x0) / (y1 - y0), self.SIZE[0] / self.SIZE[1], places=6)

    def test_a_pan_is_smooth_from_one_frame_to_the_next(self):
        steps = [edit.motion_box("pan-right", n / 209, self.SIZE, (0.5, 0.5))[0] for n in range(210)]
        deltas = [b - a for a, b in zip(steps, steps[1:])]
        self.assertTrue(all(d >= 0 for d in deltas))
        self.assertLess(max(deltas), 2.0)  # under two pixels a frame: no jumps
        self.assertTrue(any(0 < d < 1 for d in deltas))  # and finer than a pixel: the box is resampled at a fraction of one


class Captions(Folder):
    def cues(self, cues):
        return self.json_file("captions.json", {"cues": cues})

    def test_a_captions_file_is_read_in_order(self):
        found = edit.read_captions(self.cues([{"start": 0.3, "end": 1.2, "lines": [" One "]}, {"start": 1.2, "end": 9.0, "lines": ["a", "b"]}]), 5.0)
        self.assertEqual(found[0]["lines"], ["One"])
        self.assertEqual(found[1]["end"], 5.0)  # held inside the narration

    def test_every_wrong_cue_is_named(self):
        cases = {
            "three lines": [{"start": 0, "end": 1, "lines": ["a", "b", "c"]}], "no lines": [{"start": 0, "end": 1, "lines": []}],
            "end first": [{"start": 2, "end": 1, "lines": ["a"]}], "out of order": [{"start": 3, "end": 4, "lines": ["a"]}, {"start": 1, "end": 2, "lines": ["b"]}],
            "text type": [{"start": 0, "end": 1, "lines": [3]}], "too wide": [{"start": 0, "end": 1, "lines": ["x" * 61]}],
            "after the end": [{"start": 9, "end": 10, "lines": ["a"]}], "not a cue": ["a"], "no times": [{"lines": ["a"]}],
        }
        for label, cues in cases.items():
            with self.subTest(label):
                with self.assertRaises(edit.InputError):
                    edit.read_captions(self.cues(cues), 5.0)
        with self.assertRaises(edit.InputError):
            edit.read_captions(self.json_file("x.json", {"words": []}), 5.0)
        with self.assertRaises(edit.InputError):
            edit.read_captions(self.json_file("y.json", [1]), 5.0)


class Exits(Folder):
    """The command's refusals, before any picture is drawn: they need no Pillow and no FFmpeg."""

    def setup_files(self, seconds=10.0, codec=b"mp4a"):
        self.picture("cards", "a.png")
        plan = self.json_file("plan.json", {"scenes": [{"image": "cards/a.png", "seconds": 3}, {"image": "cards/a.png", "seconds": 3}]})
        audio = self.m4a("n.m4a", seconds, codec)
        captions = self.json_file("captions.json", {"cues": [{"start": 0.3, "end": 1.2, "lines": ["Hello"]}]})
        return ["--plan", plan, "--narration", audio, "--captions", captions, "--out", self.path("out.mp4")]

    def test_a_narration_over_58_seconds_is_refused_before_anything_is_drawn(self):
        code, line, _err = run_main(edit, self.setup_files(58.5))
        self.assertEqual(code, 2)
        self.assertIn("58.0 s", line["problem"])
        self.assertIn("run voice.py again", line["problem"])
        self.assertFalse(os.path.exists(self.path("out.mp4")))

    def test_a_narration_that_is_not_aac_in_an_m4a_is_refused(self):
        code, line, _err = run_main(edit, self.setup_files(10.0, codec=b"alac"))
        self.assertEqual(code, 2)
        self.assertIn("AAC", line["problem"])
        self.touch("not-audio.m4a", data=b"nope")
        args = self.setup_files(10.0)
        args[args.index("--narration") + 1] = self.path("not-audio.m4a")
        code, line, _err = run_main(edit, args)
        self.assertEqual(code, 2)

    def test_scenes_that_leave_less_than_a_second_for_the_last_are_refused(self):
        args = self.setup_files(3.5)  # the first scene takes 3 s of it
        code, line, _err = run_main(edit, args)
        self.assertEqual(code, 2)
        self.assertIn("shorten the earlier scenes", line["problem"])

    def test_the_output_is_an_mp4_never_an_input_in_a_folder_that_exists(self):
        args = self.setup_files()
        for out, why in ((self.path("out.mov"), ".mp4"), (self.path("nope", "out.mp4"), "folder")):
            changed = list(args)
            changed[changed.index("--out") + 1] = out
            with self.subTest(out):
                code, line, _err = run_main(edit, changed)
                self.assertEqual(code, 2)
                self.assertIn(why, line["problem"])
        # an .mp4 narration (the video's own sound track may be one) is never overwritten by the output
        narration = self.m4a("same.mp4", 10.0)
        changed = list(args)
        changed[changed.index("--narration") + 1] = narration
        changed[changed.index("--out") + 1] = narration
        code, line, _err = run_main(edit, changed)
        self.assertEqual(code, 2)
        self.assertIn("overwrite", line["problem"])

    def test_still_needs_a_picture_name_and_a_time_inside_the_video(self):
        args = self.setup_files(10.0)
        code, line, _err = run_main(edit, args + ["--still", self.path("s.gif")])
        self.assertEqual((code, ".png" in line["problem"]), (2, True))
        code, line, _err = run_main(edit, args + ["--still", self.path("s.png"), "--still-at", "30"])
        self.assertEqual(code, 2)
        self.assertIn("after the end", line["problem"])
        code, line, _err = run_main(edit, args + ["--still", self.path("s.png"), "--still-at", "-1"])
        self.assertEqual(code, 2)

    def test_a_playlist_renamed_mp4_is_exit_2_with_the_json_line(self):
        args = self.setup_files(10.0)
        self.touch("clip.mp4", data=b"#EXTM3U\n#EXTINF:1,\nhttp://example.com/a.ts\n")
        self.json_file("plan.json", {"scenes": [{"image": "cards/a.png", "seconds": 3}, {"clip": "clip.mp4", "seconds": 3}]})
        with mock.patch.object(media.subprocess, "Popen") as popen:
            code, line, _err = run_main(edit, args)
        self.assertEqual(code, 2)
        self.assertIn("clip.mp4", line["problem"])
        popen.assert_not_called()  # FFmpeg was never started

    def test_a_longer_scene_never_reads_a_clip_past_its_trim(self):
        scene = {"kind": "clip", "path": "/x/clip.mp4", "trim": (2.0, 4.5), "seconds": 9.0, "motion": "still", "focus": (0.5, 0.5), "fit": "cover", "text": None}
        seen = {}

        def fake_decode(ff, path, width, height, fps, start, length):
            seen.update(start=start, length=length)
            return iter(())

        with mock.patch.object(media, "decode_clip", fake_decode):
            clip = edit.ClipScene(scene, object())
            with self.assertRaises(edit.InputError):  # the fake yields no frame
                clip.frame(0, 10)
        self.assertEqual((seen["start"], seen["length"]), (2.0, 2.5))  # out - in, not the scene's 9 s
        scene = dict(scene, trim=None, seconds=3.0)
        with mock.patch.object(media, "decode_clip", fake_decode):
            with self.assertRaises(edit.InputError):
                edit.ClipScene(scene, object()).frame(0, 10)
        self.assertEqual((seen["start"], seen["length"]), (None, 3.0))

    def test_a_wrong_command_line_is_exit_2_with_the_json_line(self):
        code, line, _err = run_main(edit, ["--plan"])
        self.assertEqual((code, line["ok"]), (2, False))

    def test_without_pillow_it_exits_3_and_says_how_to_install_it(self):
        with mock.patch.dict(sys.modules, {"hrizzup_draw": None}):
            code, line, _err = run_main(edit, self.setup_files(10.0))
        self.assertEqual(code, 3)
        self.assertIn("uv run scripts/edit.py", line["problem"])
        self.assertIn("--require-hashes -r scripts/edit.requirements.txt", line["problem"])

    def test_no_ffmpeg_exits_3(self):
        error = media.FfmpegError("no usable FFmpeg (the path can't be run)", 3)
        fake = type(sys)("hrizzup_draw")
        with mock.patch.dict(sys.modules, {"hrizzup_draw": fake}), mock.patch.object(media, "find_ffmpeg", mock.Mock(side_effect=error)):
            code, line, _err = run_main(edit, self.setup_files(10.0))
        self.assertEqual(code, 3)


class CardFiles(Folder):
    def test_every_kind_is_read_into_its_slots(self):
        path = self.json_file("cards.json", {"cards": [
            {"kind": "title", "title": "The air  turns severe", "kicker": "Delhi NCR", "subtitle": "A minute"},
            {"kind": "fact", "value": "450+", "text": "Readings passed 450.", "label": "Air quality"},
            {"kind": "list", "title": "Rules", "items": ["One", "Two", "Three"]},
            {"kind": "quote", "quote": "Quoted words", "by": "Someone", "name": "the-quote"},
            {"kind": "sources", "items": ["example.com/a"]},
        ]})
        found = cards.read_cards(path)
        self.assertEqual([f[0] for f in found], ["01-title", "02-fact", "03-list", "the-quote", "05-sources"])
        self.assertEqual(found[0][2], {"title": "The air turns severe", "kicker": "Delhi NCR", "subtitle": "A minute"})
        self.assertEqual(found[2][2], {"title": "Rules", "item1": "One", "item2": "Two", "item3": "Three"})
        self.assertEqual(found[4][2], {"item1": "example.com/a", "title": "Sources"})

    def test_each_rule_is_named_when_it_is_broken(self):
        cases = {
            "kind": [{"kind": "poster"}], "missing": [{"kind": "title"}], "extra field": [{"kind": "title", "title": "A", "size": 3}],
            "too long": [{"kind": "title", "title": "x" * 91}], "empty": [{"kind": "title", "title": " "}], "type": [{"kind": "title", "title": 3}],
            "control": [{"kind": "title", "title": "a\u0007"}], "items count": [{"kind": "list", "title": "A", "items": []}],
            "items many": [{"kind": "list", "title": "A", "items": ["a"] * 5}], "items type": [{"kind": "list", "title": "A", "items": "abc"}],
            "name": [{"kind": "title", "title": "A", "name": "Bad Name"}],
            "duplicate": [{"kind": "title", "title": "A", "name": "same"}, {"kind": "title", "title": "B", "name": "same"}],
            "not a card": ["x"],
        }
        for label, found in cases.items():
            with self.subTest(label):
                with self.assertRaises(cards.InputError):
                    cards.read_cards(self.json_file("c.json", {"cards": found}))
        for document in ({}, {"cards": []}, {"cards": {}}, {"cards": [], "x": 1}, []):
            with self.assertRaises(cards.InputError):
                cards.read_cards(self.json_file("d.json", document))

    def test_the_command_refuses_bad_input_with_the_json_line(self):
        code, line, _err = run_main(cards, ["--cards", self.path("none.json"), "--out-dir", self.path("out")])
        self.assertEqual((code, line["ok"]), (2, False))
        self.assertFalse(os.path.exists(self.path("out")))
        path = self.json_file("c.json", {"cards": [{"kind": "title", "title": "A"}]})
        self.touch("afile")
        code, line, _err = run_main(cards, ["--cards", path, "--out-dir", self.path("afile")])
        self.assertEqual(code, 2)
        with mock.patch.dict(sys.modules, {"hrizzup_draw": None}):
            code, line, _err = run_main(cards, ["--cards", path, "--out-dir", self.path("out")])
        self.assertEqual(code, 3)
        self.assertIn("uv run scripts/cards.py", line["problem"])

    def test_the_templates_leave_the_bottom_fifth_free_for_the_captions(self):
        for kind in cards.KINDS:
            with open(os.path.join(EXPLAINER, "..", "assets", "templates", "card-%s.json" % kind), encoding="utf-8") as f:
                template = json.load(f)
            self.assertEqual(template["sizes"], [[1080, 1920]])
            self.assertIsNone(template["signature"], "the signature is drawn on every frame by edit.py, not on the card")
            for text in template["texts"]:
                self.assertLessEqual(text["box"][3], 0.8, (kind, text["slot"]))  # the captions sit in the last fifth
                self.assertGreaterEqual(text["box"][1], 0.1, (kind, text["slot"]))  # and the signature at the very top


class Stills(Folder):
    def test_sizes_texts_and_focus(self):
        self.assertEqual(still.parse_size("1080x1920"), (1080, 1920))
        self.assertEqual(still.parse_size("1080X1080"), (1080, 1080))
        for bad in ("1080x1350", "1920x1080", "x", "1080"):
            with self.assertRaises(still.InputError):
                still.parse_size(bad)
        self.assertEqual(still.parse_focus("0.5,0.2"), (0.5, 0.2))
        for bad in ("1.5,0", "a,b", "0.5"):
            with self.assertRaises(still.InputError):
                still.parse_focus(bad)
        self.assertEqual(still.clean_text("  A   title ", "--title", 120), "A title")
        for bad in ("", "  ", "x" * 121, "a\u0007b"):
            with self.assertRaises(still.InputError):
                still.clean_text(bad, "--title", 120)

    def test_the_command_refuses_bad_input_with_the_json_line(self):
        out = self.path("s.png")
        for argv, why in ((["--title", "A", "--size", "800x800", "--out", out], "--size"), (["--title", " ", "--out", out], "empty"),
                          (["--title", "A", "--out", self.path("s.gif")], ".png"), (["--title", "A", "--out", self.path("no", "s.png")], "folder"),
                          (["--title", "A", "--image", out, "--out", out], "overwrite"), (["--out", out], "--title")):
            with self.subTest(argv):
                code, line, _err = run_main(still, argv)
                self.assertEqual((code, line["ok"]), (2, False))
                self.assertIn(why, line["problem"])
        with mock.patch.dict(sys.modules, {"hrizzup_draw": None}):
            code, line, _err = run_main(still, ["--title", "A", "--out", out])
        self.assertEqual(code, 3)
        self.assertIn("uv run scripts/still.py", line["problem"])

    def test_the_two_templates_are_a_videos_and_an_audios_still(self):
        self.assertEqual(still.SIZES, {(1080, 1920): "still-tall", (1080, 1080): "still-square"})
        for name in still.SIZES.values():
            with open(os.path.join(SHARED, "..", "assets", "templates", name + ".json"), encoding="utf-8") as f:
                template = json.load(f)
            self.assertEqual({t["slot"] for t in template["texts"]}, {"title", "subtitle"})
            self.assertIsNotNone(template["signature"])


# ---------------------------------------------------------------------------------------------
# Where the packages are: real pictures and a real video
# ---------------------------------------------------------------------------------------------

class UsesTheExplainersDrawingModule(Folder):
    """The scripts import `hrizzup_draw` by name, inside a function, and whichever copy another test module imported first stays in
    `sys.modules` (the timeline's holds no Anton, which the cards and stills need): these tests run with the explainer's own."""

    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location("hrizzup_draw", os.path.join(EXPLAINER, "hrizzup_draw.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        patcher = mock.patch.dict(sys.modules, {"hrizzup_draw": module})
        patcher.start()
        self.addCleanup(patcher.stop)


@unittest.skipUnless(have("PIL", "fontTools"), "needs Pillow and fontTools")
class Drawing(UsesTheExplainersDrawingModule):
    STYLE = {"signature": "Illustrative sample"}

    def style(self):
        return self.json_file("style.json", self.STYLE)

    def test_every_card_kind_is_drawn_at_1080_by_1920_and_the_json_line_says_so(self):
        path = self.json_file("cards.json", {"cards": [
            {"kind": "title", "title": "The air turns severe", "kicker": "Delhi NCR", "subtitle": "An illustrative minute"},
            {"kind": "fact", "value": "450+", "text": "Readings passed 450 before dawn on Monday.", "label": "Air quality"},
            {"kind": "list", "title": "The rules", "items": ["Building work stops", "Diesel trucks kept out", "Work from home where you can"]},
            {"kind": "quote", "quote": "Only Delhi's primary schools moved online.", "by": "The correction"},
            {"kind": "sources", "items": ["example.com/sources/one", "example.com/sources/two"]},
        ]})
        code, line, _err = run_main(cards, ["--cards", path, "--out-dir", self.path("cards"), "--style", self.style()])
        self.assertEqual(code, 0, line)
        self.assertEqual([os.path.basename(o["path"]) for o in line["outputs"]],
                         ["01-title.png", "02-fact.png", "03-list.png", "04-quote.png", "05-sources.png"])
        for output in line["outputs"]:
            self.assertEqual((output["width"], output["height"]), (1080, 1920))
            info = media.inspect(output["path"])
            self.assertEqual(media.problems(info, "image", budget=False), [])

    def test_a_chart_shaped_picture_keeps_its_edges_by_default_and_loses_them_only_when_cover_is_asked_for(self):
        from PIL import Image

        picture = Image.new("RGB", (1080, 1350), (240, 240, 240))
        for x in range(24):
            for y in range(1350):
                picture.putpixel((x, y), (200, 30, 30))  # a red strip at the left edge: the first letters of a line of words
                picture.putpixel((1079 - x, y), (30, 30, 200))  # and a blue one at the right
        self.picture("pictures", "chart.png", width=1080, height=1350)
        picture.save(self.path("pictures", "chart.png"))
        draw = sys.modules["hrizzup_draw"]
        style = draw.load_style(None)
        for fit, kept in (("", True), ("cover", False)):
            scene = {"image": "pictures/chart.png", "seconds": 4}
            if fit:
                scene["fit"] = fit
            plan = edit.read_plan(self.json_file("plan.json", {"scenes": [scene]}))["scenes"][0]
            frame = edit.ImageScene(plan, style, draw).frame(0, 1)
            self.assertEqual(frame.size, (1080, 1920))
            with self.subTest(fit=fit or "(not given)"):
                self.assertEqual(frame.getpixel((8, 800)) == (200, 30, 30), kept)  # the picture's own left edge is in the frame
                self.assertEqual(frame.getpixel((1071, 800)) == (30, 30, 200), kept)
                if kept:
                    self.assertEqual(plan["fit"], "contain")
                    self.assertEqual(frame.getpixel((540, 1700)), (255, 255, 255))  # the style's paper below it, where the captions go

    def test_a_text_too_long_for_its_card_exits_1_and_writes_no_card(self):
        path = self.json_file("cards.json", {"cards": [{"kind": "title", "title": "A fine title"}, {"kind": "title", "title": "W" * 90}]})
        code, line, _err = run_main(cards, ["--cards", path, "--out-dir", self.path("cards")])
        self.assertEqual(code, 1)
        self.assertIn("shorten to about", line["problem"])
        self.assertIn("02-title", line["problem"])
        self.assertEqual(os.listdir(self.path("cards")) if os.path.isdir(self.path("cards")) else [], [])

    def test_a_character_the_font_cant_draw_exits_2(self):
        path = self.json_file("cards.json", {"cards": [{"kind": "title", "title": "Smog \U0001F600"}]})
        code, line, _err = run_main(cards, ["--cards", path, "--out-dir", self.path("cards")])
        self.assertEqual(code, 2)
        self.assertIn("U+1F600", line["problem"])

    def test_a_still_in_each_size_with_and_without_a_picture(self):
        for size in ("1080x1920", "1080x1080"):
            for with_picture in (False, True):
                out = self.path("still-%s-%s.png" % (size, with_picture))
                argv = ["--title", "Delhi's air turns severe", "--subtitle", "An illustrative minute", "--size", size, "--style", self.style(), "--out", out]
                if with_picture:
                    from PIL import Image

                    Image.new("RGB", (1600, 1212), (120, 160, 200)).save(self.path("p.png"))
                    argv += ["--image", self.path("p.png"), "--focus", "0.3,0.5"]
                with self.subTest(size=size, picture=with_picture):
                    code, line, _err = run_main(still, argv)
                    self.assertEqual(code, 0, line)
                    self.assertEqual("%dx%d" % (line["outputs"][0]["width"], line["outputs"][0]["height"]), size)
                    self.assertEqual(media.problems(media.inspect(out), "image", budget=False), [])

    def test_a_still_with_a_title_too_long_exits_1_and_leaves_nothing(self):
        out = self.path("s.png")
        code, line, _err = run_main(still, ["--title", "W" * 120, "--size", "1080x1080", "--out", out])
        self.assertEqual(code, 1)
        self.assertIn("shorten to about", line["problem"])
        self.assertFalse(os.path.exists(out))


@unittest.skipUnless(have("PIL", "fontTools") and real_ffmpeg(), "needs Pillow, fontTools and an FFmpeg with libx264, aac and loudnorm")
class Videos(UsesTheExplainersDrawingModule):
    """A real video of two seconds, from pictures drawn here, through the command and read back."""

    @classmethod
    def setUpClass(cls):
        cls.ff = real_ffmpeg()
        cls.shared = tempfile.TemporaryDirectory()
        cls.wav = os.path.join(cls.shared.name, "tone.wav")
        with wave.open(cls.wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            frames = bytearray()
            for n in range(24000 * 3):
                level = 0.05 + 0.04 * math.sin(2 * math.pi * 0.7 * n / 24000)
                frames += struct.pack("<h", int(32767 * level * math.sin(2 * math.pi * 220 * n / 24000)))
            w.writeframes(bytes(frames))
        cls.narration = os.path.join(cls.shared.name, "n.m4a")
        media.loudnorm_apply(cls.ff, cls.wav, media.loudnorm_measure(cls.ff, cls.wav), cls.narration)

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def pictures(self):
        from PIL import Image

        Image.new("RGB", (1080, 1920), (200, 40, 40)).save(self.path("red.png"))
        Image.new("RGB", (1080, 1350), (40, 200, 40)).save(self.path("green.png"))
        return self.path("red.png"), self.path("green.png")

    def make(self, scenes, transition="cut", extra=()):
        self.pictures()
        plan = self.json_file("plan.json", {"scenes": scenes, "transition": transition})
        captions = self.json_file("captions.json", {"cues": [{"start": 0.3, "end": 1.4, "lines": ["First caption", "on two lines"]},
                                                              {"start": 1.5, "end": 2.6, "lines": ["Second caption"]}]})
        style = self.json_file("style.json", {"signature": "Illustrative sample"})
        out = self.path("out.mp4")
        code, line, err = run_main(edit, ["--plan", plan, "--narration", self.narration, "--captions", captions, "--out", out, "--style", style] + list(extra))
        return code, line, err, out

    def test_scenes_with_motion_and_captions_make_a_valid_video_that_ends_with_its_narration(self):
        code, line, err, out = self.make([{"image": "red.png", "seconds": 1.0, "motion": "zoom-in"},
                                          {"image": "green.png", "seconds": 1.0, "fit": "contain", "text": "A scene's text"},
                                          {"image": "red.png", "seconds": 1.0, "motion": "pan-left", "focus": [0.3, 0.5]}])
        self.assertEqual(code, 0, (line, err))
        info = media.inspect(out)
        self.assertEqual((info.kind, info.width, info.height, info.video_codec, info.audio_codec, info.faststart), ("mp4", 1080, 1920, "avc1", "mp4a", True))
        self.assertEqual(media.problems(info, "video", budget=False), [])
        self.assertAlmostEqual(info.seconds, 3.0, delta=0.12)
        self.assertEqual(line["outputs"][0]["seconds"], round(info.seconds, 3))
        self.assertTrue(all(c["ok"] for c in line["checks"]))
        self.assertFalse(os.path.exists(self.path("out.part.mp4")))
        # the narration was copied in, not made again: its loudness is the file's
        self.assertEqual(media.loudness_problems(media.loudnorm_measure(self.ff, out)), [])

    def test_a_fade_and_a_still_frame_without_its_caption(self):
        code, line, err, out = self.make([{"image": "red.png", "seconds": 1.5}, {"image": "green.png", "seconds": 1.0, "fit": "contain"}], "fade",
                                         ["--still", self.path("grab.png"), "--still-at", "0.5"])
        self.assertEqual(code, 0, (line, err))
        self.assertEqual([os.path.basename(o["path"]) for o in line["outputs"]], ["out.mp4", "grab.png"])
        grab = media.inspect(self.path("grab.png"))
        self.assertEqual((grab.width, grab.height), (1080, 1920))
        self.assertEqual(media.problems(grab, "image", budget=False), [])

    def test_a_clip_is_a_scene_with_its_sound_dropped(self):
        clip = self.path("clip.mp4")
        with media.encode_video(self.ff, clip, 128, 224, 30) as encoder:
            for n in range(45):
                encoder.write(bytes([n * 5 % 256, 90, 160]) * (128 * 224))
        code, line, err, out = self.make([{"clip": "clip.mp4", "trim": [0.2, 1.0]}, {"image": "red.png", "seconds": 1.0}])
        self.assertEqual(code, 0, (line, err))
        self.assertEqual(media.problems(media.inspect(out), "video", budget=False), [])

    def test_a_cue_with_a_character_the_font_cant_draw_exits_2_and_leaves_nothing(self):
        self.pictures()
        plan = self.json_file("plan.json", {"scenes": [{"image": "red.png", "seconds": 1.0}, {"image": "green.png", "seconds": 1.0}]})
        captions = self.json_file("captions.json", {"cues": [{"start": 0.3, "end": 1.4, "lines": ["Cost \u20b9 450"]}]})
        out = self.path("out.mp4")
        code, line, _err = run_main(edit, ["--plan", plan, "--narration", self.narration, "--captions", captions, "--out", out])
        self.assertEqual(code, 2)
        self.assertIn("U+20B9", line["problem"])
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".mp4")], [])


if __name__ == "__main__":
    unittest.main()
