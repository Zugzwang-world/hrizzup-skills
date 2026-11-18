"""voice.py's reading of its command line and its script, its chunks, its exit codes, and the model downloader it shares with captions.py.

Nothing here needs numpy, Kokoro or a network: the model's packages are stood in for, and the downloader runs against a fake
server. The voice itself is proved by the samples (the narrations in skills/audio-brief/examples and skills/explainer-video/examples).
"""

import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import types
import unittest
import urllib.error
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHARED = os.path.join(ROOT, "shared", "scripts")
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

import importlib.util  # noqa: E402

import catalogue  # noqa: E402,F401  (puts hrizzup_media in sys.modules)

media = catalogue.media


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_under_test", os.path.join(SHARED, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


voice = load("voice")
captions = load("captions")


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

    def path(self, name):
        return os.path.join(self.dir, name)

    def write(self, name, text):
        with open(self.path(name), "w", encoding="utf-8") as f:
            f.write(text)
        return self.path(name)


class Arguments(Folder):
    def args(self, *extra):
        script = self.write("script.txt", "Hello there.")
        return voice.make_parser().parse_args(["--script", script, "--out", self.path("narration.m4a")] + list(extra))

    def test_the_defaults(self):
        args = self.args()
        self.assertEqual((args.voice, args.speed, args.max_seconds, args.offline), ("af_heart", 1.0, 295, False))

    def test_every_voice_the_design_names_and_no_other(self):
        for name in ("af_heart", "af_bella", "bf_emma", "am_michael", "am_fenrir", "bm_george"):
            self.assertEqual(self.args("--voice", name).voice, name)
        with self.assertRaises(voice.InputError):
            self.args("--voice", "af_sky")

    def test_numbers_outside_their_ranges_are_bad_input(self):
        for bad in (("--speed", "0.8"), ("--speed", "1.2"), ("--max-seconds", "0"), ("--max-seconds", "296"), ("--max-seconds", "300")):
            with self.subTest(bad):
                with self.assertRaises(voice.InputError):
                    voice.check_arguments(self.args(*bad))
        voice.check_arguments(self.args("--speed", "0.85", "--max-seconds", "57.5"))
        voice.check_arguments(self.args("--speed", "1.15", "--max-seconds", "295"))

    def test_out_is_an_m4a_in_a_folder_that_exists_and_never_an_input(self):
        script = self.write("s.txt", "Hi.")
        for out, why in ((self.path("n.mp3"), ".m4a"), (self.path("nope/n.m4a"), "folder"), (script, "overwrite")):
            with self.subTest(out):
                args = voice.make_parser().parse_args(["--script", script, "--out", out])
                with self.assertRaises(voice.InputError) as caught:
                    voice.check_arguments(args)
                self.assertIn(why, str(caught.exception))
        again = self.write("again.m4a", "")
        args = voice.make_parser().parse_args(["--script", again, "--out", again])
        with self.assertRaises(voice.InputError) as caught:
            voice.check_arguments(args)
        self.assertIn("overwrite", str(caught.exception))

    def test_timings_are_never_an_input_nor_the_output(self):
        script = self.write("s.txt", "Hi.")
        for timings in (script, self.path("n.m4a")):
            args = voice.make_parser().parse_args(["--script", script, "--out", self.path("n.m4a"), "--timings", timings])
            with self.assertRaises(voice.InputError):
                voice.check_arguments(args)

    def test_a_missing_script_is_bad_input_with_the_json_line(self):
        code, line, _err = run_main(voice, ["--script", self.path("missing.txt"), "--out", self.path("n.m4a")])
        self.assertEqual(code, 2)
        self.assertFalse(line["ok"])
        self.assertIn("missing.txt", line["problem"])
        for key in ("ok", "outputs", "checks", "problem"):
            self.assertIn(key, line)

    def test_a_wrong_command_line_is_exit_2_with_the_json_line_and_help_is_exit_0(self):
        code, line, _err = run_main(voice, ["--no-such-flag"])
        self.assertEqual((code, line["ok"]), (2, False))
        with contextlib.redirect_stdout(io.StringIO()) as shown, self.assertRaises(SystemExit) as caught:
            voice.make_parser().parse_args(["--help"])
        self.assertEqual(caught.exception.code, 0)
        tail = shown.getvalue().strip().split("\n")[-3:]
        self.assertIn("voice.py", " ".join(tail))

    def test_a_script_with_a_word_the_captions_cant_show_is_bad_input(self):
        script = self.write("hindi.txt", "Fine.\n\n\u0928\u092e\u0938\u094d\u0924\u0947")
        code, line, _err = run_main(voice, ["--script", script, "--out", self.path("n.m4a")])
        self.assertEqual(code, 2)
        self.assertIn("line 3", line["problem"])


