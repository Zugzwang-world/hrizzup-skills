"""hrizzup_media: pictures, MP4 and M4A read from their bytes, Hrizzup's limits, and the FFmpeg allowlist.

Every file in the first classes is built from pieces, byte by byte, so nothing needs FFmpeg or a package. The
builders' arguments are tested without FFmpeg too; the last class runs them against a real FFmpeg when there is one.
"""

import io
import os
import struct
import sys
import tempfile
import types
import unittest
import zlib
from unittest import mock

import catalogue  # puts hrizzup_media in sys.modules

media = catalogue.media


# ---- pictures ----

def png(width, height):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IEND", b"")


def jpeg(width, height, marker=0xC0, before=b""):
    def segment(code, data):
        return bytes([0xFF, code]) + struct.pack(">H", len(data) + 2) + data
    frame = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    return (b"\xff\xd8" + segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00") + before
            + segment(marker, frame) + segment(0xDA, b"\x00") + b"\xff\xd9")


def webp_lossy(width, height):
    data = b"\x00\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", width, height) + b"\x00" * 8
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(data)) + b"WEBP" + b"VP8 " + struct.pack("<I", len(data)) + data


def webp_lossless(width, height):
    bits = (width - 1) | ((height - 1) << 14)
    data = b"\x2f" + struct.pack("<I", bits) + b"\x00" * 4
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(data)) + b"WEBP" + b"VP8L" + struct.pack("<I", len(data)) + data


def webp_extended(width, height):
    data = b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + 8 + len(data)) + b"WEBP" + b"VP8X" + struct.pack("<I", len(data)) + data


class Pictures(unittest.TestCase):
    def test_png_ihdr(self):
        self.assertEqual(media.image_size(png(1080, 1350)), ("png", 1080, 1350))

    def test_jpeg_sof_variants(self):
        self.assertEqual(media.image_size(jpeg(1080, 1080)), ("jpeg", 1080, 1080))
        self.assertEqual(media.image_size(jpeg(640, 480, marker=0xC2)), ("jpeg", 640, 480))  # progressive

    def test_jpeg_skips_the_tables_that_look_like_frames(self):
        # DHT (0xC4) sits in the 0xC0 to 0xCF range but holds no size.
        table = bytes([0xFF, 0xC4]) + struct.pack(">H", 5) + b"\x00\x00\x00"
        self.assertEqual(media.image_size(jpeg(1920, 1080, before=table)), ("jpeg", 1920, 1080))

    def test_jpeg_with_fill_bytes(self):
        data = b"\xff\xd8\xff\xff\xff" + jpeg(300, 200)[2:]
        self.assertEqual(media.image_size(data), ("jpeg", 300, 200))

    def test_webp_three_ways(self):
        self.assertEqual(media.image_size(webp_lossy(640, 480)), ("webp", 640, 480))
        self.assertEqual(media.image_size(webp_lossless(321, 123)), ("webp", 321, 123))
        self.assertEqual(media.image_size(webp_extended(4096, 1)), ("webp", 4096, 1))

    def test_refusals_are_clean(self):
        bad = {
            "not a picture": b"hello world, not a picture at all",
            "empty": b"",
            "png cut short": png(10, 10)[:20],
            "png with another chunk first": b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IDAT" + b"\x00" * 17,
            "png of no width": png(0, 10),
            "jpeg without a frame": b"\xff\xd8\xff\xe0\x00\x02\xff\xda\x00\x02",
            "jpeg cut short": jpeg(10, 10)[:12],
            "jpeg with no marker": b"\xff\xd8\x00\x00",
            "webp cut short": b"RIFF\x04\x00\x00\x00WEBP",
            "webp of another kind": b"RIFF" + b"\x00" * 4 + b"WEBP" + b"ALPH" + b"\x00" * 30,
        }
        for label, data in bad.items():
            with self.subTest(label):
                with self.assertRaises(media.MediaError):
                    media.image_size(data)

    def test_inspect_wants_the_extension_to_match(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "x.png")
            with open(path, "wb") as f:
                f.write(jpeg(100, 100))
            with self.assertRaises(media.MediaError):
                media.inspect(path)
            good = os.path.join(folder, "y.jpg")
            with open(good, "wb") as f:
                f.write(jpeg(100, 100))
            info = media.inspect(good)
            self.assertEqual((info.kind, info.width, info.height), ("jpeg", 100, 100))
            other = os.path.join(folder, "z.gif")
            with open(other, "wb") as f:
                f.write(b"GIF89a")
            with self.assertRaises(media.MediaError):
                media.inspect(other)


# ---- MP4 and M4A ----

def box(kind, payload):
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def box64(kind, payload):
    return struct.pack(">I", 1) + kind + struct.pack(">Q", 16 + len(payload)) + payload


def box_to_end(kind, payload):
    return struct.pack(">I", 0) + kind + payload


def ftyp(brand=b"isom"):
    return box(b"ftyp", brand + b"\x00\x00\x02\x00" + brand + b"mp42")


def mvhd(timescale, duration, version=0):
    if version == 0:
        return box(b"mvhd", b"\x00\x00\x00\x00" + struct.pack(">IIII", 0, 0, timescale, duration) + b"\x00" * 80)
    return box(b"mvhd", b"\x01\x00\x00\x00" + struct.pack(">QQIQ", 0, 0, timescale, duration) + b"\x00" * 80)


