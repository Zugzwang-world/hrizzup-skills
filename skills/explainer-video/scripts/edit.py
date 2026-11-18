# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["pillow==13.0.0", "fonttools==4.68.0", "imageio-ffmpeg==0.8.1"]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""Edit a video: scenes (pictures with gentle motion, or clips) over a narration, with captions burned in.

A plan is JSON: {"scenes": [...], "transition": "cut" or "fade"}. A scene is either a picture or a clip:

    {"image": "cards/01-title.png", "seconds": 7.5, "motion": "zoom-in", "focus": [0.5, 0.4], "fit": "cover", "text": "..."}
    {"clip": "river.mp4", "trim": [2.0, 6.5], "text": "..."}

    image    a PNG, JPEG or WebP; its path is relative to the plan's folder. "fit" is "contain" (the picture shown whole, on the
             style's paper, in the top four fifths: the bottom fifth is left for the captions) or "cover" (it fills the
             1080 x 1920 frame, cropped around "focus"). Left out, it is "cover" for a picture of the frame's own 9:16 shape
             and "contain" for any other, so a picture's words are never cut off unless you ask for it.
    clip     an MP4 with a video track (checked from its own bytes: a file that only looks like one is refused, exit 2): scaled
             to cover the frame, cut to 30 frames a second, its sound dropped. "trim" is [in, out] in seconds, and nothing past
             `out` is read; "seconds" makes the scene shorter, or longer by holding the clip's last frame.
    seconds  how long the scene lasts. The last scene takes whatever is left of the narration (at least 1 second must be).
    motion   still (default), zoom-in, zoom-out, pan-left, pan-right, pan-up or pan-down: a slow move with eased starts. It
             never takes the middle of the picture (where the cards put their words) out of the frame, under the signature
             or into the captions: a zoom stops at about 1.11 times and a pan is made at a smaller zoom to fit its travel.
    focus    [x, y], fractions of the picture, where a zoom heads and a pan is centred (default [0.5, 0.5]), as far as
             that safe middle allows.
    text     a short line shown at the top of the scene (at most 80 characters).

Each frame is drawn here (Pillow), with the scene's text, the current caption and the style's signature on top, and
FFmpeg only encodes it with the narration copied in, as Hrizzup's video (H.264, 1080 x 1920, 30 frames a second).
The captions are `captions.py`'s captions.json. The narration is an .m4a made by `voice.py`, at most 58.0 seconds.

