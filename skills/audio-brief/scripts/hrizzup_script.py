"""A narration script: its paragraphs, the words it shows and the words it says, and how to compare it with what was heard.
Standard library only.

This is a module, not a command: `voice.py` (what to say) and `captions.py` (what to show, and when) import it as a
sibling, inside a function. A script is plain text. Paragraphs are separated by a blank line. `{shown|spoken}` gives a
word two forms: the captions and the transcript use the shown one, the voice says the spoken one (`{AQI|A Q I}`).

    import hrizzup_script
    script = hrizzup_script.parse(open("script.txt", encoding="utf-8").read())
    script.shown_text()                      # the transcript: paragraphs separated by a blank line
    hrizzup_script.normalise("AQI passed 450.")   # ['aqi', 'passed', 'four', 'hundred', 'fifty']

Every refusal is a ScriptError, which a command turns into exit 2 (bad input).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

MAX_SCRIPT_CHARACTERS = 20000  # the longest transcript Hrizzup takes
UNIT_GROUP = re.compile(r"\{([^{}|]*)\|([^{}|]*)\}")
MARK_OPEN, MARK_CLOSE = "\ue000", "\ue001"  # private-use marks hold a {shown|spoken} while a block is split into words (a script may not hold them)
RESTORE = re.compile("%s(\\d+)%s" % (MARK_OPEN, MARK_CLOSE))


class ScriptError(ValueError):
    """The script can't be used. The message says what to change."""


@dataclass
class Unit:
    """One word of the script as people see it and as the voice says it: `shown` is the text (a plain word with its
    punctuation, or the shown side of a `{shown|spoken}`), `spoken` what the voice says for it."""

    shown: str
    spoken: str
    paragraph: int


@dataclass
class Paragraph:
    index: int
    units: List[Unit] = field(default_factory=list)

    @property
    def shown(self) -> str:
        return " ".join(u.shown for u in self.units)

    @property
    def spoken(self) -> str:
        return " ".join(u.spoken for u in self.units)


@dataclass
class Script:
    paragraphs: List[Paragraph]

    def shown_text(self) -> str:
        """What the captions and the transcript say: the paragraphs, separated by a blank line."""
        return "\n\n".join(p.shown for p in self.paragraphs)

    def spoken_text(self) -> str:
        return "\n\n".join(p.spoken for p in self.paragraphs)

    def units(self) -> List[Unit]:
        return [u for p in self.paragraphs for u in p.units]


# ---------------------------------------------------------------------------------------------
# Reading a script
# ---------------------------------------------------------------------------------------------

# What a script may hold: plain ASCII, Latin letters (accents included) and a few marks. The fonts that draw the captions
# have no other scripts, no emoji and no arrows, and a transcript is the shown text.
MARKS = "\u2018\u2019\u201c\u201d\u2013\u2014\u2026\u00a3\u00b0\u00d7\u20ac\u00b7"


def _allowed(char: str) -> bool:
    if " " <= char <= "~":
        return True
    if char in MARKS:
        return True
    return unicodedata.category(char).startswith("L") and (ord(char) <= 0x24F or 0x1E00 <= ord(char) <= 0x1EFF)


def _check_characters(text: str) -> None:
    for number, char in enumerate(text):
        if char in "\n\t" or _allowed(char):
            continue
        line = text.count("\n", 0, number) + 1
        if unicodedata.category(char) in ("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp", "Zs"):
            raise ScriptError("line %d holds U+%04X, a control, invisible or odd space character: remove it" % (line, ord(char)))
        raise ScriptError("line %d holds %r (U+%04X): the voice and the captions read English (Latin letters, digits and common "
                          "punctuation) only for now, so write the script in plain English" % (line, char, ord(char)))


