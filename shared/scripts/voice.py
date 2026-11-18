# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["numpy==2.5.4", "kokoro-onnx==0.6.1", "onnxruntime==1.32.0", "imageio-ffmpeg==0.8.1"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Make a narration: read a script aloud with Kokoro-82M, level it to -16 LUFS and write it as an M4A.

The script is plain text. Paragraphs are separated by a blank line. `{shown|spoken}` gives a word a spoken form
that differs from the shown one: `{AQI|A Q I}` is said "A Q I" and shown, in the captions and the transcript, as
"AQI". The voices are af_heart (the default), af_bella, bf_emma (British), am_michael, am_fenrir and bm_george.

It reads English only. The first run downloads the model (about 140 MiB, once, checked by its SHA-256) into
$HRIZZUP_MODELS_DIR, else ~/.cache/hrizzup-skills/models; `--offline` never downloads. Past `--max-seconds` it exits 1
and says how many words to cut: speech is never trimmed or sped up to fit.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made and checked;
1 the narration failed a Hrizzup limit or quality check (too long, or not at the loudness Hrizzup wants: nothing is
left behind); 2 bad input; 3 a missing package, tool or model (with what to install or run). A mistake in this
command itself still ends in the JSON line, with exit 1.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave

import hrizzup_media

SAMPLE_RATE = 24000  # Kokoro's own rate
VOICES = ("af_heart", "af_bella", "bf_emma", "am_michael", "am_fenrir", "bm_george")
SPEED_RANGE = (0.85, 1.15)
CHUNK_CHARACTERS = 250  # sentences are joined into chunks of about this many characters, never across paragraphs
SILENCE_BEFORE = 0.3
SILENCE_BETWEEN_CHUNKS = 0.25
SILENCE_BETWEEN_PARAGRAPHS = 0.6
SILENCE_AFTER = 0.5
DEFAULT_MAX_SECONDS = hrizzup_media.AUDIO_MAX_SECONDS  # 295
ABBREVIATIONS = frozenset("mr mrs ms dr st no vs prof sr jr mt rs approx etc".split())

# The model's files: (SHA-256, bytes, name), the digest first (docs/design.md, 5 "Digests" and 10).
MODEL_NAME = "kokoro-82m-v1.0-int8"
MODEL_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
MODEL_FILES = (
    ("ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c", 114119327, "kokoro-v1.0.int8.onnx"),
    ("bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d", 28214398, "voices-v1.0.bin"),
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


class CheckError(Exception):
    """The narration was made but breaks a limit (exit 1)."""


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
        prog="voice.py",
        description="Read a script aloud (Kokoro-82M), level it to -16 LUFS and write it as an M4A narration.",
        epilog="Example: uv run scripts/voice.py --script script.txt --out narration.m4a --timings timings.json",
    )
    parser.add_argument("--script", required=True, help="the script: plain text, paragraphs apart by a blank line, {shown|spoken} for a spoken form")
    parser.add_argument("--out", required=True, help="the narration to write: an .m4a (never an input)")
    parser.add_argument("--voice", default="af_heart", choices=VOICES, help="the voice (default af_heart)")
    parser.add_argument("--speed", type=float, default=1.0, help="speaking speed, %.2f to %.2f (default 1.0)" % SPEED_RANGE)
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS,
                        help="the longest narration to accept, at most %d (default %d); a longer one exits 1 and says how many words to cut"
                             % (DEFAULT_MAX_SECONDS, DEFAULT_MAX_SECONDS))
    parser.add_argument("--timings", help="also write when each paragraph and chunk is spoken, as JSON (never an input)")
    parser.add_argument("--offline", action="store_true", help="never download: stop, saying what to do, if the model isn't already in the models folder")
    return parser


