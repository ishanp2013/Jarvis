"""Builds a finished PowerPoint deck (16:9) from Jarvis's slide plan.

Layouts: title, bullets, image (text + a free-licence picture with its credit), chart (a real, editable
PowerPoint chart), two_column, statement, and a closing sources slide. Every slide gets speaker notes."""
import datetime as dt

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

NAVY, AMBER, INK, MUTED, PAPER, WHITE = (RGBColor(0x1B, 0x2A, 0x41), RGBColor(0xF2, 0xA5, 0x41), RGBColor(0x1E, 0x23, 0x2B),
                                         RGBColor(0x6B, 0x72, 0x80), RGBColor(0xF7, 0xF7, 0xF2), RGBColor(0xFF, 0xFF, 0xFF))
FONT = "Segoe UI"
W, H = Inches(13.333), Inches(7.5)
CHARTS = {"bar": XL_CHART_TYPE.COLUMN_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED, "pie": XL_CHART_TYPE.PIE,
          "line": XL_CHART_TYPE.LINE_MARKERS, "barh": XL_CHART_TYPE.BAR_CLUSTERED}


def _bg(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _box(slide, x, y, w, h, text="", size=20, color=INK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    p = tf.paragraphs[0]
    p.alignment = align
    r = p.add_run()
    r.text = text
    r.font.size, r.font.bold, r.font.name = Pt(size), bold, FONT
    r.font.color.rgb = color
    return tf


def _bullets(tf, items, size, color=INK):
    first = True
    for item in items:
        p = tf.paragraphs[0] if first and not tf.paragraphs[0].runs else tf.add_paragraph()
        first = False
        p.space_after = Pt(size * 0.45)
        r = p.add_run()
        r.text = "•  " + str(item).strip()
        r.font.size, r.font.name = Pt(size), FONT
        r.font.color.rgb = color


def _fit(items, base=24, width_in=11.5):
    """A font size that keeps bullets on the slide (python-pptx can't measure text, so estimate)."""
    chars = sum(len(str(i)) for i in items)
    lines = sum(max(1, len(str(i)) * base * 0.55 / 72 / width_in + 0.5) for i in items)
    size = base
    while size > 14 and (lines * size * 1.6 / 72 > 4.8 or chars * size > 11000 * width_in / 11.5):
        size -= 2
        lines = sum(max(1, len(str(i)) * size * 0.55 / 72 / width_in + 0.5) for i in items)
    return size


def _header(slide, title, n):
    _bg(slide, WHITE)
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.28), H)
    bar.fill.solid()
    bar.fill.fore_color.rgb = AMBER
    bar.line.fill.background()
    _box(slide, Inches(0.7), Inches(0.45), Inches(12), Inches(1.0), title, 32, NAVY, True, anchor=MSO_ANCHOR.MIDDLE)
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.72), Inches(1.45), Inches(1.4), Emu(38000))
    line.fill.solid()
    line.fill.fore_color.rgb = AMBER
    line.line.fill.background()
    _box(slide, Inches(12.3), Inches(6.95), Inches(0.8), Inches(0.4), str(n), 11, MUTED, align=PP_ALIGN.RIGHT)


