"""Deterministic 1024x1024 editorial world-news infographic generator."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

CANVAS_SIZE = 1024
MAX_FILE_BYTES = 1024 * 1024  # 1 MiB

# Editorial palette: deep navy canvas, slate-navy cards, warm ivory text.
BG_NAVY = "#0B132B"
HEADER_BG = "#0F1A38"
CARD_BG = "#142244"
CARD_BORDER = "#273B69"
STAT_BG = "#0E1935"
IVORY = "#F5F2EA"
IVORY_MUTED = "#DAE0EC"
META_MUTED = "#B8C4DA"
RULE_GOLD = "#D4A853"
DATE_BG = "#D4A853"
DATE_FG = "#0B132B"

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_PATH = BASE_DIR / "news.json"
DEFAULT_OUTPUT_PATH = BASE_DIR / "output" / "entry.png"

FONT_CANDIDATES = {
    "serif_bold": [
        r"C:\Windows\Fonts\georgiab.ttf",
        r"C:\Windows\Fonts\cambriab.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ],
    "sans_regular": [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ],
    "sans_semibold": [
        r"C:\Windows\Fonts\segoeuisl.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ],
    "sans_bold": [
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
    ],
}


class InfographicError(RuntimeError):
    """Raised when input data, fonts, or layout constraints fail validation."""


def load_font(role: str, size: int) -> ImageFont.FreeTypeFont:
    """Load the first available TrueType font for a semantic role."""
    candidates = FONT_CANDIDATES.get(role, [])
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size)
            except OSError:
                continue
    raise InfographicError(
        f"Could not load a TrueType font for role '{role}'. "
        f"Checked: {', '.join(candidates)}"
    )


def load_news_data(data_path: Path) -> dict[str, Any]:
    """Read and validate the structured news JSON file."""
    if not data_path.is_file():
        raise InfographicError(f"News data file not found: {data_path}")

    try:
        raw = data_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise InfographicError(f"Failed to parse JSON from {data_path}: {exc}") from exc

    required_top = ("edition_date", "title", "subtitle", "footer_note", "stories")
    for field in required_top:
        if field not in data:
            raise InfographicError(f"Missing required top-level field '{field}' in {data_path}")

    stories = data["stories"]
    if not isinstance(stories, list) or len(stories) != 4:
        raise InfographicError(
            f"Expected exactly 4 stories in {data_path}, found {len(stories) if isinstance(stories, list) else type(stories).__name__}"
        )

    required_story = (
        "id",
        "region",
        "topic",
        "accent",
        "icon",
        "headline",
        "stat_value",
        "stat_label",
        "summary",
        "sources",
    )
    for idx, story in enumerate(stories):
        for field in required_story:
            if not isinstance(story, dict) or not str(story.get(field, "")).strip():
                raise InfographicError(f"Story #{idx + 1} is missing non-empty field '{field}'")

    return data


def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
    """Return rendered pixel width for single-line text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return int(bbox[2] - bbox[0])


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
    label: str,
) -> list[str]:
    """Deterministically wrap text to max_width and fail loudly if it exceeds max_lines."""
    words = text.split()
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        if text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            if not current:
                raise InfographicError(
                    f"Single word '{word}' in {label} exceeds max width {max_width}px"
                )
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    if len(lines) > max_lines:
        raise InfographicError(
            f"Text overflow in {label}: wrapped to {len(lines)} lines (max {max_lines}): {lines}"
        )
    return lines


def draw_icon(
    draw: ImageDraw.ImageDraw,
    kind: str,
    cx: int,
    cy: int,
    radius: int,
    accent: str,
) -> None:
    """Draw a deterministic, 2x-supersampled minimalist editorial icon badge."""
    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=STAT_BG,
        outline=accent,
        width=3,
    )
    r = radius * 0.48
    if kind == "shelter":
        # Stylized roof + baseline representing displaced households.
        pts = [(cx, cy - r), (cx + r, cy + r * 0.15), (cx - r, cy + r * 0.15)]
        draw.line(pts + [pts[0]], fill=accent, width=4, joint="curve")
        draw.rectangle((cx - r * 0.55, cy + r * 0.15, cx + r * 0.55, cy + r * 0.85), outline=IVORY, width=3)
    elif kind == "health":
        # Medical cross for emergency health response.
        arm = r * 0.32
        draw.rectangle((cx - arm, cy - r * 0.85, cx + arm, cy + r * 0.85), fill=accent)
        draw.rectangle((cx - r * 0.85, cy - arm, cx + r * 0.85, cy + arm), fill=accent)
    elif kind == "trophy":
        # Minimalist cup + base for CAS sports ruling.
        draw.polygon(
            [
                (cx - r * 0.72, cy - r * 0.75),
                (cx + r * 0.72, cy - r * 0.75),
                (cx + r * 0.42, cy + r * 0.15),
                (cx - r * 0.42, cy + r * 0.15),
            ],
            outline=accent,
            width=4,
        )
        draw.line((cx, cy + r * 0.15, cx, cy + r * 0.75), fill=accent, width=4)
        draw.line((cx - r * 0.52, cy + r * 0.78, cx + r * 0.52, cy + r * 0.78), fill=IVORY, width=4)
    elif kind == "orbit":
        # Tilted orbital ring + planet + spacecraft for Tiangong / Shenzhou-24.
        pts = []
        for deg in range(0, 365, 10):
            rad = math.radians(deg)
            rx = r * 0.95 * math.cos(rad)
            ry = r * 0.36 * math.sin(rad)
            # Rotate -28 degrees for an unmistakable orbital trajectory.
            ang = math.radians(-28)
            px = cx + rx * math.cos(ang) - ry * math.sin(ang)
            py = cy + rx * math.sin(ang) + ry * math.cos(ang)
            pts.append((px, py))
        draw.line(pts, fill=accent, width=3, joint="curve")
        draw.ellipse((cx - r * 0.32, cy - r * 0.32, cx + r * 0.32, cy + r * 0.32), fill=IVORY)
        orb_x, orb_y = pts[4]
        draw.ellipse((orb_x - 5, orb_y - 5, orb_x + 5, orb_y + 5), fill=accent)
    else:
        raise InfographicError(f"Unsupported icon type '{kind}'")


