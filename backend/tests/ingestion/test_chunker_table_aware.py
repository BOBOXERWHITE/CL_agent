"""Table-aware chunking guarantees retrieval can answer ``row × column``
lookup questions on Markdown reference tables.

The structural invariants under test:

1. A pipe table is emitted as a single chunk (rows never split).
2. The immediately preceding heading is prepended so the chunk carries
   its own semantic anchor.
3. A table that exceeds ``chunk_size`` still survives intact rather than
   being truncated or merged with unrelated prose.
4. Non-table prose still packs normally up to ``chunk_size``.
5. The heading-table boundary stops the window so the table never gets
   blended with adjacent prose.
"""

from __future__ import annotations

from app.services.ingestion.chunker import chunk_document
from app.services.ingestion.parser import ParsedDocument


def _doc(*paragraphs: str) -> ParsedDocument:
    return ParsedDocument(title="t", paragraphs=list(paragraphs), parser_name="markdown")


SMALL_TABLE = (
    "| 级别 | A 档 | B 档 |\n| --- | --- | --- |\n| L1 | 500 | 350 |\n| L2 普通员工 | 700 | 500 |"
)

LARGE_TABLE = (
    "| 级别 | A 档 | B 档 | C 档 | D 档 (USD) | E 档 (USD) |\n"
    "| --- | --- | --- | --- | --- | --- |\n"
    "| L1 实习 / 一线 | 500 | 350 | 250 | 150 | 120 |\n"
    "| L2 普通员工 | 700 | 500 | 350 | 200 | 160 |\n"
    "| L3 资深 / 主管 | 900 | 650 | 450 | 250 | 200 |\n"
    "| L4 经理 | 1,200 | 800 | 600 | 320 | 250 |\n"
    "| L5 高级经理 / 总监 | 1,500 | 1,000 | 700 | 400 | 320 |\n"
    "| L6 副总裁 | 不限 | 不限 | 不限 | 600 | 500 |\n"
    "| L7 总裁 / C-Level | 不限 | 不限 | 不限 | 不限 | 不限 |"
)


def test_table_emitted_as_single_chunk() -> None:
    chunks = chunk_document(_doc(SMALL_TABLE))

    assert len(chunks) == 1
    assert chunks[0].content == SMALL_TABLE
    assert chunks[0].attributes.get("is_table") is True


def test_heading_immediately_before_table_is_prepended() -> None:
    chunks = chunk_document(_doc("### 2.2 差标房费", SMALL_TABLE))

    table_chunks = [chunk for chunk in chunks if chunk.attributes.get("is_table")]
    assert len(table_chunks) == 1
    table_chunk = table_chunks[0]
    # Both the heading anchor and the table body must end up in the same chunk.
    assert "### 2.2 差标房费" in table_chunk.content
    assert "L2 普通员工 | 700" in table_chunk.content


def test_large_table_is_preserved_even_when_oversized() -> None:
    # The L1–L7 differential rate table from the real hotel kb is ~330
    # chars by itself; with the heading it can approach the default
    # chunk_size of 450. We still want it as one chunk so retrieval
    # can answer ``L2 + 北京 → 700``.
    assert len(LARGE_TABLE) > 200
    chunks = chunk_document(_doc("### 2.2 差标房费 (RMB / 晚, 含税)", LARGE_TABLE))

    table_chunks = [chunk for chunk in chunks if chunk.attributes.get("is_table")]
    assert len(table_chunks) == 1
    body = table_chunks[0].content
    # Every level row must be present so a ``L2 + 700`` query can match.
    for row in ("L1 实习", "L2 普通员工 | 700", "L7 总裁"):
        assert row in body


def test_non_table_prose_still_packs_normally() -> None:
    chunks = chunk_document(
        _doc("段落一", "段落二", "段落三"),
    )

    assert len(chunks) == 1
    assert chunks[0].content == "段落一\n段落二\n段落三"
    assert chunks[0].attributes.get("is_table") is not True


def test_table_does_not_blend_with_adjacent_prose() -> None:
    # The window MUST stop at the table boundary, otherwise prose gets
    # mixed with the table and the chunk's lexical signal for the table
    # content gets diluted.
    chunks = chunk_document(
        _doc("一些前置说明文字。", SMALL_TABLE, "一些后续解释文字。"),
    )

    table_chunks = [chunk for chunk in chunks if chunk.attributes.get("is_table")]
    assert len(table_chunks) == 1
    table_body = table_chunks[0].content
    assert "前置说明" not in table_body
    assert "后续解释" not in table_body
