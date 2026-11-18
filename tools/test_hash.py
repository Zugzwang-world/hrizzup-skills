"""The contentHash (hrizzup's docs/social/skills-catalogue.md): its worked example, and what changes it."""

import copy
import hashlib
import json
import unittest

import catalogue

KIT_FILE = b'print("hi")\n'
BODY = (
    "---\nname: \"hello\"\n"
    "description: \"Says hello. Use when someone asks you to greet them.\"\n"
    "metadata:\n  hrizzup-name: \"Hello\"\n  hrizzup-summary: \"Says hello.\"\n  hrizzup-needs: \"Nothing\"\n"
    "---\n\n# Hello\n\nRun `scripts/hi.py` — it prints \"hi\"."
)


def worked_example():
    """The item of the catalogue note's worked example, without its contentHash."""
    return {
        "slug": "hello", "kind": "skill", "name": "Hello", "summary": "Says hello.", "needs": None,
        "format": None, "path": "skills/hello", "contentHash": "", "body": BODY,
        "meta": {"kit": ["scripts/hi.py"], "kitSha256": {"scripts/hi.py": hashlib.sha256(KIT_FILE).hexdigest()}},
    }


def canonical(item):
    bare = {k: v for k, v in item.items() if k != "contentHash"}
    return json.dumps(bare, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


class WorkedExample(unittest.TestCase):
    def test_the_kit_file_is_the_notes(self):
        self.assertEqual(len(KIT_FILE), 12)
        self.assertEqual(hashlib.sha256(KIT_FILE).hexdigest(), "0ca9091eb4e31fb1ab24c8c5de92a08e4e5f402919f82ea3ca784f38534f03f3")

    def test_canonical_form_is_515_bytes_on_one_line(self):
        data = canonical(worked_example())
        self.assertEqual(len(data), 515)
        self.assertNotIn(b"\n", data)
        self.assertIn("—".encode("utf-8"), data)  # the dash is written as its three UTF-8 bytes

    def test_hash_is_the_notes(self):
        self.assertEqual(catalogue.content_hash(worked_example()),
                         "f8df1f487b6e8bf444e5599db7fc262a774ff629267e3ea36004948d0c216549")

    def test_a_stored_hash_doesnt_change_it(self):
        item = worked_example()
        item["contentHash"] = "0" * 64
        self.assertEqual(catalogue.content_hash(item), catalogue.content_hash(worked_example()))


class WhatChangesIt(unittest.TestCase):
    def setUp(self):
        self.base = catalogue.content_hash(worked_example())

    def changed(self, edit):
        item = copy.deepcopy(worked_example())
        edit(item)
        return catalogue.content_hash(item)

    def test_every_field_counts(self):
        edits = {
            "slug": lambda i: i.update(slug="hello2"),
            "kind": lambda i: i.update(kind="starter-agent"),
            "name": lambda i: i.update(name="Hello!"),
            "summary": lambda i: i.update(summary="Says hello!"),
            "needs": lambda i: i.update(needs="A tool"),
            "format": lambda i: i.update(format="meme"),
            "path": lambda i: i.update(path="skills/other"),
            "body": lambda i: i.update(body=i["body"] + " "),
        }
        for field, edit in edits.items():
            with self.subTest(field=field):
                self.assertNotEqual(self.changed(edit), self.base)

    def test_meta_counts(self):
        self.assertNotEqual(self.changed(lambda i: i["meta"].update(extra=1)), self.base)
        self.assertNotEqual(self.changed(lambda i: i["meta"]["kit"].append("scripts/more.py")), self.base)

    def test_one_kit_byte_counts(self):
        other = hashlib.sha256(b'print("ho")\n').hexdigest()
        self.assertNotEqual(self.changed(lambda i: i["meta"]["kitSha256"].update({"scripts/hi.py": other})), self.base)

    def test_a_remade_sample_doesnt(self):
        # Samples (examples/) are in neither the kit nor the item, so nothing here can see them.
        self.assertEqual(self.changed(lambda i: None), self.base)


class Escaping(unittest.TestCase):
    """RFC 8785 here is Python's json.dumps with these settings: strings escaped as JSON.stringify does."""

    def escaped(self, text):
        return json.dumps({"k": text}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def test_quotes_and_backslashes(self):
        self.assertEqual(self.escaped('a"b\\c'), '{"k":"a\\"b\\\\c"}')

    def test_new_line_and_control_characters(self):
        self.assertEqual(self.escaped("a\nb"), '{"k":"a\\nb"}')
        self.assertEqual(self.escaped("a\tb\rc"), '{"k":"a\\tb\\rc"}')
        self.assertEqual(self.escaped("\u0001"), '{"k":"\\u0001"}')  # lower-case hex, as JSON.stringify writes it

    def test_non_ascii_is_written_as_it_is(self):
        self.assertEqual(self.escaped("₹ — é"), '{"k":"₹ — é"}')

    def test_keys_are_sorted_and_nothing_has_white_space(self):
        text = json.dumps({"b": 1, "a": [1, 2], "c": {"z": None, "y": True}}, ensure_ascii=False,
                          separators=(",", ":"), sort_keys=True)
        self.assertEqual(text, '{"a":[1,2],"b":1,"c":{"y":true,"z":null}}')


if __name__ == "__main__":
    unittest.main()
