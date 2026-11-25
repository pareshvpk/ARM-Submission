"""Generate the PS3 Sentinel launcher, splash and README icons from docs/logo_source.png.

The launcher icon is a plain transparent PNG, so launchers draw the logo straight
on the wallpaper with no plate, circle or adaptive background behind it.

Pillow only. Run with:
    python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "docs" / "logo_source.png"
RES = REPO / "android" / "app" / "src" / "main" / "res"

MIPMAP_SIZES = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}


def load_cropped() -> Image.Image:
    """Load the source and crop it to its alpha bounding box."""
    img = Image.open(SOURCE).convert("RGBA")
    # Removes the glow halo of the source art
    ALPHA_CUT = 240
    alpha = img.getchannel("A").point(lambda a: 255 if a >= ALPHA_CUT else 0)
    img.putalpha(alpha)
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    return img


def scaled(img: Image.Image, target_width: int) -> Image.Image:
    ratio = target_width / img.width
    size = (max(1, round(img.width * ratio)), max(1, round(img.height * ratio)))
    return img.resize(size, Image.LANCZOS)


def paste_centred(canvas: Image.Image, img: Image.Image) -> Image.Image:
    x = (canvas.width - img.width) // 2
    y = (canvas.height - img.height) // 2
    canvas.alpha_composite(img, (x, y))
    return canvas


def write(path: Path, img: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    print(f"{path.relative_to(REPO)} {img.width}x{img.height}")


def main() -> None:
    logo = load_cropped()

    # a. Launcher icon: plain transparent PNG, no plate or mask. The art is
    #    wider than tall, so scaling it to 100% of the canvas width fills the
    #    square edge to edge with full transparency above and below it.
    for density, size in MIPMAP_SIZES.items():
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        art = scaled(logo, size)
        write(RES / f"mipmap-{density}" / "ic_launcher.png",
              paste_centred(canvas, art))

    # b. Splash icon: 960x960 transparent, art width 500 px.
    splash = Image.new("RGBA", (960, 960), (0, 0, 0, 0))
    write(RES / "drawable-nodpi" / "splash_logo.png",
          paste_centred(splash, scaled(logo, 500)))

    # c. README logo: 512x512 transparent, art at 92% width.
    doc = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    write(REPO / "docs" / "logo.png", paste_centred(doc, scaled(logo, round(512 * 0.92))))


if __name__ == "__main__":
    main()
