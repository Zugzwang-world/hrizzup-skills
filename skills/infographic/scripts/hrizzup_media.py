"""Hrizzup's media limits, readers for the files a skill makes, and the only place FFmpeg is run. Standard library only.

This is a module, not a command: scripts import it as a sibling. It reads PNG, JPEG and WebP
pictures and MP4 and M4A files straight from their bytes (no FFmpeg, no packages), so a check
can say what a file is, and whether Hrizzup's limits and this repository's budgets hold, on any
machine. The limits are the ones in `references/sizes.md`, and Hrizzup's format guide
(`social.formats`) is the authority if they ever differ.

    from hrizzup_media import inspect, problems
    info = inspect("meme.png")             # MediaError if it isn't what its name says
    print(problems(info, "image"))         # [] when it fits

FFmpeg runs only through the builders at the end (`find_ffmpeg`, `encode_video`, `decode_clip`, `loudnorm_measure`,
`loudnorm_apply`): each makes its argument list first (`*_args`), and `ffmpeg_args_problems` refuses a list that
asks for more than the allowlist. Nothing else in this repository imports `subprocess` or `imageio_ffmpeg`.
"""

from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from typing import BinaryIO, Iterable, Iterator, Optional

# ---- Hrizzup's limits (shared/references/sizes.md) ----
MIB = 1024 * 1024
IMAGE_MAX_BYTES = 10 * MIB  # 10,485,760
IMAGE_MAX_SIDE = 4096
VIDEO_MAX_BYTES = 100 * MIB  # 104,857,600 (Hrizzup's limit)
VIDEO_MAX_SECONDS = 58.0  # Hrizzup allows 60
VIDEO_SIZE = (1080, 1920)
AUDIO_MAX_BYTES = 20 * MIB  # 20,971,520
AUDIO_MAX_SECONDS = 295.0  # Hrizzup allows 300
AUDIO_BRAND = "M4A "
LOUDNESS_LUFS = -16.0  # -17 to -15 accepted
LOUDNESS_TOLERANCE = 1.0
TRUE_PEAK_TARGET_DBTP = -1.5  # -1.0 at most
TRUE_PEAK_MAX_DBTP = -1.0
LOUDNESS_RANGE = 11
CAPTION_MAX = 1000  # a media post's body
TEXT_POST_MAX = 5000
SOURCES_MAX = 10
DESCRIPTION_MAX = 1000
TRANSCRIPT_MAX = 20000
# This repository's budgets for its samples (design 6).
IMAGE_BUDGET_BYTES = 2 * MIB
AUDIO_BUDGET_BYTES = 5 * MIB
VIDEO_BUDGET_BYTES = 25 * MIB

# ---- the pictures a command reads: a creator's own picture or chart (not Hrizzup's limits; what a command accepts) ----
PICTURE_INPUT_MAX_BYTES = 25 * MIB  # a picture file read
PICTURE_INPUT_MAX_PIXELS = 40_000_000  # 40 megapixels, counted from the header before any pixel is decoded
PICTURE_INPUT_MAX_SIDE = 8192

# ---- FFmpeg's allowlist (design 5): what the builders may ask for ----
FFMPEG_FILTERS = ("loudnorm", "aresample", "scale", "crop", "fps", "format", "setsar")
FFMPEG_ENCODERS = ("libx264", "h264_videotoolbox", "libopenh264", "aac", "pcm_s16le")
FFMPEG_FORMATS = ("rawvideo", "mp4", "ipod", "wav", "null")  # what a command may write
# What a command may read, each named on the command line before its `-i` (FFmpeg's MP4 demuxer is `mov`: it reads MP4 and M4A), so
# FFmpeg never guesses a file's kind from its content, and nothing a clip contains (a playlist, a concat file) is followed to another
# file or to the network: only `file` and `pipe` may be opened.
FFMPEG_INPUT_FORMATS = ("mov", "rawvideo", "wav")
FFMPEG_PROTOCOLS = "file,pipe"

_EXTENSION_KIND = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}


class MediaError(Exception):
    """A file isn't what its name says, or is damaged. The message says what to fix."""


@dataclass(frozen=True)
class MediaInfo:
    kind: str  # png, jpeg, webp, mp4 or m4a
    bytes: int
    width: Optional[int] = None  # pictures and video
    height: Optional[int] = None
    seconds: Optional[float] = None  # video and audio
    brand: Optional[str] = None  # the ftyp major brand
    video_codec: Optional[str] = None  # a sample entry's four letters: avc1
    audio_codec: Optional[str] = None  # mp4a
    faststart: Optional[bool] = None  # moov before mdat


# ---------------------------------------------------------------------------------------------
# Pictures
# ---------------------------------------------------------------------------------------------

