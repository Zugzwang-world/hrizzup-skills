# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow==13.0.0", "fonttools==4.68.0"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Make a meme: a picture and one or two short texts, laid out by one of four templates (1080 x 1080 or 1080 x 1350).

    caption-bar   a bar of text on top, the picture below it          (--text; needs --image)
    top-bottom    the picture with a line at the top and one at the bottom, white with a black outline
                  (--text, and --text2 for the bottom)
    two-panel     a setup in a text panel, then the picture with the punchline on it   (--text, --text2)
    label         the picture with a label on its left half and one on its right half  (--text, --text2;
                  needs --image)

Without --image, top-bottom and two-panel fill the picture's place with the style's accent colour; caption-bar and
label need a picture and exit 2 without one. The picture must be one you made or may use: never someone else's meme
image, and at most 25 MiB, 40 megapixels and 8,192 px a side.
The style (--style) gives the colours, the fonts and the signature; the templates have none of their own.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made and
checked; 1 the meme failed a Hrizzup limit or quality check (a text too long: it says how far to shorten);
2 bad input (a character the font can't draw, emoji and Hindi included: the fonts draw English letters only for
now; a template that needs a picture; a picture too big); 3 a missing package or kit file. A mistake in this command
itself still ends in the JSON line, with exit 1.
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
TEMPLATE_IDS = ("caption-bar", "top-bottom", "two-panel", "label")
SIZES = ((1080, 1080), (1080, 1350))  # a meme's sizes (Hrizzup's format guide)
NEEDS_TEXT2 = ("two-panel", "label")  # the templates that need both texts
MAX_TEXT = 200  # characters in one text


class InputError(Exception):
    """The input is wrong (exit 2)."""


# ---------------------------------------------------------------------------------------------
# Reading the command line (standard library only)
# ---------------------------------------------------------------------------------------------

def parse_size(text):
    """(width, height) of "1080x1350"; only a meme's two sizes are accepted."""
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


def clean_text(value, what):
    """A text as one line: whitespace collapsed, no control characters, 1 to MAX_TEXT characters."""
    if any(ord(c) < 32 and c not in "\n\t" or 127 <= ord(c) < 160 for c in value):
        raise InputError("%s has a control character" % what)
    cleaned = " ".join(value.split())
    if not cleaned:
        raise InputError("%s is empty" % what)
    if len(cleaned) > MAX_TEXT:
        raise InputError("%s is %d characters; at most %d (a meme is a line or two)" % (what, len(cleaned), MAX_TEXT))
    return cleaned


def texts_for(template_id, text, text2, slots):
    """{slot: text} for the template. `slots` are the template's slot names."""
    texts = {"text": clean_text(text, "--text")}
    if text2 is not None:
        if "text2" not in slots:
            raise InputError("the template %s has one text; drop --text2 (or use top-bottom, two-panel or label)" % template_id)
        texts["text2"] = clean_text(text2, "--text2")
    elif template_id in NEEDS_TEXT2:
        raise InputError("the template %s needs --text2 as well as --text" % template_id)
    return texts


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


def accent_rgb(style):
    colour = style["accent"]
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


# ---------------------------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------------------------

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
        prog="meme.py",
        description="Make a meme (1080 x 1080 or 1080 x 1350) from a picture and one or two short texts.",
        epilog="Example: uv run scripts/meme.py --template top-bottom --image picture.png --text \"Monday's headline\" "
               "--text2 \"Tuesday's correction\" --out meme.png",
    )
    parser.add_argument("--template", required=True, choices=TEMPLATE_IDS, help="the layout")
    parser.add_argument("--image", help="the picture: a PNG, JPEG or WebP you made or may use (never someone else's meme)")
    parser.add_argument("--text", required=True, help="the first text: the top, the bar, the setup, or the left label")
    parser.add_argument("--text2", help="the second text: the bottom, the punchline, or the right label")
    parser.add_argument("--size", default="1080x1080", help="1080x1080 (default) or 1080x1350")
    parser.add_argument("--focus", default="0.5,0.5", help="where the picture is cropped around, as fractions: x,y (default 0.5,0.5)")
    parser.add_argument("--style", help="a style file: JSON, or a markdown file with a json block (default plain)")
    parser.add_argument("--out", required=True, help="the meme to write: a .png, .jpg or .webp (never an input)")
    return parser


