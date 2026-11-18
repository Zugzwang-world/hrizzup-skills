"""tools/kits_run.py: the commands it builds, how it checks a picture, and the workflow that runs it.

The runs themselves need uv, the network and the kits' packages; they are proved by running the harness (on a Mac, and
by the "Kits on Linux" workflow after it merges). Here: the commands name real files, the uv way uses the lock and the pip
way uses the hashed requirements, a bad picture is refused, and the workflow is the one the design asks for.
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import catalogue  # noqa: E402
import kits_run  # noqa: E402
import test_media as built  # noqa: E402

EXPLAINER_SCRIPTS = os.path.join(ROOT, "skills", "explainer-video", "scripts")
SHARED_SCRIPTS = os.path.join(ROOT, "shared", "scripts")
for _folder in (EXPLAINER_SCRIPTS, SHARED_SCRIPTS):
    if _folder not in sys.path:
        sys.path.insert(0, _folder)
import importlib.util  # noqa: E402


def _load(name, folder):
    spec = importlib.util.spec_from_file_location(name + "_kits_run_test", os.path.join(folder, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


edit = _load("edit", EXPLAINER_SCRIPTS)
cards = _load("cards", EXPLAINER_SCRIPTS)
import hrizzup_script  # noqa: E402

WORKFLOW = os.path.join(ROOT, ".github", "workflows", "kits-linux.yml")


def workflow_text():
    with open(WORKFLOW, encoding="utf-8") as f:
        return f.read()


class Commands(unittest.TestCase):
    def test_every_kit_names_files_that_exist(self):
        self.assertEqual([k[0] for k in kits_run.KITS], ["timeline", "meme", "infographic"])
        for skill, script, arguments, name, sample, sizes in kits_run.KITS:
            folder = os.path.join(ROOT, "skills", skill)
            self.assertTrue(os.path.isfile(os.path.join(folder, "scripts", script)), script)
            self.assertTrue(os.path.isfile(os.path.join(folder, "scripts", script + ".lock")), script)
            self.assertTrue(os.path.isfile(os.path.join(folder, "scripts", script[:-3] + ".requirements.txt")), script)
            self.assertTrue(os.path.isfile(os.path.join(folder, "examples", sample)), sample)  # the committed sample it is compared with
            for flag, value in zip(arguments, arguments[1:]):
                if flag in ("--items", "--image", "--spec", "--style"):
                    self.assertTrue(os.path.isfile(os.path.join(folder, value)), value)  # a sample's own input
            self.assertNotIn("--out", arguments)  # the harness adds it

    def test_the_uv_way_uses_the_lock_and_the_pip_way_the_hashes(self):
        command = kits_run.uv_command("3.12", "meme.py", ["--text", "a"], "/x/meme.png")
        self.assertEqual(command[:6], ["uv", "run", "--locked", "--python", "3.12", os.path.join("scripts", "meme.py")])
        self.assertEqual(command[-2:], ["--out", "/x/meme.png"])
        make, install, run = kits_run.pip_commands("3.12", "meme.py", ["--text", "a"], "/x/meme.png", "/v")
        self.assertEqual(make[:3], ["uv", "venv", "--python"])
        self.assertIn("--seed", make)  # pip is in the environment
        self.assertIn("--require-hashes", install)
        self.assertTrue(install[-1].endswith("meme.requirements.txt"))
        self.assertTrue(run[0].startswith("/v") and run[1].endswith("meme.py"))  # that environment's own Python

    def test_the_pip_way_also_asks_pillow_about_libimagequant(self):
        command = kits_run.feature_command("/v/bin/python")
        self.assertEqual(command[:2], ["/v/bin/python", "-c"])
        self.assertIn("features.check_feature('libimagequant')", command[2])
        self.assertIn("from PIL import features", command[2])
        compile(command[2], "<feature>", "exec")  # it is valid Python

    def test_the_notices_row_says_what_was_checked_and_where_it_is_confirmed(self):
        with open(os.path.join(ROOT, "NOTICES.md"), encoding="utf-8") as f:
            rows = [line for line in f.read().split("\n") if line.startswith("| libimagequant")]
        self.assertEqual(len(rows), 1)
        self.assertIn('scope "optional"', rows[0])
        self.assertIn("absent from Pillow's macOS arm64 and Linux x86-64 wheels", rows[0])
        self.assertIn("44312350592", rows[0])  # the Linux run that printed it
        self.assertIn("check_feature('libimagequant')", rows[0])
        self.assertIn("tools/kits_run.py", rows[0])
        self.assertIn("No kit calls `quantize`", rows[0])
        self.assertIn("installed by the creator's setup", rows[0])
        self.assertNotIn("built with this", rows[0])  # the earlier, stronger claim

    def test_help_ends_with_an_example(self):
        text = kits_run.make_parser().format_help().strip().split("\n")
        tail = "\n".join(text[-4:]).lower()
        self.assertIn("example", tail)
        self.assertIn("kits_run.py", tail)

    def test_bad_arguments_exit_2(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            kits_run.main(["--out", "x", "--mode", "docker"])
        self.assertEqual(caught.exception.code, 2)


class Checking(unittest.TestCase):
    def check(self, data, name="o.png", sizes=((1080, 1350),)):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, name)
            with open(path, "wb") as f:
                f.write(data)
            return kits_run.check_output(kits_run.load_media(), path, sizes)

    def test_a_valid_picture_of_the_right_size_passes(self):
        info, problems = self.check(built.png(1080, 1350))
        self.assertEqual((info.width, info.height, problems), (1080, 1350, []))

    def test_the_wrong_size_and_a_broken_file_are_refused(self):
        _info, problems = self.check(built.png(1080, 1920))
        self.assertTrue(any("1080x1920" in p for p in problems))
        info, problems = self.check(b"this is not a picture")
        self.assertIsNone(info)
        self.assertTrue(problems)
        _info, problems = self.check(built.jpeg(1080, 1350))  # a JPEG named .png
        self.assertTrue(problems)

    def test_a_picture_over_the_repositorys_budget_is_refused(self):
        _info, problems = self.check(built.png(1080, 1350) + b"\0" * (2 * 1024 * 1024 + 1))
        self.assertTrue(any("budget" in p for p in problems))


class VoiceGroup(unittest.TestCase):
    """The voice and video group's commands, inputs and checks (the runs themselves need uv, the network and the models)."""

    def steps(self, work="/w"):
        return dict(kits_run.voice_steps(work))

    def test_every_command_names_a_script_with_its_lock_and_hashed_requirements_in_its_skills_folder(self):
        steps = self.steps()
        self.assertEqual(sorted(steps), ["audio-brief", "explainer-video"])
        self.assertEqual([s[1] for s in steps["audio-brief"]], ["voice.py", "still.py"])
        self.assertEqual([s[1] for s in steps["explainer-video"]], ["voice.py", "captions.py", "cards.py", "edit.py", "still.py"])
        for skill, found in steps.items():
            folder = os.path.join(ROOT, "skills", skill, "scripts")
            for _label, script, _arguments, _outputs in found:
                for name in (script, script + ".lock", script[:-3] + ".requirements.txt"):
                    self.assertTrue(os.path.isfile(os.path.join(folder, name)), (skill, name))

    def test_the_audio_briefs_own_sample_inputs_exist_and_every_other_path_is_under_the_output_folder(self):
        steps = self.steps("/w")
        folder = os.path.join(ROOT, "skills", "audio-brief")
        for _label, _script, arguments, _outputs in steps["audio-brief"]:
            for flag, value in zip(arguments, arguments[1:]):
                if flag in ("--script", "--style"):
                    self.assertTrue(os.path.isfile(os.path.join(folder, value)), value)  # relative: the sample's own input
                if flag in ("--out", "--timings"):
                    self.assertTrue(value.startswith("/w/audio-brief/"), value)
        for _label, _script, arguments, outputs in steps["explainer-video"]:
            for flag, value in zip(arguments, arguments[1:]):
                if flag in ("--script", "--style", "--out", "--timings", "--audio", "--captions", "--plan", "--narration", "--cards", "--out-dir"):
                    self.assertTrue(value.startswith("/w/explainer-video/"), (flag, value))
            for path, role in outputs:
                self.assertTrue(path.startswith("/w/") and role in ("audio", "image", "video"), path)

    def test_each_step_feeds_the_next_in_order(self):
        written = set()
        for skill, found in kits_run.voice_steps("/w"):
            written = set()
            for _label, script, arguments, outputs in found:
                for flag, value in zip(arguments, arguments[1:]):
                    if flag in ("--audio", "--narration", "--captions", "--timings") and skill == "explainer-video" and script != "voice.py":
                        self.assertIn(value, written, (script, flag))  # an input made by an earlier step
                written.update(v for f, v in zip(arguments, arguments[1:]) if f in ("--out", "--timings", "--srt"))

    def test_the_short_explainers_inputs_are_valid_for_the_real_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            kits_run.write_short_inputs(folder)
            self.assertEqual(sorted(os.listdir(folder)), ["cards.json", "plan.json", "script.txt", "style.json"])
            with open(os.path.join(folder, "script.txt"), encoding="utf-8") as f:
                script = hrizzup_script.parse(f.read())
            self.assertEqual(len(script.paragraphs), 2)
            self.assertTrue(15 <= len(script.shown_text().split()) <= 30)  # a few seconds of speech: about ten with the pauses
            found = cards.read_cards(os.path.join(folder, "cards.json"))
            self.assertEqual([f[0] for f in found], ["01-title", "02-fact"])  # the names the plan uses
            os.makedirs(os.path.join(folder, "cards"))
            for stem, _kind, _texts in found:
                with open(os.path.join(folder, "cards", stem + ".png"), "wb") as f:
                    f.write(built.png(1080, 1920))
            plan = edit.read_plan(os.path.join(folder, "plan.json"))
            self.assertEqual([os.path.basename(s["path"]) for s in plan["scenes"]], ["01-title.png", "02-fact.png"])
            counts, _starts, total = edit.schedule(plan["scenes"], 9.5)  # about what the narration lasts
            self.assertEqual(sum(counts), total)

    def test_every_output_is_checked_against_hrizzups_limits_and_what_the_sample_is_for(self):
        media = kits_run.load_media()
        with tempfile.TemporaryDirectory() as folder:
            def make(name, data):
                path = os.path.join(folder, name)
                with open(path, "wb") as f:
                    f.write(data)
                return path

            def m4a(seconds):
                return synthetic_m4a(seconds)

            good = make("a.m4a", m4a(61.1))
            self.assertEqual(kits_run.check_voice_output(media, good, "audio", "audio-brief", "narration")[1], [])
            self.assertTrue(kits_run.check_voice_output(media, make("short.m4a", m4a(20.0)), "audio", "audio-brief", "narration")[1])  # not a minute
            self.assertEqual(kits_run.check_voice_output(media, make("s.m4a", m4a(10.0)), "audio", "explainer-video", "narration")[1], [])
            self.assertTrue(kits_run.check_voice_output(media, make("l.m4a", m4a(40.0)), "audio", "explainer-video", "narration")[1])
            video = make("v.mp4", built.ftyp() + built.video_moov(9800) + built.mdat())
            self.assertEqual(kits_run.check_voice_output(media, video, "video", "explainer-video", "video")[1], [])
            self.assertTrue(kits_run.check_voice_output(media, make("long.mp4", built.ftyp() + built.video_moov(59000) + built.mdat()), "video", "explainer-video", "video")[1])
            self.assertEqual(kits_run.check_voice_output(media, make("sq.png", built.png(1080, 1080)), "image", "audio-brief", "still")[1], [])
            self.assertTrue(kits_run.check_voice_output(media, make("tall.png", built.png(1080, 1920)), "image", "audio-brief", "still")[1])
            self.assertEqual(kits_run.check_voice_output(media, make("c.png", built.png(1080, 1920)), "image", "explainer-video", "its cards")[1], [])
            info, found = kits_run.check_voice_output(media, make("bad.png", b"not a picture"), "image", "explainer-video", "its cards")
            self.assertIsNone(info)
            self.assertTrue(found)

    def test_a_skills_requirements_are_its_commands_each_once_in_order(self):
        steps = self.steps()
        self.assertEqual(kits_run.skill_requirements("audio-brief", steps["audio-brief"]),
                         [os.path.join("scripts", "voice.requirements.txt"), os.path.join("scripts", "still.requirements.txt")])
        names = [os.path.basename(n) for n in kits_run.skill_requirements("explainer-video", steps["explainer-video"])]
        self.assertEqual(names, ["voice.requirements.txt", "captions.requirements.txt", "cards.requirements.txt", "edit.requirements.txt", "still.requirements.txt"])

    def test_a_commands_last_line_is_read_as_json_or_not_at_all(self):
        self.assertEqual(kits_run.last_json("log\nmore log\n{\"ok\": true}\n"), {"ok": True})
        self.assertIsNone(kits_run.last_json("log\nTraceback...\nValueError: no"))
        self.assertIsNone(kits_run.last_json(""))
        self.assertIsNone(kits_run.last_json("[1, 2]"))

    def test_the_parser_offers_both_groups_and_defaults_to_the_images(self):
        parser = kits_run.make_parser()
        self.assertEqual(parser.parse_args(["--out", "x"]).group, "images")
        self.assertEqual(parser.parse_args(["--out", "x", "--group", "voice"]).group, "voice")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--out", "x", "--group", "video"])


