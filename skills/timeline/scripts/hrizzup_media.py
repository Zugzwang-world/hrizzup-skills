"""Hrizzup's media limits, and readers for the files a skill makes. Standard library only.

This is a module, not a command: scripts import it as a sibling. It reads PNG, JPEG and WebP
pictures and MP4 and M4A files straight from their bytes (no FFmpeg, no packages), so a check
can say what a file is, and whether Hrizzup's limits and this repository's budgets hold, on any
machine. The limits are the ones in `references/sizes.md`, and Hrizzup's format guide
(`GET /social/formats`) is the authority if they ever differ.

    from hrizzup_media import inspect, problems
    info = inspect("meme.png")             # MediaError if it isn't what its name says
    print(problems(info, "image"))         # [] when it fits
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import BinaryIO, Optional

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

# ---- FFmpeg's allowlist (design 5): what the builders may ask for ----
FFMPEG_FILTERS = ("loudnorm", "aresample", "scale", "crop", "fps", "format", "setsar")
FFMPEG_ENCODERS = ("libx264", "h264_videotoolbox", "libopenh264", "aac", "pcm_s16le")
FFMPEG_FORMATS = ("rawvideo", "mp4", "ipod", "wav", "null")

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
# FFmpeg's allowlist, as a validator (the builders that make the arguments arrive with the scripts)
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


def ffmpeg_args_problems(args: "list[str]") -> "list[str]":
    """Why an FFmpeg argument list asks for more than the allowlist (empty if it doesn't).

    Filters, encoders and formats named outside it are refused; `-c copy` is allowed.
    """
    found: "list[str]" = []
    i = 0
    while i < len(args):
        flag = args[i]
        value = args[i + 1] if i + 1 < len(args) else ""
        if flag in ("-vf", "-af", "-filter:v", "-filter:a", "-filter_complex", "-lavfi"):
            for name in _filter_names(value):
                if name not in FFMPEG_FILTERS:
                    found.append("filter %r isn't on the allowlist" % name)
            i += 2
        elif flag in ("-c", "-c:v", "-c:a", "-vcodec", "-acodec", "-codec", "-codec:v", "-codec:a"):
            if value != "copy" and value not in FFMPEG_ENCODERS:
                found.append("encoder %r isn't on the allowlist" % value)
            i += 2
        elif flag == "-f":
            if value not in FFMPEG_FORMATS:
                found.append("format %r isn't on the allowlist" % value)
            i += 2
        else:
            i += 1
    return found
