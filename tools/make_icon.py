"""Generate app icon (.ico) — purple/teal rounded gradient square.

Run via:  .venv\\Scripts\\python tools\\make_icon.py
Writes:   build/app.ico
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Two radial-gradient blobs blended onto a dark bg, then rounded.
    bg = Image.new("RGBA", (size, size), (16, 18, 28, 255))
    blob1 = _radial(size, (size * 0.28, size * 0.30), size * 0.55, (124, 92, 255, 230))
    blob2 = _radial(size, (size * 0.78, size * 0.78), size * 0.50, (78, 205, 196, 200))
    bg.alpha_composite(blob1)
    bg.alpha_composite(blob2)

    # Round corners
    radius = int(size * 0.22)
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    img.paste(bg, (0, 0), mask)

    return img


def _radial(size: int, center: tuple[float, float], radius: float, color: tuple[int, int, int, int]) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = layer.load()
    cx, cy = center
    r, g, b, a_max = color
    rr = radius * radius
    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            d2 = dx * dx + dy * dy
            if d2 >= rr:
                continue
            t = 1.0 - (d2 / rr)
            a = int(a_max * (t ** 1.6))
            if a > 0:
                px[x, y] = (r, g, b, a)
    return layer.filter(ImageFilter.GaussianBlur(radius=size / 64))


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "app.ico"

    base = make(256)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    base.save(out_path, format="ICO", sizes=sizes)
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
