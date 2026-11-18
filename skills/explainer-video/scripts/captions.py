# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["faster-whisper==1.2.1", "av==18.1.0"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Time a narration's words and make its captions: a check that the voice said the script, and the cues to burn in.

The script is the one `voice.py` read (paragraphs apart by a blank line, `{shown|spoken}` for a word with two forms).
faster-whisper (the Whisper base.en model, on the CPU, 8-bit, with no prompt) listens to the narration and gives each
word's time; the script, never Whisper's words, is the transcript. Spoken and heard words are normalised the same way (lower case,
no punctuation, numbers as words, spelled letters joined) and aligned; matched words take Whisper's times and the rest
are spread between their neighbours. The captions show the script's shown words, at most 2 lines of 32 characters, 0.8
to 3.5 seconds a cue, broken at sentence ends and at pauses over 0.6 s.

If the word error rate (words changed, added or dropped, over the words the script says) is above `--max-wer`, it exits 1
and lists the words: the voice said something else, or the script has a word the voice reads in another way (use
{shown|spoken}). The first run downloads the model (about 140 MiB, once, checked by its SHA-256) into
$HRIZZUP_MODELS_DIR, else ~/.cache/hrizzup-skills/models; `--offline` never downloads.

`--timings` takes the file `voice.py --timings` wrote: Whisper times a word that follows a pause a little early (its first
word reaches back into the silence), so no word is shown before its paragraph is spoken or after it ends.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made and checked; 1 the
reading is too far from the script (nothing is written); 2 bad input; 3 a missing package or model (with what to do).
A mistake in this command itself still ends in the JSON line, with exit 1.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import hrizzup_media

LINE_CHARACTERS = 32
MAX_LINES = 2
CUE_MIN_SECONDS = 0.8
CUE_MAX_SECONDS = 3.5
PAUSE_BREAK_SECONDS = 0.6
LINGER_SECONDS = 0.2  # a cue stays this long after its last word, if the next cue isn't there yet
DEFAULT_MAX_WER = 0.15
CLAUSE_END = re.compile(r"[,;:][\"')\]]*$")
SENTENCE_END = re.compile(r"[.!?][\"')\]\u201d\u2019]*$")

# The model's files: (SHA-256, bytes, name), the digest first (docs/design.md, 5 "Digests" and 10).
MODEL_NAME = "whisper-base.en-3d3d5dee"
MODEL_BASE = "https://huggingface.co/Systran/faster-whisper-base.en/resolve/3d3d5dee26484f91867d81cb899cfcf72b96be6c/"
MODEL_FILES = (
    ("2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef", 145216508, "model.bin"),
    ("f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb", 2227, "config.json"),
    ("929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df", 2128466, "tokenizer.json"),
    ("ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf", 422309, "vocabulary.txt"),
)

# ---- the model downloader (design 10): this block is the same in voice.py and captions.py, and a test checks it ----

class ModelError(Exception):
    """A model file is missing, or couldn't be fetched or checked (exit 3). The message says what to do."""


USER_AGENT = "hrizzup-skills-models/1.0 (+https://github.com/Zugzwang-world/hrizzup-skills)"
TRY_PAUSES = (5, 20)  # seconds waited after the first and the second failed try: three tries in all
READ_BYTES = 1 << 20
CONNECT_SECONDS = 60


def models_root():
    """Where models are kept: $HRIZZUP_MODELS_DIR, else $XDG_CACHE_HOME/hrizzup-skills/models, else
    ~/.cache/hrizzup-skills/models. Never inside the repository."""
    given = os.environ.get("HRIZZUP_MODELS_DIR", "").strip()
    if given:
        return os.path.abspath(given)
    cache = os.environ.get("XDG_CACHE_HOME", "").strip() or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(os.path.abspath(cache), "hrizzup-skills", "models")


