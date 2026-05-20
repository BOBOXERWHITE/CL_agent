from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.rag.index_builder import VectorRecord, text_to_embedding
from app.services.rag.settings import get_rag_settings

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorSearchHit:
    chunk_id: str
    score: float


class NoopVectorStore:
    def upsert(self, records: list[VectorRecord]) -> dict[str, str]:
        return {record.chunk_id: f"noop:{record.chunk_id}" for record in records}

    def search(
        self, *, query_text: str, tenant_id: str, customer_id: str, top_k: int
    ) -> list[tuple[str, float]]:
        del query_text, tenant_id, customer_id, top_k
        return []

    def search_bm25(
        self, *, query_text: str, tenant_id: str, customer_id: str, top_k: int
    ) -> list[tuple[str, float]]:
        """Parity with MilvusVectorStore so retrievers can call this
        method on either backend without isinstance checks."""
        del query_text, tenant_id, customer_id, top_k
        return []

    def delete(self, chunk_ids: list[str]) -> int:
        return len(chunk_ids)

    def preload(self) -> None:
        """No-op: the noop store has no state to warm."""
        return


class MilvusVectorStore:
    def __init__(self) -> None:
        from pymilvus import (
            Collection,
            CollectionSchema,
            DataType,
            FieldSchema,
            Function,
            FunctionType,
            connections,
            utility,
        )

        settings = get_settings()
        rag_settings = get_rag_settings()

        connections.connect(
            alias="travel_ops",
            host=settings.milvus_host,
            port=str(settings.milvus_port),
        )

        self._collection_name = rag_settings.milvus_collection_name
        self._collection_cls = Collection
        self._utility = utility
        self._schema_cls = CollectionSchema
        self._field_cls = FieldSchema
        self._datatype = DataType
        # P6: Milvus 2.5+ Function API for native BM25. Held as
        # instance attrs so unit tests can swap in fakes via __new__.
        self._function_cls = Function
        self._function_type = FunctionType
        self._embedding_dimension = rag_settings.embedding_dimension
        # P6: feature-flagged Milvus BM25 (Milvus 2.5+). When enabled,
        # the collection schema gains a content VARCHAR + sparse_vector
        # SPARSE_FLOAT_VECTOR field bound by a BM25 Function. Defaults
        # off to preserve legacy ILIKE-based lexical retrieval.
        self._bm25_enabled = settings.milvus_bm25_enabled
        self._bm25_tokenizer = settings.milvus_bm25_tokenizer
        # P2.8: track whether collection.load() has been called at least
        # once this process. search() used to call it per query, which
        # is the Milvus anti-pattern flagged in the original audit.
        self._loaded = False

    def _ensure_collection(self):
        if self._utility.has_collection(self._collection_name, using="travel_ops"):
            collection = self._collection_cls(self._collection_name, using="travel_ops")
            existing_dimension = self._get_embedding_dimension(collection)
            if existing_dimension in (None, self._embedding_dimension):
                return collection

            self._release_collection(collection)
            self._utility.drop_collection(self._collection_name, using="travel_ops")
            return self._create_collection()

        return self._create_collection()

    def _create_collection(self):
        fields = [
            self._field_cls(
                name="chunk_id",
                dtype=self._datatype.VARCHAR,
                is_primary=True,
                auto_id=False,
                max_length=64,
            ),
            self._field_cls(name="document_id", dtype=self._datatype.VARCHAR, max_length=64),
            self._field_cls(name="tenant_id", dtype=self._datatype.VARCHAR, max_length=64),
            self._field_cls(name="customer_id", dtype=self._datatype.VARCHAR, max_length=64),
        ]
        # P6: when BM25 is enabled the content + sparse_vector fields go
        # BEFORE the dense embedding so the Function's input/output names
        # resolve at schema construction time. The dense vector column is
        # always the last entity-data column so the upsert tuple order
        # stays predictable across both branches.
        if self._bm25_enabled:
            fields.append(
                self._field_cls(
                    name="content",
                    dtype=self._datatype.VARCHAR,
                    # 65535 is the Milvus VARCHAR ceiling; chunks are
                    # normally <2k chars so we have generous headroom.
                    max_length=65535,
                    enable_analyzer=True,
                    analyzer_params={"tokenizer": self._bm25_tokenizer},
                )
            )
            fields.append(
                self._field_cls(
                    name="sparse_vector",
                    dtype=self._datatype.SPARSE_FLOAT_VECTOR,
                )
            )
        fields.append(
            self._field_cls(
                name="embedding",
                dtype=self._datatype.FLOAT_VECTOR,
                dim=self._embedding_dimension,
            )
        )

        schema = self._schema_cls(
            fields=fields,
            description="Knowledge chunk embeddings",
        )

        # P6: bind the BM25 Function to content → sparse_vector so
        # Milvus auto-tokenizes (jieba for Chinese by default) and
        # writes BM25 weights into sparse_vector on every insert.
        if self._bm25_enabled:
            schema.add_function(
                self._function_cls(
                    name="bm25_emit",
                    function_type=self._function_type.BM25,
                    input_field_names=["content"],
                    output_field_names=["sparse_vector"],
                )
            )

        collection = self._collection_cls(
            self._collection_name,
            schema=schema,
            using="travel_ops",
        )
        # P2.8: use HNSW instead of AUTOINDEX for tunable recall/latency.
        # M=16 efConstruction=200 are the Milvus docs' recommended defaults
        # for <1M vector collections; ef=64 at query time is a good starting
        # point and can be raised (`param={"params": {"ef": 128}}`) to lift
        # recall at the cost of latency.
        collection.create_index(
            field_name="embedding",
            index_params={
                "index_type": "HNSW",
                "metric_type": "IP",
                "params": {"M": 16, "efConstruction": 200},
            },
        )
        if self._bm25_enabled:
            # SPARSE_INVERTED_INDEX is the only index type Milvus accepts
            # for a sparse vector that backs a BM25 Function; metric_type
            # must be "BM25" so the server applies the Okapi formula on
            # query time rather than computing IP / cosine over weights.
            collection.create_index(
                field_name="sparse_vector",
                index_params={
                    "index_type": "SPARSE_INVERTED_INDEX",
                    "metric_type": "BM25",
                },
            )
        return collection

    @staticmethod
    def _get_embedding_dimension(collection) -> int | None:
        schema = getattr(collection, "schema", None)
        fields = getattr(schema, "fields", None)
        if not fields:
            return None

        for field in fields:
            if getattr(field, "name", None) != "embedding":
                continue

            params = getattr(field, "params", None) or {}
            if isinstance(params, dict) and params.get("dim") is not None:
                return int(params["dim"])

            dim = getattr(field, "dim", None)
            if dim is not None:
                return int(dim)
        return None

    @staticmethod
    def _release_collection(collection) -> None:
        release = getattr(collection, "release", None)
        if callable(release):
            try:
                release()
            except Exception:
                pass

    @staticmethod
    def _escape_literal(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _delete_existing(self, collection, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return

        batch_size = 200
        for start in range(0, len(chunk_ids), batch_size):
            batch = chunk_ids[start : start + batch_size]
            encoded = ", ".join(f'"{self._escape_literal(chunk_id)}"' for chunk_id in batch)
            collection.delete(expr=f"chunk_id in [{encoded}]")

    def upsert(self, records: list[VectorRecord]) -> dict[str, str]:
        collection = self._ensure_collection()
        if not records:
            return {}

        self._delete_existing(collection, [record.chunk_id for record in records])
        columns: list[list[object]] = [
            [record.chunk_id for record in records],
            [record.document_id for record in records],
            [record.tenant_id for record in records],
            [record.customer_id for record in records],
        ]
        # P6: insert column order must mirror schema field order. When
        # BM25 is on, content comes BEFORE embedding; sparse_vector is
        # auto-populated by the BM25 Function so we never pass it.
        if self._bm25_enabled:
            columns.append([record.content for record in records])
        columns.append([record.embedding for record in records])
        collection.insert(columns)
        collection.flush()
        return {record.chunk_id: record.chunk_id for record in records}

    def delete(self, chunk_ids: list[str]) -> int:
        if not chunk_ids:
            return 0
        if not self._utility.has_collection(self._collection_name, using="travel_ops"):
            return 0

        collection = self._collection_cls(self._collection_name, using="travel_ops")
        self._delete_existing(collection, chunk_ids)
        collection.flush()
        return len(chunk_ids)

    def preload(self) -> None:
        """Warm the collection into Milvus memory once per process.

        Called from the FastAPI lifespan hook (P2.8). Safe to call
        repeatedly: subsequent calls short-circuit via ``_loaded``.
        Failures here must not crash app startup -- search() will
        opportunistically retry the load on first use.
        """
        if self._loaded:
            return
        try:
            if not self._utility.has_collection(self._collection_name, using="travel_ops"):
                _log.info(
                    "milvus_preload_skipped_collection_missing",
                    extra={"collection": self._collection_name},
                )
                return
            collection = self._collection_cls(self._collection_name, using="travel_ops")
            collection.load()
            self._loaded = True
            _log.info(
                "milvus_collection_loaded",
                extra={"collection": self._collection_name},
            )
        except Exception as exc:
            _log.warning(
                "milvus_preload_failed",
                extra={"collection": self._collection_name, "error": str(exc)},
            )

    def search(
        self, *, query_text: str, tenant_id: str, customer_id: str, top_k: int
    ) -> list[tuple[str, float]]:
        if top_k <= 0:
            return []

        if not self._utility.has_collection(self._collection_name, using="travel_ops"):
            return []

        collection = self._collection_cls(self._collection_name, using="travel_ops")
        # P2.8: load once per process, not per query. ``_loaded`` is
        # flipped by ``preload()`` (lifespan) or by this defensive call
        # if preload was skipped / failed.
        if not self._loaded:
            collection.load()
            self._loaded = True
        query_vector = text_to_embedding(query_text, self._embedding_dimension)
        safe_tenant = self._escape_literal(tenant_id)
        safe_customer = self._escape_literal(customer_id)
        expr = f'tenant_id == "{safe_tenant}" and customer_id == "{safe_customer}"'
        search_result = collection.search(
            data=[query_vector],
            anns_field="embedding",
            # HNSW search param: ef=64 is a sensible starting default; raise
            # to trade latency for recall.
            param={"metric_type": "IP", "params": {"ef": 64}},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id"],
        )

        hits: list[tuple[str, float]] = []
        for hit in search_result[0]:
            hits.append((str(hit.entity.get("chunk_id") or hit.id), float(hit.distance)))
        return hits

    def search_bm25(
        self, *, query_text: str, tenant_id: str, customer_id: str, top_k: int
    ) -> list[tuple[str, float]]:
        """P6: Native Milvus BM25 over the sparse_vector field.

        Mirrors :meth:`search` but routes through the BM25-bound sparse
        field. Returns ``[]`` when the BM25 feature flag is off or the
        collection has not been created yet, so callers can invoke this
        method unconditionally without isinstance / feature-flag checks
        at every site.

        The raw ``query_text`` is sent to Milvus as-is — the server-side
        BM25 Function tokenizes it with the configured analyzer (jieba
        for Chinese) and computes the score against every chunk's
        sparse weights. Tenant + customer filtering is preserved as a
        boolean expression so cross-tenant rows cannot leak.
        """
        if not self._bm25_enabled or top_k <= 0:
            return []
        if not self._utility.has_collection(self._collection_name, using="travel_ops"):
            return []

        collection = self._collection_cls(self._collection_name, using="travel_ops")
        if not self._loaded:
            collection.load()
            self._loaded = True

        safe_tenant = self._escape_literal(tenant_id)
        safe_customer = self._escape_literal(customer_id)
        expr = f'tenant_id == "{safe_tenant}" and customer_id == "{safe_customer}"'
        # ``drop_ratio_search`` is a Milvus BM25 tuning knob: 0.2 drops
        # the bottom 20 % of low-weight matches at query time, which
        # cuts latency on long queries without changing recall@k for
        # the kind of question lengths we see in this product (<40 chars).
        search_result = collection.search(
            data=[query_text],
            anns_field="sparse_vector",
            param={"metric_type": "BM25", "params": {"drop_ratio_search": 0.2}},
            limit=top_k,
            expr=expr,
            output_fields=["chunk_id"],
        )

        hits: list[tuple[str, float]] = []
        for hit in search_result[0]:
            hits.append((str(hit.entity.get("chunk_id") or hit.id), float(hit.distance)))
        return hits


def get_vector_store() -> NoopVectorStore | MilvusVectorStore:
    settings = get_settings()
    if settings.vector_store_provider == "milvus":
        return MilvusVectorStore()
    return NoopVectorStore()