The last line it prints is one JSON object: {"ok", "outputs", "checks", "problem"}. Exit codes: 0 made and checked; 1 the
video failed a Hrizzup limit or quality check (nothing is left behind); 2 bad input (a plan that breaks a rule, with the
rule named; a narration over 58.0 seconds; a character the font can't draw); 3 a missing package, tool or kit file.
A mistake in this command itself still ends in the JSON line, with exit 1.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time

import hrizzup_media

FRAME = hrizzup_media.VIDEO_SIZE  # 1080 x 1920
FPS = hrizzup_media.VIDEO_FPS  # 30
MOTIONS = ("still", "zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down")
TRANSITIONS = ("cut", "fade")
FITS = ("cover", "contain")
PRESCALE = 1.25  # a picture is scaled to 1.25 times what covers the frame, then a box of it is resampled to the frame
ZOOM_MAX = 1.12  # a zoom goes from 1.00 towards 1.12 times, and stops where the safe area (below) needs
PAN_ZOOM = 1.10  # a pan is made at 1.10 times, or at less where the safe area needs
PAN_TRAVEL_X = 0.06  # and moves 6% of the picture's width sideways
PAN_TRAVEL_Y = 0.08  # or 8% of its height up or down
# What a moving picture must keep in view (fractions of the picture, which at rest are fractions of the frame): where the cards'
# templates put their words, and where those words may land in the frame while it moves: a little in from the sides, below the
# signature's pill and above the captions. `tools/test_edit.py` checks every motion and focus against them.
SAFE_AREA = (0.06, 0.14, 0.94, 0.78)
KEEP_CLEAR = (0.01, 0.07, 0.99, 0.835)
FRAME_ASPECT = hrizzup_media.VIDEO_SIZE[0] / hrizzup_media.VIDEO_SIZE[1]  # a picture of this shape (9:16) fills the frame
ASPECT_TOLERANCE = 0.03
FADE_SECONDS = 0.5  # a fade between scenes lasts this long, centred on the cut
MIN_LAST_SCENE = 1.0  # the last scene takes what is left of the narration: at least this long
MAX_SCENES = 40
MAX_TEXT = 80
CONTAIN_BOTTOM = 0.8125  # a picture shown whole sits in the top part of the frame: 1560 of 1920 px
CAPTION_BOTTOM = 1760  # the last line of a caption ends here
CAPTION_SIZES = (56, 34)  # the largest and the smallest size of caption text
SIDE_MARGIN = 80
STILL_AT_DEFAULT = 1.0
PROGRESS_EVERY = 300  # frames


class InputError(Exception):
    """The input is wrong (exit 2)."""


class CheckError(Exception):
    """The video was made but breaks a limit or a quality rule (exit 1)."""


# ---------------------------------------------------------------------------------------------
# Reading the plan (standard library only)
# ---------------------------------------------------------------------------------------------

def number(value, what, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError("%s must be a number" % what)
    if (low is not None and value < low) or (high is not None and value > high):
        raise InputError("%s must be %s" % (what, " to ".join(str(v) for v in (low, high) if v is not None) if high is not None else "at least %s" % low))
    return float(value)


def read_plan(path):
    """The plan: {"scenes": [scene dicts], "transition"}. Each scene has "kind" (image or clip), "path" (absolute, checked to
    be a file), "trim", "seconds", "motion", "focus", "fit" and "text". Raises InputError naming the scene and the rule."""
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, UnicodeDecodeError) as error:
        raise InputError("can't read the plan %s: %s" % (path, error))
    except ValueError as error:
        raise InputError("the plan %s isn't valid JSON: %s" % (path, error))
    if not isinstance(document, dict) or not set(document) <= {"scenes", "transition"} or "scenes" not in document:
        raise InputError('a plan is {"scenes": [ ... ], "transition": "cut" or "fade"}')
    transition = document.get("transition", "cut")
    if transition not in TRANSITIONS:
        raise InputError('"transition" is cut or fade')
    scenes = document["scenes"]
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise InputError("a plan has 1 to %d scenes" % MAX_SCENES)
    folder = os.path.dirname(os.path.abspath(path))
    found = []
    for position, scene in enumerate(scenes, 1):
        where = "scene %d" % position
        allowed = {"image", "clip", "trim", "seconds", "motion", "focus", "text", "fit"}
        if not isinstance(scene, dict) or not set(scene) <= allowed:
            raise InputError("%s: a scene has only these keys: %s" % (where, ", ".join(sorted(allowed))))
        if ("image" in scene) == ("clip" in scene):
            raise InputError('%s: give "image" or "clip", one of them' % where)
        kind = "image" if "image" in scene else "clip"
        name = scene[kind]
        if not isinstance(name, str) or not name or any(part in ("", ".", "..") for part in re.split(r"[\\/]", name)) or os.path.isabs(name):
            raise InputError('%s: "%s" is a path inside the plan\'s folder, like cards/01-title.png (no .. and not absolute)' % (where, kind))
        full = os.path.join(folder, name)
        if not os.path.isfile(full):
            raise InputError("%s: %s isn't a file (paths are relative to the plan's folder)" % (where, name))
        if kind == "clip":
            refused = hrizzup_media.clip_problems(full)  # read from its own bytes, never by FFmpeg: a playlist renamed .mp4 is refused here
            if refused:
                raise InputError("%s: the clip %s %s: a clip is an MP4 with a video track" % (where, name, refused[0]))
        motion = scene.get("motion", "still")
        if motion not in MOTIONS:
            raise InputError("%s: \"motion\" is one of %s" % (where, ", ".join(MOTIONS)))
        if kind == "clip" and motion != "still":
            raise InputError("%s: a clip has no motion of its own to add; leave \"motion\" out" % where)
        fit = scene.get("fit")
        if (fit is not None and fit not in FITS) or (kind == "clip" and "fit" in scene):
            raise InputError('%s: "fit" is cover or contain, and only for an image' % where)
        if fit is None:
            fit = "cover"
            if kind == "image":  # a picture that isn't the frame's own shape is shown whole unless the plan says "cover"
                try:
                    shape = hrizzup_media.inspect(full)
                except (hrizzup_media.MediaError, OSError) as error:
                    raise InputError("%s: can't read the picture %s: %s" % (where, name, error))
                fit = default_fit(shape.width, shape.height)
        focus = scene.get("focus", [0.5, 0.5])
        if not (isinstance(focus, list) and len(focus) == 2):
            raise InputError('%s: "focus" is [x, y], two fractions from 0 to 1' % where)
        focus = (number(focus[0], where + " focus x", 0, 1), number(focus[1], where + " focus y", 0, 1))
        trim = None
        if "trim" in scene:
            if kind != "clip" or not (isinstance(scene["trim"], list) and len(scene["trim"]) == 2):
                raise InputError('%s: "trim" is [in, out] seconds, for a clip' % where)
            low, high = number(scene["trim"][0], where + " trim in", 0), number(scene["trim"][1], where + " trim out", 0)
            if high <= low:
                raise InputError('%s: "trim" out must be after in' % where)
            trim = (low, high)
        seconds = scene.get("seconds")
        if seconds is None:
            if trim is None:
                raise InputError('%s: "seconds" is needed (or, for a clip, "trim")' % where)
            seconds = trim[1] - trim[0]
        seconds = number(seconds, where + " seconds", 0.2)
        text = scene.get("text")
        if text is not None:
            if not isinstance(text, str) or not text.strip() or len(" ".join(text.split())) > MAX_TEXT or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in text):
                raise InputError('%s: "text" is one short line, 1 to %d characters' % (where, MAX_TEXT))
            text = " ".join(text.split())
        found.append({"kind": kind, "path": full, "trim": trim, "seconds": seconds, "motion": motion, "focus": focus, "fit": fit, "text": text})
    return {"scenes": found, "transition": transition}


