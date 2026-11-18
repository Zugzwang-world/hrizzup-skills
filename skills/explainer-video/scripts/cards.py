# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow==13.0.0", "fonttools==4.68.0"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Make a video's cards: 1080 x 1920 pictures of one idea each, in plain templates, to use as scenes in `edit.py`.

A cards file is JSON: {"cards": [{"kind": ..., ...}, ...]}. The kinds and their fields:

    title    "title", and optionally "kicker" and "subtitle"
    fact     "value" (a big number or a short word), "text", and optionally "label"
    list     "title" and "items" (2 to 4 short lines)
    quote    "quote", and optionally "by"
    sources  "items" (1 to 4 short lines), and optionally "title" (default "Sources")

Any card may also have "name" (the file's name, without .png); otherwise it is <number>-<kind>.png. Every card keeps its
text above the bottom fifth of the picture, where `edit.py` puts the captions, and the top is left for the style's
signature. The fonts draw English (Latin) letters only for now.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made and checked;
1 a card failed a Hrizzup limit or quality check (a text too long: it says how far to shorten; nothing is written);
2 bad input; 3 a missing package or kit file. A mistake in this command itself still ends in the JSON line, with exit 1.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import hrizzup_media

KIT = Path(__file__).resolve().parent.parent
TEMPLATES = KIT / "assets" / "templates"
SIZE = hrizzup_media.VIDEO_SIZE  # a video's frame: 1080 x 1920
# kind: (the fields it must have, the fields it may have, the fields that hold a list of lines)
KINDS = {
    "title": (("title",), ("kicker", "subtitle"), ()),
    "fact": (("value", "text"), ("label",), ()),
    "list": (("title", "items"), (), ("items",)),
    "quote": (("quote",), ("by",), ()),
    "sources": (("items",), ("title",), ("items",)),
}
LIMITS = {"title": 90, "kicker": 40, "subtitle": 140, "value": 12, "text": 240, "label": 40, "quote": 280, "by": 80, "items": 90}
ITEMS = (1, 4)  # a list or sources card holds this many lines
SAME_SIZE = [["item1", "item2", "item3", "item4"]]  # a card's lines are drawn at one size, so they read evenly
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")


class InputError(Exception):
    """The input is wrong (exit 2)."""


def clean(value, what, limit):
    """A text as one line: whitespace collapsed, no control characters, 1 to `limit` characters."""
    if not isinstance(value, str):
        raise InputError("%s must be text" % what)
    if any(ord(c) < 32 and c not in "\n\t" or 127 <= ord(c) < 160 for c in value):
        raise InputError("%s has a control character" % what)
    cleaned = " ".join(value.split())
    if not cleaned:
        raise InputError("%s is empty" % what)
    if len(cleaned) > limit:
        raise InputError("%s is %d characters; at most %d" % (what, len(cleaned), limit))
    return cleaned


def read_cards(path):
    """The cards file as a list of (file stem, kind, {slot: text}). Raises InputError naming what is wrong."""
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, UnicodeDecodeError) as error:
        raise InputError("can't read the cards file %s: %s" % (path, error))
    except ValueError as error:
        raise InputError("the cards file %s isn't valid JSON: %s" % (path, error))
    if not isinstance(document, dict) or set(document) != {"cards"} or not isinstance(document["cards"], list):
        raise InputError('the cards file is {"cards": [ ... ]}')
    cards = document["cards"]
    if not 1 <= len(cards) <= 40:
        raise InputError("a cards file holds 1 to 40 cards, not %d" % len(cards))
    found, used = [], set()
    for number, card in enumerate(cards, 1):
        where = "card %d" % number
        if not isinstance(card, dict) or card.get("kind") not in KINDS:
            raise InputError("%s: \"kind\" is one of %s" % (where, ", ".join(KINDS)))
        kind = card["kind"]
        must, may, lists = KINDS[kind]
        extra = set(card) - {"kind", "name"} - set(must) - set(may)
        if extra:
            raise InputError("%s (%s): unknown field %s; a %s card has %s" % (where, kind, ", ".join(sorted(extra)), kind, ", ".join(must + may)))
        for field in must:
            if field not in card:
                raise InputError("%s (%s): \"%s\" is needed" % (where, kind, field))
        texts = {}
        for field in must + may:
            if field not in card:
                continue
            if field in lists:
                items = card[field]
                if not isinstance(items, list) or not ITEMS[0] <= len(items) <= ITEMS[1]:
                    raise InputError("%s (%s): \"%s\" is a list of %d to %d lines" % (where, kind, field, ITEMS[0], ITEMS[1]))
                for position, line in enumerate(items, 1):
                    texts["item%d" % position] = clean(line, "%s, %s %d" % (where, field, position), LIMITS[field])
            else:
                texts[field] = clean(card[field], "%s, %s" % (where, field), LIMITS[field])
        if kind == "sources" and "title" not in texts:
            texts["title"] = "Sources"
        stem = card.get("name", "%02d-%s" % (number, kind))
        if not isinstance(stem, str) or not NAME.match(stem):
            raise InputError("%s: \"name\" is lower-case letters, digits, - and _ (at most 60), not %r" % (where, stem))
        if stem in used:
            raise InputError("%s: the file name %s is used twice" % (where, stem))
        used.add(stem)
        found.append((stem, kind, texts))
    return found


