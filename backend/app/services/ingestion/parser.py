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
WORD_NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def parse_document(file_bytes: bytes, filename: str, content_type: str) -> ParsedDocument:
    suffix = Path(filename).suffix.lower()

    if suffix == ".docx" or content_type == DOCX_CONTENT_TYPE:
        return parse_docx(file_bytes, filename=filename)
    if suffix == ".pdf" or content_type == PDF_CONTENT_TYPE:
        return parse_pdf(file_bytes, filename=filename)

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
