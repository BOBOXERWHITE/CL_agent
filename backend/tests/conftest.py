from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.ingestion.pipeline import start_ingestion

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _build_docx_file(paragraphs: list[str]) -> bytes:
    paragraph_xml = "\n".join(
        f"    <w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>" for paragraph in paragraphs
    )
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
{paragraph_xml}
  </w:body>
</w:document>
"""

    content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

    rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", rels_xml)
        archive.writestr("word/document.xml", document_xml)

    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _test_environment(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Integration tests manage their own environment (real PG + real MinIO via
    # testcontainers). Skip the lightweight SQLite defaults for them.
    if request.node.get_closest_marker("integration"):
        return

    database_path = tmp_path / "travel_ops.db"
    storage_root = tmp_path / "object-store"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "local")
    monkeypatch.setenv("OBJECT_STORAGE_ROOT", str(storage_root))
    monkeypatch.setenv("VECTOR_STORE_PROVIDER", "noop")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture()
def client(_test_environment: None) -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        # P1.1 removed the ``auth_enabled=false`` admin bypass. Tests now
        # authenticate with the default static admin token; individual tests
        # that need a specific role can override via ``client.headers`` or
        # pass per-request ``headers=...``.
        test_client.headers.update({"Authorization": "Bearer admin-token"})
        yield test_client

    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture()
def docx_file() -> bytes:
    return _build_docx_file(
        [
            "Travel Policy",
            "Employees can book economy class for domestic trips.",
            "Hotel reimbursement cap in Beijing is 650 CNY per night.",
        ]
    )


@pytest.fixture()
def multilingual_docx_file() -> bytes:
    return _build_docx_file(
        [
            "差旅政策总则",
            "国内出差机票应优先预订 economy class，特殊情况需要审批。",
            "北京酒店报销上限为每晚 650 元。",
            "Shanghai hotel reimbursement cap is 550 CNY per night.",
            "提交报销前需要确认发票抬头与出差城市一致。",
        ]
    )


@pytest.fixture()
def seeded_policy_chunks(docx_file: bytes) -> None:
    start_ingestion(
        file_bytes=docx_file,
        filename="policy.docx",
        content_type=DOCX_CONTENT_TYPE,
        tenant_id="t1",
        customer_id="c1",
    )


@pytest.fixture()
def seeded_multilingual_policy_chunks(multilingual_docx_file: bytes) -> None:
    start_ingestion(
        file_bytes=multilingual_docx_file,
        filename="multilingual-policy.docx",
        content_type=DOCX_CONTENT_TYPE,
        tenant_id="t1",
        customer_id="c1",
    )


_HOTEL_KB_DIR = Path(__file__).resolve().parents[2] / "docs" / "knowledge-base" / "hotel"


@pytest.fixture()
def seeded_hotel_knowledge_base() -> None:
    """Ingest every ``docs/knowledge-base/hotel/*.md`` into tenant ``t1``.

    Used by the multi-hop eval baseline so the runner exercises the real
    differential-rate / breakfast / invoice / weekend-stay policy text
    rather than the trimmed fixture used by the smoke dataset.
    """
    if not _HOTEL_KB_DIR.is_dir():
        pytest.skip(f"hotel kb directory missing: {_HOTEL_KB_DIR}")

    markdown_files = sorted(_HOTEL_KB_DIR.glob("*.md"))
    if not markdown_files:
        pytest.skip(f"no markdown files under {_HOTEL_KB_DIR}")

    for path in markdown_files:
        start_ingestion(
            file_bytes=path.read_bytes(),
            filename=path.name,
            content_type="text/markdown",
            tenant_id="t1",
            customer_id="c1",
        )