def tkhd(width, height, version=0, fraction=0):
    if version == 0:
        head = b"\x00\x00\x00\x07" + struct.pack(">IIIII", 0, 0, 1, 0, 0) + b"\x00" * 8
    else:
        head = b"\x01\x00\x00\x07" + struct.pack(">QQIIQ", 0, 0, 1, 0, 0) + b"\x00" * 8
    middle = b"\x00" * 2 + b"\x00" * 2 + b"\x00\x00" + b"\x00\x00" + b"\x00" * 36
    return box(b"tkhd", head + middle + struct.pack(">II", (width << 16) | fraction, (height << 16) | fraction))


def trak(handler, codec, width=0, height=0, tkhd_version=0):
    hdlr = box(b"hdlr", b"\x00\x00\x00\x00" + b"\x00" * 4 + handler + b"\x00" * 12 + b"\x00")
    stsd = box(b"stsd", b"\x00\x00\x00\x00" + struct.pack(">I", 1) + box(codec, b"\x00" * 8))
    stbl = box(b"stbl", stsd)
    minf = box(b"minf", stbl)
    mdia = box(b"mdia", hdlr + minf)
    return box(b"trak", tkhd(width, height, tkhd_version) + mdia)


def video_moov(seconds_ms=12345, version=0):
    return box(b"moov", mvhd(1000, seconds_ms, version) + trak(b"vide", b"avc1", 1080, 1920) + trak(b"soun", b"mp4a"))


def mdat(size=64):
    return box(b"mdat", b"\x00" * size)


class Mp4(unittest.TestCase):
    def info(self, data):
        return media.mp4_info(io.BytesIO(data))

    def test_version_0(self):
        info = self.info(ftyp() + video_moov(12345) + mdat())
        self.assertAlmostEqual(info.seconds, 12.345)
        self.assertEqual((info.width, info.height), (1080, 1920))
        self.assertEqual((info.video_codec, info.audio_codec, info.brand, info.kind), ("avc1", "mp4a", "isom", "mp4"))
        self.assertTrue(info.faststart)

    def test_version_1_has_a_64_bit_duration(self):
        info = self.info(ftyp() + video_moov(5_000_000_000, version=1) + mdat())
        self.assertAlmostEqual(info.seconds, 5_000_000.0)

    def test_tkhd_version_1_and_16_16_fixed_point(self):
        moov = box(b"moov", mvhd(1000, 2000) + trak(b"vide", b"avc1", 1080, 1920, tkhd_version=1))
        info = self.info(ftyp() + moov + mdat())
        self.assertEqual((info.width, info.height), (1080, 1920))
        fractional = box(b"moov", mvhd(1000, 2000) + box(b"trak", tkhd(720, 1280, fraction=0x8000)))
        # a track with a tkhd and no mdia still gives its size
        self.assertEqual(self.info(ftyp() + fractional + mdat()).width, 720)

    def test_a_64_bit_box_size(self):
        data = ftyp() + box64(b"mdat", b"\x00" * 100) + video_moov()
        info = self.info(data)
        self.assertAlmostEqual(info.seconds, 12.345)
        self.assertFalse(info.faststart)  # moov after mdat

    def test_a_64_bit_moov(self):
        moov = video_moov()
        big = box64(b"moov", moov[8:])
        self.assertEqual(self.info(ftyp() + big + mdat()).width, 1080)

    def test_a_size_0_last_box_runs_to_the_end(self):
        info = self.info(ftyp() + video_moov() + box_to_end(b"mdat", b"\x00" * 500))
        self.assertTrue(info.faststart)
        self.assertEqual(info.bytes, len(ftyp() + video_moov()) + 8 + 500)
        last_moov = ftyp() + mdat() + box_to_end(b"moov", video_moov()[8:])
        self.assertAlmostEqual(self.info(last_moov).seconds, 12.345)

    def test_moov_after_mdat_is_not_faststart(self):
        self.assertFalse(self.info(ftyp() + mdat() + video_moov()).faststart)

    def test_m4a(self):
        moov = box(b"moov", mvhd(48000, 48000 * 61) + trak(b"soun", b"mp4a"))
        info = self.info(ftyp(b"M4A ") + moov + mdat())
        self.assertEqual((info.kind, info.brand, info.video_codec, info.audio_codec), ("m4a", "M4A ", None, "mp4a"))
        self.assertAlmostEqual(info.seconds, 61.0)

    def test_truncated_files_are_refused(self):
        whole = ftyp() + video_moov() + mdat()
        for cut in (3, 12, 30, len(ftyp()) + 20, len(ftyp()) + len(video_moov()) + 30, len(whole) - 1):
            with self.subTest(cut=cut):
                with self.assertRaises(media.MediaError):
                    self.info(whole[:cut])

    def test_other_damage_is_refused(self):
        cases = {
            "no ftyp": video_moov() + mdat(),
            "no moov": ftyp() + mdat(),
            "no mvhd": ftyp() + box(b"moov", trak(b"vide", b"avc1", 1080, 1920)) + mdat(),
            "timescale 0": ftyp() + box(b"moov", mvhd(0, 100)) + mdat(),
            "a box smaller than its header": ftyp() + struct.pack(">I", 4) + b"moov" + b"\x00" * 8,
            "not an MP4": b"hello world, definitely not an mp4 file",
            "empty": b"",
        }
        for label, data in cases.items():
            with self.subTest(label):
                with self.assertRaises(media.MediaError):
                    self.info(data)

    def test_from_a_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "v.mp4")
            with open(path, "wb") as f:
                f.write(ftyp() + video_moov() + mdat())
            self.assertEqual(media.inspect(path).kind, "mp4")
            audio = os.path.join(folder, "a.m4a")
            with open(audio, "wb") as f:
                f.write(ftyp() + video_moov() + mdat())  # video in an .m4a
            with self.assertRaises(media.MediaError):
                media.inspect(audio)


