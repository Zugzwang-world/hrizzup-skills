"""The strict frontmatter (design 4.1) and the catalogue's text rules (4.2)."""

import unicodedata
import unittest

import catalogue
import frontmatter
import rules

GOOD = (
    '---\n'
    'name: "hello"\n'
    'description: "Says hello. Use when someone asks you to greet them."\n'
    'compatibility: "Python 3.12 with uv."\n'
    'metadata:\n'
    '  hrizzup-name: "Hello"\n'
    '  hrizzup-summary: "Says hello."\n'
    '  hrizzup-needs: "Nothing"\n'
    '  hrizzup-format: "breakdown"\n'
    '---\n'
    '\n'
    '# Hello\n'
    '\n'
    'Text.\n'
)

GOOD_AGENT = (
    '---\n'
    'name: "greeter"\n'
    'metadata:\n'
    '  hrizzup-name: "Greeter"\n'
    '  hrizzup-summary: "Greets."\n'
    '  hrizzup-skills: "hello other"\n'
    '---\n'
    '\n'
    '# Greeter\n'
)


def skill(text=GOOD, folder="hello"):
    return frontmatter.parse(text, frontmatter.SKILL, folder)


class Subset(unittest.TestCase):
    def test_a_good_skill_parses(self):
        fields, body_start, problems = skill()
        self.assertEqual(problems, [])
        self.assertEqual(fields["name"], "hello")
        self.assertEqual(fields["hrizzup-needs"], "Nothing")
        self.assertEqual(fields["hrizzup-format"], "breakdown")
        self.assertEqual(GOOD.split("\n")[body_start], "# Hello")

    def test_the_optional_lines_can_be_left_out(self):
        text = GOOD.replace('compatibility: "Python 3.12 with uv."\n', "").replace('  hrizzup-format: "breakdown"\n', "")
        fields, _, problems = skill(text)
        self.assertEqual(problems, [])
        self.assertNotIn("compatibility", fields)
        self.assertNotIn("hrizzup-format", fields)

    def test_a_good_agent_parses(self):
        fields, _, problems = frontmatter.parse(GOOD_AGENT, frontmatter.AGENT, "greeter")
        self.assertEqual(problems, [])
        self.assertEqual(fields["hrizzup-skills"], "hello other")

    def refused(self, text, words, folder="hello", kind=frontmatter.SKILL):
        _, _, problems = frontmatter.parse(text, kind, folder)
        self.assertTrue(problems, "nothing refused: " + words)
        self.assertIn(words, " ".join(problems))

    def test_unquoted_value(self):
        self.refused(GOOD.replace('hrizzup-name: "Hello"', "hrizzup-name: Hello"), "double-quoted")

    def test_single_quotes_are_not_double_quotes(self):
        self.refused(GOOD.replace('hrizzup-name: "Hello"', "hrizzup-name: 'Hello'"), "double-quoted")

    def test_unknown_key(self):
        self.refused(GOOD.replace('name: "hello"\n', 'name: "hello"\nlicense: "MIT"\n', 1), "license")

    def test_misordered_key(self):
        text = GOOD.replace('name: "hello"\ndescription:', 'description:', 1).replace('compatibility:', 'name: "hello"\ncompatibility:', 1)
        self.refused(text, "out of order")

    def test_a_tab(self):
        self.refused(GOOD.replace('  hrizzup-name:', '\thrizzup-name:'), "tab")

    def test_a_backslash(self):
        self.refused(GOOD.replace("Says hello.", "Says \\ hello.", 1), "backslash")

    def test_a_double_quote_inside(self):
        self.refused(GOOD.replace("Says hello.", 'Says "hello".', 1), "double quote")

    def test_a_second_line(self):
        text = GOOD.replace('description: "Says hello. Use when someone asks you to greet them."',
                            'description: "Says hello.\n  Use when someone asks you."')
        self.refused(text, "double-quoted")

    def test_missing_metadata_key(self):
        self.refused(GOOD.replace('  hrizzup-summary: "Says hello."\n', ""), "hrizzup-summary")
        self.refused(GOOD.replace("metadata:\n", "").replace('  hrizzup', 'hrizzup'), "metadata")

    def test_missing_needs_is_refused_too(self):
        self.refused(GOOD.replace('  hrizzup-needs: "Nothing"\n', ""), "hrizzup-needs")

    def test_name_must_be_the_folders(self):
        _, _, problems = skill(GOOD, "other")
        self.assertIn("must match", " ".join(problems))

    def test_the_title_must_be_the_name(self):
        self.refused(GOOD.replace("# Hello", "# Hello there"), "# Hello")

    def test_a_blank_line_must_follow(self):
        self.refused(GOOD.replace("---\n\n# Hello", "---\n# Hello"), "blank line")

    def test_it_must_open_and_close(self):
        self.refused(GOOD[4:], "line 1")
        self.refused(GOOD.replace("---\n\n# Hello", "# Hello"), "never closes")

    def test_an_unknown_format_code(self):
        self.refused(GOOD.replace('"breakdown"', '"podcast"'), "format code")

    def test_values_can_not_be_empty_or_padded(self):
        self.refused(GOOD.replace('hrizzup-summary: "Says hello."', 'hrizzup-summary: ""'), "empty")
        self.refused(GOOD.replace('hrizzup-summary: "Says hello."', 'hrizzup-summary: " Says hello."'), "space")

    def test_lengths_count_characters_and_the_rupee_sign_is_one(self):
        rupees = "₹" * 300
        fields, _, problems = skill(GOOD.replace("Says hello.\"\n  hrizzup-needs", rupees + "\"\n  hrizzup-needs"))
        self.assertEqual(problems, [])
        self.assertEqual(len(fields["hrizzup-summary"]), 300)
        self.refused(GOOD.replace("Says hello.\"\n  hrizzup-needs", rupees + "x\"\n  hrizzup-needs"), "301")

    def test_a_character_outside_the_allowlist_in_a_value(self):
        self.refused(GOOD.replace("Says hello.", "Says héllo.", 1), "U+00E9")

    def test_the_agent_skills_line(self):
        agent = dict(folder="greeter", kind=frontmatter.AGENT)
        self.refused(GOOD_AGENT.replace("hello other", "hello  other"), "one to 5 slugs", **agent)
        self.refused(GOOD_AGENT.replace("hello other", "hello hello"), "twice", **agent)
        self.refused(GOOD_AGENT.replace("hello other", "a b c d e f"), "one to 5 slugs", **agent)

    def test_an_agent_has_no_needs_or_format(self):
        text = GOOD_AGENT.replace('  hrizzup-skills: "hello other"\n', '  hrizzup-needs: "Nothing"\n  hrizzup-skills: "hello"\n')
        self.refused(text, "hrizzup-needs", folder="greeter", kind=frontmatter.AGENT)