class Chunks(unittest.TestCase):
    def test_sentences_split_after_full_stops_but_not_after_abbreviations_or_initials(self):
        self.assertEqual(voice.split_sentences("One. Two! Three? Four."), ["One.", "Two!", "Three?", "Four."])
        self.assertEqual(voice.split_sentences("Dr. Rao spoke. Rs. 450 crore was spent."), ["Dr. Rao spoke.", "Rs. 450 crore was spent."])
        self.assertEqual(voice.split_sentences("J. K. Rowling wrote it. Then she slept."), ["J. K. Rowling wrote it.", "Then she slept."])
        self.assertEqual(voice.split_sentences("It said \"yes.\" Then it left."), ["It said \"yes.\"", "Then it left."])
        self.assertEqual(voice.split_sentences("No full stop here"), ["No full stop here"])

    def test_chunks_are_whole_sentences_of_about_250_characters(self):
        sentence = "This sentence is exactly sixty characters long, no more, ok."
        self.assertEqual(len(sentence), 60)
        text = " ".join([sentence] * 9)
        chunks = voice.chunk_paragraph(text)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= 250 for c in chunks))
        self.assertEqual(" ".join(chunks), text)  # nothing lost or repeated
        self.assertEqual(voice.chunk_paragraph("Short one. Short two."), ["Short one. Short two."])

    def test_a_sentence_longer_than_a_chunk_is_a_chunk_of_its_own(self):
        long = "Many " + "word " * 80 + "end."
        chunks = voice.chunk_paragraph("Before. " + long + " After.")
        self.assertEqual(chunks, ["Before.", long, "After."])

    def test_the_words_to_cut_is_enough_to_get_under_the_limit(self):
        from hrizzup_script import parse  # a sibling module in shared/scripts

        script = parse(" ".join(["word"] * 150))
        self.assertGreaterEqual(voice.words_to_cut(script, 75.0, 60.0), 30)  # 15 s of 75 s is a fifth of 150 words
        self.assertLessEqual(voice.words_to_cut(script, 75.0, 60.0), 40)
        self.assertEqual(voice.words_to_cut(script, 60.1, 60.0), 3)


class FakeNumpy(types.ModuleType):
    """Enough of numpy for the code paths a test takes."""