class InputPictures(unittest.TestCase):
    """The pictures a command reads (a creator's own): refused from the header's size, before any pixel is decoded."""

    def test_the_limits(self):
        self.assertEqual(media.PICTURE_INPUT_MAX_PIXELS, 40_000_000)
        self.assertEqual(media.PICTURE_INPUT_MAX_SIDE, 8192)
        self.assertEqual(media.input_picture_problems(1080, 1350), [])
        self.assertEqual(media.input_picture_problems(8192, 4880), [])  # 40.0 megapixels and 8,192 a side: allowed
        self.assertEqual(media.input_picture_problems(6324, 6324), [])

    def test_too_many_pixels_or_too_long_a_side(self):
        self.assertTrue(any("megapixels" in p for p in media.input_picture_problems(7000, 7000)))
        self.assertTrue(any("a side" in p for p in media.input_picture_problems(9000, 10)))
        self.assertTrue(any("a side" in p for p in media.input_picture_problems(10, 8193)))
        both = media.input_picture_problems(12000, 12000)
        self.assertEqual(len(both), 2)
        self.assertTrue(media.input_picture_problems(40_000_001, 1))


class SameFile(unittest.TestCase):
    """A command never overwrites an input, however its path is spelled."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="same-file-")
        self.addCleanup(__import__("shutil").rmtree, self.folder, True)
        self.path = os.path.join(self.folder, "Spec.json")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{}\n")

    def test_the_same_path_even_when_nothing_is_there(self):
        self.assertTrue(media.same_file(self.path, self.path))
        missing = os.path.join(self.folder, "none.png")
        self.assertTrue(media.same_file(missing, missing))  # the same name is enough
        self.assertFalse(media.same_file(missing, self.path))

    def test_another_spelling_of_the_same_file(self):
        self.assertTrue(media.same_file(self.path, os.path.join(self.folder, "sub", "..", "Spec.json")))
        self.assertFalse(media.same_file(self.path, os.path.join(self.folder, "Other.json")))

    def test_a_symbolic_link_and_a_hard_link(self):
        link = os.path.join(self.folder, "link.png")
        hard = os.path.join(self.folder, "hard.png")
        try:
            os.symlink(self.path, link)
            os.link(self.path, hard)
        except (OSError, NotImplementedError):
            self.skipTest("this file system has no links")
        self.assertTrue(media.same_file(self.path, link))
        self.assertTrue(media.same_file(link, self.path))
        self.assertTrue(media.same_file(self.path, hard))

    def test_another_case_on_a_disk_that_ignores_case(self):
        other = os.path.join(self.folder, "spec.JSON")
        if not os.path.exists(other):
            self.skipTest("this disk tells upper and lower case apart")
        self.assertTrue(media.same_file(self.path, other))


class Limits(unittest.TestCase):
    def video(self, **changes):
        base = dict(kind="mp4", bytes=1_000_000, width=1080, height=1920, seconds=45.0, brand="isom",
                    video_codec="avc1", audio_codec="mp4a", faststart=True)
        base.update(changes)
        return media.MediaInfo(**base)

    def audio(self, **changes):
        base = dict(kind="m4a", bytes=500_000, seconds=61.0, brand="M4A ", audio_codec="mp4a", faststart=True)
        base.update(changes)
        return media.MediaInfo(**base)

    def test_a_good_video_and_audio(self):
        self.assertEqual(media.problems(self.video(), "video"), [])
        self.assertEqual(media.problems(self.audio(), "audio"), [])

    def test_video_limits(self):
        self.assertTrue(media.problems(self.video(seconds=58.5), "video"))
        self.assertEqual(media.problems(self.video(seconds=58.0), "video"), [])
        self.assertTrue(media.problems(self.video(width=1080, height=1080), "video"))
        self.assertTrue(media.problems(self.video(video_codec="hvc1"), "video"))
        self.assertTrue(media.problems(self.video(audio_codec=None), "video"))
        self.assertTrue(media.problems(self.video(faststart=False), "video"))
        over_budget = media.problems(self.video(bytes=media.VIDEO_BUDGET_BYTES + 1), "video")
        self.assertIn("budget", " ".join(over_budget))
        self.assertEqual(media.problems(self.video(bytes=media.VIDEO_BUDGET_BYTES + 1), "video", budget=False), [])
        over_limit = media.problems(self.video(bytes=media.VIDEO_MAX_BYTES + 1), "video", budget=False)
        self.assertIn("limit", " ".join(over_limit))

    def test_audio_limits(self):
        self.assertTrue(media.problems(self.audio(seconds=295.5), "audio"))
        self.assertEqual(media.problems(self.audio(seconds=295.0), "audio"), [])
        self.assertTrue(media.problems(self.audio(brand="mp42"), "audio"))
        self.assertTrue(media.problems(self.audio(audio_codec="alac"), "audio"))
        self.assertTrue(media.problems(self.audio(bytes=media.AUDIO_BUDGET_BYTES + 1), "audio"))
        self.assertTrue(media.problems(self.audio(bytes=media.AUDIO_MAX_BYTES + 1), "audio", budget=False))

    def test_image_limits(self):
        small = media.MediaInfo(kind="png", bytes=100_000, width=1080, height=1350)
        self.assertEqual(media.problems(small, "image"), [])
        self.assertTrue(media.problems(media.MediaInfo(kind="png", bytes=media.IMAGE_BUDGET_BYTES + 1, width=10, height=10), "image"))
        self.assertTrue(media.problems(media.MediaInfo(kind="png", bytes=media.IMAGE_MAX_BYTES + 1, width=10, height=10), "image", budget=False))
        self.assertTrue(media.problems(media.MediaInfo(kind="jpeg", bytes=10, width=4097, height=10), "image"))
        self.assertEqual(media.problems(media.MediaInfo(kind="jpeg", bytes=10, width=4096, height=4096), "image"), [])
        self.assertTrue(media.problems(media.MediaInfo(kind="mp4", bytes=10), "image"))

    def test_the_numbers_are_the_sizes_page(self):
        self.assertEqual(media.IMAGE_MAX_BYTES, 10485760)
        self.assertEqual(media.VIDEO_MAX_BYTES, 104857600)
        self.assertEqual(media.AUDIO_MAX_BYTES, 20971520)
        self.assertEqual((media.VIDEO_MAX_SECONDS, media.AUDIO_MAX_SECONDS), (58.0, 295.0))


PIN = ["-protocol_whitelist", "file,pipe"]


class FfmpegAllowlist(unittest.TestCase):
    """The validator the builders' arguments go through (design 5): filters, encoders and formats, and what may be read."""

    def test_the_planned_commands_pass(self):
        video = ["-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1080x1920", "-r", "30"] + PIN + ["-i", "pipe:0"] + PIN + [
                 "-f", "mov", "-i", "narration.m4a", "-vf", "format=yuv420p,setsar=1", "-c:v", "libx264", "-preset", "slow",
                 "-crf", "22", "-c:a", "copy", "-movflags", "+faststart", "-f", "mp4", "out.mp4"]
        self.assertEqual(media.ffmpeg_args_problems(video), [])
        clip = PIN + ["-f", "mov", "-i", "in.mp4", "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30", "-an",
                      "-f", "rawvideo", "-"]
        self.assertEqual(media.ffmpeg_args_problems(clip), [])
        loud = PIN + ["-f", "wav", "-i", "in.wav", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]
        self.assertEqual(media.ffmpeg_args_problems(loud), [])
        apply = PIN + ["-f", "wav", "-i", "in.wav", "-af", "loudnorm=I=-16:linear=true,aresample=48000", "-c:a", "aac", "-f", "ipod", "out.m4a"]
        self.assertEqual(media.ffmpeg_args_problems(apply), [])
        graph = PIN + ["-f", "mov", "-i", "in.mp4", "-filter_complex", "[0:a]loudnorm=I=-16[a];[a]aresample=48000[o]", "-map", "[o]", "-c:a", "pcm_s16le",
                       "-f", "wav", "x.wav"]
        self.assertEqual(media.ffmpeg_args_problems(graph), [])

    def test_each_kind_of_overreach_is_refused(self):
        refused = {
            "drawtext": ["-vf", "scale=10:10,drawtext=text=hi"],
            "zoompan": ["-vf", "zoompan=z=1.2"],
            "subtitles": ["-vf", "subtitles=a.srt"],
            "a filter graph": ["-filter_complex", "[0:v]scale=1:1[v];[v]overlay[o]"],
            "x265": ["-c:v", "libx265"],
            "mp3": ["-c:a", "libmp3lame"],
            "matroska": ["-f", "matroska"],
            "old spelling": ["-vcodec", "libvpx"],
        }
        for label, args in refused.items():
            with self.subTest(label):
                self.assertTrue(media.ffmpeg_args_problems(args), label)

    def test_every_input_must_be_pinned_to_a_format_and_to_files_and_pipes(self):
        good = PIN + ["-f", "mov", "-i", "in.mp4", "-f", "null", "-"]
        self.assertEqual(media.ffmpeg_args_problems(good), [])
        cases = {
            "no format": PIN + ["-i", "in.mp4", "-f", "null", "-"],
            "no whitelist": ["-f", "mov", "-i", "in.mp4", "-f", "null", "-"],
            "a wider whitelist": ["-protocol_whitelist", "file,pipe,http,tcp", "-f", "mov", "-i", "in.mp4", "-f", "null", "-"],
            "the default whitelist's kind": ["-protocol_whitelist", "file,crypto,data", "-f", "mov", "-i", "in.mp4", "-f", "null", "-"],
            "a playlist format": PIN + ["-f", "hls", "-i", "in.mp4", "-f", "null", "-"],
            "a concat list": PIN + ["-f", "concat", "-i", "in.mp4", "-f", "null", "-"],
            "a format named twice": PIN + ["-f", "mov", "-f", "wav", "-i", "in.mp4", "-f", "null", "-"],
            "no input value": PIN + ["-f", "mov", "-i"],
        }
        for label, args in cases.items():
            with self.subTest(label):
                self.assertTrue(media.ffmpeg_args_problems(args), label)

    def test_a_second_input_needs_its_own_pins(self):
        both = PIN + ["-f", "rawvideo", "-i", "pipe:0"] + PIN + ["-f", "mov", "-i", "narration.m4a", "-f", "mp4", "o.mp4"]
        self.assertEqual(media.ffmpeg_args_problems(both), [])
        unpinned = PIN + ["-f", "rawvideo", "-i", "pipe:0", "-i", "narration.m4a", "-f", "mp4", "o.mp4"]
        self.assertTrue(media.ffmpeg_args_problems(unpinned))
        # the pins of the first input are not the second's
        self.assertTrue(media.ffmpeg_args_problems(PIN + ["-f", "mov", "-i", "a.mp4", "-i", "b.mp4", "-f", "null", "-"]))

    def test_an_input_that_is_an_address_is_refused_even_when_pinned(self):
        for value in ("http://example.com/a.mp4", "https://example.com/a.mp4", "concat:a.mp4|b.mp4", "file:/etc/hostname", "ftp://x/y", "rtmp://x/y",
                      "subfile:x", "data:video/mp4;base64,AAAA", "tcp://127.0.0.1:1", "udp://1.2.3.4:5"):
            with self.subTest(value):
                found = media.ffmpeg_args_problems(PIN + ["-f", "mov", "-i", value, "-f", "null", "-"])
                self.assertTrue(any("address" in p for p in found), found)

    def test_files_pipes_and_windows_paths_are_not_addresses(self):
        for value in ("in.mp4", "/tmp/a b/in.mp4", "pipe:0", "pipe:", "-", "C:\\clips\\in.mp4", "./a:b.mp4", "a/b:c.mp4"):
            with self.subTest(value):
                args = PIN + ["-f", "rawvideo" if value.startswith("pipe") or value == "-" else "mov", "-i", value, "-f", "null", "-"]
                self.assertEqual([p for p in media.ffmpeg_args_problems(args) if "address" in p], [], value)

    def test_the_lists_are_the_designs(self):
        self.assertEqual(media.FFMPEG_FILTERS, ("loudnorm", "aresample", "scale", "crop", "fps", "format", "setsar"))
        self.assertEqual(media.FFMPEG_ENCODERS, ("libx264", "h264_videotoolbox", "libopenh264", "aac", "pcm_s16le"))
        self.assertEqual(media.FFMPEG_FORMATS, ("rawvideo", "mp4", "ipod", "wav", "null"))
        self.assertEqual(media.FFMPEG_INPUT_FORMATS, ("mov", "rawvideo", "wav"))
        self.assertEqual(media.FFMPEG_PROTOCOLS, "file,pipe")


