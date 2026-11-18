"""hrizzup_media: pictures, MP4 and M4A read from their bytes, Hrizzup's limits, and the FFmpeg allowlist.

Every file here is built from pieces, byte by byte, so nothing needs FFmpeg or a package.
"""

import io
import os
import struct
import tempfile
import unittest
import zlib

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


class FfmpegAllowlist(unittest.TestCase):
    """The validator the builders' arguments go through (design 5). The builders arrive with the scripts."""

    def test_the_planned_commands_pass(self):
        video = ["-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1080x1920", "-r", "30", "-i", "-",
                 "-i", "narration.m4a", "-vf", "format=yuv420p,setsar=1", "-c:v", "libx264", "-preset", "slow",
                 "-crf", "22", "-c:a", "copy", "-movflags", "+faststart", "-f", "mp4", "out.mp4"]
        self.assertEqual(media.ffmpeg_args_problems(video), [])
        clip = ["-i", "in.mp4", "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30", "-an", "-f", "rawvideo", "-"]
        self.assertEqual(media.ffmpeg_args_problems(clip), [])
        loud = ["-i", "in.wav", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"]
        self.assertEqual(media.ffmpeg_args_problems(loud), [])
        apply = ["-i", "in.wav", "-af", "loudnorm=I=-16:linear=true,aresample=48000", "-c:a", "aac", "-f", "ipod", "out.m4a"]
        self.assertEqual(media.ffmpeg_args_problems(apply), [])
        graph = ["-filter_complex", "[0:a]loudnorm=I=-16[a];[a]aresample=48000[o]", "-map", "[o]", "-c:a", "pcm_s16le", "-f", "wav", "x.wav"]
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

    def test_the_lists_are_the_designs(self):
        self.assertEqual(media.FFMPEG_FILTERS, ("loudnorm", "aresample", "scale", "crop", "fps", "format", "setsar"))
        self.assertEqual(media.FFMPEG_ENCODERS, ("libx264", "h264_videotoolbox", "libopenh264", "aac", "pcm_s16le"))
        self.assertEqual(media.FFMPEG_FORMATS, ("rawvideo", "mp4", "ipod", "wav", "null"))


if __name__ == "__main__":
    unittest.main()