def image_size(data: bytes) -> "tuple[str, int, int]":
    """(kind, width, height) of a PNG, JPEG or WebP, read from its own header."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ("png",) + _png_size(data)
    if data[:2] == b"\xff\xd8":
        return ("jpeg",) + _jpeg_size(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ("webp",) + _webp_size(data)
    raise MediaError("not a PNG, JPEG or WebP picture")


def _png_size(data: bytes) -> "tuple[int, int]":
    # 8 signature bytes, then the IHDR chunk: length 13, "IHDR", width, height (big-endian).
    if len(data) < 24 or data[12:16] != b"IHDR" or struct.unpack(">I", data[8:12])[0] != 13:
        raise MediaError("PNG without its IHDR chunk first")
    width, height = struct.unpack(">II", data[16:24])
    return _positive(width, height)


def _jpeg_size(data: bytes) -> "tuple[int, int]":
    # Segments are 0xFF, a marker byte, then a two-byte length (which counts itself). The size
    # is in the first start-of-frame marker: 0xC0 to 0xCF, but not 0xC4 (DHT), 0xC8 or 0xCC.
    i, n = 2, len(data)
    while i < n:
        if data[i] != 0xFF:
            raise MediaError("JPEG damaged: no marker where one belongs")
        while i < n and data[i] == 0xFF:  # fill bytes
            i += 1
        if i >= n:
            break
        marker = data[i]
        i += 1
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            continue  # no length
        if marker == 0xD9:
            break
        if i + 2 > n:
            break
        length = struct.unpack(">H", data[i:i + 2])[0]
        if length < 2:
            raise MediaError("JPEG damaged: a segment shorter than its own length")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if i + 7 > n:
                break
            height, width = struct.unpack(">HH", data[i + 3:i + 7])
            return _positive(width, height)
        if marker == 0xDA:
            break  # the picture's data starts and no frame header came first
        i += length
    raise MediaError("JPEG without a frame header, or cut short")


def _webp_size(data: bytes) -> "tuple[int, int]":
    # RIFF, size, "WEBP", then chunks: a four-letter name, a little-endian size, the payload.
    if len(data) < 20:
        raise MediaError("WebP cut short")
    chunk = data[12:16]
    body = data[20:]
    if chunk == b"VP8 ":  # lossy: 3-byte frame tag, start code 9d 01 2a, two 14-bit sizes
        if len(body) < 10 or body[3:6] != b"\x9d\x01\x2a":
            raise MediaError("WebP (VP8) without its start code")
        width, height = struct.unpack("<HH", body[6:10])
        return _positive(width & 0x3FFF, height & 0x3FFF)
    if chunk == b"VP8L":  # lossless: signature 0x2f, then two 14-bit sizes, each minus one
        if len(body) < 5 or body[0] != 0x2F:
            raise MediaError("WebP (VP8L) without its signature")
        bits = struct.unpack("<I", body[1:5])[0]
        return _positive((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    if chunk == b"VP8X":  # extended: flags, 3 reserved bytes, two 24-bit sizes, each minus one
        if len(body) < 10:
            raise MediaError("WebP (VP8X) cut short")
        width = int.from_bytes(body[4:7], "little") + 1
        height = int.from_bytes(body[7:10], "little") + 1
        return _positive(width, height)
    raise MediaError("WebP with no VP8, VP8L or VP8X chunk first")


def _positive(width: int, height: int) -> "tuple[int, int]":
    if width < 1 or height < 1:
        raise MediaError("a picture with no width or height")
    return width, height


# ---------------------------------------------------------------------------------------------
# MP4 and M4A: walking boxes
# ---------------------------------------------------------------------------------------------

def _boxes(data: bytes, start: int, end: int):
    """Yield (type, payload start, box end) for the boxes in data[start:end].

    A box is a 4-byte size, a 4-byte type, then its payload. Size 1 means a 64-bit size follows
    the type; size 0 means the box runs to the end of its parent. Anything that doesn't fit is
    refused, never guessed at.
    """
    i = start
    while i < end:
        if i + 8 > end:
            raise MediaError("MP4 cut short inside a box header")
        size, kind = struct.unpack(">I4s", data[i:i + 8])
        header = 8
        if size == 1:
            if i + 16 > end:
                raise MediaError("MP4 cut short inside a 64-bit box size")
            size = struct.unpack(">Q", data[i + 8:i + 16])[0]
            header = 16
        elif size == 0:
            size = end - i
        if size < header:
            raise MediaError("MP4 damaged: a box smaller than its own header")
        if i + size > end:
            raise MediaError("MP4 cut short: a %s box runs past the end" % kind.decode("latin-1"))
        yield kind, i + header, i + size
        i += size


def mp4_info(source: "str | os.PathLike[str] | BinaryIO") -> MediaInfo:
    """What an MP4 or M4A is: brand, duration, size, codecs and whether it starts quickly.

    Reads the top-level boxes by seeking past `mdat`, and parses `moov` in memory.
    """
    if hasattr(source, "read"):
        return _mp4_from_file(source)  # type: ignore[arg-type]
    with open(source, "rb") as f:  # type: ignore[arg-type]
        return _mp4_from_file(f)


def _mp4_from_file(f: BinaryIO) -> MediaInfo:
    f.seek(0, os.SEEK_END)
    total = f.tell()
    f.seek(0)
    brand: Optional[str] = None
    moov: Optional[bytes] = None
    order = []
    i = 0
    while i < total:
        f.seek(i)
        header = f.read(16)
        if len(header) < 8:
            raise MediaError("MP4 cut short inside a box header")
        size, kind = struct.unpack(">I4s", header[:8])
        head = 8
        if size == 1:
            if len(header) < 16:
                raise MediaError("MP4 cut short inside a 64-bit box size")
            size = struct.unpack(">Q", header[8:16])[0]
            head = 16
        elif size == 0:
            size = total - i
        if size < head:
            raise MediaError("MP4 damaged: a box smaller than its own header")
        if i + size > total:
            raise MediaError("MP4 cut short: a %s box runs past the end" % kind.decode("latin-1"))
        order.append(kind)
        if kind == b"ftyp" and brand is None:
            f.seek(i + head)
            major = f.read(4)
            if len(major) < 4:
                raise MediaError("MP4 cut short inside its ftyp box")
            brand = major.decode("latin-1")
        elif kind == b"moov" and moov is None:
            f.seek(i + head)
            moov = f.read(size - head)
        i += size
    if brand is None:
        raise MediaError("not an MP4: no ftyp box")
    if moov is None:
        raise MediaError("MP4 with no moov box (cut short?)")
    seconds, width, height, video_codec, audio_codec = _read_moov(moov)
    faststart = None
    if b"mdat" in order:
        faststart = order.index(b"moov") < order.index(b"mdat")
    kind_name = "m4a" if brand == "M4A " and video_codec is None else "mp4"
    return MediaInfo(
        kind=kind_name, bytes=total, width=width, height=height, seconds=seconds, brand=brand,
        video_codec=video_codec, audio_codec=audio_codec, faststart=faststart,
    )


def _read_moov(moov: bytes):
    seconds: Optional[float] = None
    width = height = None
    video_codec = audio_codec = None
    for kind, start, end in _boxes(moov, 0, len(moov)):
        if kind == b"mvhd":
            seconds = _mvhd_seconds(moov[start:end])
        elif kind == b"trak":
            handler, codec, size = _read_trak(moov, start, end)
            if handler == "soun":
                audio_codec = audio_codec or codec
            else:  # a video track (an audio track's size is 0 x 0)
                if handler == "vide":
                    video_codec = video_codec or codec
                if size and size[0] and size[1] and width is None:
                    width, height = size
    if seconds is None:
        raise MediaError("MP4 with no mvhd box, so no duration")
    return seconds, width, height, video_codec, audio_codec


def _mvhd_seconds(payload: bytes) -> float:
    # Version 0: 4 version+flags, 4 created, 4 modified, 4 timescale, 4 duration.
    # Version 1: the times are 8 bytes each and the duration is 8 bytes.
    if len(payload) < 4:
        raise MediaError("mvhd cut short")
    version = payload[0]
    if version == 0 and len(payload) >= 20:
        timescale, duration = struct.unpack(">II", payload[12:20])
    elif version == 1 and len(payload) >= 32:
        timescale = struct.unpack(">I", payload[20:24])[0]
        duration = struct.unpack(">Q", payload[24:32])[0]
    else:
        raise MediaError("mvhd of an unknown version, or cut short")
    if timescale == 0:
        raise MediaError("mvhd with a timescale of zero")
    return duration / timescale


def _read_trak(data: bytes, start: int, end: int):
    """(handler, sample entry type, (width, height) or None) for one track."""
    handler = codec = None
    size = None
    for kind, s, e in _boxes(data, start, end):
        if kind == b"tkhd":
            size = _tkhd_size(data[s:e])
        elif kind == b"mdia":
            handler, codec = _read_mdia(data, s, e)
    return handler, codec, size


def _tkhd_size(payload: bytes):
    # The width and height follow the 36-byte matrix, at offset 76 in a version 0 box and 88 in a
    # version 1 box (whose times and duration are wider), each a 16.16 fixed-point number.
    if not payload:
        raise MediaError("tkhd cut short")
    offset = 76 if payload[0] == 0 else 88
    if len(payload) < offset + 8:
        raise MediaError("tkhd cut short")
    width, height = struct.unpack(">II", payload[offset:offset + 8])
    return width >> 16, height >> 16


def _read_mdia(data: bytes, start: int, end: int):
    handler = codec = None
    for kind, s, e in _boxes(data, start, end):
        if kind == b"hdlr" and e - s >= 12:
            handler = data[s + 8:s + 12].decode("latin-1")
        elif kind == b"minf":
            for k2, s2, e2 in _boxes(data, s, e):
                if k2 != b"stbl":
                    continue
                for k3, s3, e3 in _boxes(data, s2, e2):
                    if k3 == b"stsd":
                        codec = _first_sample_entry(data, s3, e3)
    return handler, codec


def _first_sample_entry(data: bytes, start: int, end: int) -> Optional[str]:
    # stsd: 4 version+flags, 4 entry count, then the entries (a size and a four-letter type each).
    if end - start < 16:
        return None
    count = struct.unpack(">I", data[start + 4:start + 8])[0]
    if count < 1:
        return None
    return data[start + 12:start + 16].decode("latin-1")


# ---------------------------------------------------------------------------------------------
# One call for everything, and the limits
# ---------------------------------------------------------------------------------------------

def inspect(path: "str | os.PathLike[str]") -> MediaInfo:
    """Read a picture, MP4 or M4A by what its name says it is. Raises MediaError otherwise."""
    name = os.fspath(path)
    extension = os.path.splitext(name)[1].lower()
    size = os.path.getsize(name)
    if extension in _EXTENSION_KIND:
        with open(name, "rb") as f:
            data = f.read()
        kind, width, height = image_size(data)
        if kind != _EXTENSION_KIND[extension]:
            raise MediaError("a %s file named %s" % (kind.upper(), extension))
        return MediaInfo(kind=kind, bytes=size, width=width, height=height)
    if extension in (".mp4", ".m4a"):
        info = mp4_info(name)
        if extension == ".m4a" and info.video_codec is not None:
            raise MediaError("an .m4a file with a video track")
        return info
    raise MediaError("not a picture, MP4 or M4A by its name: %s" % extension)


def input_picture_problems(width: int, height: int) -> "list[str]":
    """Why a picture a command is asked to read is too big to open (an empty list if it isn't). Call it with the size
    read from the file's header, before the pixels are decoded, so a huge picture never fills the machine's memory."""
    found: "list[str]" = []
    if max(width, height) > PICTURE_INPUT_MAX_SIDE:
        found.append("%dx%d is over %d px a side" % (width, height, PICTURE_INPUT_MAX_SIDE))
    if width * height > PICTURE_INPUT_MAX_PIXELS:
        found.append("%dx%d is %.1f megapixels, over the %d a command reads" % (
            width, height, width * height / 1e6, PICTURE_INPUT_MAX_PIXELS // 1_000_000))
    return found


def same_file(first: "str | os.PathLike[str]", second: "str | os.PathLike[str]") -> bool:
    """Whether two paths name the same file: the same path, or (when both exist) the same file on disk, whatever the
    spelling: a different case on a case-insensitive disk, a symbolic link, a hard link, `..` in the path. A command
    uses it so its output never overwrites one of its inputs."""
    try:
        if os.path.abspath(first) == os.path.abspath(second):
            return True
        return os.path.exists(first) and os.path.exists(second) and os.path.samefile(first, second)
    except (OSError, ValueError):
        return False


def problems(info: MediaInfo, role: str, budget: bool = True) -> "list[str]":
    """Why a file breaks Hrizzup's limits or this repository's budgets (an empty list if it fits).

    `role` is "image", "video" or "audio". `budget=False` leaves out this repository's sample
    budgets and keeps Hrizzup's own limits (what a creator's file must meet to upload).
    """
    found: "list[str]" = []
    if role == "image":
        if info.kind not in ("png", "jpeg", "webp"):
            found.append("an image must be a PNG, JPEG or WebP, not %s" % info.kind)
        if info.bytes > IMAGE_MAX_BYTES:
            found.append("%d bytes is over Hrizzup's image limit of %d" % (info.bytes, IMAGE_MAX_BYTES))
        elif budget and info.bytes > IMAGE_BUDGET_BYTES:
            found.append("%d bytes is over the repository's image budget of %d" % (info.bytes, IMAGE_BUDGET_BYTES))
        for side in (info.width, info.height):
            if side is not None and side > IMAGE_MAX_SIDE:
                found.append("%d px is over Hrizzup's limit of %d a side" % (side, IMAGE_MAX_SIDE))
                break
    elif role == "video":
        if info.kind != "mp4" or info.video_codec != "avc1":
            found.append("a video must be an MP4 with H.264 (avc1) video")
        if info.audio_codec != "mp4a":
            found.append("a video needs AAC (mp4a) audio")
        if (info.width, info.height) != VIDEO_SIZE:
            found.append("a video is %dx%d, not %sx%s" % (VIDEO_SIZE + (info.width, info.height)))
        if info.seconds is None or info.seconds > VIDEO_MAX_SECONDS:
            found.append("%s s is over the video limit of %.1f s" % (info.seconds, VIDEO_MAX_SECONDS))
        if info.bytes > VIDEO_MAX_BYTES:
            found.append("%d bytes is over Hrizzup's video limit of %d" % (info.bytes, VIDEO_MAX_BYTES))
        elif budget and info.bytes > VIDEO_BUDGET_BYTES:
            found.append("%d bytes is over the repository's video budget of %d" % (info.bytes, VIDEO_BUDGET_BYTES))
        if info.faststart is False:
            found.append("moov comes after mdat: write the file with +faststart")
    elif role == "audio":
        if info.kind != "m4a" or info.brand != AUDIO_BRAND:
            found.append("audio must be M4A with the %r brand" % AUDIO_BRAND)
        if info.audio_codec != "mp4a":
            found.append("audio must be AAC (mp4a)")
        if info.seconds is None or info.seconds > AUDIO_MAX_SECONDS:
            found.append("%s s is over the audio limit of %.1f s" % (info.seconds, AUDIO_MAX_SECONDS))
        if info.bytes > AUDIO_MAX_BYTES:
            found.append("%d bytes is over Hrizzup's audio limit of %d" % (info.bytes, AUDIO_MAX_BYTES))
        elif budget and info.bytes > AUDIO_BUDGET_BYTES:
            found.append("%d bytes is over the repository's audio budget of %d" % (info.bytes, AUDIO_BUDGET_BYTES))
        if info.faststart is False:
            found.append("moov comes after mdat: write the file with +faststart")
    else:
        found.append("unknown role %r" % role)
    return found


# ---------------------------------------------------------------------------------------------
# FFmpeg's allowlist, as a validator (the builders that make the arguments are below)
# ---------------------------------------------------------------------------------------------

def _filter_names(graph: str) -> "list[str]":
    """The filter names in a -vf, -af or -filter_complex string: `scale=1080:-2,fps=30`."""
    names = []
    for chain in graph.split(";"):
        for step in chain.split(","):
            step = step.strip()
            if not step:
                continue
            # Drop pad labels like [0:v] on either side, then take the name before "=".
            while step.startswith("["):
                step = step.split("]", 1)[1].strip()
            step = step.split("[", 1)[0]
            names.append(step.split("=", 1)[0].strip())
    return names


_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+:")  # two or more letters then a colon: http:, concat:, file:, subfile:; not C:


def ffmpeg_args_problems(args: "list[str]") -> "list[str]":
    """Why an FFmpeg argument list asks for more than the allowlist (empty if it doesn't).

    Filters, encoders and formats named outside it are refused; `-c copy` is allowed. **Every input** (each `-i`) must be a file or
    `pipe:`, never an address (`http:`, `concat:`, `file:` and the like), and must be preceded, after the input before it, by
    `-f` with one of FFMPEG_INPUT_FORMATS and by `-protocol_whitelist file,pipe`: FFmpeg then reads exactly the kind of file it was
    told to, and follows nothing in it to anywhere else. A `-f` after the last input is an output format.
    """
    found: "list[str]" = []
    inputs = [i for i, flag in enumerate(args) if flag == "-i"]
    last_input = inputs[-1] if inputs else -1
    previous_input = -1
    group: "dict[str, list[str]]" = {"-f": [], "-protocol_whitelist": []}
    i = 0
    while i < len(args):
        flag = args[i]
        value = args[i + 1] if i + 1 < len(args) else ""
        if flag == "-i":
            if not value:
                found.append("-i has no input")
            elif _SCHEME.match(value) and not value.startswith("pipe:"):
                found.append("input %r is an address, not a file: only files and pipe: are read" % value.split("?")[0][:60])
            if len(group["-f"]) != 1 or group["-f"][0] not in FFMPEG_INPUT_FORMATS:
                found.append("input %r needs `-f` with one of %s before it, so FFmpeg is told what the file is" % (value[:60], ", ".join(FFMPEG_INPUT_FORMATS)))
            if group["-protocol_whitelist"] != [FFMPEG_PROTOCOLS]:
                found.append("input %r needs `-protocol_whitelist %s` before it" % (value[:60], FFMPEG_PROTOCOLS))
            group = {"-f": [], "-protocol_whitelist": []}
            previous_input = i
            i += 2
        elif flag in ("-vf", "-af", "-filter:v", "-filter:a", "-filter_complex", "-lavfi"):
            for name in _filter_names(value):
                if name not in FFMPEG_FILTERS:
                    found.append("filter %r isn't on the allowlist" % name)
            i += 2
        elif flag in ("-c", "-c:v", "-c:a", "-vcodec", "-acodec", "-codec", "-codec:v", "-codec:a"):
            if value != "copy" and value not in FFMPEG_ENCODERS:
                found.append("encoder %r isn't on the allowlist" % value)
            i += 2
        elif flag == "-f":
            if i < last_input:  # an input's format
                group["-f"].append(value)
                if value not in FFMPEG_INPUT_FORMATS:
                    found.append("input format %r isn't on the allowlist" % value)
            elif value not in FFMPEG_FORMATS:
                found.append("format %r isn't on the allowlist" % value)
            i += 2
        elif flag == "-protocol_whitelist":
            group["-protocol_whitelist"].append(value)
            if value != FFMPEG_PROTOCOLS:
                found.append("protocol whitelist %r isn't %r" % (value, FFMPEG_PROTOCOLS))
            i += 2
        else:
            i += 1
    return found


# ---------------------------------------------------------------------------------------------
# The FFmpeg builders (design 5 and 9): the only place FFmpeg is run
# ---------------------------------------------------------------------------------------------

VIDEO_ENCODER_ORDER = ("libx264", "h264_videotoolbox", "libopenh264")  # the first one a build has is used (design 9)
VIDEO_FPS = 30
VIDEO_BITRATE = "5M"
AUDIO_SAMPLE_RATE = 48000
AUDIO_BITRATE = "96k"
ENV_FFMPEG = "HRIZZUP_FFMPEG"
FFMPEG_TIMEOUT_SECONDS = 600  # one FFmpeg run, however long the file


class FfmpegError(Exception):
    """FFmpeg is missing or a run failed. `code` is the exit code a command should use: 3 for a missing
    tool, 1 for a run that failed (nothing is left behind)."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Ffmpeg:
    path: str
    video_encoder: Optional[str]  # None when only audio was asked for and the build has no H.264 encoder
    source: str  # where it came from: "HRIZZUP_FFMPEG", "imageio-ffmpeg" or "the path"
    version: str  # the first line of `-version`, for the log

    def describe(self) -> str:
        """One line for a command's log: which FFmpeg was chosen (the path is not in it)."""
        return "FFmpeg from %s (%s), video encoder %s" % (self.source, self.version, self.video_encoder or "none needed")


def _probe_output(path: str, *args: str) -> str:
    """What `ffmpeg <args>` prints (both streams); an empty string if it can't be run."""
    try:
        done = subprocess.run([path, "-hide_banner", *args], capture_output=True, text=True, timeout=60,
                              errors="replace", stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (done.stdout or "") + (done.stderr or "")


def _names(text: str, flags: str, columns: str) -> "set[str]":
    """The encoder or filter names in `ffmpeg -encoders` or `-filters` output: a flags column, then the name. Encoders
    have six flag characters; filters two or three, by the build."""
    return {m.group(1) for m in re.finditer(r"^\s*[%s.]{%s}\s+(\S+)" % (flags, columns), text, re.MULTILINE)}


def _candidates():
    """(source, path) in the order they are tried (design 9): HRIZZUP_FFMPEG, imageio-ffmpeg's program, `ffmpeg` on the path."""
    given = os.environ.get(ENV_FFMPEG, "").strip()
    if given:
        yield "HRIZZUP_FFMPEG", given
    try:
        import imageio_ffmpeg  # inside the function: a script's header may not name it, and the path may do

        yield "imageio-ffmpeg", imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # not installed, or its program isn't there (imageio-ffmpeg raises RuntimeError)
        pass
    import shutil

    found = shutil.which("ffmpeg")
    if found:
        yield "the path", found


def find_ffmpeg(video: bool = True) -> Ffmpeg:
    """The first FFmpeg that has `aac`, the `loudnorm` filter and (with `video`) one of libx264, h264_videotoolbox or
    libopenh264; each is probed once. Raises FfmpegError (code 3) naming what to install if none does."""
    tried = []
    for source, path in _candidates():
        encoders = _names(_probe_output(path, "-encoders"), "VASFXBD", "6")
        filters = _names(_probe_output(path, "-filters"), "TSC", "2,3")
        version = (_probe_output(path, "-version").split("\n", 1)[0] or "FFmpeg").strip()
        chosen = next((e for e in VIDEO_ENCODER_ORDER if e in encoders), None)
        missing = [name for name, ok in (("the aac encoder", "aac" in encoders), ("the loudnorm filter", "loudnorm" in filters),
                                         ("an H.264 encoder (libx264)", chosen is not None or not video)) if not ok]
        if not missing:
            return Ffmpeg(path=path, video_encoder=chosen, source=source, version=version)
        tried.append("%s lacks %s" % (source, " and ".join(missing)) if encoders or filters else "%s can't be run" % source)
    raise FfmpegError(
        "no usable FFmpeg (%s). Install the package that brings one (`pip install imageio-ffmpeg`, which this kit's "
        "requirements file already has), or put an FFmpeg with libx264, aac and loudnorm on the path, or set %s to its file"
        % ("; ".join(tried) if tried else "none was found", ENV_FFMPEG), 3)


def clip_problems(path: "str | os.PathLike[str]") -> "list[str]":
    """Why a file isn't a clip the kits decode (an empty list if it is): an MP4 read by `mp4_info` itself (an `ftyp` box, a `moov` box
    and a video track). FFmpeg is never asked to find out: a text file renamed `.mp4` (a playlist, a concat list) is refused here,
    from its own bytes, and the decoder is also told the file is an MP4 (see FFMPEG_INPUT_FORMATS)."""
    try:
        info = mp4_info(path)
    except (MediaError, OSError) as error:
        return ["isn't an MP4 video (%s)" % (error if isinstance(error, MediaError) else getattr(error, "strerror", None) or type(error).__name__)]
    if info.video_codec is None:
        return ["is an MP4 with no video track"]
    return []


def _tail(text: str, lines: int = 8) -> str:
    return "\n".join(text.strip().split("\n")[-lines:])


def _base(ff: Ffmpeg, *, info: bool = False) -> "list[str]":
    """The start of every command: no questions, no banner, errors only (loudnorm's numbers need `info`)."""
    return [ff.path, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info" if info else "error", "-y"]


# What every file FFmpeg writes here is made without: no metadata copied from the input, and no encoder version or time in the
# container (`bitexact`). The codec's own name stays in a video's sample entry, and x264 writes its version and settings as text in
# the video stream (no FFmpeg option leaves that out); neither holds a path.
NO_METADATA = ["-map_metadata", "-1", "-fflags", "+bitexact"]


def encode_video_args(ff: Ffmpeg, out: str, width: int, height: int, fps: int = VIDEO_FPS,
                      audio: Optional[str] = None) -> "list[str]":
    """FFmpeg's command for raw RGB frames on its input, as Hrizzup's video (design 9): H.264, yuv420p with a BT.709 matrix,
    constant `fps`, the narration copied in as it is, `+faststart`, and no metadata."""
    args = _base(ff) + ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (width, height), "-r", str(fps),
                        "-protocol_whitelist", FFMPEG_PROTOCOLS, "-i", "pipe:0"]
    if audio:
        args += ["-protocol_whitelist", FFMPEG_PROTOCOLS, "-f", "mov", "-i", os.path.abspath(audio), "-map", "0:v:0", "-map", "1:a:0"]
    args += ["-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setsar=1", "-r", str(fps), "-c:v", ff.video_encoder or "libx264",
             "-flags:v", "+bitexact"]
    if ff.video_encoder == "libx264":
        args += ["-preset", "slow", "-crf", "22", "-maxrate", VIDEO_BITRATE, "-bufsize", "10M", "-profile:v", "high",
                 "-g", str(2 * fps), "-sc_threshold", "0"]
    elif ff.video_encoder == "h264_videotoolbox":
        args += ["-b:v", VIDEO_BITRATE, "-profile:v", "high", "-g", str(2 * fps)]
    else:  # libopenh264
        args += ["-b:v", VIDEO_BITRATE, "-g", str(2 * fps)]
    args += ["-colorspace", "bt709"]
    if audio:
        args += ["-c:a", "copy"]
    args += NO_METADATA + ["-movflags", "+faststart", "-f", "mp4", out]
    return args


class VideoEncoder:
    """A running FFmpeg that takes raw RGB frames (`write`) and writes the MP4 (`close`). Use it as a context manager:
    leaving it by an error stops FFmpeg and removes the half-written file."""

    def __init__(self, ff: Ffmpeg, out: str, width: int, height: int, fps: int = VIDEO_FPS, audio: Optional[str] = None):
        self.out, self.frame_bytes, self.frames, self._closed = out, width * height * 3, 0, False
        self.command = encode_video_args(ff, out, width, height, fps, audio)
        problems = ffmpeg_args_problems(self.command)
        if problems:
            raise FfmpegError("the video command asks for more than the allowlist: " + "; ".join(problems))
        self._log = tempfile.TemporaryFile()
        try:
            self._process = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self._log)
        except OSError as error:
            self._log.close()
            raise FfmpegError("can't run FFmpeg: %s" % error, 3)

    def write(self, frame: bytes) -> None:
        if len(frame) != self.frame_bytes:
            raise FfmpegError("a frame is %d bytes; this video's frames are %d" % (len(frame), self.frame_bytes))
        try:
            self._process.stdin.write(frame)
        except (BrokenPipeError, OSError):
            raise FfmpegError("FFmpeg stopped while the frames were being written: " + self._why())
        self.frames += 1

    def _why(self) -> str:
        try:
            self._process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self._log.seek(0)
        return _tail(self._log.read().decode("utf-8", "replace")) or "no message"

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._process.stdin.close()
        except OSError:
            pass
        try:
            code = self._process.wait(timeout=FFMPEG_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            self._process.kill()
            code = -1
        self._log.seek(0)
        message = _tail(self._log.read().decode("utf-8", "replace"))
        self._log.close()
        if code != 0:
            raise FfmpegError("FFmpeg failed to write the video: %s" % (message or "exit %d" % code))

    def abort(self) -> None:
        if not self._closed:
            self._closed = True
            self._process.kill()
            self._process.wait()
            for stream in (self._process.stdin, self._log):
                try:
                    stream.close()
                except OSError:
                    pass
        try:
            os.remove(self.out)
        except OSError:
            pass

    def __enter__(self) -> "VideoEncoder":
        return self

    def __exit__(self, kind, value, trace) -> bool:
        if kind is None:
            self.close()
        else:
            self.abort()
        return False


def encode_video(ff: Ffmpeg, out: str, width: int, height: int, fps: int = VIDEO_FPS, audio: Optional[str] = None) -> VideoEncoder:
    """Start encoding Hrizzup's video: write raw RGB frames to the encoder, then close it (see `VideoEncoder`)."""
    return VideoEncoder(ff, out, width, height, fps, audio)


def decode_clip_args(ff: Ffmpeg, clip: str, width: int, height: int, fps: int = VIDEO_FPS,
                     start: Optional[float] = None, seconds: Optional[float] = None) -> "list[str]":
    """FFmpeg's command for a clip's picture as raw RGB frames of one size: scaled to cover, cropped to fit, at `fps`,
    its sound dropped. `start` and `seconds` trim it."""
    args = _base(ff)
    if start:
        args += ["-ss", "%.3f" % start]
    if seconds:
        args += ["-t", "%.3f" % seconds]
    graph = "scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,fps=%d,format=rgb24" % (width, height, width, height, fps)
    return args + ["-protocol_whitelist", FFMPEG_PROTOCOLS, "-f", "mov", "-i", os.path.abspath(clip), "-an", "-vf", graph,
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def decode_clip(ff: Ffmpeg, clip: str, width: int, height: int, fps: int = VIDEO_FPS,
                start: Optional[float] = None, seconds: Optional[float] = None) -> Iterator[bytes]:
    """Each frame of a clip as raw RGB bytes (width x height x 3), through `decode_clip_args`. Stop reading and the
    FFmpeg run is stopped."""
    refused = clip_problems(clip)
    if refused:
        raise FfmpegError("the clip %s %s" % (os.path.basename(os.fspath(clip)), refused[0]), 2)
    command = decode_clip_args(ff, clip, width, height, fps, start, seconds)
    problems = ffmpeg_args_problems(command)
    if problems:
        raise FfmpegError("the clip command asks for more than the allowlist: " + "; ".join(problems))
    size = width * height * 3
    log = tempfile.TemporaryFile()
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log)
    except OSError as error:
        log.close()
        raise FfmpegError("can't run FFmpeg: %s" % error, 3)
    finished = False
    try:
        while True:
            frame = process.stdout.read(size)
            if len(frame) < size:
                finished = True
                break
            yield frame
    finally:
        if not finished:
            process.kill()
        process.stdout.close()
        code = process.wait()
        log.seek(0)
        message = _tail(log.read().decode("utf-8", "replace"))
        log.close()
    if code != 0:
        raise FfmpegError("FFmpeg couldn't read the clip %s: %s" % (os.path.basename(clip), message or "exit %d" % code))


def _run(command: "list[str]", what: str) -> str:
    """Run one FFmpeg command and return what it printed on stderr (where loudnorm writes its numbers)."""
    problems = ffmpeg_args_problems(command)
    if problems:
        raise FfmpegError("the %s command asks for more than the allowlist: %s" % (what, "; ".join(problems)))
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                              timeout=FFMPEG_TIMEOUT_SECONDS)
    except OSError as error:
        raise FfmpegError("can't run FFmpeg: %s" % error, 3)
    except subprocess.TimeoutExpired:
        raise FfmpegError("FFmpeg took more than %d seconds to %s" % (FFMPEG_TIMEOUT_SECONDS, what))
    if done.returncode != 0:
        raise FfmpegError("FFmpeg failed to %s: %s" % (what, _tail(done.stderr) or "exit %d" % done.returncode))
    return done.stderr


LOUDNORM_TARGET = "I=%d:TP=%s:LRA=%d" % (LOUDNESS_LUFS, TRUE_PEAK_TARGET_DBTP, LOUDNESS_RANGE)
LOUDNORM_ATTEMPTS = 3  # pass 2 is tried again, with a lower true-peak target, if the encoded file's peak is too near the limit
TRUE_PEAK_SETTLE_DBTP = -1.2  # an encoded peak above this (the limit is -1.0) is levelled again: a measurement is never trusted to the last decimal
LOUDNORM_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


def _loudnorm_json(text: str) -> "dict[str, str]":
    """The last JSON object in loudnorm's output (it prints one when `print_format=json`)."""
    found = re.findall(r"\{[^{}]*\}", text)
    for block in reversed(found):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and "input_i" in data:
            return data
    raise FfmpegError("loudnorm printed no measurements: " + (_tail(text, 4) or "nothing"))


def loudnorm_measure_args(ff: Ffmpeg, source: str) -> "list[str]":
    """Pass 1: FFmpeg measures a file's loudness (nothing is written)."""
    kind = "wav" if os.fspath(source).lower().endswith(".wav") else "mov"  # a WAV, or an MP4 or M4A: never left to FFmpeg to guess
    return _base(ff, info=True) + ["-protocol_whitelist", FFMPEG_PROTOCOLS, "-f", kind, "-i", os.path.abspath(source), "-vn", "-af",
                                  "loudnorm=%s:print_format=json" % LOUDNORM_TARGET, "-f", "null", "-"]


def loudnorm_measure(ff: Ffmpeg, source: str) -> "dict[str, float]":
    """The loudness of an audio or video file's sound: `input_i` (integrated LUFS), `input_tp` (true peak, dBTP),
    `input_lra`, `input_thresh` and `target_offset`, as numbers. It is also how a finished file is measured again."""
    data = _loudnorm_json(_run(loudnorm_measure_args(ff, source), "measure the loudness"))
    try:
        return {key: float(data[key]) for key in LOUDNORM_KEYS}
    except (KeyError, ValueError):
        raise FfmpegError("loudnorm's measurements are incomplete: %s" % sorted(data))


def loudnorm_apply_args(ff: Ffmpeg, source: str, measured: "dict[str, float]", out: str,
                        true_peak: float = TRUE_PEAK_TARGET_DBTP) -> "list[str]":
    """Pass 2: level `source` with pass 1's numbers (`linear=true`; loudnorm uses its dynamic mode where linear can't keep
    the true peak), then `aresample=48000`, as AAC-LC mono in M4A (the `ipod` muxer, 96 kb/s, `+faststart`). `true_peak` is
    the target peak in dBTP, -1.5 unless the caller is making up for what the AAC encoder adds."""
    given = ":".join("%s=%.2f" % (name, measured[key]) for name, key in (
        ("measured_I", "input_i"), ("measured_LRA", "input_lra"), ("measured_TP", "input_tp"),
        ("measured_thresh", "input_thresh"), ("offset", "target_offset")))
    target = "I=%d:TP=%s:LRA=%d" % (LOUDNESS_LUFS, ("%.1f" % true_peak).rstrip("0").rstrip("."), LOUDNESS_RANGE)
    graph = "loudnorm=%s:%s:linear=true:print_format=json,aresample=%d" % (target, given, AUDIO_SAMPLE_RATE)
    return _base(ff, info=True) + ["-protocol_whitelist", FFMPEG_PROTOCOLS, "-f", "wav", "-i", os.path.abspath(source), "-vn", "-af", graph,
                                  "-ac", "1", "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-flags:a", "+bitexact"] + NO_METADATA + [
                                      "-movflags", "+faststart", "-f", "ipod", out]


def loudnorm_apply(ff: Ffmpeg, source: str, measured: "dict[str, float]", out: str,
                   true_peak: float = TRUE_PEAK_TARGET_DBTP) -> str:
    """Level and encode `source` to `out` (an `.m4a`); returns loudnorm's own `normalization_type` (`linear`, or
    `dynamic` when it couldn't keep the sound's shape). The result is measured again by the caller."""
    text = _run(loudnorm_apply_args(ff, source, measured, out, true_peak), "level and encode the audio")
    blocks = re.findall(r"\{[^{}]*\}", text)
    for block in reversed(blocks):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if isinstance(data, dict) and "normalization_type" in data:
            return str(data["normalization_type"])
    return "unknown"


def loudness_problems(measured: "dict[str, float]") -> "list[str]":
    """Why a measured file is outside Hrizzup's loudness rule (design 9): -17 to -15 LUFS and a true peak of -1.0 dBTP at most."""
    found = []
    integrated = measured["input_i"]
    if abs(integrated - LOUDNESS_LUFS) > LOUDNESS_TOLERANCE:
        found.append("%.1f LUFS is outside %d to %d" % (integrated, LOUDNESS_LUFS - LOUDNESS_TOLERANCE, LOUDNESS_LUFS + LOUDNESS_TOLERANCE))
    if measured["input_tp"] > TRUE_PEAK_MAX_DBTP:
        found.append("a true peak of %.1f dBTP is over %.1f" % (measured["input_tp"], TRUE_PEAK_MAX_DBTP))
    return found


def next_true_peak_target(target: float, measured_peak: float) -> float:
    """The true-peak target for another try of pass 2, when the encoded file's peak came out at `measured_peak`: lower by how far
    it was from -1.5 dBTP, and a little more (loudnorm can't see what the AAC encoder adds after it)."""
    return round(target - (measured_peak - TRUE_PEAK_TARGET_DBTP) - 0.2, 1)
