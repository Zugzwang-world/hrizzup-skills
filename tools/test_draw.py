"""hrizzup_draw's reading of a creator's picture and its refusals of text the fonts can't draw.

The module needs Pillow and fontTools, which the repository's offline check doesn't install: these tests run where they are
installed (`uv run --with pillow --with fonttools ...`, or any environment that has them) and are skipped where they aren't.
The sample pictures prove the drawing itself.
"""

import io
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHARED = os.path.join(ROOT, "shared", "scripts")

import catalogue  # noqa: E402,F401  (puts hrizzup_media in sys.modules)

try:
    import importlib.util

    from PIL import Image

    if SHARED not in sys.path:
        sys.path.insert(0, SHARED)
    spec = importlib.util.spec_from_file_location("hrizzup_draw_under_test", os.path.join(SHARED, "hrizzup_draw.py"))
    draw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(draw)
    HAVE_PILLOW = True
except ImportError:  # no Pillow or fontTools here
    HAVE_PILLOW = False

PAPER = "#336699"
PAPER_RGB = (0x33, 0x66, 0x99)


@unittest.skipUnless(HAVE_PILLOW, "needs Pillow and fontTools")
class Loading(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="draw-test-")
        self.addCleanup(__import__("shutil").rmtree, self.folder, True)

    def save(self, image, name, **options):
        path = os.path.join(self.folder, name)
        image.save(path, **options)
        return path

    def test_a_good_picture_loads(self):
        picture = draw.load_picture(self.save(Image.new("RGB", (40, 30), (1, 2, 3)), "ok.png"))
        self.assertEqual(picture.size, (40, 30))

    def test_a_picture_with_too_many_pixels_is_refused_before_it_is_decoded(self):
        path = self.save(Image.new("1", (8190, 8190)), "big.png")  # 67 megapixels, a few KiB on disk
        with mock.patch("PIL.PngImagePlugin.PngImageFile.load", side_effect=AssertionError("decoded the pixels")):
            with self.assertRaises(draw.DrawError) as caught:
                draw.load_picture(path)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("megapixels", str(caught.exception))

    def test_a_picture_with_a_side_over_8192_is_refused(self):
        path = self.save(Image.new("1", (8193, 4)), "wide.png")
        with mock.patch("PIL.PngImagePlugin.PngImageFile.load", side_effect=AssertionError("decoded the pixels")):
            with self.assertRaises(draw.DrawError) as caught:
                draw.load_picture(path)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("8192", str(caught.exception))

    def test_the_limit_itself_is_allowed_and_pillows_own_guard_matches_it(self):
        path = self.save(Image.new("1", (8192, 4880)), "limit.png")  # 39.98 megapixels
        self.assertEqual(draw.load_picture(path).size, (8192, 4880))
        self.assertEqual(Image.MAX_IMAGE_PIXELS, 40_000_000)

    def test_other_refusals_exit_2(self):
        text = os.path.join(self.folder, "notes.png")
        with open(text, "w", encoding="utf-8") as f:
            f.write("not a picture")
        for path in (text, os.path.join(self.folder, "missing.png"), self.save(Image.new("P", (4, 4)), "anim.gif")):
            with self.subTest(path=os.path.basename(path)), self.assertRaises(draw.DrawError) as caught:
                draw.load_picture(path)
            self.assertEqual(caught.exception.code, 2)
        with mock.patch("os.path.getsize", return_value=26 * 1024 * 1024), self.assertRaises(draw.DrawError) as caught:
            draw.load_picture(self.save(Image.new("RGB", (4, 4)), "ok.png"))
        self.assertIn("MiB", str(caught.exception))
        whole = self.save(Image.new("RGB", (300, 300), (5, 5, 5)), "whole.png")
        with open(whole, "rb") as f:
            cut = f.read()[:200]  # the header and a little data
        broken = os.path.join(self.folder, "cut.png")
        with open(broken, "wb") as f:
            f.write(cut)
        with self.assertRaises(draw.DrawError):
            draw.load_picture(broken)  # a file cut short: refused, not a traceback