def check_arguments(args):
    """The paths and numbers, checked before any work. Returns the absolute output and timings paths."""
    if not SPEED_RANGE[0] <= args.speed <= SPEED_RANGE[1]:
        raise InputError("--speed is %.2f to %.2f" % SPEED_RANGE)
    if not 1 <= args.max_seconds <= DEFAULT_MAX_SECONDS:
        raise InputError("--max-seconds is 1 to %d (Hrizzup allows 300 seconds of audio; this kit keeps a margin)" % DEFAULT_MAX_SECONDS)
    if not os.path.isfile(args.script):
        raise InputError("can't read the script %s: it isn't a file" % args.script)
    out = os.path.abspath(args.out)
    timings = os.path.abspath(args.timings) if args.timings else None
    for given in (args.script, args.timings):
        if given and hrizzup_media.same_file(given, out):
            raise InputError("--out would overwrite %s, an input" % given)
    if timings and hrizzup_media.same_file(args.script, timings):
        raise InputError("--timings would overwrite the script")
    if timings and hrizzup_media.same_file(out, timings):
        raise InputError("--timings and --out are the same file")
    if os.path.splitext(out)[1].lower() != ".m4a":
        raise InputError("--out is an .m4a file")
    for path in (out, timings):
        if path:
            folder = os.path.dirname(path)
            if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
                raise InputError("the folder for %s doesn't exist or can't be written to" % path)
    return out, timings


# ---------------------------------------------------------------------------------------------
# Sentences and chunks
# ---------------------------------------------------------------------------------------------

SENTENCE_END = re.compile(r"[.!?][\"')\]\u201d\u2019]*(?=\s+[\"'(\[\u201c\u2018]?[A-Z0-9])")


def split_sentences(text):
    """A paragraph's sentences (a closing quote stays with its sentence). A full stop after an abbreviation or a single capital
    letter (Dr. Rs. J.) isn't a sentence end."""
    text = text.strip()
    sentences, begin = [], 0
    for found in SENTENCE_END.finditer(text):
        piece = text[begin:found.end()]
        last = piece.rstrip(".!?\"')\u201d\u2019").rsplit(" ", 1)[-1]
        if found.group(0).startswith(".") and (last.lower() in ABBREVIATIONS or (len(last) == 1 and last.isupper())):
            continue  # an abbreviation or an initial: the sentence goes on
        sentences.append(piece)
        begin = found.end()
        while begin < len(text) and text[begin].isspace():
            begin += 1
    if text[begin:]:
        sentences.append(text[begin:])
    return [s for s in sentences if s]


def chunk_paragraph(text, limit=CHUNK_CHARACTERS):
    """Sentences joined into chunks of at most `limit` characters (a longer sentence is a chunk of its own)."""
    chunks, current = [], ""
    for sentence in split_sentences(text):
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = (current + " " + sentence) if current else sentence
    if current:
        chunks.append(current)
    return chunks


# ---------------------------------------------------------------------------------------------
# The narration
# ---------------------------------------------------------------------------------------------

