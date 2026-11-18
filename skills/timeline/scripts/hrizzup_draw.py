"""Hrizzup's drawing module: fonts, text that fits, contrast, picture crops, saving. Pillow and fontTools.

This is a module, not a command: scripts import it as a sibling, inside a function, so that
`--help` and the repository's check need nothing installed. It draws every image a skill makes,
text included, and refuses what Hrizzup's posts can't hold.

    import hrizzup_draw
    style = hrizzup_draw.load_style("style.json")            # or None for the default
    canvas = hrizzup_draw.render_template(template, {"title": "Hello"}, style, (1080, 1350))
    path = hrizzup_draw.save_image(canvas, "card.png")

Every refusal is a DrawError, whose `code` is the command's exit code: 1 when the picture would fail a
Hrizzup limit or a quality rule (text that won't fit: it says how far to shorten), 2 for bad input
(a glyph a font lacks, emoji included; a style whose colours are too close; a template the size
doesn't fit), 3 for a missing kit file (a font).
"""

from __future__ import annotations

import io
import json
import os
import re
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont, ImageOps

import hrizzup_media

# ---- fonts: by role ----
FONT_FOLDER = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FAMILIES: Dict[str, Dict[str, str]] = {
    "anton": {"regular": "Anton-Regular.ttf"},
    "atkinson-hyperlegible": {
        "regular": "AtkinsonHyperlegible-Regular.ttf",
        "bold": "AtkinsonHyperlegible-Bold.ttf",
    },
}
ROLES = ("display", "text", "text-bold")
VALIGNS = ("top", "middle", "bottom")  # where a text's lines sit in its box (a template's optional "valign")
LINE_HEIGHT = 1.25  # a line's height as a multiple of the font size
OUTLINE = 0.08  # the outline of text over a picture, as a fraction of its size
MIN_CONTRAST = 4.5  # WCAG's, for normal text
QUALITY = 90  # JPEG and WebP

DEFAULT_STYLE: Dict[str, str] = {
    "ink": "#111111",
    "paper": "#FFFFFF",
    "accent": "#111111",
    "display_font": "anton",
    "text_font": "atkinson-hyperlegible",
    "signature": "",
}
COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}$")
SIGNATURE_MAX = 60


class DrawError(Exception):
    """Something this module refuses. `code` is the exit code the command should use."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------------------------

def _first_json_block(text: str) -> Optional[str]:
    inside, block = False, []
    for line in text.split("\n"):
        if not inside and line.strip() == "```json":
            inside = True
        elif inside and line.strip().startswith("```"):
            return "\n".join(block)
        elif inside:
            block.append(line)
    return None


def load_style(source: "Optional[str | os.PathLike[str]]" = None) -> Dict[str, str]:
    """The agent's style: JSON, or the first fenced `json` block of a markdown file (an agent's `style`
    file). Unknown keys are ignored; missing ones take the default. None gives the default."""
    style = dict(DEFAULT_STYLE)
    if source is None:
        return style
    try:
        text = Path(source).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DrawError("can't read the style file %s: %s" % (source, error))
    if str(source).lower().endswith(".md"):
        block = _first_json_block(text)
        if block is None:
            raise DrawError("%s holds no fenced json block with a style" % source)
        text = block
    try:
        given = json.loads(text)
    except ValueError as error:
        raise DrawError("the style in %s isn't valid JSON: %s" % (source, error))
    if not isinstance(given, dict):
        raise DrawError("a style is a JSON object")
    for key in DEFAULT_STYLE:
        if key in given:
            style[key] = given[key]
    for key in ("ink", "paper", "accent"):
        if not (isinstance(style[key], str) and COLOUR.match(style[key])):
            raise DrawError("the style's %s must be a colour like #111111" % key)
    for key in ("display_font", "text_font"):
        if style[key] not in FAMILIES:
            raise DrawError("the style's %s must be one of: %s" % (key, ", ".join(sorted(FAMILIES))))
    signature = style["signature"]
    if not isinstance(signature, str) or len(signature) > SIGNATURE_MAX or any(
            c in signature for c in "\n\r\t") or signature != signature.strip():
        raise DrawError("the style's signature is one short line (at most %d characters)" % SIGNATURE_MAX)
    return style


def _rgb(colour: str) -> Tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def luminance(colour: str) -> float:
    """WCAG's relative luminance of a #RRGGBB colour."""
    def channel(value: int) -> float:
        x = value / 255
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in _rgb(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: str, second: str) -> float:
    """WCAG's contrast ratio of two #RRGGBB colours, 1 to 21."""
    a, b = luminance(first), luminance(second)
    high, low = (a, b) if a >= b else (b, a)
    return (high + 0.05) / (low + 0.05)