@unittest.skipUnless(HAVE_PILLOW, "needs Pillow and fontTools")
class Flattening(unittest.TestCase):
    def test_an_alpha_channel_goes_over_the_paper(self):
        image = Image.new("RGBA", (4, 1), (255, 0, 0, 255))
        image.putpixel((1, 0), (255, 0, 0, 0))  # fully transparent
        image.putpixel((2, 0), (255, 0, 0, 128))  # half
        flat = draw.flatten(image, PAPER)
        self.assertEqual(flat.mode, "RGB")
        self.assertEqual(flat.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(flat.getpixel((1, 0)), PAPER_RGB)
        half = flat.getpixel((2, 0))
        self.assertTrue(all(abs(a - b) <= 2 for a, b in zip(half, (0x99, 0x33, 0x4C))), half)

    def test_grey_with_alpha(self):
        image = Image.new("LA", (2, 1), (200, 255))
        image.putpixel((1, 0), (200, 0))
        flat = draw.flatten(image, PAPER)
        self.assertEqual((flat.getpixel((0, 0)), flat.getpixel((1, 0))), ((200, 200, 200), PAPER_RGB))

    def test_a_palette_with_a_transparent_colour(self):
        image = Image.new("P", (2, 1), 0)
        image.putpalette([255, 0, 0, 0, 255, 0] + [0] * 250 * 3)
        image.putpixel((1, 0), 1)
        image.info["transparency"] = 1  # colour 1 is transparent
        flat = draw.flatten(image, PAPER)
        self.assertEqual((flat.getpixel((0, 0)), flat.getpixel((1, 0))), ((255, 0, 0), PAPER_RGB))

    def test_a_palette_picture_after_a_save_and_a_reload(self):
        image = Image.new("RGBA", (3, 1), (0, 0, 0, 0)).convert("P")
        buffer = io.BytesIO()
        Image.new("RGBA", (3, 1), (10, 20, 30, 0)).save(buffer, "PNG")
        buffer.seek(0)
        flat = draw.flatten(Image.open(buffer), PAPER)
        self.assertEqual(flat.getpixel((0, 0)), PAPER_RGB)
        self.assertEqual(image.mode, "P")

    def test_16_bit_grey_is_scaled_to_8_bits(self):
        image = Image.new("I;16", (4, 1))
        image.putdata([0, 256, 32768, 65535])
        flat = draw.flatten(image, PAPER)
        self.assertEqual([flat.getpixel((n, 0))[0] for n in range(4)], [0, 1, 128, 255])
        buffer = io.BytesIO()
        image.save(buffer, "PNG")  # a 16-bit PNG as a creator's tool writes it
        buffer.seek(0)
        again = draw.flatten(Image.open(buffer), PAPER)
        self.assertEqual([again.getpixel((n, 0))[0] for n in range(4)], [0, 1, 128, 255])

    def test_a_dark_16_bit_grey_is_not_drawn_light(self):
        dark = Image.new("I;16", (4, 1))
        dark.putdata([0, 100, 200, 255])  # every value is at most 255, but this is a 16-bit picture: nearly black
        flat = draw.flatten(dark, PAPER)
        self.assertEqual([flat.getpixel((n, 0))[0] for n in range(4)], [0, 0, 1, 1])
        buffer = io.BytesIO()
        dark.save(buffer, "PNG")
        buffer.seek(0)
        again = draw.flatten(Image.open(buffer), PAPER)
        self.assertEqual(max(again.getpixel((n, 0))[0] for n in range(4)), 1)
        other = Image.new("I;16B", (2, 1))
        other.putdata([255, 65535])
        self.assertEqual([draw.flatten(other, PAPER).getpixel((n, 0))[0] for n in range(2)], [1, 255])  # big-endian too

    def test_the_whole_16_bit_range_maps_to_the_whole_8_bit_range(self):
        image = Image.new("I;16", (3, 1))
        image.putdata([0, 65535, 32896])
        self.assertEqual([draw.flatten(image, PAPER).getpixel((n, 0))[0] for n in range(3)], [0, 255, 128])

    def test_32_bit_integer_pictures(self):
        small = Image.new("I", (3, 1))
        small.putdata([0, 100, 255])  # values that are already 8-bit
        self.assertEqual([draw.flatten(small, PAPER).getpixel((n, 0))[0] for n in range(3)], [0, 100, 255])
        wide = Image.new("I", (3, 1))
        wide.putdata([0, 1000, 65535])  # 16-bit values
        self.assertEqual([draw.flatten(wide, PAPER).getpixel((n, 0))[0] for n in range(3)], [0, 4, 255])
        huge = Image.new("I", (2, 1))
        huge.putdata([0, 70000])
        with self.assertRaises(draw.DrawError) as caught:
            draw.flatten(huge, PAPER)
        self.assertEqual(caught.exception.code, 2)

    def test_floating_point_pictures_are_refused(self):
        with self.assertRaises(draw.DrawError) as caught:
            draw.flatten(Image.new("F", (2, 2)), PAPER)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("8-bit", str(caught.exception))

    def test_other_modes_become_plain_rgb(self):
        self.assertEqual(draw.flatten(Image.new("1", (2, 2), 1), PAPER).getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(draw.flatten(Image.new("L", (2, 2), 7), PAPER).getpixel((0, 0)), (7, 7, 7))
        self.assertEqual(draw.flatten(Image.new("CMYK", (2, 2), (0, 0, 0, 0)), PAPER).mode, "RGB")
        self.assertEqual(draw.flatten(Image.new("RGB", (2, 2), (9, 8, 7)), PAPER).getpixel((0, 0)), (9, 8, 7))

    def test_exif_orientation_is_applied(self):
        image = Image.new("RGB", (6, 2), (1, 2, 3))
        exif = Image.Exif()
        exif[0x0112] = 6  # turn 90 degrees clockwise to view
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", exif=exif)
        buffer.seek(0)
        self.assertEqual(draw.flatten(Image.open(buffer), PAPER).size, (2, 6))

    def test_cover_crop_lays_transparency_over_the_paper(self):
        image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        crop = draw.cover_crop(image, (20, 10), (0.5, 0.5), PAPER)
        self.assertEqual(crop.size, (20, 10))
        self.assertEqual(crop.getpixel((5, 5)), PAPER_RGB)
        self.assertEqual(draw.cover_crop(image, (20, 10)).getpixel((5, 5)), (255, 255, 255))  # white unless told


@unittest.skipUnless(HAVE_PILLOW, "needs Pillow and fontTools")
class Glyphs(unittest.TestCase):
    def test_the_refusal_says_english_letters_only_and_names_hindi(self):
        style = draw.load_style(None)
        with self.assertRaises(draw.DrawError) as caught:
            draw.check_glyphs("हिन्दी", "text", style, "the title")
        message = str(caught.exception)
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("English (Latin) letters", message)
        self.assertIn("Hindi", message)
        self.assertIn("U+0939", message)

    def test_plain_english_passes_and_emoji_is_still_refused(self):
        style = draw.load_style(None)
        draw.check_glyphs("Delhi's air: 450 AQI, Rs 5 to Rs 7", "text", style)
        with self.assertRaises(draw.DrawError):
            draw.check_glyphs("smog \U0001F62E", "text-bold", style)


if __name__ == "__main__":
    unittest.main()