def parse(text: str) -> Script:
    """The script's paragraphs and units. Raises ScriptError for an empty script, one that is too long, a character
    that can't be read or shown, or a `{shown|spoken}` that isn't whole."""
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_SCRIPT_CHARACTERS:
        raise ScriptError("the script is %d characters; a transcript holds at most %d" % (len(text), MAX_SCRIPT_CHARACTERS))
    _check_characters(text)
    paragraphs: List[Paragraph] = []
    for block in re.split(r"\n[ \t]*\n+", text.strip("\n")):
        block = " ".join(block.split())  # lines inside a paragraph are one run of words
        if not block:
            continue
        paragraph = Paragraph(index=len(paragraphs))
        forms: List[Tuple[str, str]] = []

        def keep(found: "re.Match[str]") -> str:
            shown, spoken = found.group(1).strip(), found.group(2).strip()
            if not shown or not spoken:
                raise ScriptError("paragraph %d: {%s|%s} needs both a shown and a spoken form" % (paragraph.index + 1, shown, spoken))
            forms.append((shown, spoken))
            return "%s%d%s" % (MARK_OPEN, len(forms) - 1, MARK_CLOSE)

        protected = UNIT_GROUP.sub(keep, block)
        stray = re.search(r"\S*[{}|]\S*", protected)
        if stray:
            raise ScriptError("paragraph %d: a stray { } or | in %r; a word with two forms is written {shown|spoken}" % (paragraph.index + 1, stray.group(0)[:40]))
        for word in protected.split():
            # a word's punctuation stays with it: {AQI|A Q I}, is shown "AQI," and said "A Q I,"
            shown = RESTORE.sub(lambda found: forms[int(found.group(1))][0], word)
            spoken = RESTORE.sub(lambda found: forms[int(found.group(1))][1], word)
            paragraph.units.append(Unit(shown, spoken, paragraph.index))
        paragraphs.append(paragraph)
    if not paragraphs:
        raise ScriptError("the script is empty")
    return Script(paragraphs)


# ---------------------------------------------------------------------------------------------
# Words: normalised the same way on both sides of a comparison
# ---------------------------------------------------------------------------------------------

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"))
SCALE_WORDS = frozenset(["hundred", "thousand", "million", "billion", "lakh", "crore"])
ORDINAL_ENDINGS = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth",
                   "twelve": "twelfth"}