def check_contrast(foreground: str, background: str, what: str) -> None:
    ratio = contrast_ratio(foreground, background)
    if ratio < MIN_CONTRAST:
        raise DrawError("%s: %s on %s is %.1f to 1, and the least that reads well is %.1f to 1 (WCAG); "
                        "change the style's colours" % (what, foreground, background, ratio, MIN_CONTRAST))


# ---------------------------------------------------------------------------------------------
# Fonts and glyphs
# ---------------------------------------------------------------------------------------------

def font_path(role: str, style: Dict[str, str]) -> Path:
    """The font file for a role: `display` is the style's display font; `text` and `text-bold` its text font."""
    if role not in ROLES:
        raise DrawError("a font role is one of: %s" % ", ".join(ROLES))
    family = style["display_font"] if role == "display" else style["text_font"]
    files = FAMILIES[family]
    weight = "bold" if role == "text-bold" and "bold" in files else "regular"
    path = FONT_FOLDER / family / files[weight]
    if not path.is_file():
        raise DrawError("the font %s/%s isn't in this kit's assets/fonts: get the kit again" % (family, files[weight]), 3)
    return path


@lru_cache(maxsize=64)
def _characters(path: str) -> frozenset:
    font = TTFont(path, lazy=True)
    try:
        return frozenset(font.getBestCmap())
    finally:
        font.close()


@lru_cache(maxsize=256)
def _font(path: str, size: int):
    # BASIC layout: the same result with or without Raqm on the machine.
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)


def get_font(role: str, size: int, style: Dict[str, str]):
    return _font(str(font_path(role, style)), int(size))


def missing_glyphs(text: str, role: str, style: Dict[str, str]) -> List[str]:
    have = _characters(str(font_path(role, style)))
    return sorted({c for c in text if c != "\n" and ord(c) not in have})


HINTS = {
    chr(0x20B9): "write Rs or INR",
    chr(0x2190): "write the word instead",
    chr(0x2192): "write the word instead (\"to\")",
}


def check_glyphs(text: str, role: str, style: Dict[str, str], where: str = "the text") -> None:
    """Refuse a character the font lacks (emoji included): it would draw as an empty box."""
    missing = missing_glyphs(text, role, style)
    if missing:
        shown = ", ".join("U+%04X%s" % (ord(c), " (%s)" % HINTS[c] if c in HINTS else "") for c in missing[:6])
        raise DrawError("%s has a character the %s font can't draw: %s. The fonts draw English (Latin) letters, digits and "
                        "common punctuation only: Hindi and other scripts are refused for now, and so are emoji. Use plain "
                        "English letters (write Rs or INR for rupees, and \"to\" for an arrow)" % (where, role, shown))


# ---------------------------------------------------------------------------------------------
# Fitting text to a box
# ---------------------------------------------------------------------------------------------

def _width(text: str, font) -> float:
    return font.getlength(text)


