"""`catalogue.py write` and `check`, on whole temporary repositories (docs/design.md, 7.2 and 7.3).

One complete valid repository (a skill, a starter agent, a script, an example, the shared files) is built
once and made with `write`. Every test then copies it, breaks one thing, and says which rule must fail.
Bad examples (a home-folder path, an email address, a digest after a key word) are built from pieces
here, so this file never trips the rules it tests.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import catalogue
import rules
import test_media as built

REAL = catalogue.ROOT
H1 = "ab" * 32  # made-up digests, nothing real
H2 = "cd" * 32
H3 = "ef" * 32

GOLDEN = None


def put(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))


def read(root, rel):
    return (Path(root) / rel).read_text(encoding="utf-8")


def edit(root, rel, old, new, count=1):
    text = read(root, rel)
    assert text.count(old) >= 1, "%r not in %s" % (old, rel)
    put(root, rel, text.replace(old, new, count))


def copy_real(root, *names):
    for name in names:
        put(root, name, (REAL / name).read_bytes())


HI_PY = '''#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Says hi."""
import argparse
import sys

import hrizzup_media  # noqa: F401


def main(argv=None):
    parser = argparse.ArgumentParser(description="Says hi.", epilog="Example: python3 scripts/hi.py --name World")
    parser.add_argument("--name", default="World")
    args = parser.parse_args(argv)
    print("hi " + args.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

SKILL_MD = """---
name: "hello"
description: "Says hello. Use when someone asks you to greet them."
compatibility: "Python 3.10 or later; nothing else."
metadata:
  hrizzup-name: "Hello"
  hrizzup-summary: "Says hello."
  hrizzup-needs: "Nothing"
  hrizzup-format: "breakdown"
---

# Hello

Says hello to a story. Short and plain.

## When to use

When someone asks you to greet them.

## What you need

Nothing beyond Python 3.12 with uv (`pip install uv`). The first run downloads nothing.

## Steps

1. Pin the story and read its brief.
2. Run `python3 scripts/hi.py --name World`, then read `references/guide.md`.

## Post it

A text post in the format `breakdown`: a caption of at most 5,000 characters.
"""

AGENT_MD = """---
name: "greeter"
metadata:
  hrizzup-name: "Greeter"
  hrizzup-summary: "Greets everyone."
  hrizzup-skills: "hello"
---

# Greeter

## Purpose

Say hello to readers.

## Voice

Warm and brief.

## Makes

Greetings.

## Never

Rudeness.

## Cadence

Once a day.

## Style

```json
%s
```
""" % json.dumps(rules.STYLE_DEFAULT, indent=2)

EXAMPLES_README = (
    rules.EXAMPLE_FIRST_LINE + "\n\nInput: the example story's brief. Command, as run: `python3 scripts/hi.py --name World`.\n"
    "Made on " + rules.EXAMPLE_MACHINE + ", on 18 November 2026, with Python 3.12.\n\nFiles: `post.json`.\n"
)

POST = {
    "storyId": rules.STORY_ID, "kind": "text", "format": "breakdown",
    "body": "Delhi NCR smog: what is new, and what is not confirmed.", "sources": ["https://example.com/a"],
}


def build_golden(root):
    copy_real(root, ".gitattributes", ".gitignore", "README.md", "NOTICES.md", "retired.txt", "shared/rules.md",
              "shared/agent-intro.md", "shared/references/sizes.md", "shared/scripts/hrizzup_media.py",
              ".github/workflows/checks.yml")
    put(root, "skills/hello/SKILL.md", SKILL_MD)
    put(root, "skills/hello/scripts/hi.py", HI_PY)
    put(root, "skills/hello/scripts/hrizzup_media.py", "# an old copy\n")  # opts in; `write` overwrites it
    put(root, "skills/hello/references/guide.md", "# Guide\n\nBe brief.\n")
    put(root, "skills/hello/examples/README.md", EXAMPLES_README)
    put(root, "skills/hello/examples/post.json", json.dumps(POST, indent=2) + "\n")
    put(root, "agents/greeter/AGENT.md", AGENT_MD)
    code, problems, _ = catalogue.write(root)
    assert code == 0, problems


def setUpModule():
    global GOLDEN
    GOLDEN = tempfile.mkdtemp(prefix="skills-golden-")
    build_golden(GOLDEN)


def tearDownModule():
    shutil.rmtree(GOLDEN, ignore_errors=True)


class Repo(unittest.TestCase):
    """A fresh copy of the golden repository, and helpers to break it and read what check says."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="skills-test-")
        self.addCleanup(shutil.rmtree, self.root, True)
        shutil.copytree(GOLDEN, self.root, dirs_exist_ok=True)

    def check(self, **kw):
        kw.setdefault("run_help_checks", False)
        return catalogue.check(self.root, **kw)[0]

    def write(self):
        code, problems, _ = catalogue.write(self.root)
        self.assertEqual(code, 0, problems)

    def fails(self, lines, path, rule, text=""):
        hits = [l for l in lines if l.startswith("%s: %s: " % (path, rule)) and text in l]
        self.assertTrue(hits, "no `%s: %s: …%s…` in:\n%s" % (path, rule, text, "\n".join(lines) or "(nothing)"))

    def clean(self, **kw):
        lines = self.check(**kw)
        self.assertEqual(lines, [], "\n".join(lines))


class Golden(Repo):
    def test_it_is_clean_with_the_help_checks_run(self):
        self.clean(run_help_checks=True)

    def test_the_catalogue(self):
        document = json.loads(read(self.root, "catalogue.json"))
        self.assertEqual(document["version"], 1)
        self.assertEqual([(i["kind"], i["slug"]) for i in document["items"]], [("skill", "hello"), ("starter-agent", "greeter")])
        skill, agent = document["items"]
        self.assertEqual(tuple(skill), rules.ITEM_KEYS)
        self.assertIsNone(skill["needs"])  # "Nothing" becomes null
        self.assertEqual(skill["format"], "breakdown")
        self.assertEqual(skill["body"] + "\n", read(self.root, "skills/hello/SKILL.md"))
        self.assertEqual(skill["meta"]["kit"], ["references/guide.md", "scripts/hi.py", "scripts/hrizzup_media.py"])
        self.assertEqual(set(skill["meta"]["kitSha256"]), set(skill["meta"]["kit"]))
        self.assertNotIn("examples/post.json", skill["meta"]["kit"])  # samples are never in the kit
        self.assertEqual(agent["meta"], {"skills": ["hello"]})
        self.assertTrue(agent["body"].startswith("# Greeter\n"))
        self.assertNotIn("name:", agent["body"])  # an agent's body starts after its frontmatter

    def test_every_kit_digest_is_the_sha256_of_the_file_on_disk(self):
        for item in json.loads(read(self.root, "catalogue.json"))["items"]:
            if item["kind"] != "skill":
                continue
            self.assertTrue(item["meta"]["kitSha256"])
            for path, digest in item["meta"]["kitSha256"].items():
                data = (Path(self.root) / item["path"] / path).read_bytes()
                self.assertEqual(digest, hashlib.sha256(data).hexdigest(), path)

    def test_the_file_is_exactly_what_json_dumps_makes_with_a_raw_em_dash(self):
        dash = chr(0x2014)
        edit(self.root, "skills/hello/SKILL.md", "Short and plain.", "Short " + dash + " plain.")
        self.write()
        raw = (Path(self.root) / "catalogue.json").read_bytes()
        document = json.loads(raw.decode("utf-8"))
        self.assertIn(dash, document["items"][0]["body"])
        self.assertEqual(raw, (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        self.assertIn(dash.encode("utf-8"), raw)  # written as its three UTF-8 bytes, not as a \\u escape
        self.assertNotIn(b"\\u2014", raw)
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(raw.endswith(b"}\n") and not raw.endswith(b"\n\n"))

    def test_the_generated_sections(self):
        text = read(self.root, "skills/hello/SKILL.md")
        self.assertIn("## Get the kit\n\nThis skill's kit is the folder skills/hello of " + rules.REPO_URL, text)
        self.assertIn("Files: `references/guide.md`, `scripts/hi.py`, `scripts/hrizzup_media.py`", text)
        self.assertTrue(text.endswith("## Hrizzup's rules\n\n" + rules.RULES_TEXT + "\n"))
        self.assertLess(text.index("## Get the kit"), text.index("## Steps"))
        agent = read(self.root, "agents/greeter/AGENT.md")
        self.assertIn("# Greeter\n\n" + rules.AGENT_INTRO_TEXT + "\n\n## Purpose", agent)
        self.assertTrue(agent.endswith("## Skills\n\n- hello\n"))

    def test_the_shared_copy_was_made(self):
        self.assertEqual((Path(self.root) / "skills/hello/scripts/hrizzup_media.py").read_bytes(),
                         (REAL / "shared/scripts/hrizzup_media.py").read_bytes())

    def test_the_readme_table(self):
        text = read(self.root, "README.md")
        self.assertIn("| Hello | Skill | Says hello. | Nothing | [skills/hello](skills/hello) |", text)
        self.assertIn("| Greeter | Starter agent | Greets everyone. | Nothing | [agents/greeter](agents/greeter) |", text)

    def test_write_twice_is_byte_identical(self):
        before = {rel: (Path(self.root) / rel).read_bytes() for rel in catalogue.Tree(self.root).files()}
        code, _, changed = catalogue.write(self.root)
        self.assertEqual((code, changed), (0, []))
        after = {rel: (Path(self.root) / rel).read_bytes() for rel in catalogue.Tree(self.root).files()}
        self.assertEqual(before, after)

    def test_the_hash_command_matches_the_catalogue(self):
        document = json.loads(read(self.root, "catalogue.json"))
        for item in document["items"]:
            self.assertEqual(catalogue.hash_folder(self.root, item["path"]), item["contentHash"])
        self.assertIsNone(catalogue.hash_folder(self.root, "skills/nothing"))

    def test_the_command_line(self):
        done = subprocess.run([sys.executable, str(REAL / "tools/catalogue.py"), "--root", self.root, "check"],
                              capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout.strip().split("\n")[-1]), (0, "ok: no problems"), done.stdout)
        done = subprocess.run([sys.executable, str(REAL / "tools/catalogue.py"), "--root", self.root, "hash", "skills/hello"],
                              capture_output=True, text=True)
        self.assertRegex(done.stdout.strip(), r"^[0-9a-f]{64}$")

    def test_an_empty_repository_works(self):
        for rel in ("skills", "agents"):
            shutil.rmtree(Path(self.root) / rel)
        self.write()
        self.clean()
        self.assertEqual(json.loads(read(self.root, "catalogue.json")), {"version": 1, "items": []})


class Stale(Repo):
    def test_one_changed_kit_byte_makes_the_catalogue_stale_until_write(self):
        before = json.loads(read(self.root, "catalogue.json"))["items"][0]["meta"]["kitSha256"]["references/guide.md"]
        put(self.root, "skills/hello/references/guide.md", "# Guide\n\nBe briefer.\n")
        self.fails(self.check(), "catalogue.json", "generated", "stale")
        self.write()
        after = json.loads(read(self.root, "catalogue.json"))["items"][0]["meta"]["kitSha256"]["references/guide.md"]
        self.assertNotEqual(before, after)
        self.assertEqual(after, hashlib.sha256(b"# Guide\n\nBe briefer.\n").hexdigest())
        self.clean()

    def test_a_hand_edit_to_the_catalogue(self):
        edit(self.root, "catalogue.json", '"Says hello."', '"Says hullo."')
        self.fails(self.check(), "catalogue.json", "generated", "stale")

    def test_a_missing_catalogue(self):
        os.remove(Path(self.root) / "catalogue.json")
        lines = self.check()
        self.fails(lines, "catalogue.json", "generated", "missing")
        self.fails(lines, "catalogue.json", "layout", "missing")

    def test_a_hand_edited_generated_section(self):
        edit(self.root, "skills/hello/SKILL.md", "Files: `references", "Files: `x`, `references")
        self.fails(self.check(), "skills/hello/SKILL.md", "generated", "stale")

    def test_a_hand_edited_rules_section(self):
        edit(self.root, "skills/hello/SKILL.md", "Hrizzup basics", "Hrizzup basics (changed)")
        self.fails(self.check(), "skills/hello/SKILL.md", "generated", "stale")

    def test_a_skill_edit_makes_the_catalogue_stale_until_write(self):
        edit(self.root, "skills/hello/SKILL.md", "Short and plain.", "Short, plain and kind.")
        self.fails(self.check(), "catalogue.json", "generated", "stale")
        self.write()
        self.clean()

    def test_an_edited_shared_copy_in_a_skill(self):
        put(self.root, "skills/hello/scripts/hrizzup_media.py", "# edited here, not in shared/\n")
        self.fails(self.check(), "skills/hello/scripts/hrizzup_media.py", "generated", "shared file")
        self.write()
        self.clean()

    def test_an_edited_shared_file_updates_every_copy(self):
        put(self.root, "shared/references/sizes.md", "# Sizes\n\nNew.\n")
        put(self.root, "skills/hello/references/sizes.md", "# old\n")  # opting in
        self.write()
        self.assertEqual(read(self.root, "skills/hello/references/sizes.md"), "# Sizes\n\nNew.\n")
        self.assertIn("references/sizes.md", json.loads(read(self.root, "catalogue.json"))["items"][0]["meta"]["kit"])
        self.clean()

    def test_a_stale_readme_table(self):
        edit(self.root, "README.md", "| Hello | Skill |", "| Hallo | Skill |")
        self.fails(self.check(), "README.md", "generated", "stale")

    def test_readme_markers_are_needed(self):
        edit(self.root, "README.md", rules.README_END, "")
        self.fails(self.check(), "README.md", "generated", "once each")

    def test_a_missing_get_the_kit_section_is_made_by_write(self):
        text = read(self.root, "skills/hello/SKILL.md")
        put(self.root, "skills/hello/SKILL.md", re.sub(r"## Get the kit\n.*?(?=## Steps)", "", text, flags=re.S))
        self.fails(self.check(), "skills/hello/SKILL.md", "generated", "stale")
        self.write()
        self.assertIn("## Get the kit", read(self.root, "skills/hello/SKILL.md"))

    def test_a_skill_with_no_kit_has_no_get_the_kit_section(self):
        shutil.rmtree(Path(self.root) / "skills/hello/scripts")
        shutil.rmtree(Path(self.root) / "skills/hello/references")
        edit(self.root, "skills/hello/SKILL.md", 'compatibility: "Python 3.10 or later; nothing else."\n', "")
        edit(self.root, "skills/hello/SKILL.md", "Run `python3 scripts/hi.py --name World`, then read `references/guide.md`.", "Read the brief.")
        edit(self.root, "skills/hello/SKILL.md", "Nothing beyond Python 3.12 with uv (`pip install uv`). The first run downloads nothing.", "Nothing.")
        edit(self.root, "skills/hello/examples/README.md", "Command, as run: `python3 scripts/hi.py --name World`.", "No command.")
        self.write()
        self.assertNotIn("## Get the kit", read(self.root, "skills/hello/SKILL.md"))
        self.assertEqual(json.loads(read(self.root, "catalogue.json"))["items"][0]["meta"], {"kit": [], "kitSha256": {}})
        self.clean()

    def test_the_agent_intro_and_skills_are_generated(self):
        edit(self.root, "agents/greeter/AGENT.md", "- hello", "- hello\n- extra")
        self.fails(self.check(), "agents/greeter/AGENT.md", "generated", "stale")
        edit(self.root, "agents/greeter/AGENT.md", "A starter agent from Hrizzup's marketplace.", "My own words.")
        self.write()
        self.clean()

    def test_write_refuses_to_build_from_broken_frontmatter(self):
        edit(self.root, "skills/hello/SKILL.md", 'name: "hello"', "name: hello")
        code, problems, _ = catalogue.write(self.root)
        self.assertEqual(code, 1)
        self.assertIn("double-quoted", "\n".join(problems))


class Layout(Repo):
    def test_an_extra_top_level_entry(self):
        put(self.root, "LICENSE", "x\n")
        self.fails(self.check(), "LICENSE", "layout", "top-level")
        put(self.root, "extra/file.md", "x\n")
        self.fails(self.check(), "extra/file.md", "layout", "top-level")

    def test_gitattributes_must_start_star_minus_text(self):
        put(self.root, ".gitattributes", "# first\n* -text\n")
        self.fails(self.check(), ".gitattributes", "layout", "* -text")

    def test_gitignore_must_name_the_five(self):
        put(self.root, ".gitignore", ".DS_Store\n")
        self.fails(self.check(), ".gitignore", "layout", "must name")

    def test_a_symbolic_link(self):
        os.symlink("guide.md", Path(self.root) / "skills/hello/references/link.md")
        self.fails(self.check(), "skills/hello/references/link.md", "paths", "symbolic link")

    def test_a_path_that_differs_only_in_case(self):
        # This Mac's file system ignores case, so the second name is added in memory, not on disk.
        tree = catalogue.Tree(self.root)
        tree.put("skills/hello/references/Guide.md", "# G\n")
        P = catalogue.Problems()
        catalogue.check_layout(tree, P)
        self.fails(P.lines(), "skills/hello/references/Guide.md", "paths", "only in case")

    def test_a_bad_path_part(self):
        put(self.root, "skills/hello/references/guide copy.md", "# G\n")
        put(self.root, "skills/hello/references/a+b.md", "# G\n")
        lines = self.check()
        self.fails(lines, "skills/hello/references/guide copy.md", "paths")
        self.fails(lines, "skills/hello/references/a+b.md", "paths")

    def test_a_path_over_200_characters(self):
        put(self.root, "skills/hello/references/" + "a" * 190 + ".md", "# A\n")
        self.fails(self.check(), "skills/hello/references/" + "a" * 190 + ".md", "paths", "200")

    def test_a_file_over_25_mib(self):
        path = Path(self.root) / "skills/hello/examples/big.json"
        with open(path, "wb") as f:
            f.truncate(rules.FILE_MAX_BYTES + 1)
        self.fails(self.check(), "skills/hello/examples/big.json", "paths", "25 MiB")

    def test_a_file_type_that_doesnt_belong(self):
        put(self.root, "skills/hello/references/notes.txt", "x\n")
        put(self.root, "skills/hello/scripts/run.sh", "x\n")
        put(self.root, "skills/hello/other/x.md", "x\n")
        put(self.root, "skills/hello/README.md", "x\n")
        lines = self.check()
        for rel in ("skills/hello/references/notes.txt", "skills/hello/scripts/run.sh", "skills/hello/other/x.md", "skills/hello/README.md"):
            self.fails(lines, rel, "layout")

    def test_an_agent_folder_holds_agent_md_only(self):
        put(self.root, "agents/greeter/notes.md", "x\n")
        self.fails(self.check(), "agents/greeter/notes.md", "layout", "AGENT.md")

    def test_a_skill_folder_name_must_be_a_slug(self):
        shutil.copytree(Path(self.root) / "skills/hello", Path(self.root) / "skills/Bad-Name")
        self.fails(self.check(), "skills/Bad-Name/SKILL.md", "layout", "slug")

    def test_a_slug_over_54_characters(self):
        long = "a" * 55
        shutil.copytree(Path(self.root) / "skills/hello", Path(self.root) / ("skills/" + long))
        self.fails(self.check(), "skills/%s/SKILL.md" % long, "layout", "54")

    def test_a_missing_required_file(self):
        for name in ("README.md", "NOTICES.md", "retired.txt"):
            os.remove(Path(self.root) / name)
        lines = self.check()
        for name in ("README.md", "NOTICES.md", "retired.txt"):
            self.fails(lines, name, "layout", "missing")

    def test_a_workflow_is_the_only_thing_in_github(self):
        put(self.root, ".github/CODEOWNERS", "x\n")
        self.fails(self.check(), ".github/CODEOWNERS", "layout")


class Symlinks(Repo):
    """`write` and `check` never follow a symbolic link: nothing outside the repository is read or written."""

    def outside(self, **files):
        folder = tempfile.mkdtemp(prefix="skills-outside-")
        self.addCleanup(shutil.rmtree, folder, True)
        for name, text in files.items():
            put(folder, name, text)
        return folder

    def snapshot(self, folder):
        return {rel: (Path(folder) / rel).read_bytes() for rel in catalogue.Tree(folder).files()}

    def refused(self, outside):
        before = self.snapshot(outside)
        code, problems, changed = catalogue.write(self.root)
        self.assertEqual((code, changed), (1, []), problems)
        self.assertIn("symbolic link", "\n".join(problems))
        self.assertEqual(self.snapshot(outside), before, "something outside the repository changed")

    def test_a_linked_folder_inside_skills(self):
        outside = self.outside(**{"SKILL.md": SKILL_MD, "scripts/hrizzup_media.py": "# sentinel\n"})
        os.symlink(outside, Path(self.root) / "skills/linked")
        self.refused(outside)
        self.fails(self.check(), "skills/linked", "paths", "symbolic link")

    def test_a_linked_scripts_folder_the_shared_copy_would_have_been_written_through(self):
        outside = self.outside(**{"hrizzup_media.py": "# sentinel\n", "hi.py": HI_PY})
        shutil.rmtree(Path(self.root) / "skills/hello/scripts")
        os.symlink(outside, Path(self.root) / "skills/hello/scripts")
        self.refused(outside)

    def test_the_same_in_a_git_repository_where_the_files_are_still_tracked(self):
        for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "base")):
            subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@users.noreply.github.com", "-c", "commit.gpgsign=false", *args],
                           cwd=self.root, check=True, capture_output=True)
        outside = self.outside(**{"hrizzup_media.py": "# sentinel\n", "hi.py": HI_PY})
        shutil.rmtree(Path(self.root) / "skills/hello/scripts")
        os.symlink(outside, Path(self.root) / "skills/hello/scripts")
        self.refused(outside)

    def test_a_linked_generated_file(self):
        outside = self.outside(**{"catalogue.json": "sentinel\n"})
        os.remove(Path(self.root) / "catalogue.json")
        os.symlink(Path(outside) / "catalogue.json", Path(self.root) / "catalogue.json")
        self.refused(outside)

    def test_a_link_that_appears_after_the_listing_is_still_not_written_through(self):
        outside = self.outside(**{"hrizzup_media.py": "# sentinel\n"})
        tree = catalogue.Tree(self.root)
        tree.files()
        shutil.rmtree(Path(self.root) / "skills/hello/scripts")
        os.symlink(outside, Path(self.root) / "skills/hello/scripts")
        before = self.snapshot(outside)
        problems = tree.write_all({"skills/hello/scripts/hrizzup_media.py": b"changed\n"})
        self.assertTrue(problems)
        self.assertEqual(self.snapshot(outside), before)
        with self.assertRaises(OSError):
            tree.read("skills/hello/scripts/hi.py")

    def test_a_link_is_never_read_either(self):
        secret = self.outside(**{"x.md": "# outside\n"})
        os.symlink(Path(secret) / "x.md", Path(self.root) / "skills/hello/references/x.md")
        tree = catalogue.Tree(self.root)
        self.assertNotIn("skills/hello/references/x.md", tree.files())
        self.assertFalse(tree.exists("skills/hello/references/x.md"))
        self.assertNotIn("references/x.md", catalogue.kit_paths(tree, "hello"))  # nor in a kit

    def test_a_clean_tree_still_writes(self):
        code, problems, changed = catalogue.write(self.root)
        self.assertEqual((code, problems, changed), (0, [], []))


class CleanPaths(Repo):
    """A path with `.`, `..` or an empty part is never a file of the tree, however it resolves."""

    def outside_file(self, name, data):
        path = Path(self.root).parent / name
        path.write_bytes(data)
        self.addCleanup(path.unlink)
        return path

    def test_unclean_paths_are_refused_by_the_tree(self):
        tree = catalogue.Tree(self.root)
        self.assertTrue(tree.exists("skills/hello/SKILL.md"))
        for rel in ("skills/hello/../hello/SKILL.md", "./README.md", "skills//hello/SKILL.md", "skills/hello/SKILL.md/",
                    "..", "../x", "/etc/hosts", "skills\\hello\\SKILL.md", ""):
            with self.subTest(rel=rel):
                self.assertFalse(tree.exists(rel))
                with self.assertRaises(OSError):
                    tree.read(rel)
                with self.assertRaises(OSError):
                    tree.size(rel)

    def test_a_skills_named_file_can_not_climb_out_of_the_repository(self):
        self.outside_file("climb-outside.md", b"# outside\n")
        edit(self.root, "skills/hello/SKILL.md", "then read `references/guide.md`", "then read `references/../../../../climb-outside.md`")
        self.fails(self.check(), "skills/hello/SKILL.md", "body", "isn't in the skill's folder")

    def test_a_named_file_can_not_use_dots_to_reach_another_file_inside_either(self):
        edit(self.root, "skills/hello/SKILL.md", "then read `references/guide.md`", "then read `references/../references/guide.md`")
        self.fails(self.check(), "skills/hello/SKILL.md", "body", "isn't in the skill's folder")

    def test_a_posts_media_can_not_climb_out_of_examples(self):
        outside = self.outside_file("climb-outside.png", built.png(1080, 1080))
        edit(self.root, "skills/hello/SKILL.md", '"breakdown"', '"meme"')
        edit(self.root, "skills/hello/SKILL.md", "`breakdown`", "`meme`")
        media = {"file": "../../../../climb-outside.png", "description": "x"}
        put(self.root, "skills/hello/examples/post.json", json.dumps(dict(POST, kind="image", format="meme", body="A caption.", media=media)) + "\n")
        self.assertTrue(outside.exists())
        self.fails(self.check(), "skills/hello/examples/post.json", "examples", "climb-outside.png")


class TheSkillsFile(Repo):
    def sections_problem(self, old, new, text="", count=1):
        edit(self.root, "skills/hello/SKILL.md", old, new, count)
        self.fails(self.check(), "skills/hello/SKILL.md", "body", text)

    def test_a_missing_section(self):
        self.sections_problem("## When to use\n\nWhen someone asks you to greet them.\n\n", "", "sections must start")

    def test_sections_out_of_order(self):
        text = read(self.root, "skills/hello/SKILL.md")
        swapped = text.replace("## When to use", "## SWAP").replace("## What you need", "## When to use").replace("## SWAP", "## What you need")
        put(self.root, "skills/hello/SKILL.md", swapped)
        self.fails(self.check(), "skills/hello/SKILL.md", "body", "sections must start")

    def test_the_last_two_sections(self):
        self.sections_problem("## Post it", "## Poster", "last two sections")

    def test_an_optional_section_is_allowed_between_steps_and_post_it(self):
        edit(self.root, "skills/hello/SKILL.md", "## Post it", "## Script shape\n\nIt prints hi.\n\n## Post it")
        self.write()
        self.clean()

    def test_the_introduction_is_one_to_three_sentences(self):
        self.sections_problem("Says hello to a story. Short and plain.", "One. Two. Three. Four.", "3 sentences")
        self.sections_problem("# Hello\n\nOne. Two. Three. Four.\n", "# Hello\n", "no introduction")

    def test_steps_are_numbered(self):
        self.sections_problem("1. Pin", "- Pin", "numbered")

    def test_a_named_file_must_exist(self):
        self.sections_problem("then read `references/guide.md`", "then read `references/missing.md`", "references/missing.md")
        self.sections_problem("Run `python3 scripts/hi.py", "Run `python3 scripts/nope.py", "scripts/nope.py")

    def test_a_named_path_in_a_url_is_not_a_file(self):
        edit(self.root, "skills/hello/SKILL.md", "1. Pin the story", "1. See https://example.com/a/scripts/x for background. Pin the story")
        self.write()
        self.clean()

    def test_compatibility_goes_with_scripts(self):
        edit(self.root, "skills/hello/SKILL.md", 'compatibility: "Python 3.10 or later; nothing else."\n', "")
        self.fails(self.check(), "skills/hello/SKILL.md", "frontmatter", "compatibility")
        put(self.root, "skills/hello/SKILL.md", SKILL_MD)
        shutil.rmtree(Path(self.root) / "skills/hello/scripts")
        self.fails(self.check(), "skills/hello/SKILL.md", "frontmatter", "only for a skill with a scripts/")

    def test_what_you_need_says_uv_for_a_script(self):
        self.sections_problem("Nothing beyond Python 3.12 with uv (`pip install uv`). The first run downloads nothing.", "Nothing.", "uv")

    def test_post_it_names_the_format(self):
        self.sections_problem("in the format `breakdown`", "in its format", "format code")

    def test_a_body_over_20000_characters_or_500_lines(self):
        edit(self.root, "skills/hello/SKILL.md", "1. Pin the story and read its brief.\n", "1. Pin the story.\n" + "\n".join("Line %d." % i for i in range(520)) + "\n")
        self.fails(self.check(), "skills/hello/SKILL.md", "body", "lines; at most 500")
        edit(self.root, "skills/hello/SKILL.md", "Line 5.\n", "x" * 20500 + "\n")
        self.fails(self.check(), "skills/hello/SKILL.md", "body", "characters; at most 20000")

    def test_bad_characters_and_endings(self):
        edit(self.root, "skills/hello/SKILL.md", "Short and plain.", "Short and plain \u00e9.")
        self.fails(self.check(), "skills/hello/SKILL.md", "text", "U+00E9")
        put(self.root, "skills/hello/SKILL.md", SKILL_MD.replace("\n", "\r\n"))
        self.fails(self.check(), "skills/hello/SKILL.md", "text", "carriage return")
        put(self.root, "skills/hello/SKILL.md", SKILL_MD.rstrip("\n"))
        self.fails(self.check(), "skills/hello/SKILL.md", "text", "no final new line")

    def test_a_skill_without_a_skill_md(self):
        os.remove(Path(self.root) / "skills/hello/SKILL.md")
        self.fails(self.check(), "skills/hello/SKILL.md", "frontmatter", "missing")

    def test_a_skill_that_is_also_a_starter_agent_slug(self):
        shutil.copytree(Path(self.root) / "agents/greeter", Path(self.root) / "agents/hello")
        edit(self.root, "agents/hello/AGENT.md", 'name: "greeter"', 'name: "hello"')
        self.write()
        self.fails(self.check(), "catalogue.json", "catalogue", "used twice")


class TheAgentsFile(Repo):
    def test_sections_must_be_in_order(self):
        edit(self.root, "agents/greeter/AGENT.md", "## Never", "## Nevermind")
        self.fails(self.check(), "agents/greeter/AGENT.md", "body", "sections must be")

    def test_a_section_is_at_most_1500_characters(self):
        edit(self.root, "agents/greeter/AGENT.md", "Say hello to readers.", "x" * 1501)
        self.fails(self.check(), "agents/greeter/AGENT.md", "body", "1500")

    def test_a_body_over_6000_characters(self):
        for name in ("Purpose", "Voice", "Makes", "Never"):
            edit(self.root, "agents/greeter/AGENT.md", "## %s\n\n" % name, "## %s\n\n%s\n\n" % (name, "y" * 1400))
        self.fails(self.check(), "agents/greeter/AGENT.md", "body", "6000")

    def test_an_empty_section(self):
        edit(self.root, "agents/greeter/AGENT.md", "Greetings.\n", "")
        self.fails(self.check(), "agents/greeter/AGENT.md", "body", "## Makes is empty")

    def test_the_style_block(self):
        edit(self.root, "agents/greeter/AGENT.md", '"ink": "#111111"', '"ink": "black"')
        self.fails(self.check(), "agents/greeter/AGENT.md", "body", "ink")
        edit(self.root, "agents/greeter/AGENT.md", "```json", "```text")
        self.fails(self.check(), "agents/greeter/AGENT.md", "body", "fenced `json` block")

    def test_a_style_missing_a_key_is_refused_even_with_an_unknown_one(self):
        edit(self.root, "agents/greeter/AGENT.md", '"signature": ""', '"mystery": 1')
        self.fails(self.check(), "agents/greeter/AGENT.md", "body", "every key of the default style")

    def test_every_skill_it_names_must_exist(self):
        edit(self.root, "agents/greeter/AGENT.md", 'hrizzup-skills: "hello"', 'hrizzup-skills: "hello ghost"')
        self.write()
        self.fails(self.check(), "agents/greeter/AGENT.md", "frontmatter", "ghost")
        self.fails(self.check(), "catalogue.json", "catalogue", "ghost")


class Scripts(Repo):
    def script(self, text, name="hi.py"):
        put(self.root, "skills/hello/scripts/" + name, text)
        return self.check(run_help_checks=True)

    def test_a_top_level_package_import(self):
        self.fails(self.script(HI_PY.replace("import sys\n", "import sys\nimport requests\n")), "skills/hello/scripts/hi.py", "script", "imports requests at the top")

    def test_a_package_inside_a_function_is_fine(self):
        lines = self.script(HI_PY.replace('    print("hi', '    import PIL  # noqa\n    print("hi'))
        self.assertFalse([l for l in lines if "hi.py: script" in l], lines)

    def test_a_relative_import(self):
        self.fails(self.script(HI_PY.replace("import sys\n", "import sys\nfrom . import x\n")), "skills/hello/scripts/hi.py", "script", "relative")

    def test_gpl_modules_only_in_voice(self):
        lines = self.script(HI_PY.replace("def main", "def other():\n    import kokoro_onnx\n\n\ndef main"))
        self.fails(lines, "skills/hello/scripts/hi.py", "script", "only voice.py")

    def test_ffmpeg_only_through_hrizzup_media(self):
        lines = self.script(HI_PY.replace("import sys\n", "import sys\nimport subprocess\n"))
        self.fails(lines, "skills/hello/scripts/hi.py", "script", "FFmpeg runs only through")
        lines = self.script(HI_PY.replace("def main", "def other():\n    import imageio_ffmpeg\n\n\ndef main"))
        self.fails(lines, "skills/hello/scripts/hi.py", "script", "imageio_ffmpeg")

    def test_the_network_only_for_three_scripts(self):
        self.fails(self.script(HI_PY.replace("import sys\n", "import sys\nimport socket\n")), "skills/hello/scripts/hi.py", "script", "network")
        self.fails(self.script(HI_PY.replace("def main", "def other():\n    import urllib.request\n\n\ndef main")), "skills/hello/scripts/hi.py", "script", "network")
        lines = self.script(HI_PY.replace("import sys\n", "import sys\nimport socket\n").replace("hi.py", "check_links.py"), "check_links.py")
        self.assertFalse([l for l in lines if "check_links.py: script" in l and "network" in l], lines)

    def test_hrizzup_media_may_not_use_the_network_either(self):
        lines = self.script("import socket\n", "hrizzup_media.py")
        self.fails(lines, "skills/hello/scripts/hrizzup_media.py", "script", "network")

    def test_a_script_without_a_header(self):
        lines = self.script(HI_PY.replace("# /// script\n# requires-python = \">=3.10\"\n# dependencies = []\n# ///\n", ""))
        self.fails(lines, "skills/hello/scripts/hi.py", "script", "no `# /// script` header")

    def test_a_standard_library_script_says_python_3_10(self):
        lines = self.script(HI_PY.replace(">=3.10", ">=3.12"))
        self.fails(lines, "skills/hello/scripts/hi.py", "script", "requires-python")

    def test_help_must_work_and_end_with_an_example(self):
        self.fails(self.script(HI_PY.replace(', epilog="Example: python3 scripts/hi.py --name World"', "")), "skills/hello/scripts/hi.py", "script", "example")
        self.fails(self.script(HI_PY.replace("import sys\n", "import sys\nraise SystemExit(5)\n")), "skills/hello/scripts/hi.py", "script", "--help")

    def test_a_command_never_prompts(self):
        self.fails(self.script(HI_PY.replace('    print("hi', '    input("name? ")\n    print("hi')), "skills/hello/scripts/hi.py", "script", "input()")

    def test_a_file_that_doesnt_parse(self):
        self.fails(self.script("def (:\n"), "skills/hello/scripts/hi.py", "script", "doesn't parse")

    def test_a_module_has_no_header(self):
        lines = self.script("# /// script\n# dependencies = []\n# ///\nimport os\n", "hrizzup_extra.py")
        self.fails(lines, "skills/hello/scripts/hrizzup_extra.py", "script", "module has no script header")

    def test_the_draw_module_may_import_pillow_at_its_top(self):
        lines = self.script("from PIL import Image\nimport fontTools\n", "hrizzup_draw.py")
        self.assertFalse([l for l in lines if "hrizzup_draw.py: script" in l], lines)
        lines = self.script("import numpy\n", "hrizzup_draw.py")
        self.fails(lines, "skills/hello/scripts/hrizzup_draw.py", "script", "numpy")

    def test_voice_and_captions_take_offline(self):
        lines = self.script(HI_PY.replace("hi.py", "voice.py"), "voice.py")
        self.fails(lines, "skills/hello/scripts/voice.py", "script", "--offline")

    def test_a_lone_python_file_outside_scripts_isnt_run(self):
        put(self.root, "skills/hello/references/x.py", "x\n")
        self.fails(self.check(), "skills/hello/references/x.py", "layout")


def lock_text(packages, requirements=None, exclude=rules.EXCLUDE_NEWER, python=">=3.12, <3.14"):
    requirements = requirements if requirements is not None else [(n, "==" + v[0]) for n, v in packages.items() if n in rules.PINS]
    lines = ["version = 1", "revision = 5", 'requires-python = "%s"' % python, "", "[options]",
             'exclude-newer = "%s"' % exclude, "", "[manifest]", "requirements = ["]
    lines += ['    { name = "%s", specifier = "%s" },' % r for r in requirements]
    lines += ["]"]
    for name, (version, hashes) in packages.items():
        lines += ["", "[[package]]", 'name = "%s"' % name, 'version = "%s"' % version,
                  'source = { registry = "https://pypi.org/simple" }', "wheels = ["]
        lines += ['    { url = "https://files.example/%s.whl", hash = "sha256:%s", size = 1 },' % (name, h) for h in hashes]
        lines += ["]"]
    return "\n".join(lines) + "\n"


def requirements_text(packages):
    lines = ["# This file was autogenerated by uv via the following command:",
             "#    uv export --script draw.py --format requirements.txt --locked -o draw.requirements.txt"]
    for name, (version, hashes) in packages.items():
        lines.append("%s==%s \\" % (name, version))
        lines += ["    --hash=sha256:%s%s" % (h, " \\" if i < len(hashes) - 1 else "") for i, h in enumerate(hashes)]
    return "\n".join(lines) + "\n"


def script_text(deps, python=">=3.12,<3.14", exclude=rules.EXCLUDE_NEWER, name="draw.py"):
    return (
        '#!/usr/bin/env python3\n# /// script\n# requires-python = "%s"\n# dependencies = %s\n# [tool.uv]\n# exclude-newer = "%s"\n# ///\n'
        '"""Draws."""\nimport argparse\nimport sys\n\n\ndef main(argv=None):\n'
        '    parser = argparse.ArgumentParser(description="Draws.", epilog="Example: uv run scripts/%s")\n'
        "    parser.parse_args(argv)\n    return 0\n\n\nif __name__ == \"__main__\":\n    sys.exit(main())\n"
        % (python, json.dumps(deps), exclude, name)
    )


PILLOW = {"pillow": ("13.0.0", [H1, H2])}
NOTICE_HEADER = "| Name | Version | Licence | Home | How it's used | Used by |\n|---|---|---|---|---|---|\n"


def notice(name, version, licence="MIT", used="installed by the creator's setup", by="draw.py"):
    return "| %s | %s | %s | https://example.org | %s | %s |\n" % (name, version, licence, used, by)


class Locks(Repo):
    def heavy(self, packages=PILLOW, deps=("pillow==13.0.0",), notices=None, name="draw.py"):
        """A script with packages, its lock, its requirements file and its NOTICES rows (safe to call twice)."""
        base = "skills/hello/scripts/" + name
        put(self.root, base, script_text(list(deps), name=name))
        put(self.root, base + ".lock", lock_text(packages))
        put(self.root, base[:-3] + ".requirements.txt", requirements_text(packages))
        rows = notices if notices is not None else "".join(notice(n, v[0]) for n, v in packages.items())
        put(self.root, "NOTICES.md", (REAL / "NOTICES.md").read_text(encoding="utf-8") + rows)
        need = "The first run downloads nothing."
        no_uv = " On a machine without uv: `python3.12 -m venv .venv`, then `.venv/bin/python -m pip install --require-hashes -r scripts/%s.requirements.txt`." % name[:-3]
        put(self.root, "skills/hello/SKILL.md", SKILL_MD.replace(need, need + no_uv))
        put(self.root, "skills/hello/examples/README.md", EXAMPLES_README + "Also `uv run scripts/%s`.\n" % name)
        self.write()

    def test_a_complete_heavy_script_is_clean(self):
        self.heavy()
        self.clean(run_help_checks=True)
        self.assertIn("scripts/draw.py.lock", json.loads(read(self.root, "catalogue.json"))["items"][0]["meta"]["kit"])

    def test_the_header_must_use_the_repositorys_pins_and_date(self):
        self.heavy()
        put(self.root, "skills/hello/scripts/draw.py", script_text(["pillow==12.0.0"]))
        self.fails(self.check(), "skills/hello/scripts/draw.py", "script", "13.0.0")
        put(self.root, "skills/hello/scripts/draw.py", script_text(["pillow==13.0.0"], exclude="2026-11-01T00:00:00Z"))
        self.fails(self.check(), "skills/hello/scripts/draw.py", "script", "exclude-newer")
        put(self.root, "skills/hello/scripts/draw.py", script_text(["pillow"]))
        self.fails(self.check(), "skills/hello/scripts/draw.py", "script", "pinned exactly")
        put(self.root, "skills/hello/scripts/draw.py", script_text(["pillow>=13"]))
        self.fails(self.check(), "skills/hello/scripts/draw.py", "script", "pinned exactly")
        put(self.root, "skills/hello/scripts/draw.py", script_text(["left-pad==1.0.0"]))
        self.fails(self.check(), "skills/hello/scripts/draw.py", "script", "isn't a package the repository pins")
        put(self.root, "skills/hello/scripts/draw.py", script_text(["pillow==13.0.0"], python=">=3.9"))
        self.fails(self.check(), "skills/hello/scripts/draw.py", "script", "requires-python")

    def test_av_is_pinned_below_the_newest(self):
        self.assertEqual(rules.PINS["av"], "18.1.0")
        self.assertEqual(rules.EXCLUDE_NEWER, "2026-11-15T00:00:00Z")

    def test_a_missing_lock_or_requirements_file(self):
        self.heavy()
        os.remove(Path(self.root) / "skills/hello/scripts/draw.py.lock")
        os.remove(Path(self.root) / "skills/hello/scripts/draw.requirements.txt")
        lines = self.check()
        self.fails(lines, "skills/hello/scripts/draw.py.lock", "locks", "missing")
        self.fails(lines, "skills/hello/scripts/draw.requirements.txt", "locks", "missing")

    def test_a_lock_that_doesnt_match_the_header(self):
        self.heavy()
        put(self.root, "skills/hello/scripts/draw.py.lock", lock_text(PILLOW, requirements=[("pillow", "==12.0.0")]))
        self.fails(self.check(), "skills/hello/scripts/draw.py.lock", "locks", "manifest")

    def test_a_lock_with_another_date_or_python(self):
        self.heavy()
        put(self.root, "skills/hello/scripts/draw.py.lock", lock_text(PILLOW, exclude="2026-11-01T00:00:00Z"))
        self.fails(self.check(), "skills/hello/scripts/draw.py.lock", "locks", "exclude-newer")
        put(self.root, "skills/hello/scripts/draw.py.lock", lock_text(PILLOW, python=">=3.9"))
        self.fails(self.check(), "skills/hello/scripts/draw.py.lock", "locks", "requires-python")

    def test_a_lock_at_another_version_than_the_pin(self):
        self.heavy()
        put(self.root, "skills/hello/scripts/draw.py.lock", lock_text({"pillow": ("12.0.0", [H1, H2])}, requirements=[("pillow", "==13.0.0")]))
        self.fails(self.check(), "skills/hello/scripts/draw.py.lock", "locks", "not the repository's pin")

    def test_requirements_with_another_set_version_or_hash(self):
        self.heavy()
        path = "skills/hello/scripts/draw.requirements.txt"
        put(self.root, path, requirements_text({"pillow": ("13.0.0", [H1, H2]), "extra": ("1.0", [H3])}))
        self.fails(self.check(), path, "locks", "different set of packages")
        put(self.root, path, requirements_text({"pillow": ("12.9.9", [H1])}))
        self.fails(self.check(), path, "locks", "12.9.9")
        put(self.root, path, requirements_text({"pillow": ("13.0.0", [H3])}))
        self.fails(self.check(), path, "locks", "needs hashes, all of them from the lock")
        put(self.root, path, "pillow==13.0.0\n")
        self.fails(self.check(), path, "locks", "needs hashes")

    def test_a_lock_with_no_script_beside_it(self):
        put(self.root, "skills/hello/scripts/ghost.py.lock", lock_text(PILLOW))
        put(self.root, "skills/hello/scripts/ghost.requirements.txt", requirements_text(PILLOW))
        lines = self.check()
        self.fails(lines, "skills/hello/scripts/ghost.py.lock", "locks", "no script")
        self.fails(lines, "skills/hello/scripts/ghost.requirements.txt", "locks", "no script")

    def test_a_standard_library_script_needs_no_lock(self):
        put(self.root, "skills/hello/scripts/hi.py.lock", lock_text(PILLOW))
        self.fails(self.check(), "skills/hello/scripts/hi.py.lock", "locks", "needs no lock")

    def test_one_version_of_a_package_across_the_locks(self):
        self.heavy()
        other = {"pillow": ("13.0.0", [H1]), "somepkg": ("1.0.0", [H1])}
        put(self.root, "skills/hello/scripts/other.py", script_text(["pillow==13.0.0"], name="other.py"))
        put(self.root, "skills/hello/scripts/other.py.lock", lock_text(other))
        put(self.root, "skills/hello/scripts/other.requirements.txt", requirements_text(other))
        edit(self.root, "NOTICES.md", NOTICE_HEADER, NOTICE_HEADER + notice("somepkg", "1.0.0") + notice("somepkg", "2.0.0"))
        put(self.root, "skills/hello/scripts/third.py", script_text(["pillow==13.0.0"], name="third.py"))
        third = {"pillow": ("13.0.0", [H1]), "somepkg": ("2.0.0", [H1])}
        put(self.root, "skills/hello/scripts/third.py.lock", lock_text(third))
        put(self.root, "skills/hello/scripts/third.requirements.txt", requirements_text(third))
        self.fails(self.check(), "shared/scripts", "locks", "somepkg is locked at 1.0.0 and 2.0.0")

    def test_every_locked_package_needs_a_licence_row(self):
        self.heavy(notices="")
        self.fails(self.check(), "NOTICES.md", "notices", "no row, with a licence, for pillow 13.0.0")

    def test_a_row_without_a_licence_or_at_another_version_doesnt_count(self):
        self.heavy(notices=notice("Pillow", "13.0.0", licence=""))
        self.fails(self.check(), "NOTICES.md", "notices", "pillow 13.0.0")
        self.heavy(notices=notice("Pillow", "12.9.9"))
        self.fails(self.check(), "NOTICES.md", "notices", "pillow 13.0.0")

    def test_a_row_is_found_by_normalised_name(self):
        self.heavy(notices=notice("PILLOW", "13.0.0"))
        self.assertEqual([l for l in self.check() if l.startswith("NOTICES.md")], [])

    def test_native_extras_need_their_own_rows(self):
        packages = {"imageio-ffmpeg": ("0.8.1", [H1]), "av": ("18.1.0", [H2]), "espeakng-loader": ("0.2.4", [H1]),
                    "kokoro-onnx": ("0.6.1", [H2]), "faster-whisper": ("1.2.1", [H3])}
        deps = ["%s==%s" % (n, v[0]) for n, v in packages.items()]
        rows = "".join(notice(n, v[0]) for n, v in packages.items())
        self.heavy(packages=packages, deps=deps, notices=rows)
        lines = self.check()
        for words in ("ffmpeg binary", "ffmpeg libraries", "espeak-ng", "kokoro-82m", "whisper base.en"):
            self.fails(lines, "NOTICES.md", "notices", '"%s"' % words)
        extras = (notice("FFmpeg binary (imageio-ffmpeg)", "9.0", "GPL-2.0-or-later") + notice("FFmpeg libraries (in av)", "8.1", "LGPL-3.0-or-later")
                  + notice("espeak-ng (in espeakng-loader)", "1.52", "GPL-3.0-or-later") + notice("Kokoro-82M weights", "1.0", "Apache-2.0")
                  + notice("Whisper base.en (CTranslate2)", "revision 3d3d5dee", "MIT"))
        edit(self.root, "NOTICES.md", NOTICE_HEADER, NOTICE_HEADER + extras)
        self.assertEqual([l for l in self.check() if l.startswith("NOTICES.md")], [])

    def test_a_gpl_row_never_says_bundled(self):
        self.heavy(notices=notice("Pillow", "13.0.0", licence="GPL-3.0-or-later", used="bundled in the kit"))
        self.fails(self.check(), "NOTICES.md", "notices", "bundled")
        self.heavy(notices=notice("Pillow", "13.0.0", licence="LGPL-3.0-or-later", used="bundled in the kit"))
        self.assertEqual([l for l in self.check() if "bundled" in l], [])

    def test_the_notices_table_must_have_its_columns(self):
        put(self.root, "NOTICES.md", "# Notices\n\n| Name | Version |\n|---|---|\n| a | 1 |\n")
        self.fails(self.check(), "NOTICES.md", "notices", "columns")

    def test_a_font_family_needs_its_licence_file_and_a_row(self):
        font = b"\x00\x01\x00\x00" + b"\x00" * 64
        put(self.root, "skills/hello/assets/fonts/anton/Anton-Regular.ttf", font)
        lines = self.check()
        self.fails(lines, "skills/hello/assets/fonts/anton", "notices", "OFL.txt")
        self.fails(lines, "NOTICES.md", "notices", "font family anton")
        put(self.root, "skills/hello/assets/fonts/anton/OFL.txt", "This is a licence.\r\n")
        self.fails(self.check(), "skills/hello/assets/fonts/anton/OFL.txt", "notices", "Open Font License")
        put(self.root, "skills/hello/assets/fonts/anton/OFL.txt", "SIL OPEN FONT LICENSE Version 1.1\r\nline \r\n ")
        edit(self.root, "NOTICES.md", NOTICE_HEADER, NOTICE_HEADER + notice("Anton", "google/fonts cc39c4c", "OFL-1.1", by="timeline"))
        self.write()
        self.assertEqual([l for l in self.check() if "anton" in l.lower()], [])

    def test_a_font_file_must_be_a_font(self):
        put(self.root, "skills/hello/assets/fonts/anton/Anton-Regular.ttf", b"not a font at all")
        self.fails(self.check(), "skills/hello/assets/fonts/anton/Anton-Regular.ttf", "media", "TrueType")


class Examples(Repo):
    def post(self, **changes):
        data = dict(POST)
        data.update(changes)
        put(self.root, "skills/hello/examples/post.json", json.dumps(data, indent=2) + "\n")

    def test_the_readme_rules(self):
        path = "skills/hello/examples/README.md"
        put(self.root, path, EXAMPLES_README.replace(rules.EXAMPLE_FIRST_LINE, "Made from the example story."))
        self.fails(self.check(), path, "examples", "first line")
        put(self.root, path, EXAMPLES_README.replace(rules.EXAMPLE_MACHINE, "a computer"))
        self.fails(self.check(), path, "examples", "machine")
        put(self.root, path, EXAMPLES_README.replace("`post.json`", "the post"))
        self.fails(self.check(), path, "examples", "doesn't name post.json")
        put(self.root, path, EXAMPLES_README.replace("hi.py", "it"))
        self.fails(self.check(), path, "examples", "hi.py")
        os.remove(Path(self.root) / path)
        self.fails(self.check(), path, "examples", "missing")

    def test_a_missing_post(self):
        os.remove(Path(self.root) / "skills/hello/examples/post.json")
        put(self.root, "skills/hello/examples/README.md", EXAMPLES_README.replace("`post.json`", "nothing"))
        self.fails(self.check(), "skills/hello/examples/post.json", "examples", "missing")

    def test_the_post_rules(self):
        path = "skills/hello/examples/post.json"
        cases = {
            "storyId": dict(storyId="00000000-0000-7000-8000-000000000000"),
            "requestId": dict(requestId="x"),
            "format must be": dict(format="meme"),
            "kind is one of": dict(kind="story"),
            "body is": dict(body="x" * 5001),
            "control or invisible": dict(body="a bell \x07 in it"),
            "sources": dict(sources=["http://example.com/a"]),
            "sources:": dict(sources=["https://example.com/%d" % i for i in range(11)]),
            "unknown key": dict(extra=1),
            "a text post has no media": dict(media={"file": "x.png", "description": "d"}),
        }
        for words, change in cases.items():
            with self.subTest(words):
                self.post(**change)
                self.fails(self.check(), path, "examples", words)

    def test_a_translation_may_carry_the_original_words(self):
        # Devanagari, accents and the rupee sign are fine in a post (plain_text), though not in SKILL.md.
        words = "".join(chr(c) for c in (0x939, 0x93F, 0x928, 0x94D, 0x926, 0x940)) + " " + chr(0xE9) + " " + chr(0x20B9) + "450"
        self.post(body="The notice says: " + words)
        self.assertEqual([l for l in self.check() if "post.json" in l], [])

    def test_sources_are_hrizzups_web_addresses(self):
        path = "skills/hello/examples/post.json"
        good = ["https://example.com/a", "https://example.com/a%20b?x=1&y=(2)#frag", "https://sub.example.co.in:8443/p;q=1,2",
                "https://example.com/it's~ok_(x)*+!$@:"]
        self.post(sources=good)
        self.assertEqual([l for l in self.check() if "sources" in l], [], good)
        bad = {
            "a space": "https://example.com/a b", "a bad %": "https://example.com/%zz", "% at the end": "https://example.com/a%",
            "non-ASCII": "https://example.com/caf" + chr(0xE9), "a double quote": 'https://example.com/a"b', "angle brackets": "https://example.com/<a>",
            "a backslash": "https://example.com/a" + chr(92) + "b", "a new line at the end": "https://example.com/a\n",
            "http": "http://example.com/a", "no dot in the host": "https://localhost/a", "a user name": "https://user" + "@" + "example.com/a",
            "an under score host": "https://exa_mple.com/a", "too long": "https://example.com/" + "a" * 2040, "not text": 5,
        }
        for label, source in bad.items():
            with self.subTest(label):
                self.post(sources=[source])
                self.fails(self.check(), path, "examples", "sources")

    def test_post_that_isnt_json(self):
        put(self.root, "skills/hello/examples/post.json", "{not json")
        self.fails(self.check(), "skills/hello/examples/post.json", "examples", "valid JSON")

    def retarget(self, code, kind="image"):
        edit(self.root, "skills/hello/SKILL.md", '"breakdown"', '"%s"' % code)
        edit(self.root, "skills/hello/SKILL.md", "`breakdown`", "`%s`" % code)
        self.post(kind=kind, format=code, body="A caption.")

    def test_an_image_post_with_its_picture_and_size(self):
        self.retarget("meme")
        put(self.root, "skills/hello/examples/meme.png", built.png(1080, 1080))
        put(self.root, "skills/hello/examples/README.md", EXAMPLES_README.replace("`post.json`", "`post.json`, `meme.png`"))
        self.post(kind="image", format="meme", body="A caption.", media={"file": "meme.png", "description": "A plain square."})
        self.write()
        self.clean()
        put(self.root, "skills/hello/examples/meme.png", built.png(1080, 1000))
        self.fails(self.check(), "skills/hello/examples/post.json", "examples", "Hrizzup wants 1080x1080 or 1080x1350")

    def test_an_image_post_needs_its_media(self):
        self.retarget("meme")
        self.fails(self.check(), "skills/hello/examples/post.json", "examples", "needs media")
        self.post(kind="image", format="meme", body="A caption.", media={"file": "nope.png", "description": "x"})
        self.fails(self.check(), "skills/hello/examples/post.json", "examples", "nope.png")

    def test_a_video_post(self):
        self.retarget("explainer", kind="video")
        video = built.ftyp() + built.video_moov(30000) + built.mdat()
        put(self.root, "skills/hello/examples/v.mp4", video)
        put(self.root, "skills/hello/examples/still.png", built.png(1080, 1920))
        put(self.root, "skills/hello/examples/README.md", EXAMPLES_README.replace("`post.json`", "`post.json`, `v.mp4`, `still.png`"))
        media = {"file": "v.mp4", "transcript": "The shown text.", "still": {"file": "still.png", "description": "A plain card."}}
        self.post(kind="video", format="explainer", body="A caption.", media=media)
        self.write()
        self.clean()
        put(self.root, "skills/hello/examples/still.png", built.png(1080, 1080))
        self.fails(self.check(), "skills/hello/examples/post.json", "examples", "1080x1920")
        put(self.root, "skills/hello/examples/still.png", built.png(1080, 1920))
        put(self.root, "skills/hello/examples/v.mp4", built.ftyp() + built.video_moov(70000) + built.mdat())
        self.fails(self.check(), "skills/hello/examples/v.mp4", "media", "58.0")

    def test_media_over_budget_or_damaged(self):
        put(self.root, "skills/hello/examples/big.png", built.png(100, 100) + b"\x00" * (rules_budget() + 10))
        put(self.root, "skills/hello/examples/bad.png", b"not a png")
        put(self.root, "skills/hello/examples/tall.png", built.png(100, 5000))
        put(self.root, "skills/hello/examples/cut.mp4", (built.ftyp() + built.video_moov() + built.mdat())[:40])
        put(self.root, "skills/hello/examples/README.md", EXAMPLES_README.replace("`post.json`", "`post.json`, `big.png`, `bad.png`, `tall.png`, `cut.mp4`"))
        lines = self.check()
        self.fails(lines, "skills/hello/examples/big.png", "media", "budget")
        self.fails(lines, "skills/hello/examples/bad.png", "media", "not a PNG")
        self.fails(lines, "skills/hello/examples/tall.png", "media", "4096")
        self.fails(lines, "skills/hello/examples/cut.mp4", "media", "cut short")

    def test_audio_needs_the_m4a_brand(self):
        moov = built.box(b"moov", built.mvhd(48000, 48000 * 10) + built.trak(b"soun", b"mp4a"))
        put(self.root, "skills/hello/examples/a.m4a", built.ftyp(b"isom") + moov + built.mdat())
        put(self.root, "skills/hello/examples/README.md", EXAMPLES_README.replace("`post.json`", "`post.json`, `a.m4a`"))
        self.fails(self.check(), "skills/hello/examples/a.m4a", "media", "M4A")
        put(self.root, "skills/hello/examples/a.m4a", built.ftyp(b"M4A ") + moov + built.mdat())
        self.assertEqual([l for l in self.check() if "a.m4a" in l], [])


def rules_budget():
    return catalogue.media.IMAGE_BUDGET_BYTES


GOOD_TEMPLATE = {
    "id": "caption-bar", "sizes": [[1080, 1080], [1080, 1350]], "background": "paper",
    "picture": {"box": [0, 0, 1, 0.8], "required": True},
    "texts": [{"slot": "caption", "box": [0.05, 0.82, 0.95, 0.97], "font": "display", "max": 96, "min": 40,
               "lines": 2, "align": "center", "on": "paper", "case": "upper"}],
    "signature": {"box": [0.6, 0.95, 0.95, 0.99], "align": "right"},
}


class Templates(Repo):
    """Templates are JSON in assets/templates/ (design 8.1): a fixed shape, and no colours of their own."""

    def problems(self, **changes):
        template = json.loads(json.dumps(GOOD_TEMPLATE))
        template.update(changes)
        return catalogue.template_problems("caption-bar", template)

    def test_a_good_template_and_one_in_the_tree(self):
        self.assertEqual(self.problems(), [])
        put(self.root, "skills/hello/assets/templates/caption-bar.json", json.dumps(GOOD_TEMPLATE, indent=2) + "\n")
        self.write()
        self.clean()

    def test_a_template_with_no_picture_and_no_signature(self):
        self.assertEqual(self.problems(picture=None, signature=None, texts=[]), [])

    def test_each_rule(self):
        cases = {
            "keys": dict(extra=1),
            "id": dict(id="other"),
            "sizes": dict(sizes=[[1080]]),
            "sizes ": dict(sizes=[[5000, 10]]),
            "background": dict(background="red"),
            "picture": dict(picture={"box": [0, 0, 1, 1]}),
            "picture.box": dict(picture={"box": [0, 0, 2, 1], "required": False}),
            "signature": dict(signature={"box": [0, 0, 1, 1], "align": "up"}),
            "texts is": dict(texts="x"),
        }
        for words, change in cases.items():
            with self.subTest(words):
                self.assertTrue(self.problems(**change), words)

    def test_each_text_rule(self):
        base = GOOD_TEMPLATE["texts"][0]
        cases = {
            "keys": dict(base, extra=1), "font": dict(base, font="comic"), "box": dict(base, box=[0.9, 0, 0.1, 1]),
            "min": dict(base, min=100, max=50), "lines": dict(base, lines=0), "align": dict(base, align="top"),
            "on": dict(base, on="sky"), "case": dict(base, case="lower"), "slot": dict(base, slot="Bad Slot"),
        }
        for words, text in cases.items():
            with self.subTest(words):
                self.assertTrue(self.problems(texts=[text]), words)
        self.assertTrue(self.problems(texts=[base, dict(base)]))  # the same slot twice
        self.assertIn("no picture", " ".join(self.problems(picture=None, texts=[dict(base, on="picture")])))

    def test_no_colours_of_its_own(self):
        text = dict(GOOD_TEMPLATE["texts"][0], slot="colour-bar")
        self.assertIn("no colours", " ".join(self.problems(texts=[text])))
        template = json.loads(json.dumps(GOOD_TEMPLATE))
        template["background"] = "#FFFFFF"
        self.assertTrue(catalogue.template_problems("caption-bar", template))

    def test_a_bad_template_in_the_tree_fails_check(self):
        put(self.root, "skills/hello/assets/templates/caption-bar.json", json.dumps(dict(GOOD_TEMPLATE, background="red")) + "\n")
        self.fails(self.check(), "skills/hello/assets/templates/caption-bar.json", "template", "background")
        put(self.root, "skills/hello/assets/templates/caption-bar.json", "{not json\n")
        self.fails(self.check(), "skills/hello/assets/templates/caption-bar.json", "template", "valid JSON")


class KitSize(Repo):
    def test_a_kit_over_3_mib_without_the_samples(self):
        path = Path(self.root) / "skills/hello/assets/big.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(b" " * (rules.KIT_MAX_BYTES + 1))
        self.fails(self.check(), "skills/hello", "kit", "over 3145728")

    def test_samples_are_not_counted(self):
        with open(Path(self.root) / "skills/hello/examples/big.json", "wb") as f:
            f.write(b" " * (rules.KIT_MAX_BYTES + 1))
        self.assertEqual([l for l in self.check() if ": kit:" in l], [])


class TheDesign(unittest.TestCase):
    def test_the_pins_table_is_rules_pins(self):
        text = (REAL / "docs/design.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\s*\| `([a-z0-9-]+)` \| `([0-9][^`]*)` \|", text, re.M)
        self.assertEqual(dict(rows), rules.PINS)
        self.assertIn('exclude-newer = "%s"' % rules.EXCLUDE_NEWER, text)

    def test_the_design_values_the_code_repeats(self):
        text = (REAL / "docs/design.md").read_text(encoding="utf-8")
        for value in (rules.STORY_ID, rules.REPO, *rules.FORMATS):
            self.assertIn(value, text)


class TextTypes(unittest.TestCase):
    """The API's `plain_text` (body, description) and `longText` (transcript), as the agreement writes them.

    Every unusual character is built with chr(), so this file holds none of them.
    """

    def test_plain_text_takes_any_visible_character_and_new_lines_inside(self):
        samples = [
            "Plain words.", "A caf" + chr(0xE9) + ", and " + chr(0x20B9) + "450.",
            "".join(chr(c) for c in (0x939, 0x93F, 0x928, 0x94D, 0x926, 0x940)),  # Devanagari
            chr(0x1F600) + " an emoji", "two\nlines", chr(0x1F468) + chr(0x200D) + chr(0x1F469) + " a joined emoji",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(rules.plain_text_problems("body", text, 5000), [])

    def test_plain_text_refuses_what_the_agreement_refuses(self):
        bad = {
            "empty": "", "leading space": " a", "trailing space": "a ", "leading new line": "\na", "trailing new line": "a\n",
            "a tab": "a\tb", "a bell": "a" + chr(7), "NUL": chr(0), "DEL": chr(0x7F), "C1 control": chr(0x85),
            "soft hyphen": "a" + chr(0xAD) + "b", "zero-width space": "a" + chr(0x200B) + "b", "bidi mark": "a" + chr(0x202E),
            "private use": chr(0xE000), "BOM": chr(0xFEFF) + "a", "variation selector": "a" + chr(0xFE00),
            "too long": "x" * 5001, "not text": 5,
        }
        for label, text in bad.items():
            with self.subTest(label):
                self.assertTrue(rules.plain_text_problems("body", text, 5000), label)

    def test_the_code_checks_of_the_other_planes(self):
        # agreement.passes_code_checks: these ranges, for plain_text and longText alike.
        refused = (0x110BD, 0x110CD, 0x13430, 0x1343F, 0x1BCA0, 0x1BCA3, 0x1D173, 0x1D17A, 0xE0000, 0xE0001, 0xE007F, 0xE0100, 0xE0FFF,
                   0xF0000, 0xFFFFD, 0x100000, 0x10FFFD)
        allowed = (0x110BC, 0x110BE, 0x1342F, 0x13440, 0x1BC9F, 0x1BCA4, 0x1D172, 0x1D17B, 0xE1000, 0x1F600, 0x1F468, 0x20000)
        for code in refused:
            with self.subTest(refused=hex(code)):
                self.assertTrue(rules.plain_text_problems("b", "a" + chr(code) + "b", 100))
                self.assertTrue(rules.long_text_problems("t", "a" + chr(code) + "b", 100))
        for code in allowed:
            with self.subTest(allowed=hex(code)):
                self.assertEqual(rules.plain_text_problems("b", "a" + chr(code) + "b", 100), [])
                self.assertEqual(rules.long_text_problems("t", "a" + chr(code) + "b", 100), [])
        self.assertEqual(len(rules.ASTRAL_HIDDEN_RANGES), 8)

    def test_plain_text_has_the_other_code_checks_too(self):
        joiner = chr(0x200D)
        bad = {"stacked selectors": "a" + chr(0xFE0F) * 2, "joiner by a letter": "a" + joiner + "b", "joiner at the end": "a" + chr(0x1F468) + joiner,
               "joiner at the start": joiner + chr(0x1F468), "doubled joiner": chr(0x1F468) + joiner * 2 + chr(0x1F469),
               "joiner by a new line": chr(0x1F468) + joiner + "\n" + chr(0x1F469)}
        for label, text in bad.items():
            with self.subTest(label):
                self.assertTrue(rules.plain_text_problems("b", text, 100))
        self.assertEqual(rules.plain_text_problems("b", chr(0x1F468) + joiner + chr(0x1F469) + chr(0xFE0F), 100), [])

    def test_the_ranges_are_the_agreements_24(self):
        self.assertEqual(len(rules.HIDDEN_RANGES), 24)
        self.assertFalse(rules.hidden(chr(0x200D)))  # the joiner inside emoji is allowed

    def test_long_text_takes_tabs_and_new_lines_and_any_script(self):
        text = "Line one\n\tIndented " + chr(0x20B9) + " and " + chr(0x928) + "\n\nLine three"
        self.assertEqual(rules.long_text_problems("transcript", text, 20000), [])
        joined = chr(0x1F468) + chr(0x200D) + chr(0x1F469)
        self.assertEqual(rules.long_text_problems("transcript", joined, 20000), [])
        self.assertEqual(rules.long_text_problems("transcript", chr(0x2764) + chr(0xFE0F), 20000), [])

    def test_long_text_refuses_what_the_api_refuses(self):
        bad = {
            "empty": "", "escape": "a" + chr(0x1B) + "[0m", "carriage return": "a\r\nb", "NUL": chr(0), "DEL": chr(0x7F),
            "final new line": "a\n", "zero-width space": "a" + chr(0x200B), "private use": chr(0xE000),
            "stacked selectors": "a" + chr(0xFE0F) * 2, "joiner at the end": "a" + chr(0x200D), "joiner by a letter": "a" + chr(0x200D) + "b",
            "doubled joiner": chr(0x1F468) + chr(0x200D) * 2 + chr(0x1F469), "too long": "x" * 20001,
        }
        for label, text in bad.items():
            with self.subTest(label):
                self.assertTrue(rules.long_text_problems("transcript", text, 20000), label)

    def test_a_leading_space_is_fine_in_a_transcript_but_not_a_body(self):
        self.assertEqual(rules.long_text_problems("t", " a", 100), [])
        self.assertTrue(rules.plain_text_problems("b", " a", 100))


class Catalogue(Repo):
    """skills-catalogue.md's rules, on a catalogue the repository would make with a broken input."""

    def problems_of(self, document):
        P = catalogue.Problems()
        text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        catalogue.check_catalogue(document, text, P)
        return P.lines()

    def item(self, **changes):
        document = json.loads(read(self.root, "catalogue.json"))
        item = document["items"][0]
        item.update(changes)
        item["contentHash"] = catalogue.content_hash(item)
        return document

    def test_a_good_catalogue_has_none(self):
        self.assertEqual(self.problems_of(json.loads(read(self.root, "catalogue.json"))), [])

    def test_each_field_rule(self):
        cases = {
            "slug": dict(slug="Hello"), "name": dict(name=""), "summary": dict(summary="x" * 301),
            "needs": dict(needs="x" * 301), "format": dict(format="podcast"), "path": dict(path="skills/other"),
            "kind": dict(kind="plugin"), "body": dict(body="x\n"), "body is": dict(body=""),
        }
        for words, change in cases.items():
            with self.subTest(words):
                self.assertTrue(self.problems_of(self.item(**change)), words)

    def test_a_wrong_hash(self):
        document = json.loads(read(self.root, "catalogue.json"))
        document["items"][0]["contentHash"] = "0" * 64
        self.assertIn("isn't the hash", " ".join(self.problems_of(document)))
        document["items"][0]["contentHash"] = "ABC"
        self.assertIn("64 lower-case hex", " ".join(self.problems_of(document)))

    def test_a_body_of_501_lines(self):
        self.assertIn("500 lines", " ".join(self.problems_of(self.item(body="\n".join(["a"] * 501)))))

    def test_the_kit_rules(self):
        document = json.loads(read(self.root, "catalogue.json"))
        document["items"][0]["meta"]["kit"] = ["scripts/hi.py", "references/guide.md", "scripts/hrizzup_media.py"]
        document["items"][0]["contentHash"] = catalogue.content_hash(document["items"][0])
        self.assertIn("sorted", " ".join(self.problems_of(document)))
        document = json.loads(read(self.root, "catalogue.json"))
        document["items"][0]["meta"]["kitSha256"]["x.md"] = H1
        self.assertIn("kitSha256", " ".join(self.problems_of(document)))

    def test_items_sorted_by_kind_then_slug_and_unique(self):
        document = json.loads(read(self.root, "catalogue.json"))
        document["items"].reverse()
        self.assertIn("sorted by kind", " ".join(self.problems_of(document)))
        document["items"] = [document["items"][1], dict(document["items"][1])]
        self.assertIn("used twice", " ".join(self.problems_of(document)))

    def test_agent_skills_must_resolve_and_be_one_to_five(self):
        document = json.loads(read(self.root, "catalogue.json"))
        agent = document["items"][1]
        agent["meta"]["skills"] = ["ghost"]
        agent["contentHash"] = catalogue.content_hash(agent)
        self.assertIn("ghost", " ".join(self.problems_of(document)))
        agent["meta"]["skills"] = []
        self.assertIn("one to 5", " ".join(self.problems_of(document)))
        agent["meta"]["skills"] = ["hello", "hello"]
        self.assertIn("no repeats", " ".join(self.problems_of(document)))

    def test_the_file_is_under_1_mib_and_has_its_keys(self):
        P = catalogue.Problems()
        catalogue.check_catalogue({"version": 1, "items": []}, "x" * (rules.CATALOGUE_MAX_BYTES + 1), P)
        self.assertIn("1 MiB", " ".join(P.lines()))
        self.assertIn("must be", " ".join(self.problems_of({"version": 2, "items": []})))
        document = json.loads(read(self.root, "catalogue.json"))
        document["items"][0]["extra"] = 1
        self.assertIn("exactly these keys", " ".join(self.problems_of(document)))


class Retirement(Repo):
    def git(self, *args):
        subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@users.noreply.github.com", "-c", "commit.gpgsign=false", *args],
                       cwd=self.root, check=True, capture_output=True)

    def commit_golden(self):
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=True).stdout.strip()

    def test_a_removed_skill_must_be_retired_first(self):
        base = self.commit_golden()
        shutil.rmtree(Path(self.root) / "skills/hello")
        shutil.rmtree(Path(self.root) / "agents/greeter")
        self.write()
        lines = self.check(base=base)
        self.fails(lines, "catalogue.json", "retirement", "hello is gone")
        self.fails(lines, "catalogue.json", "retirement", "greeter is gone")
        put(self.root, "retired.txt", read(self.root, "retired.txt") + "hello\ngreeter\n")
        self.assertEqual([l for l in self.check(base=base) if "retirement" in l], [])

    def test_a_removed_kit_path_must_be_retired_first(self):
        base = self.commit_golden()
        os.remove(Path(self.root) / "skills/hello/references/guide.md")
        edit(self.root, "skills/hello/SKILL.md", ", then read `references/guide.md`", "")
        self.write()
        self.fails(self.check(base=base), "skills/hello/references/guide.md", "retirement", "kit path")
        put(self.root, "retired.txt", read(self.root, "retired.txt") + "skills/hello/references/guide.md\n")
        self.assertEqual([l for l in self.check(base=base) if "retirement" in l], [])

    def test_a_renamed_kit_path_is_a_removal(self):
        base = self.commit_golden()
        os.rename(Path(self.root) / "skills/hello/references/guide.md", Path(self.root) / "skills/hello/references/handbook.md")
        edit(self.root, "skills/hello/SKILL.md", "references/guide.md", "references/handbook.md")
        self.write()
        self.fails(self.check(base=base), "skills/hello/references/guide.md", "retirement", "never renamed")

    def test_a_retired_slug_never_comes_back(self):
        put(self.root, "retired.txt", read(self.root, "retired.txt") + "hello\n")
        self.fails(self.check(), "retired.txt", "retirement", "never reused")

    def test_the_base_is_skipped_with_a_note(self):
        for base in (None, "", "0" * 40):
            with self.subTest(base=base):
                lines, notes = catalogue.check(self.root, base=base, run_help_checks=False)
                self.assertEqual(lines, [])
                self.assertIn("skipped", " ".join(notes))
        base = self.commit_golden()
        self.git("rm", "-q", "--cached", "catalogue.json")
        self.git("commit", "-q", "-m", "no catalogue")
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True, check=True).stdout.strip()
        lines, notes = catalogue.check(self.root, base=head, run_help_checks=False)
        self.assertIn("no catalogue.json", " ".join(notes))
        self.assertEqual(base != head, True)

    def test_retired_txt_only_grows(self):
        put(self.root, "retired.txt", read(self.root, "retired.txt") + "oldslug\nskills/hello/references/old.md\n")
        base = self.commit_golden()
        # A pull request that deletes the lines, then brings the slug back, must fail.
        put(self.root, "retired.txt", "# nothing retired\n")
        lines = self.check(base=base)
        self.fails(lines, "retired.txt", "retirement", "oldslug was retired on the base commit and is missing now")
        self.fails(lines, "retired.txt", "retirement", "skills/hello/references/old.md was retired")
        put(self.root, "retired.txt", read(self.root, "retired.txt") + "oldslug\nskills/hello/references/old.md\nanother\n")
        self.assertEqual([l for l in self.check(base=base) if "retirement" in l], [])  # adding is fine

    def test_a_comment_only_retired_file_has_nothing_to_keep(self):
        base = self.commit_golden()
        put(self.root, "retired.txt", "")
        self.assertEqual([l for l in self.check(base=base) if "retirement" in l], [])

    def test_an_unknown_base_commit_is_a_problem_not_a_note(self):
        self.commit_golden()
        for base in ("1" * 40, "deadbeef", "no-such-branch"):
            with self.subTest(base=base):
                lines, notes = catalogue.check(self.root, base=base, run_help_checks=False)
                self.fails(lines, "--base", "retirement", "isn't a commit")
                self.assertNotIn("skipped", " ".join(notes))
        done = subprocess.run([sys.executable, str(REAL / "tools/catalogue.py"), "--root", self.root, "check", "--base", "1" * 40],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 1, done.stdout)

    def test_a_base_that_looks_like_an_option_is_never_given_to_git(self):
        self.commit_golden()
        for base in ("-h", "--version", "--output=x"):
            with self.subTest(base=base):
                lines, _ = catalogue.check(self.root, base=base, run_help_checks=False)
                self.fails(lines, "--base", "retirement", "isn't a commit")

    def test_a_base_in_a_folder_that_is_not_a_repository_is_a_problem_too(self):
        lines, _ = catalogue.check(self.root, base="abc1234", run_help_checks=False)
        self.fails(lines, "--base", "retirement", "isn't a commit")

    def test_a_bad_retired_line(self):
        put(self.root, "retired.txt", "# comment\n\nNot A Slug\n")
        self.fails(self.check(), "retired.txt", "retirement", "line 3")