def build_base_layer(data: dict[str, Any]) -> Image.Image:
    """Render vector geometry at 2x resolution and downsample cleanly to 1024x1024."""
    scale = 2
    hi = Image.new("RGB", (CANVAS_SIZE * scale, CANVAS_SIZE * scale), BG_NAVY)
    draw = ImageDraw.Draw(hi)

    # Top editorial masthead panel.
    draw.rectangle((0, 0, CANVAS_SIZE * scale, 134 * scale), fill=HEADER_BG)
    draw.line((36 * scale, 134 * scale, (CANVAS_SIZE - 36) * scale, 134 * scale), fill=RULE_GOLD, width=3 * scale)

    # Subtle decorative top accent rule.
    draw.rectangle((0, 0, CANVAS_SIZE * scale, 6 * scale), fill=RULE_GOLD)

    # Prominent date pill on top right (exact string "24 NOVEMBER 2026").
    date_x0, date_y0, date_x1, date_y1 = 690 * scale, 30 * scale, 988 * scale, 80 * scale
    draw.rounded_rectangle((date_x0, date_y0, date_x1, date_y1), radius=8 * scale, fill=DATE_BG)

    # 2x2 grid cards.
    card_positions = [
        (36, 156, 498, 542),
        (526, 156, 988, 542),
        (36, 566, 498, 952),
        (526, 566, 988, 952),
    ]
    for story, (x0, y0, x1, y1) in zip(data["stories"], card_positions):
        accent = story["accent"]
        draw.rounded_rectangle(
            (x0 * scale, y0 * scale, x1 * scale, y1 * scale),
            radius=14 * scale,
            fill=CARD_BG,
            outline=CARD_BORDER,
            width=2 * scale,
        )
        # Colored top accent strip inside card.
        draw.rounded_rectangle(
            ((x0 + 18) * scale, (y0 + 14) * scale, (x1 - 18) * scale, (y0 + 20) * scale),
            radius=3 * scale,
            fill=accent,
        )
        # Stat highlight band.
        draw.rounded_rectangle(
            ((x0 + 20) * scale, (y0 + 142) * scale, (x1 - 20) * scale, (y0 + 200) * scale),
            radius=8 * scale,
            fill=STAT_BG,
            outline=CARD_BORDER,
            width=1 * scale,
        )
        # Editorial icon badge on top right of card.
        draw_icon(
            draw,
            kind=story["icon"],
            cx=(x1 - 42) * scale,
            cy=(y0 + 50) * scale,
            radius=18 * scale,
            accent=accent,
        )
        # Thin divider above sources.
        draw.line(
            ((x0 + 20) * scale, (y1 - 44) * scale, (x1 - 20) * scale, (y1 - 44) * scale),
            fill=CARD_BORDER,
            width=1 * scale,
        )

    # Bottom footer separator.
    draw.line((36 * scale, 968 * scale, (CANVAS_SIZE - 36) * scale, 968 * scale), fill=CARD_BORDER, width=1 * scale)

    return hi.resize((CANVAS_SIZE, CANVAS_SIZE), resample=Image.Resampling.LANCZOS)