def log(message):
    print(message, file=sys.stderr)


def finish(ok, outputs, checks, problem, code):
    print(json.dumps({"ok": ok, "outputs": outputs, "checks": checks, "problem": problem}, ensure_ascii=False))
    return code


class Parser(argparse.ArgumentParser):
    """A command line that is wrong is bad input (exit 2, with the JSON line), not argparse's own exit."""

    def error(self, message):
        raise InputError(message)


def make_parser():
    parser = Parser(
        prog="cards.py",
        description="Make 1080 x 1920 cards (title, fact, list, quote, sources) from a cards file, to use as scenes in a video.",
        epilog="Example: uv run scripts/cards.py --cards cards.json --out-dir cards",
    )
    parser.add_argument("--cards", required=True, help="the cards file: JSON, {\"cards\": [{\"kind\": \"title\", \"title\": \"...\"}, ...]}")
    parser.add_argument("--out-dir", required=True, help="the folder for the cards, as PNG files (made if it isn't there)")
    parser.add_argument("--style", help="a style file: JSON, or a markdown file with a json block (default plain)")
    return parser


def main(argv=None):
    """Make the cards; whatever goes wrong, the last line printed is the JSON line."""
    try:
        return make(argv)
    except ImportError as error:  # a package turned out to be missing deep inside a call
        message = "a Python package or module is missing (%s): get the kit again and install its packages" % error
        log("cards.py: " + message)
        return finish(False, [], [], message, 3)
    except Exception as error:  # the last resort: a mistake in this command, never a bare traceback
        message = "cards.py failed unexpectedly (%s: %s): this is a mistake in the kit, so tell your owner" % (type(error).__name__, error)
        log("cards.py: " + message)
        return finish(False, [], [], message, 1)


def make(argv=None):
    try:
        args = make_parser().parse_args(argv)
        cards = read_cards(args.cards)
        folder = os.path.abspath(args.out_dir)
        if os.path.exists(folder) and not os.path.isdir(folder):
            raise InputError("--out-dir %s is a file" % args.out_dir)
        for given in (args.cards, args.style):
            if given and hrizzup_media.same_file(given, folder):
                raise InputError("--out-dir is an input")
    except InputError as error:
        log("cards.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    try:
        import hrizzup_draw
    except ImportError as error:
        message = ("a Python package is missing (%s): run this with `uv run scripts/cards.py`, which installs them, or make a virtual "
                   "environment and install the exact set: `python3.12 -m venv .venv`, `.venv/bin/python -m pip install --require-hashes "
                   "-r scripts/cards.requirements.txt`, then `.venv/bin/python scripts/cards.py ...`" % error)
        log("cards.py: " + message)
        return finish(False, [], [], message, 3)
    canvases = []
    try:
        style = hrizzup_draw.load_style(args.style)
        for stem, kind, texts in cards:
            template = hrizzup_draw.load_template(TEMPLATES / ("card-" + kind + ".json"))
            try:
                canvas, _placed = hrizzup_draw.render_template(template, dict(texts), style, SIZE, same_size=SAME_SIZE)
            except hrizzup_draw.DrawError as error:
                raise hrizzup_draw.DrawError("card %s (%s): %s" % (stem, kind, error), error.code)
            canvases.append((stem, canvas))
    except hrizzup_draw.DrawError as error:
        log("cards.py: %s" % error)
        return finish(False, [], [], str(error), error.code)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as error:
        message = "can't make the folder %s: %s" % (args.out_dir, error.strerror)
        log("cards.py: " + message)
        return finish(False, [], [], message, 2)
    written, problems, checks = [], [], []
    try:
        for stem, canvas in canvases:
            written.append(hrizzup_draw.save_image(canvas, os.path.join(folder, stem + ".png")))
    except hrizzup_draw.DrawError as error:
        for path in written:
            _remove(path)
        log("cards.py: %s" % error)
        return finish(False, [], [], str(error), error.code)
    outputs = []
    for path in written:
        try:
            info = hrizzup_media.inspect(path)
        except hrizzup_media.MediaError as error:
            problems.append("%s: %s" % (os.path.basename(path), error))
            continue
        for found in hrizzup_media.problems(info, "image", budget=False):
            problems.append("%s: %s" % (os.path.basename(path), found))
        if (info.width, info.height) != SIZE:
            problems.append("%s is %dx%d, not %dx%d" % (os.path.basename(path), info.width, info.height, SIZE[0], SIZE[1]))
        shown = os.path.join(args.out_dir, os.path.basename(path))
        outputs.append({"path": shown if not os.path.isabs(args.out_dir) else path, "bytes": info.bytes, "width": info.width,
                        "height": info.height, "seconds": None})
    checks = [{"name": "Hrizzup's image limits, 1080 x 1920", "ok": not problems}]
    if problems:
        for path in written:
            _remove(path)
        message = "; ".join(problems)
        log("cards.py: the cards failed their checks: " + message)
        return finish(False, [], checks, message, 1)
    log("cards.py: %d cards in %s" % (len(outputs), args.out_dir))
    return finish(True, outputs, checks, None, 0)


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
