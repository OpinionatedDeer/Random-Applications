"""Launcher icon rendering with Pillow."""
import io

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # resolve()/doctor report it; only rendering needs Pillow
    Image = ImageDraw = ImageFont = None

ICON_SIZE = 512


def number_colour(n):
    # "% 255" (not 256) is a historical quirk, kept so existing icons stay byte-identical.
    return (n % 255, (n * 7) % 255, (n * 13) % 255)


def load_font(font_path, size):
    if font_path:
        return ImageFont.truetype(font_path, size)
    return ImageFont.load_default(size=size)


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_number_icon(number, font_path):
    """512x512 icon: background colour derived from the number, the number in white."""
    img = Image.new("RGB", (ICON_SIZE, ICON_SIZE), color=number_colour(number))
    draw = ImageDraw.Draw(img)
    font = load_font(font_path, 256)
    text = str(number)
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (ICON_SIZE - bbox[0] - bbox[2]) / 2
    y = (ICON_SIZE - bbox[1] - bbox[3]) / 2
    draw.text((x, y), text, fill=(255, 255, 255), font=font)
    return png_bytes(img)

