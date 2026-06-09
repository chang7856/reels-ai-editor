#!/usr/bin/env python3
"""Generate the Reels AI Editor icon as a 1024x1024 PNG.

Design: chunky pixel-art scissors crossed in an X, with a star/sparkle in
the upper-right. Y2K palette: hot pink, sky blue, cream background, soft
drop shadow. The pixel grid is 32x32 logical cells (each cell = 32 actual
pixels) so the scissors read as deliberately pixel-art at any zoom level.

Outputs:
  assets/icon-1024.png   (master, 1024x1024)
  assets/icon.iconset/   (all resolutions for macOS iconutil)

Build script (scripts/build_icon.sh) converts the iconset to icon.icns
for PyInstaller's BUNDLE.
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter


SIZE = 1024
GRID = 32              # 32x32 chunky cells
CELL = SIZE // GRID    # 32 actual px per cell

# Y2K palette
BG_TOP = (255, 232, 244)      # cream pink
BG_BOT = (236, 224, 255)      # cream lilac
PINK = (255, 107, 181)        # #FF6BB5
PINK_DARK = (210, 70, 145)
BLUE = (91, 194, 255)         # #5BC2FF
BLUE_DARK = (45, 145, 215)
WHITE = (255, 255, 255)
DARK_INK = (40, 28, 60)
STAR_GOLD = (255, 220, 96)
STAR_CORE = (255, 245, 180)


def cell(x, y):
    """Top-left pixel of grid cell (x, y)."""
    return x * CELL, y * CELL


def fill_cell(draw, gx, gy, color):
    px, py = cell(gx, gy)
    draw.rectangle((px, py, px + CELL - 1, py + CELL - 1), fill=color)


def fill_block(draw, gx, gy, w, h, color):
    px, py = cell(gx, gy)
    draw.rectangle((px, py, px + w * CELL - 1, py + h * CELL - 1), fill=color)


def rounded_background():
    """Soft pink-to-lilac gradient rounded square -- the icon "card"."""
    bg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad = Image.new("RGB", (SIZE, SIZE))
    for y in range(SIZE):
        t = y / SIZE
        r = int(BG_TOP[0] * (1 - t) + BG_BOT[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOT[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOT[2] * t)
        for x in range(SIZE):
            grad.putpixel((x, y), (r, g, b))
    mask = Image.new("L", (SIZE, SIZE), 0)
    md = ImageDraw.Draw(mask)
    radius = 220
    md.rounded_rectangle((40, 40, SIZE - 40, SIZE - 40), radius=radius, fill=255)
    bg.paste(grad, (0, 0), mask)
    return bg


# Pixel layouts. Coordinates are (col, row) on the 32x32 grid; (0,0) is
# top-left. We define the scissors as two blade lines drawn in X and two
# finger loops below.
#
# Visual sketch (one "X" pixel = one filled cell):
#
#         . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
#         . . . . . . . . . . . . . . . . . . . . . . . . . S S . . . . .
#         . . . . . . . . . . . . . . . . . . . . . . . . S S S S . . . .
#         . . . X . . . . . . . . . . . . . . . . X . . . . S . . . . . .
#         . . X X X . . . . . . . . . . . . . . X X . . . . . . . . . . .
#         . . . X . . . . . . . . . . . . . . X X . . . . . . . . . . . .
#         . . . . . . . . . . . . . . . . . X X . . . . . . . . . . . . .
#         . . . . . . . . . . . . . . . . X X . . . . . . . . . . . . . .
#         ...
#
# We'll fill it programmatically rather than ASCII to make tweaking easier.


def draw_blade(draw, start_gx, start_gy, end_gx, end_gy, color, thickness=2):
    """Draw a chunky diagonal blade from (start_gx, start_gy) to
    (end_gx, end_gy) on the 32-grid. `thickness` is in grid cells (always
    perpendicular to the diagonal -- we just stamp a 2x2 block per step).
    """
    dx = end_gx - start_gx
    dy = end_gy - start_gy
    steps = max(abs(dx), abs(dy))
    for i in range(steps + 1):
        gx = start_gx + i * dx / steps
        gy = start_gy + i * dy / steps
        # Round and stamp a thickness x thickness block centred on (gx, gy)
        cx = int(round(gx))
        cy = int(round(gy))
        for ox in range(thickness):
            for oy in range(thickness):
                gxx = cx + ox - thickness // 2
                gyy = cy + oy - thickness // 2
                if 0 <= gxx < GRID and 0 <= gyy < GRID:
                    fill_cell(draw, gxx, gyy, color)


def draw_loop(draw, center_gx, center_gy, radius_cells, ring_color, hole_color=None):
    """Draw a chunky pixel-art ring (finger loop)."""
    px_c, py_c = center_gx * CELL + CELL // 2, center_gy * CELL + CELL // 2
    outer = radius_cells * CELL
    inner = max(1, (radius_cells - 2)) * CELL
    draw.ellipse((px_c - outer, py_c - outer, px_c + outer, py_c + outer), fill=ring_color)
    if hole_color is not None:
        draw.ellipse((px_c - inner, py_c - inner, px_c + inner, py_c + inner), fill=hole_color)


def draw_star(draw, center_gx, center_gy, color_outer, color_inner):
    """4-point sparkle star (pixel-y), 5x5 cells."""
    # plus shape arms
    for d in range(3):
        fill_cell(draw, center_gx, center_gy - 2 + d * 0, color_outer)
    # vertical arm
    for dy in range(-2, 3):
        if dy != 0:
            fill_cell(draw, center_gx, center_gy + dy, color_outer)
    # horizontal arm
    for dx in range(-2, 3):
        if dx != 0:
            fill_cell(draw, center_gx + dx, center_gy, color_outer)
    # diagonal sparkle tips at distance 1
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        fill_cell(draw, center_gx + dx, center_gy + dy, color_outer)
    # core
    fill_cell(draw, center_gx, center_gy, color_inner)


def build_icon():
    base = rounded_background()
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # Two crossed scissor blades (pink + blue) meeting near the middle.
    # Blade tips at upper-left and upper-right; loops at bottom-left and
    # bottom-right. The blades cross around grid (16, 16).
    # Pink blade: tip top-left -> pivot center -> heading to bottom-right loop
    draw_blade(draw, 5, 5, 16, 17, PINK, thickness=3)
    draw_blade(draw, 16, 17, 23, 25, PINK, thickness=3)
    # Blue blade: tip top-right -> pivot center -> heading to bottom-left loop
    draw_blade(draw, 26, 5, 16, 17, BLUE, thickness=3)
    draw_blade(draw, 16, 17, 9, 25, BLUE, thickness=3)

    # Highlights to give the blades a metallic pixel sheen
    draw_blade(draw, 6, 6, 14, 15, WHITE, thickness=1)
    draw_blade(draw, 25, 6, 17, 15, WHITE, thickness=1)

    # Pivot rivet at the cross point
    px_c, py_c = cell(16, 17)
    draw.ellipse((px_c - CELL, py_c - CELL, px_c + 2 * CELL, py_c + 2 * CELL), fill=DARK_INK)
    draw.ellipse((px_c - CELL // 2, py_c - CELL // 2, px_c + CELL + CELL // 2, py_c + CELL + CELL // 2), fill=STAR_CORE)

    # Finger loops below
    draw_loop(draw, 23, 26, 4, PINK_DARK, hole_color=None)
    draw_loop(draw, 23, 26, 3, PINK, hole_color=(248, 220, 230))
    draw_loop(draw, 9, 26, 4, BLUE_DARK, hole_color=None)
    draw_loop(draw, 9, 26, 3, BLUE, hole_color=(220, 235, 248))

    # Sparkle in the upper-right corner
    draw_star(draw, 26, 8, STAR_GOLD, STAR_CORE)
    # tiny secondary sparkle
    draw_star(draw, 6, 23, STAR_GOLD, STAR_CORE)

    # Soft drop shadow under the whole scissors set so it pops on the BG.
    shadow_src = layer.split()[3]
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow.paste((30, 18, 60, 80), (0, 18), shadow_src)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=14))

    composed = Image.alpha_composite(base, shadow)
    composed = Image.alpha_composite(composed, layer)
    return composed


def main():
    out_dir = Path(__file__).resolve().parent.parent / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    icon = build_icon()
    master = out_dir / "icon-1024.png"
    icon.save(master)
    print(f"Wrote {master}")

    # Emit the iconset for `iconutil -c icns` (called by build_icon.sh).
    iconset = out_dir / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    # Apple's required sizes (1x and 2x variants):
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    for s in sizes:
        scaled = icon.resize((s, s), Image.LANCZOS)
        scaled.save(iconset / f"icon_{s}x{s}.png")
        if s <= 512:
            # @2x variant lives at 2*s but is named after the @1x size
            scaled2x = icon.resize((s * 2, s * 2), Image.LANCZOS)
            scaled2x.save(iconset / f"icon_{s}x{s}@2x.png")
    print(f"Wrote iconset at {iconset}")


if __name__ == "__main__":
    main()
