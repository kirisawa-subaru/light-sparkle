import unittest
from io import BytesIO

from PIL import Image

from telepaste.images import ImageError, looks_like_image, to_png
from tests.helpers import jpeg_bytes, png_bytes


class ImageTests(unittest.TestCase):
    def test_jpeg_becomes_rgb_png(self):
        out = to_png(jpeg_bytes((5, 7)))
        self.assertTrue(out.startswith(b"\x89PNG\r\n\x1a\n"))
        with Image.open(BytesIO(out)) as im:
            self.assertEqual((im.format, im.mode, im.size), ("PNG", "RGB", (5, 7)))

    def test_alpha_is_preserved(self):
        with Image.open(BytesIO(to_png(png_bytes((2, 2), "RGBA")))) as im:
            self.assertEqual(im.mode, "RGBA")

    def test_palette_without_transparency_becomes_rgb(self):
        out = BytesIO()
        Image.new("P", (2, 2)).save(out, format="PNG")
        with Image.open(BytesIO(to_png(out.getvalue()))) as im:
            self.assertEqual(im.mode, "RGB")

    def test_exif_orientation_is_applied(self):
        buf = BytesIO()
        im = Image.new("RGB", (4, 2))
        exif = im.getexif()
        exif[0x0112] = 6  # rotate 90° CW
        im.save(buf, format="JPEG", exif=exif.tobytes())
        with Image.open(BytesIO(to_png(buf.getvalue()))) as rotated:
            self.assertEqual(rotated.size, (2, 4))

    def test_garbage_raises(self):
        with self.assertRaises(ImageError):
            to_png(b"%PDF-1.4 not an image")
        self.assertFalse(looks_like_image(b"nope"))
        self.assertTrue(looks_like_image(jpeg_bytes()))


if __name__ == "__main__":
    unittest.main()