def wrap(text: str, font, width: float) -> List[str]:
    """Break text into lines no wider than `width` pixels, at spaces (and inside a word only when a
    single word is wider than the box). A new line in the text ends a line."""
    lines: List[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            trial = word if not current else current + " " + word
            if _width(trial, font) <= width:
                current = trial
                continue
            if current:
                lines.append(current)
                current = ""
            while _width(word, font) > width and len(word) > 1:
                cut = len(word) - 1
                while cut > 1 and _width(word[:cut], font) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


def line_height(size: int) -> int:
    return int(round(size * LINE_HEIGHT))


class Fitted:
    """Text that fits: its font, size, lines and the height it takes."""

    def __init__(self, size: int, font, lines: List[str]):
        self.size, self.font, self.lines = size, font, lines
        self.height = len(lines) * line_height(size)


def _fits(text: str, role: str, style: Dict[str, str], box: Tuple[float, float], size: int,
          max_lines: int, stroke: int) -> Optional[Fitted]:
    font = get_font(role, size, style)
    lines = wrap(text, font, box[0] - 2 * stroke)
    if len(lines) > max_lines or len(lines) * line_height(size) > box[1] - 2 * stroke:
        return None
    if any(_width(line, font) > box[0] - 2 * stroke for line in lines):
        return None
    return Fitted(size, font, lines)


def fit_text(text: str, role: str, style: Dict[str, str], box: Tuple[float, float], largest: int,
             smallest: int, max_lines: int, outline: bool = False, where: str = "the text") -> Fitted:
    """The largest size from `largest` down to `smallest` that fits the box (width, height in pixels) in
    at most `max_lines` lines. Otherwise DrawError code 1: shorten to about N characters."""
    check_glyphs(text, role, style, where)
    for size in range(largest, smallest - 1, -1):
        stroke = max(1, round(size * OUTLINE)) if outline else 0
        found = _fits(text, role, style, box, size, max_lines, stroke)
        if found is not None:
            return found
    font = get_font(role, smallest, style)
    characters = max(1, len(text.replace("\n", " ")))
    per_character = max(1.0, _width(text.replace("\n", " "), font) / characters)
    stroke = max(1, round(smallest * OUTLINE)) if outline else 0
    rows = max(1, min(max_lines, int((box[1] - 2 * stroke) // line_height(smallest))))
    capacity = int(rows * ((box[0] - 2 * stroke) / per_character) * 0.9)
    about = max(5, capacity - capacity % 5)
    raise DrawError("%s is too long for its place: shorten to about %d characters (it is %d)" % (where, about, len(text)), 1)


def draw_lines(canvas: Image.Image, fitted: Fitted, box: Tuple[float, float, float, float], align: str,
               fill: str, outline: Optional[str] = None, valign: str = "top") -> None:
    """Draw fitted lines inside a pixel box, at its top, middle or bottom (`valign`); `outline` (a colour) adds
    the picture outline."""
    draw = ImageDraw.Draw(canvas)
    stroke = max(1, round(fitted.size * OUTLINE)) if outline else 0
    x0, y0, x1, y1 = box
    if valign == "middle":
        top = y0 + (y1 - y0 - fitted.height) / 2
    elif valign == "bottom":
        top = y1 - stroke - fitted.height
    else:
        top = y0 + stroke
    for number, line in enumerate(fitted.lines):
        if not line:
            continue
        length = _width(line, fitted.font)
        if align == "center":
            x = x0 + (x1 - x0 - length) / 2
        elif align == "right":
            x = x1 - stroke - length
        else:
            x = x0 + stroke
        draw.text((x, top + number * line_height(fitted.size)), line, font=fitted.font, fill=_rgb(fill),
                  stroke_width=stroke, stroke_fill=_rgb(outline) if outline else None)


# ---------------------------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------------------------

IMAGE_FORMATS = ("PNG", "JPEG", "MPO", "WEBP")  # what Pillow calls the formats a picture may have (MPO: a phone's JPEG)


def load_picture(path: "str | os.PathLike[str]") -> Image.Image:
    """Open a creator's picture and load it: a PNG, JPEG or WebP of at most 25 MiB, 40 megapixels and 8,192 px a side
    (`hrizzup_media`). The size is read from the header and refused before any pixel is decoded, so a huge picture
    can't fill the machine's memory. A refusal is a DrawError with code 2."""
    Image.MAX_IMAGE_PIXELS = hrizzup_media.PICTURE_INPUT_MAX_PIXELS  # Pillow's own guard, at the same size
    name = os.fspath(path)
    try:
        size = os.path.getsize(name)
    except OSError as error:
        raise DrawError("can't read the picture %s: %s" % (name, error.strerror or type(error).__name__))
    if size > hrizzup_media.PICTURE_INPUT_MAX_BYTES:
        raise DrawError("the picture %s is %d MiB; at most %d MiB" % (
            name, size // hrizzup_media.MIB, hrizzup_media.PICTURE_INPUT_MAX_BYTES // hrizzup_media.MIB))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)  # the size is checked, and refused, just below
            picture = Image.open(name)
    except (OSError, Image.UnidentifiedImageError, Image.DecompressionBombError, ValueError) as error:
        raise DrawError("can't read %s as a picture: %s" % (name, error))
    too_big = hrizzup_media.input_picture_problems(picture.width, picture.height)
    if too_big:
        picture.close()
        raise DrawError("the picture %s is too big to use: %s. Make it smaller first (a post's picture is at most "
                        "1080 px wide)" % (name, "; ".join(too_big)))
    if picture.format not in IMAGE_FORMATS:
        picture.close()
        raise DrawError("the picture %s is a %s; use a PNG, JPEG or WebP" % (name, picture.format))
    try:
        picture.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as error:
        picture.close()
        raise DrawError("can't read %s as a picture: %s" % (name, error))
    return picture


def flatten(picture: Image.Image, paper: str = "#FFFFFF") -> Image.Image:
    """The picture as 8-bit RGB, turned the way its EXIF says: transparency (an alpha channel, or a palette's
    transparent colour) is laid over the `paper` colour, 16-bit grey is scaled to 8 bits, and a floating-point or
    wider picture is refused (DrawError, code 2) rather than drawn wrongly."""
    upright = ImageOps.exif_transpose(picture)
    mode = upright.mode
    if mode == "F":
        raise DrawError("the picture holds floating-point values: save it as an ordinary 8-bit PNG, JPEG or WebP")
    if mode == "I" or mode.startswith("I;16"):
        wide = upright.convert("I")
        high = wide.getextrema()[1]
        if high > 65535:
            raise DrawError("the picture holds %d-bit values: save it as an ordinary 8-bit PNG, JPEG or WebP" % int(high).bit_length())
        upright = (wide if high <= 255 else wide.point(lambda value: value * (1 / 256) + 0.5)).convert("L")  # 16-bit to 8-bit, rounded
        mode = "L"
    try:
        if mode in ("RGBA", "LA", "PA", "RGBa", "La") or "transparency" in upright.info:
            over = upright.convert("RGBA")
            ground = Image.new("RGBA", over.size, _rgb(paper) + (255,))
            return Image.alpha_composite(ground, over).convert("RGB")
        return upright.convert("RGB")
    except (ValueError, OSError) as error:
        raise DrawError("can't use this picture (%s): save it as an ordinary 8-bit PNG, JPEG or WebP" % error)


def cover_crop(picture: Image.Image, size: Tuple[int, int], focus: Tuple[float, float] = (0.5, 0.5),
               paper: str = "#FFFFFF") -> Image.Image:
    """Fill `size` with the picture, cropped around a focus point (fractions of its width and height), after
    turning it the way its EXIF says and flattening it (`flatten`: transparency goes over `paper`)."""
    fx = min(1.0, max(0.0, float(focus[0])))
    fy = min(1.0, max(0.0, float(focus[1])))
    return ImageOps.fit(flatten(picture, paper), size, method=Image.Resampling.LANCZOS, centering=(fx, fy))


def save_image(canvas: Image.Image, path: "str | os.PathLike[str]") -> str:
    """Save as PNG, JPEG or WebP by the name's extension, without metadata (JPEG and WebP at quality
    90). A PNG over 10 MiB is saved as a JPEG instead, with `.jpg` for its extension. Returns the path
    written."""
    target = os.fspath(path)
    extension = os.path.splitext(target)[1].lower()
    if extension not in (".png", ".jpg", ".jpeg", ".webp"):
        raise DrawError("an image is saved as .png, .jpg or .webp, not %r" % extension)
    clean = Image.new("RGB", canvas.size)  # a new image carries none of the picture's metadata
    clean.paste(canvas.convert("RGB"))
    buffer = io.BytesIO()
    if extension == ".png":
        clean.save(buffer, "PNG", optimize=True)
        if buffer.tell() > hrizzup_media.IMAGE_MAX_BYTES:
            buffer = io.BytesIO()
            clean.save(buffer, "JPEG", quality=QUALITY, optimize=True)
            target = os.path.splitext(target)[0] + ".jpg"
    elif extension == ".webp":
        clean.save(buffer, "WEBP", quality=QUALITY, method=6)
    else:
        clean.save(buffer, "JPEG", quality=QUALITY, optimize=True)
    try:
        with open(target, "wb") as f:
            f.write(buffer.getvalue())
    except OSError as error:
        raise DrawError("can't write %s: %s" % (target, error.strerror or type(error).__name__))
    return target


# ---------------------------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------------------------

def load_template(path: "str | os.PathLike[str]") -> Dict[str, Any]:
    try:
        template = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DrawError("can't read the template %s: %s" % (path, error), 3)
    if not isinstance(template, dict):
        raise DrawError("a template is a JSON object", 3)
    return template


def _pixels(box: Sequence[float], size: Tuple[int, int]) -> Tuple[float, float, float, float]:
    return box[0] * size[0], box[1] * size[1], box[2] * size[0], box[3] * size[1]


def render_template(template: Dict[str, Any], texts: Dict[str, str], style: Dict[str, str],
                    size: Tuple[int, int], picture: Optional[Image.Image] = None,
                    focus: Tuple[float, float] = (0.5, 0.5),
                    same_size: Sequence[Sequence[str]] = ()) -> Tuple[Image.Image, List[Dict[str, Any]]]:
    """Draw a template (docs/design.md, 8.1) with the texts for its slots; returns the canvas and, for
    each slot drawn, {"slot", "size", "lines"}. A slot with no text is left empty. Slots listed together
    in `same_size` are drawn at the smallest size any of them needs, so a column reads evenly."""
    if list(size) not in [list(s) for s in template["sizes"]]:
        raise DrawError("the template %s is made for %s, not %dx%d" % (
            template["id"], " or ".join("%dx%d" % tuple(s) for s in template["sizes"]), size[0], size[1]))
    background = style["paper"] if template["background"] == "paper" else style["accent"]
    foreground = {"paper": style["ink"], "accent": style["paper"]}
    check_contrast(style["ink"], style["paper"], "the style's ink on its paper")
    uses = {t["on"] for t in template["texts"] if t["slot"] in texts and texts[t["slot"]]}
    if "accent" in uses or template["background"] == "accent":
        check_contrast(style["paper"], style["accent"], "the style's paper on its accent")
    canvas = Image.new("RGB", size, _rgb(background))
    if template["picture"] is not None:
        if picture is None:
            if template["picture"]["required"]:
                raise DrawError("the template %s needs a picture" % template["id"])
        else:
            left, top, right, bottom = (int(round(v)) for v in _pixels(template["picture"]["box"], size))
            canvas.paste(cover_crop(picture, (right - left, bottom - top), focus, style["paper"]), (left, top))
    slots = {t["slot"]: t for t in template["texts"]}
    for slot in texts:
        if slot not in slots:
            raise DrawError("the template %s has no slot %r (it has: %s)" % (template["id"], slot, ", ".join(slots)))
    for spec in slots.values():
        if spec.get("valign", "top") not in VALIGNS:
            raise DrawError("the template %s: valign is one of %s" % (template["id"], ", ".join(VALIGNS)), 3)
    fitted: Dict[str, Fitted] = {}
    for slot, text in texts.items():
        spec = slots[slot]
        if not text:
            continue
        text = text.upper() if spec["case"] == "upper" else text
        texts[slot] = text
        box = _pixels(spec["box"], size)
        fitted[slot] = fit_text(text, spec["font"], style, (box[2] - box[0], box[3] - box[1]), spec["max"], spec["min"],
                                spec["lines"], outline=spec["on"] == "picture", where="the \"%s\" text" % slot)
    for group in same_size:
        present = [s for s in group if s in fitted]
        if len(present) < 2:
            continue
        common = min(fitted[s].size for s in present)
        for slot in present:
            spec = slots[slot]
            box = _pixels(spec["box"], size)
            again = _fits(texts[slot], spec["font"], style, (box[2] - box[0], box[3] - box[1]), common, spec["lines"],
                          max(1, round(common * OUTLINE)) if spec["on"] == "picture" else 0)
            if again is not None:
                fitted[slot] = again
    placed = []
    for slot, found in fitted.items():
        spec = slots[slot]
        outline = "#000000" if spec["on"] == "picture" else None
        fill = "#FFFFFF" if spec["on"] == "picture" else foreground[spec["on"]]
        draw_lines(canvas, found, _pixels(spec["box"], size), spec["align"], fill, outline, spec.get("valign", "top"))
        placed.append({"slot": slot, "size": found.size, "lines": len(found.lines)})
    signature = template["signature"]
    if signature is not None and style["signature"]:
        box = _pixels(signature["box"], size)
        role = "text-bold"
        found = fit_text(style["signature"], role, style, (box[2] - box[0], box[3] - box[1]), 30, 12, 1, where="the signature")
        draw_lines(canvas, found, box, signature["align"], foreground["paper" if template["background"] == "paper" else "accent"])
        placed.append({"slot": "signature", "size": found.size, "lines": 1})
    return canvas, placed