def speak(script, voice, speed, model_folder, np):
    """Speak every chunk, in turn, with one Kokoro instance. Returns (the samples at 24 kHz, the timings)."""
    from kokoro_onnx import Kokoro  # the only place the GPL phonemizer comes in (design 5)

    kokoro = Kokoro(os.path.join(model_folder, MODEL_FILES[0][2]), os.path.join(model_folder, MODEL_FILES[1][2]))
    lang = "en-gb" if voice.startswith("b") else "en-us"

    def silence(seconds):
        return np.zeros(int(round(seconds * SAMPLE_RATE)), dtype=np.float32)

    parts, paragraphs, chunks = [silence(SILENCE_BEFORE)], [], []
    parts_seconds = SILENCE_BEFORE
    for paragraph in script.paragraphs:
        start = parts_seconds
        pieces = chunk_paragraph(paragraph.spoken)
        for number, text in enumerate(pieces):
            if number:
                parts.append(silence(SILENCE_BETWEEN_CHUNKS))
                parts_seconds += SILENCE_BETWEEN_CHUNKS
            began = time.time()
            samples, rate = kokoro.create(text, voice=voice, speed=speed, lang=lang)
            if rate != SAMPLE_RATE:
                raise CheckError("the model answered at %d Hz, not %d" % (rate, SAMPLE_RATE))
            samples = np.asarray(samples, dtype=np.float32).ravel()
            seconds = len(samples) / SAMPLE_RATE
            log("paragraph %d, chunk %d: %d characters said in %.1f s of sound (took %.1f s)" % (
                paragraph.index + 1, number + 1, len(text), seconds, time.time() - began))
            chunks.append({"paragraph": paragraph.index, "start": round(parts_seconds, 3), "end": round(parts_seconds + seconds, 3), "spoken": text})
            parts.append(samples)
            parts_seconds += seconds
        paragraphs.append({"index": paragraph.index, "start": round(start, 3), "end": round(parts_seconds, 3),
                           "shown": paragraph.shown, "words": len(paragraph.shown.split())})
        if paragraph is not script.paragraphs[-1]:
            parts.append(silence(SILENCE_BETWEEN_PARAGRAPHS))
            parts_seconds += SILENCE_BETWEEN_PARAGRAPHS
    parts.append(silence(SILENCE_AFTER))
    samples = np.concatenate(parts)
    return samples, {"sampleRate": SAMPLE_RATE, "paragraphs": paragraphs, "chunks": chunks}


