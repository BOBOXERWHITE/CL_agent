"""Diagnostic: dump table chunks and probe lexical retrieval directly.

Not a CI gate — used to confirm the new chunker actually emits the
differential rate table as a single chunk and that lexical scoring picks
it up for queries that combine ``L2``/``北京``/``住宿``.
"""

from __future__ import annotations

from app.services.rag.retrievers import retrieve_lexical


def test_dump_rate_table_chunk_and_retrieval(seeded_hotel_knowledge_base: None, capsys) -> None:
    queries = [
        "L2 普通员工 北京 住宿 上限",
        "员工实际入住 760 元/晚 超过 L2 普通员工 北京 标准 8.6% 应按哪一档处理",
        "L2 普通员工去北京出差 周五入住周一离店 760 元 含早 发票 住宿费 餐饮费 合规 审批 早餐补贴 进项税",
        "房费超标 警告 超额自付",
    ]
    lines: list[str] = []
    for query in queries:
        hits = retrieve_lexical(query, "t1", "c1", top_k=8)
        lines.append("=" * 72)
        lines.append(f"QUERY: {query}")
        lines.append("-" * 72)
        for index, hit in enumerate(hits[:8], start=1):
            preview = hit.chunk.content.replace("\n", " ")[:140]
            tags = []
            if (hit.chunk.attributes_json or {}).get("is_table"):
                tags.append("TABLE")
            if "L2 普通员工" in hit.chunk.content:
                tags.append("HAS-L2")
            if "房费超标" in hit.chunk.content:
                tags.append("HAS-超标")
            tag_str = ",".join(tags) or "-"
            lines.append(f"  #{index} score={hit.combined_score:.3f} [{tag_str}] {preview}")
    print("\n".join(lines))
    captured = capsys.readouterr()
    print(captured.out)
