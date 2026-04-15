from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings
from app.services.rag.index_builder import VectorRecord, text_to_embedding
from app.services.rag.settings import get_rag_settings


@dataclass(frozen=True)
class VectorSearchHit:
    chunk_id: str
    score: float


class NoopVectorStore:
    def upsert(self, records: list[VectorRecord]) -> dict[str, str]:
        return {record.chunk_id: f"noop:{record.chunk_id}" for record in records}

    def search(self, *, query_text: str, tenant_id: str, customer_id: str, top_k: int) -> list[tuple[str, float]]:
        del query_text, tenant_id, customer_id, top_k
        return []

    def delete(self, chunk_ids: list[str]) -> int:
        return len(chunk_ids)


class MilvusVectorStore:
    def __init__(self) -> None:
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

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
        self._embedding_dimension = rag_settings.embedding_dimension

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
        schema = self._schema_cls(
            fields=[
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
                self._field_cls(
                    name="embedding",
                    dtype=self._datatype.FLOAT_VECTOR,
                    dim=self._embedding_dimension,
                ),
            ],
            description="Knowledge chunk embeddings",
        )

        collection = self._collection_cls(
            self._collection_name,
            schema=schema,
            using="travel_ops",
        )
        collection.create_index(
            field_name="embedding",
            index_params={"index_type": "AUTOINDEX", "metric_type": "IP"},
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
        collection.insert(
            [
                [record.chunk_id for record in records],
                [record.document_id for record in records],
                [record.tenant_id for record in records],
                [record.customer_id for record in records],
                [record.embedding for record in records],
            ]
        )
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

    def search(self, *, query_text: str, tenant_id: str, customer_id: str, top_k: int) -> list[tuple[str, float]]:
        if top_k <= 0:
            return []

        if not self._utility.has_collection(self._collection_name, using="travel_ops"):
            return []

        collection = self._collection_cls(self._collection_name, using="travel_ops")
        collection.load()
        query_vector = text_to_embedding(query_text, self._embedding_dimension)
        safe_tenant = self._escape_literal(tenant_id)
        safe_customer = self._escape_literal(customer_id)
        expr = f'tenant_id == "{safe_tenant}" and customer_id == "{safe_customer}"'
        search_result = collection.search(
            data=[query_vector],
            anns_field="embedding",
            param={"metric_type": "IP", "params": {}},
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