def default_fit(width, height):
    """The `fit` of a picture when the plan doesn't say: "cover" for the frame's own 9:16 shape (within 3%), "contain" for any other."""
    return "cover" if abs(width / float(height) - FRAME_ASPECT) <= ASPECT_TOLERANCE else "contain"


def schedule(scenes, narration_seconds, fps=FPS):
    """(frames per scene, the frame each scene starts at, total frames) for a narration of `narration_seconds`. Every scene but the
    last lasts its own `seconds`; the last takes the rest, and must keep at least 1 second."""
    total = max(1, int(math.ceil(narration_seconds * fps - 1e-9)))
    before = sum(s["seconds"] for s in scenes[:-1])
    left = narration_seconds - before
    if left < MIN_LAST_SCENE:
        raise InputError("the scenes before the last add up to %.1f s, which leaves %.1f s of the %.1f s narration for the last scene; "
                         "it needs at least %.1f s: shorten the earlier scenes" % (before, max(left, 0.0), narration_seconds, MIN_LAST_SCENE))
    starts, edge = [], 0.0
    for scene in scenes[:-1]:
        starts.append(int(round(edge * fps)))
        edge += scene["seconds"]
    starts.append(int(round(edge * fps)))
    counts = [starts[k + 1] - starts[k] for k in range(len(scenes) - 1)] + [total - starts[-1]]
    if min(counts) < 1:
        raise InputError("a scene is shorter than one frame")
    return counts, starts, total


def ease(t):
    """Smoothstep: 0 to 1 with a soft start and end."""
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def zoom_limit(extra_x=0.0, extra_y=0.0):
    """The largest zoom at which the safe area, moved by `extra_x` and `extra_y` (a pan's travel, as fractions of the picture), still
    fits between the keep-clear lines of the frame."""
    across = (KEEP_CLEAR[2] - KEEP_CLEAR[0]) / (SAFE_AREA[2] - SAFE_AREA[0] + extra_x)
    down = (KEEP_CLEAR[3] - KEEP_CLEAR[1]) / (SAFE_AREA[3] - SAFE_AREA[1] + extra_y)
    return min(across, down)


def _place(wanted, size_fraction, axis):
    """Where a box of `size_fraction` of the picture starts along an axis (0 for x, 1 for y), as near `wanted` as keeps the
    safe area clear of the frame's keep-clear lines and the box inside the picture."""
    low = max(SAFE_AREA[2 + axis] - KEEP_CLEAR[2 + axis] * size_fraction, 0.0)
    high = min(SAFE_AREA[axis] - KEEP_CLEAR[axis] * size_fraction, 1.0 - size_fraction)
    if low > high:  # only the rounding of a zoom at its limit
        return (low + high) / 2.0, (low + high) / 2.0, (low + high) / 2.0
    return _clamp(wanted, low, high), low, high