class Exits(Folder):
    def fakes(self):
        return mock.patch.dict(sys.modules, {"numpy": types.ModuleType("numpy"), "kokoro_onnx": types.ModuleType("kokoro_onnx")})

    def ffmpeg(self):
        return mock.patch.object(media, "find_ffmpeg", lambda video=True: media.Ffmpeg("/x/ffmpeg", None, "the path", "ffmpeg version 0"))

    def test_without_the_packages_it_exits_3_and_says_how_to_install_them(self):
        script = self.write("s.txt", "Hello there.")
        with mock.patch.dict(sys.modules, {"numpy": None, "kokoro_onnx": None}):
            code, line, _err = run_main(voice, ["--script", script, "--out", self.path("n.m4a")])
        self.assertEqual(code, 3)
        self.assertIn("uv run scripts/voice.py", line["problem"])
        self.assertIn("--require-hashes -r scripts/voice.requirements.txt", line["problem"])

    def test_offline_with_no_model_exits_3_and_says_what_to_do(self):
        script = self.write("s.txt", "Hello there.")
        empty = os.path.join(self.dir, "models")
        os.mkdir(empty)
        with self.fakes(), self.ffmpeg(), mock.patch.dict(os.environ, {"HRIZZUP_MODELS_DIR": empty}):
            code, line, _err = run_main(voice, ["--script", script, "--out", self.path("n.m4a"), "--offline"])
        self.assertEqual(code, 3)
        for words in ("--offline", "kokoro-v1.0.int8.onnx", "voices-v1.0.bin", "without --offline", "MiB"):
            self.assertIn(words, line["problem"])
        self.assertEqual(os.listdir(empty), [])  # nothing was fetched or made

    def test_a_narration_over_the_limit_exits_1_and_says_how_many_words_to_cut(self):
        script = self.write("s.txt", " ".join(["word"] * 150))

        class Long:
            def __len__(self):
                return 70 * voice.SAMPLE_RATE

        with self.fakes(), self.ffmpeg(), mock.patch.object(voice, "ensure_model", lambda *a, **k: self.dir), \
                mock.patch.object(voice, "speak", lambda *a, **k: (Long(), {})):
            code, line, _err = run_main(voice, ["--script", script, "--out", self.path("n.m4a"), "--max-seconds", "57"])
        self.assertEqual(code, 1)
        self.assertRegex(line["problem"], r"70\.0 s, over --max-seconds 57\.0: cut about \d+ words")
        self.assertFalse(line["checks"][0]["ok"])
        self.assertFalse(os.path.exists(self.path("n.m4a")))  # nothing left behind

    def test_no_ffmpeg_exits_3_before_anything_is_fetched(self):
        script = self.write("s.txt", "Hello there.")
        error = media.FfmpegError("no usable FFmpeg (the path can't be run)", 3)
        with self.fakes(), mock.patch.object(media, "find_ffmpeg", mock.Mock(side_effect=error)):
            code, line, _err = run_main(voice, ["--script", script, "--out", self.path("n.m4a")])
        self.assertEqual(code, 3)
        self.assertIn("no usable FFmpeg", line["problem"])

    def test_a_mistake_in_the_command_still_ends_in_the_json_line(self):
        script = self.write("s.txt", "Hello there.")
        with self.fakes(), self.ffmpeg(), mock.patch.object(voice, "ensure_model", mock.Mock(side_effect=ZeroDivisionError("boom"))):
            code, line, _err = run_main(voice, ["--script", script, "--out", self.path("n.m4a")])
        self.assertEqual(code, 1)
        self.assertIn("mistake in the kit", line["problem"])


# ---------------------------------------------------------------------------------------------
# The model downloader, in voice.py and captions.py
# ---------------------------------------------------------------------------------------------

class Response:
    """What `urlopen` gives back, for a fake server."""

    def __init__(self, body, status=200, headers=None, stop_after=None, fail_with=None):
        self.body, self.status, self.headers = body, status, dict(headers or {})
        self.position, self.stop_after, self.fail_with = 0, stop_after, fail_with
        self.headers.setdefault("Content-Length", str(len(body)))

    class _Headers(dict):
        def get(self, name, default=None):
            return dict.get(self, name, default)

    def __enter__(self):
        self.headers = self._Headers(self.headers)
        return self

    def __exit__(self, *exc):
        return False

    def read(self, count):
        limit = len(self.body) if self.stop_after is None else self.stop_after
        if self.position >= limit:
            if self.fail_with and self.position < len(self.body):
                raise self.fail_with
            return b""
        chunk = self.body[self.position:min(self.position + count, limit)]
        self.position += len(chunk)
        return chunk


class Server:
    """A stand-in for `_open(url, start)`: answers from a list of canned behaviours, one for each call, and records what was asked."""

    def __init__(self, body, plan):
        self.body, self.plan, self.calls = body, list(plan), []

    def __call__(self, url, start=0):
        self.calls.append((url, start))
        step = self.plan.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(self.body, start)


def whole(body, start):
    return Response(body)


def short(fraction):
    def respond(body, start):
        return Response(body, stop_after=int(len(body) * fraction))
    return respond


