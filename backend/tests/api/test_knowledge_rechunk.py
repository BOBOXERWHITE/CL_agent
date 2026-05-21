"""Verify the rechunk endpoint regenerates chunk boundaries from the
original file in object storage.

The contract under test:

1. After ``/rechunk``, old chunk rows are gone and new ones replace them.
2. New chunks come from the *current* chunker logic — for a Markdown
   file containing a pipe table, the table-aware chunker emits the
   table as a single chunk with ``is_table=True`` in attributes.
3. The document_id is stable across the operation; only its chunk
   children turn over.
4. ``scope=all`` works when no document_id is supplied.
"""

from __future__ import annotations

from app.db.models.knowledge import KnowledgeChunk
from app.db.session import SessionLocal

_MARKDOWN_WITH_TABLE = b"""# Travel policy with a rate table

### 2.2 Differential rate (RMB / night)

| Level | A tier | B tier |
| --- | --- | --- |
| L1 | 500 | 350 |
| L2 employee | 700 | 500 |
| L3 senior | 900 | 650 |

Some prose after the table that talks about approval flow.
"""


def _upload_markdown(client) -> str:
    response = client.post(
        "/api/knowledge/upload",
        data={"tenant_id": "t1", "customer_id": "c1"},
        files={"file": ("policy.md", _MARKDOWN_WITH_TABLE, "text/markdown")},
    )
    assert response.status_code == 202, response.text
    return response.json()["document_id"]


def _chunk_rows_for(document_id: str) -> list[KnowledgeChunk]:
    with SessionLocal() as session:
        return (
            session.query(KnowledgeChunk)
            .filter(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index.asc())
            .all()
        )


def test_rechunk_endpoint_replaces_chunks_in_place(client) -> None:
    document_id = _upload_markdown(client)
    original_chunk_ids = {chunk.id for chunk in _chunk_rows_for(document_id)}
    assert original_chunk_ids, "upload should produce at least one chunk"

    response = client.post(
        "/api/knowledge/rechunk",
        json={"document_id": document_id},
    )
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["scope"] == "document"
    assert payload["document_count"] == 1
    assert payload["document_ids"] == [document_id]
    assert payload["chunk_count"] > 0

    rechunked = _chunk_rows_for(document_id)
    rechunked_ids = {chunk.id for chunk in rechunked}
    # Chunk IDs are regenerated — the row turnover is what makes the new
    # chunker logic actually take effect for downstream retrieval.
    assert rechunked_ids.isdisjoint(original_chunk_ids)


def test_rechunk_emits_table_aware_chunk_for_pipe_table(client) -> None:
    document_id = _upload_markdown(client)

    response = client.post(
        "/api/knowledge/rechunk",
        json={"document_id": document_id},
    )
    assert response.status_code == 200, response.text

    chunks = _chunk_rows_for(document_id)
    table_chunks = [chunk for chunk in chunks if (chunk.attributes_json or {}).get("is_table")]
    assert len(table_chunks) == 1, (
        "rechunk should produce exactly one table chunk for the pipe table"
    )
    body = table_chunks[0].content
    # Heading prepended for semantic anchor.
    assert "Differential rate" in body
    # Every level row in the table survives in the same chunk.
    for row in ("L1 | 500", "L2 employee | 700", "L3 senior | 900"):
        assert row in body
    # Surrounding prose must NOT have been merged into the table chunk.
    assert "approval flow" not in body


def test_rechunk_all_scope_when_document_id_omitted(client) -> None:
    document_id = _upload_markdown(client)

    response = client.post("/api/knowledge/rechunk", json={})
    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["scope"] == "all"
    assert document_id in payload["document_ids"]


def test_rechunk_returns_404_for_unknown_document(client) -> None:
    response = client.post(
        "/api/knowledge/rechunk",
        json={"document_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"
