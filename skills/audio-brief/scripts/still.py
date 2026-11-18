# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow==13.0.0", "fonttools==4.68.0"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Make the still image a video or audio post needs: a title, an optional line under it and an optional picture.

    1080x1920   a video's still (Hrizzup's format guide): the picture at the top, the title in capitals, a line under it
    1080x1080   an audio's still

Without --image the picture's place is filled with the style's accent colour. The picture must be one you made or may use
(never someone else's meme image or a real person's likeness made up), at most 25 MiB, 40 megapixels and 8,192 px a side.
The style (--style) gives the colours, the fonts and the signature; the templates have none of their own.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made and checked;
1 the still failed a Hrizzup limit or quality check (a text too long: it says how far to shorten); 2 bad input (a
character the font can't draw, emoji and Hindi included: the fonts draw English letters only for now; a picture too
big); 3 a missing package or kit file. A mistake in this command itself still ends in the JSON line, with exit 1.
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
SIZES = {(1080, 1920): "still-tall", (1080, 1080): "still-square"}  # a video's still, an audio's still
MAX_TITLE = 120
MAX_SUBTITLE = 200


class InputError(Exception):
    """The input is wrong (exit 2)."""


def parse_size(text):
    """(width, height) of "1080x1920"; only a still's two sizes are accepted."""
    found = re.fullmatch(r"(\d+)[xX](\d+)", text.strip())
    if not found or (int(found.group(1)), int(found.group(2))) not in SIZES:
        raise InputError("--size is one of: %s" % ", ".join("%dx%d" % s for s in SIZES))
    return int(found.group(1)), int(found.group(2))


def parse_focus(text):
    """(x, y) as fractions of the picture's width and height, like "0.5,0.35": where the crop is centred."""
    parts = text.split(",")
    try:
        x, y = (float(p) for p in parts) if len(parts) == 2 else (None, None)
    except ValueError:
        x = y = None
    if x is None or not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise InputError("--focus is two fractions from 0 to 1, like 0.5,0.35 (the picture's left to right, top to bottom)")
    return x, y


def clean_text(value, what, limit):
    """A text as one line: whitespace collapsed, no control characters, 1 to `limit` characters."""
    if any(ord(c) < 32 and c not in "\n\t" or 127 <= ord(c) < 160 for c in value):
        raise InputError("%s has a control character" % what)
    cleaned = " ".join(value.split())
    if not cleaned:
        raise InputError("%s is empty" % what)
    if len(cleaned) > limit:
        raise InputError("%s is %d characters; at most %d" % (what, len(cleaned), limit))
    return cleaned


def check_paths(args):
    """The output folder and extension; --out is never an input. Returns the absolute output path."""
    out = os.path.abspath(args.out)
    for given in (args.image, args.style):
        if given and hrizzup_media.same_file(given, out):
            raise InputError("--out would overwrite %s, an input" % given)
    if os.path.splitext(out)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise InputError("--out is a .png, .jpg or .webp file")
    folder = os.path.dirname(out)
    if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
        raise InputError("the folder for --out, %s, doesn't exist or can't be written to" % folder)
    return out


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
        prog="still.py",
        description="Make a still image (1080 x 1920 for a video, 1080 x 1080 for audio) from a title, an optional line and an optional picture.",
        epilog="Example: uv run scripts/still.py --title \"Delhi's air, explained\" --subtitle \"A minute on the story\" --size 1080x1920 --out still.png",
    )
    parser.add_argument("--title", required=True, help="the title, in capitals (at most %d characters)" % MAX_TITLE)
    parser.add_argument("--subtitle", help="a line under the title (at most %d characters)" % MAX_SUBTITLE)
    parser.add_argument("--image", help="the picture: a PNG, JPEG or WebP you made or may use")
    parser.add_argument("--size", default="1080x1920", help="1080x1920 (default, a video's still) or 1080x1080 (an audio's still)")
    parser.add_argument("--focus", default="0.5,0.5", help="where the picture is cropped around, as fractions: x,y (default 0.5,0.5)")
    parser.add_argument("--style", help="a style file: JSON, or a markdown file with a json block (default plain)")
    parser.add_argument("--out", required=True, help="the still to write: a .png, .jpg or .webp (never an input)")
    return parser


