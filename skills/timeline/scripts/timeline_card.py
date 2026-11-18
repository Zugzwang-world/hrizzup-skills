# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow==13.0.0", "fonttools==4.68.0"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Draw a story's timeline as a card (1080 x 1350): one dated row for each update, oldest first.

The rows come from the story's updates: either `--items` (a JSON list from the updates call) or
`--brief` (the story's brief as Hrizzup serves it: its `## Timeline` lines). The newest six are kept,
and a line says how many earlier ones are left out. A correction is marked, with the update it corrects.
Times are shown in `--tz` (UTC unless you say otherwise).

    items.json: [{"at": "2026-11-02T01:30:00Z", "headline": "...", "corrects": null}, ...]
    `at` is an ISO 8601 time (`reportedAt` works too; no zone means UTC). `corrects` is left out or null,
    or says which update is corrected: the `id` of another item, or its time. Any other text marks the row
    as a correction of an earlier update.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made
and checked; 1 the card failed a Hrizzup limit or quality check (text too long: it says how far to shorten);
2 bad input; 3 a missing package or kit file.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hrizzup_media

KIT = Path(__file__).resolve().parent.parent
TEMPLATE = KIT / "assets" / "templates" / "timeline-card.json"
ROWS = 6  # the template's rows
MAX_ITEMS_FILE = 500
MAX_HEADLINE = 300
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
SIZES = ((1080, 1350), (1080, 1080))  # a timeline card's sizes (Hrizzup's format guide)
BRIEF_LINE = re.compile(
    r"^- (?P<at>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) UTC"
    r"(?P<corrects> \(corrects (?:the (?P<target>\d{4}-\d{2}-\d{2} \d{2}:\d{2}) update|an earlier update)\))?"
    r": (?P<text>.+)$"
)
UNKNOWN_TARGET = True  # a correction whose target isn't known


class InputError(Exception):
    """The input is wrong (exit 2)."""


# ---------------------------------------------------------------------------------------------
# Reading the updates (standard library only)
# ---------------------------------------------------------------------------------------------

def minute_time(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def split_headline(text):
    """The headline of a brief's timeline line: the text up to its first ". "; or all of it, without
    its closing full stop, when there is no second sentence."""
    head, found, _rest = text.partition(". ")
    head = head.strip()
    if not found and head.endswith("."):
        head = head[:-1].rstrip()
    return head


def parse_brief(text):
    """(title, items) from a brief's text: its `# ` title and the lines of its `## Timeline` section."""
    title = None
    items = []
    inside = False
    for line in text.split("\n"):
        line = line.rstrip()
        if line.startswith("# ") and title is None:
            title = line[2:].strip()
        if line.startswith("## "):
            inside = line[3:].strip() == "Timeline"
            continue
        if not inside:
            continue
        found = BRIEF_LINE.match(line)
        if not found:
            continue  # a blank line, or the note about older updates left out
        headline = split_headline(found.group("text"))
        if not headline:
            continue
        corrects = None
        if found.group("corrects"):
            corrects = minute_time(found.group("target")) if found.group("target") else UNKNOWN_TARGET
        items.append({"at": minute_time(found.group("at")), "headline": headline, "corrects": corrects, "id": None})
    if not items:
        raise InputError("the brief has no `## Timeline` lines like \"- 2026-11-02 01:30 UTC: headline. more\"")
    return title, items


def parse_time(value, what):
    if not isinstance(value, str):
        raise InputError("%s must be a time as text, like 2026-11-02T01:30:00Z" % what)
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        raise InputError("%s %r isn't an ISO 8601 time like 2026-11-02T01:30:00Z" % (what, value))
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def read_items(data):
    """Items from the JSON of `--items` (a list of {"at", "headline", "corrects"}, see the top of this file)."""
    if not isinstance(data, list) or not data:
        raise InputError("the items file must be a JSON list with at least one item")
    if len(data) > MAX_ITEMS_FILE:
        raise InputError("the items file has %d items; at most %d" % (len(data), MAX_ITEMS_FILE))
    items = []
    for number, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise InputError("item %d isn't an object" % number)
        when = entry.get("at", entry.get("reportedAt"))
        headline = entry.get("headline")
        if not isinstance(headline, str) or not headline.strip():
            raise InputError("item %d needs a headline" % number)
        if len(headline) > MAX_HEADLINE:
            raise InputError("item %d's headline is %d characters; at most %d" % (number, len(headline), MAX_HEADLINE))
        corrects = entry.get("corrects")
        if corrects is not None and not isinstance(corrects, str):
            raise InputError("item %d: corrects is null, or text naming the corrected update" % number)
        items.append({"at": parse_time(when, "item %d's `at`" % number), "headline": " ".join(headline.split()),
                      "corrects": corrects, "id": entry.get("id") if isinstance(entry.get("id"), str) else None})
    by_id = {i["id"]: i["at"] for i in items if i["id"]}
    for item in items:
        target = item["corrects"]
        if target is None:
            continue
        if target in by_id:
            item["corrects"] = by_id[target]
        else:
            try:
                item["corrects"] = parse_time(target, "corrects")
            except InputError:
                item["corrects"] = UNKNOWN_TARGET
    return items


def select(items, limit):
    """(the newest `limit` items oldest first, how many earlier ones are left out)."""
    ordered = sorted(items, key=lambda i: i["at"])  # a stable sort keeps the given order for equal times
    kept = ordered[-limit:] if limit < len(ordered) else ordered
    return kept, len(ordered) - len(kept)


def parse_zone(name):
    """A time zone: UTC, an offset like +05:30, or an IANA name like Asia/Kolkata."""
    if name.strip().upper() in ("UTC", "Z"):
        return timezone.utc
    offset = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", name.strip())
    if offset:
        delta = timedelta(hours=int(offset.group(2)), minutes=int(offset.group(3)))
        if delta >= timedelta(hours=24):
            raise InputError("the offset %s is more than a day" % name)
        return timezone(delta if offset.group(1) == "+" else -delta)
    try:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    except ImportError:  # pragma: no cover
        raise InputError("this Python has no time zone names: use UTC or an offset like +05:30")
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise InputError("unknown time zone %r: use a name like Asia/Kolkata, UTC or an offset like +05:30 "
                         "(on Windows, names need `pip install tzdata`)" % name)


def date_text(moment, zone, with_year):
    local = moment.astimezone(zone)
    return "%d %s%s" % (local.day, MONTHS[local.month - 1], " %d" % local.year if with_year else "")


def time_text(moment, zone):
    local = moment.astimezone(zone)
    return "%02d:%02d %s" % (local.hour, local.minute, local.tzname())


def plain_correction(headline):
    """A correction's headline without its leading "Correction:", which the card's mark already says."""
    stripped = re.sub(r"^\s*correction\s*:\s*", "", headline, flags=re.I)
    return stripped[:1].upper() + stripped[1:] if stripped else headline


def minute_of(moment):
    return moment.astimezone(timezone.utc).replace(second=0, microsecond=0)


def build_texts(kept, left_out, title, zone):
    """{slot: text} for the template, and the groups of slots to draw at one size.

    A correction's row says which update it corrects, and the row it corrects says it was corrected and
    by which update (the earliest one), so nobody reads the old claim without seeing the new one."""
    with_year = len({i["at"].astimezone(zone).year for i in kept}) > 1
    texts = {"title": title}
    newest = kept[-1]["at"]
    texts["subtitle"] = "Latest update: %s, %s" % (date_text(newest, zone, True), time_text(newest, zone))
    if left_out:
        texts["more"] = ("1 earlier update is not shown" if left_out == 1
                         else "%d earlier updates are not shown" % left_out)
    corrected_by = {}  # the minute of a corrected update -> the time of the earliest correction of it
    for item in kept:
        if isinstance(item["corrects"], datetime) and minute_of(item["corrects"]) != minute_of(item["at"]):
            corrected_by.setdefault(minute_of(item["corrects"]), item["at"])

    def stamp(moment):
        return "%s, %s" % (date_text(moment, zone, with_year), time_text(moment, zone))

    for row, item in enumerate(kept, start=1):
        texts["when%d" % row] = date_text(item["at"], zone, with_year) + "\n" + time_text(item["at"], zone)
        corrects, later = item["corrects"], corrected_by.get(minute_of(item["at"]))
        texts["what%d" % row] = item["headline"] if corrects is None else plain_correction(item["headline"])
        marks = []
        if corrects is UNKNOWN_TARGET:
            marks.append("Correction")
        elif corrects is not None:
            marks.append(("Corrects the %s update" if later is None else "Corrects %s") % stamp(corrects))
        if later is not None:
            marks.append("Corrected %s" % stamp(later))
        if marks:
            texts["mark%d" % row] = ". ".join(marks)
    texts["note"] = "Sources are attached to the post."
    groups = [["when%d" % r for r in range(1, ROWS + 1)], ["what%d" % r for r in range(1, ROWS + 1)],
              ["mark%d" % r for r in range(1, ROWS + 1)]]
    return texts, groups


def spread_rows(template, count):
    """The template has six rows; for fewer updates, spread the rows down the card (each at most one and
    a half times as tall as the template's), so the card isn't empty at the bottom, and drop the rows
    that aren't used."""
    spread = copy.deepcopy(template)
    slots = {t["slot"]: t for t in spread["texts"]}
    first = slots["when1"]["box"][1]
    band = slots["when2"]["box"][1] - first
    height = min(band * ROWS / count, band * 1.5)
    scale = height / band
    for row in range(1, ROWS + 1):
        old, new = first + (row - 1) * band, first + (row - 1) * height
        for kind in ("when", "mark", "what"):
            box = slots["%s%d" % (kind, row)]["box"]
            box[1], box[3] = new + (box[1] - old) * scale, new + (box[3] - old) * scale
    spread["texts"] = [t for t in spread["texts"] if not (re.fullmatch(r"(?:when|mark|what)\d", t["slot"]) and int(t["slot"][-1]) > count)]
    return spread


# ---------------------------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------------------------

def log(message):
    print(message, file=sys.stderr)


def finish(ok, outputs, checks, problem, code):
    print(json.dumps({"ok": ok, "outputs": outputs, "checks": checks, "problem": problem}, ensure_ascii=False))
    return code


def read_text(path, what):
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise InputError("can't read %s %s: %s" % (what, path, error))


def make_parser():
    parser = argparse.ArgumentParser(
        prog="timeline_card.py",
        description="Draw a story's timeline as a 1080 x 1350 card, one dated row for each update, oldest first.",
        epilog="Example: uv run scripts/timeline_card.py --brief brief.md --out card.png --tz Asia/Kolkata",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--items", help="a JSON list of {\"at\", \"headline\", \"corrects\"} from the updates call")
    source.add_argument("--brief", help="the story's brief (its ## Timeline lines are read)")
    parser.add_argument("--out", required=True, help="the card to write: a .png, .jpg or .webp (never an input)")
    parser.add_argument("--tz", default="UTC", help="the time zone to show, such as Asia/Kolkata (default UTC)")
    parser.add_argument("--max-items", type=int, default=ROWS, help="the newest rows to show, 1 to 6 (default 6)")
    parser.add_argument("--title", help="the card's title (default: the brief's title, or \"The story so far\")")
    parser.add_argument("--style", help="a style file: JSON, or a markdown file with a json block (default plain)")
    return parser


def run(args):
    if not 1 <= args.max_items <= ROWS:
        raise InputError("--max-items is 1 to %d" % ROWS)
    out = os.path.abspath(args.out)
    for given in (args.items, args.brief, args.style):
        if given and os.path.abspath(given) == out:
            raise InputError("--out would overwrite %s, an input" % given)
    if os.path.splitext(out)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise InputError("--out is a .png, .jpg or .webp file")
    zone = parse_zone(args.tz)
    title = None
    if args.brief:
        title, items = parse_brief(read_text(args.brief, "the brief"))
    else:
        try:
            items = read_items(json.loads(read_text(args.items, "the items file")))
        except ValueError as error:
            raise InputError("the items file isn't valid JSON: %s" % error)
    title = args.title or title or "The story so far"
    kept, left_out = select(items, args.max_items)
    texts, groups = build_texts(kept, left_out, title, zone)
    return kept, left_out, texts, groups, zone, out


def main(argv=None):
    args = make_parser().parse_args(argv)
    try:
        kept, left_out, texts, groups, zone, out = run(args)
    except InputError as error:
        log("timeline_card.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    try:
        import hrizzup_draw
    except ImportError as error:
        message = ("a Python package is missing (%s): run this with `uv run scripts/timeline_card.py`, which installs "
                   "them, or make a virtual environment and install the exact set: `python3.12 -m venv .venv`, "
                   "`.venv/bin/python -m pip install --require-hashes -r scripts/timeline_card.requirements.txt`, "
                   "then `.venv/bin/python scripts/timeline_card.py ...`" % error)
        log("timeline_card.py: " + message)
        return finish(False, [], [], message, 3)
    try:
        style = hrizzup_draw.load_style(args.style)
        template = spread_rows(hrizzup_draw.load_template(TEMPLATE), len(kept))
        size = tuple(template["sizes"][0])
        canvas, placed = hrizzup_draw.render_template(template, texts, style, size, same_size=groups)
        written = hrizzup_draw.save_image(canvas, out)
    except hrizzup_draw.DrawError as error:
        log("timeline_card.py: %s" % error)
        return finish(False, [], [], str(error), error.code)
    checks, problems = [], []
    try:
        info = hrizzup_media.inspect(written)
    except hrizzup_media.MediaError as error:
        info, problems = None, [str(error)]
    if info is not None:
        problems += hrizzup_media.problems(info, "image")
        if (info.width, info.height) not in SIZES:
            problems.append("the card is %dx%d; a timeline card is %s" % (
                info.width, info.height, " or ".join("%dx%d" % s for s in SIZES)))
        checks = [
            {"name": "Hrizzup's image limits and this repository's budget", "ok": not hrizzup_media.problems(info, "image")},
            {"name": "a timeline card's size", "ok": (info.width, info.height) in SIZES},
        ]
    if problems:
        try:
            os.remove(written)
        except OSError:
            pass
        message = "; ".join(problems)
        log("timeline_card.py: the card failed its checks: " + message)
        return finish(False, [], checks, message, 1)
    log("timeline_card.py: %d row%s, %d earlier left out; %d bytes, %dx%d" % (
        len(kept), "" if len(kept) == 1 else "s", left_out, info.bytes, info.width, info.height))
    outputs = [{"path": os.path.relpath(written) if not os.path.isabs(args.out) else written,
                "bytes": info.bytes, "width": info.width, "height": info.height, "seconds": None}]
    return finish(True, outputs, checks, None, 0)


if __name__ == "__main__":
    sys.exit(main())
