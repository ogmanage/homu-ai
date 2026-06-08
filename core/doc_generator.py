"""Word (.docx), PDF, and PNG generation from ContractDraft."""

from __future__ import annotations

import io
import os
import re
import sys

from .models import ContractDraft

# ── 禁則処理：行頭に来てはいけない文字 ──────────────────────────────────────
_KINSOKU_CHARS = "。、，．・：；？！）〕］｝〉》」』】〙〗〟‘’“”｠»‐〜"

def _fix_kinsoku_linebreaks(text: str) -> str:
    """行頭禁則文字（。、など）が単独で行頭に来ている場合、前の行に結合する。"""
    lines = text.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if result and stripped and stripped[0] in _KINSOKU_CHARS and not line.startswith("#"):
            result[-1] = result[-1] + stripped
        else:
            result.append(line)
    return "\n".join(result)


_SIG_STARTERS = ("甲：", "乙：", "甲:", "乙:")

def _fix_signature_newlines(text: str) -> str:
    """署名欄の甲・乙行が同一段落に結合されないよう、前後に空行を挿入する。"""
    lines = text.split("\n")
    result: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_sig = any(stripped.startswith(s) for s in _SIG_STARTERS)
        if is_sig:
            if result and result[-1].strip() != "":
                result.append("")
            result.append(line)
            if i + 1 < len(lines) and lines[i + 1].strip() != "":
                result.append("")
        else:
            result.append(line)
    return "\n".join(result)


def preprocess_markdown(text: str) -> str:
    """全出力前に適用する共通前処理（禁則処理 + 署名欄改行保証）。"""
    text = _fix_kinsoku_linebreaks(text)
    text = _fix_signature_newlines(text)
    return text


def _strip_markdown_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


# ── CJK フォント検索 ──────────────────────────────────────────────────────────

def _find_cjk_font(bold: bool = False) -> str | None:
    candidates_bold = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W7.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Bold.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    candidates_regular = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    for path in (candidates_bold if bold else candidates_regular):
        if os.path.exists(path):
            return path
    return None


# ── Word (.docx) ─────────────────────────────────────────────────────────────

def draft_to_docx(draft: ContractDraft) -> bytes:
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    doc = Document()
    for section in doc.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(2.5)

    def _set_cjk_font(run, font_name: str = "MS Mincho") -> None:
        run.font.name = font_name
        r_pr = run._element.get_or_add_rPr()
        r_fonts = r_pr.get_or_add_rFonts()
        r_fonts.set(qn("w:eastAsia"), font_name)

    def _enable_kinsoku(paragraph) -> None:
        """Word 禁則処理・文字間調整を有効化"""
        pPr = paragraph._p.get_or_add_pPr()
        for tag, val in [("w:kinsoku", "1"), ("w:overflowPunct", "1"), ("w:wordWrap", "1")]:
            el = OxmlElement(tag)
            el.set(qn("w:val"), val)
            pPr.append(el)

    body = preprocess_markdown(draft.body_markdown)

    for line in body.split("\n"):
        if line.startswith("# "):
            p = doc.add_heading(line[2:], level=1)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _enable_kinsoku(p)
            for run in p.runs:
                _set_cjk_font(run)
        elif line.startswith("## "):
            p = doc.add_heading(line[3:], level=2)
            _enable_kinsoku(p)
            for run in p.runs:
                _set_cjk_font(run)
        elif line.startswith("### "):
            p = doc.add_heading(line[4:], level=3)
            _enable_kinsoku(p)
            for run in p.runs:
                _set_cjk_font(run)
        elif line.strip() == "":
            doc.add_paragraph("")
        else:
            p = doc.add_paragraph(line)
            _enable_kinsoku(p)
            for run in p.runs:
                run.font.size = Pt(10.5)
                _set_cjk_font(run)

    doc.add_paragraph("─" * 50)
    disclaimer = doc.add_paragraph(
        "※ 本契約書はAIによる参考ひな形です。"
        "締結前には必ず弁護士等の法律専門家にご確認ください。"
    )
    disclaimer.runs[0].font.size = Pt(9)
    _set_cjk_font(disclaimer.runs[0])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────────────

def draft_to_pdf(draft: ContractDraft) -> bytes:
    if sys.platform == "darwin":
        return _pdf_via_docx2pdf(draft)
    return _pdf_via_reportlab(draft)


def _pdf_via_docx2pdf(draft: ContractDraft) -> bytes:
    import tempfile
    try:
        from docx2pdf import convert
    except ImportError:
        return _pdf_via_reportlab(draft)
    with tempfile.TemporaryDirectory() as tmp:
        docx_path = os.path.join(tmp, "contract.docx")
        pdf_path = os.path.join(tmp, "contract.pdf")
        with open(docx_path, "wb") as f:
            f.write(draft_to_docx(draft))
        convert(docx_path, pdf_path)
        with open(pdf_path, "rb") as f:
            return f.read()


