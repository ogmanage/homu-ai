"""Word (.docx) and PDF generation from ContractDraft."""

from __future__ import annotations

import io
import re
import sys

from .models import ContractDraft


def draft_to_docx(draft: ContractDraft) -> bytes:
    """Convert ContractDraft to a .docx file and return raw bytes."""
    from docx import Document
    from docx.shared import Cm, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    doc = Document()

    # A4 margins (Japanese standard)
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

    lines = draft.body_markdown.split("\n")
    for line in lines:
        if line.startswith("# "):
            p = doc.add_heading(line[2:], level=1)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                _set_cjk_font(run)
        elif line.startswith("## "):
            p = doc.add_heading(line[3:], level=2)
            for run in p.runs:
                _set_cjk_font(run)
        elif line.startswith("### "):
            p = doc.add_heading(line[4:], level=3)
            for run in p.runs:
                _set_cjk_font(run)
        elif line.strip() == "":
            doc.add_paragraph("")
        else:
            p = doc.add_paragraph(line)
            for run in p.runs:
                run.font.size = Pt(10.5)
                _set_cjk_font(run)

    # Divider + disclaimer footer
    doc.add_paragraph("─" * 50)
    disclaimer = doc.add_paragraph(
        "※ 本契約書はAIによる参考ひな形です。"
        "締結前には必ず弁護士等の法律専門家にご確認ください。"
        "本ツールの出力は法的助言を構成するものではありません。"
    )
    disclaimer.runs[0].font.size = Pt(9)
    _set_cjk_font(disclaimer.runs[0])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def draft_to_pdf(draft: ContractDraft) -> bytes:
    """
    macOS: use docx2pdf (requires Microsoft Word)
    Linux/Cloud: use reportlab with built-in CJK font
    """
    if sys.platform == "darwin":
        return _pdf_via_docx2pdf(draft)
    else:
        return _pdf_via_reportlab(draft)


def _pdf_via_docx2pdf(draft: ContractDraft) -> bytes:
    import os
    import tempfile
    try:
        from docx2pdf import convert
    except ImportError:
        # fallback to reportlab on macOS if docx2pdf not installed
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

    # Register built-in Japanese CID font (no external font file needed)
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        leftMargin=3.0 * cm,
        rightMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()
    base_font = "HeiseiKakuGo-W5"

    h1_style = ParagraphStyle("H1", parent=styles["Heading1"], fontName=base_font, fontSize=14, spaceAfter=12)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontName=base_font, fontSize=12, spaceAfter=8)
    h3_style = ParagraphStyle("H3", parent=styles["Heading3"], fontName=base_font, fontSize=11, spaceAfter=6)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName=base_font, fontSize=10, leading=16, spaceAfter=4)
    note_style = ParagraphStyle("Note", parent=styles["Normal"], fontName=base_font, fontSize=9, textColor=(0.4, 0.4, 0.4))

    story = []
    for line in draft.body_markdown.split("\n"):
        clean = _strip_markdown_bold(line)
        if line.startswith("# "):
            story.append(Paragraph(clean[2:], h1_style))
        elif line.startswith("## "):
            story.append(Paragraph(clean[3:], h2_style))
        elif line.startswith("### "):
            story.append(Paragraph(clean[4:], h3_style))
        elif line.strip() == "":
            story.append(Spacer(1, 6))
        else:
            story.append(Paragraph(clean, body_style))

    story.append(Spacer(1, 12))
    story.append(Paragraph("─" * 40, body_style))
    story.append(
        Paragraph(
            "※ 本契約書はAIによる参考ひな形です。締結前には必ず弁護士等の法律専門家にご確認ください。",
            note_style,
        )
    )

    doc.build(story)
    return buf.getvalue()


def _strip_markdown_bold(text: str) -> str:
    """Remove **bold** markers for reportlab (which doesn't render markdown)."""
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)
