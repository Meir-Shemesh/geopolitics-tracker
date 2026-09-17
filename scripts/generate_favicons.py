"""One-off asset generation: derive the site favicon set from the existing
MS_Logo.png (the same logo already used in every top-nav) - no new design
asset, just standard-size exports so browsers/OSes that look for
conventional filenames (favicon.ico, apple-touch-icon.png) find them.

Run manually whenever the source logo changes; output lives alongside the
source in scripts/assets/, matching that directory's existing role as the
source-of-truth that publish.py's _copy_logo()/_copy_favicons() copy from
into docs/assets/images/ and reports/assets/images/ at build time.
"""

from pathlib import Path

from PIL import Image

SOURCE = Path(__file__).resolve().parent / "assets" / "MS_Logo.png"
OUTPUT_DIR = Path(__file__).resolve().parent / "assets"

# (filename, size) - standard sizes for broad browser/OS support.
PNG_TARGETS = [
    ("favicon-16x16.png", 16),
    ("favicon-32x32.png", 32),
    ("apple-touch-icon.png", 180),
]
ICO_SIZES = (16, 32, 48)


def run() -> None:
    source = Image.open(SOURCE).convert("RGB")

    for filename, size in PNG_TARGETS:
        resized = source.resize((size, size), Image.LANCZOS)
        dest = OUTPUT_DIR / filename
        resized.save(dest)
        print(f"wrote {dest} ({size}x{size})")

    ico_images = [source.resize((s, s), Image.LANCZOS) for s in ICO_SIZES]
    ico_dest = OUTPUT_DIR / "favicon.ico"
    ico_images[-1].save(
        ico_dest,
        format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=ico_images[:-1],
    )
    print(f"wrote {ico_dest} (sizes: {ICO_SIZES})")


if __name__ == "__main__":
    run()