def write_wav(samples, path, np):
    """A 16-bit mono WAV at Kokoro's rate (written with `wave`)."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def words_to_cut(script, seconds, limit):
    """About how many words to cut so the narration fits `limit` seconds."""
    words = sum(len(p.shown.split()) for p in script.paragraphs) or 1
    return max(1, int(math.ceil((seconds - limit) * words / seconds)) + 2)


# ---------------------------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------------------------

def main(argv=None):
    """Make the narration; whatever goes wrong, the last line printed is the JSON line."""
    try:
        return make(argv)
    except ImportError as error:  # a package turned out to be missing deep inside a call
        message = ("a Python package or module is missing (%s): get the kit again and install its packages with `uv run scripts/voice.py`, "
                   "or `.venv/bin/python -m pip install --require-hashes -r scripts/voice.requirements.txt`" % error)
        log("voice.py: " + message)
        return finish(False, [], [], message, 3)
    except hrizzup_media.FfmpegError as error:
        log("voice.py: %s" % error)
        return finish(False, [], [], str(error), error.code)
    except Exception as error:  # the last resort: a mistake in this command, never a bare traceback
        message = "voice.py failed unexpectedly (%s: %s): this is a mistake in the kit, so tell your owner" % (type(error).__name__, error)
        log("voice.py: " + message)
        return finish(False, [], [], message, 1)


def make(argv=None):
    try:
        args = make_parser().parse_args(argv)
        out, timings_path = check_arguments(args)
        import hrizzup_script

        try:
            with open(args.script, encoding="utf-8") as f:
                script = hrizzup_script.parse(f.read())
        except (OSError, UnicodeDecodeError) as error:
            raise InputError("can't read the script %s as UTF-8 text: %s" % (args.script, error))
        except hrizzup_script.ScriptError as error:
            raise InputError(str(error))
    except InputError as error:
        log("voice.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    try:
        import numpy as np
        import kokoro_onnx  # noqa: F401  (checked here so a missing package is exit 3 before a model is fetched)
    except ImportError as error:
        message = ("a Python package is missing (%s): run this with `uv run scripts/voice.py`, which installs them, or make a virtual "
                   "environment and install the exact set: `python3.12 -m venv .venv`, `.venv/bin/python -m pip install --require-hashes "
                   "-r scripts/voice.requirements.txt`, then `.venv/bin/python scripts/voice.py ...`" % error)
        log("voice.py: " + message)
        return finish(False, [], [], message, 3)
    ff = hrizzup_media.find_ffmpeg(video=False)
    log("voice.py: " + ff.describe())
    try:
        folder = ensure_model(MODEL_NAME, MODEL_BASE, MODEL_FILES, args.offline, log)
    except ModelError as error:
        log("voice.py: %s" % error)
        return finish(False, [], [], str(error), 3)
    began = time.time()
    samples, timings = speak(script, args.voice, args.speed, folder, np)
    seconds = len(samples) / SAMPLE_RATE
    log("voice.py: %.1f s of narration made in %.0f s" % (seconds, time.time() - began))
    if seconds > args.max_seconds:
        cut = words_to_cut(script, seconds, args.max_seconds)
        message = ("the narration is %.1f s, over --max-seconds %.1f: cut about %d words from the script (speech is never trimmed "
                   "or sped up to fit)" % (seconds, args.max_seconds, cut))
        log("voice.py: " + message)
        return finish(False, [], [{"name": "within --max-seconds", "ok": False, "seconds": round(seconds, 1)}], message, 1)
    part = out[:-4] + ".part.m4a"
    handle, wav = tempfile.mkstemp(suffix=".wav", prefix="narration-")
    os.close(handle)
    try:
        write_wav(samples, wav, np)
        measured = hrizzup_media.loudnorm_measure(ff, wav)
        log("voice.py: before levelling %.1f LUFS, true peak %.1f dBTP" % (measured["input_i"], measured["input_tp"]))
        target = hrizzup_media.TRUE_PEAK_TARGET_DBTP
        for attempt in range(1, hrizzup_media.LOUDNORM_ATTEMPTS + 1):
            kind = hrizzup_media.loudnorm_apply(ff, wav, measured, part, target)
            after = hrizzup_media.loudnorm_measure(ff, part)
            if after["input_tp"] <= hrizzup_media.TRUE_PEAK_SETTLE_DBTP or attempt == hrizzup_media.LOUDNORM_ATTEMPTS:
                break
            # the AAC encoder adds to the peak loudnorm saw: level again with a lower target, so the file settles clear of the limit
            lower = hrizzup_media.next_true_peak_target(target, after["input_tp"])
            log("voice.py: the encoded file's true peak is %.2f dBTP (the limit is %.1f; this is levelled again above %.1f); trying a target of %.1f" % (
                after["input_tp"], hrizzup_media.TRUE_PEAK_MAX_DBTP, hrizzup_media.TRUE_PEAK_SETTLE_DBTP, lower))
            target = lower
        info = hrizzup_media.inspect(part)
    except hrizzup_media.MediaError as error:
        _remove(part)
        return finish(False, [], [], "the narration can't be read back: %s" % error, 1)
    except hrizzup_media.FfmpegError:
        _remove(part)
        raise
    finally:
        _remove(wav)
    problems = hrizzup_media.problems(info, "audio", budget=False) + hrizzup_media.loudness_problems(after)
    checks = [
        {"name": "Hrizzup's audio limits", "ok": not hrizzup_media.problems(info, "audio", budget=False)},
        {"name": "loudness", "ok": not hrizzup_media.loudness_problems(after), "integratedLufs": round(after["input_i"], 1),
         "truePeakDbtp": round(after["input_tp"], 1), "normalization": kind, "truePeakTarget": target},
    ]
    if problems:
        _remove(part)
        message = "; ".join(problems)
        log("voice.py: the narration failed its checks: " + message)
        return finish(False, [], checks, message, 1)
    os.replace(part, out)
    if timings_path:
        timings.update({"voice": args.voice, "speed": args.speed, "seconds": round(info.seconds, 3)})
        with open(timings_path, "w", encoding="utf-8") as f:
            json.dump(timings, f, indent=2, ensure_ascii=False)
            f.write("\n")
    log("voice.py: %.1f LUFS, true peak %.1f dBTP (%s); %d bytes, %.2f s" % (after["input_i"], after["input_tp"], kind, info.bytes, info.seconds))
    outputs = [{"path": os.path.relpath(out) if not os.path.isabs(args.out) else out, "bytes": info.bytes, "width": None,
                "height": None, "seconds": round(info.seconds, 3)}]
    return finish(True, outputs, checks, None, 0)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
