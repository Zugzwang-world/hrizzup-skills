# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow==13.0.0", "fonttools==4.68.0", "matplotlib==3.11.2", "numpy==2.5.4"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Make an infographic: a chart, one big number, or a few steps, on a card (1080 x 1350 or 1080 x 1080).

The input is a JSON spec:

    {"template": "chart-card" | "stat-card" | "steps-card",
     "title": "...", "subtitle": "...",                  # subtitle is optional
     "chart": {"type": "bar" | "column" | "line" | "scale" | "stat", ...},     # or "image": "chart.png"
     "steps": ["...", ...],                              # steps-card: 2 to 5 steps
     "source": "Source: ..."}                            # always: the source goes on the image

    chart-card    a bar, column, line or scale chart (drawn here), or your own chart as a picture ("image")
    stat-card     one big number: "chart": {"type": "stat", "value": "450", "label": "...", "note": "..."}
    steps-card    two to five numbered steps

    bar / column  {"type": "bar", "data": [{"label": "Delhi", "value": 410}, ...], "unit": "AQI", "highlight": "Delhi"}
                  starts at zero, every bar labelled with its value; an item may carry "text" for its value label
    line          {"type": "line", "data": [{"label": "Mon", "value": 3}, ...], "unit": "...", "from_zero": true}
    scale         {"type": "scale", "bands": [{"name": "Good", "from": 0, "to": 50}, ...],
                   "marker": {"value": 450, "label": "..."}, "unit": "AQI"}

matplotlib draws the chart on its Agg canvas with the kit's fonts, and Pillow places it on the card. The style
(--style) gives the colours, the fonts and the signature; the templates have none of their own.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made and
checked; 1 the card failed a Hrizzup limit or quality check (a text too long for its place: it says how far to
shorten); 2 bad input (a bad spec; a character the font can't draw, emoji and Hindi included: the fonts draw English
letters only for now; a picture too big); 3 a missing package or kit file. A mistake in this command itself still ends in
the JSON line, with exit 1.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import sys
from decimal import Decimal
from pathlib import Path

import hrizzup_media

KIT = Path(__file__).resolve().parent.parent
TEMPLATES = KIT / "assets" / "templates"
TEMPLATE_IDS = ("chart-card", "stat-card", "steps-card")
SIZES = ((1080, 1350), (1080, 1080))  # an infographic's sizes (Hrizzup's format guide)
CHART_TYPES = ("bar", "column", "line", "scale")
SPEC_KEYS = ("template", "title", "subtitle", "chart", "image", "steps", "source")
MAX_TITLE, MAX_SUBTITLE, MAX_SOURCE = 140, 200, 300
MAX_LABEL, MAX_VALUE_TEXT, MAX_UNIT, MAX_NAME = 60, 24, 12, 24
MAX_STEP, STEPS_MIN, STEPS_MAX = 200, 2, 5
MAX_BARS, MAX_COLUMNS, MAX_POINTS, BANDS_MIN, BANDS_MAX = 12, 8, 24, 2, 8
STYLE_FILE = KIT / "assets" / "hrizzup.mplstyle"
DPI = 100  # the chart's canvas: one pixel is 0.72 of a point
STEP_ROWS = 5  # the steps template's rows
# Tints of ink over paper, as the share of ink: a scale's bands go from light to dark; bars are TINT_OTHERS beside a highlight.
# Every tint that is drawn passes a contrast rule against the paper: text (a label, a note) WCAG's 4.5 to 1, and a mark
# (a bar's or a band's fill, a line) WCAG's 3 to 1 for graphics. `shade` raises a share that doesn't pass.
TINT_LOW, TINT_HIGH, TINT_OTHERS = 0.14, 0.92, 0.38
MIN_CONTRAST = 4.5  # text
GRAPHIC_CONTRAST = 3.0  # marks
MARKER_VALUE = 84  # px, the scale marker's big value
MARKER_LABEL = 26  # px, the words under it
LINE = 1.22  # a line of text's height as a multiple of its size


class InputError(Exception):
    """The input is wrong (exit 2)."""


class TooLong(Exception):
    """Text that won't fit its place (exit 1); the message says how far to shorten."""


# ---------------------------------------------------------------------------------------------
# Reading and checking the spec (standard library only)
# ---------------------------------------------------------------------------------------------

def parse_size(text):
    found = re.fullmatch(r"(\d+)[xX](\d+)", text.strip())
    if not found or (int(found.group(1)), int(found.group(2))) not in SIZES:
        raise InputError("--size is one of: %s" % ", ".join("%dx%d" % s for s in SIZES))
    return int(found.group(1)), int(found.group(2))


def one_line(value, what, high, required=True):
    """A text as one line: whitespace collapsed, no control characters, 1 to `high` characters. None if absent."""
    if value is None:
        if required:
            raise InputError("%s is required" % what)
        return None
    if not isinstance(value, str):
        raise InputError("%s must be text" % what)
    if any(ord(c) < 32 and c not in "\n\t" or 127 <= ord(c) < 160 for c in value):
        raise InputError("%s has a control character" % what)
    cleaned = " ".join(value.split())
    if not cleaned:
        if required:
            raise InputError("%s is empty" % what)
        return None
    if len(cleaned) > high:
        raise InputError("%s is %d characters; at most %d" % (what, len(cleaned), high))
    return cleaned


