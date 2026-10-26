"""Build tanomu's hybrid README hero with local, deterministic raster material."""

from io import BytesIO
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source"
SIZE = 1200


def vertical_gradient(size, top, bottom):
    width, height = size
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(height - 1, 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        draw.line((0, y, width, y), fill=color)
    return image


def place(base, layer, center):
    base.alpha_composite(layer, (round(center[0] - layer.width / 2), round(center[1] - layer.height / 2)))


def message_sheet(color_top, color_bottom):
    layer = Image.new("RGBA", (760, 620))
    mask = Image.new("L", layer.size)
    ImageDraw.Draw(mask).rounded_rectangle((100, 110, 630, 470), radius=62, fill=220)

    shadow = Image.new("RGBA", layer.size)
    shadow_mask = mask.filter(ImageFilter.GaussianBlur(28))
    shadow.paste((2, 10, 28, 105), (18, 32), shadow_mask)
    layer.alpha_composite(shadow)

    fill = vertical_gradient(layer.size, color_top, color_bottom)
    fill.putalpha(mask)
    layer.alpha_composite(fill)

    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle((100, 110, 630, 470), radius=62, outline=(235, 245, 255, 150), width=3)
    draw.polygon([(516, 112), (628, 112), (628, 224)], fill=(225, 239, 255, 58))
    draw.line([(516, 112), (628, 224)], fill=(240, 248, 255, 85), width=3)

    highlight = Image.new("RGBA", layer.size)
    highlight_mask = Image.new("L", layer.size)
    ImageDraw.Draw(highlight_mask).ellipse((80, 45, 510, 270), fill=90)
    highlight_mask = highlight_mask.filter(ImageFilter.GaussianBlur(55))
    highlight.paste((255, 255, 255, 80), (0, 0), highlight_mask)
    highlight.putalpha(Image.composite(highlight.getchannel("A"), Image.new("L", layer.size), mask))
    layer.alpha_composite(highlight)
    return layer


def paper_plane():
    layer = Image.new("RGBA", (700, 620))
    shape = Image.new("L", layer.size)
    points = [(88, 278), (606, 96), (410, 514), (314, 340), (218, 414), (238, 316)]
    ImageDraw.Draw(shape).polygon(points, fill=255)

    shadow = Image.new("RGBA", layer.size)
    shadow_mask = shape.filter(ImageFilter.GaussianBlur(24))
    shadow.paste((0, 8, 25, 135), (18, 30), shadow_mask)
    layer.alpha_composite(shadow)

    gradient = vertical_gradient(layer.size, (250, 253, 255, 255), (126, 171, 245, 245))
    gradient.putalpha(shape)
    layer.alpha_composite(gradient)
    draw = ImageDraw.Draw(layer)
    draw.polygon([(88, 278), (606, 96), (314, 340), (238, 316)], fill=(237, 246, 255, 210))
    draw.polygon([(314, 340), (606, 96), (410, 514)], fill=(96, 145, 229, 175))
    draw.line([(606, 96), (314, 340), (410, 514)], fill=(255, 255, 255, 165), width=3)
    draw.line([(314, 340), (218, 414)], fill=(228, 241, 255, 180), width=3)
    return layer


def build_subject():
    subject = Image.new("RGBA", (SIZE, SIZE))
    sheets = [
        (message_sheet((75, 124, 218, 150), (26, 62, 137, 110)), -18, (548, 620)),
        (message_sheet((112, 165, 247, 175), (40, 88, 184, 130)), -5, (602, 578)),
        (message_sheet((159, 199, 255, 190), (66, 118, 218, 150)), 10, (650, 540)),
    ]
    for sheet, angle, center in sheets:
        place(subject, sheet.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True), center)
    place(subject, paper_plane().rotate(-8, resample=Image.Resampling.BICUBIC, expand=True), (680, 424))
    subject.save(SOURCE / "hero-subject.png", optimize=True)
    return subject


def render_svg(source, width, height):
    result = subprocess.run(
        ["rsvg-convert", "-w", str(width), "-h", str(height), str(source)],
        check=True,
        capture_output=True,
    )
    return Image.open(BytesIO(result.stdout)).convert("RGBA")


def compose(subject):
    scale = 2
    hero = render_svg(SOURCE / "hero-layout.svg", 1200 * scale, 520 * scale)
    raster = subject.resize((460 * scale, 460 * scale), Image.Resampling.LANCZOS)
    hero.alpha_composite(raster, (720 * scale, 0))
    hero.alpha_composite(render_svg(SOURCE / "hero-overlay.svg", 1200 * scale, 520 * scale))
    hero.convert("RGB").save(ROOT / "hero.png", optimize=True)


if __name__ == "__main__":
    compose(build_subject())
