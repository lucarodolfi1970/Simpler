"""Makes the pictures of the setup wizard from the splash and the icon of the app (run by Build-Setup.bat).
Large (left of the first and last page): 164x314, 192x386, 246x459. Small (top right of the other pages): 55x58, 64x68, 83x80.
Usage: python make_wizard_images.py <folder of the app sources (with splash.jpg and Simpler.ico)> <output folder>"""
import sys, os
from PIL import Image, ImageDraw, ImageFilter

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
splash = Image.open(os.path.join(src, "splash.jpg")).convert("RGB")
ico = Image.open(os.path.join(src, "Simpler.ico"))
try:
    ico.size = max(ico.info.get("sizes", {(256, 256)}))
except Exception:
    pass
ico = ico.convert("RGBA")


def big(w, h):
    # the rings of the splash (the right part) on the blue of the splash, the icon above, a dark fade at the bottom
    im = Image.new("RGB", (w, h), (13, 33, 74))
    rings = splash.crop((520, 40, 1170, 560))          # both rings
    s = h * 0.62 / rings.height
    rings = rings.resize((int(rings.width * s), int(rings.height * s)), Image.LANCZOS)
    x = -int((rings.width - w) * 0.55)
    im.paste(rings, (x, int(h * 0.30)))
    fade = Image.new("L", (1, h))
    for y in range(h):
        t = y / h
        fade.putpixel((0, y), int(255 * max(0, min(1, (0.34 - t) / 0.12 + 1))) if t < 0.34 else 0)
    shade = Image.new("RGB", (w, h), (13, 33, 74))
    im = Image.composite(shade, im, fade.resize((w, h)))
    ic = ico.resize((int(w * 0.42), int(w * 0.42)), Image.LANCZOS)
    im.paste(ic, ((w - ic.width) // 2, int(h * 0.06)), ic)
    d = ImageDraw.Draw(im)
    d.rectangle([0, h - 3, w, h], fill=(46, 134, 255))
    return im


def small(w, h):
    im = Image.new("RGB", (w, h), (255, 255, 255))
    ic = ico.resize((min(w, h) - 6, min(w, h) - 6), Image.LANCZOS)
    im.paste(ic, ((w - ic.width) // 2, (h - ic.height) // 2), ic)
    return im


for w, h in ((164, 314), (192, 386), (246, 459)):
    big(w, h).save(os.path.join(out, f"wizard-{w}.bmp"))
for w, h in ((55, 58), (64, 68), (83, 80)):
    small(w, h).save(os.path.join(out, f"small-{w}.bmp"))