GOOD_WORKFLOW = """name: x
on:
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  one:
    name: One
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - run: echo "${{ github.sha }}"
      - name: with env
        env:
          TITLE: ${{ github.event.pull_request.title }}
        run: echo "$TITLE"
"""


class Workflows(Repo):
    def problems(self, text):
        P = catalogue.Problems()
        catalogue.check_workflow(".github/workflows/x.yml", text, P)
        return P.lines()

    def test_the_good_one_and_the_real_checks_file(self):
        self.assertEqual(self.problems(GOOD_WORKFLOW), [])
        self.assertEqual(self.problems((REAL / ".github/workflows/checks.yml").read_text(encoding="utf-8")), [])

    def test_dangerous_triggers(self):
        for event in ("pull_request_target", "workflow_run"):
            with self.subTest(event):
                text = GOOD_WORKFLOW.replace("  pull_request:\n", "  %s:\n" % event)
                self.assertIn(event, " ".join(self.problems(text)))
        self.assertIn(
            "pull_request_target", " ".join(self.problems(GOOD_WORKFLOW.replace("on:\n  pull_request:\n  workflow_dispatch:\n", "on: [push, pull_request_target]\n"))))

    def test_the_dangerous_words_fail_closed_in_every_spelling(self):
        quote = chr(34)
        forms = {
            "double-quoted key": GOOD_WORKFLOW.replace("  pull_request:\n", "  " + quote + "pull_request_target" + quote + ":\n"),
            "single-quoted key": GOOD_WORKFLOW.replace("  pull_request:\n", "  'workflow_run':\n    workflows: [x]\n"),
            "flow sequence": GOOD_WORKFLOW.replace("on:\n  pull_request:\n  workflow_dispatch:\n", "on: [push, pull_request_target]\n"),
            "flow mapping": GOOD_WORKFLOW.replace("on:\n  pull_request:\n  workflow_dispatch:\n", "on: {workflow_run: {workflows: [x], types: [completed]}}\n"),
            "multi-line flow": GOOD_WORKFLOW.replace("on:\n  pull_request:\n  workflow_dispatch:\n", "on: [\n  push,\n  pull_request_target,\n]\n"),
            "after a comment mark inside a string": GOOD_WORKFLOW.replace("on:\n  pull_request:\n  workflow_dispatch:\n", "on: [" + quote + "a # b" + quote + ", pull_request_target]\n"),
            "a YAML escape": GOOD_WORKFLOW.replace("on:\n  pull_request:\n  workflow_dispatch:\n", "on: {" + quote + "pull_request" + chr(92) + "x5ftarget" + quote + ": null}\n"),
            "a unicode escape": GOOD_WORKFLOW.replace("on:\n  pull_request:\n  workflow_dispatch:\n", "on: {" + quote + "workflow" + chr(92) + "u005frun" + quote + ": null}\n"),
            "in a condition": GOOD_WORKFLOW.replace("    runs-on:", "    if: github.event_name == 'workflow_run'\n    runs-on:"),
        }
        for label, text in forms.items():
            with self.subTest(label):
                found = " ".join(self.problems(text))
                self.assertTrue("pull_request_target" in found or "workflow_run" in found, found)

    def test_a_whole_line_comment_may_name_them(self):
        text = "# never pull_request_target or workflow_run here\n" + GOOD_WORKFLOW
        self.assertEqual(self.problems(text), [])

    def test_an_action_must_be_pinned_to_a_commit(self):
        self.assertIn("pin actions/checkout@v4", " ".join(self.problems(GOOD_WORKFLOW.replace("3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1", "v4"))))
        short = GOOD_WORKFLOW.replace("3d3c42e5aac5ba805825da76410c181273ba90b1", "3d3c42e")
        self.assertIn("full commit SHA", " ".join(self.problems(short)))

    def test_permissions_are_written_down(self):
        self.assertIn("permissions", " ".join(self.problems(GOOD_WORKFLOW.replace("permissions:\n  contents: read\n", ""))))
        self.assertIn("write-all", " ".join(self.problems(GOOD_WORKFLOW.replace("contents: read", "write-all"))))

    def test_text_someone_else_can_choose_goes_through_env(self):
        bad = GOOD_WORKFLOW.replace('echo "$TITLE"', 'echo "${{ github.event.pull_request.title }}"')
        self.assertIn("through env:", " ".join(self.problems(bad)))
        self.assertIn("github.head_ref", " ".join(self.problems(GOOD_WORKFLOW.replace('"${{ github.sha }}"', '"${{ github.head_ref }}"'))))

    def test_only_githubs_machines(self):
        self.assertIn("self-hosted", " ".join(self.problems(GOOD_WORKFLOW.replace("ubuntu-24.04", "self-hosted"))))

    def test_the_two_required_jobs_must_exist(self):
        edit(self.root, ".github/workflows/checks.yml", "    name: Secret check", "    name: Secrets")
        self.fails(self.check(), ".github/workflows/checks.yml", "workflow", "Secret check")
        os.remove(Path(self.root) / ".github/workflows/checks.yml")
        self.fails(self.check(), ".github/workflows/checks.yml", "workflow", "missing")

    def test_a_workflow_file_in_the_tree_is_checked(self):
        put(self.root, ".github/workflows/extra.yml", GOOD_WORKFLOW.replace("pull_request:", "pull_request_target:"))
        self.fails(self.check(), ".github/workflows/extra.yml", "workflow", "pull_request_target")

    def test_the_real_checks_workflow_has_the_design_values(self):
        text = (REAL / ".github/workflows/checks.yml").read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("ubuntu-24.04", text)
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1", text)
        self.assertIn("551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb", text)
        self.assertIn("gitleaks git --redact --no-banner --verbose .", text)
        self.assertIn("github.event.pull_request.base.sha || github.event.before", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("persist-credentials: false", text)
        self.assertEqual(text.count("timeout-minutes: 10"), 2)


def home():
    return "/" + "Users" + "/someone/projects"


def linux_home():
    return "/" + "home" + "/someone"


def windows_home():
    return "C:" + chr(92) + "Users" + chr(92) + "someone"


def windows_home_escaped():
    """How JSON and Python source write it: each backslash doubled."""
    return "C:" + chr(92) * 2 + "Users" + chr(92) * 2 + "someone"


def address(who="someone", domain="example.org"):
    return who + "@" + domain


class PublicRepository(Repo):
    def test_home_folder_paths(self):
        for label, path in (("mac", home()), ("linux", linux_home()), ("windows", windows_home()), ("escaped", windows_home_escaped())):
            with self.subTest(label):
                put(self.root, "skills/hello/references/guide.md", "# Guide\n\nSee %s for it.\n" % path)
                self.fails(self.check(), "skills/hello/references/guide.md", "public", "home-folder path")

    def test_a_path_that_only_looks_similar_is_fine(self):
        put(self.root, "skills/hello/references/guide.md", "# Guide\n\nSee https://example.com/home/page and the Users guide, /home alone.\n")
        self.assertEqual([l for l in self.check() if "public" in l], [])

    def test_email_addresses(self):
        put(self.root, "skills/hello/references/guide.md", "# Guide\n\nWrite to %s.\n" % address())
        self.fails(self.check(), "skills/hello/references/guide.md", "public", "email")

    def test_githubs_noreply_address_is_allowed(self):
        put(self.root, "skills/hello/references/guide.md", "# Guide\n\nBy 12345+someone@users.noreply.github.com.\n")
        self.assertEqual([l for l in self.check() if "public" in l], [])

    def test_a_version_after_an_at_sign_is_not_an_address(self):
        put(self.root, "skills/hello/references/guide.md", "# Guide\n\nUse actions/checkout@v7.0.1 or uv@0.13.1 here.\n")
        self.assertEqual([l for l in self.check() if "public" in l], [])

    def test_text_file_rules(self):
        path = "skills/hello/references/guide.md"
        put(self.root, path, "\ufeff# Guide\n")
        self.fails(self.check(), path, "text", "byte-order mark")
        put(self.root, path, "# Guide\r\n")
        self.fails(self.check(), path, "text", "carriage return")
        put(self.root, path, "# Guide")
        self.fails(self.check(), path, "text", "no final new line")
        put(self.root, path, "# Guide\n\n")
        self.fails(self.check(), path, "text", "more than one")
        put(self.root, path, "# Guide\n\nA zero\u200bwidth space.\n")
        self.fails(self.check(), path, "text", "U+200B")
        put(self.root, path, "# Guide\n\nA \x07 bell.\n")
        self.fails(self.check(), path, "text", "U+0007")
        put(self.root, path, "# Guide\n\nA " + chr(0xFEFF) + " mark in the middle.\n")
        self.fails(self.check(), path, "text", "U+FEFF")
        put(self.root, path, b"# Guide\n\xff\xfe\n")
        self.fails(self.check(), path, "text", "UTF-8")
        put(self.root, path, "# Guide\n\nTabs\tare fine, and so are \u20b9 and \u00e9 in other files.\n")
        self.assertEqual([l for l in self.check() if path in l and "text" in l], [])

    def test_the_licence_file_is_kept_byte_for_byte(self):
        font = b"\x00\x01\x00\x00" + b"\x00" * 64
        put(self.root, "skills/hello/assets/fonts/anton/Anton-Regular.ttf", font)
        put(self.root, "skills/hello/assets/fonts/anton/OFL.txt", "SIL OPEN FONT LICENSE\r\nCopyright \r\nend. ")
        lines = self.check()
        self.assertEqual([l for l in lines if "OFL.txt" in l and ": text:" in l], [])
        put(self.root, "skills/hello/assets/fonts/anton/OFL.txt", "SIL OPEN FONT LICENSE\rlone CR\n")
        self.fails(self.check(), "skills/hello/assets/fonts/anton/OFL.txt", "text", "carriage return")

    # ---- digests the Secret check would flag (gitleaks 8.30.1's generic-api-key) ----

    def test_a_digest_after_a_key_word_is_refused(self):
        path = "skills/hello/references/guide.md"
        for label, line in {
            "json map": '"tokenizer.json": "%s"' % H1,
            "list": '["tokenizer.json", "%s"]' % H1,
            "name tuple": '("tokenizer.json", "%s")' % H1,
            "plain": "tokenizer.json: %s" % H1,
            "key in a path": '"references/key-numbers.md": "%s"' % H1,
            "api": '"references/api-notes.md": "%s"' % H1,
            "secret": 'secret = "%s"' % H1,
        }.items():
            with self.subTest(label):
                put(self.root, path, "# Guide\n\n%s\n" % line)
                self.fails(self.check(), path, "digest", "Secret check")

    def test_digests_stored_the_safe_ways_are_accepted(self):
        path = "skills/hello/references/guide.md"
        safe = [
            "| tokenizer.json | 2,128,466 | %s |" % H1,
            '("%s", 2128466, "tokenizer.json"),' % H1,
            "%s  tokenizer.json" % H1,
            '{"file": "tokenizer.json", "sha256": "%s"}' % H1,
            'hash = "sha256:%s"' % H1,
            "    --hash=sha256:%s \\" % H1,
            '"kitSha256": { "scripts/voice.py": "%s" }' % H1,
        ]
        for line in safe:
            with self.subTest(line=line[:30]):
                put(self.root, path, "# Guide\n\n%s\n" % line)
                self.assertEqual([l for l in self.check() if "digest" in l], [], line)

    def test_a_path_with_a_key_word_is_refused(self):
        for name in ("key-numbers.md", "api-notes.md", "Token-guide.md", "my-secret.md", "auth.md", "passwords.md", "credentials.md", "access-log.md", "creds.md"):
            with self.subTest(name):
                put(self.root, "skills/hello/references/" + name, "# G\n")
                self.fails(self.check(), "skills/hello/references/" + name, "digest", "Secret check")

    def test_the_trap_matches_a_digest_only_when_it_is_64_hex(self):
        self.assertTrue(rules.DIGEST_TRAP.search('"token": "%s"' % H1))
        self.assertFalse(rules.DIGEST_TRAP.search('"token": "%s"' % H1[:60]))
        self.assertFalse(rules.DIGEST_TRAP.search('"token": "%s0"' % H1))

    def test_the_catalogue_with_a_kit_path_is_not_trapped_when_names_are_plain(self):
        self.assertFalse(rules.DIGEST_TRAP.search(read(self.root, "catalogue.json")))


class PythonVersions(unittest.TestCase):
    def test_the_tools_parse_as_python_3_9(self):
        import ast
        for name in sorted(os.listdir(REAL / "tools")):
            if name.endswith(".py") and name != "test_check.py":
                with self.subTest(name):
                    ast.parse((REAL / "tools" / name).read_text(encoding="utf-8"), name, feature_version=(3, 9))

    def test_the_version_guard_comes_before_any_other_import(self):
        source = (REAL / "tools/catalogue.py").read_text(encoding="utf-8")
        guard = source.index("sys.version_info < (3, 12)")
        for needle in ("import rules", "import frontmatter", "import tomllib", "import argparse"):
            self.assertLess(guard, source.index("\n" + needle), needle)

    def test_an_older_python_is_refused_with_the_command_to_use(self):
        older = None
        for name in ("python3.9", "python3.10", "python3.11", "python3"):
            exe = shutil.which(name)
            if exe:
                version = subprocess.run([exe, "-c", "import sys; print(sys.version_info >= (3, 12))"], capture_output=True, text=True).stdout.strip()
                if version == "False":
                    older = exe
                    break
        if older is None:
            self.skipTest("no Python older than 3.12 on this machine; the parse and guard-order tests above cover it")
        done = subprocess.run([older, str(REAL / "tools/catalogue.py"), "check"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        self.assertIn("python3.12", done.stderr)
        self.assertNotIn("Traceback", done.stderr)


if __name__ == "__main__":
    unittest.main()