def motion_box(motion, progress, size, focus):
    """The part of a picture (its box, in pixels of the pre-scaled picture of `size`) the frame shows at `progress` (0 to 1)
    through a scene: a zoom heads to the focus, a pan moves along its axis. The box is always inside the picture, and always keeps
    the picture's safe area (SAFE_AREA) inside the frame, below the signature and above the captions: a zoom stops at its limit,
    a pan is made at a zoom small enough for its travel, and the focus gives way where it would push the words out."""
    width, height = size
    shown = ease(progress)
    if motion == "still":
        return 0.0, 0.0, float(width), float(height)
    horizontal = motion in ("pan-left", "pan-right")
    if motion in ("zoom-in", "zoom-out"):
        amount = shown if motion == "zoom-in" else 1.0 - shown
        zoom = min(1.0 + (ZOOM_MAX - 1.0) * amount, zoom_limit())
    elif horizontal:
        zoom = min(PAN_ZOOM, zoom_limit(extra_x=PAN_TRAVEL_X))
    else:
        zoom = min(PAN_ZOOM, zoom_limit(extra_y=PAN_TRAVEL_Y))
    box_w, box_h = 1.0 / zoom, 1.0 / zoom  # as fractions of the picture
    x0, x_low, x_high = _place(focus[0] - box_w / 2, box_w, 0)
    y0, y_low, y_high = _place(focus[1] - box_h / 2, box_h, 1)
    if motion.startswith("pan-"):
        forward = motion in ("pan-right", "pan-down")
        travel = PAN_TRAVEL_X if horizontal else PAN_TRAVEL_Y
        low, high, base = (x_low, x_high, x0) if horizontal else (y_low, y_high, y0)
        if high - low >= travel:
            begin = _clamp(base - travel / 2.0, low, high - travel)
            end = begin + travel
        else:
            begin, end = low, high
        if not forward:
            begin, end = end, begin
        moved = begin + (end - begin) * shown
        if horizontal:
            x0 = moved
        else:
            y0 = moved
    return x0 * width, y0 * height, (x0 + box_w) * width, (y0 + box_h) * height


def _clamp(value, low, high):
    return max(low, min(high, value))


def _rgb(colour):
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def read_captions(path, seconds):
    """The cues of a captions.json: [{"start", "end", "lines"}] in order, inside the narration. Raises InputError."""
    try:
        with open(path, encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, UnicodeDecodeError) as error:
        raise InputError("can't read the captions %s: %s" % (path, error))
    except ValueError as error:
        raise InputError("the captions %s aren't valid JSON: %s" % (path, error))
    cues = document.get("cues") if isinstance(document, dict) else None
    if not isinstance(cues, list):
        raise InputError("the captions file is captions.py's output: it holds a list of \"cues\"")
    found, previous = [], 0.0
    for position, cue in enumerate(cues, 1):
        where = "caption cue %d" % position
        if not isinstance(cue, dict) or not isinstance(cue.get("lines"), list) or not 1 <= len(cue["lines"]) <= 2 \
                or not all(isinstance(line, str) and line.strip() and len(line) <= 60 for line in cue["lines"]):
            raise InputError("%s: \"lines\" is one or two short lines of text" % where)
        start, end = number(cue.get("start"), where + " start", 0), number(cue.get("end"), where + " end", 0)
        if end <= start or start < previous - 1e-6:
            raise InputError("%s: cues run in order, each ending after it starts" % where)
        if start > seconds + 0.5:
            raise InputError("%s starts at %.1f s, after the %.1f s narration: are these the captions of another narration?" % (where, start, seconds))
        found.append({"start": start, "end": min(end, seconds), "lines": [line.strip() for line in cue["lines"]]})
        previous = end
    return found


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
        prog="edit.py",
        description="Edit scenes (pictures with gentle motion, or clips) over a narration, with captions burned in: Hrizzup's video, 1080 x 1920.",
        epilog="Example: uv run scripts/edit.py --plan plan.json --narration narration.m4a --captions captions.json --out explainer.mp4",
    )
    parser.add_argument("--plan", required=True, help="the plan: JSON, {\"scenes\": [...], \"transition\": \"cut\" or \"fade\"}")
    parser.add_argument("--narration", required=True, help="the narration: an .m4a made by voice.py, at most %.1f seconds" % hrizzup_media.VIDEO_MAX_SECONDS)
    parser.add_argument("--captions", required=True, help="the captions: captions.json made by captions.py")
    parser.add_argument("--out", required=True, help="the video to write: an .mp4 (never an input)")
    parser.add_argument("--still", help="also save one frame of the video, with no caption on it, as a still image: a .png, .jpg or .webp")
    parser.add_argument("--still-at", type=float, default=STILL_AT_DEFAULT, help="the time of that frame, in seconds (default %.1f)" % STILL_AT_DEFAULT)
    parser.add_argument("--style", help="a style file: JSON, or a markdown file with a json block (default plain)")
    return parser


