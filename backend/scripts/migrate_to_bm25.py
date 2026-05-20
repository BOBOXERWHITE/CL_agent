"""One-shot migration: switch the Milvus collection to a BM25-enabled schema.

What it does
============
1. Verifies ``MILVUS_BM25_ENABLED=true`` in the live ``settings``. The
   ``vector_store`` only adds the BM25 fields when this flag is set, so
   running the migration without it would just rebuild the old shape.
2. Drops the existing Milvus collection so the next upsert recreates it
   with the new schema (content VARCHAR + sparse_vector SPARSE_FLOAT_VECTOR
   + BM25 Function bound between them).
3. Calls ``rebuild_knowledge_index()`` to reingest every completed
   document. The pipeline already wires ``VectorRecord.content`` from the
   chunk content, so the BM25 Function gets the right text on insert.
4. Prints a before/after summary so operators can confirm the row counts
   match.

Safety
======
- DESTRUCTIVE: the Milvus drop is irreversible. The script refuses to run
  unless ``--confirm`` is passed; ``--dry-run`` shows what *would* happen
  without touching state.
- Idempotent on the PG side: PG chunks are not touched. Only the Milvus
  collection is dropped + rebuilt.
- Tenant data is preserved because the rebuild iterates over every
  document and re-upserts with the same chunk_id / tenant_id / customer_id.

Usage
=====
::

    # Preview — no state change:
    python backend/scripts/migrate_to_bm25.py --dry-run

    # Actually do it:
    export MILVUS_BM25_ENABLED=true
    python backend/scripts/migrate_to_bm25.py --confirm

    # After the migration succeeds, flip the retrieval path:
    export LEXICAL_BACKEND=milvus_bm25

Run the eval gate against the new backend to confirm answer correctness
and faithfulness did not regress before flipping LEXICAL_BACKEND in
production.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Final

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_log = logging.getLogger("migrate_to_bm25")

_EX_PRECONDITION_FAILED: Final = 64  # BSD sysexits.h EX_USAGE


def _verify_bm25_enabled() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    if not settings.milvus_bm25_enabled:
        _log.error(
            "MILVUS_BM25_ENABLED is False. Set it to true in your env before running "
            "this migration, otherwise the rebuilt collection will not contain the "
            "BM25 fields and the migration is a no-op."
        )
        sys.exit(_EX_PRECONDITION_FAILED)
    if settings.vector_store_provider != "milvus":
        _log.error(
            "VECTOR_STORE_PROVIDER=%r, but this migration only applies to Milvus. Aborting.",
            settings.vector_store_provider,
        )
        sys.exit(_EX_PRECONDITION_FAILED)


def _count_documents() -> tuple[int, int]:
    """Return (document_count, chunk_count) of completed documents in PG.

    Used for the before / after summary so operators see at a glance that
    the rebuild covered everything.
    """
    from sqlalchemy import func, select

    from app.db.models.knowledge import KnowledgeChunk, KnowledgeDocument
    from app.db.session import bypass_rls_session, init_db

    init_db()
    with bypass_rls_session() as session:
        doc_count = session.scalar(
            select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.status == "completed")
        )
        chunk_count = session.scalar(
            select(func.count(KnowledgeChunk.id))
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            )
            .where(KnowledgeDocument.status == "completed")
        )
    return int(doc_count or 0), int(chunk_count or 0)


def _drop_collection() -> None:
    """Drop the Milvus collection so the next upsert recreates it with
    the BM25-enabled schema. No-op when the collection does not exist
    (fresh deployment)."""
    from app.core.config import get_settings
    from app.services.rag.vector_store import MilvusVectorStore

    settings = get_settings()
    # Instantiate just to open the pymilvus connection; we don't reuse it
    # beyond drop_collection because the next upsert call from
    # rebuild_knowledge_index will build its own MilvusVectorStore that
    # observes the new MILVUS_BM25_ENABLED flag.
    store = MilvusVectorStore()
    name = settings.milvus_collection_name
    if store._utility.has_collection(name, using="travel_ops"):
        _log.info("dropping existing Milvus collection: %s", name)
        # Release before drop to avoid the "collection still loaded" race.
        try:
            from pymilvus import Collection

            Collection(name, using="travel_ops").release()
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("collection.release() raised %r (continuing)", exc)
        store._utility.drop_collection(name, using="travel_ops")
        _log.info("dropped: %s", name)
    else:
        _log.info("no existing collection named %r (nothing to drop)", name)


def _rebuild_all() -> tuple[int, int]:
    """Reingest every completed document. Returns (document_count, chunk_count)."""
    from app.services.ingestion.pipeline import rebuild_knowledge_index

    snapshot = rebuild_knowledge_index()
    _log.info(
        "rebuilt: scope=%s documents=%d chunks=%d",
        snapshot.scope,
        snapshot.document_count,
        snapshot.chunk_count,
    )
    return snapshot.document_count, snapshot.chunk_count


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="migrate-to-bm25",
        description=(
            "Drop and rebuild the Milvus collection with the BM25-enabled "
            "schema. DESTRUCTIVE — requires --confirm."
        ),
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--confirm",
        action="store_true",
        help="Actually drop + rebuild. Required for any state change.",
    )
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen and exit 0 without touching Milvus.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _verify_bm25_enabled()

    docs_before, chunks_before = _count_documents()
    _log.info(
        "preflight: %d completed documents (%d chunks) in PG",
        docs_before,
        chunks_before,
    )

    if args.dry_run:
        _log.info(
            "--dry-run set: would drop Milvus collection and reingest %d chunks", chunks_before
        )
        return 0

    _drop_collection()
    docs_after, chunks_after = _rebuild_all()

    if docs_after != docs_before or chunks_after != chunks_before:
        _log.error(
            "row count mismatch: PG had (%d docs, %d chunks) before rebuild "
            "but rebuild snapshot reports (%d, %d). Investigate before flipping "
            "LEXICAL_BACKEND=milvus_bm25.",
            docs_before,
            chunks_before,
            docs_after,
            chunks_after,
        )
        return 1

    _log.info(
        "migration complete: %d documents / %d chunks reingested. Next step: "
        "set LEXICAL_BACKEND=milvus_bm25 and run the eval gate.",
        docs_after,
        chunks_after,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
