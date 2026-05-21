from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    paragraphs: list[str]
    parser_name: str


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_CONTENT_TYPE = "application/pdf"
MARKDOWN_CONTENT_TYPES = frozenset(
    {
        "text/markdown",
        "text/x-markdown",
        "application/markdown",
        "application/x-markdown",
    }
)
TEXT_CONTENT_TYPES = frozenset({"text/plain"})
WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def parse_document(file_bytes: bytes, filename: str, content_type: str) -> ParsedDocument:
    suffix = Path(filename).suffix.lower()

    if suffix == ".docx" or content_type == DOCX_CONTENT_TYPE:
        return parse_docx(file_bytes, filename=filename)
    if suffix == ".pdf" or content_type == PDF_CONTENT_TYPE:
        return parse_pdf(file_bytes, filename=filename)
    if suffix in {".md", ".markdown"} or content_type in MARKDOWN_CONTENT_TYPES:
        return parse_markdown(file_bytes, filename=filename)
    if suffix == ".txt" or content_type in TEXT_CONTENT_TYPES:
        return parse_plain_text(file_bytes, filename=filename)

    raise ValueError(f"unsupported file type: {filename}")


def parse_docx(file_bytes: bytes, filename: str) -> ParsedDocument:
    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        document_xml = archive.read("word/document.xml")

    root = ET.fromstring(document_xml)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", WORD_NAMESPACE):
        texts = [
            node.text.strip()
            for node in paragraph.findall(".//w:t", WORD_NAMESPACE)
            if node.text and node.text.strip()
        ]
        if texts:
            paragraphs.append("".join(texts))

    title = paragraphs[0] if paragraphs else Path(filename).stem
    return ParsedDocument(title=title, paragraphs=paragraphs, parser_name="docx")


def parse_pdf(file_bytes: bytes, filename: str) -> ParsedDocument:
    reader = PdfReader(io.BytesIO(file_bytes))
    paragraphs: list[str] = []

    for page in reader.pages:
        text = page.extract_text() or ""
        for line in text.splitlines():
            if line.strip():
                paragraphs.append(line.strip())

    title = paragraphs[0] if paragraphs else Path(filename).stem
    return ParsedDocument(title=title, paragraphs=paragraphs, parser_name="pdf")


def _decode_text(file_bytes: bytes) -> str:
    """Decode bytes to text, stripping the UTF-8 BOM and tolerating GBK fallbacks.

    Markdown / txt files commonly arrive with a UTF-8 BOM (Windows editors) or, in
    Chinese environments, GBK encoding. We try strict UTF-8 first, then fall back
    to GBK; on total failure we use UTF-8 with replacement so ingestion never
    crashes on a single bad byte.
    """
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def parse_markdown(file_bytes: bytes, filename: str) -> ParsedDocument:
    """Split markdown into RAG-friendly paragraphs.

    Splits on blank lines so that:
    - Headers (``# / ## / ###``) become their own paragraph and survive as
      retrieval anchors with the leading hashes intact.
    - Tables and lists stay grouped (no blank line between rows / items).
    - Code fences and HTML comments are kept verbatim — they're rare in our
      knowledge base and stripping them risks corrupting tables that legitimately
      use ``|`` characters.

    The title is taken from the first ``# H1`` heading if present, otherwise the
    first non-empty line, falling back to the filename stem.
    """
    text = _decode_text(file_bytes)
    paragraphs: list[str] = []
    title: str | None = None

    for block in text.split("\n\n"):
        # Normalise: trim per-line trailing whitespace, drop the block if it's
        # empty after normalisation. Multi-line blocks (tables, code fences,
        # bullet groups) are joined with single newlines.
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        cleaned = "\n".join(lines)
        paragraphs.append(cleaned)

        # Capture the first H1 as the document title; ignore the leading hash.
        if title is None:
            for line in lines:
                stripped = line.lstrip()
                if stripped.startswith("# ") and not stripped.startswith("## "):
                    title = stripped[2:].strip() or None
                    break

    if title is None:
        title = (
            paragraphs[0].splitlines()[0].lstrip("# ").strip()
            if paragraphs
            else Path(filename).stem
        )
    return ParsedDocument(title=title, paragraphs=paragraphs, parser_name="markdown")


def parse_plain_text(file_bytes: bytes, filename: str) -> ParsedDocument:
    """Split plain text into paragraphs by blank lines."""
    text = _decode_text(file_bytes)
    paragraphs: list[str] = []
    for block in text.split("\n\n"):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if lines:
            paragraphs.append("\n".join(lines))

    title = paragraphs[0].splitlines()[0] if paragraphs else Path(filename).stem
    return ParsedDocument(title=title, paragraphs=paragraphs, parser_name="text")