def number(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError("%s must be a number" % what)
    return value


def fmt_number(value):
    """A number as plain digits, exactly as given and no rounder: a whole number without a decimal point, any other in
    its shortest exact form (0.001 is "0.001", 0.125 is "0.125"), never an exponent."""
    if isinstance(value, int) or float(value).is_integer():
        return str(int(value))
    text = format(Decimal(repr(float(value))), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def value_text(item, unit):
    """What a bar, column or point is labelled with: its own text, or its number and the unit."""
    if item.get("text"):
        return item["text"]
    shown = fmt_number(item["value"])
    if not unit:
        return shown
    return shown + unit if unit == "%" else shown + " " + unit


def validate_items(data, what, low, high, kinds):
    if not isinstance(data, list) or not low <= len(data) <= high:
        raise InputError("%s: \"data\" is a list of %d to %d items, each {\"label\": ..., \"value\": ...}" % (what, low, high))
    items, seen = [], set()
    for number_, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise InputError("%s: item %d isn't an object" % (what, number_))
        extra = set(entry) - {"label", "value", "text"}
        if extra:
            raise InputError("%s: item %d has unknown keys %s (use label, value and, optionally, text)" % (what, number_, sorted(extra)))
        label = one_line(entry.get("label"), "%s item %d's label" % (what, number_), MAX_LABEL)
        value = number(entry.get("value"), "%s item %d's value" % (what, number_))
        text = one_line(entry.get("text"), "%s item %d's text" % (what, number_), MAX_VALUE_TEXT, required=False)
        if label in seen:
            raise InputError("%s: two items are labelled %r" % (what, label))
        seen.add(label)
        items.append({"label": label, "value": value, "text": text})
    return items


def validate_chart(chart, template_id):
    if not isinstance(chart, dict):
        raise InputError("\"chart\" must be an object like {\"type\": \"bar\", \"data\": [...]}")
    kind = chart.get("type")
    if template_id == "stat-card":
        if kind != "stat":
            raise InputError("the stat-card's chart is {\"type\": \"stat\", \"value\": ..., \"label\": ...}")
        extra = set(chart) - {"type", "value", "label", "note"}
        if extra:
            raise InputError("a stat has unknown keys %s (use value, label and note)" % sorted(extra))
        return {"type": "stat", "value": one_line(chart.get("value"), "the stat's value", 12),
                "label": one_line(chart.get("label"), "the stat's label", 100),
                "note": one_line(chart.get("note"), "the stat's note", 200, required=False)}
    if kind not in CHART_TYPES:
        raise InputError("the chart's type is one of: %s" % ", ".join(CHART_TYPES))
    unit = one_line(chart.get("unit"), "the chart's unit", MAX_UNIT, required=False)
    if kind in ("bar", "column", "line"):
        extra = set(chart) - {"type", "data", "unit", "highlight", "from_zero"}
        if extra:
            raise InputError("a %s chart has unknown keys %s" % (kind, sorted(extra)))
        high = {"bar": MAX_BARS, "column": MAX_COLUMNS, "line": MAX_POINTS}[kind]
        items = validate_items(chart.get("data"), "the %s chart" % kind, 2 if kind == "line" else 1, high, kind)
        values = [i["value"] for i in items]
        from_zero = chart.get("from_zero", True)
        if not isinstance(from_zero, bool):
            raise InputError("\"from_zero\" is true or false")
        if kind != "line" and "from_zero" in chart:
            raise InputError("bars and columns always start at zero; \"from_zero\" is only for a line")
        if (kind != "line" or from_zero) and min(values) < 0:
            raise InputError("a value is below zero: bars and columns start at zero, and a line does unless it has "
                             "\"from_zero\": false. Use a line with \"from_zero\": false, or put the numbers in the post's text")
        if max(values) == min(values) == 0 or (kind == "line" and not from_zero and max(values) == min(values)):
            raise InputError("every value is the same: there is nothing to show")
        marked = chart.get("highlight")
        if marked is not None:
            marked = [marked] if isinstance(marked, str) else marked
            labels = [i["label"] for i in items]
            if not isinstance(marked, list) or not 1 <= len(marked) <= 3 or any(m not in labels for m in marked):
                raise InputError("\"highlight\" is the label of up to three items in \"data\"")
        return {"type": kind, "data": items, "unit": unit, "highlight": marked, "from_zero": from_zero}
    # scale
    extra = set(chart) - {"type", "bands", "marker", "unit"}
    if extra:
        raise InputError("a scale has unknown keys %s (use bands, marker and unit)" % sorted(extra))
    bands = chart.get("bands")
    if not isinstance(bands, list) or not BANDS_MIN <= len(bands) <= BANDS_MAX:
        raise InputError("a scale's \"bands\" is a list of %d to %d, each {\"name\", \"from\", \"to\"}" % (BANDS_MIN, BANDS_MAX))
    out, previous = [], None
    for number_, band in enumerate(bands, start=1):
        if not isinstance(band, dict) or set(band) != {"name", "from", "to"}:
            raise InputError("band %d is {\"name\", \"from\", \"to\"}" % number_)
        name = one_line(band["name"], "band %d's name" % number_, MAX_NAME)
        low, high = number(band["from"], "band %d's from" % number_), number(band["to"], "band %d's to" % number_)
        if not high > low:
            raise InputError("band %d: \"to\" must be above \"from\"" % number_)
        if previous is not None and low < previous:
            raise InputError("band %d starts below where band %d ends: list the bands from lowest to highest, not overlapping" % (number_, number_ - 1))
        previous = high
        out.append({"name": name, "from": low, "to": high})
    marker = chart.get("marker")
    if marker is not None:
        if not isinstance(marker, dict) or set(marker) - {"value", "label"} or "value" not in marker:
            raise InputError("a scale's \"marker\" is {\"value\": number, \"label\": text}")
        value = number(marker["value"], "the marker's value")
        if not out[0]["from"] <= value <= out[-1]["to"]:
            raise InputError("the marker's value %s is off the scale (%s to %s)" % (fmt_number(value), fmt_number(out[0]["from"]), fmt_number(out[-1]["to"])))
        marker = {"value": value, "label": one_line(marker.get("label"), "the marker's label", 80, required=False)}
    return {"type": "scale", "bands": out, "marker": marker, "unit": unit}


def validate_spec(spec):
    """The spec, checked and tidied. InputError says what to change."""
    if not isinstance(spec, dict):
        raise InputError("the spec is a JSON object")
    extra = set(spec) - set(SPEC_KEYS)
    if extra:
        raise InputError("the spec has unknown keys %s (it has: %s)" % (sorted(extra), ", ".join(SPEC_KEYS)))
    template = spec.get("template")
    if template not in TEMPLATE_IDS:
        raise InputError("\"template\" is one of: %s" % ", ".join(TEMPLATE_IDS))
    checked = {
        "template": template,
        "title": one_line(spec.get("title"), "\"title\"", MAX_TITLE),
        "subtitle": one_line(spec.get("subtitle"), "\"subtitle\"", MAX_SUBTITLE, required=False),
        "source": one_line(spec.get("source"), "\"source\" (an infographic names its source on the image)", MAX_SOURCE),
    }
    if template == "stat-card" and spec.get("subtitle") is not None:
        raise InputError("a stat-card has no subtitle: put it in the note")
    wanted = {"chart-card": ("chart", "image"), "stat-card": ("chart",), "steps-card": ("steps",)}[template]
    for key in ("chart", "image", "steps"):
        if key in spec and key not in wanted:
            raise InputError("the %s takes %s, not %r" % (template, " or ".join(repr(w) for w in wanted), key))
    if template == "chart-card":
        if ("chart" in spec) == ("image" in spec):
            raise InputError("the chart-card takes either \"chart\" (drawn here) or \"image\" (your own chart, a picture file), not both and not neither")
        if "image" in spec:
            checked["image"] = one_line(spec["image"], "\"image\"", 300)
        else:
            checked["chart"] = validate_chart(spec["chart"], template)
    elif template == "stat-card":
        if "chart" not in spec:
            raise InputError("the stat-card needs \"chart\": {\"type\": \"stat\", \"value\": ..., \"label\": ...}")
        checked["chart"] = validate_chart(spec["chart"], template)
    else:
        steps = spec.get("steps")
        if not isinstance(steps, list) or not STEPS_MIN <= len(steps) <= STEPS_MAX:
            raise InputError("the steps-card needs \"steps\": a list of %d to %d short steps" % (STEPS_MIN, STEPS_MAX))
        checked["steps"] = [one_line(s, "step %d" % n, MAX_STEP) for n, s in enumerate(steps, start=1)]
    return checked


def check_paths(args):
    out = os.path.abspath(args.out)
    for given in (args.spec, args.style):
        if given and hrizzup_media.same_file(given, out):
            raise InputError("--out would overwrite %s, an input" % given)
    if os.path.splitext(out)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise InputError("--out is a .png, .jpg or .webp file")
    folder = os.path.dirname(out)
    if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
        raise InputError("the folder for --out, %s, doesn't exist or can't be written to" % folder)
    return out


# ---------------------------------------------------------------------------------------------
# Layout: where each mark and label goes, in pixels. `measure(text, role, size)` and `wrap(text, role, size,
# width)` come from the drawing module in a real run, and from stand-ins in the tests.
# ---------------------------------------------------------------------------------------------

def mix(base, over, share):
    """A colour `share` of the way from `base` toward `over` (both #RRGGBB)."""
    a = [int(base[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(over[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(int(round(x + (y - x) * share)) for x, y in zip(a, b))


def tint_for(index, count, floor=TINT_LOW):
    """The share of ink for band `index` of `count`: light to dark, from `floor` (the lightest share that reads)."""
    low = max(TINT_LOW, floor)
    high = max(TINT_HIGH, low)
    return low if count == 1 else low + (high - low) * index / (count - 1)


def contrast(first, second):
    """WCAG's contrast ratio of two #RRGGBB colours (the formula of hrizzup_draw.contrast_ratio), 1 to 21."""
    def luminance(colour):
        total = 0.0
        for weight, index in ((0.2126, 1), (0.7152, 3), (0.0722, 5)):
            value = int(colour[index:index + 2], 16) / 255
            total += weight * (value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
        return total
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def readable_share(paper, ink, share=0.0, against=None, ratio=MIN_CONTRAST):
    """The smallest share of ink from `share` up (in hundredths) at which the tint of ink over paper has `ratio` (WCAG's
    4.5 to 1 for text, `GRAPHIC_CONTRAST` for a mark) against `against` (the paper unless said): 1.0, the full ink,
    when none lighter does."""
    against = against or paper
    for hundredth in range(int(round(share * 100)), 100):
        if contrast(mix(paper, ink, hundredth / 100), against) >= ratio:
            return hundredth / 100
    return 1.0


def shade(paper, ink, share, against=None, ratio=MIN_CONTRAST):
    """A tint of ink over paper that has `ratio` against `against` (the paper unless said): the one at `share`, or the
    lightest above it that does, or else the full ink. Used for text (4.5 to 1, the default) and for lines and fills
    that are not a ramp (pass `GRAPHIC_CONTRAST`)."""
    return mix(paper, ink, readable_share(paper, ink, share, against, ratio))


def band_fills(style, count):
    """The fills of a scale's `count` bands, lowest first: the ramp of tints of ink from TINT_LOW to TINT_HIGH, its light end
    raised only as far as WCAG's 3 to 1 for graphics against the paper (a fill is not text, so it needs no more). With
    paler ink the ramp is shorter, and with ink that has less than 3 to 1 all the bands are the ink."""
    floor = readable_share(style["paper"], style["ink"], ratio=GRAPHIC_CONTRAST)
    return [mix(style["paper"], style["ink"], tint_for(number, count, floor)) for number in range(count)]


def accent_on_paper(style):
    """The accent where it is drawn on the paper as a mark (a highlighted bar, a line): the accent if it has WCAG's
    3 to 1 for graphics there, else the ink."""
    return style["accent"] if contrast(style["accent"], style["paper"]) >= GRAPHIC_CONTRAST else style["ink"]


def fit_labels(labels, role, widest, measure, wrap, largest, smallest, max_lines, where, row=None):
    """The largest size from `largest` to `smallest` at which every label fits `widest` pixels in at most
    `max_lines` lines, and (given `row`, the height each label has) its lines fit that height, so the labels of two
    rows never overlap. Returns (size, [lines of each label]); TooLong otherwise."""
    for size in range(largest, smallest - 1, -1):
        lines = [wrap(label, role, size, widest) for label in labels]
        if all(len(found) <= max_lines and all(measure(line, role, size) <= widest for line in found)
               and (row is None or len(found) * size * LINE <= row) for found in lines):
            return size, lines
    worst = max(labels, key=lambda label: measure(label, role, smallest))
    raise TooLong("%s: the label %r is too long for its place: shorten it to about %d characters (it is %d), or use fewer items" % (
        where, worst, max(6, int(len(worst) * widest * max_lines / max(1.0, measure(worst, role, smallest)) * 0.8)), len(worst)))


def bar_layout(items, unit, width, height, measure, wrap):
    """Horizontal bars from zero, each labelled at the left and with its value at its end."""
    count = len(items)
    row = min(height / count, 112.0)
    column = width * 0.34
    size, lines = fit_labels([i["label"] for i in items], "text", column, measure, wrap, 32, 18, 2, "the bar chart", row=row)
    value_size = min(36, size + 4)
    texts = [value_text(i, unit) for i in items]
    value_width = max(measure(t, "text-bold", value_size) for t in texts)
    left = column + 20
    longest = width - left - value_width - 24
    if longest < 120:
        raise TooLong("the bar chart: the value labels are too wide: shorten the unit or the \"text\" of each value")
    top = max(i["value"] for i in items)
    thick = min(row * 0.62, 64.0)
    rows = []
    for number_, (item, found, text) in enumerate(zip(items, lines, texts)):
        length = item["value"] / top * longest
        if item["value"] > 0:
            length = max(length, 4.0)
        centre = row * (number_ + 0.5)
        rows.append({"label": item["label"], "lines": found, "value": text, "x0": left, "x1": left + length,
                     "y0": centre - thick / 2, "y1": centre + thick / 2, "centre": centre})
    return {"label_size": size, "value_size": value_size, "label_right": column, "rows": rows, "left": left,
            "bottom": row * count}


def column_layout(items, unit, width, height, measure, wrap):
    """Vertical columns from zero, each labelled beneath and with its value above."""
    count = len(items)
    slot = width / count
    size, lines = fit_labels([i["label"] for i in items], "text", slot * 0.92, measure, wrap, 30, 20, 3, "the column chart")
    label_height = max(len(found) for found in lines) * size * LINE
    texts = [value_text(i, unit) for i in items]
    for value_size in range(min(34, size + 4), 19, -1):  # the largest size at which every value fits above its column
        if all(measure(text, "text-bold", value_size) <= slot * 0.98 for text in texts):
            break
    else:
        raise TooLong("the column chart: a value label is wider than its column: shorten the unit or the \"text\" of each value, "
                      "or use fewer columns")
    base = height - label_height - 18
    room = base - (value_size * 1.3 + 14)
    if room < 80:
        raise TooLong("the column chart: not enough height for its labels: shorten them")
    top = max(i["value"] for i in items)
    wide = min(slot * 0.62, 130.0)
    cols = []
    for number_, (item, found, text) in enumerate(zip(items, lines, texts)):
        centre = slot * (number_ + 0.5)
        tall = item["value"] / top * room
        if item["value"] > 0:
            tall = max(tall, 4.0)
        cols.append({"label": item["label"], "lines": found, "value": text, "x0": centre - wide / 2, "x1": centre + wide / 2,
                     "y0": base - tall, "y1": base, "centre": centre})
    return {"label_size": size, "value_size": value_size, "base": base, "cols": cols}


def segment_hits_box(start, end, box, clearance=0.0):
    """Whether the segment start-end touches the box (left, top, right, bottom), grown by `clearance` pixels."""
    left, top, right, bottom = box[0] - clearance, box[1] - clearance, box[2] + clearance, box[3] + clearance
    (x0, y0), (x1, y1) = start, end
    enter, leave = 0.0, 1.0
    for delta, behind in ((x1 - x0, x0 - left), (x0 - x1, right - x0), (y1 - y0, y0 - top), (y0 - y1, bottom - y0)):
        if delta == 0:
            if behind < 0:
                return False
            continue
        along = -behind / delta  # where on the segment (0 to 1) this edge of the box is crossed
        if delta > 0:
            enter = max(enter, along)
        else:
            leave = min(leave, along)
        if enter > leave:
            return False
    return True


def boxes_overlap(first, second, clearance=0.0):
    return not (first[2] + clearance <= second[0] or second[2] + clearance <= first[0]
                or first[3] + clearance <= second[1] or second[3] + clearance <= first[1])


def line_layout(items, unit, from_zero, width, height, measure, wrap, marked):
    """A line through the points, labelled at the first, the last and any highlighted point. A label sits beside its
    point (left of the first, right of the last) or above or below it by the line's direction, and is never placed
    where the line, another label or the edge of the chart is in the way (TooLong when there is no such place)."""
    count = len(items)
    size = 26
    texts = [value_text(i, unit) for i in items]
    value_size = 30
    gap = 14  # from a point to its label
    labels = [i["label"] for i in items]
    ends = (0, count - 1)
    widths = [measure(text, "text-bold", value_size) for text in texts]
    left = max(widths[0] + gap + 8, measure(labels[0], "text", size) / 2 + 8)
    right = width - max(widths[-1] + gap + 8, measure(labels[-1], "text", size) / 2 + 8)
    label_height = size * LINE
    base = height - label_height - 20
    top_pad = value_size * 1.3 + 14
    values = [i["value"] for i in items]
    low = 0.0 if from_zero else min(values)
    high = max(values) if max(values) > low else low + 1.0
    if not from_zero:
        low = low - (high - low) * 0.08  # the line doesn't sit on the axis
    step = (right - left) / (count - 1)
    widest = max(measure(label, "text", size) for label in labels) + 18
    every = max(1, int(math.ceil(widest / step)))
    shown = list(range(0, count, every))
    if shown[-1] != count - 1:
        if (count - 1 - shown[-1]) * step < widest:
            shown[-1] = count - 1
        else:
            shown.append(count - 1)
    points = []
    for number_, item in enumerate(items):
        points.append({"label": item["label"], "x": left + step * number_,
                       "y": base - (item["value"] - low) / (high - low) * (base - top_pad), "value": texts[number_]})
    named = sorted({0, count - 1} | {n for n, i in enumerate(items) if marked and i["label"] in marked})
    path = [(p["x"], p["y"]) for p in points]
    height_of = value_size * 1.25
    taken = []
    for number_ in named:
        point, wide = points[number_], widths[number_]
        before = points[number_ - 1]["y"] if number_ > 0 else None
        after = points[number_ + 1]["y"] if number_ < count - 1 else None
        # (x of the text's anchor, y of its centre, how it is aligned): the first choice follows the line's direction
        beside_left = (point["x"] - gap, point["y"], "right", "center")
        beside_right = (point["x"] + gap, point["y"], "left", "center")
        above = (point["x"], point["y"] - gap, "center", "bottom")
        below = (point["x"], point["y"] + gap, "center", "top")
        upper_left = (point["x"] - gap, point["y"] - gap, "right", "bottom")
        upper_right = (point["x"] + gap, point["y"] - gap, "left", "bottom")
        lower_left = (point["x"] - gap, point["y"] + gap, "right", "top")
        lower_right = (point["x"] + gap, point["y"] + gap, "left", "top")
        if before is None:
            choices = [beside_left, upper_left, lower_left]
        elif after is None:
            choices = [beside_right, upper_right, lower_right]
        elif before > point["y"] and after > point["y"]:  # a peak
            choices = [above, upper_left, upper_right]
        elif before < point["y"] and after < point["y"]:  # a valley
            choices = [below, lower_left, lower_right]
        elif before > after:  # rising through the point: the free corners are upper left and lower right
            choices = [upper_left, lower_right, above, below]
        else:  # falling through it: upper right and lower left
            choices = [upper_right, lower_left, above, below]
        # if the line is in the way close to the point, try the same corners and sides a little further off
        for far in (30, 48):
            choices += [(point["x"], point["y"] - far, "center", "bottom"), (point["x"], point["y"] + far, "center", "top"),
                        (point["x"] - far, point["y"] - far, "right", "bottom"), (point["x"] + far, point["y"] - far, "left", "bottom"),
                        (point["x"] - far, point["y"] + far, "right", "top"), (point["x"] + far, point["y"] + far, "left", "top")]
        for x, y, align, vertical in choices:
            left_edge = x - wide if align == "right" else (x - wide / 2 if align == "center" else x)
            top_edge = y - height_of / 2 if vertical == "center" else (y - height_of if vertical == "bottom" else y)
            box = (left_edge, top_edge, left_edge + wide, top_edge + height_of)
            if box[0] < 0 or box[2] > width or box[1] < 0 or box[3] > base - 4:
                continue  # off the chart, or onto the axis
            if any(segment_hits_box(a, b, box, 3) for a, b in zip(path, path[1:])) or any(boxes_overlap(box, other, 4) for other in taken):
                continue
            points[number_]["label_at"] = {"x": x, "y": y, "align": align, "vertical": vertical}
            taken.append(box)
            break
        else:
            raise TooLong("the line chart: there is no room to label the point %r without the line running through its label: "
                          "highlight fewer points, or shorten the unit" % point["label"])
    return {"label_size": size, "value_size": value_size, "points": points, "base": base, "shown": shown, "named": named,
            "low": low}


def scale_layout(chart, width, height, measure, wrap):
    """A vertical scale: the bands stacked from lowest to highest in proportion, each named at the right, and
    the marker's value and label at the left."""
    bands = chart["bands"]
    low, high = bands[0]["from"], bands[-1]["to"]
    pad = 14.0
    span = height - 2 * pad

    def at(value):
        return height - pad - (value - low) / (high - low) * span

    left_col = width * 0.30
    bar_x0 = left_col + 24
    bar_x1 = bar_x0 + width * 0.17
    names_x = bar_x1 + 26
    room = width - names_x
    smallest_band = min(b["to"] - (bands[n - 1]["to"] if n else b["from"]) for n, b in enumerate(bands)) / (high - low) * span
    size = int(max(20, min(32, smallest_band * 0.5)))
    if smallest_band < size * LINE:
        raise TooLong("the scale: a band is only %d px tall, too narrow in proportion to carry its label: make the card taller "
                      "(1080x1350), or show the scale another way" % int(smallest_band))
    ranges = ["%s–%s" % (fmt_number(b["from"]), fmt_number(b["to"])) for b in bands]  # an en dash
    while size >= 20:
        name_w = max(measure(b["name"], "text-bold", size) for b in bands)
        range_w = max(measure(r, "text", size) for r in ranges)
        if name_w + 22 + range_w <= room:
            break
        size -= 1
    else:
        raise TooLong("the scale: the band names are too long for their place: shorten them (to about %d characters)" % 12)
    range_x = names_x + name_w + 22
    out = []
    for number_, (band, text) in enumerate(zip(bands, ranges)):
        # Edge to edge: a band starts where the one below it ends (so "0-50" and "51-100" are each 50 long).
        start = band["from"] if number_ == 0 else bands[number_ - 1]["to"]
        out.append({"name": band["name"], "range": text, "y0": at(band["to"]), "y1": at(start), "tint": tint_for(number_, len(bands))})
    marker = chart["marker"]
    placed = None
    if marker is not None:
        y = at(marker["value"])
        right = bar_x0 - 60  # the callout's right edge, left of the pointer
        centre = min(max(y, MARKER_VALUE + 4), height - MARKER_VALUE)  # the big value stays inside the chart
        lines = wrap(marker["label"], "text", MARKER_LABEL, right) if marker["label"] else []
        if len(lines) > 4 or any(measure(line, "text", MARKER_LABEL) > right for line in lines):
            raise TooLong("the scale's marker label is too long for its place: shorten it to about %d characters" % max(
                8, len(marker["label"]) * 4 // max(1, len(lines))))
        tall = len(lines) * MARKER_LABEL * LINE
        below_top = centre + MARKER_VALUE * 0.5 + 8
        above_bottom = centre - MARKER_VALUE * 0.5 - 8
        label = None
        if lines and below_top + tall <= height - 2:  # under the value
            label = {"y": below_top, "vertical": "top"}
        elif lines and above_bottom - tall >= 2:  # a low marker: over the value instead
            label = {"y": above_bottom, "vertical": "bottom"}
        elif lines:
            raise TooLong("the scale's marker label doesn't fit above or below the value at %s: shorten it" % fmt_number(marker["value"]))
        placed = {"y": y, "value_y": centre, "value": fmt_number(marker["value"]), "label": marker["label"], "right": right,
                  "label_lines": lines, "label_at": label,
                  "inside": next(n for n, b in enumerate(bands) if marker["value"] <= b["to"])}
    return {"size": size, "bar_x0": bar_x0, "bar_x1": bar_x1, "names_x": names_x, "range_x": range_x, "bands": out,
            "marker": placed, "left_col": left_col}


def spread_steps(template, count):
    """The template has five rows; for fewer steps, spread the rows over the same space (each at most one and a
    half times as tall as the template's) and drop the rows that aren't used. Returns (template, [y of each rule
    between rows, as a fraction of the height])."""
    spread = copy.deepcopy(template)
    slots = {t["slot"]: t for t in spread["texts"]}
    first, second = slots["n1"]["box"][1], slots["n2"]["box"][1]
    band = second - first
    last = slots["n%d" % STEP_ROWS]["box"][3]
    height = min((last - first + (band - (slots["n1"]["box"][3] - first))) / count, band * 1.5)
    scale = height / band
    for row in range(1, STEP_ROWS + 1):
        old, new = first + (row - 1) * band, first + (row - 1) * height
        for kind in ("n", "step"):
            box = slots["%s%d" % (kind, row)]["box"]
            box[1], box[3] = new + (box[1] - old) * scale, new + (box[3] - old) * scale
    spread["texts"] = [t for t in spread["texts"] if not (re.fullmatch(r"(?:n|step)\d", t["slot"]) and int(t["slot"][-1]) > count)]
    rule_gap = (band - (slots["n1"]["box"][3] - slots["n1"]["box"][1]) / scale) * scale / 2
    rules = [first + k * height - rule_gap for k in range(1, count)]
    return spread, rules


# ---------------------------------------------------------------------------------------------
# Drawing (matplotlib on its Agg canvas, Pillow to place)
# ---------------------------------------------------------------------------------------------

def log(message):
    print(message, file=sys.stderr)


def finish(ok, outputs, checks, problem, code):
    print(json.dumps({"ok": ok, "outputs": outputs, "checks": checks, "problem": problem}, ensure_ascii=False))
    return code


class Chart:
    """One chart's canvas: pixels from the top left, drawn by matplotlib's Agg and handed back as a Pillow image."""

    def __init__(self, hrizzup_draw, style, width, height):
        import logging
        from matplotlib import font_manager
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
        self.draw_module, self.style, self.width, self.height = hrizzup_draw, style, width, height
        self.font_manager = font_manager
        self.figure = Figure(figsize=((width + 0.25) / DPI, (height + 0.25) / DPI), dpi=DPI, facecolor=style["paper"],
                             layout="none")  # no layout engine, whatever the kit's style says: every mark is placed in pixels here
        self.canvas = FigureCanvasAgg(self.figure)
        self.axes = self.figure.add_axes([0, 0, 1, 1])
        self.axes.axis("off")
        self.axes.set_xlim(0, width)
        self.axes.set_ylim(height, 0)
        for role in ("display", "text", "text-bold"):
            font_manager.fontManager.addfont(str(hrizzup_draw.font_path(role, style)))  # the kit's own files

    def properties(self, role, size):
        return self.font_manager.FontProperties(fname=str(self.draw_module.font_path(role, self.style)), size=size * 72.0 / DPI)

    def text(self, x, y, text, role, size, colour, align="left", valign="center", spacing=1.2):
        self.draw_module.check_glyphs(text, role, self.style, "the chart's text %r" % text[:30])
        # A string is only ever text: "$5 to $7" is not maths, and no TeX is run (parse_math and usetex off, here
        # and in the drawing's own settings, so a creator's matplotlibrc can't turn them on).
        self.axes.text(x, y, text, fontproperties=self.properties(role, size), color=colour, ha=align, va=valign,
                       linespacing=spacing, multialignment=align, parse_math=False, usetex=False)

    def rectangle(self, x0, y0, x1, y1, colour, edge=None, edge_width=0):
        from matplotlib.patches import Rectangle
        self.axes.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor=colour, edgecolor=edge or "none",
                                      linewidth=edge_width * 72.0 / DPI, antialiased=True))

    def line(self, points, colour, width, cap="butt"):
        self.axes.plot([p[0] for p in points], [p[1] for p in points], color=colour, linewidth=width * 72.0 / DPI,
                       solid_capstyle=cap, solid_joinstyle="round")

    def polygon(self, points, colour):
        from matplotlib.patches import Polygon
        self.axes.add_patch(Polygon(points, closed=True, facecolor=colour, edgecolor="none", linewidth=0))

    def dot(self, x, y, radius, colour, ring=None):
        from matplotlib.patches import Circle
        self.axes.add_patch(Circle((x, y), radius, facecolor=colour, edgecolor=ring or "none",
                                   linewidth=(0 if not ring else 3 * 72.0 / DPI)))

    def image(self):
        from PIL import Image
        self.axes.set_xlim(0, self.width)
        self.axes.set_ylim(self.height, 0)
        self.canvas.draw()
        got_width, got_height = self.canvas.get_width_height()
        picture = Image.frombuffer("RGBA", (got_width, got_height), bytes(self.canvas.buffer_rgba()), "raw", "RGBA", 0, 1).convert("RGB")
        if picture.size != (self.width, self.height):
            picture = picture.crop((0, 0, self.width, self.height)) if picture.width >= self.width and picture.height >= self.height \
                else picture.resize((self.width, self.height), Image.Resampling.LANCZOS)
        return picture


def measurer(hrizzup_draw, style):
    def measure(text, role, size):
        return hrizzup_draw.get_font(role, size, style).getlength(text)

    def wrap(text, role, size, width):
        return hrizzup_draw.wrap(text, hrizzup_draw.get_font(role, size, style), width)

    return measure, wrap


def check_chart_text(hrizzup_draw, style, chart):
    """Refuse a character a font can't draw before anything is drawn (matplotlib would fall back quietly)."""
    for text in chart_texts(chart):
        hrizzup_draw.check_glyphs(text[1], text[0], style, "the chart's text %r" % text[1][:30])


def chart_texts(chart):
    """[(role, text)] of every string the chart draws."""
    found = []
    if chart["type"] in ("bar", "column", "line"):
        for item in chart["data"]:
            found += [("text", item["label"]), ("text-bold", value_text(item, chart["unit"]))]
    elif chart["type"] == "scale":
        for band in chart["bands"]:
            found += [("text-bold", band["name"]), ("text", fmt_number(band["from"]) + "–" + fmt_number(band["to"]))]
        if chart["marker"] is not None:
            found.append(("display", fmt_number(chart["marker"]["value"])))
            if chart["marker"]["label"]:
                found.append(("text", chart["marker"]["label"]))
    return found


def draw_bar(chart, spec, style, hrizzup_draw, width, height):
    measure, wrap = measurer(hrizzup_draw, style)
    layout = bar_layout(spec["data"], spec["unit"], width, height, measure, wrap)
    ink, paper = style["ink"], style["paper"]
    marked = set(spec["highlight"] or [])
    others = shade(paper, ink, TINT_OTHERS if marked else 0.86, ratio=GRAPHIC_CONTRAST)
    for row in layout["rows"]:
        colour = accent_on_paper(style) if row["label"] in marked else others
        chart.rectangle(row["x0"], row["y0"], row["x1"], row["y1"], colour)
        chart.text(layout["label_right"], row["centre"], "\n".join(row["lines"]), "text", layout["label_size"], ink, align="right")
        chart.text(row["x1"] + 14, row["centre"], row["value"], "text-bold", layout["value_size"], ink)
    chart.line([(layout["left"], 0), (layout["left"], layout["bottom"])], ink, 3)  # the zero line


def draw_column(chart, spec, style, hrizzup_draw, width, height):
    measure, wrap = measurer(hrizzup_draw, style)
    layout = column_layout(spec["data"], spec["unit"], width, height, measure, wrap)
    ink, paper = style["ink"], style["paper"]
    marked = set(spec["highlight"] or [])
    others = shade(paper, ink, TINT_OTHERS if marked else 0.86, ratio=GRAPHIC_CONTRAST)
    for col in layout["cols"]:
        colour = accent_on_paper(style) if col["label"] in marked else others
        chart.rectangle(col["x0"], col["y0"], col["x1"], col["y1"], colour)
        chart.text(col["centre"], col["y0"] - 10, col["value"], "text-bold", layout["value_size"], ink, align="center", valign="bottom")
        chart.text(col["centre"], layout["base"] + 14, "\n".join(col["lines"]), "text", layout["label_size"], ink, align="center", valign="top")
    chart.line([(0, layout["base"]), (width, layout["base"])], ink, 3)  # the zero line


def draw_line(chart, spec, style, hrizzup_draw, width, height):
    measure, wrap = measurer(hrizzup_draw, style)
    layout = line_layout(spec["data"], spec["unit"], spec["from_zero"], width, height, measure, wrap, spec["highlight"])
    ink, paper = style["ink"], style["paper"]
    stroke = accent_on_paper(style)
    points = layout["points"]
    chart.line([(0, layout["base"]), (width, layout["base"])], shade(paper, ink, 0.5, ratio=GRAPHIC_CONTRAST), 2)
    chart.line([(p["x"], p["y"]) for p in points], stroke, 6, cap="round")
    for number_ in layout["named"]:
        point = points[number_]
        chart.dot(point["x"], point["y"], 9, stroke, ring=paper)
        at = point["label_at"]  # beside the point, or above or below it, where the line is not
        chart.text(at["x"], at["y"], point["value"], "text-bold", layout["value_size"], ink, align=at["align"], valign=at["vertical"])
    for number_ in layout["shown"]:
        chart.text(points[number_]["x"], layout["base"] + 14, points[number_]["label"], "text", layout["label_size"], ink,
                   align="center", valign="top")
    if not spec["from_zero"]:
        chart.text(width, layout["base"] - 8, "The axis does not start at zero", "text", 22, shade(paper, ink, 0.7), align="right", valign="bottom")


def draw_scale(chart, spec, style, hrizzup_draw, width, height):
    measure, wrap = measurer(hrizzup_draw, style)
    layout = scale_layout(spec, width, height, measure, wrap)
    ink, paper = style["ink"], style["paper"]
    highlight = accent_on_paper(style)
    fills = band_fills(style, len(layout["bands"]))  # marks, not text: 3 to 1 on the paper, so the ramp keeps its range
    marker = layout["marker"]
    for number_, band in enumerate(layout["bands"]):
        colour = fills[number_]
        if marker is not None and highlight != ink and marker["inside"] == number_:
            colour = highlight
        chart.rectangle(layout["bar_x0"], band["y0"], layout["bar_x1"], band["y1"], colour, edge=paper, edge_width=3)
        middle = (band["y0"] + band["y1"]) / 2
        chart.text(layout["names_x"], middle, band["name"], "text-bold", layout["size"], ink)
        chart.text(layout["range_x"], middle, band["range"], "text", layout["size"], shade(paper, ink, 0.75))
    if marker is not None:
        y = marker["y"]
        end = layout["bar_x1"] + 6
        tip = layout["bar_x0"] - 16
        chart.line([(tip, y), (end, y)], paper, 11)  # a halo, so it shows on the darkest band
        chart.line([(tip, y), (end, y)], ink, 5)
        chart.polygon([(tip - 30, y - 17), (tip - 30, y + 17), (tip, y)], ink)
        chart.text(marker["right"], marker["value_y"], marker["value"], "display", MARKER_VALUE, ink, align="right")
        if marker["label_at"] is not None:
            chart.text(marker["right"], marker["label_at"]["y"], "\n".join(marker["label_lines"]), "text", MARKER_LABEL, ink,
                       align="right", valign=marker["label_at"]["vertical"])


DRAWERS = {"bar": draw_bar, "column": draw_column, "line": draw_line, "scale": draw_scale}


def draw_chart(spec, style, hrizzup_draw, width, height):
    """The chart as a Pillow image of exactly width x height, drawn with matplotlib's own defaults plus the kit's
    style (`assets/hrizzup.mplstyle`), whatever a matplotlibrc on this machine says (usetex and the like)."""
    check_chart_text(hrizzup_draw, style, spec)
    import matplotlib
    import matplotlib.style
    if not STYLE_FILE.is_file():
        raise hrizzup_draw.DrawError("the kit's assets/hrizzup.mplstyle isn't there: get the kit again", 3)
    with matplotlib.rc_context(matplotlib.rcParamsDefault):
        matplotlib.style.use(str(STYLE_FILE))
        chart = Chart(hrizzup_draw, style, width, height)
        DRAWERS[spec["type"]](chart, spec, style, hrizzup_draw, width, height)
        return chart.image()


def place_picture(hrizzup_draw, canvas, path, box, paper):
    """Your own chart, centred in the chart's place at no more than its own size (shrunk to fit, never enlarged),
    its transparency laid over the paper. The picture must be one `hrizzup_draw.load_picture` accepts."""
    from PIL import Image
    picture = hrizzup_draw.flatten(hrizzup_draw.load_picture(path), paper)
    left, top, right, bottom = box
    scale = min(1.0, (right - left) / picture.width, (bottom - top) / picture.height)
    if scale < 1.0:
        picture = picture.resize((max(1, int(picture.width * scale)), max(1, int(picture.height * scale))), Image.Resampling.LANCZOS)
    x = int(left + (right - left - picture.width) / 2)
    y = int(top + (bottom - top - picture.height) / 2)
    canvas.paste(picture, (x, y))


class Parser(argparse.ArgumentParser):
    """A command line that is wrong is bad input (exit 2, with the JSON line), not argparse's own exit."""

    def error(self, message):
        raise InputError(message)


def make_parser():
    parser = Parser(
        prog="infographic.py",
        description="Make an infographic (1080 x 1350 or 1080 x 1080): a chart, one big number, or a few steps, from a JSON spec.",
        epilog="Example: uv run scripts/infographic.py --spec spec.json --size 1080x1350 --out infographic.png",
    )
    parser.add_argument("--spec", required=True, help="the spec: a JSON file (see this command's docstring and SKILL.md)")
    parser.add_argument("--size", default="1080x1350", help="1080x1350 (default) or 1080x1080")
    parser.add_argument("--style", help="a style file: JSON, or a markdown file with a json block (default plain)")
    parser.add_argument("--out", required=True, help="the card to write: a .png, .jpg or .webp (never an input)")
    return parser


def read_spec(path):
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InputError("can't read the spec %s: %s" % (path, error))
    try:
        return json.loads(text)
    except ValueError as error:
        raise InputError("the spec %s isn't valid JSON: %s" % (path, error))


def main(argv=None):
    """Make the card; whatever goes wrong, the last line printed is the JSON line."""
    try:
        return make(argv)
    except ImportError as error:  # a package turned out to be missing deep inside a call
        message = "a Python package or module is missing (%s): get the kit again and install its packages" % error
        log("infographic.py: " + message)
        return finish(False, [], [], message, 3)
    except Exception as error:  # the last resort: a mistake in this command, never a bare traceback
        message = "infographic.py failed unexpectedly (%s: %s): this is a mistake in the kit, so tell your owner" % (
            type(error).__name__, error)
        log("infographic.py: " + message)
        return finish(False, [], [], message, 1)


def make(argv=None):
    try:
        args = make_parser().parse_args(argv)
        size, out = parse_size(args.size), check_paths(args)
        spec = validate_spec(read_spec(args.spec))
    except InputError as error:
        log("infographic.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    try:
        import hrizzup_draw
        if spec["template"] == "chart-card" and "chart" in spec:
            import matplotlib  # noqa: F401  (named here so a missing package is reported before any drawing)
    except ImportError as error:
        message = ("a Python package is missing (%s): run this with `uv run scripts/infographic.py`, which installs them, or "
                   "make a virtual environment and install the exact set: `python3.12 -m venv .venv`, "
                   "`.venv/bin/python -m pip install --require-hashes -r scripts/infographic.requirements.txt`, "
                   "then `.venv/bin/python scripts/infographic.py ...`" % error)
        log("infographic.py: " + message)
        return finish(False, [], [], message, 3)
    try:
        style = hrizzup_draw.load_style(args.style)
        template = hrizzup_draw.load_template(TEMPLATES / (spec["template"] + ".json"))
        texts = {"title": spec["title"], "source": spec["source"]}
        if spec["subtitle"]:
            texts["subtitle"] = spec["subtitle"]
        rules, groups = [], []
        if spec["template"] == "stat-card":
            stat = spec["chart"]
            texts.update({"value": stat["value"], "label": stat["label"]})
            if stat["note"]:
                texts["note"] = stat["note"]
        elif spec["template"] == "steps-card":
            template, rules = spread_steps(template, len(spec["steps"]))
            for number_, step in enumerate(spec["steps"], start=1):
                texts["n%d" % number_], texts["step%d" % number_] = str(number_), step
            groups = [["n%d" % n for n in range(1, len(spec["steps"]) + 1)], ["step%d" % n for n in range(1, len(spec["steps"]) + 1)]]
        canvas, placed = hrizzup_draw.render_template(template, texts, style, size, same_size=groups)
        if spec["template"] == "chart-card":
            box = template["picture"]["box"]
            pixels = (int(round(box[0] * size[0])), int(round(box[1] * size[1])), int(round(box[2] * size[0])), int(round(box[3] * size[1])))
            if "image" in spec:
                given = spec["image"] if os.path.isabs(spec["image"]) else os.path.join(os.path.dirname(os.path.abspath(args.spec)), spec["image"])
                if hrizzup_media.same_file(given, out):
                    raise InputError("--out would overwrite the image %s, an input" % given)
                place_picture(hrizzup_draw, canvas, given, pixels, style["paper"])
            else:
                canvas.paste(draw_chart(spec["chart"], style, hrizzup_draw, pixels[2] - pixels[0], pixels[3] - pixels[1]), pixels[:2])
        elif spec["template"] == "steps-card":
            from PIL import ImageDraw
            draw = ImageDraw.Draw(canvas)
            line = tuple(int(mix(style["paper"], style["ink"], 0.22)[i:i + 2], 16) for i in (1, 3, 5))
            left, right = template["texts"][0]["box"][0] * size[0], template["texts"][0]["box"][2] * size[0]
            for fraction in rules:
                draw.line([(left, fraction * size[1]), (right, fraction * size[1])], fill=line, width=2)
        written = hrizzup_draw.save_image(canvas, out)
    except InputError as error:
        log("infographic.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    except TooLong as error:
        log("infographic.py: %s" % error)
        return finish(False, [], [], str(error), 1)
    except hrizzup_draw.DrawError as error:
        log("infographic.py: %s" % error)
        return finish(False, [], [], str(error), error.code)
    checks, problems = [], []
    try:
        info = hrizzup_media.inspect(written)
    except hrizzup_media.MediaError as error:
        info, problems = None, [str(error)]
    if info is not None:
        # Hrizzup's own limits (10 MiB, 4,096 px a side); the repository's 2 MiB is for its samples.
        limits = hrizzup_media.problems(info, "image", budget=False)
        problems += limits
        if (info.width, info.height) not in SIZES:
            problems.append("the card is %dx%d; an infographic is %s" % (info.width, info.height, " or ".join("%dx%d" % s for s in SIZES)))
        checks = [
            {"name": "Hrizzup's image limits", "ok": not limits},
            {"name": "an infographic's size", "ok": (info.width, info.height) in SIZES},
        ]
    if problems:
        try:
            os.remove(written)
        except OSError:
            pass
        message = "; ".join(problems)
        log("infographic.py: the card failed its checks: " + message)
        return finish(False, [], checks, message, 1)
    log("infographic.py: %s; %d bytes, %dx%d" % (spec["template"], info.bytes, info.width, info.height))
    outputs = [{"path": os.path.relpath(written) if not os.path.isabs(args.out) else written,
                "bytes": info.bytes, "width": info.width, "height": info.height, "seconds": None}]
    return finish(True, outputs, checks, None, 0)


if __name__ == "__main__":
    sys.exit(main())
