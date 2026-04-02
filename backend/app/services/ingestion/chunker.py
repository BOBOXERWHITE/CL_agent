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


def chunk_document(parsed_document: ParsedDocument) -> list[ChunkPayload]:
    rag_settings = get_rag_settings()
    paragraphs = [paragraph for paragraph in parsed_document.paragraphs if paragraph.strip()]
    if not paragraphs:
        paragraphs = [parsed_document.title]

    chunks: list[ChunkPayload] = []
    start_index = 0

    while start_index < len(paragraphs):
        content_parts: list[str] = []
        current_length = 0
        end_index = start_index

        while end_index < len(paragraphs):
            paragraph = paragraphs[end_index]
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