def main(argv=None):
    """Make the meme; whatever goes wrong, the last line printed is the JSON line."""
    try:
        return make(argv)
    except ImportError as error:  # a package turned out to be missing deep inside a call
        message = "a Python package or module is missing (%s): get the kit again and install its packages" % error
        log("meme.py: " + message)
        return finish(False, [], [], message, 3)
    except Exception as error:  # the last resort: a mistake in this command, never a bare traceback
        message = "meme.py failed unexpectedly (%s: %s): this is a mistake in the kit, so tell your owner" % (type(error).__name__, error)
        log("meme.py: " + message)
        return finish(False, [], [], message, 1)


def make(argv=None):
    try:
        args = make_parser().parse_args(argv)
        size, focus, out = parse_size(args.size), parse_focus(args.focus), check_paths(args)
    except InputError as error:
        log("meme.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    try:
        import hrizzup_draw
        from PIL import Image
    except ImportError as error:
        message = ("a Python package is missing (%s): run this with `uv run scripts/meme.py`, which installs them, or "
                   "make a virtual environment and install the exact set: `python3.12 -m venv .venv`, "
                   "`.venv/bin/python -m pip install --require-hashes -r scripts/meme.requirements.txt`, "
                   "then `.venv/bin/python scripts/meme.py ...`" % error)
        log("meme.py: " + message)
        return finish(False, [], [], message, 3)
    try:
        style = hrizzup_draw.load_style(args.style)
        template = hrizzup_draw.load_template(TEMPLATES / (args.template + ".json"))
        texts = texts_for(args.template, args.text, args.text2, [t["slot"] for t in template["texts"]])
        picture = hrizzup_draw.load_picture(args.image) if args.image else None
        box = template["picture"]
        if picture is None and box is not None:
            if box["required"]:
                raise InputError("the template %s needs a picture: give --image (one you made or may use)" % args.template)
            width = int(round((box["box"][2] - box["box"][0]) * size[0]))
            height = int(round((box["box"][3] - box["box"][1]) * size[1]))
            picture = Image.new("RGB", (width, height), accent_rgb(style))  # the style's accent where the picture would be
            log("meme.py: no --image, so the picture's place is the style's accent colour")
        elif picture is not None and box is not None:
            wanted = (box["box"][2] - box["box"][0]) * size[0], (box["box"][3] - box["box"][1]) * size[1]
            if picture.width < wanted[0] * 0.6 or picture.height < wanted[1] * 0.6:
                log("meme.py: the picture is %dx%d and is enlarged to fill %dx%d, so it will look soft"
                    % (picture.width, picture.height, wanted[0], wanted[1]))
        canvas, placed = hrizzup_draw.render_template(template, texts, style, size, picture=picture, focus=focus)
        written = hrizzup_draw.save_image(canvas, out)
    except InputError as error:
        log("meme.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    except hrizzup_draw.DrawError as error:
        log("meme.py: %s" % error)
        return finish(False, [], [], str(error), error.code)
    checks, problems = [], []
    try:
        info = hrizzup_media.inspect(written)
    except hrizzup_media.MediaError as error:
        info, problems = None, [str(error)]
    if info is not None:
        # Hrizzup's own limits (10 MiB, 4,096 px a side); the repository's 2 MiB is for its samples, not a creator's meme.
        limits = hrizzup_media.problems(info, "image", budget=False)
        problems += limits
        if (info.width, info.height) not in SIZES:
            problems.append("the meme is %dx%d; a meme is %s" % (info.width, info.height, " or ".join("%dx%d" % s for s in SIZES)))
        checks = [
            {"name": "Hrizzup's image limits", "ok": not limits},
            {"name": "a meme's size", "ok": (info.width, info.height) in SIZES},
        ]
    if problems:
        try:
            os.remove(written)
        except OSError:
            pass
        message = "; ".join(problems)
        log("meme.py: the meme failed its checks: " + message)
        return finish(False, [], checks, message, 1)
    log("meme.py: %s, %d text%s; %d bytes, %dx%d" % (args.template, len(texts), "" if len(texts) == 1 else "s", info.bytes,
                                                      info.width, info.height))
    outputs = [{"path": os.path.relpath(written) if not os.path.isabs(args.out) else written,
                "bytes": info.bytes, "width": info.width, "height": info.height, "seconds": None}]
    return finish(True, outputs, checks, None, 0)


if __name__ == "__main__":
    sys.exit(main())