def main(argv=None):
    """Make the still; whatever goes wrong, the last line printed is the JSON line."""
    try:
        return make(argv)
    except ImportError as error:  # a package turned out to be missing deep inside a call
        message = "a Python package or module is missing (%s): get the kit again and install its packages" % error
        log("still.py: " + message)
        return finish(False, [], [], message, 3)
    except Exception as error:  # the last resort: a mistake in this command, never a bare traceback
        message = "still.py failed unexpectedly (%s: %s): this is a mistake in the kit, so tell your owner" % (type(error).__name__, error)
        log("still.py: " + message)
        return finish(False, [], [], message, 1)


def make(argv=None):
    try:
        args = make_parser().parse_args(argv)
        size, focus, out = parse_size(args.size), parse_focus(args.focus), check_paths(args)
        texts = {"title": clean_text(args.title, "--title", MAX_TITLE)}
        if args.subtitle is not None:
            texts["subtitle"] = clean_text(args.subtitle, "--subtitle", MAX_SUBTITLE)
    except InputError as error:
        log("still.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    try:
        import hrizzup_draw
        from PIL import Image
    except ImportError as error:
        message = ("a Python package is missing (%s): run this with `uv run scripts/still.py`, which installs them, or "
                   "make a virtual environment and install the exact set: `python3.12 -m venv .venv`, "
                   "`.venv/bin/python -m pip install --require-hashes -r scripts/still.requirements.txt`, "
                   "then `.venv/bin/python scripts/still.py ...`" % error)
        log("still.py: " + message)
        return finish(False, [], [], message, 3)
    try:
        style = hrizzup_draw.load_style(args.style)
        template = hrizzup_draw.load_template(TEMPLATES / (SIZES[size] + ".json"))
        picture = hrizzup_draw.load_picture(args.image) if args.image else None
        box = template["picture"]
        if picture is None:
            width = int(round((box["box"][2] - box["box"][0]) * size[0]))
            height = int(round((box["box"][3] - box["box"][1]) * size[1]))
            colour = style["accent"]
            picture = Image.new("RGB", (width, height), (int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)))
            log("still.py: no --image, so the picture's place is the style's accent colour")
        canvas, _placed = hrizzup_draw.render_template(template, texts, style, size, picture=picture, focus=focus)
        written = hrizzup_draw.save_image(canvas, out)
    except InputError as error:
        log("still.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    except hrizzup_draw.DrawError as error:
        log("still.py: %s" % error)
        return finish(False, [], [], str(error), error.code)
    checks, problems = [], []
    try:
        info = hrizzup_media.inspect(written)
    except hrizzup_media.MediaError as error:
        info, problems = None, [str(error)]
    if info is not None:
        limits = hrizzup_media.problems(info, "image", budget=False)  # Hrizzup's own limits: the 2 MiB budget is for samples
        problems += limits
        if (info.width, info.height) not in SIZES:
            problems.append("the still is %dx%d; a still is %s" % (info.width, info.height, " or ".join("%dx%d" % s for s in SIZES)))
        checks = [
            {"name": "Hrizzup's image limits", "ok": not limits},
            {"name": "a still's size", "ok": (info.width, info.height) in SIZES},
        ]
    if problems:
        try:
            os.remove(written)
        except OSError:
            pass
        message = "; ".join(problems)
        log("still.py: the still failed its checks: " + message)
        return finish(False, [], checks, message, 1)
    log("still.py: %dx%d, %d bytes" % (info.width, info.height, info.bytes))
    outputs = [{"path": os.path.relpath(written) if not os.path.isabs(args.out) else written,
                "bytes": info.bytes, "width": info.width, "height": info.height, "seconds": None}]
    return finish(True, outputs, checks, None, 0)


if __name__ == "__main__":
    sys.exit(main())
