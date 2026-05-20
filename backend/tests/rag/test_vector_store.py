from __future__ import annotations

from types import SimpleNamespace

from app.services.rag.vector_store import MilvusVectorStore


def test_ensure_collection_recreates_milvus_collection_when_embedding_dimension_changes() -> None:
    class FakeField:
        def __init__(
            self, *, name: str, dtype: object, dim: int | None = None, **_: object
        ) -> None:
            self.name = name
            self.dtype = dtype
            self.dim = dim
            self.params = {"dim": dim} if dim is not None else {}

    class FakeSchema:
        def __init__(self, *, fields: list[FakeField], description: str) -> None:
            self.fields = fields
            self.description = description

    class FakeCollection:
        created: FakeCollection | None = None

        def __init__(
            self, name: str, schema: FakeSchema | None = None, using: str | None = None
        ) -> None:
            self.name = name
            self.using = using
            self.released = False
            self.index_args: tuple[str, dict[str, object]] | None = None
            if schema is None:
                self.schema = FakeSchema(
                    fields=[FakeField(name="embedding", dtype="FLOAT_VECTOR", dim=16)],
                    description="existing",
                )
            else:
                self.schema = schema
                FakeCollection.created = self

        def create_index(self, field_name: str, index_params: dict[str, object]) -> None:
            self.index_args = (field_name, index_params)

        def release(self) -> None:
            self.released = True

    class FakeUtility:
        def __init__(self) -> None:
            self.dropped: list[tuple[str, str | None]] = []
            self.exists = True

        def has_collection(self, name: str, using: str | None = None) -> bool:
            return self.exists

        def drop_collection(self, name: str, using: str | None = None) -> None:
            self.dropped.append((name, using))
            self.exists = False

    store = MilvusVectorStore.__new__(MilvusVectorStore)
    store._collection_name = "knowledge_chunks"
    store._collection_cls = FakeCollection
    store._utility = FakeUtility()
    store._schema_cls = FakeSchema
    store._field_cls = FakeField
    store._datatype = SimpleNamespace(VARCHAR="VARCHAR", FLOAT_VECTOR="FLOAT_VECTOR")
    store._embedding_dimension = 1024
    # P6: BM25 fields are opt-in; this test pins the legacy dense-only
    # schema shape, so leave the flag off.
    store._bm25_enabled = False
    store._bm25_tokenizer = "jieba"
    store._function_cls = None
    store._function_type = None

    collection = store._ensure_collection()

    assert store._utility.dropped == [("knowledge_chunks", "travel_ops")]
    assert FakeCollection.created is collection
    embedding_field = next(field for field in collection.schema.fields if field.name == "embedding")
    assert embedding_field.dim == 1024
    # P2.8: index switched from AUTOINDEX to HNSW with tuned M / efConstruction.
    assert collection.index_args == (
        "embedding",
        {
            "index_type": "HNSW",
            "metric_type": "IP",
            "params": {"M": 16, "efConstruction": 200},
        },
    )
