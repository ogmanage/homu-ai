"""PDF / Word / plain-text input parsing."""

from __future__ import annotations

import io

MAX_CONTRACT_CHARS = 50_000  # ~12,500 tokens — well within sonnet's 200K limit


def parse_uploaded_file(uploaded_file) -> str:
    """
    Dispatch on file extension and return extracted plain text.
    Truncates at MAX_CONTRACT_CHARS with an appended notice.
    """
    name: str = uploaded_file.name.lower()
    if name.endswith(".pdf"):
        text = _parse_pdf(uploaded_file)
    elif name.endswith(".docx"):
        text = _parse_docx(uploaded_file)
    elif name.endswith(".txt"):
        text = uploaded_file.read().decode("utf-8", errors="replace")
    else:
        raise ValueError(f"非対応のファイル形式です: {uploaded_file.name}")

    if not text.strip():
        raise ValueError(
            "テキストを抽出できませんでした。\n"
            "スキャンPDFの場合はテキストPDF・Wordファイルをご利用ください。"
        )

    return _truncate(text)


def _parse_pdf(uploaded_file) -> str:
    try:
        import pdfplumber
        data = uploaded_file.read()
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
        return "\n".join(parts)
    except ImportError:
        # pdfplumber not available, fall back to pypdf
        return _parse_pdf_fallback(uploaded_file)
    except Exception as exc:
        raise ValueError(f"PDFの読み込みに失敗しました: {exc}") from exc


def _parse_pdf_fallback(uploaded_file) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(uploaded_file.read()))
    parts = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(parts)


def _parse_docx(uploaded_file) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(uploaded_file.read()))
        parts: list[str] = []
        for para in doc.paragraphs:
            if para.text.strip():
                parts.append(para.text)
        # Also extract table cells
        for table in doc.tables:
            for row in table.rows:
                row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_texts:
                    parts.append(" | ".join(row_texts))
        return "\n".join(parts)
    except Exception as exc:
        raise ValueError(f"Wordファイルの読み込みに失敗しました: {exc}") from exc


def _truncate(text: str) -> str:
    if len(text) <= MAX_CONTRACT_CHARS:
        return text
    truncated = text[:MAX_CONTRACT_CHARS]
    return (
        truncated
        + f"\n\n⚠️ [注意] 文字数制限（{MAX_CONTRACT_CHARS:,}文字）により末尾が省略されました。"
    )
