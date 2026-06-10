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
_SIG_REP = ("代表者：", "代表者:")

def _fix_signature_newlines(text: str) -> str:
    """署名欄の甲・乙・代表者行が同一段落に結合されないよう空行を調整する。
    フォーマット: 甲：{名称} → 代表者：＿＿＿ → [空行] → 乙：{名称} → 代表者：＿＿＿
    """
    lines = text.split("\n")
    result: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_party = any(stripped.startswith(s) for s in _SIG_STARTERS)
        is_rep   = any(stripped.startswith(s) for s in _SIG_REP)

        if is_party:
            # 甲・乙行の前には必ず空行
            if result and result[-1].strip() != "":
                result.append("")
            result.append(line)
            # 次行が代表者行でもそれ以外でも空行は入れない（代表者が直後に来るため）
        elif is_rep:
            # 代表者行は前の行が甲・乙行なら空行なしで続ける
            # 前行が空行でなく、かつ甲/乙行でもない場合のみ空行を挿入
            prev = result[-1].strip() if result else ""
            if prev and not any(prev.startswith(s) for s in _SIG_STARTERS):
                result.append("")
            result.append(line)
            # 代表者行の後には空行（次の甲/乙ブロックとの区切り）
            if i + 1 < len(lines) and lines[i + 1].strip() != "":
                result.append("")
        else:
            result.append(line)
    return "\n".join(result)


def _strip_disclaimer(text: str) -> str:
    """AIが生成した免責注記（※本契約書はAI…）を除去する。"""
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if "本契約書はAI" in stripped or "参考ひな形" in stripped:
            # その直前の区切り線も除去
            if result and result[-1].strip().startswith("─"):
                result.pop()
            continue
        result.append(line)
    return "\n".join(result)


def preprocess_markdown(text: str) -> str:
    """全出力前に適用する共通前処理（禁則処理 + 署名欄改行保証 + 免責除去）。"""
    text = _fix_kinsoku_linebreaks(text)
    text = _fix_signature_newlines(text)
    text = _strip_disclaimer(text)
    return text


def _strip_markdown_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)




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

    doc.build(story)
    return buf.getvalue()

