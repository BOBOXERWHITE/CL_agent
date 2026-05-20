"""Tests for the Milvus 2.5+ native BM25 schema + ``search_bm25`` API.

These tests pin down the contract that ``MilvusVectorStore`` exposes to
the retriever layer once ``milvus_bm25_enabled=True``:

1. The collection schema gains a ``content`` VARCHAR field and a
   ``sparse_vector`` SPARSE_FLOAT_VECTOR field, bound by a ``BM25``
   Function whose tokenizer is taken from ``settings.milvus_bm25_tokenizer``.
2. ``upsert`` writes ``content`` into the new field so Milvus' Function
   can auto-compute the BM25 sparse vector server-side. (We do NOT
   compute the sparse vector in Python — that's the whole point of
   Milvus 2.5+.)
3. A new ``search_bm25(query_text, tenant_id, customer_id, top_k)``
   method mirrors ``search()``'s signature but routes through the
   sparse field; the tenant / customer scoping filter is preserved.
4. When ``milvus_bm25_enabled=False`` the schema reverts to the dense-only
   shape exactly as before, and ``search_bm25`` returns ``[]``. This keeps
   the legacy ``ILIKE`` path working bit-for-bit.

All tests inject hand-rolled fakes via ``__new__`` so they do not need
a live Milvus.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from app.core.config import Settings, get_settings
from app.services.rag.index_builder import VectorRecord
from app.services.rag.vector_store import MilvusVectorStore, NoopVectorStore

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeField:
    def __init__(self, *, name: str, dtype: object, **kwargs: Any) -> None:
        self.name = name
        self.dtype = dtype
        self.dim = kwargs.get("dim")
        # Mirror pymilvus FieldSchema's attribute surface enough for our
        # assertions: analyzer params + enable_analyzer.
        self.enable_analyzer = bool(kwargs.get("enable_analyzer", False))
        self.analyzer_params = kwargs.get("analyzer_params")
        self.is_primary = bool(kwargs.get("is_primary", False))
        self.max_length = kwargs.get("max_length")
        self.params = {"dim": self.dim} if self.dim is not None else {}


class _FakeFunction:
    def __init__(
        self,
        *,
        name: str,
        function_type: object,
        input_field_names: list[str],
        output_field_names: list[str],
    ) -> None:
        self.name = name
        self.function_type = function_type
        self.input_field_names = input_field_names
        self.output_field_names = output_field_names


class _FakeSchema:
    def __init__(self, *, fields: list[_FakeField], description: str = "") -> None:
        self.fields = fields
        self.description = description
        self.functions: list[_FakeFunction] = []

    def add_function(self, function: _FakeFunction) -> None:
        self.functions.append(function)


class _FakeCollection:
    # ClassVar because test fakes intentionally share the registry across
    # instantiations; ruff RUF012 otherwise demands per-instance attrs.
    instances: ClassVar[list[_FakeCollection]] = []

    def __init__(
        self,
        name: str,
        schema: _FakeSchema | None = None,
        using: str | None = None,
    ) -> None:
        self.name = name
        self.using = using
        self.schema = schema or _FakeSchema(
            fields=[_FakeField(name="embedding", dtype="FLOAT_VECTOR", dim=1024)]
        )
        self.indexes: list[tuple[str, dict[str, Any]]] = []
        self.inserts: list[list[list[Any]]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.search_result: list[list[SimpleNamespace]] = [[]]
        self.released = False
        _FakeCollection.instances.append(self)

    def create_index(self, field_name: str, index_params: dict[str, Any]) -> None:
        self.indexes.append((field_name, index_params))

    def insert(self, data: list[list[Any]]) -> None:
        self.inserts.append(data)

    def flush(self) -> None:
        pass

    def load(self) -> None:
        pass

    def release(self) -> None:
        self.released = True

    def delete(self, expr: str) -> None:
        pass

    def search(self, **kwargs: Any) -> list[list[SimpleNamespace]]:
        self.search_calls.append(kwargs)
        return self.search_result


class _FakeUtility:
    def __init__(self, *, exists: bool = False) -> None:
        self.exists = exists
        self.dropped: list[tuple[str, str | None]] = []

    def has_collection(self, name: str, using: str | None = None) -> bool:
        return self.exists

    def drop_collection(self, name: str, using: str | None = None) -> None:
        self.dropped.append((name, using))
        self.exists = False


def _build_store(
    *,
    bm25_enabled: bool,
    tokenizer: str = "jieba",
    exists: bool = False,
) -> tuple[MilvusVectorStore, _FakeUtility, Settings]:
    """Construct a MilvusVectorStore wired to fakes, with overridden settings."""
    _FakeCollection.instances = []
    base_settings = get_settings()
    overridden = replace(
        base_settings,
        milvus_bm25_enabled=bm25_enabled,
        milvus_bm25_tokenizer=tokenizer,
    )
    store = MilvusVectorStore.__new__(MilvusVectorStore)
    store._collection_name = "knowledge_chunks"
    store._collection_cls = _FakeCollection
    store._utility = _FakeUtility(exists=exists)
    store._schema_cls = _FakeSchema
    store._field_cls = _FakeField
    store._datatype = SimpleNamespace(
        VARCHAR="VARCHAR",
        FLOAT_VECTOR="FLOAT_VECTOR",
        SPARSE_FLOAT_VECTOR="SPARSE_FLOAT_VECTOR",
    )
    store._function_cls = _FakeFunction
    store._function_type = SimpleNamespace(BM25="BM25")
    store._embedding_dimension = 1024
    store._loaded = False
    store._bm25_enabled = bm25_enabled
    store._bm25_tokenizer = tokenizer
    return store, store._utility, overridden


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_schema_unchanged_when_bm25_disabled() -> None:
    """Default flag off → schema is the legacy 5-field dense-only shape."""
    store, _, _ = _build_store(bm25_enabled=False)
    collection = store._create_collection()
    field_names = [f.name for f in collection.schema.fields]
    assert field_names == [
        "chunk_id",
        "document_id",
        "tenant_id",
        "customer_id",
        "embedding",
    ]
    # No BM25 function attached
    assert collection.schema.functions == []
    # Only the dense HNSW index is built
    index_fields = [field for field, _ in collection.indexes]
    assert index_fields == ["embedding"]


def test_schema_adds_content_and_sparse_when_bm25_enabled() -> None:
    """With the flag on, schema gains content + sparse_vector and the BM25 Function."""
    store, _, _ = _build_store(bm25_enabled=True, tokenizer="jieba")
    collection = store._create_collection()
    field_names = [f.name for f in collection.schema.fields]
    assert "content" in field_names
    assert "sparse_vector" in field_names

    content_field = next(f for f in collection.schema.fields if f.name == "content")
    assert content_field.enable_analyzer is True
    assert content_field.analyzer_params == {"tokenizer": "jieba"}

    sparse_field = next(f for f in collection.schema.fields if f.name == "sparse_vector")
    assert sparse_field.dtype == "SPARSE_FLOAT_VECTOR"

    assert len(collection.schema.functions) == 1
    fn = collection.schema.functions[0]
    assert fn.function_type == "BM25"
    assert fn.input_field_names == ["content"]
    assert fn.output_field_names == ["sparse_vector"]


def test_schema_creates_sparse_inverted_index_when_bm25_enabled() -> None:
    """The sparse field must get a SPARSE_INVERTED_INDEX or Milvus
    will refuse the BM25 query at runtime."""
    store, _, _ = _build_store(bm25_enabled=True)
    collection = store._create_collection()
    sparse_indexes = [params for field, params in collection.indexes if field == "sparse_vector"]
    assert len(sparse_indexes) == 1
    assert sparse_indexes[0]["index_type"] == "SPARSE_INVERTED_INDEX"
    # metric_type for BM25 is always "BM25" (Milvus convention) — different
    # from the dense field's "IP".
    assert sparse_indexes[0]["metric_type"] == "BM25"


def test_schema_honours_tokenizer_override() -> None:
    """``settings.milvus_bm25_tokenizer`` flows into the analyzer params,
    so users can switch jieba → standard for non-Chinese corpora."""
    store, _, _ = _build_store(bm25_enabled=True, tokenizer="standard")
    collection = store._create_collection()
    content_field = next(f for f in collection.schema.fields if f.name == "content")
    assert content_field.analyzer_params == {"tokenizer": "standard"}


# ---------------------------------------------------------------------------
# Upsert tests
# ---------------------------------------------------------------------------


def test_upsert_writes_content_when_bm25_enabled() -> None:
    """The content string must reach Milvus so the BM25 Function can
    auto-compute the sparse vector. Without this, BM25 search returns 0 hits."""
    store, _, _ = _build_store(bm25_enabled=True)
    records = [
        VectorRecord(
            chunk_id="c1",
            document_id="d1",
            tenant_id="t1",
            customer_id="cust1",
            embedding=[0.1] * 1024,
            content="北京酒店报销上限是 650 元",
        ),
    ]
    store.upsert(records)
    # Last collection created is the one used for insert
    collection = _FakeCollection.instances[-1]
    assert len(collection.inserts) == 1
    columns = collection.inserts[0]
    # Order: chunk_id, document_id, tenant_id, customer_id, content, embedding
    assert columns[0] == ["c1"]
    assert columns[1] == ["d1"]
    assert columns[2] == ["t1"]
    assert columns[3] == ["cust1"]
    assert columns[4] == ["北京酒店报销上限是 650 元"]
    assert columns[5] == [[0.1] * 1024]


def test_upsert_omits_content_when_bm25_disabled() -> None:
    """Legacy collections must not receive the new column — Milvus would reject."""
    store, _, _ = _build_store(bm25_enabled=False)
    records = [
        VectorRecord(
            chunk_id="c1",
            document_id="d1",
            tenant_id="t1",
            customer_id="cust1",
            embedding=[0.1] * 1024,
            content="never used in this code path",
        ),
    ]
    store.upsert(records)
    collection = _FakeCollection.instances[-1]
    columns = collection.inserts[0]
    # Only 5 columns: chunk_id, document_id, tenant_id, customer_id, embedding
    assert len(columns) == 5


# ---------------------------------------------------------------------------
# search_bm25 tests
# ---------------------------------------------------------------------------


def test_search_bm25_returns_empty_when_bm25_disabled() -> None:
    """When the flag is off, search_bm25 short-circuits so retrievers
    can call it unconditionally without crashing on a missing field."""
    store, _, _ = _build_store(bm25_enabled=False, exists=True)
    hits = store.search_bm25(
        query_text="北京酒店报销",
        tenant_id="t1",
        customer_id="cust1",
        top_k=5,
    )
    assert hits == []


def test_search_bm25_routes_through_sparse_field_with_tenant_scope() -> None:
    """The search call must (a) target the sparse_vector field, (b) carry
    the raw query text (Milvus tokenizes it server-side), (c) preserve the
    tenant_id == ? AND customer_id == ? expression so cross-tenant rows
    cannot leak."""
    store, _, _ = _build_store(bm25_enabled=True, exists=True)

    # Pre-seed the fake collection's search return value
    fake_collection = _FakeCollection("knowledge_chunks", using="travel_ops")
    fake_collection.search_result = [
        [
            SimpleNamespace(entity={"chunk_id": "c1"}, id="c1", distance=2.34),
            SimpleNamespace(entity={"chunk_id": "c2"}, id="c2", distance=1.11),
        ]
    ]
    # Make the collection lookup return our pre-seeded one
    store._collection_cls = lambda name, using=None: fake_collection  # type: ignore[assignment]

    hits = store.search_bm25(
        query_text="北京酒店报销",
        tenant_id="t1",
        customer_id="cust1",
        top_k=5,
    )

    assert len(fake_collection.search_calls) == 1
    call = fake_collection.search_calls[0]
    assert call["anns_field"] == "sparse_vector"
    # Milvus 2.5+ BM25: raw text in, server tokenizes
    assert call["data"] == ["北京酒店报销"]
    assert call["limit"] == 5
    assert 'tenant_id == "t1"' in call["expr"]
    assert 'customer_id == "cust1"' in call["expr"]

    assert hits == [("c1", 2.34), ("c2", 1.11)]


def test_search_bm25_returns_empty_for_zero_top_k() -> None:
    """Defensive: callers occasionally pass top_k=0 from a UI that
    hasn't decided yet; we should return [] without hitting Milvus."""
    store, _, _ = _build_store(bm25_enabled=True, exists=True)
    hits = store.search_bm25(query_text="q", tenant_id="t1", customer_id="cust1", top_k=0)
    assert hits == []


