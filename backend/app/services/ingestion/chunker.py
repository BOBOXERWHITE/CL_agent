from __future__ import annotations

from dataclasses import dataclass

from app.services.ingestion.parser import ParsedDocument
from app.services.rag.settings import get_rag_settings


@dataclass(frozen=True)
class ChunkPayload:
    chunk_index: int
    title: str
    content: str
    attributes: dict[str, object]


def _is_markdown_table(paragraph: str) -> bool:
    """Detect a Markdown pipe-style table.

    Two structural requirements:
    1. The first non-empty line starts with ``|`` (header row).
    2. The second line is a separator row whose cells contain only
       ``-`` and optional alignment ``:`` characters.

    Anything else (a single line beginning with ``|``, a code-fenced
    block, prose containing a ``|``) is rejected. Conservative on purpose
    — false positives would emit one-line chunks that hurt recall.
    """
    lines = paragraph.split("\n")
    if len(lines) < 2:
        return False
    first = lines[0].lstrip()
    second = lines[1].strip()
    if not first.startswith("|") or not second.startswith("|"):
        return False
    cells = [cell.strip() for cell in second.strip("|").split("|")]
    if not cells:
        return False
    return all(cell and set(cell) <= {"-", ":"} for cell in cells)


def _is_heading(paragraph: str) -> bool:
    return paragraph.lstrip().startswith("#")


def chunk_document(parsed_document: ParsedDocument) -> list[ChunkPayload]:
    rag_settings = get_rag_settings()
    paragraphs = [paragraph for paragraph in parsed_document.paragraphs if paragraph.strip()]
    if not paragraphs:
        paragraphs = [parsed_document.title]

    chunks: list[ChunkPayload] = []
    start_index = 0

    while start_index < len(paragraphs):
        # Markdown tables must survive ingestion as a single chunk; the
        # window-pack logic below would otherwise either truncate them
        # or merge them with unrelated prose, both of which destroy the
        # row × column lookup semantics retrieval relies on.
        if _is_markdown_table(paragraphs[start_index]):
            prefix = ""
            if start_index > 0 and _is_heading(paragraphs[start_index - 1]):
                prefix = paragraphs[start_index - 1] + "\n"
            chunks.append(
                ChunkPayload(
                    chunk_index=len(chunks),
                    title=parsed_document.title,
                    content=prefix + paragraphs[start_index],
                    attributes={
                        "parser_name": parsed_document.parser_name,
                        "paragraph_start": start_index,
                        "paragraph_end": start_index,
                        "is_table": True,
                    },
                )
            )
            start_index += 1
            continue

        content_parts: list[str] = []
        current_length = 0
        end_index = start_index

        while end_index < len(paragraphs):
            paragraph = paragraphs[end_index]
            # Stop the window at the next table boundary so the table
            # opens its own chunk fresh (with its own heading prefix).
            if _is_markdown_table(paragraph):
                break
            projected_length = current_length + len(paragraph) + (1 if content_parts else 0)
            if content_parts and projected_length > rag_settings.chunk_size:
                break
            content_parts.append(paragraph)
            current_length = projected_length
            end_index += 1

        chunks.append(
            ChunkPayload(
                chunk_index=len(chunks),
                title=parsed_document.title,
                content="\n".join(content_parts),
                attributes={
                    "parser_name": parsed_document.parser_name,
                    "paragraph_start": start_index,
                    "paragraph_end": end_index - 1,
                },
            )
        )

        if end_index >= len(paragraphs):
            break

        start_index = max(end_index - rag_settings.chunk_overlap, start_index + 1)

    return chunks
