"""Layout kit for the Project Atlas technical overview PDF (ReportLab).

Styles, page templates, reusable flowables (callouts, stat tiles, code blocks, figures)
and vector diagrams drawn with reportlab.graphics. Colours follow the Atlas UI palette
(frontend/src/index.css) so the document matches the product.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from reportlab.graphics.shapes import Circle, Drawing, Ellipse, Group, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, Image, KeepTogether, NextPageTemplate, PageBreak, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

# ------------------------------------------------------------------------------------------------ fonts
_FONT_DIRS = {
    "Body": "/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf",
    "Body-Bold": "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
    "Body-Italic": "/usr/share/fonts/truetype/crosextra/Carlito-Italic.ttf",
    "Body-BoldItalic": "/usr/share/fonts/truetype/crosextra/Carlito-BoldItalic.ttf",
    "Mono": "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Regular.ttf",
    "Mono-Bold": "/usr/share/fonts/truetype/jetbrains-mono/JetBrainsMono-Bold.ttf",
    "Sym": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}
for _name, _path in _FONT_DIRS.items():
    pdfmetrics.registerFont(TTFont(_name, _path))
pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-BoldItalic")
pdfmetrics.registerFontFamily("Mono", normal="Mono", bold="Mono-Bold", italic="Mono", boldItalic="Mono-Bold")

# ------------------------------------------------------------------------------------------------ palette
INK = colors.HexColor("#151B23")
TEXT = colors.HexColor("#1F2933")
MUTED = colors.HexColor("#5C6A78")
LINE = colors.HexColor("#D0D8E0")
RAISED = colors.HexColor("#F1F4F7")
ACCENT = colors.HexColor("#2B6FA0")
ACCENT_2 = colors.HexColor("#4FA3D9")
ACCENT_DEEP = colors.HexColor("#1D4E73")
PALE = colors.HexColor("#E8F1F8")
OK = colors.HexColor("#268456")
OK_PALE = colors.HexColor("#E6F3EC")
WARN = colors.HexColor("#B07814")
WARN_PALE = colors.HexColor("#FBF1DE")
DANGER = colors.HexColor("#BA3434")
DANGER_PALE = colors.HexColor("#F8E5E5")
HYPO = colors.HexColor("#8E5CBE")
HYPO_PALE = colors.HexColor("#F1EAF8")
WHITE = colors.white

PAGE_W, PAGE_H = A4
MARGIN_L = MARGIN_R = 54
MARGIN_T = 66
MARGIN_B = 58
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

# ------------------------------------------------------------------------------------------------ styles
STY = {
    "body": ParagraphStyle("body", fontName="Body", fontSize=10.5, leading=14.8, textColor=TEXT, spaceAfter=6),
    "lead": ParagraphStyle("lead", fontName="Body", fontSize=12.2, leading=17.5, textColor=MUTED, spaceAfter=10),
    "small": ParagraphStyle("small", fontName="Body", fontSize=9, leading=12.4, textColor=TEXT),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=9, leading=11.8, textColor=TEXT),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=9, leading=11.8, textColor=INK),
    "cellh": ParagraphStyle("cellh", fontName="Body-Bold", fontSize=8, leading=10, textColor=MUTED),
    "cellm": ParagraphStyle("cellm", fontName="Mono", fontSize=7.6, leading=10.4, textColor=ACCENT_DEEP),
    "h2": ParagraphStyle("h2", fontName="Body-Bold", fontSize=15, leading=19, textColor=INK, spaceBefore=12, spaceAfter=6),
    "h3": ParagraphStyle("h3", fontName="Body-Bold", fontSize=11.5, leading=15, textColor=ACCENT, spaceBefore=8, spaceAfter=3),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=10.5, leading=14.6, textColor=TEXT, leftIndent=14,
                             bulletIndent=3, spaceAfter=3.2),
    "caption": ParagraphStyle("caption", fontName="Body-Italic", fontSize=8.8, leading=11.5, textColor=MUTED,
                              spaceBefore=4, spaceAfter=10),
    "code": ParagraphStyle("code", fontName="Mono", fontSize=8, leading=11.2, textColor=INK),
    "callout_t": ParagraphStyle("callout_t", fontName="Body-Bold", fontSize=10, leading=13.5, textColor=INK, spaceAfter=2),
    "callout": ParagraphStyle("callout", fontName="Body", fontSize=9.8, leading=13.8, textColor=TEXT),
    "toc0": ParagraphStyle("toc0", fontName="Body-Bold", fontSize=10.8, leading=13, textColor=INK, spaceBefore=1.8,
                           leftIndent=0, firstLineIndent=0),
    "toc1": ParagraphStyle("toc1", fontName="Body", fontSize=9.3, leading=12.2, textColor=MUTED, leftIndent=22,
                           firstLineIndent=0),
}


def P(text: str, style: str = "body", **kw) -> Paragraph:
    st = STY[style] if not kw else ParagraphStyle(f"{style}_x", parent=STY[style], **kw)
    return Paragraph(text, st)


def code_inline(t: str) -> str:
    return f'<font name="Mono" size="8.6" color="#1D4E73">{t}</font>'


C = code_inline  # short alias used in content


def sym(t: str) -> str:
    return f'<font name="Sym">{t}</font>'


CHECK = f'<font name="Sym" color="#268456">✓</font>'
CROSS = f'<font name="Sym" color="#BA3434">✗</font>'
DOT = f'<font name="Sym" color="#9AA8B6">·</font>'


# ------------------------------------------------------------------------------------------------ flowables
class ChapterHeading(Flowable):
    """Chapter opener: large number, title and an accent rule beneath the number only."""

    def __init__(self, number: str, title: str, kicker: str = "", in_toc: bool = True):
        super().__init__()
        self.number, self.title, self.kicker = number, title, kicker
        self.toc_entry = (0, f"{number}  {title}" if number else title) if in_toc else None
        self.chapter_title = title
        self.height = 92

    def wrap(self, aw, ah):
        self.width = aw
        return aw, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(ACCENT)
        c.setFont("Body-Bold", 10)
        label = (self.kicker or ("CHAPTER " + self.number if self.number else "")).upper()
        c.drawString(0, self.height - 12, " ".join(label))  # letter-spaced
        num_w = 0
        if self.number:
            c.setFillColor(PALE)
            c.setFont("Body-Bold", 64)
            c.drawRightString(self.width, self.height - 58, self.number)
            num_w = pdfmetrics.stringWidth(self.number, "Body-Bold", 64) + 14
        size = 28
        while size > 18 and pdfmetrics.stringWidth(self.title, "Body-Bold", size) > self.width - num_w:
            size -= 0.5
        c.setFillColor(INK)
        c.setFont("Body-Bold", size)
        c.drawString(0, self.height - 50, self.title)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.8)
        c.line(0, 18, self.width, 18)


class H2(Paragraph):
    def __init__(self, text: str):
        super().__init__(text, STY["h2"])
        self.toc_entry = (1, text)


def h2(text: str) -> list:
    # never strand a heading at the foot of a page, but let long tables after it split normally
    from reportlab.platypus import CondPageBreak

    return [CondPageBreak(124), H2(text)]


def h3(text: str) -> list:
    from reportlab.platypus import CondPageBreak

    return [CondPageBreak(72), Paragraph(text, STY["h3"])]


def bullets(items: list[str], style: str = "bullet") -> list[Paragraph]:
    return [Paragraph(t, STY[style], bulletText="•") for t in items]


def table(rows: list[list], widths: list[float], *, header: bool = True, zebra: bool = True, mono_cols: tuple = (),
          bold_first: bool = False, font_size: float | None = None, valign: str = "TOP", pad: float = 4.2,
          col_align: dict | None = None) -> Table:
    """Rows of strings/flowables -> styled table. Widths are fractions of CONTENT_W when all <= 1."""
    if all(w <= 1 for w in widths):
        widths = [w * CONTENT_W for w in widths]
    data = []
    for ri, row in enumerate(rows):
        out = []
        for ci, cell in enumerate(row):
            if isinstance(cell, Flowable):
                out.append(cell)
                continue
            if header and ri == 0:
                st = STY["cellh"]
                cell = str(cell).upper()
            elif ci in mono_cols:
                st = STY["cellm"]
            elif bold_first and ci == 0:
                st = STY["cellb"]
            else:
                st = STY["cell"]
            if font_size and not (header and ri == 0):
                st = ParagraphStyle(st.name + "fs", parent=st, fontSize=font_size, leading=font_size * 1.32)
            if col_align and ci in col_align:
                st = ParagraphStyle(st.name + "al", parent=st, alignment=col_align[ci])
            out.append(Paragraph(str(cell), st))
        data.append(out)
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), valign),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), pad),
        ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
    ]
    if header:
        cmds += [("BACKGROUND", (0, 0), (-1, 0), RAISED), ("LINEBELOW", (0, 0), (-1, 0), 0.9, colors.HexColor("#B8C4D0"))]
    if zebra:
        for i in range(1 if header else 0, len(data)):
            if (i - (1 if header else 0)) % 2 == 1:
                cmds.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC")))
    t.setStyle(TableStyle(cmds))
    t.spaceBefore = 2
    t.spaceAfter = 8
    return t


_CALLOUT = {
    "info": (PALE, ACCENT_DEEP), "ok": (OK_PALE, OK), "warn": (WARN_PALE, WARN), "danger": (DANGER_PALE, DANGER),
    "hypo": (HYPO_PALE, HYPO), "neutral": (RAISED, INK),
}


def callout(title: str, body: str | list, kind: str = "info", width: float | None = None) -> Table:
    bg, fg = _CALLOUT[kind]
    t_style = ParagraphStyle("ct" + kind, parent=STY["callout_t"], textColor=fg)
    content = [Paragraph(title, t_style)] if title else []
    if isinstance(body, str):
        content.append(Paragraph(body, STY["callout"]))
    else:
        content += [Paragraph(b, ParagraphStyle("cb", parent=STY["callout"], leftIndent=10, bulletIndent=0,
                                                spaceAfter=1.5), bulletText="•") for b in body]
    t = Table([[content]], colWidths=[width or CONTENT_W], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), bg), ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("ROUNDEDCORNERS", [5, 5, 5, 5]),
    ]))
    return t


def code_block(text: str, width: float | None = None) -> Table:
    lines = text.strip("\n").split("\n")
    esc = [ln.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(" ", "&nbsp;") for ln in lines]
    para = Paragraph("<br/>".join(esc), STY["code"])
    t = Table([[para]], colWidths=[width or CONTENT_W], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), RAISED), ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    return t


def stat_tiles(items: list[tuple[str, str]], cols: int = 3, width: float | None = None) -> Table:
    width = width or CONTENT_W
    gap = 8
    cw = (width - gap * (cols - 1)) / cols
    cells = []
    for v, label in items:
        cells.append([Paragraph(v, ParagraphStyle("sv", fontName="Body-Bold", fontSize=24, leading=27, textColor=ACCENT)),
                      Paragraph(label, ParagraphStyle("sl", fontName="Body", fontSize=9, leading=11.5, textColor=MUTED))])
    rows = []
    for i in range(0, len(cells), cols):
        if rows:
            rows.append([""] * (2 * cols - 1))  # spacer row
        row = []
        for j in range(cols):
            if j:
                row.append("")
            row.append(cells[i + j] if i + j < len(cells) else "")
        rows.append(row)
    widths = []
    for j in range(cols):
        if j:
            widths.append(gap)
        widths.append(cw)
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    cmds = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10), ("LEFTPADDING", (0, 0), (-1, -1), 11)]
    for ri in range(len(rows)):
        if ri % 2 == 1:  # spacer rows
            cmds += [("TOPPADDING", (0, ri), (-1, ri), 0), ("BOTTOMPADDING", (0, ri), (-1, ri), 0)]
            continue
        for j in range(cols):
            col = j * 2
            cmds.append(("BACKGROUND", (col, ri), (col, ri), PALE))
    t = Table(rows, colWidths=widths, rowHeights=[None if r % 2 == 0 else 8 for r in range(len(rows))], hAlign="LEFT")
    t.setStyle(TableStyle(cmds))
    return t


class FigureCounter:
    n = 0


def figure(flowable, caption: str, keep: bool = True) -> list:
    FigureCounter.n += 1
    cap = Paragraph(f"<b>Figure {FigureCounter.n}</b> — {caption}", STY["caption"])
    items = [Spacer(1, 4), flowable, cap]
    return [KeepTogether(items)] if keep else items


def screenshot(path: str | Path, caption: str, width: float | None = None) -> list:
    width = width or CONTENT_W
    from PIL import Image as PILImage

    w, h = PILImage.open(path).size
    img = Image(str(path), width=width, height=width * h / w)
    framed = Table([[img]], colWidths=[width + 2], hAlign="LEFT")
    framed.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 1),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return figure(framed, caption)


def screenshot_pair(left: tuple, right: tuple, caption: str) -> list:
    """Two screenshots side by side: (path, label) each."""
    gap = 10
    w = (CONTENT_W - gap) / 2
    from PIL import Image as PILImage

    cells = []
    for path, label in (left, right):
        iw, ih = PILImage.open(path).size
        img = Image(str(path), width=w - 2, height=(w - 2) * ih / iw)
        inner = Table([[img]], colWidths=[w])
        inner.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 1),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 1), ("TOPPADDING", (0, 0), (-1, -1), 1),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
        cells.append([inner, Paragraph(label, ParagraphStyle("pl", parent=STY["small"], textColor=MUTED, spaceBefore=3))])
    t = Table([[cells[0], "", cells[1]]], colWidths=[w, gap, w], hAlign="LEFT")
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return figure(t, caption)


# ------------------------------------------------------------------------------------------------ drawing helpers
def wrap(text: str, font: str, size: float, maxw: float) -> list[str]:
    out = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for w in words:
            cand = (line + " " + w).strip()
            if pdfmetrics.stringWidth(cand, font, size) <= maxw or not line:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def box(g: Group, x, y, w, h, *, fill=WHITE, stroke=LINE, title="", body="", title_color=INK, body_color=MUTED,
        title_size=9.5, body_size=7.8, radius=5, align="center", stroke_w=0.8, pad=6, title_font="Body-Bold"):
    g.add(Rect(x, y, w, h, rx=radius, ry=radius, fillColor=fill, strokeColor=stroke, strokeWidth=stroke_w))
    lines_t = wrap(title, title_font, title_size, w - 2 * pad) if title else []
    lines_b = wrap(body, "Body", body_size, w - 2 * pad) if body else []
    th = len(lines_t) * title_size * 1.18
    bh = len(lines_b) * body_size * 1.25
    total = th + bh + (3 if lines_t and lines_b else 0)
    cy = y + h / 2 + total / 2
    for ln in lines_t:
        cy -= title_size * 1.0
        _txt(g, x, w, cy, ln, title_font, title_size, title_color, align, pad)
        cy -= title_size * 0.18
    if lines_t and lines_b:
        cy -= 3
    for ln in lines_b:
        cy -= body_size * 1.0
        _txt(g, x, w, cy, ln, "Body", body_size, body_color, align, pad)
        cy -= body_size * 0.25


def _txt(g, x, w, y, s, font, size, color, align, pad):
    if align == "center":
        g.add(String(x + w / 2, y, s, fontName=font, fontSize=size, fillColor=color, textAnchor="middle"))
    else:
        g.add(String(x + pad, y, s, fontName=font, fontSize=size, fillColor=color))


def text(g: Group, x, y, s, *, size=8, color=MUTED, font="Body", anchor="start"):
    g.add(String(x, y, s, fontName=font, fontSize=size, fillColor=color, textAnchor=anchor))


def arrow(g: Group, x1, y1, x2, y2, *, color=MUTED, width=1.0, head=5.0, dash=None):
    ang = math.atan2(y2 - y1, x2 - x1)
    ex, ey = x2 - head * 0.8 * math.cos(ang), y2 - head * 0.8 * math.sin(ang)
    g.add(Line(x1, y1, ex, ey, strokeColor=color, strokeWidth=width, strokeDashArray=dash))
    p1 = (x2 - head * math.cos(ang - 0.42), y2 - head * math.sin(ang - 0.42))
    p2 = (x2 - head * math.cos(ang + 0.42), y2 - head * math.sin(ang + 0.42))
    g.add(Polygon([x2, y2, p1[0], p1[1], p2[0], p2[1]], fillColor=color, strokeColor=color, strokeWidth=0.1))


def chip_flow(g: Group, x, y_top, w, labels: list[str], *, fill=PALE, color=ACCENT_DEEP, size=7.6, h=13, gap=4,
              font="Body") -> float:
    """Lay out chips left-to-right, wrapping; returns the y of the bottom edge."""
    cx, cy = x, y_top - h
    for lab in labels:
        cw = pdfmetrics.stringWidth(lab, font, size) + 10
        if cx + cw > x + w:
            cx = x
            cy -= h + gap
        g.add(Rect(cx, cy, cw, h, rx=3, ry=3, fillColor=fill, strokeColor=None))
        g.add(String(cx + cw / 2, cy + h / 2 - size * 0.34, lab, fontName=font, fontSize=size, fillColor=color,
                     textAnchor="middle"))
        cx += cw + gap
    return cy


def hbar_chart(items: list[tuple[str, float]], *, width=CONTENT_W, bar_h=11, gap=5, label_w=150, color=ACCENT,
               value_fmt=lambda v: f"{v:,.0f}", unit="", highlight: set | None = None, max_v=None, title="") -> Drawing:
    n = len(items)
    top_pad = 16 if title else 4
    h = n * (bar_h + gap) + top_pad + 4
    d = Drawing(width, h)
    mv = max_v or max(v for _, v in items)
    plot_w = width - label_w - 60
    if title:
        d.add(String(0, h - 10, title, fontName="Body-Bold", fontSize=9, fillColor=INK))
    for i, (lab, v) in enumerate(items):
        y = h - top_pad - (i + 1) * (bar_h + gap) + gap
        d.add(String(label_w - 8, y + bar_h / 2 - 3, lab, fontName="Body", fontSize=8.3, fillColor=TEXT, textAnchor="end"))
        bw = max(1.5, plot_w * v / mv)
        col = WARN if highlight and lab in highlight else color
        d.add(Rect(label_w, y, bw, bar_h, rx=2, ry=2, fillColor=col, strokeColor=None))
        d.add(String(label_w + bw + 5, y + bar_h / 2 - 3, value_fmt(v) + unit, fontName="Body-Bold", fontSize=8,
                     fillColor=INK))
    d.add(Line(label_w, 2, label_w, h - top_pad + 2, strokeColor=LINE, strokeWidth=0.8))
    return d


# ------------------------------------------------------------------------------------------------ logo
def logo(size: float = 64) -> Group:
    s = size / 64.0
    g = Group()
    g.add(Rect(2 * s, 2 * s, 60 * s, 60 * s, rx=14 * s, ry=14 * s, fillColor=INK, strokeColor=None))
    g.add(Circle(32 * s, 32 * s, 20 * s, fillColor=None, strokeColor=ACCENT_2, strokeWidth=2.2 * s))
    g.add(Ellipse(32 * s, 32 * s, 9 * s, 20 * s, fillColor=None, strokeColor=colors.HexColor("#3B7FB0"), strokeWidth=1.4 * s))
    for yy, x1, x2 in ((32, 12, 52), (22, 15, 49), (42, 15, 49)):
        g.add(Line(x1 * s, yy * s, x2 * s, yy * s, strokeColor=colors.HexColor("#2E5F86"), strokeWidth=1.2 * s))
    # SVG y axis is downward; flip
    pts = [(22, 24), (38, 20), (44, 36), (28, 44)]
    fp = [(x * s, (64 - y) * s) for x, y in pts]
    lc = colors.HexColor("#9AD0F2")
    for a, b in ((0, 1), (1, 2), (2, 3), (3, 0), (0, 2), (1, 3)):
        g.add(Line(fp[a][0], fp[a][1], fp[b][0], fp[b][1], strokeColor=lc, strokeWidth=1.6 * s))
    for x, y in fp:
        g.add(Circle(x, y, 3 * s, fillColor=colors.HexColor("#E8F4FC"), strokeColor=None))
    return g


# ------------------------------------------------------------------------------------------------ document
class AtlasDoc(BaseDocTemplate):
    def __init__(self, filename: str, **kw):
        super().__init__(filename, pagesize=A4, leftMargin=MARGIN_L, rightMargin=MARGIN_R, topMargin=MARGIN_T,
                         bottomMargin=MARGIN_B, title="Project Atlas — Technical Overview",
                         author="Project Atlas contributors", subject="Offline Intelligence and Data Operations Platform",
                         creator="ReportLab", **kw)
        self.current_chapter = ""
        self.chapter_first_page = False
        frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W, PAGE_H - MARGIN_T - MARGIN_B, id="main", leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0)
        cover_frame = Frame(0, 0, PAGE_W, PAGE_H, id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[cover_frame], onPage=self._cover_bg),
            PageTemplate(id="content", frames=[frame], onPageEnd=self._decorate),
        ])
        self._bm = 0

    def beforeDocument(self):
        # multiBuild runs several passes; keys must be identical each pass for the TOC to settle
        self._bm = 0
        self.current_chapter = ""

    def _cover_bg(self, canv, doc):
        pass  # the cover flowable paints the whole page

    def _decorate(self, canv, doc):
        canv.saveState()
        canv.setFont("Body-Bold", 7.6)
        canv.setFillColor(ACCENT)
        canv.drawString(MARGIN_L, PAGE_H - 38, "P R O J E C T   A T L A S")
        canv.setFont("Body", 8)
        canv.setFillColor(MUTED)
        canv.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 38, self.current_chapter)
        canv.setStrokeColor(LINE)
        canv.setLineWidth(0.5)
        canv.line(MARGIN_L, PAGE_H - 45, PAGE_W - MARGIN_R, PAGE_H - 45)
        canv.line(MARGIN_L, 40, PAGE_W - MARGIN_R, 40)
        canv.setFont("Body", 8)
        canv.drawString(MARGIN_L, 28, "Technical Overview · Version 0.2.0 · November 2026")
        canv.setFont("Body-Bold", 8.5)
        canv.setFillColor(INK)
        canv.drawRightString(PAGE_W - MARGIN_R, 28, str(canv.getPageNumber()))
        canv.restoreState()

    def afterFlowable(self, flowable):
        entry = getattr(flowable, "toc_entry", None)
        if isinstance(flowable, ChapterHeading):
            self.current_chapter = flowable.chapter_title
        if entry:
            level, txt = entry
            key = f"bm{self._bm}"
            self._bm += 1
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(txt.replace("&amp;", "&"), key, level=level, closed=level == 0)
            if level == 0:
                self.notify("TOCEntry", (level, txt, self.page, key))


def toc() -> TableOfContents:
    t = TableOfContents()
    t.levelStyles = [STY["toc0"], STY["toc1"]]
    t.dotsMinLevel = 0
    t.tableStyle = TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0.8),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8)])
    return t


__all__ = [n for n in dir() if not n.startswith("_")]