def test_search_bm25_returns_empty_when_collection_missing() -> None:
    """A fresh deployment with no collection should not crash — same
    behaviour as the dense ``search()`` path."""
    store, _, _ = _build_store(bm25_enabled=True, exists=False)
    hits = store.search_bm25(query_text="q", tenant_id="t1", customer_id="cust1", top_k=5)
    assert hits == []


# ---------------------------------------------------------------------------
# NoopVectorStore parity
# ---------------------------------------------------------------------------


def test_noop_vector_store_implements_search_bm25_returning_empty() -> None:
    """Retrievers must be able to call search_bm25 on either backend
    without isinstance checks. Noop returns [] for parity."""
    store = NoopVectorStore()
    assert store.search_bm25(query_text="q", tenant_id="t1", customer_id="cust1", top_k=5) == []


# ---------------------------------------------------------------------------
# VectorRecord content field backward compat
# ---------------------------------------------------------------------------


def test_vector_record_content_defaults_to_empty_string() -> None:
    """Existing call sites that don't yet pass ``content`` must keep working;
    the BM25 path silently won't recall those rows, which is the expected
    behaviour pre-migration."""
    record = VectorRecord(
        chunk_id="c1",
        document_id="d1",
        tenant_id="t1",
        customer_id="cust1",
        embedding=[0.0] * 16,
    )
    assert record.content == ""


def test_vector_record_is_immutable() -> None:
    """The dataclass is frozen — accidental mutation should raise."""
    record = VectorRecord(
        chunk_id="c1",
        document_id="d1",
        tenant_id="t1",
        customer_id="cust1",
        embedding=[0.0] * 16,
        content="x",
    )
    with pytest.raises((AttributeError, TypeError)):
        record.chunk_id = "c2"  # type: ignore[misc]