class ClaudeAiRules(unittest.TestCase):
    """claude.ai and the Skills API refuse "anthropic" or "claude" in a skill's name, and XML tags in its
    name or description (Anthropic's Agent Skills documentation), so every SKILL.md here avoids them."""

    def refused(self, text, folder, words):
        _, _, problems = frontmatter.parse(text, frontmatter.SKILL, folder)
        self.assertIn(words, " ".join(problems))

    def test_reserved_words_in_the_name(self):
        for name in ("claude-notes", "my-anthropic-skill", "notes-for-claude"):
            with self.subTest(name):
                self.refused(GOOD.replace('name: "hello"', 'name: "%s"' % name), name, "refuse in a skill's name")

    def test_xml_tags_in_the_name_or_description(self):
        self.refused(GOOD.replace("Says hello.", "Says <b>hello</b>.", 1), "hello", "`description` holds `<` or `>`")
        self.refused(GOOD.replace("Says hello.", "Says hello > goodbye.", 1), "hello", "`description` holds `<` or `>`")
        self.refused(GOOD.replace('name: "hello"', 'name: "<x>"'), "<x>", "`name` holds `<` or `>`")

    def test_mentioning_claude_in_a_description_is_fine(self):
        text = GOOD.replace("Says hello.", "Says hello in Claude Code.", 1)
        self.assertEqual(frontmatter.parse(text, frontmatter.SKILL, "hello")[2], [])

    def test_a_starter_agent_is_not_loaded_by_claude_ai(self):
        text = GOOD_AGENT.replace('name: "greeter"', 'name: "claude-greeter"')
        self.assertEqual(frontmatter.parse(text, frontmatter.AGENT, "claude-greeter")[2], [])


class CatalogueText(unittest.TestCase):
    def problems(self, text):
        return catalogue.catalogue_text_problems(text)

    def test_good(self):
        self.assertEqual(self.problems("# A\n\nLine one.\n"), [])

    def test_the_allowlist_is_printable_ascii_and_21_marks(self):
        self.assertEqual(len(rules.MARKS), 21)
        for mark in rules.MARKS:
            with self.subTest(mark=unicodedata.name(mark)):
                self.assertEqual(self.problems("a %s b\n" % mark), [])
        for ordinary in "abcXYZ019 !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~":
            self.assertTrue(rules.catalogue_char_ok(ordinary), ordinary)

    def test_everything_else_is_refused(self):
        # Built with chr(), so this file holds no invisible character itself.
        for char in ("\u00e9", chr(0x1F600), chr(0x200B), chr(0xA0), chr(0x443), chr(0x928), chr(0xBD), chr(0xAE), chr(0x2122), "\t"):
            with self.subTest(char=hex(ord(char))):
                self.assertTrue(self.problems("a %s b\n" % char))

    def test_a_carriage_return(self):
        self.assertIn("carriage return", " ".join(self.problems("a\r\nb\r\n")))

    def test_the_final_new_line(self):
        self.assertIn("no final new line", " ".join(self.problems("a")))
        self.assertIn("more than one", " ".join(self.problems("a\n\n")))

    def test_a_trailing_space(self):
        self.assertIn("ends with a space", " ".join(self.problems("a \nb\n")))

    def test_the_rupee_sign_counts_one(self):
        self.assertEqual(len("₹"), 1)
        self.assertEqual(len("₹".encode("utf-8")), 3)  # bytes are not what the limits count

    def test_the_marks_agree_with_the_catalogue_note(self):
        names = [unicodedata.name(c) for c in rules.MARKS]
        self.assertIn("INDIAN RUPEE SIGN", names)
        self.assertIn("EM DASH", names)
        self.assertIn("MINUS SIGN", names)
        self.assertIn("RIGHTWARDS ARROW", names)


if __name__ == "__main__":
    unittest.main()
