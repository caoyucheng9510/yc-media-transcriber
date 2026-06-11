from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.transcript import format_dialog_items_for_display

USER_ARTIFACT_MIME_TYPES = {
    "document_md": "text/markdown",
    "document_pdf": "application/pdf",
}

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_MAX_FILENAME_STEM_LENGTH = 120


def transcript_text(segments: list[dict[str, Any]]) -> str:
    lines = []
    for segment in segments:
        speaker = segment.get("speaker")
        prefix = f"{speaker}: " if speaker else ""
        lines.append(f"{prefix}{segment.get('text', '').strip()}".strip())
    return "\n".join(line for line in lines if line)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def safe_export_stem(title: str | None, fallback: str) -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("", (title or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    cleaned = cleaned[:_MAX_FILENAME_STEM_LENGTH].strip(" .")
    return cleaned or fallback


def job_artifact_paths(job_dir: Path, result: dict[str, Any]) -> dict[str, Path]:
    stem = safe_export_stem(_document_title(result), str(result.get("job_id") or "document"))
    return {
        "document_md": job_dir / f"{stem}.md",
        "document_pdf": job_dir / f"{stem}.pdf",
    }


def write_job_artifacts(job_dir: Path, result: dict[str, Any]) -> dict[str, Path]:
    artifacts = job_artifact_paths(job_dir, result)
    markdown = document_markdown(result)
    write_text(artifacts["document_md"], markdown)
    write_pdf(artifacts["document_pdf"], markdown)
    return artifacts


def document_markdown(result: dict[str, Any]) -> str:
    title = _document_title(result)
    summary = _normalize_block(result.get("summary")) or "## 总结\n\n暂无总结。"
    polished_text = document_polished_text(result) or "暂无校对稿。"
    return f"# {title}\n\n{summary}\n\n## 校对稿\n\n{polished_text}\n"


def write_pdf(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _register_pdf_fonts()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    doc.build(_markdown_flowables(markdown))


def _document_title(result: dict[str, Any]) -> str:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    title = metadata.get("title") if metadata else None
    return str(title or result.get("job_id") or "转录文稿").strip()


def _normalize_block(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def document_polished_text(result: dict[str, Any]) -> str:
    polished_text = _normalize_block(result.get("polished_text"))
    if polished_text:
        return polished_text
    structured_transcript = result.get("structured_transcript")
    if isinstance(structured_transcript, list) and structured_transcript:
        return _normalize_block(format_dialog_items_for_display(structured_transcript))
    return ""


def _register_pdf_fonts() -> None:
    if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def _pdf_styles() -> dict[str, ParagraphStyle]:
    base = {
        "fontName": "STSong-Light",
        "textColor": HexColor("#222222"),
    }
    return {
        "title": ParagraphStyle(
            "DocumentTitle",
            **base,
            fontSize=18,
            leading=25,
            spaceAfter=12,
        ),
        "heading": ParagraphStyle(
            "DocumentHeading",
            **base,
            fontSize=13,
            leading=20,
            spaceBefore=8,
            spaceAfter=6,
        ),
        "normal": ParagraphStyle(
            "DocumentBody",
            **base,
            fontSize=10.5,
            leading=17,
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "DocumentBullet",
            **base,
            fontSize=10.5,
            leading=17,
            leftIndent=12,
            firstLineIndent=0,
            spaceAfter=4,
        ),
    }


def _markdown_flowables(markdown: str) -> list[Any]:
    styles = _pdf_styles()
    flowables: list[Any] = []
    paragraph_lines: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        text = " ".join(paragraph_lines).strip()
        if text:
            flowables.append(Paragraph(escape(text), styles["normal"]))
        paragraph_lines.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flowables.append(Spacer(1, 4))
            continue
        if line.startswith("# "):
            flush_paragraph()
            flowables.append(Paragraph(escape(line[2:].strip()), styles["title"]))
            continue
        if line.startswith("## "):
            flush_paragraph()
            flowables.append(Paragraph(escape(line[3:].strip()), styles["heading"]))
            continue
        if line.startswith("- "):
            flush_paragraph()
            flowables.append(Paragraph(escape(line[2:].strip()), styles["bullet"], bulletText="-"))
            continue
        paragraph_lines.append(line)

    flush_paragraph()
    return flowables
