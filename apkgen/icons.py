"""Launcher icon rendering with Pillow."""
import colorsys
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


def drawable_path(name, legacy=False):
    """Resource path for a 512 px icon: drawable-xxxhdpi (decoded at its real size on any
    phone), or the original generator's drawable/ (treated as mdpi, so decoded ~4x larger)."""
    return f"drawable/{name}.png" if legacy else f"drawable-xxxhdpi/{name}.png"


def frame_colour(frame, frames):
    """Hue depends only on the frame, so every app in sync shows the same colour."""
    r, g, b = colorsys.hsv_to_rgb(frame / frames, 0.75, 0.9)
    return (round(r * 255), round(g * 255), round(b * 255))


def _fitted_font(draw, text, font_path, size, max_width, stroke):
    """Largest font up to `size` whose rendering of text fits max_width."""
    while True:
        font = load_font(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        if bbox[2] - bbox[0] <= max_width or size <= 12:
            return font
        size = int(size * 0.9)


def _draw_centered(draw, text, font, cy, fill=(255, 255, 255), stroke=8):
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
    x = (ICON_SIZE - bbox[0] - bbox[2]) / 2
    y = cy - (bbox[1] + bbox[3]) / 2
    draw.text((x, y), text, fill=fill, font=font, stroke_width=stroke, stroke_fill=(0, 0, 0))


def render_frame_icon(app, frame, frames, font_path):
    """Frame icon of a changing app: frame hue, a ring of `frames` segments with the current
    one filled, the app number large and the frame label small (f0, f1, ...)."""
    img = Image.new("RGB", (ICON_SIZE, ICON_SIZE), color=frame_colour(frame, frames))
    draw = ImageDraw.Draw(img)
    margin, width = 22, 34
    box = (margin, margin, ICON_SIZE - margin, ICON_SIZE - margin)
    step = 360 / frames
    gap = min(4.0, step / 6)
    for k in range(frames):
        start = -90 + k * step + gap
        colour = (255, 255, 255) if k == frame else (0, 0, 0)
        draw.arc(box, start, start + step - 2 * gap, fill=colour, width=width if k == frame else width // 3)
    text = str(app)  # fit inside the ring
    _draw_centered(draw, text, _fitted_font(draw, text, font_path, 240, 330, 8), ICON_SIZE * 0.45)
    _draw_centered(draw, f"f{frame}", _fitted_font(draw, f"f{frame}", font_path, 72, 200, 5),
                   ICON_SIZE * 0.76, stroke=5)
    return png_bytes(img)


def render_caption_icon(app, caption, background, font_path):
    """Plain icon with the app number and a caption (used for the INIT and APP icons)."""
    img = Image.new("RGB", (ICON_SIZE, ICON_SIZE), color=background)
    draw = ImageDraw.Draw(img)
    text = str(app)
    _draw_centered(draw, text, _fitted_font(draw, text, font_path, 240, 440, 8), ICON_SIZE * 0.42)
    _draw_centered(draw, caption, _fitted_font(draw, caption, font_path, 90, 440, 5), ICON_SIZE * 0.78,
                   stroke=5)
    return png_bytes(img)
