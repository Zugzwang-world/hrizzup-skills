"""hrizzup_script: reading a narration script, and the words compared with what was heard (standard library only).

A correct reading must never be counted as an error for how it was written: numbers, spelled-out letters and punctuation are
normalised the same way on both sides, and the rules are general (no list of words that are let off).
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHARED = os.path.join(ROOT, "shared", "scripts")
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

import hrizzup_script as script  # noqa: E402


class Reading(unittest.TestCase):
    def test_paragraphs_are_split_by_blank_lines_and_lines_inside_one_are_joined(self):
        parsed = script.parse("First line\nof one paragraph.\n\n\n  \nSecond paragraph.\n")
        self.assertEqual([p.shown for p in parsed.paragraphs], ["First line of one paragraph.", "Second paragraph."])
        self.assertEqual(parsed.shown_text(), "First line of one paragraph.\n\nSecond paragraph.")

    def test_a_word_with_two_forms_is_shown_one_way_and_said_another(self):
        parsed = script.parse("Readings in {AQI|A Q I} passed {450|four hundred fifty}.")
        self.assertEqual(parsed.shown_text(), "Readings in AQI passed 450.")
        self.assertEqual(parsed.spoken_text(), "Readings in A Q I passed four hundred fifty.")
        self.assertEqual([(u.shown, u.spoken) for u in parsed.units()][2:4], [("AQI", "A Q I"), ("passed", "passed")])

    def test_a_shown_form_may_be_several_words(self):
        parsed = script.parse("It costs {Rs 450 crore|four hundred fifty crore rupees} a year.")
        self.assertEqual(parsed.paragraphs[0].units[2].shown, "Rs 450 crore")
        self.assertEqual(parsed.spoken_text(), "It costs four hundred fifty crore rupees a year.")

    def test_a_broken_word_with_two_forms_is_refused(self):
        for bad, why in (("a {b|} c", "both"), ("a {|b} c", "both"), ("a {b c", "stray"), ("a b} c", "stray"), ("a | b", "stray"),
                         ("a {b|c|d} e", "stray")):
            with self.subTest(bad):
                with self.assertRaises(script.ScriptError) as caught:
                    script.parse(bad)
                self.assertIn(why, str(caught.exception))

    def test_an_empty_or_too_long_script_is_refused(self):
        for bad in ("", "  \n\n \n"):
            with self.assertRaises(script.ScriptError):
                script.parse(bad)
        with self.assertRaises(script.ScriptError) as caught:
            script.parse("word " * 4001)
        self.assertIn("20000", str(caught.exception))

    def test_characters_the_voice_and_the_captions_cant_use_are_refused_by_line(self):
        for bad in ("a \u0928\u092e\u0938\u094d\u0924\u0947 b", "an emoji \U0001F600 here", "zero\u200bwidth", "a\u00a0b", "\u20b9 rupee", "an arrow \u2192"):
            with self.subTest(bad):
                with self.assertRaises(script.ScriptError) as caught:
                    script.parse("fine line\n\n" + bad)
                self.assertIn("line 3", str(caught.exception))
        # plain English, accents and the usual marks are fine
        script.parse("Caf\u00e9 \u201cquoted\u201d \u2013 and \u2014 and a \u00a3 sign\u2026")

    def test_a_byte_order_mark_and_crlf_are_tolerated(self):
        self.assertEqual(script.parse("\ufeffOne.\r\n\r\nTwo.\r\n").shown_text(), "One.\n\nTwo.")


class Normalising(unittest.TestCase):
    def test_numbers_become_words_the_usual_way(self):
        cases = {
            "450": "four hundred fifty", "7": "seven", "19": "nineteen", "20": "twenty", "21": "twenty one", "100": "one hundred",
            "101": "one hundred one", "1,200": "one thousand two hundred", "2026": "two thousand twenty six",
            "1000000": "one million", "3.5": "three point five", "0.25": "zero point two five", "12.5%": "twelve point five percent",
            "007": "zero zero seven",
        }
        for written, words in cases.items():
            with self.subTest(written):
                self.assertEqual(" ".join(script.normalise(written)), words)

    def test_ordinals(self):
        for written, words in {"1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth", "5th": "fifth", "12th": "twelfth",
                               "20th": "twentieth", "21st": "twenty first", "100th": "one hundredth"}.items():
            with self.subTest(written):
                self.assertEqual(" ".join(script.normalise(written)), words)

    def test_the_example_stories_450_is_read_the_same_however_it_was_written(self):
        said = script.normalise("passed 450.")
        for heard in ("passed 450", "passed four hundred fifty", "passed four hundred and fifty", "Passed 450!", "passed 4-5-0 "):
            if heard.endswith("4-5-0 "):
                continue  # digits said one by one are a different reading
            with self.subTest(heard):
                self.assertEqual(script.normalise(heard), said)

    def test_spelled_letters_are_one_word_however_they_were_written(self):
        said = script.normalise("AQI")
        for heard in ("AQI", "A Q I", "A.Q.I.", "a.q.i", "A-Q-I", "aqi"):
            with self.subTest(heard):
                self.assertEqual(script.normalise(heard), said)
        for heard in ("NCR", "N C R", "N.C.R.", "n c r"):
            with self.subTest(heard):
                self.assertEqual(script.normalise(heard), ["ncr"])
        self.assertEqual(script.normalise("U.S. and U S A"), ["us", "and", "usa"])

    def test_a_single_letter_word_stays_a_word(self):
        self.assertEqual(script.normalise("a plan, I think"), ["a", "plan", "i", "think"])
        self.assertEqual(script.normalise("Plan B works"), ["plan", "b", "works"])

    def test_names_are_only_lower_cased(self):
        self.assertEqual(script.normalise("Noida and Gurugram, Delhi's schools."), ["noida", "and", "gurugram", "delhi's", "schools"])
        self.assertEqual(script.normalise("\u201cHrizzup\u2019s\u201d sample \u2014 illustrative"), ["hrizzup's", "sample", "illustrative"])

    def test_and_is_dropped_only_inside_a_number(self):
        self.assertEqual(script.normalise("one hundred and one"), ["one", "hundred", "one"])
        self.assertEqual(script.normalise("Noida and Gurugram"), ["noida", "and", "gurugram"])
        self.assertEqual(script.normalise("a thousand and one nights"), ["a", "thousand", "one", "nights"])

    def test_spoken_words_say_which_script_words_each_comes_from(self):
        parsed = script.parse("The N C R {AQI|A Q I} passed 450.")
        units = parsed.units()
        words = script.spoken_words(units)
        self.assertEqual([w for w, _ in words][:2], ["the", "ncraqi"])  # letters side by side run together: keep acronyms apart
        parsed = script.parse("The {AQI|A Q I} passed 450 today.")
        words = script.spoken_words(parsed.units())
        self.assertEqual(words[1], ("aqi", [1]))
        self.assertEqual([w for w, _ in words][3:6], ["four", "hundred", "fifty"])
        self.assertEqual({tuple(u) for w, u in words[3:6]}, {(3,)})
        plain = script.spoken_words(script.parse("an N C R story").units())
        self.assertEqual(plain[1], ("ncr", [1, 2, 3]))


class Comparing(unittest.TestCase):
    def test_edit_distance_and_word_error_rate(self):
        self.assertEqual(script.edit_distance(["a", "b", "c"], ["a", "b", "c"]), 0)
        self.assertEqual(script.edit_distance(["a", "b", "c"], ["a", "x", "c"]), 1)
        self.assertEqual(script.edit_distance(["a", "b", "c"], ["a", "c"]), 1)
        self.assertEqual(script.edit_distance(["a"], ["a", "b", "c"]), 2)
        self.assertEqual(script.edit_distance([], ["a"]), 1)
        self.assertAlmostEqual(script.word_error_rate(["a", "b", "c", "d"], ["a", "x", "c", "d"]), 0.25)
        self.assertEqual(script.word_error_rate([], []), 0.0)
        self.assertEqual(script.word_error_rate([], ["x"]), 1.0)

    def test_a_correct_reading_of_the_example_scripts_hard_words_has_no_errors(self):
        said = script.normalise("AQI readings in Delhi NCR, Noida and Gurugram passed 450 before dawn.")
        heard = script.normalise("A.Q.I. readings in Delhi N.C.R., Noida and Gurugram passed four hundred and fifty before dawn")
        self.assertEqual(script.word_error_rate(said, heard), 0.0)

    def test_differences_say_what_was_said_and_what_was_heard(self):
        said = script.normalise("schools in Noida stay open")
        heard = script.normalise("schools in Noyda stay open today")
        found = script.differences(said, heard)
        self.assertIn("said 'noida', heard 'noyda'", found)
        self.assertIn("heard 'today', which the script doesn't say", found)
        self.assertEqual(script.differences(["a", "b"], ["a"]), ["said 'b', heard nothing there"])
        self.assertEqual(script.differences(["a"], ["a"]), [])
        self.assertEqual(len(script.differences(list("abcdefghijklmnop"), list("ABCDEFGHIJKLMNOP"), limit=3)), 1)  # one run of changes

    def test_timed_words_share_a_numbers_time_by_letters_and_join_spelled_letters(self):
        heard = [script.Heard("Passed", 0.0, 0.4), script.Heard("450.", 0.4, 1.4), script.Heard("A", 1.5, 1.6), script.Heard("Q", 1.6, 1.7),
                 script.Heard("I", 1.7, 1.8), script.Heard("\u2014", 1.8, 1.9)]
        words = script.timed_words(heard)
        self.assertEqual([w for w, _, _ in words], ["passed", "four", "hundred", "fifty", "aqi"])
        self.assertAlmostEqual(words[1][1], 0.4)
        self.assertAlmostEqual(words[3][2], 1.4)
        self.assertAlmostEqual(sum(e - s for _, s, e in words[1:4]), 1.0)
        self.assertEqual((words[4][1], words[4][2]), (1.5, 1.8))

    def test_matched_words_take_the_heard_times_and_the_rest_are_spread_between_neighbours(self):
        said = ["the", "air", "turned", "severe", "today"]
        heard = [("the", 1.0, 1.2), ("air", 1.2, 1.5), ("severe", 3.0, 3.5), ("today", 3.5, 4.0)]
        times = script.align_times(said, heard, 5.0)
        self.assertEqual(times[0], (1.0, 1.2, True))
        self.assertEqual(times[3], (3.0, 3.5, True))
        start, end, matched = times[2]  # "turned" was not heard: it sits between "air" and "severe"
        self.assertFalse(matched)
        self.assertTrue(1.5 <= start < end <= 3.0)

    def test_words_before_the_first_and_after_the_last_match_stay_inside_the_audio(self):
        said = ["oh", "the", "air", "ok", "bye"]
        heard = [("the", 1.0, 1.2), ("air", 1.2, 1.5)]
        times = script.align_times(said, heard, 2.0)
        self.assertTrue(0.0 <= times[0][0] < times[0][1] <= 1.0 and not times[0][2])
        self.assertTrue(1.5 <= times[3][0] and times[4][1] <= 2.0)
        for start, end, _matched in times:
            self.assertTrue(0.0 <= start <= end <= 2.0)

    def test_nothing_heard_spreads_the_words_over_the_whole_audio(self):
        times = script.align_times(["a", "bb", "ccc"], [], 6.0)
        self.assertEqual(times[0][0], 0.0)
        self.assertAlmostEqual(times[-1][1], 6.0, places=2)
        self.assertFalse(any(m for _, _, m in times))
        self.assertTrue(all(times[k][1] <= times[k + 1][0] + 1e-9 for k in range(2)))


def compare(text, heard):
    parsed = script.parse(text)
    return script.compare(parsed.units(), script.normalise(heard))


class TheGate(unittest.TestCase):
    """Did the voice say the script? A word with two forms and a number are one word each; a number heard as another number, or three
    words in a row not heard, fail whatever the word error rate."""

    def test_a_perfect_reading_has_no_differences(self):
        found = compare("Readings in Delhi passed 450 today.", "readings in Delhi passed four hundred and fifty today")
        self.assertEqual((found.errors, found.rate, found.differences(), found.problems(0.15)), (0, 0.0, [], []))
        self.assertEqual(len(found.tokens), 6)  # 450 is one word

    def test_a_word_with_two_forms_is_one_word_matched_by_either_form(self):
        text = "Made from {Hrizzup's|Hrizz-up's} example story."
        for heard in ("made from Hrizzup's example story", "Made from Hrizz up's example story", "made from hrizz-up's example story"):
            with self.subTest(heard):
                found = compare(text, heard)
                self.assertEqual(found.errors, 0)
                self.assertEqual(len(found.tokens), 5)  # the name is one of five words, not two or three
        found = compare(text, "made from H. Rezaup's example story")
        self.assertEqual(found.errors, 1)  # one word wrong, not two
        self.assertEqual(found.differences(), ["said \"Hrizzup's\", heard \"h rezaup's\""])
        self.assertAlmostEqual(found.rate, 0.2)

    def test_the_two_forms_of_a_figure_are_one_word_too(self):
        found = compare("It rose to {450|four hundred fifty} today.", "it rose to four hundred fifty today")
        self.assertEqual(found.errors, 0)
        self.assertEqual(found.numbers_heard_wrong(), [])

    def test_a_number_heard_as_another_number_fails_however_few_words_it_is(self):
        text = "Before dawn on Monday readings in Delhi and Noida passed 450, the worst of the season so far, and doctors advise people to stay in."
        found = compare(text, "before dawn on Monday readings in Delhi and Noida passed 500 the worst of the season so far and doctors advise people to stay in")
        self.assertLess(found.rate, 0.15)  # one word in twenty-five: the rate alone would pass it
        self.assertEqual(found.numbers_heard_wrong(), ["said '450,' (four hundred fifty), heard 'five hundred'"])
        self.assertEqual(len(found.problems(0.15)), 1)
        self.assertIn("a number was heard as another", found.problems(0.15)[0])
        for kind in ("3rd", "12.5%", "1,200"):
            self.assertTrue(compare("It was %s today." % kind, "it was something else today").numbers_heard_wrong(), kind)
        self.assertFalse(compare("It was Delhi today.", "it was something else today").numbers_heard_wrong())  # not a number
        self.assertTrue(compare("It passed 450.", "it passed").numbers_heard_wrong())  # a number not heard at all

    def test_three_words_in_a_row_not_heard_fail_and_two_do_not(self):
        text = ("one two. three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen. "
                "eighteen nineteen twenty twenty-one twenty-two twenty-three twenty-four.")
        full = " ".join(text.replace(".", "").split())
        dropped = full.replace("five six seven", "")
        found = compare(text, dropped)
        self.assertEqual(found.longest_unheard_run(), 3)
        self.assertLess(found.rate, 0.15)
        self.assertIn("3 script words in a row weren't heard", found.problems(0.15))
        found = compare(text, full.replace("five six", ""))
        self.assertEqual(found.longest_unheard_run(), 2)
        self.assertEqual(found.problems(0.15), [])
        # words that were changed, not dropped, are not heard either
        found = compare(text, full.replace("five six seven", "cat dog fish"))
        self.assertEqual(found.longest_unheard_run(), 3)

    def test_the_word_error_rate_counts_changed_missing_and_added_words(self):
        found = compare("alpha bravo charlie delta echo foxtrot golf hotel india juliet", "alpha xray charlie delta echo foxtrot golf hotel india juliet kilo")
        self.assertEqual(found.errors, 2)  # one changed, one added
        self.assertAlmostEqual(found.rate, 0.2)
        self.assertIn("the word error rate 0.20 is over 0.15", found.problems(0.15))
        self.assertEqual(found.problems(0.2), [])  # the limit is inclusive
        self.assertEqual(found.differences(), ["said 'bravo', heard 'xray'", "heard 'kilo', which the script doesn't say"])

    def test_every_difference_is_listed_with_nothing_left_out(self):
        text = " ".join("w%d" % n for n in range(40))
        heard = " ".join("w%d" % n if n % 3 else "z%d" % n for n in range(40))  # fourteen changed words
        found = compare(text, heard)
        self.assertEqual(len(found.differences()), 14)
        self.assertEqual(found.errors, 14)

    def test_adjacent_changed_words_are_one_difference(self):
        found = compare("alpha bravo charlie delta echo foxtrot", "alpha xray yankee zulu echo foxtrot")
        self.assertEqual(found.differences(), ["said 'bravo charlie delta', heard 'xray yankee zulu'"])
        self.assertEqual(found.longest_unheard_run(), 3)

    def test_spelled_letters_are_one_word(self):
        for heard in ("the ncr and aqi", "the N C R and A Q I", "the N.C.R. and A.Q.I."):
            found = compare("The N C R and AQI.", heard)
            self.assertEqual(found.errors, 0, heard)
            self.assertEqual(len(found.tokens), 4)

    def test_a_hyphenated_word_is_one_word_heard_with_or_without_the_hyphen(self):
        for heard in ("a one-minute brief", "a one minute brief"):
            self.assertEqual(compare("A one-minute brief", heard).errors, 0)
        self.assertEqual(len(compare("A one-minute brief", "a one minute brief").tokens), 3)

    def test_nothing_heard_and_nothing_said(self):
        found = compare("One two three four.", "")
        self.assertEqual((found.errors, found.rate, found.longest_unheard_run()), (4, 1.0, 4))
        self.assertEqual(found.differences(), ["said 'One two three four.', heard nothing there"])
        self.assertEqual(script.compare([], []).rate, 0.0)

    def test_the_old_helpers_still_work_on_plain_word_lists(self):
        self.assertEqual(script.edit_distance(["a", "b"], ["a", "c"]), 1)


if __name__ == "__main__":
    unittest.main()
