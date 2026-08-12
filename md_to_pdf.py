"""
Markdown → PDF via ReportLab + system Chinese fonts.

Supports:
- Chinese + English mixed text (Arial Unicode as primary CJK, Hiragino/STHeiti as fallback)
- Headings (H1-H4), paragraphs, lists, code, blockquote, tables
- Page header/footer with page numbers
- Book-style typography: titles, chapter breaks, justified text

Key insight: macOS .ttc files are unreliable in ReportLab for some CJK glyph ranges.
We use Arial Unicode.ttf (a single-file TTF with broad Unicode coverage) as primary
CJK font to avoid the tofu-box problem.
"""

from __future__ import annotations
import os
import re
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm, cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, PageBreak,
    Table, TableStyle, KeepTogether, Preformatted,
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY, TA_CENTER

# ────────────────────────────────────────────────────────────────────────────
# Font registration
# ────────────────────────────────────────────────────────────────────────────
# Arial Unicode is a single TTF with the broadest Unicode coverage of any
# pre-installed macOS font. We use it as the primary CJK font to avoid tofu boxes
# that occur when ReportLab misreads a .ttc container face.
FONT_PRIMARY_CJK = ("ArialUnicode", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
FONT_LATIN = ("Helvetica", "/System/Library/Fonts/Helvetica.ttc")
FONT_MONO_CANDIDATES = [
    ("Menlo", "/System/Library/Fonts/Menlo.ttc"),
    ("CourierNew", "/Library/Fonts/Courier New.ttf"),
    ("Courier", "/System/Library/Fonts/Courier.ttc"),
]

def register_fonts():
    """Register fonts; return (font_name_primary, font_name_mono)."""
    primary_name = "Helvetica"
    try:
        pdfmetrics.registerFont(TTFont(FONT_PRIMARY_CJK[0], FONT_PRIMARY_CJK[1]))
        primary_name = FONT_PRIMARY_CJK[0]
        print(f"[font] registered primary CJK: {primary_name}")
    except Exception as e:
        print(f"[font] WARN: ArialUnicode failed: {e}")
    # Latin fallback
    try:
        pdfmetrics.registerFont(TTFont(FONT_LATIN[0], FONT_LATIN[1]))
    except Exception:
        pass
    # Mono
    mono_name = "Courier"
    for name, path in FONT_MONO_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                mono_name = name
                print(f"[font] registered mono: {name}")
                break
            except Exception:
                continue
    return primary_name, mono_name

# ────────────────────────────────────────────────────────────────────────────
# Style sheet
# ────────────────────────────────────────────────────────────────────────────
def build_styles(cjk_font: str, mono_font: str) -> dict:
    base = getSampleStyleSheet()
    styles = {}
    styles["BodyText"] = ParagraphStyle(
        "BodyText", parent=base["BodyText"],
        fontName=cjk_font, fontSize=10.5, leading=17,
        alignment=TA_JUSTIFY, spaceBefore=2, spaceAfter=8,
    )
    styles["Title"] = ParagraphStyle(
        "Title", parent=base["Title"],
        fontName=cjk_font, fontSize=22, leading=28,
        alignment=TA_LEFT, spaceAfter=14,
        textColor=colors.HexColor("#1a1a1a"),
    )
    styles["H1"] = ParagraphStyle(
        "H1", parent=base["Heading1"],
        fontName=cjk_font, fontSize=18, leading=24,
        spaceBefore=18, spaceAfter=10,
        textColor=colors.HexColor("#1f4e79"), keepWithNext=True,
    )
    styles["H2"] = ParagraphStyle(
        "H2", parent=base["Heading2"],
        fontName=cjk_font, fontSize=14.5, leading=20,
        spaceBefore=14, spaceAfter=8,
        textColor=colors.HexColor("#2e74b5"), keepWithNext=True,
    )
    styles["H3"] = ParagraphStyle(
        "H3", parent=base["Heading3"],
        fontName=cjk_font, fontSize=12.5, leading=18,
        spaceBefore=10, spaceAfter=6,
        textColor=colors.HexColor("#1f4e79"), keepWithNext=True,
    )
    styles["H4"] = ParagraphStyle(
        "H4", parent=base["Heading4"],
        fontName=cjk_font, fontSize=11, leading=16,
        spaceBefore=8, spaceAfter=4,
        textColor=colors.HexColor("#404040"), keepWithNext=True,
    )
    styles["Blockquote"] = ParagraphStyle(
        "Blockquote", parent=styles["BodyText"],
        leftIndent=18, rightIndent=10,
        fontSize=10, leading=16,
        textColor=colors.HexColor("#404040"),
        borderColor=colors.HexColor("#cccccc"),
        borderWidth=0, borderPadding=6,
        spaceBefore=6, spaceAfter=10,
    )
    styles["CodeInline"] = ParagraphStyle(
        "CodeInline", parent=styles["BodyText"],
        fontName=mono_font, fontSize=9, leading=14,
        textColor=colors.HexColor("#a31515"),
    )
    styles["CodeBlock"] = ParagraphStyle(
        "CodeBlock",
        fontName=cjk_font, fontSize=8.5, leading=12,  # CJK so Chinese in event logs renders
        leftIndent=10, rightIndent=10,
        spaceBefore=6, spaceAfter=10,
        backColor=colors.HexColor("#f5f5f5"),
        borderColor=colors.HexColor("#dddddd"),
        borderWidth=0.5, borderPadding=8,
        textColor=colors.HexColor("#222222"),
    )
    styles["Caption"] = ParagraphStyle(
        "Caption", parent=styles["BodyText"],
        fontSize=9, leading=13, alignment=TA_CENTER,
        textColor=colors.HexColor("#666666"), spaceAfter=12,
    )
    return styles

# ────────────────────────────────────────────────────────────────────────────
# Markdown → flowables
# ────────────────────────────────────────────────────────────────────────────
INLINE_CODE = re.compile(r"`([^`]+)`")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
ITALIC = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
TABLE_SEP = re.compile(r"^\s*\|?\s*[-:]+[-:\s|]*[-:]+\s*\|?\s*$")

def inline_to_html(text: str, styles: dict) -> str:
    """Convert inline markdown to ReportLab HTML."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = INLINE_CODE.sub(
        lambda m: f'<font name="{styles["CodeInline"].fontName}" size="9" color="#a31515">{m.group(1)}</font>',
        text,
    )
    text = BOLD.sub(r"<b>\1</b>", text)
    text = ITALIC.sub(r"<i>\1</i>", text)
    return text

def parse_table_block(lines: list[str], styles: dict) -> list:
    rows = []
    for line in lines:
        if not line.strip() or TABLE_SEP.match(line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append([Paragraph(inline_to_html(c, styles), styles["BodyText"]) for c in cells])
    if not rows:
        return [Spacer(1, 4)]
    table = Table(rows, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
        ("FONTNAME", (0, 0), (-1, 0), styles["H4"].fontName),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTNAME", (0, 1), (-1, -1), styles["BodyText"].fontName),
        ("FONTSIZE", (0, 1), (-1, -1), 9.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f7f7")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return [Spacer(1, 4), table, Spacer(1, 8)]

def markdown_to_flowables(md_text: str, styles: dict) -> list:
    flowables = []
    lines = md_text.split("\n")
    i, n = 0, len(lines)
    in_code, code_buf, code_lang = False, [], ""

    def flush_code():
        nonlocal code_buf, in_code
        if code_buf:
            text = "\n".join(code_buf)
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            flowables.append(Preformatted(text, styles["CodeBlock"]))
            flowables.append(Spacer(1, 4))
            code_buf = []
        in_code = False

    while i < n:
        line = lines[i]
        stripped = line.rstrip()

        if stripped.startswith("```"):
            if not in_code:
                in_code, code_buf = True, []
            else:
                flush_code()
            i += 1
            continue

        if in_code:
            code_buf.append(line)
            i += 1
            continue

        if re.match(r"^\s*---+\s*$", stripped):
            flowables.append(Spacer(1, 6))
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            text = inline_to_html(m.group(2).strip(), styles)
            style_key = f"H{min(level,4)}"
            flowables.append(Paragraph(text, styles[style_key]))
            i += 1
            continue

        if stripped.startswith(">"):
            buf = []
            while i < n and lines[i].rstrip().startswith(">"):
                buf.append(lines[i].rstrip().lstrip(">").strip())
                i += 1
            flowables.append(Paragraph(inline_to_html(" ".join(buf), styles), styles["Blockquote"]))
            continue

        if "|" in stripped and i + 1 < n and TABLE_SEP.match(lines[i + 1].rstrip()):
            tbl_lines = []
            while i < n and "|" in lines[i].rstrip():
                tbl_lines.append(lines[i].rstrip())
                i += 1
            flowables.extend(parse_table_block(tbl_lines, styles))
            continue

        m = re.match(r"^\s*[-*]\s+(.*)$", stripped)
        if m:
            buf = []
            while i < n:
                m2 = re.match(r"^\s*[-*]\s+(.*)$", lines[i].rstrip())
                if not m2:
                    break
                buf.append("• " + m2.group(1))
                i += 1
            for item in buf:
                flowables.append(Paragraph(inline_to_html(item, styles), styles["BodyText"]))
            flowables.append(Spacer(1, 4))
            continue

        m = re.match(r"^\s*\d+\.\s+(.*)$", stripped)
        if m:
            buf = []
            while i < n:
                m2 = re.match(r"^\s*(\d+)\.\s+(.*)$", lines[i].rstrip())
                if not m2:
                    break
                buf.append(f"{m2.group(1)}. {m2.group(2)}")
                i += 1
            for item in buf:
                flowables.append(Paragraph(inline_to_html(item, styles), styles["BodyText"]))
            flowables.append(Spacer(1, 4))
            continue

        if not stripped:
            i += 1
            continue

        buf = [stripped]
        i += 1
        while i < n and lines[i].rstrip() and not re.match(
            r"^(#{1,6}\s|>|```|\s*[-*]\s|\s*\d+\.\s|---+\s*$)", lines[i].rstrip()
        ) and "|" not in lines[i].rstrip():
            buf.append(lines[i].rstrip())
            i += 1
        text = inline_to_html(" ".join(buf), styles)
        flowables.append(Paragraph(text, styles["BodyText"]))

    return flowables

# ────────────────────────────────────────────────────────────────────────────
# Document
# ────────────────────────────────────────────────────────────────────────────
class ThesisDoc(BaseDocTemplate):
    def __init__(self, filename, *, title, author, cjk_font):
        super().__init__(
            filename, pagesize=A4,
            leftMargin=22*mm, rightMargin=22*mm,
            topMargin=22*mm, bottomMargin=22*mm,
            title=title, author=author,
        )
        self.cjk_font = cjk_font
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="normal")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=self._draw_cover),
            PageTemplate(id="body", frames=[frame], onPage=self._draw_body),
        ])

    def _draw_cover(self, canvas, doc):
        pass

    def _draw_body(self, canvas, doc):
        canvas.saveState()
        page_num = canvas.getPageNumber()
        canvas.setFont(self.cjk_font, 9)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawCentredString(A4[0] / 2, 12*mm, f"— {page_num} —")
        canvas.setStrokeColor(colors.HexColor("#cccccc"))
        canvas.setLineWidth(0.4)
        canvas.line(self.leftMargin, A4[1] - 16*mm, A4[0] - self.rightMargin, A4[1] - 16*mm)
        canvas.restoreState()

def render(md_path: str, pdf_path: str, *, title: str, author: str = "Graduate Researcher"):
    md_text = Path(md_path).read_text(encoding="utf-8")
    cjk_font, mono_font = register_fonts()
    styles = build_styles(cjk_font, mono_font)

    cover_flowables = [
        Spacer(1, 60*mm),
        Paragraph(title, ParagraphStyle("CoverTitle", parent=styles["Title"],
                                        fontSize=26, leading=34, alignment=TA_CENTER)),
        Spacer(1, 14*mm),
        Paragraph(author, ParagraphStyle("CoverAuthor", parent=styles["BodyText"],
                                          fontSize=14, alignment=TA_CENTER,
                                          textColor=colors.HexColor("#404040"))),
        Spacer(1, 8*mm),
        Paragraph("A Four-Dimensional Engineering Framework",
                  ParagraphStyle("CoverSub", parent=styles["BodyText"],
                                 fontSize=13, alignment=TA_CENTER,
                                 textColor=colors.HexColor("#666666"))),
        PageBreak(),
    ]
    body_flowables = markdown_to_flowables(md_text, styles)

    doc = ThesisDoc(pdf_path, title=title, author=author, cjk_font=cjk_font)
    doc.build(cover_flowables + body_flowables)
    print(f"[ok] PDF written: {pdf_path} ({os.path.getsize(pdf_path):,} bytes)")

if __name__ == "__main__":
    import sys
    md = sys.argv[1]
    out = sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else "Thesis"
    render(md, out, title=title)