def synthetic_m4a(seconds):
    """A synthetic .m4a with real boxes and a duration (nothing plays it)."""
    moov = built.box(b"moov", built.mvhd(1000, int(seconds * 1000)) + built.trak(b"soun", b"mp4a"))
    return built.ftyp(b"M4A ") + moov + built.mdat()


class Workflow(unittest.TestCase):
    def test_it_is_started_by_hand_and_nothing_else(self):
        text = workflow_text()
        self.assertEqual(catalogue.triggers(text), {"workflow_dispatch"})
        self.assertTrue(re.search(r"^permissions:\n  contents: read$", text, re.M))

    def test_it_follows_the_public_repository_rules(self):
        problems = []

        class Collect:
            def add(self, path, rule, message):
                problems.append((path, rule, message))

        catalogue.check_workflow(".github/workflows/kits-linux.yml", workflow_text(), Collect())
        self.assertEqual(problems, [])

    def test_the_actions_are_pinned_and_uv_itself_is_pinned(self):
        uses = catalogue.workflow_actions(workflow_text())
        names = sorted(u.split("@")[0] for u in uses)
        self.assertEqual(names, ["actions/checkout"] * 2 + ["actions/upload-artifact"] * 2 + ["astral-sh/setup-uv"] * 2)  # each job uses each once
        self.assertEqual(len(set(uses)), 3)  # at the same commits in both jobs
        self.assertTrue(all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses))
        self.assertEqual(workflow_text().count('version: "0.13.1"'), 2)  # uv itself pinned in both jobs
        # the same checkout commit as the checks'
        with open(os.path.join(ROOT, ".github", "workflows", "checks.yml"), encoding="utf-8") as f:
            checkout = [u for u in catalogue.workflow_actions(f.read()) if u.startswith("actions/checkout")][0]
        self.assertIn(checkout, uses)

    def test_it_runs_the_harness_both_ways_and_keeps_the_pictures(self):
        text = workflow_text()
        self.assertIn("python3 tools/kits_run.py --out out --mode both", text)
        self.assertIn("path: out", text)
        self.assertIn("if: always()", text)  # the pictures are kept even when a run fails

    def test_it_runs_the_whole_suite_with_the_packages_installed_even_after_a_failed_run(self):
        text = workflow_text()
        step = text[text.index("- name: Run the whole unit-test suite"):text.index("- name: Keep the pictures")]
        self.assertIn("if: always()", step)
        self.assertIn("uv run --no-project --python 3.12", step)
        self.assertIn("--with-requirements skills/infographic/scripts/infographic.requirements.txt", step)
        self.assertIn("python -m unittest discover -s tools -p 'test_*.py'", step)
        self.assertLess(text.index("kits_run.py"), text.index("unittest discover"))  # after the kits, before the artifact
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "skills", "infographic", "scripts", "infographic.requirements.txt")))

    def test_the_one_requirements_file_holds_every_package_the_other_kits_need(self):
        """The suite's single `--with-requirements` is enough only while the infographic's set covers the meme's and the timeline's."""
        def pins(path):
            found = {}
            with open(os.path.join(ROOT, "skills", path), encoding="utf-8") as f:
                for line in f:
                    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", line)
                    if match:
                        found[match.group(1).lower()] = match.group(2)
            return found

        big = pins("infographic/scripts/infographic.requirements.txt")
        self.assertTrue(big)
        for small in ("meme/scripts/meme.requirements.txt", "timeline/scripts/timeline_card.requirements.txt"):
            for name, version in pins(small).items():
                self.assertEqual(big.get(name), version, (small, name))
        for needed in ("pillow", "fonttools", "matplotlib", "numpy"):  # what the real-drawing tests import
            self.assertIn(needed, big)

    def test_the_second_job_runs_the_voice_and_video_kits_and_keeps_only_the_outputs(self):
        text = workflow_text()
        job = text[text.index("\n  voice:\n"):]
        self.assertIn("name: Voice and video kits", job)
        self.assertIn("timeout-minutes: 60", job)
        self.assertIn("python3 tools/kits_run.py --group voice --out out-voice --mode both --python 3.12", job)
        self.assertIn("path: out-voice", job)  # the models are downloaded elsewhere (a temporary folder) and never kept
        self.assertIn("name: kits-linux-voice", job)
        self.assertIn("if-no-files-found: error", job)
        self.assertLess(job.index("kits_run.py"), job.index("unittest discover"))
        self.assertLess(job.index("unittest discover"), job.index("upload-artifact"))
        for tests in ("test_edit.py", "test_media.py"):
            self.assertIn("-p '%s'" % tests, job)
        self.assertIn("--with-requirements skills/explainer-video/scripts/edit.requirements.txt", job)
        # a failed run still keeps what it made, and still runs the tests
        self.assertEqual(job.count("if: always()"), 2)

    def test_the_two_jobs_are_independent_and_both_run_on_githubs_machines(self):
        text = workflow_text()
        self.assertEqual(len(re.findall(r"^  [a-z]+:\n    name:", text, re.M)), 2)
        self.assertEqual(text.count("runs-on: ubuntu-24.04"), 2)
        self.assertNotIn("needs:", text)  # one failing doesn't stop the other
        self.assertEqual(catalogue.triggers(text), {"workflow_dispatch"})

    def test_it_is_not_a_required_check(self):
        checks = os.path.join(ROOT, ".github", "workflows", "checks.yml")
        with open(checks, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("Kits on Linux", text)
        self.assertNotIn("Image kits", text)
        self.assertNotIn("Voice and video kits", text)


if __name__ == "__main__":
    unittest.main()