def _pdf_via_reportlab(draft: ContractDraft) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=2.5 * cm, bottomMargin=2.5 * cm,
        leftMargin=3.0 * cm, rightMargin=2.5 * cm,
    )
    styles = getSampleStyleSheet()
    F = "HeiseiKakuGo-W5"
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName=F, fontSize=14, spaceAfter=12)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontName=F, fontSize=12, spaceAfter=8)
    h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontName=F, fontSize=11, spaceAfter=6)
    bd = ParagraphStyle("Body", parent=styles["Normal"], fontName=F, fontSize=10, leading=18, spaceAfter=4)
    nt = ParagraphStyle("Note", parent=styles["Normal"], fontName=F, fontSize=9, textColor=(0.4, 0.4, 0.4))

    body = preprocess_markdown(draft.body_markdown)
    story = []
    for line in body.split("\n"):
        clean = _strip_markdown_bold(line)
        if line.startswith("# "):
            story.append(Paragraph(clean[2:], h1))
        elif line.startswith("## "):
            story.append(Paragraph(clean[3:], h2))
        elif line.startswith("### "):
            story.append(Paragraph(clean[4:], h3))
        elif line.strip() == "":
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(clean, bd))

    story += [
        Spacer(1, 12),
        Paragraph("─" * 40, bd),
        Paragraph(
            "※ 本契約書はAIによる参考ひな形です。締結前には必ず弁護士等の法律専門家にご確認ください。",
            nt,
        ),
    ]
    doc.build(story)
    return buf.getvalue()


# ── PNG（Canva用）────────────────────────────────────────────────────────────

def draft_to_png(draft: ContractDraft) -> bytes:
    """A4サイズ 150dpi のPNG画像を生成（Canvaへの取り込みに最適化）。
    複数ページの場合は縦に連結した1枚の画像を返す。"""
    from PIL import Image, ImageDraw, ImageFont

    DPI = 150
    A4_W = int(8.27 * DPI)    # 1240px
    A4_H = int(11.69 * DPI)   # 1754px
    MX = int(1.1 * DPI)       # horizontal margin
    MT = int(1.0 * DPI)       # top margin
    MB = int(0.9 * DPI)       # bottom margin
    CW = A4_W - MX * 2        # content width

    BG = (255, 255, 255)
    C_TITLE   = (20,  35,  80)
    C_H2      = (30,  70, 150)
    C_H3      = (50,  50,  90)
    C_BODY    = (30,  30,  30)
    C_NOTE    = (140, 140, 140)
    C_RULE    = (200, 210, 225)

    # Font loader
    bold_path = _find_cjk_font(bold=True)
    reg_path  = _find_cjk_font(bold=False)

    def _font(size: int, bold: bool = False):
        path = bold_path if bold else reg_path
        if path:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    f_title = _font(28, bold=True)
    f_h2    = _font(19, bold=True)
    f_h3    = _font(16, bold=True)
    f_body  = _font(14)
    f_note  = _font(11)

    # ── ページ管理 ─────────────────────────────────────────────────────────
    pages: list[Image.Image] = []

    def _new_page():
        img = Image.new("RGB", (A4_W, A4_H), BG)
        return img, ImageDraw.Draw(img), MT

    page, draw, y = _new_page()

    def _wrap(text: str, font) -> list[str]:
        lines_out: list[str] = []
        current = ""
        for ch in text:
            test = current + ch
            if font.getlength(test) > CW and current:
                lines_out.append(current)
                current = ch
            else:
                current = test
        if current:
            lines_out.append(current)
        return lines_out or [""]

    def _add(text: str, font, color=C_BODY, center: bool = False,
             gap_before: int = 0, gap_after: int = 6):
        nonlocal page, draw, y
        y += gap_before
        for wline in _wrap(text, font):
            lh = int(font.getbbox(wline)[3]) + 6
            if y + lh > A4_H - MB:
                pages.append(page)
                page, draw, y = _new_page()
            x = (A4_W - int(font.getlength(wline))) // 2 if center else MX
            draw.text((x, y), wline, font=font, fill=color)
            y += lh
        y += gap_after

    def _hline(color=C_RULE, width=1):
        nonlocal y
        draw.line([(MX, y), (A4_W - MX, y)], fill=color, width=width)
        y += 6

    # ── 本文レンダリング ───────────────────────────────────────────────────
    body = preprocess_markdown(draft.body_markdown)
    for line in body.split("\n"):
        clean = _strip_markdown_bold(line)
        if line.startswith("# "):
            _add(clean[2:], f_title, C_TITLE, center=True, gap_before=10, gap_after=4)
            _hline((180, 200, 230), width=2)
        elif line.startswith("## "):
            _add(clean[3:], f_h2, C_H2, gap_before=14, gap_after=2)
            _hline()
        elif line.startswith("### "):
            _add(clean[4:], f_h3, C_H3, gap_before=8, gap_after=2)
        elif clean.strip() in ("", "---", "```"):
            y += 8
        else:
            _add(clean, f_body, C_BODY, gap_before=0, gap_after=4)

    # 免責注記
    y += 14
    _hline()
    _add(
        "※ 本契約書はAIによる参考ひな形です。締結前には必ず弁護士等の法律専門家にご確認ください。",
        f_note, C_NOTE,
    )
    pages.append(page)

    # ── ページ結合 ─────────────────────────────────────────────────────────
    total_h = A4_H * len(pages)
    combined = Image.new("RGB", (A4_W, total_h), BG)
    for i, pg in enumerate(pages):
        combined.paste(pg, (0, i * A4_H))

    buf = io.BytesIO()
    combined.save(buf, format="PNG", dpi=(DPI, DPI))
    return buf.getvalue()
