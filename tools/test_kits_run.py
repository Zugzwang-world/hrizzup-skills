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
        self.assertIn("not built into the macOS arm64 wheel", rows[0])
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
        self.assertEqual(names, ["actions/checkout", "actions/upload-artifact", "astral-sh/setup-uv"])
        self.assertTrue(all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses))
        self.assertIn('version: "0.13.1"', workflow_text())
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

    def test_it_is_not_a_required_check(self):
        checks = os.path.join(ROOT, ".github", "workflows", "checks.yml")
        with open(checks, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("Kits on Linux", text)
        self.assertNotIn("Image kits", text)


if __name__ == "__main__":
    unittest.main()
