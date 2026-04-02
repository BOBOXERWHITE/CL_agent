from __future__ import annotations

import io
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.ingestion.pipeline import start_ingestion

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
        yield test_client

    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.fixture()
def docx_file() -> bytes:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>Travel Policy</w:t></w:r></w:p>
    <w:p><w:r><w:t>Employees can book economy class for domestic trips.</w:t></w:r></w:p>
    <w:p><w:r><w:t>Hotel reimbursement cap in Beijing is 650 CNY per night.</w:t></w:r></w:p>
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


@pytest.fixture()
def seeded_policy_chunks(docx_file: bytes) -> None:
    start_ingestion(
        file_bytes=docx_file,
        filename="policy.docx",
        content_type=DOCX_CONTENT_TYPE,
        tenant_id="t1",
        customer_id="c1",
    )