def number_words(value: int) -> List[str]:
    """A whole number in words, the usual English way (450 is four hundred fifty; 2026 is two thousand twenty six)."""
    if value < 0:
        return ["minus"] + number_words(-value)
    if value < 20:
        return [ONES[value]]
    if value < 100:
        return [TENS[value // 10]] + ([ONES[value % 10]] if value % 10 else [])
    if value < 1000:
        return [ONES[value // 100], "hundred"] + (number_words(value % 100) if value % 100 else [])
    for size, name in SCALES:
        if value >= size:
            head = number_words(value // size)
            rest = value % size
            return head + [name] + (number_words(rest) if rest else [])
    return [ONES[0]]


def _ordinal(words: List[str]) -> List[str]:
    last = words[-1]
    if last in ORDINAL_ENDINGS:
        last = ORDINAL_ENDINGS[last]
    elif last.endswith("y"):
        last = last[:-1] + "ieth"
    else:
        last = last + "th"
    return words[:-1] + [last]


NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(st|nd|rd|th)?(?![\w])", re.IGNORECASE)


def _read_number(found: "re.Match[str]") -> str:
    raw = found.group(1).replace(",", "")
    suffix = found.group(2)
    whole, _, fraction = raw.partition(".")
    if len(whole) > 12 or (len(whole) > 1 and whole.startswith("0")):
        words = [ONES[int(digit)] for digit in whole]  # a long or zero-led number is read digit by digit
    else:
        words = number_words(int(whole or "0"))
    if suffix and not fraction:
        words = _ordinal(words)
    if fraction:
        words = words + ["point"] + [ONES[int(digit)] for digit in fraction]
    return " " + " ".join(words) + " "


def _tokens(text: str) -> List[str]:
    """One piece of text as lower-case words: no punctuation, numbers as words."""
    text = unicodedata.normalize("NFKC", text)
    for old, new in (("\u2018", "'"), ("\u2019", "'"), ("\u201b", "'"), ("\u201c", '"'), ("\u201d", '"')):
        text = text.replace(old, new)
    text = text.lower()
    text = text.replace("%", " percent ").replace("&", " and ")
    text = NUMBER.sub(_read_number, text)
    text = re.sub(r"\b([a-z])\.(?=[a-z](?:\.|\b))", r"\1", text)  # a.q.i. -> aqi
    text = re.sub(r"[-_/\u2013\u2014\u2212]", " ", text)
    text = re.sub(r"[^a-z0-9' ]", " ", text)
    return [w for w in (w.strip("'") for w in text.split()) if w]


def _runs(words: Sequence[Tuple[str, List[int]]]) -> List[Tuple[str, List[int]]]:
    """The rules that look across words, on (word, the script units it comes from): "and" inside a number is dropped, and a
    run of two or more single letters (a q i) becomes one word (aqi), the way an acronym is spelled out."""
    kept: List[Tuple[str, List[int]]] = []
    for word, units in words:
        if word == "and" and kept and kept[-1][0] in SCALE_WORDS:
            continue
        kept.append((word, units))
    joined: List[Tuple[str, List[int]]] = []
    run: List[Tuple[str, List[int]]] = []

    def flush() -> None:
        if len(run) > 1:
            covered: List[int] = []
            for _, units in run:
                covered += [u for u in units if u not in covered]
            joined.append(("".join(w for w, _ in run), covered))
        else:
            joined.extend(run)
        run.clear()

    for entry in kept:
        if len(entry[0]) == 1 and entry[0].isalpha():
            run.append(entry)
        else:
            flush()
            joined.append(entry)
    flush()
    return joined


def normalise(text: str) -> List[str]:
    """Words to compare: lower case, no punctuation, numbers as words, "and" inside a number dropped, and a run of
    spelled letters (A Q I, or A.Q.I.) one word. The same rule is used for what the script says and for what was
    heard, so a correct reading is never counted as an error for how it was written."""
    return [word for word, _ in _runs([(w, [0]) for w in _tokens(text)])]


def spoken_words(units: Sequence[Unit]) -> List[Tuple[str, List[int]]]:
    """The words the voice says for a script's units, normalised, each with the indices of the units it comes from (one
    word can cover several: the units N, C and R say "ncr")."""
    return _runs([(w, [index]) for index, unit in enumerate(units) for w in _tokens(unit.spoken)])


# ---------------------------------------------------------------------------------------------
# Comparing the script with what was heard
# ---------------------------------------------------------------------------------------------

def edit_distance(said: Sequence[str], heard: Sequence[str]) -> int:
    """The word-level Levenshtein distance: the fewest words to change, add or drop to turn one list into the other."""
    previous = list(range(len(heard) + 1))
    for i, word in enumerate(said, 1):
        current = [i] + [0] * len(heard)
        for j, other in enumerate(heard, 1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word != other))
        previous = current
    return previous[-1]


def word_error_rate(said: Sequence[str], heard: Sequence[str]) -> float:
    """Errors divided by the words the script says (0 is a perfect reading)."""
    if not said:
        return 0.0 if not heard else 1.0
    return edit_distance(said, heard) / len(said)


def differences(said: Sequence[str], heard: Sequence[str], limit: int = 12) -> List[str]:
    """The words where the script and the reading part, each as a line a person can act on."""
    found: List[str] = []
    matcher = difflib.SequenceMatcher(None, said, heard, autojunk=False)
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            found.append("said %r, heard %r" % (" ".join(said[a0:a1]), " ".join(heard[b0:b1])))
        elif tag == "delete":
            found.append("said %r, heard nothing there" % " ".join(said[a0:a1]))
        else:
            found.append("heard %r, which the script doesn't say" % " ".join(heard[b0:b1]))
        if len(found) >= limit:
            break
    return found


# ---- the gate: did the voice say the script? (a word with two forms is one word; numbers and runs of missing words fail) ----

NUMBER_UNIT = re.compile(r"^\W*\d[\d,]*(?:\.\d+)?(?:%|st|nd|rd|th)?\W*$", re.IGNORECASE)
UNHEARD_RUN = 3  # this many script words in a row with nothing heard in their place fail the gate, whatever the word error rate


@dataclass
class Token:
    """One word of the script as the gate scores it: a plain word (a number is one word, and so is a hyphenated one), or a
    `{shown|spoken}`, which is one word whichever of its two forms is heard."""

    shown: str  # the script's own words for it, as shown
    forms: List[List[str]]  # the normalised words it may be heard as: how it is spoken, then how it is shown if that differs
    units: List[int]
    number: bool  # a figure ("450", "12.5%", "3rd"): heard as another number, it fails the gate


def script_tokens(units: Sequence[Unit]) -> List[Token]:
    """The script's words as the gate scores them (see `Token`). Spelled letters side by side (N C R) are one word."""
    flat = spoken_words(units)
    tokens: List[Token] = []
    i = 0
    while i < len(flat):
        j = i
        while j < len(flat) and flat[j][1] == flat[i][1]:  # the words that come from the same units are one token
            j += 1
        covered = flat[i][1]
        spoken = [word for word, _ in flat[i:j]]
        forms = [spoken]
        number = False
        if len(covered) == 1:
            unit = units[covered[0]]
            if unit.shown != unit.spoken:
                shown = [word for word, _ in _runs([(w, [0]) for w in _tokens(unit.shown)])]
                if shown and shown != spoken:
                    forms.append(shown)
            number = bool(NUMBER_UNIT.match(unit.shown))
        tokens.append(Token(" ".join(units[u].shown for u in covered), forms, covered, number))
        i = j
    return tokens


@dataclass
class Comparison:
    """The script against what was heard, as a list of events in order: ("heard", token, words), ("changed", token, words: other
    words were heard in its place), ("missing", token, []) and ("extra", None, words: heard words the script doesn't say)."""

    tokens: List[Token]
    events: List[Tuple[str, Optional[int], List[str]]]
    errors: int

    @property
    def rate(self) -> float:
        """Words changed, missing or added, over the words the script says (a `{shown|spoken}` and a number are one word)."""
        if self.tokens:
            return self.errors / len(self.tokens)
        return 0.0 if not self.events else 1.0

    def results(self) -> List[Tuple[str, List[str]]]:
        """(status, heard words) for each script word, where status is "heard", "changed" or "missing"."""
        by_token = {index: (status, words) for status, index, words in self.events if index is not None}
        return [by_token[i] for i in range(len(self.tokens))]

    def differences(self) -> List[str]:
        """Every place the script and the reading part, each as a line a person can act on."""
        found: List[str] = []
        said: List[str] = []
        heard: List[str] = []

        def flush() -> None:
            if said and heard:
                found.append("said %r, heard %r" % (" ".join(said), " ".join(heard)))
            elif said:
                found.append("said %r, heard nothing there" % " ".join(said))
            elif heard:
                found.append("heard %r, which the script doesn't say" % " ".join(heard))
            said.clear()
            heard.clear()

        for status, index, words in self.events:
            if status == "heard":
                flush()
                continue
            if index is not None:
                said.append(self.tokens[index].shown)
            heard.extend(words)
        flush()
        return found

    def numbers_heard_wrong(self) -> List[str]:
        """The numbers the script says that weren't heard as that number, with what was heard instead."""
        found = []
        for token, (status, words) in zip(self.tokens, self.results()):
            if token.number and status != "heard":
                found.append("said %r (%s), heard %s" % (token.shown, " ".join(token.forms[0]), repr(" ".join(words)) if words else "nothing there"))
        return found

    def longest_missing_run(self) -> int:
        """The most script words in a row with nothing heard in their place (status "missing"): a skipped sentence. A word heard as
        something else (a name the recogniser spells its own way) is neither counted nor does it end a run, so a list of misheard
        names passes, and a skipped sentence with a stray word heard inside it still fails. A word heard right ends the run."""
        longest = run = 0
        for status, _words in self.results():
            if status == "heard":
                run = 0
            elif status == "missing":
                run += 1
                longest = max(longest, run)
        return longest

    def problems(self, max_wer: float) -> List[str]:
        """Why the voice failed the script, if it did: the rate over its limit, a number heard as another, a run of missing words."""
        found = []
        if self.rate > max_wer:
            found.append("the word error rate %.2f is over %.2f" % (self.rate, max_wer))
        wrong = self.numbers_heard_wrong()
        if wrong:
            found.append("a number was heard as another (%s)" % "; ".join(wrong))
        if self.longest_missing_run() >= UNHEARD_RUN:
            found.append("%d script words in a row weren't heard" % self.longest_missing_run())
        return found


def compare(units: Sequence[Unit], heard: Sequence[str]) -> Comparison:
    """Align the script's words with the normalised words that were heard (the fewest changes, a `{shown|spoken}` or a number counted
    as one word) and report where they part. A word matches when the words heard in its place are one of its forms."""
    tokens = script_tokens(units)
    n, m = len(tokens), len(heard)
    widest = [max(len(f) for f in token.forms) for token in tokens]
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i == n:
                cost[i][j] = m - j
                continue
            best = cost[i + 1][j] + 1  # the word wasn't heard
            for form in tokens[i].forms:
                if list(heard[j:j + len(form)]) == form:
                    best = min(best, cost[i + 1][j + len(form)])
            for take in range(1, widest[i] + 1):
                if j + take <= m:
                    best = min(best, cost[i + 1][j + take] + 1)  # other words were heard in its place
            if j < m:
                best = min(best, cost[i][j + 1] + 1)  # a heard word the script doesn't have
            cost[i][j] = best
    events: List[Tuple[str, Optional[int], List[str]]] = []
    i = j = 0
    while i < n or j < m:
        here = cost[i][j]
        if i < n:
            step = None
            for form in tokens[i].forms:  # a match is preferred to every other way of getting the same cost
                if list(heard[j:j + len(form)]) == form and cost[i + 1][j + len(form)] == here:
                    step = ("heard", i, list(form), len(form))
                    break
            if step is None:
                for take in range(1, widest[i] + 1):
                    if j + take <= m and cost[i + 1][j + take] + 1 == here:
                        step = ("changed", i, list(heard[j:j + take]), take)
                        break
            if step is None and cost[i + 1][j] + 1 == here:
                step = ("missing", i, [], 0)
            if step is not None:
                events.append(step[:3])
                i, j = i + 1, j + step[3]
                continue
        if events and events[-1][0] == "extra":
            events[-1][2].append(heard[j])
        else:
            events.append(("extra", None, [heard[j]]))
        j += 1
    return Comparison(tokens, events, cost[0][0])


@dataclass
class Heard:
    """A recognised word and when it was said (seconds)."""

    text: str
    start: float
    end: float


def timed_words(heard: Sequence[Heard]) -> List[Tuple[str, float, float]]:
    """Each recognised word as normalised words with times. A word that normalises to several (450 to four hundred fifty) shares
    its time by letters; one that normalises to none (a dash) is dropped; and the rules that look across words ("and" inside a
    number; spelled letters heard one by one) are applied across them, a joined word keeping the first one's start and the
    last one's end."""
    expanded: List[Tuple[str, float, float]] = []
    for item in heard:
        words = _tokens(item.text)
        if not words:
            continue
        total = sum(len(w) for w in words) or 1
        cursor = item.start
        for word in words:
            share = (item.end - item.start) * len(word) / total
            expanded.append((word, cursor, cursor + share))
            cursor += share
    out: List[Tuple[str, float, float]] = []
    for word, covered in _runs([(w, [n]) for n, (w, _s, _e) in enumerate(expanded)]):
        out.append((word, expanded[covered[0]][1], expanded[covered[-1]][2]))
    return out


def align_times(said: Sequence[str], heard: Sequence[Tuple[str, float, float]], seconds: float) -> List[Tuple[float, float, bool]]:
    """(start, end, matched) for each word the script says. Words that match a recognised word (found with
    `difflib.SequenceMatcher(autojunk=False)`) take its time; the others are spread between their matched neighbours by
    length, and ahead of the first or after the last matched word by the usual time a letter takes."""
    n = len(said)
    times: List[Optional[Tuple[float, float]]] = [None] * n
    matcher = difflib.SequenceMatcher(None, list(said), [h[0] for h in heard], autojunk=False)
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            times[block.a + k] = (heard[block.b + k][1], heard[block.b + k][2])
    matched = [t is not None for t in times]
    known = [t for t in times if t is not None]
    letters = sum(len(said[i]) for i in range(n) if times[i] is not None) or 1
    per_letter = (sum(t[1] - t[0] for t in known) / letters) if known else (seconds / max(1, sum(len(w) for w in said)))
    per_letter = max(per_letter, 0.02)
    i = 0
    while i < n:
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        weights = [len(w) + 1 for w in said[i:j]]
        before = times[i - 1][1] if i > 0 else None
        after = times[j][0] if j < n else None
        if before is None and after is None:
            low, high = 0.0, seconds
        elif before is None:
            low, high = max(0.0, after - sum(weights) * per_letter), after
        elif after is None:
            low, high = before, min(seconds, before + sum(weights) * per_letter)
        else:
            low, high = before, max(before, after)
        cursor = low
        for k, weight in enumerate(weights):
            share = (high - low) * weight / sum(weights)
            times[i + k] = (cursor, cursor + share)
            cursor += share
        i = j
    result = []
    for k in range(n):
        start, end = times[k]  # type: ignore[misc]
        result.append((round(start, 3), round(max(start, end), 3), matched[k]))
    return result