def check_arguments(args):
    out = os.path.abspath(args.out)
    still = os.path.abspath(args.still) if args.still else None
    if os.path.splitext(out)[1].lower() != ".mp4":
        raise InputError("--out is an .mp4 file")
    if still and os.path.splitext(still)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise InputError("--still is a .png, .jpg or .webp file")
    if args.still_at < 0:
        raise InputError("--still-at is a time in seconds, 0 or more")
    for name, path in (("--plan", args.plan), ("--narration", args.narration), ("--captions", args.captions)):
        if not os.path.isfile(path):
            raise InputError("can't read %s %s: it isn't a file" % (name, path))
    for target in (out, still):
        if not target:
            continue
        for given in (args.plan, args.narration, args.captions, args.style):
            if given and hrizzup_media.same_file(given, target):
                raise InputError("%s would overwrite %s, an input" % (os.path.basename(target), given))
        folder = os.path.dirname(target)
        if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
            raise InputError("the folder for %s doesn't exist or can't be written to" % target)
    if still and hrizzup_media.same_file(out, still):
        raise InputError("--out and --still are the same file")
    return out, still


# ---------------------------------------------------------------------------------------------
# Drawing the frames
# ---------------------------------------------------------------------------------------------

class ImageScene:
    """A picture as a scene: the frame at any point of its motion."""

    def __init__(self, scene, style, draw):
        self.scene, self.style, self.draw = scene, style, draw
        self._prepared = None
        self._still = None

    def _picture(self):
        return self.draw.flatten(self.draw.load_picture(self.scene["path"]), self.style["paper"])

    def _base(self, size):
        """The picture as a canvas of `size` with the frame's proportions: it fills it (cover, cropped around the focus) or sits
        whole in the top part of it on the style's paper (contain)."""
        from PIL import Image

        picture = self._picture()
        if self.scene["fit"] == "cover":
            return self.draw.cover_crop(picture, size, self.scene["focus"], self.style["paper"])
        area = (size[0], int(round(size[1] * CONTAIN_BOTTOM)))
        scale = min(area[0] / picture.width, area[1] / picture.height)
        shown = picture.resize((max(1, int(round(picture.width * scale))), max(1, int(round(picture.height * scale)))), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, _rgb(self.style["paper"]))
        canvas.paste(shown, ((size[0] - shown.width) // 2, (area[1] - shown.height) // 2))
        return canvas

    def frame(self, index, count):
        from PIL import Image

        if self.scene["motion"] == "still":
            if self._still is None:
                self._still = self._base(FRAME)
            return self._still.copy()
        if self._prepared is None:
            self._prepared = self._base((int(round(FRAME[0] * PRESCALE)), int(round(FRAME[1] * PRESCALE))))
        progress = _clamp(index / max(1, count - 1), 0.0, 1.0)
        box = motion_box(self.scene["motion"], progress, self._prepared.size, self.scene["focus"])
        return self._prepared.resize(FRAME, Image.Resampling.BICUBIC, box=box)

    def is_still(self):
        return self.scene["motion"] == "still"

    def release(self):
        self._prepared = None


class ClipScene:
    """A clip as a scene: its frames in order, the first held before it starts and the last held after it ends."""

    def __init__(self, scene, ff):
        self.scene, self.ff = scene, ff
        self._iterator = None
        self._position = -1
        self._current = None

    def frame(self, index, count):
        wanted = _clamp(index, 0, count - 1)
        if self._iterator is None:
            start, length = None, self.scene["seconds"]
            if self.scene["trim"]:
                start = self.scene["trim"][0]
                length = min(length, self.scene["trim"][1] - self.scene["trim"][0])  # never read past `out`; a longer scene holds the last frame
            self._iterator = hrizzup_media.decode_clip(self.ff, self.scene["path"], FRAME[0], FRAME[1], FPS, start, length)
        while self._position < wanted:
            data = next(self._iterator, None)
            if data is None:
                if self._current is None:
                    raise InputError("the clip %s has no picture to read" % os.path.basename(self.scene["path"]))
                self._position = wanted  # the clip is shorter than its scene: its last frame is held
                break
            from PIL import Image

            self._current = Image.frombytes("RGB", FRAME, data)
            self._position += 1
        return self._current.copy()

    def is_still(self):
        return False

    def release(self):
        if self._iterator is not None:
            self._iterator.close()
            self._iterator = None


class Overlays:
    """What goes over every frame, drawn once: the signature, each scene's text and each caption cue."""

    def __init__(self, style, draw, cues, scenes):
        from PIL import Image, ImageDraw

        self.style, self.draw, self.Image, self.ImageDraw = style, draw, Image, ImageDraw
        self.signature = self._signature()
        self.texts = [self._scene_text(s["text"]) if s["text"] else None for s in scenes]
        self.size = self._caption_size(cues)
        self.cues = [self._cue(c["lines"]) for c in cues]

    def _outlined(self, lines, font, width, pad):
        """A transparent layer with centred white lines outlined in black; (layer, its height)."""
        stroke = max(1, round(font.size * self.draw.OUTLINE))
        step = self.draw.line_height(font.size)
        layer = self.Image.new("RGBA", (width, step * len(lines) + 2 * pad), (0, 0, 0, 0))
        pen = self.ImageDraw.Draw(layer)
        for number, line in enumerate(lines):
            x = (width - font.getlength(line)) / 2
            pen.text((x, pad + number * step), line, font=font, fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        return layer

    def _signature(self):
        text = self.style["signature"]
        if not text:
            return None
        fitted = self.draw.fit_text(text, "text-bold", self.style, (FRAME[0] - 2 * SIDE_MARGIN - 80, 60), 36, 20, 1, where="the signature")
        width, height = int(math.ceil(fitted.font.getlength(text))) + 48, fitted.height + 16
        layer = self.Image.new("RGBA", (width, height), (0, 0, 0, 0))
        pen = self.ImageDraw.Draw(layer)
        pen.rounded_rectangle((0, 0, width - 1, height - 1), radius=height // 2, fill=(0, 0, 0, 160))
        pen.text((24, 8), text, font=fitted.font, fill=(255, 255, 255, 255))
        return layer, ((FRAME[0] - width) // 2, 56)

    def _scene_text(self, text):
        fitted = self.draw.fit_text(text, "text-bold", self.style, (FRAME[0] - 2 * SIDE_MARGIN, 200), 64, 34, 2, outline=True, where="a scene's text")
        layer = self._outlined(fitted.lines, fitted.font, FRAME[0], 8)
        return layer, (0, 150)

    def _caption_size(self, cues):
        """One size for every caption: the largest from 56 down to 34 at which the widest line fits between the margins."""
        lines = [line for cue in cues for line in cue["lines"]]
        for line in lines:
            self.draw.check_glyphs(line, "text-bold", self.style, "a caption")
        for size in range(CAPTION_SIZES[0], CAPTION_SIZES[1] - 1, -1):
            font = self.draw.get_font("text-bold", size, self.style)
            stroke = max(1, round(size * self.draw.OUTLINE))
            if all(font.getlength(line) + 2 * stroke <= FRAME[0] - 2 * SIDE_MARGIN for line in lines):
                return size
        widest = max(lines, key=len)
        raise self.draw.DrawError("a caption line (%r, %d characters) is too wide at the smallest size, %d: the captions hold 32 characters a line"
                                  % (widest, len(widest), CAPTION_SIZES[1]), 1)

    def _cue(self, lines):
        font = self.draw.get_font("text-bold", self.size, self.style)
        layer = self._outlined(lines, font, FRAME[0], 6)
        return layer, (0, CAPTION_BOTTOM - layer.height + 6)

    def put(self, frame, scene_number, cue_number):
        """Draw the signature, the scene's text and (if there is a cue) the caption on `frame`."""
        for layer in (self.signature, self.texts[scene_number]):
            if layer:
                frame.paste(layer[0], layer[1], layer[0])
        if cue_number is not None:
            layer, position = self.cues[cue_number]
            frame.paste(layer, position, layer)


def cue_at(cues, seconds, hint):
    """The index of the cue showing at `seconds` (or None); `hint` is where the last search ended (the time only moves forward)."""
    index = hint
    while index < len(cues) and cues[index]["end"] <= seconds:
        index += 1
    if index < len(cues) and cues[index]["start"] <= seconds:
        return index, index
    return None, index


def scene_at(starts, frame):
    for number in range(len(starts) - 1, -1, -1):
        if frame >= starts[number]:
            return number
    return 0


def fade_window(starts, frame, transition):
    """(previous scene, next scene, how far through the fade, 0 to 1) when `frame` is inside a fade, else None."""
    if transition != "fade" or len(starts) < 2:
        return None
    half = max(1, int(round(FADE_SECONDS * FPS / 2)))
    for number in range(1, len(starts)):
        low, high = starts[number] - half, starts[number] + half
        if low <= frame < high:
            return number - 1, number, (frame - low + 0.5) / (high - low)
    return None


# ---------------------------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------------------------

def main(argv=None):
    """Make the video; whatever goes wrong, the last line printed is the JSON line."""
    try:
        return make(argv)
    except ImportError as error:  # a package turned out to be missing deep inside a call
        message = ("a Python package or module is missing (%s): get the kit again and install its packages with `uv run scripts/edit.py`, "
                   "or `.venv/bin/python -m pip install --require-hashes -r scripts/edit.requirements.txt`" % error)
        log("edit.py: " + message)
        return finish(False, [], [], message, 3)
    except hrizzup_media.FfmpegError as error:
        log("edit.py: %s" % error)
        return finish(False, [], [], str(error), error.code)
    except Exception as error:  # the last resort: a mistake in this command, never a bare traceback
        message = "edit.py failed unexpectedly (%s: %s): this is a mistake in the kit, so tell your owner" % (type(error).__name__, error)
        log("edit.py: " + message)
        return finish(False, [], [], message, 1)


def make(argv=None):
    try:
        args = make_parser().parse_args(argv)
        out, still = check_arguments(args)
        plan = read_plan(args.plan)
        try:
            narration = hrizzup_media.inspect(args.narration)
        except hrizzup_media.MediaError as error:
            raise InputError("the narration %s can't be read as an .m4a or .mp4: %s" % (args.narration, error))
        except OSError as error:
            raise InputError("can't read the narration %s: %s" % (args.narration, error))
        if narration.audio_codec != "mp4a":
            raise InputError("the narration must be AAC in an .m4a (voice.py makes one): it is copied into the video as it is")
        if narration.seconds > hrizzup_media.VIDEO_MAX_SECONDS:
            raise InputError("the narration is %.1f s; a video is at most %.1f s (Hrizzup allows 60): cut the script and run voice.py again"
                             % (narration.seconds, hrizzup_media.VIDEO_MAX_SECONDS))
        cues = read_captions(args.captions, narration.seconds)
        counts, starts, total = schedule(plan["scenes"], narration.seconds)
        if still and args.still_at >= total / FPS:
            raise InputError("--still-at %.1f is after the end of the %.1f s video" % (args.still_at, total / FPS))
    except InputError as error:
        log("edit.py: %s" % error)
        return finish(False, [], [], str(error), 2)
    try:
        import hrizzup_draw
    except ImportError as error:
        message = ("a Python package is missing (%s): run this with `uv run scripts/edit.py`, which installs them, or make a virtual "
                   "environment and install the exact set: `python3.12 -m venv .venv`, `.venv/bin/python -m pip install --require-hashes "
                   "-r scripts/edit.requirements.txt`, then `.venv/bin/python scripts/edit.py ...`" % error)
        log("edit.py: " + message)
        return finish(False, [], [], message, 3)
    ff = hrizzup_media.find_ffmpeg()
    log("edit.py: " + ff.describe())
    part = out[:-4] + ".part.mp4"
    try:
        style = hrizzup_draw.load_style(args.style)
        overlays = Overlays(style, hrizzup_draw, cues, plan["scenes"])
        scenes = [ImageScene(s, style, hrizzup_draw) if s["kind"] == "image" else ClipScene(s, ff) for s in plan["scenes"]]
        began = time.time()
        still_frame = render(plan, scenes, overlays, counts, starts, total, narration.seconds, cues, args.narration, part, ff,
                             args.still_at if still else None)
    except (InputError, hrizzup_draw.DrawError) as error:
        _remove(part)
        log("edit.py: %s" % error)
        return finish(False, [], [], str(error), 2 if isinstance(error, InputError) else error.code)
    except BaseException:
        _remove(part)
        raise
    log("edit.py: %d frames drawn and encoded in %.0f s" % (total, time.time() - began))
    problems, checks = check_video(part, narration.seconds)
    if still_frame is not None:
        written_still = hrizzup_draw.save_image(still_frame, still)
    if problems:
        _remove(part)
        if still_frame is not None:
            _remove(written_still)
        message = "; ".join(problems)
        log("edit.py: the video failed its checks: " + message)
        return finish(False, [], checks, message, 1)
    os.replace(part, out)
    info = hrizzup_media.inspect(out)
    outputs = [{"path": args.out if not os.path.isabs(args.out) else out, "bytes": info.bytes, "width": info.width, "height": info.height,
                "seconds": round(info.seconds, 3)}]
    if still_frame is not None:
        pic = hrizzup_media.inspect(written_still)
        outputs.append({"path": args.still if not os.path.isabs(args.still) else written_still, "bytes": pic.bytes, "width": pic.width,
                        "height": pic.height, "seconds": None})
    log("edit.py: %.2f s, %d bytes, %dx%d" % (info.seconds, info.bytes, info.width, info.height))
    return finish(True, outputs, checks, None, 0)


def render(plan, scenes, overlays, counts, starts, total, narration_seconds, cues, narration, part, ff, still_at):
    """Draw every frame and give it to the encoder. Returns the frame saved for --still (without its caption), or None."""
    from PIL import Image

    still_index = int(round(still_at * FPS)) if still_at is not None else None
    still_frame = None
    cached = {}  # a picture scene that doesn't move draws the same frame until its caption changes
    hint = 0
    with hrizzup_media.encode_video(ff, part, FRAME[0], FRAME[1], FPS, audio=narration) as encoder:
        for frame_number in range(total):
            seconds = frame_number / FPS
            cue, hint = cue_at(cues, seconds, hint)
            fade = fade_window(starts, frame_number, plan["transition"])
            number = scene_at(starts, frame_number)
            key = None
            if fade is None and scenes[number].is_still() and frame_number != still_index:
                key = (number, cue)
                if key in cached:
                    encoder.write(cached[key])
                    continue
            if fade is None:
                picture = scenes[number].frame(frame_number - starts[number], counts[number])
                shown = number
            else:
                before, after, amount = fade
                one = scenes[before].frame(frame_number - starts[before], counts[before])
                two = scenes[after].frame(frame_number - starts[after], counts[after])
                picture = Image.blend(one, two, ease(amount))
                shown = after if amount >= 0.5 else before
            if still_index is not None and frame_number == still_index:
                bare = picture.copy()
                overlays.put(bare, shown, None)
                still_frame = bare
            overlays.put(picture, shown, cue)
            data = picture.tobytes()
            if key is not None:
                cached = {k: v for k, v in cached.items() if k[0] == number}  # only the current scene's frames are kept
                cached[key] = data
            encoder.write(data)
            if number > 1:
                scenes[number - 2].release()
            if frame_number and frame_number % PROGRESS_EVERY == 0:
                log("edit.py: %d of %d frames" % (frame_number, total))
        for scene in scenes:
            scene.release()
    return still_frame


def check_video(path, narration_seconds):
    """(problems, checks) for the finished video against Hrizzup's limits (design 9) and the narration's length."""
    try:
        info = hrizzup_media.inspect(path)
    except hrizzup_media.MediaError as error:
        return ["the video can't be read back: %s" % error], [{"name": "the video can be read back", "ok": False}]
    limits = hrizzup_media.problems(info, "video", budget=False)
    slack = abs(info.seconds - narration_seconds)
    in_step = slack <= 2.0 / FPS + 0.05
    found = list(limits)
    if not in_step:
        found.append("the video is %.2f s and the narration %.2f s: they should end together" % (info.seconds, narration_seconds))
    return found, [{"name": "Hrizzup's video limits", "ok": not limits}, {"name": "the video ends with its narration", "ok": in_step}]


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