def ranged(body, start):
    rest = body[start:]
    return Response(rest, status=206, headers={"Content-Range": "bytes %d-%d/%d" % (start, len(body) - 1, len(body))})


class Downloads(Folder):
    BODY = bytes(range(256)) * 20  # 5,120 bytes: more than one read of the test's size
    DIGEST = hashlib.sha256(BODY).hexdigest()
    FILES = ((DIGEST, len(BODY), "model.bin"),)
    BASE = "https://models.example.com/a/b/"

    def setUp(self):
        super().setUp()
        self.sleeps = []
        self.patches = [mock.patch.dict(os.environ, {"HRIZZUP_MODELS_DIR": self.dir})]
        for module in (voice, captions):
            self.patches.append(mock.patch.object(module, "READ_BYTES", 1000))
            self.patches.append(mock.patch.object(module.time, "sleep", self.sleeps.append))
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.log = []

    def ensure(self, module, server, offline=False, files=None):
        with mock.patch.object(module, "_open", server):
            return module.ensure_model("m", self.BASE, files or self.FILES, offline, self.log.append)

    def model_path(self, name="model.bin"):
        return os.path.join(self.dir, "m", name)

    def parts(self):
        """Every part file in the models folder (a download in progress, or left behind)."""
        folder = os.path.join(self.dir, "m")
        return sorted(n for n in os.listdir(folder) if n.endswith(".part")) if os.path.isdir(folder) else []

    def both(self):
        for module in (voice, captions):
            with self.subTest(module=module.__name__):
                yield module

    def test_a_good_download_is_kept_checked_and_never_fetched_twice(self):
        for module in self.both():
            server = Server(self.BODY, [whole])
            folder = self.ensure(module, server)
            self.assertEqual(folder, os.path.join(self.dir, "m"))
            with open(self.model_path(), "rb") as f:
                self.assertEqual(f.read(), self.BODY)
            self.assertEqual(sorted(os.listdir(folder)), ["model.bin"])  # no .part left
            self.assertEqual(server.calls, [(self.BASE + "model.bin", 0)])
            self.ensure(module, Server(self.BODY, []))  # a second run asks for nothing (the fake would fail)
            os.remove(self.model_path())
            self.log.clear()

    def test_the_wrong_file_is_refused_deleted_and_not_tried_again(self):
        for module in self.both():
            wrong = b"x" * len(self.BODY)
            server = Server(wrong, [whole, whole, whole])
            with self.assertRaises(module.ModelError) as caught:
                self.ensure(module, server)
            self.assertIn("SHA-256", str(caught.exception))
            self.assertEqual(len(server.calls), 1)  # the file has changed: another try would get the same
            self.assertFalse(os.path.exists(self.model_path()))
            self.assertEqual(self.parts(), [])  # no part file is left behind

    def test_a_file_longer_than_expected_or_with_another_stated_size_is_refused(self):
        for module in self.both():
            for body, headers in ((self.BODY + b"extra", {"Content-Length": None}), (self.BODY[:-1], {})):
                def respond(_body, _start, body=body, headers=headers):
                    r = Response(body)
                    if headers.get("Content-Length", "x") is None:
                        del r.headers["Content-Length"]
                    return r
                with self.assertRaises(module.ModelError):
                    self.ensure(module, Server(body, [respond]))
                self.assertEqual(os.listdir(os.path.join(self.dir, "m")) if os.path.isdir(os.path.join(self.dir, "m")) else [], [])

    def test_a_download_that_stops_short_carries_on_from_where_it_stopped(self):
        for module in self.both():
            server = Server(self.BODY, [short(0.4), ranged])
            self.ensure(module, server)
            with open(self.model_path(), "rb") as f:
                self.assertEqual(f.read(), self.BODY)
            self.assertEqual(server.calls[0][1], 0)
            self.assertGreater(server.calls[1][1], 0)  # the second try asked for a range
            self.assertEqual(self.sleeps[-1:], [5])
            os.remove(self.model_path())
            self.sleeps.clear()

    def test_a_server_that_ignores_the_range_sends_the_file_again_from_the_start(self):
        for module in self.both():
            server = Server(self.BODY, [short(0.5), whole])
            self.ensure(module, server)
            with open(self.model_path(), "rb") as f:
                self.assertEqual(f.read(), self.BODY)
            os.remove(self.model_path())

    def test_a_resumed_file_that_does_not_check_out_is_fetched_again_from_the_start(self):
        for module in self.both():
            def bad_range(body, start):
                rest = bytes(len(body) - start)  # the right length, wrong bytes
                return Response(rest, status=206, headers={"Content-Range": "bytes %d-%d/%d" % (start, len(body) - 1, len(body))})
            server = Server(self.BODY, [short(0.4), bad_range, whole])
            self.ensure(module, server)
            with open(self.model_path(), "rb") as f:
                self.assertEqual(f.read(), self.BODY)
            self.assertEqual(server.calls[-1][1], 0)
            os.remove(self.model_path())

    def test_server_errors_are_retried_after_5_then_20_seconds_and_three_tries_then_stop(self):
        for module in self.both():
            error = urllib.error.HTTPError("https://x/", 503, "Service Unavailable", {}, None)
            self.sleeps.clear()
            self.ensure(module, Server(self.BODY, [error, error, whole]))
            self.assertEqual(self.sleeps, [5, 20])
            os.remove(self.model_path())
            self.sleeps.clear()
            with self.assertRaises(module.ModelError) as caught:
                self.ensure(module, Server(self.BODY, [error, error, error, whole]))
            self.assertIn("after 3 tries", str(caught.exception))
            self.assertEqual(self.sleeps, [5, 20])
            self.assertEqual(self.parts(), [])

    def test_a_network_failure_is_retried_too(self):
        for module in self.both():
            self.ensure(module, Server(self.BODY, [urllib.error.URLError("no route"), TimeoutError("timed out"), whole]))
            os.remove(self.model_path())

    def test_a_missing_address_is_not_retried(self):
        for module in self.both():
            error = urllib.error.HTTPError("https://x/", 404, "Not Found", {}, None)
            server = Server(self.BODY, [error, whole])
            with self.assertRaises(module.ModelError) as caught:
                self.ensure(module, server)
            self.assertIn("404", str(caught.exception))
            self.assertEqual(len(server.calls), 1)

    def test_only_https_is_fetched_and_a_redirect_to_http_is_refused(self):
        for module in self.both():
            with self.assertRaises(module.ModelError):
                module._open("http://models.example.com/x")
            handler = module._HttpsOnly()
            with self.assertRaises(module.ModelError) as caught:
                handler.redirect_request(mock.Mock(), None, 302, "Found", {}, "http://elsewhere.example.com/x?token=1")
            self.assertNotIn("token=1", str(caught.exception))  # a query string is never echoed

    def test_offline_never_asks_the_network_and_says_what_to_do(self):
        for module in self.both():
            server = Server(self.BODY, [whole])
            with self.assertRaises(module.ModelError) as caught:
                self.ensure(module, server, offline=True)
            for words in ("--offline", "model.bin", "without --offline", self.dir):
                self.assertIn(words, str(caught.exception))
            self.assertEqual(server.calls, [])
            self.assertFalse(os.path.exists(os.path.join(self.dir, "m")))  # not even the folder is made

    def test_offline_uses_a_model_that_is_already_there_and_checks_it(self):
        for module in self.both():
            self.ensure(module, Server(self.BODY, [whole]))
            self.assertEqual(self.ensure(module, Server(self.BODY, []), offline=True), os.path.join(self.dir, "m"))
            with open(self.model_path(), "r+b") as f:  # damaged: the right size, one byte different
                f.seek(10)
                f.write(b"\xff")
            with self.assertRaises(module.ModelError) as caught:
                self.ensure(module, Server(self.BODY, []), offline=True)
            self.assertIn("missing or damaged", str(caught.exception))
            self.ensure(module, Server(self.BODY, [whole]))  # online, a damaged file is fetched again
            with open(self.model_path(), "rb") as f:
                self.assertEqual(f.read(), self.BODY)
            os.remove(self.model_path())

    def test_a_part_left_by_another_run_is_not_trusted_and_not_touched(self):
        for module in self.both():
            os.makedirs(os.path.join(self.dir, "m"), exist_ok=True)
            with open(self.model_path() + ".part", "wb") as f:  # what an older run, or one going on now, has under the old fixed name
                f.write(b"junk from another run")
            server = Server(self.BODY, [whole])
            self.ensure(module, server)
            self.assertEqual(server.calls[0][1], 0)  # it started from nothing
            with open(self.model_path(), "rb") as f:
                self.assertEqual(f.read(), self.BODY)
            with open(self.model_path() + ".part", "rb") as f:
                self.assertEqual(f.read(), b"junk from another run")  # and never wrote to, resumed from or deleted another run's file
            os.remove(self.model_path())
            os.remove(self.model_path() + ".part")

    def test_every_download_writes_a_part_file_of_its_own_so_two_first_runs_never_share_one(self):
        for module in self.both():
            seen = []

            def watching(body, start, seen=seen):
                response = Response(body)
                real_read = response.read

                def read(count):
                    seen.append(self.parts())  # what part files exist while the bytes arrive
                    return real_read(count)
                response.read = read
                return response

            os.makedirs(os.path.join(self.dir, "m"), exist_ok=True)
            self.ensure(module, Server(self.BODY, [watching]))
            first = seen[0]
            os.remove(self.model_path())
            seen2 = []
            self.ensure(module, Server(self.BODY, [lambda body, start: watching(body, start, seen2)]))
            self.assertEqual(len(first), 1)
            self.assertNotEqual(first[0], "model.bin.part")  # not a fixed name two runs would share
            self.assertTrue(first[0].startswith("model.bin.") and first[0].endswith(".part"))
            self.assertNotEqual(first, seen2[0])  # a different one each time
            self.assertEqual(self.parts(), [])
            os.remove(self.model_path())

    def test_a_file_replaced_by_another_run_during_the_download_is_caught_before_the_folder_is_given_back(self):
        for module in self.both():
            real_replace = os.replace

            def replace_then_corrupt(source, target):
                real_replace(source, target)
                with open(target, "r+b") as f:  # another run wrote a bad file over it
                    f.seek(5)
                    f.write(b"\xff\xfe")

            with mock.patch.object(module.os, "replace", replace_then_corrupt):
                with self.assertRaises(module.ModelError) as caught:
                    self.ensure(module, Server(self.BODY, [whole]))
            self.assertIn("doesn't check out", str(caught.exception))
            self.assertIn("run the command again", str(caught.exception))
            os.remove(self.model_path())

    def test_every_file_of_a_model_is_checked_again_after_the_downloads(self):
        body2 = b"second file" * 50
        files = ((self.DIGEST, len(self.BODY), "model.bin"), (hashlib.sha256(body2).hexdigest(), len(body2), "other.bin"))
        for module in self.both():
            checked = []
            real = module._is_good

            def spy(path, digest, size, checked=checked, real=real):
                checked.append(os.path.basename(path))
                return real(path, digest, size)

            server = Server(self.BODY, [whole, lambda b, st: Response(body2)])
            with mock.patch.object(module, "_is_good", spy):
                self.ensure(module, server, files=files)
            self.assertEqual(checked[:2], ["model.bin", "other.bin"])  # what was wanted, before
            self.assertEqual(checked[2:], ["model.bin", "other.bin"])  # and every file again, after
            for name in ("model.bin", "other.bin"):
                os.remove(self.model_path(name))

    def test_where_models_are_kept(self):
        for module in self.both():
            with mock.patch.dict(os.environ, {"HRIZZUP_MODELS_DIR": "/somewhere/models"}):
                self.assertEqual(module.models_root(), "/somewhere/models")
            with mock.patch.dict(os.environ, {"HRIZZUP_MODELS_DIR": "", "XDG_CACHE_HOME": "/cache"}):
                self.assertEqual(module.models_root(), os.path.join("/cache", "hrizzup-skills", "models"))
            with mock.patch.dict(os.environ, {"HRIZZUP_MODELS_DIR": "", "XDG_CACHE_HOME": ""}):
                self.assertEqual(module.models_root(), os.path.join(os.path.expanduser("~"), ".cache", "hrizzup-skills", "models"))


