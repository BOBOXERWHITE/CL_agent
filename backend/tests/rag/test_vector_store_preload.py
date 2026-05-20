"""Tests for the P2.8 Milvus preload + per-query load elimination.

We don't bring up a real Milvus container for these tests; instead we
construct a ``MilvusVectorStore`` with hand-rolled fakes for ``utility``
and ``Collection``. This isolates the behavioural contract:

- ``preload`` calls ``collection.load()`` exactly once, flips
  ``_loaded`` to True, and short-circuits on subsequent calls.
- ``search`` no longer calls ``collection.load()`` when ``_loaded`` is
  already True (the old anti-pattern that triggered a load per query).
- Missing collection → preload is a silent no-op.
- Preload upstream failure → logged, no raise, ``_loaded`` stays False.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.rag.vector_store import MilvusVectorStore, NoopVectorStore


class _FakeCollection:
    def __init__(self) -> None:
        self.load_calls = 0
        self.search_calls = 0
        self.schema = SimpleNamespace(
            fields=[SimpleNamespace(name="embedding", params={"dim": 16}, dim=16)]
        )

    def load(self) -> None:
        self.load_calls += 1

    def search(self, **_kwargs) -> list[list[object]]:
        self.search_calls += 1
        return [[]]  # empty search result


class _FakeUtility:
    def __init__(self, *, has: bool = True) -> None:
        self.has = has

    def has_collection(self, name: str, using: str) -> bool:
        return self.has


def _fresh_store(
    *,
    has_collection: bool = True,
    collection: _FakeCollection | None = None,
) -> MilvusVectorStore:
    """Build a MilvusVectorStore without talking to real Milvus.

    Skips __init__ (which imports pymilvus and opens a socket) and wires
    only the attributes the tests need.
    """
    store = MilvusVectorStore.__new__(MilvusVectorStore)
    fake_collection = collection or _FakeCollection()
    store._collection_name = "knowledge_chunks"
    store._collection_cls = lambda name, using: fake_collection  # type: ignore[attr-defined,assignment]
    store._utility = _FakeUtility(has=has_collection)  # type: ignore[attr-defined]
    store._embedding_dimension = 16
    store._loaded = False
    # P6: BM25 fields are off by default in this fixture so the legacy
    # preload tests keep pinning the dense-only schema shape.
    store._bm25_enabled = False
    store._bm25_tokenizer = "jieba"
    store._function_cls = None
    store._function_type = None
    # Stash the fake so tests can assert on it.
    store.__test_collection__ = fake_collection  # type: ignore[attr-defined]
    return store


def test_preload_calls_load_exactly_once() -> None:
    store = _fresh_store()
    store.preload()
    assert store.__test_collection__.load_calls == 1  # type: ignore[attr-defined]
    assert store._loaded is True

    # Second preload must short-circuit.
    store.preload()
    assert store.__test_collection__.load_calls == 1  # type: ignore[attr-defined]


def test_preload_skips_when_collection_missing() -> None:
    store = _fresh_store(has_collection=False)
    store.preload()
    # No load call attempted; _loaded stays False so search can retry.
    assert store.__test_collection__.load_calls == 0  # type: ignore[attr-defined]
    assert store._loaded is False


def test_preload_swallows_upstream_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BoomCollection(_FakeCollection):
        def load(self) -> None:
            raise RuntimeError("milvus unreachable")

    store = _fresh_store(collection=_BoomCollection())
    # Should not raise; _loaded stays False.
    store.preload()
    assert store._loaded is False


def test_search_does_not_reload_after_preload(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _fresh_store()
    store.preload()
    # stub text_to_embedding so search doesn't try real embeddings.
    monkeypatch.setattr(
        "app.services.rag.vector_store.text_to_embedding",
        lambda text, dim: [0.0] * dim,
    )

    store.search(query_text="q", tenant_id="t", customer_id="c", top_k=3)
    store.search(query_text="q", tenant_id="t", customer_id="c", top_k=3)

    # load() from preload, then 0 additional loads from the 2 searches.
    assert store.__test_collection__.load_calls == 1  # type: ignore[attr-defined]
    assert store.__test_collection__.search_calls == 2  # type: ignore[attr-defined]


def test_search_triggers_defensive_load_when_preload_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If preload was never called (e.g. bootstrap skipped), the first
    search must still load the collection rather than hit unloaded data.
    """
    store = _fresh_store()
    monkeypatch.setattr(
        "app.services.rag.vector_store.text_to_embedding",
        lambda text, dim: [0.0] * dim,
    )
    assert store._loaded is False

    store.search(query_text="q", tenant_id="t", customer_id="c", top_k=3)
    # First search loaded; second should not reload.
    store.search(query_text="q", tenant_id="t", customer_id="c", top_k=3)
    assert store.__test_collection__.load_calls == 1  # type: ignore[attr-defined]


def test_noop_preload_is_a_no_op() -> None:
    # Smoke test: ensures the protocol method exists and does not raise.
    NoopVectorStore().preload()


def test_create_collection_uses_hnsw_index_params() -> None:
    """Pin the HNSW index params so a future refactor can't silently
    regress to AUTOINDEX / flat / etc.
    """
    captured: dict[str, object] = {}

    class _RecordingCollection(_FakeCollection):
        def create_index(self, *, field_name: str, index_params: dict[str, object]) -> None:
            captured["field_name"] = field_name
            captured["index_params"] = index_params

    store = _fresh_store(collection=_RecordingCollection())
    # Swap _collection_cls to a factory returning a new recording collection
    # each time, then call the internal _create_collection path.
    store._schema_cls = lambda *, fields, description: SimpleNamespace(  # type: ignore[attr-defined]
        fields=fields, description=description
    )
    store._field_cls = lambda **kwargs: SimpleNamespace(**kwargs)  # type: ignore[attr-defined]

    class _DataType:
        VARCHAR = "varchar"
        FLOAT_VECTOR = "float_vector"

    store._datatype = _DataType  # type: ignore[attr-defined]

    def _factory(name: str, schema=None, using: str = "") -> object:
        return store.__test_collection__  # type: ignore[attr-defined]

    store._collection_cls = _factory  # type: ignore[attr-defined,assignment]

    store._create_collection()

    assert captured["field_name"] == "embedding"
    params = captured["index_params"]
    assert isinstance(params, dict)
    assert params["index_type"] == "HNSW"
    assert params["metric_type"] == "IP"
    assert params["params"] == {"M": 16, "efConstruction": 200}