def _fake(path="/x/ffmpeg", encoder="libx264", source="the path"):
    return media.Ffmpeg(path=path, video_encoder=encoder, source=source, version="ffmpeg version 0")


class FfmpegBuilders(unittest.TestCase):
    """Every builder's arguments stay inside the allowlist (design 5 and 7.3), and `find_ffmpeg` chooses as design 9 says."""

    def test_every_builders_arguments_are_on_the_allowlist(self):
        for encoder in media.VIDEO_ENCODER_ORDER:
            ff = _fake(encoder=encoder)
            for audio in (None, "narration.m4a"):
                with self.subTest(encoder=encoder, audio=audio):
                    args = media.encode_video_args(ff, "out.mp4", 1080, 1920, 30, audio)
                    self.assertEqual(media.ffmpeg_args_problems(args), [])
                    self.assertIn(encoder, args)
                    self.assertEqual(("-c:a", "copy") in list(zip(args, args[1:])), audio is not None)
        ff = _fake()
        measure = media.loudnorm_measure_args(ff, "in.m4a")
        measured = {"input_i": -22.4, "input_tp": -6.1, "input_lra": 3.2, "input_thresh": -33.0, "target_offset": 0.4}
        apply = media.loudnorm_apply_args(ff, "in.wav", measured, "out.m4a")
        clip = media.decode_clip_args(ff, "in.mp4", 1080, 1920, 30, 1.5, 4.0)
        for label, args in (("measure", measure), ("apply", apply), ("clip", clip)):
            with self.subTest(label):
                self.assertEqual(media.ffmpeg_args_problems(args), [])

    def test_every_builders_inputs_are_pinned_and_absolute(self):
        measured = {"input_i": -22.4, "input_tp": -6.1, "input_lra": 3.2, "input_thresh": -33.0, "target_offset": 0.4}
        ff = _fake()
        commands = {
            "video": media.encode_video_args(ff, "out.mp4", 1080, 1920, 30, "narration.m4a"),
            "video, no sound": media.encode_video_args(ff, "out.mp4", 1080, 1920, 30),
            "clip": media.decode_clip_args(ff, "in.mp4", 1080, 1920, 30, 1.5, 4.0),
            "measure a wav": media.loudnorm_measure_args(ff, "in.wav"),
            "measure an m4a": media.loudnorm_measure_args(ff, "in.m4a"),
            "measure an mp4": media.loudnorm_measure_args(ff, "in.MP4"),
            "apply": media.loudnorm_apply_args(ff, "in.wav", measured, "out.m4a"),
        }
        formats = {"video": ["rawvideo", "mov"], "video, no sound": ["rawvideo"], "clip": ["mov"], "measure a wav": ["wav"],
                   "measure an m4a": ["mov"], "measure an mp4": ["mov"], "apply": ["wav"]}
        for label, args in commands.items():
            with self.subTest(label):
                self.assertEqual(media.ffmpeg_args_problems(args), [])
                inputs = [i for i, flag in enumerate(args) if flag == "-i"]
                self.assertEqual(len(inputs), len(formats[label]))
                before = -2
                for i, wanted in zip(inputs, formats[label]):
                    segment = args[before + 2:i]  # what sits between the last input and this one
                    self.assertEqual(segment[segment.index("-protocol_whitelist") + 1], "file,pipe")
                    self.assertEqual(segment[segment.index("-f") + 1], wanted)
                    self.assertTrue(args[i + 1] == "pipe:0" or os.path.isabs(args[i + 1]), args[i + 1])  # a relative path can't look like an address
                    before = i

    def test_the_video_command_is_hrizzups_settings(self):
        args = media.encode_video_args(_fake(), "out.mp4", 1080, 1920, 30, "n.m4a")
        pairs = dict(zip(args, args[1:]))
        for flag, value in (("-preset", "slow"), ("-crf", "22"), ("-maxrate", "5M"), ("-bufsize", "10M"), ("-g", "60"),
                            ("-sc_threshold", "0"), ("-movflags", "+faststart"), ("-f", "mp4"), ("-s", "1080x1920"), ("-r", "30")):
            self.assertEqual(pairs.get(flag), value, flag)
        self.assertTrue(args[-1] == "out.mp4" and "format=yuv420p" in pairs["-vf"])
        toolbox = media.encode_video_args(_fake(encoder="h264_videotoolbox"), "out.mp4", 1080, 1920)
        self.assertEqual(dict(zip(toolbox, toolbox[1:]))["-b:v"], "5M")
        self.assertNotIn("-crf", toolbox)

    def test_every_file_is_written_without_metadata_or_an_encoder_name(self):
        video = media.encode_video_args(_fake(), "out.mp4", 1080, 1920, 30, "n.m4a")
        measured = {"input_i": -22.4, "input_tp": -6.1, "input_lra": 3.2, "input_thresh": -33.0, "target_offset": 0.4}
        audio = media.loudnorm_apply_args(_fake(), "in.wav", measured, "out.m4a")
        for args in (video, audio):
            pairs = dict(zip(args, args[1:]))
            self.assertEqual(pairs["-map_metadata"], "-1")
            self.assertEqual(pairs["-fflags"], "+bitexact")
        self.assertEqual(dict(zip(video, video[1:]))["-flags:v"], "+bitexact")
        self.assertEqual(dict(zip(audio, audio[1:]))["-flags:a"], "+bitexact")

    def test_the_audio_commands_are_the_designs(self):
        measured = {"input_i": -22.4, "input_tp": -6.1, "input_lra": 3.2, "input_thresh": -33.0, "target_offset": 0.4}
        apply = media.loudnorm_apply_args(_fake(), "in.wav", measured, "out.m4a")
        graph = dict(zip(apply, apply[1:]))["-af"]
        self.assertIn("loudnorm=I=-16:TP=-1.5:LRA=11:", graph)
        self.assertIn("measured_I=-22.40:measured_LRA=3.20:measured_TP=-6.10:measured_thresh=-33.00:offset=0.40", graph)
        self.assertTrue(graph.endswith(":linear=true:print_format=json,aresample=48000"))
        pairs = dict(zip(apply, apply[1:]))
        for flag, value in (("-c:a", "aac"), ("-b:a", "96k"), ("-ac", "1"), ("-f", "ipod"), ("-movflags", "+faststart")):
            self.assertEqual(pairs[flag], value, flag)
        first = media.loudnorm_measure_args(_fake(), "in.wav")
        self.assertIn("loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", first)
        self.assertEqual(first[-3:], ["-f", "null", "-"])

    def test_decode_clip_covers_then_crops_and_trims(self):
        args = media.decode_clip_args(_fake(), "in.mp4", 1080, 1920, 30, 1.5, 4.0)
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,format=rgb24", args)
        self.assertLess(args.index("-ss"), args.index("-i"))  # seeks before reading, so a long clip isn't decoded to its start
        self.assertIn("-an", args)
        plain = media.decode_clip_args(_fake(), "in.mp4", 1080, 1920)
        self.assertNotIn("-ss", plain)
        self.assertNotIn("-t", plain)

    def test_a_clip_is_checked_from_its_own_bytes_before_ffmpeg_sees_it(self):
        with tempfile.TemporaryDirectory() as folder:
            def make(name, data):
                path = os.path.join(folder, name)
                with open(path, "wb") as f:
                    f.write(data)
                return path

            good = make("good.mp4", ftyp() + video_moov(4000) + mdat())
            self.assertEqual(media.clip_problems(good), [])
            for label, data in {
                "an HLS playlist": b"#EXTM3U\n#EXT-X-VERSION:3\n#EXTINF:4,\nhttp://example.com/segment.ts\n",
                "a playlist of local files": b"#EXTM3U\n#EXTINF:1,\n/etc/hostname\n",
                "a concat list": b"ffconcat version 1.0\nfile '/etc/hostname'\n",
                "a text file": b"hello",
                "an empty file": b"",
                "a picture": png(10, 10),
                "audio only": ftyp(b"M4A ") + box(b"moov", mvhd(1000, 4000) + trak(b"soun", b"mp4a")) + mdat(),
                "a cut-short MP4": (ftyp() + video_moov(4000))[:40],
            }.items():
                with self.subTest(label):
                    found = media.clip_problems(make(label.replace(" ", "-") + ".mp4", data))
                    self.assertTrue(found, label)
                    self.assertTrue(found[0].startswith(("isn't an MP4", "is an MP4 with no video")), found)
            self.assertTrue(media.clip_problems(os.path.join(folder, "missing.mp4")))

    def test_decode_clip_refuses_a_clip_that_is_not_one_without_starting_ffmpeg(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "playlist.mp4")
            with open(path, "wb") as f:
                f.write(b"#EXTM3U\n#EXTINF:1,\nhttp://example.com/a.ts\n")
            with mock.patch.object(media.subprocess, "Popen") as popen:
                with self.assertRaises(media.FfmpegError) as caught:
                    list(media.decode_clip(_fake(), path, 64, 64))
            popen.assert_not_called()
            self.assertEqual(caught.exception.code, 2)  # bad input
            self.assertIn("playlist.mp4", str(caught.exception))

    def test_a_loudness_outside_the_rule_is_named(self):
        ok = {"input_i": -16.2, "input_tp": -1.6, "input_lra": 4.0, "input_thresh": -26.0, "target_offset": 0.0}
        self.assertEqual(media.loudness_problems(ok), [])
        self.assertEqual(media.loudness_problems(dict(ok, input_i=-17.0, input_tp=-1.0)), [])
        self.assertTrue(media.loudness_problems(dict(ok, input_i=-17.2)))
        self.assertTrue(media.loudness_problems(dict(ok, input_i=-14.7)))
        self.assertTrue(media.loudness_problems(dict(ok, input_tp=-0.9)))
        self.assertEqual(len(media.loudness_problems(dict(ok, input_i=-23, input_tp=0.0))), 2)

    def test_loudnorms_numbers_are_read_from_the_last_json_block(self):
        text = ("[Parsed_loudnorm_0 @ 0x1] \n{\n\t\"input_i\" : \"-22.31\",\n\t\"input_tp\" : \"-6.02\",\n\t\"input_lra\" : \"3.10\",\n"
                "\t\"input_thresh\" : \"-32.80\",\n\t\"output_i\" : \"-16.01\",\n\t\"normalization_type\" : \"linear\",\n"
                "\t\"target_offset\" : \"0.01\"\n}\n")
        data = media._loudnorm_json(text)
        self.assertEqual(data["input_i"], "-22.31")
        self.assertEqual(data["normalization_type"], "linear")
        with self.assertRaises(media.FfmpegError):
            media._loudnorm_json("no numbers here")
        with self.assertRaises(media.FfmpegError):
            media._loudnorm_json('{"something": "else"}')

    def test_find_ffmpeg_takes_the_first_build_that_has_what_the_kits_need(self):
        listings = {
            "/a": ("V....D libx264   x\n A....D aac  y\n", " .. aresample   A->A  r\n"),  # no loudnorm
            "/b": (" V....D h264_videotoolbox  v\n V....D libopenh264 o\n A....D aac  y\n", " .. loudnorm  A->A  e\n"),
            "/c": (" V....D libx264  x\n V....D h264_videotoolbox  v\n A....D aac  y\n", " T. loudnorm  A->A  e\n"),
        }

        def probe(path, *args):
            encoders, filters = listings.get(path, ("", ""))
            return {"-encoders": encoders, "-filters": filters, "-version": "ffmpeg version 9.9 x\nmore"}.get(args[0], "")

        paths = [("HRIZZUP_FFMPEG", "/a"), ("imageio-ffmpeg", "/b"), ("the path", "/c")]
        with mock.patch.object(media, "_candidates", lambda: iter(paths)), mock.patch.object(media, "_probe_output", probe):
            self.assertEqual((media.find_ffmpeg().path, media.find_ffmpeg().video_encoder), ("/b", "h264_videotoolbox"))
        with mock.patch.object(media, "_candidates", lambda: iter(paths[:1] + paths[2:])), mock.patch.object(media, "_probe_output", probe):
            found = media.find_ffmpeg()
            self.assertEqual((found.path, found.video_encoder, found.source), ("/c", "libx264", "the path"))  # libx264 first
            self.assertIn("ffmpeg version 9.9", found.describe())
            self.assertNotIn("/c", found.describe())  # which build, never its path
        # audio only: a build with no H.264 encoder will do
        only_audio = {"/d": (" A....D aac  y\n", " .. loudnorm  A->A  e\n")}
        with mock.patch.object(media, "_candidates", lambda: iter([("the path", "/d")])), \
                mock.patch.object(media, "_probe_output", lambda path, *args: {"-encoders": only_audio[path][0], "-filters": only_audio[path][1], "-version": "v"}.get(args[0], "")):
            self.assertIsNone(media.find_ffmpeg(video=False).video_encoder)
            with self.assertRaises(media.FfmpegError) as caught:
                media.find_ffmpeg(video=True)
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("H.264", str(caught.exception))

    def test_no_ffmpeg_at_all_exits_3_and_says_what_to_install(self):
        with mock.patch.object(media, "_candidates", lambda: iter(())):
            with self.assertRaises(media.FfmpegError) as caught:
                media.find_ffmpeg()
        self.assertEqual(caught.exception.code, 3)
        self.assertIn("pip install imageio-ffmpeg", str(caught.exception))
        self.assertIn("HRIZZUP_FFMPEG", str(caught.exception))

    def test_the_candidates_come_in_the_designs_order(self):
        fake = types.ModuleType("imageio_ffmpeg")
        fake.get_ffmpeg_exe = lambda: "/i/ffmpeg"
        with mock.patch.dict(os.environ, {"HRIZZUP_FFMPEG": "/h/ffmpeg"}), mock.patch.dict(sys.modules, {"imageio_ffmpeg": fake}), \
                mock.patch("shutil.which", lambda name: "/p/ffmpeg"):
            self.assertEqual(list(media._candidates()), [("HRIZZUP_FFMPEG", "/h/ffmpeg"), ("imageio-ffmpeg", "/i/ffmpeg"), ("the path", "/p/ffmpeg")])
        with mock.patch.dict(os.environ, {"HRIZZUP_FFMPEG": ""}), mock.patch.dict(sys.modules, {"imageio_ffmpeg": None}), \
                mock.patch("shutil.which", lambda name: None):
            self.assertEqual(list(media._candidates()), [])