def _sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(READ_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_good(path, digest, size):
    """Whether the file is there, of the right size, with the right SHA-256."""
    try:
        return os.path.getsize(path) == size and _sha256_of(path) == digest
    except OSError:
        return False


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise ModelError("a model download was sent on to an address that isn't https (%s): refused" % newurl.split("?")[0][:60])
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(url, start=0):
    """The response for a download (from byte `start` on, when resuming): https only, redirects too, with a user agent
    that says who is asking."""
    if not url.lower().startswith("https://"):
        raise ModelError("a model is fetched over https only, not %s" % url.split("?")[0][:60])
    headers = {"User-Agent": USER_AGENT}
    if start:
        headers["Range"] = "bytes=%d-" % start
    return urllib.request.build_opener(_HttpsOnly).open(urllib.request.Request(url, headers=headers), timeout=CONNECT_SECONDS)


class _Short(Exception):
    """The download stopped before the file was whole, or came out wrong after being resumed: worth another try."""


def _download(url, part, digest, size):
    """Fetch one file to `part`, counting and hashing as it comes, and carrying on from what `part` already holds (a
    server that doesn't take a range sends the file again from the start). A file that is bigger than its size, or whole
    but with another SHA-256, is a ModelError (it will not get better); one that stops short is `_Short`."""
    hasher, have = hashlib.sha256(), 0
    try:
        have = os.path.getsize(part)
    except OSError:
        have = 0
    if have >= size:
        have = 0
    if have:
        with open(part, "rb") as old:
            for block in iter(lambda: old.read(READ_BYTES), b""):
                hasher.update(block)
    with _open(url, have) as response:
        resumed = have > 0 and getattr(response, "status", 200) == 206 and (response.headers.get("Content-Range") or "").startswith("bytes %d-" % have)
        if have and not resumed:
            hasher, have = hashlib.sha256(), 0  # the server sent the whole file again
        stated = response.headers.get("Content-Length")
        if stated and stated.isdigit() and int(stated) != size - have:
            raise ModelError("the server says the file is %s bytes, not the %d this kit expects: the file has changed" % (stated, size - have))
        count = have
        with open(part, "ab" if have else "wb") as out:
            for block in iter(lambda: response.read(READ_BYTES), b""):
                count += len(block)
                if count > size:
                    raise ModelError("the download is longer than the %d bytes this kit expects: the file has changed" % size)
                hasher.update(block)
                out.write(block)
    if count < size:
        raise _Short("%d of %d bytes arrived" % (count, size))
    if hasher.hexdigest() != digest:
        if have:
            _quietly_remove(part)
            raise _Short("the resumed file didn't check out, so it is fetched again from the start")
        raise ModelError("the downloaded file's SHA-256 isn't the one this kit expects: the file has changed or was damaged")


def _fetch(base, digest, size, name, folder, log):
    """Download one model file into `folder`: to `<name>.part`, checked, then renamed. 3 tries, the pauses of TRY_PAUSES
    apart; a try that stops short carries on from where it stopped."""
    final, part = os.path.join(folder, name), os.path.join(folder, name + ".part")
    log("downloading %s (%.1f MiB) from %s" % (name, size / 1048576, base.split("/")[2]))
    _quietly_remove(part)  # a part left by an earlier run isn't trusted
    problem = "no try was made"
    for attempt in range(len(TRY_PAUSES) + 1):
        try:
            _download(base + name, part, digest, size)
            os.replace(part, final)
            return
        except ModelError:
            _quietly_remove(part)
            raise
        except urllib.error.HTTPError as error:
            problem = "the server answered %d %s" % (error.code, error.reason)
            if 400 <= error.code < 500 and error.code not in (416, 429):
                _quietly_remove(part)
                raise ModelError("couldn't download %s: %s (the address is wrong or the file has moved)" % (name, problem))
            if error.code == 416:
                _quietly_remove(part)  # a range that can't be had: start again
        except (urllib.error.URLError, OSError, TimeoutError, _Short, http.client.HTTPException) as error:
            problem = str(getattr(error, "reason", None) or error) or type(error).__name__
        if attempt < len(TRY_PAUSES):
            log("%s: %s; trying again in %d s" % (name, problem, TRY_PAUSES[attempt]))
            time.sleep(TRY_PAUSES[attempt])
    _quietly_remove(part)
    raise ModelError("couldn't download %s after %d tries (%s): check the network and run again, or copy the file into %s"
                     % (name, len(TRY_PAUSES) + 1, problem, folder))


def _quietly_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


def ensure_model(folder_name, base, files, offline, log):
    """The folder that holds a model's files, each checked by size and SHA-256 (`files` are (digest, bytes, name) tuples).
    A missing or damaged file is downloaded unless `offline`; then the message says what to do. Raises ModelError."""
    folder = os.path.join(models_root(), folder_name)
    wanted = [(digest, size, name) for digest, size, name in files if not _is_good(os.path.join(folder, name), digest, size)]
    if wanted and offline:
        total = sum(size for _digest, size, _name in wanted) / 1048576
        raise ModelError("the model file%s %s %s missing or damaged in %s, and --offline was given. Run the command once without "
                         "--offline (it downloads about %.0f MiB, once), or copy the files there from another machine"
                         % ("s" if len(wanted) > 1 else "", ", ".join(name for _d, _s, name in wanted), "are" if len(wanted) > 1 else "is",
                            folder, total))
    if wanted:
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as error:
            raise ModelError("can't make the models folder %s (%s): set HRIZZUP_MODELS_DIR to one you can write" % (folder, error.strerror))
        for digest, size, name in wanted:
            try:
                _fetch(base, digest, size, name, folder, log)
            except OSError as error:
                raise ModelError("can't write %s into %s (%s)" % (name, folder, error.strerror or type(error).__name__))
    return folder


# ---- end of the model downloader ----


class InputError(Exception):
    """The input is wrong (exit 2)."""


# ---------------------------------------------------------------------------------------------
# Reading the command line (standard library only)
# ---------------------------------------------------------------------------------------------

def log(message):
    print(message, file=sys.stderr, flush=True)


def finish(ok, outputs, checks, problem, code):
    print(json.dumps({"ok": ok, "outputs": outputs, "checks": checks, "problem": problem}, ensure_ascii=False))
    return code


class Parser(argparse.ArgumentParser):
    """A command line that is wrong is bad input (exit 2, with the JSON line), not argparse's own exit."""

    def error(self, message):
        raise InputError(message)


def make_parser():
    parser = Parser(
        prog="captions.py",
        description="Time a narration's words against its script and make the captions' cues (captions.json, and an .srt if asked).",
        epilog="Example: uv run scripts/captions.py --audio narration.m4a --script script.txt --out captions.json --srt captions.srt",
    )
    parser.add_argument("--audio", required=True, help="the narration: an .m4a made by voice.py (an .mp3, .wav or .mp4 works too)")
    parser.add_argument("--script", required=True, help="the script the voice read (never an input to be overwritten)")
    parser.add_argument("--out", required=True, help="the captions to write: a .json file")
    parser.add_argument("--srt", help="also write the cues as an .srt file")
    parser.add_argument("--timings", help="the timings file voice.py wrote for this script: no word is shown before its paragraph is spoken or after it ends")
    parser.add_argument("--max-wer", type=float, default=DEFAULT_MAX_WER,
                        help="the largest word error rate to accept, 0 to 1 (default %.2f); over it the command exits 1 and lists the words" % DEFAULT_MAX_WER)
    parser.add_argument("--offline", action="store_true", help="never download: stop, saying what to do, if the model isn't already in the models folder")
    return parser


def check_arguments(args):
    if not 0.0 <= args.max_wer <= 1.0:
        raise InputError("--max-wer is 0 to 1")
    for name, path in (("--audio", args.audio), ("--script", args.script)):
        if not os.path.isfile(path):
            raise InputError("can't read %s %s: it isn't a file" % (name, path))
    out = os.path.abspath(args.out)
    srt = os.path.abspath(args.srt) if args.srt else None
    if os.path.splitext(out)[1].lower() != ".json":
        raise InputError("--out is a .json file")
    if srt and os.path.splitext(srt)[1].lower() != ".srt":
        raise InputError("--srt is an .srt file")
    for path in (out, srt):
        if not path:
            continue
        for given in (args.audio, args.script):
            if hrizzup_media.same_file(given, path):
                raise InputError("%s would overwrite %s, an input" % (os.path.basename(path), given))
        folder = os.path.dirname(path)
        if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
            raise InputError("the folder for %s doesn't exist or can't be written to" % path)
    if srt and hrizzup_media.same_file(out, srt):
        raise InputError("--out and --srt are the same file")
    if args.timings and not os.path.isfile(args.timings):
        raise InputError("can't read --timings %s: it isn't a file" % args.timings)
    return out, srt


# ---------------------------------------------------------------------------------------------
# Cues: what the captions show, and when
# ---------------------------------------------------------------------------------------------

def wrap_lines(words, width=LINE_CHARACTERS, limit=MAX_LINES):
    """The words as lines of at most `width` characters (a single longer word is a line of its own), or None if they
    need more than `limit` lines."""
    lines, current = [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word) if current else word
    if current:
        lines.append(current)
    return lines if len(lines) <= limit else None


def _segments(units):
    """Runs of units with a hard break between them: the end of a sentence, or a pause over 0.6 s."""
    runs, current = [], []
    for number, unit in enumerate(units):
        if current:
            last = units[current[-1]]
            if SENTENCE_END.search(last["shown"]) or unit["start"] - last["end"] > PAUSE_BREAK_SECONDS:
                runs.append(current)
                current = []
        current.append(number)
    if current:
        runs.append(current)
    return runs


def _best_split(units, run):
    """How to cut one run of units into cues: the fewest cues that each fit 2 lines of 32 characters and 3.5 seconds, and
    among those the most even (so a sentence doesn't leave a single word on a cue by itself), cutting after a comma where it can.
    Returns lists of unit numbers."""
    size = len(run)
    best = [None] * (size + 1)  # best[i]: (cues, unevenness, cut that ended at i) for the first i units
    best[0] = (0, 0.0, 0)
    for end in range(1, size + 1):
        for begin in range(end - 1, -1, -1):
            words = " ".join(units[run[k]]["shown"] for k in range(begin, end)).split()
            if wrap_lines(words) is None or units[run[end - 1]]["end"] - units[run[begin]]["start"] > CUE_MAX_SECONDS:
                if begin < end - 1:
                    break  # a longer cue only gets longer; a single unit that is too big is allowed on its own
            if best[begin] is None:
                continue
            fill = min(1.0, len(" ".join(words)) / float(LINE_CHARACTERS * MAX_LINES))
            # a cut inside a clause costs a little; a cut after a comma or a colon costs nothing
            mid_clause = 0.0 if end == size or CLAUSE_END.search(units[run[end - 1]]["shown"]) else 0.25
            candidate = (best[begin][0] + 1, best[begin][1] + (1.0 - fill) ** 2 + mid_clause, begin)
            if best[end] is None or candidate[:2] < best[end][:2]:
                best[end] = candidate
    cuts, end = [], size
    while end > 0:
        begin = best[end][2]
        cuts.append(run[begin:end])
        end = begin
    return cuts[::-1]


def make_cues(units, seconds):
    """Cues from timed units (dicts with "shown", "start" and "end"): at most 2 lines of 32 characters, 0.8 to 3.5 seconds,
    broken at sentence ends and at pauses over 0.6 s, and cut evenly inside a long sentence. A cue starts with its first
    word and stays a little after its last, never into the next cue; one shorter than 0.8 s is held up to 0.8 s where the
    next cue isn't yet due (speech itself shorter than that stays as it is)."""
    cues = []
    for run in _segments(units):
        for group in _best_split(units, run):
            words = " ".join(units[i]["shown"] for i in group).split()
            cues.append({"start": units[group[0]]["start"], "end": units[group[-1]]["end"], "lines": wrap_lines(words) or [" ".join(words)]})
    for number, cue in enumerate(cues):
        following = cues[number + 1]["start"] if number + 1 < len(cues) else seconds
        end = max(cue["end"] + LINGER_SECONDS, cue["start"] + CUE_MIN_SECONDS)
        end = min(end, cue["start"] + CUE_MAX_SECONDS, following)
        cue["end"] = round(max(end, cue["start"]), 3)
        cue["start"] = round(cue["start"], 3)
    return cues


def srt_time(seconds):
    millis = int(round(seconds * 1000))
    return "%02d:%02d:%02d,%03d" % (millis // 3600000, millis // 60000 % 60, millis // 1000 % 60, millis % 1000)


def srt_text(cues):
    return "".join("%d\n%s --> %s\n%s\n\n" % (n, srt_time(c["start"]), srt_time(c["end"]), "\n".join(c["lines"])) for n, c in enumerate(cues, 1)).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------------------------
# Paragraph times from the voice
# ---------------------------------------------------------------------------------------------

CLAMP_SLACK_SECONDS = 0.05  # the narration's start can differ from the voice's by the encoder's delay


def read_paragraph_times(path, paragraphs):
    """[(start, end)] for each paragraph, from the file `voice.py --timings` wrote. Raises InputError if it isn't for a script
    with this many paragraphs."""
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
        spans = [(float(p["start"]), float(p["end"])) for p in document["paragraphs"]]
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError) as error:
        raise InputError("--timings %s isn't a timings file written by voice.py (%s: %s)" % (path, type(error).__name__, error))
    if len(spans) != paragraphs:
        raise InputError("--timings %s holds %d paragraphs and the script has %d: it is the timings of another script" % (path, len(spans), paragraphs))
    return spans


def clamp_to_paragraphs(units, spans):
    """Move each unit's time inside the time its paragraph is spoken (`units` are dicts with "paragraph", "start" and "end"). A time
    within 0.05 s of its paragraph (the encoder's delay) is left as it is; a word heard before its paragraph starts is moved to
    the start, and one heard after it ends to the end."""
    for unit in units:
        low, high = spans[unit["paragraph"]]
        start = unit["start"]
        if start < low - CLAMP_SLACK_SECONDS:
            start = low
        elif start > high + CLAMP_SLACK_SECONDS:
            start = high
        end = unit["end"]
        if end > high + CLAMP_SLACK_SECONDS:
            end = high
        unit["start"] = round(start, 3)
        unit["end"] = round(max(end, start), 3)
    return units


# ---------------------------------------------------------------------------------------------
# Listening
# ---------------------------------------------------------------------------------------------

def listen(audio, model_folder):
    """(the recognised words as hrizzup_script.Heard, the audio's length in seconds), by faster-whisper: base.en on the CPU,
    8-bit, English, beam size 5, word times, and no memory of the text before (`condition_on_previous_text=False`). It is given
    no initial prompt: the design asked for the script's first 200 characters, but Whisper then treats them as already said
    and leaves them out (30 words of the audio brief sample, found at M4), so a name it spells another way costs a word
    error instead and `{shown|spoken}` is the way to give it."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")  # the model is in a folder: nothing is asked of the Hugging Face hub
    import hrizzup_script
    from faster_whisper import WhisperModel

    model = WhisperModel(model_folder, device="cpu", compute_type="int8")
    segments, info = model.transcribe(audio, language="en", beam_size=5, word_timestamps=True, condition_on_previous_text=False)
    heard = []
    for segment in segments:
        for word in segment.words or []:
            heard.append(hrizzup_script.Heard(word.word.strip(), float(word.start), float(word.end)))  # numpy floats become floats
    return heard, float(info.duration)


# ---------------------------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------------------------

def main(argv=None):
    """Make the captions; whatever goes wrong, the last line printed is the JSON line."""
    try:
        return make(argv)
    except ImportError as error:  # a package turned out to be missing deep inside a call
        message = ("a Python package or module is missing (%s): get the kit again and install its packages with `uv run scripts/captions.py`, "
                   "or `.venv/bin/python -m pip install --require-hashes -r scripts/captions.requirements.txt`" % error)
        log("captions.py: " + message)
        return finish(False, [], [], message, 3)
    except Exception as error:  # the last resort: a mistake in this command, never a bare traceback
        message = "captions.py failed unexpectedly (%s: %s): this is a mistake in the kit, so tell your owner" % (type(error).__name__, error)
        log("captions.py: " + message)
        return finish(False, [], [], message, 1)


def make(argv=None):
    try:
        args = make_parser().parse_args(argv)
        out, srt = check_arguments(args)
        import hrizzup_script

        try:
            with open(args.script, encoding="utf-8") as f:
                script = hrizzup_script.parse(f.read())
        except (OSError, UnicodeDecodeError) as error:
            raise InputError("can't read the script %s as UTF-8 text: %s" % (args.script, error))
        except hrizzup_script.ScriptError as error:
            raise InputError(str(error))
        spans = read_paragraph_times(args.timings, len(script.paragraphs)) if args.timings else None
    except InputError as error:
        log("captions.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    try:
        import faster_whisper  # noqa: F401  (checked here so a missing package is exit 3 before a model is fetched)
    except ImportError as error:
        message = ("a Python package is missing (%s): run this with `uv run scripts/captions.py`, which installs them, or make a virtual "
                   "environment and install the exact set: `python3.12 -m venv .venv`, `.venv/bin/python -m pip install --require-hashes "
                   "-r scripts/captions.requirements.txt`, then `.venv/bin/python scripts/captions.py ...`" % error)
        log("captions.py: " + message)
        return finish(False, [], [], message, 3)
    try:
        folder = ensure_model(MODEL_NAME, MODEL_BASE, MODEL_FILES, args.offline, log)
    except ModelError as error:
        log("captions.py: %s" % error)
        return finish(False, [], [], str(error), 3)
    began = time.time()
    heard, seconds = listen(args.audio, folder)
    log("captions.py: heard %d words in %.1f s of sound (took %.1f s)" % (len(heard), seconds, time.time() - began))
    units = script.units()
    said = hrizzup_script.spoken_words(units)
    said_words = [word for word, _ in said]
    heard_words = hrizzup_script.timed_words(heard)
    rate = hrizzup_script.word_error_rate(said_words, [word for word, _s, _e in heard_words])
    log("captions.py: word error rate %.3f over %d spoken words (the limit is %.2f)" % (rate, len(said_words), args.max_wer))
    checks = [{"name": "the voice said the script (word error rate at most %.2f)" % args.max_wer, "ok": rate <= args.max_wer,
               "wordErrorRate": round(rate, 3)}]
    if rate > args.max_wer:
        differing = hrizzup_script.differences(said_words, [word for word, _s, _e in heard_words])
        message = ("the narration isn't the script: word error rate %.2f is over --max-wer %.2f. Where they part: %s. Fix the script, or "
                   "give a word the way it is said with {shown|spoken}" % (rate, args.max_wer, "; ".join(differing)))
        log("captions.py: " + message)
        return finish(False, [], checks, message, 1)
    times = hrizzup_script.align_times(said_words, heard_words, seconds)
    unit_times = {}  # a unit's time: the slices of the words it says
    matched = {}
    for (word, covered), (start, end, was_matched) in zip(said, times):
        share = (end - start) / len(covered)
        for position, index in enumerate(covered):
            low, high = start + position * share, start + (position + 1) * share
            first, last = unit_times.get(index, (low, high))
            unit_times[index] = (min(first, low), max(last, high))
            matched[index] = matched.get(index, True) and was_matched
    timed, previous_end = [], 0.0
    for index, unit in enumerate(units):
        start, end = unit_times.get(index, (previous_end, previous_end))  # a unit that says nothing (a dash) sits where it falls
        timed.append({"shown": unit.shown, "paragraph": unit.paragraph, "start": round(start, 3), "end": round(end, 3),
                      "matched": matched.get(index, False)})
        previous_end = max(previous_end, end)
    if spans:
        timed = clamp_to_paragraphs(timed, spans)
    cues = make_cues(timed, seconds)
    document = {"audio": os.path.basename(args.audio), "seconds": round(seconds, 3), "model": "Whisper base.en (faster-whisper)",
                "wordErrorRate": round(rate, 3), "maxWordErrorRate": args.max_wer, "paragraphTimesFromVoice": bool(args.timings),
                "cues": cues, "words": timed}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
        f.write("\n")
    written = [(out, args.out)]
    if srt:
        with open(srt, "w", encoding="utf-8", newline="") as f:
            f.write(srt_text(cues))
        written.append((srt, args.srt))
    log("captions.py: %d cues for %d words" % (len(cues), len(timed)))
    outputs = [{"path": given if not os.path.isabs(given) else path, "bytes": os.path.getsize(path), "width": None, "height": None,
                "seconds": round(seconds, 3)} for path, given in written]
    return finish(True, outputs, checks, None, 0)


if __name__ == "__main__":
    sys.exit(main())