def render_infographic(data_path: Path, output_path: Path) -> Path:
    """Generate the 1024x1024 deterministic PNG infographic and validate size."""
    data = load_news_data(data_path)

    fonts = {
        "masthead": load_font("serif_bold", 42),
        "subtitle": load_font("sans_regular", 18),
        "date": load_font("sans_bold", 25),
        "tag": load_font("sans_bold", 16),
        "headline": load_font("serif_bold", 25),
        "stat_val": load_font("sans_bold", 26),
        "stat_lbl": load_font("sans_semibold", 17),
        "summary": load_font("sans_regular", 19),
        "sources": load_font("sans_semibold", 16),
        "footer": load_font("sans_regular", 15),
    }

    canvas = build_base_layer(data)
    draw = ImageDraw.Draw(canvas)

    # Masthead title & subtitle.
    draw.text((36, 26), data["title"], font=fonts["masthead"], fill=IVORY)
    subtitle_lines = wrap_text(
        draw, data["subtitle"], fonts["subtitle"], max_width=636, max_lines=1, label="subtitle"
    )
    draw.text((36, 86), subtitle_lines[0], font=fonts["subtitle"], fill=IVORY_MUTED)

    # Exact date centered inside the top-right gold badge.
    date_text = data["edition_date"]
    badge_cx = (690 + 988) // 2
    badge_cy = (30 + 80) // 2
    draw.text(
        (badge_cx, badge_cy),
        date_text,
        font=fonts["date"],
        fill=DATE_FG,
        anchor="mm",
    )

    # Edition sub-label below date badge.
    edition_meta = "VERIFIED DAILY EDITION · 4 STORIES"
    meta_w = text_width(draw, edition_meta, fonts["tag"])
    draw.text((988 - meta_w, 90), edition_meta, font=fonts["tag"], fill=RULE_GOLD)

    # Render each of the 4 cards.
    card_positions = [
        (36, 156, 498, 542),
        (526, 156, 988, 542),
        (36, 566, 498, 952),
        (526, 566, 988, 952),
    ]
    for story, (x0, y0, x1, y1) in zip(data["stories"], card_positions):
        accent = story["accent"]
        inner_x = x0 + 20
        text_max_w = (x1 - 20) - inner_x

        # Region & topic label.
        tag_text = f"{story['region']}  ·  {story['topic']}"
        draw.text((inner_x, y0 + 36), tag_text, font=fonts["tag"], fill=accent)

        # Headline (up to 2 lines, leaving space clear of the icon).
        headline_lines = wrap_text(
            draw,
            story["headline"],
            fonts["headline"],
            max_width=text_max_w - 46,
            max_lines=2,
            label=f"{story['id']} headline",
        )
        hy = y0 + 68
        for line in headline_lines:
            draw.text((inner_x, hy), line, font=fonts["headline"], fill=IVORY)
            hy += 31

        # Stat value + label inside stat strip (y0+142 to y0+200).
        stat_val = story["stat_value"]
        stat_x = inner_x + 14
        val_bbox = draw.textbbox((0, 0), stat_val, font=fonts["stat_val"])
        val_w = val_bbox[2] - val_bbox[0]
        draw.text((stat_x, y0 + 153), stat_val, font=fonts["stat_val"], fill=accent)

        lbl_x = stat_x + val_w + 14
        lbl_max_w = (x1 - 30) - lbl_x
        lbl_lines = wrap_text(
            draw,
            story["stat_label"],
            fonts["stat_lbl"],
            max_width=lbl_max_w,
            max_lines=2,
            label=f"{story['id']} stat_label",
        )
        if len(lbl_lines) == 1:
            draw.text((lbl_x, y0 + 161), lbl_lines[0], font=fonts["stat_lbl"], fill=IVORY_MUTED)
        else:
            draw.text((lbl_x, y0 + 149), lbl_lines[0], font=fonts["stat_lbl"], fill=IVORY_MUTED)
            draw.text((lbl_x, y0 + 171), lbl_lines[1], font=fonts["stat_lbl"], fill=IVORY_MUTED)

        # Factual summary (up to 4 lines).
        summary_lines = wrap_text(
            draw,
            story["summary"],
            fonts["summary"],
            max_width=text_max_w,
            max_lines=4,
            label=f"{story['id']} summary",
        )
        sy = y0 + 214
        for line in summary_lines:
            draw.text((inner_x, sy), line, font=fonts["summary"], fill=IVORY_MUTED)
            sy += 27

        # Source attribution pinned to card footer.
        src_text = f"SOURCES: {story['sources']}"
        src_lines = wrap_text(
            draw,
            src_text,
            fonts["sources"],
            max_width=text_max_w,
            max_lines=1,
            label=f"{story['id']} sources",
        )
        draw.text((inner_x, y1 - 32), src_lines[0], font=fonts["sources"], fill=META_MUTED)

    # Footer note.
    footer_lines = wrap_text(
        draw,
        data["footer_note"],
        fonts["footer"],
        max_width=CANVAS_SIZE - 72,
        max_lines=1,
        label="footer_note",
    )
    draw.text((36, 982), footer_lines[0], font=fonts["footer"], fill=META_MUTED)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Use deterministic PNG encoding without timestamps or ancillary volatile chunks.
    canvas.save(output_path, format="PNG", optimize=True, compress_level=9)

    size_bytes = output_path.stat().st_size
    if size_bytes >= MAX_FILE_BYTES:
        raise InfographicError(
            f"Generated PNG exceeds 1 MiB limit: {size_bytes} bytes ({output_path})"
        )

    return output_path


def main() -> int:
    """CLI entrypoint."""
    try:
        out = render_infographic(DEFAULT_DATA_PATH, DEFAULT_OUTPUT_PATH)
    except InfographicError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI error message
        print(f"UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 1

    size_kb = out.stat().st_size / 1024
    print(f"Generated {out} (1024x1024, {size_kb:.1f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