def _picture(slide, path, x, y, w, h):
    """Adds the picture as large as fits in the box, keeping its shape, centred."""
    from PIL import Image
    with Image.open(path) as im:
        iw, ih = im.size
    scale = min(w / iw, h / ih)
    pw, ph = int(iw * scale), int(ih * scale)
    slide.shapes.add_picture(path, x + (w - pw) // 2, y + (h - ph) // 2, pw, ph)


def _notes(slide, text):
    if text:
        slide.notes_slide.notes_text_frame.text = str(text)


def build(deck, path, images=None):
    """deck: {'title', 'subtitle', 'slides': [...], 'sources': [{'title', 'url'}]}; images: {slide index: {'path', 'credit'}}."""
    images = images or {}
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    blank = prs.slide_layouts[6]
    credits = []

    # title slide
    s = prs.slides.add_slide(blank)
    _bg(s, NAVY)
    band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(5.2), W, Inches(0.12))
    band.fill.solid()
    band.fill.fore_color.rgb = AMBER
    band.line.fill.background()
    _box(s, Inches(0.9), Inches(1.9), Inches(11.5), Inches(1.9), deck.get("title", "Presentation"), 46, WHITE, True,
         anchor=MSO_ANCHOR.BOTTOM)
    _box(s, Inches(0.9), Inches(3.9), Inches(11.5), Inches(1.0), deck.get("subtitle", ""), 22, AMBER)
    _box(s, Inches(0.9), Inches(5.6), Inches(11.5), Inches(0.6), dt.date.today().strftime("%d %B %Y").lstrip("0"), 14,
         RGBColor(0xC9, 0xCF, 0xD8))
    _notes(s, deck.get("title_notes", ""))

    for i, sl in enumerate(deck.get("slides", [])):
        s = prs.slides.add_slide(blank)
        n = len(prs.slides)
        layout = sl.get("layout", "bullets")
        title = sl.get("title", "")
        bullets = [b for b in sl.get("bullets", []) if str(b).strip()][:7]
        img = images.get(i)
        if layout == "statement":
            _bg(s, NAVY)
            _box(s, Inches(1.2), Inches(1.5), Inches(10.9), Inches(3.6), sl.get("statement") or title, 36, WHITE, True,
                 PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
            if sl.get("statement") and title:
                _box(s, Inches(1.2), Inches(5.3), Inches(10.9), Inches(0.8), title, 18, AMBER, align=PP_ALIGN.CENTER)
        elif layout == "two_column":
            _header(s, title, n)
            for col, x in (("left", Inches(0.7)), ("right", Inches(6.9))):
                items = [b for b in sl.get(col, []) if str(b).strip()][:6]
                size = _fit(items, 20, 5.6)
                _box(s, x, Inches(1.8), Inches(5.7), Inches(0.6), sl.get(f"{col}_title", ""), 22, NAVY, True)
                _bullets(_box(s, x, Inches(2.5), Inches(5.7), Inches(4.3), "", size), items, size)
        elif layout == "chart" and sl.get("chart"):
            _header(s, title, n)
            c = sl["chart"]
            data = CategoryChartData()
            data.categories = [str(x) for x in c["categories"]]
            for ser in c["series"]:
                data.add_series(str(ser.get("name", "")), [float(v) for v in ser["values"]])
            kind = CHARTS.get(c.get("type", "bar"), XL_CHART_TYPE.COLUMN_CLUSTERED)
            text_w = Inches(4.2) if bullets else 0
            gf = s.shapes.add_chart(kind, Inches(0.7) + text_w, Inches(1.8), Inches(12.0) - text_w, Inches(4.9), data)
            ch = gf.chart
            ch.has_title = False  # the slide title says what it shows
            ch.has_legend = kind == XL_CHART_TYPE.PIE or len(c["series"]) > 1
            if ch.has_legend:
                ch.legend.position, ch.legend.include_in_layout = XL_LEGEND_POSITION.BOTTOM, False
            ch.font.size, ch.font.name = Pt(12), FONT
            if kind != XL_CHART_TYPE.PIE:
                ch.plots[0].series[0].format.fill.solid()
                ch.plots[0].series[0].format.fill.fore_color.rgb = NAVY
            if bullets:
                size = _fit(bullets, 18, 3.9)
                _bullets(_box(s, Inches(0.7), Inches(1.9), Inches(4.0), Inches(4.8), "", size), bullets, size)
            if c.get("source"):
                _box(s, Inches(0.7), Inches(6.85), Inches(11), Inches(0.4), "Source: " + str(c["source"])[:150], 10, MUTED)
        elif img:
            _header(s, title, n)
            size = _fit(bullets, 26 if len(bullets) <= 4 else 22, 6.0)
            _bullets(_box(s, Inches(0.7), Inches(1.9), Inches(6.2), Inches(4.9), "", size), bullets, size)
            _picture(s, img["path"], Inches(7.2), Inches(1.8), Inches(5.6), Inches(4.7))
            _box(s, Inches(7.2), Inches(6.55), Inches(5.6), Inches(0.4), img["credit"], 9, MUTED, align=PP_ALIGN.RIGHT)
            credits.append(img["credit"])
        else:
            _header(s, title, n)
            size = _fit(bullets, 30 if len(bullets) <= 4 else 26)
            _bullets(_box(s, Inches(0.7), Inches(1.9), Inches(12.0), Inches(4.9), "", size), bullets, size)
        _notes(s, sl.get("notes", ""))

    # sources
    srcs = deck.get("sources", [])
    if srcs or credits:
        s = prs.slides.add_slide(blank)
        _header(s, "Sources", len(prs.slides))
        lines = [f"{x.get('title', '')} – {x.get('url', '')}" for x in srcs][:8] + credits[:4]
        size = _fit(lines, 18)
        _bullets(_box(s, Inches(0.7), Inches(1.9), Inches(12.0), Inches(5.0), "", size), lines, size, MUTED)
    prs.save(path)
    return len(prs.slides)


def check(path):
    """What the finished file actually contains, read back from disk: slide count and any empty slides."""
    prs = Presentation(path)
    empty = []
    for i, s in enumerate(prs.slides, 1):
        text = " ".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame).strip()
        if len(text) < 3 and not any(sh.shape_type == 13 or sh.has_chart for sh in s.shapes):
            empty.append(i)
    return {"slides": len(prs.slides), "empty": empty}
