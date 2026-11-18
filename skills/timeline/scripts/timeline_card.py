# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow==13.0.0", "fonttools==4.68.0"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Draw a story's timeline as a card (1080 x 1350): one dated row for each update, oldest first.

The rows come from the story's updates: either `--items`, the updates call's answer saved as a file and
passed on unchanged (`{"updates": [...], "next": ...}`, or just the list), or `--brief`, the story's brief
as Hrizzup serves it (its `## Timeline` lines). The newest six are kept, and a line says how many earlier
ones are left out. A correction is marked with the update it corrects, and the update it corrects is
marked as corrected. Times are shown in `--tz` (Asia/Kolkata unless you say otherwise), each with its zone.

    updates.json: {"updates": [{"id": "...", "headline": "...", "reportedAt": "2026-11-02T01:30:00Z",
                                "corrects": null, "sources": [...], "body": null}, ...], "next": null}
    `id`, `reportedAt` (`at` works too; no zone means UTC) and `headline` are read; `corrects` is null or the
    `id` of the update it corrects, which must be in the same answer (pass every page if `next` isn't null).

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made
and checked; 1 the card failed a Hrizzup limit or quality check (text too long: it says how far to shorten);
2 bad input; 3 a missing package or kit file, or no time zone data on this machine.
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
# brief.ts's note when the oldest updates give way: "- 3 earlier updates are left out: read them with ..."
BRIEF_LEFT_OUT = re.compile(r"^- (?P<count>\d+) earlier updates? (?:is|are) left out\b")
UNKNOWN_TARGET = True  # a correction whose target isn't known
DEFAULT_ZONE = "Asia/Kolkata"
# Words that end in a full stop without ending a sentence (compared in lower case, without their dots).
ABBREVIATIONS = frozenset((
    "no nos rs mr mrs ms dr st sr jr prof gen col lt sgt capt cmdr maj sen rep gov hon rev fr mt vs etc "
    "inc ltd co corp dept approx govt vol").split())
SENTENCE_END = re.compile(r"([.!?\u2026])([\"')\]\u2019\u201d]*)\s+")


class InputError(Exception):
    """The input is wrong (exit 2)."""


class NoZoneData(Exception):
    """This machine has no time zone data for the name given (exit 3)."""


# ---------------------------------------------------------------------------------------------
# Reading the updates (standard library only)
# ---------------------------------------------------------------------------------------------

def minute_time(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def is_abbreviation(text):
    """Whether the text before a full stop ends in an abbreviation or an initial (No, Rs, Dr, U.S, e.g, J)."""
    words = text.split()
    word = words[-1].lstrip("(\"'[\u2018\u201c") if words else ""
    bare = word.replace(".", "")
    if not bare:
        return False
    if len(bare) == 1 and bare.isalpha() and bare.isupper():
        return True  # a single capital: an initial, or "A."
    if "." in word and all(len(part) == 1 and part.isalpha() for part in word.split(".")):
        return True  # U.S, e.g, i.e, a.m
    return bare.lower() in ABBREVIATIONS


def split_headline(text):
    """The headline of a brief's timeline line. brief.ts writes the headline, a full stop if it had no
    closing mark, a space and the update's body. So the headline ends at the first "? ", "! " or ". "
    that isn't an abbreviation ("No. 3", "Rs. 500 crore", "Mr. Rao", "U.S. aid"); with no second sentence it is
    all of the text, without a closing full stop that isn't an abbreviation's."""
    text = text.strip()
    for found in SENTENCE_END.finditer(text):
        mark, closers = found.group(1), found.group(2)
        before = text[:found.start()]
        if mark == "." and not closers and is_abbreviation(before):
            continue
        head = text[:found.start() + 1 + len(closers)]
        return head[:-1].rstrip() if head.endswith(".") and not closers else head
    if text.endswith(".") and not is_abbreviation(text[:-1]):
        return text[:-1].rstrip()
    return text


def parse_brief(text):
    """(title, items, earlier) from a brief's text: its `# ` title, the lines of its `## Timeline` section, and
    how many older updates its note says were left out (0 if none)."""
    title = None
    items = []
    earlier = 0
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
        note = BRIEF_LEFT_OUT.match(line)
        if note:
            earlier = int(note.group("count"))
            continue
        found = BRIEF_LINE.match(line)
        if not found:
            continue  # a blank line, or "- No updates yet"
        headline = split_headline(found.group("text"))
        if not headline:
            continue
        corrects = None
        if found.group("corrects"):
            corrects = ({"id": None, "at": minute_time(found.group("target"))} if found.group("target")
                        else UNKNOWN_TARGET)
        items.append({"at": minute_time(found.group("at")), "headline": headline, "corrects": corrects, "id": None})
    if not items:
        raise InputError("the brief has no `## Timeline` lines like \"- 2026-11-02 01:30 UTC: headline. more\"")
    return title, items, earlier


def parse_time(value, what):
    if not isinstance(value, str):
        raise InputError("%s must be a time as text, like 2026-11-02T01:30:00Z" % what)
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        raise InputError("%s %r isn't an ISO 8601 time like 2026-11-02T01:30:00Z" % (what, value))
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment


def read_items(data):
    """(items, more) from the JSON of `--items`: the updates call's answer as it is, `{"updates": [...],
    "next": ...}`, or just its list. `more` is true when `next` says there are older updates not in the answer."""
    more = False
    if isinstance(data, dict):
        if not isinstance(data.get("updates"), list):
            raise InputError("the items file must be the updates call's answer, {\"updates\": [...], \"next\": ...}, or its list")
        more = data.get("next") not in (None, "")
        data = data["updates"]
    if not isinstance(data, list) or not data:
        raise InputError("the items file must hold at least one update")
    if len(data) > MAX_ITEMS_FILE:
        raise InputError("the items file has %d updates; at most %d" % (len(data), MAX_ITEMS_FILE))
    items = []
    for number, entry in enumerate(data, start=1):
        if not isinstance(entry, dict):
            raise InputError("update %d isn't an object" % number)
        when = entry.get("reportedAt", entry.get("at"))
        headline = entry.get("headline")
        if not isinstance(headline, str) or not headline.strip():
            raise InputError("update %d needs a headline" % number)
        if len(headline) > MAX_HEADLINE:
            raise InputError("update %d's headline is %d characters; at most %d" % (number, len(headline), MAX_HEADLINE))
        identity = entry.get("id")
        if identity is not None and not (isinstance(identity, str) and identity):
            raise InputError("update %d: id is text" % number)
        corrects = entry.get("corrects")
        if corrects is not None and not (isinstance(corrects, str) and corrects):
            raise InputError("update %d: corrects is null or the id of the update it corrects" % number)
        items.append({"at": parse_time(when, "update %d's reportedAt" % number), "headline": " ".join(headline.split()),
                      "corrects": corrects, "id": identity})
    by_id = {}
    for item in items:
        if item["id"] is not None:
            if item["id"] in by_id:
                raise InputError("two updates have the id %s" % item["id"])
            by_id[item["id"]] = item
    for item in items:
        target = item["corrects"]
        if target is None:
            continue
        if target not in by_id or target == item["id"]:
            raise InputError(
                "the update %s corrects %s, which isn't another update in the answer: pass the updates call's answer "
                "unchanged%s" % (item["id"] or item["headline"][:30], target,
                                 " (and the older pages too, as `next` isn't empty)" if more else ""))
        item["corrects"] = {"id": target, "at": by_id[target]["at"]}
    return items, more


def select(items, limit):
    """(the newest `limit` items oldest first, how many earlier ones are left out)."""
    ordered = sorted(items, key=lambda i: (i["at"], i["id"] or ""))
    kept = ordered[-limit:] if limit < len(ordered) else ordered
    return kept, len(ordered) - len(kept)


def parse_zone(name):
    """A time zone: UTC, an offset like +05:30, or an IANA name like Asia/Kolkata. Asia/Kolkata and UTC work
    even where the machine has no time zone data (as fixed offsets, which India's and UTC's always are)."""
    given = name.strip()
    if given.upper() in ("UTC", "Z"):
        return timezone.utc
    offset = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", given)
    if offset:
        delta = timedelta(hours=int(offset.group(2)), minutes=int(offset.group(3)))
        if delta >= timedelta(hours=24):
            raise InputError("the offset %s is more than a day" % name)
        return timezone(delta if offset.group(1) == "+" else -delta)
    import zoneinfo
    try:
        return zoneinfo.ZoneInfo(given)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        if given == "Asia/Kolkata":
            return timezone(timedelta(hours=5, minutes=30), "IST")
        if not zoneinfo.available_timezones():
            raise NoZoneData("this machine has no time zone data, so %r can't be used: install it (on Windows, "
                             "`pip install tzdata`), or give an offset like +05:30, or use Asia/Kolkata or UTC" % name)
        raise InputError("unknown time zone %r: use a name like Asia/Kolkata, UTC or an offset like +05:30" % name)


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


def left_out_text(left_out, more):
    """The line that says how many earlier updates the card leaves out ('' when none)."""
    if more:  # the answer has a next page: how many older ones there are isn't known
        return "%d or more earlier updates are not shown" % left_out if left_out else "Earlier updates are not shown"
    if not left_out:
        return ""
    return "1 earlier update is not shown" if left_out == 1 else "%d earlier updates are not shown" % left_out


def build_texts(kept, left_out, title, zone, more=False, everyone=None):
    """{slot: text} for the template, and the groups of slots to draw at one size.

    A correction's row says which update it corrects, and the row it corrects says it was corrected and
    by which update (the earliest one), so nobody reads the old claim without seeing the new one.
    Updates are matched by their id. A brief has no ids, only minutes, so a minute that more than one update
    (of `everyone`, every update read, kept or not) shares names no row as corrected: it could be either."""
    with_year = len({i["at"].astimezone(zone).year for i in kept}) > 1
    texts = {"title": title}
    newest = kept[-1]["at"]
    texts["subtitle"] = "Latest update: %s, %s" % (date_text(newest, zone, True), time_text(newest, zone))
    line = left_out_text(left_out, more)
    if line:
        texts["more"] = line
    minutes = {}
    for item in (everyone if everyone is not None else kept):
        minutes[minute_of(item["at"])] = minutes.get(minute_of(item["at"]), 0) + 1

    def key_of(target):
        """What names the corrected update: its id, else its minute if no other update shares it."""
        if target["id"] is not None:
            return ("id", target["id"])
        return ("minute", minute_of(target["at"])) if minutes.get(minute_of(target["at"]), 0) == 1 else None

    corrected_by = {}  # the corrected update's key -> the time of the earliest correction of it
    for item in kept:
        if isinstance(item["corrects"], dict):
            key = key_of(item["corrects"])
            if key is not None and key != key_of({"id": item["id"], "at": item["at"]}):
                corrected_by.setdefault(key, item["at"])

    def stamp(moment):
        return "%s, %s" % (date_text(moment, zone, with_year), time_text(moment, zone))

    for row, item in enumerate(kept, start=1):
        texts["when%d" % row] = date_text(item["at"], zone, with_year) + "\n" + time_text(item["at"], zone)
        corrects, later = item["corrects"], corrected_by.get(key_of({"id": item["id"], "at": item["at"]}))
        texts["what%d" % row] = item["headline"] if corrects is None else plain_correction(item["headline"])
        marks = []
        if corrects is UNKNOWN_TARGET:
            marks.append("Correction")
        elif corrects is not None:
            marks.append(("Corrects the %s update" if later is None else "Corrects %s") % stamp(corrects["at"]))
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
        epilog="Example: uv run scripts/timeline_card.py --items updates.json --title \"Story title\" --out card.png",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--items", help="the updates call's answer, saved as a file and passed on unchanged")
    source.add_argument("--brief", help="the story's brief (its ## Timeline lines are read)")
    parser.add_argument("--out", required=True, help="the card to write: a .png, .jpg or .webp (never an input)")
    parser.add_argument("--tz", default=DEFAULT_ZONE, help="the time zone to show, such as UTC or +05:30 (default Asia/Kolkata)")
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
    folder = os.path.dirname(out)
    if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
        raise InputError("the folder for --out, %s, doesn't exist or can't be written to" % folder)
    zone = parse_zone(args.tz)
    title, earlier, more = None, 0, False
    if args.brief:
        title, items, earlier = parse_brief(read_text(args.brief, "the brief"))
    else:
        try:
            items, more = read_items(json.loads(read_text(args.items, "the items file")))
        except ValueError as error:
            raise InputError("the items file isn't valid JSON: %s" % error)
    title = args.title or title or "The story so far"
    kept, left_out = select(items, args.max_items)
    left_out += earlier
    texts, groups = build_texts(kept, left_out, title, zone, more=more, everyone=items)
    return kept, left_out, texts, groups, zone, out


def main(argv=None):
    args = make_parser().parse_args(argv)
    try:
        kept, left_out, texts, groups, zone, out = run(args)
    except InputError as error:
        log("timeline_card.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    except NoZoneData as error:
        log("timeline_card.py: %s" % error)
        return finish(False, [], [], str(error), 3)
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