def _real_ffmpeg():
    try:
        return media.find_ffmpeg()
    except media.FfmpegError:
        return None


@unittest.skipUnless(_real_ffmpeg(), "no FFmpeg with libx264, aac and loudnorm here")
class FfmpegRuns(unittest.TestCase):
    """The builders against a real FFmpeg: a small video, its sound, and the two loudness passes."""

    @classmethod
    def setUpClass(cls):
        cls.ff = _real_ffmpeg()
        cls.folder = tempfile.TemporaryDirectory()
        cls.wav = os.path.join(cls.folder.name, "tone.wav")
        import math
        import wave
        with wave.open(cls.wav, "wb") as w:  # 4 s of a 220 Hz tone that swells and fades like speech, about -23 LUFS
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            frames = bytearray()
            for n in range(24000 * 4):
                level = 0.05 + 0.04 * math.sin(2 * math.pi * 0.7 * n / 24000)
                frames += struct.pack("<h", int(32767 * level * math.sin(2 * math.pi * 220 * n / 24000)))
            w.writeframes(bytes(frames))

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def test_two_passes_level_the_sound_to_hrizzups_target_and_it_measures_the_same_again(self):
        before = media.loudnorm_measure(self.ff, self.wav)
        self.assertLess(before["input_i"], -20)  # it needs levelling
        out = os.path.join(self.folder.name, "tone.m4a")
        kind = media.loudnorm_apply(self.ff, self.wav, before, out)
        self.assertEqual(kind, "linear")
        after = media.loudnorm_measure(self.ff, out)
        self.assertEqual(media.loudness_problems(after), [])
        self.assertAlmostEqual(after["input_i"], -16.0, delta=0.8)
        with open(out, "rb") as f:
            written = f.read()
        self.assertNotIn(b"Lavf", written)  # no encoder tag
        self.assertNotIn(b"Lavc63", written)
        info = media.inspect(out)
        self.assertEqual((info.kind, info.brand, info.audio_codec, info.faststart), ("m4a", "M4A ", "mp4a", True))
        self.assertAlmostEqual(info.seconds, 4.0, delta=0.15)
        self.assertEqual(media.problems(info, "audio"), [])

    def test_a_missing_input_is_a_clean_error(self):
        with self.assertRaises(media.FfmpegError) as caught:
            media.loudnorm_measure(self.ff, os.path.join(self.folder.name, "nothing.wav"))
        self.assertEqual(caught.exception.code, 1)

    def test_frames_become_a_valid_mp4_with_the_sound_copied_in_and_read_back(self):
        out = os.path.join(self.folder.name, "small.mp4")
        sound = os.path.join(self.folder.name, "small.m4a")
        media.loudnorm_apply(self.ff, self.wav, media.loudnorm_measure(self.ff, self.wav), sound)
        width, height, count = 128, 224, 60
        with media.encode_video(self.ff, out, width, height, 30, sound) as encoder:
            for n in range(count):
                encoder.write(bytes([n * 4 % 256, 128, 255 - n * 4 % 256]) * (width * height))
            with self.assertRaises(media.FfmpegError):
                encoder.write(b"too short")
        with open(out, "rb") as f:
            written = f.read()
        for name in (b"Lavf", b"Lavc63"):
            self.assertNotIn(name, written)  # no container encoder tag, no encoder version in the container
        info = media.inspect(out)
        self.assertEqual((info.kind, info.video_codec, info.audio_codec, info.faststart), ("mp4", "avc1", "mp4a", True))
        self.assertEqual((info.width, info.height), (width, height))
        self.assertAlmostEqual(info.seconds, 4.0, delta=0.2)  # the sound is 4 s and the video 2 s: the longer track sets it
        frames = list(media.decode_clip(self.ff, out, 64, 64, 15, 0.0, 1.0))
        self.assertEqual({len(f) for f in frames}, {64 * 64 * 3})
        self.assertIn(len(frames), (15, 14, 16))

    def test_leaving_the_encoder_by_an_error_leaves_no_file(self):
        out = os.path.join(self.folder.name, "half.mp4")
        with self.assertRaises(RuntimeError):
            with media.encode_video(self.ff, out, 64, 64, 30) as encoder:
                encoder.write(bytes(64 * 64 * 3))
                raise RuntimeError("the caller failed")
        self.assertFalse(os.path.exists(out))

    def test_ffmpeg_itself_refuses_a_playlist_when_told_the_file_is_an_mp4_and_follows_nothing(self):
        target = os.path.join(self.folder.name, "target.txt")
        with open(target, "w") as f:
            f.write("not for reading")
        playlist = os.path.join(self.folder.name, "list.mp4")
        with open(playlist, "w") as f:
            f.write("#EXTM3U\n#EXTINF:1,\n%s\n" % target)
        args = media.decode_clip_args(self.ff, playlist, 64, 64)
        self.assertEqual(media.ffmpeg_args_problems(args), [])
        import subprocess

        done = subprocess.run(args, capture_output=True, timeout=60)
        self.assertNotEqual(done.returncode, 0)  # an .mp4 that isn't one: "moov atom not found", the playlist is not followed
        self.assertEqual(done.stdout, b"")
        # and it is the script's own check that stops it first
        with self.assertRaises(media.FfmpegError) as caught:
            list(media.decode_clip(self.ff, playlist, 64, 64))
        self.assertEqual(caught.exception.code, 2)

    def test_a_clip_that_is_not_a_video_is_a_clean_error(self):
        with self.assertRaises(media.FfmpegError):
            list(media.decode_clip(self.ff, self.wav, 64, 64))


if __name__ == "__main__":
    unittest.main()