class TheTwoCopies(unittest.TestCase):
    """The downloader is in voice.py and captions.py (the repository's check lets only these two scripts, and check_links.py, use the
    network, and `hrizzup_media` is copied into every skill): the two copies must stay the same."""

    START, END = "# ---- the model downloader", "# ---- end of the model downloader ----"

    def block(self, name):
        with open(os.path.join(SHARED, name + ".py"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.count(self.START), 1, name)
        self.assertEqual(text.count(self.END), 1, name)
        return text[text.index(self.START):text.index(self.END) + len(self.END)]

    def test_the_blocks_are_identical(self):
        self.assertEqual(self.block("voice"), self.block("captions"))

    def test_the_block_only_uses_what_the_scripts_import_at_their_top(self):
        for name in ("voice", "captions"):
            with open(os.path.join(SHARED, name + ".py"), encoding="utf-8") as f:
                text = f.read()
            top = text[:text.index(self.START)]
            for module in ("hashlib", "http.client", "os", "tempfile", "time", "urllib.error", "urllib.request"):
                self.assertRegex(top, r"(?m)^import %s$" % re.escape(module), (name, module))

    def test_no_script_is_left_with_a_placeholder(self):
        for name in ("voice", "captions"):
            with open(os.path.join(SHARED, name + ".py"), encoding="utf-8") as f:
                self.assertNotIn("@@BLOCK@@", f.read())


class TheModelsAreTheDesigns(unittest.TestCase):
    """The sizes, digests, files and addresses are design 10's table, which was verified against each source's own listing."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "docs", "design.md"), encoding="utf-8") as f:
            text = f.read()
        section = text[text.index("## 10. Models"):text.index("## 11.")]
        cls.rows = re.findall(r"^\| ([^|]+) \| `([^`]+)` \| ([\d,]+) \| `([0-9a-f]{64})` \|", section, re.MULTILINE)
        cls.section = section

    def test_the_design_lists_six_files(self):
        self.assertEqual(len(self.rows), 6)

    def test_voice_has_the_kokoro_files_digest_first(self):
        designed = [(d, int(b.replace(",", "")), n) for _m, n, b, d in self.rows if n.startswith(("kokoro", "voices"))]
        self.assertEqual(list(voice.MODEL_FILES), designed)
        for entry in voice.MODEL_FILES:
            self.assertRegex(entry[0], r"^[0-9a-f]{64}$")
            self.assertIsInstance(entry[1], int)
        self.assertIn(voice.MODEL_BASE, self.section)

    def test_captions_has_the_whisper_files_digest_first_at_the_pinned_revision(self):
        designed = [(d, int(b.replace(",", "")), n) for m, n, b, d in self.rows if m.startswith("Whisper")]
        self.assertEqual(list(captions.MODEL_FILES), designed)
        self.assertEqual(len(captions.MODEL_FILES), 4)
        revision = "3d3d5dee26484f91867d81cb899cfcf72b96be6c"
        self.assertEqual(captions.MODEL_BASE, "https://huggingface.co/Systran/faster-whisper-base.en/resolve/%s/" % revision)
        self.assertIn(captions.MODEL_BASE + "<file>", self.section)
        self.assertTrue(captions.MODEL_NAME.endswith(revision[:8]))  # a folder per model and revision

    def test_a_file_name_never_holds_a_word_the_secret_check_reads_as_a_key_name_before_its_digest(self):
        # design 5, "Digests": the digest comes first, so "tokenizer.json" can't be read as the name of a key
        for module in (voice, captions):
            for digest, _size, name in module.MODEL_FILES:
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
                self.assertNotEqual(name, digest)


if __name__ == "__main__":
    unittest.main()
