# Phase 0 执行进度

> 依据：`docs/plans/2026-04-07-enterprise-migration-phase-0-2.md`
> 阶段目标：让改动这件事变得安全 —— 迁移、集成测试、异常体系、lifespan、类型与 lint

## 进度表

| ID | 任务 | 状态 | 完成时间 | 回归测试 |
|---|---|---|---|---|
| P0.1 | 引入 Alembic | ✅ 完成 | 2026-04-07 | 59 passed |
| P0.2 | Testcontainers 集成测试 | ✅ 代码完成 / ⏳ Docker 启动后验证 | 2026-04-07 | 59 passed + 6 skipped |
| P0.3 | 统一异常体系 | ✅ 完成 | 2026-04-07 | 65 passed |
| P0.4 | init_db + seed 移入 lifespan | ✅ 完成 | 2026-04-07 | 67 passed |
| P0.5 | 删除 _SessionLocalProxy drift 断言 | ✅ 完成 | 2026-04-07 | 67 passed |
| P0.6 | Ruff + mypy + pre-commit | ✅ 完成（非 strict 起步） | 2026-04-07 | 67 passed + ruff 全绿 |

## P0.1 验收明细

- `alembic heads` → `0001_baseline (head)` ✓
- 空 DB `alembic upgrade head` → 15 表 ✓
- `alembic revision --autogenerate` → 空 diff（无漂移）✓
- `alembic downgrade base` → 只剩 `alembic_version` ✓
- `pytest -q` → 59 passed（零回归）✓

## P0.2 验收明细

**代码层验收（不依赖 Docker）**
- `pytest -q`（默认排除 integration）→ 59 passed, 6 deselected ✓
- `pytest -m integration`（无 Docker）→ 6 skipped in 6.57s（健康检查快速失败）✓
- 主 conftest.py 的 autouse env fixture 对 integration marker 放行 ✓
- `alembic upgrade head` 在集成 session 启动时自动跑 ✓
- 容器间 `TRUNCATE ... CASCADE` 按测试用例隔离 ✓

**Docker 层验收（已完成 2026-04-17）**
- ✅ 启动 Docker Desktop + 国内镜像源预拉 postgres:16 / minio/minio (latest + RELEASE.2022-12-02T19-19-22Z) / testcontainers/ryuk:0.8.1
- ✅ `pytest -m integration -q` → **6 passed in 22.4s**（容器复用，单测 ~3s）
- ✅ 命中点全部验证：
  - `test_upload_persists_document_and_chunks_in_postgres`：PG 落 KnowledgeDocument + KnowledgeChunk ✓
  - `test_upload_puts_object_into_minio_bucket`：MinIO bucket 有对象 ✓
  - `test_agent_run_persists_to_postgres_with_tool_calls`：PG 落 AgentRun + ToolCallLog + JSON 列正确 ✓
  - `test_agent_run_over_threshold_creates_review_case`：PG 落 ReviewCase ✓
  - `test_chat_ask_persists_session_messages_and_recall_log`：PG 落 ChatSession + 2 ChatMessage + RagRecallLog ✓
  - `test_chat_ask_reuses_session_when_session_id_provided`：同一 session 下 4 ChatMessage ✓
- ✅ P1.1 引入 JWT 后，integration_client 同步加 admin-token 默认 header

**镜像源 workaround 记录**：用户网络无法直连 Docker Hub，daemon.json 配置 mirror 后 Docker Desktop 需 Restart 才生效。临时用 `daocloud.io` 前缀手动拉取 + retag 解决。后续如需在新机器跑集成测试，在 Docker Desktop Settings → Docker Engine 加 mirror 配置后重启即可。

## 未覆盖（明确记录为已识别风险）

- **Milvus 真集成**：P0.2 保留 noop，留给 P2.8 做。原因：P2.8 本来就要改 vector_store.py 支持 Milvus Lite / HNSW，两处改一起做避免返工
- **Celery 真异步**：`CELERY_TASK_ALWAYS_EAGER=true` 保留到 P4（Async 化）
- **RLS 越权测试**：要等 P1.4 RLS 落地后补

## Phase 0 总览

**已完成所有 6 个子任务**。回归测试全绿（67 单元 + 6 集成 skipped without Docker）。

核心工程性能改善：
- ✅ Schema 改动受 Alembic 管控，可以回滚、可以 diff、可以 stamp legacy
- ✅ 路由层清零 `init_db()` 每请求调用浪费；lifespan 仅跑 1 次 schema 初始化
- ✅ 错误响应统一 envelope，4xx / 5xx 分层清晰，catch-all 不泄漏内部消息
- ✅ Ruff 全仓 0 violation，format 一致化，43 文件被规整
- ✅ 集成测试基础设施就绪，Docker 起来后 6 个 pipeline 真实场景可立即验证
- ✅ `_SessionLocalProxy` drift 断言这个奇怪逻辑被清理

已识别、记录、但**不在 Phase 0 内处理**：
- 🔸 27 处 mypy strict 违规（跨 11 文件）：Phase 1 迁移时各模块同步清理
- 🔸 Milvus 真集成：P2.8 和 vector_store.py 改造一起做
- 🔸 Celery 真异步：P4

## P0.3 验收明细

- 8 个领域异常类（继承 `AppException`），`status_code` + `default_error_code` 对应齐全
- 4 个全局 handler 覆盖：domain / validation / legacy http / catch-all
- 响应体双写：`detail`（legacy shim） + `error`（权威结构）
- catch-all 不泄漏内部异常消息，只打 `INTERNAL_ERROR`
- 路由示范：knowledge / prompt_templates / evals / runtime_logs 已从 `HTTPException` 迁移
- 测试：`test_error_handlers.py` 6/6 通过
- 全量回归：`pytest -q` → 65 passed，零回归

## P0.4 / P0.5 / P0.6 验收明细

**P0.4 lifespan**：
- `create_app()` 用 `@asynccontextmanager lifespan`，启动时调一次 `init_db` + `seed_default_rules`
- 9 个路由文件清零 `init_db()` / `seed_default_rules()` 调用
- `init_db()` 按 `database_url` 去重（幂等 set）
- 新增 `test_lifespan_bootstrap.py` 2 用例验证 seed 只跑 1 次

**P0.5 Session 清理**：
- `_SessionLocalProxy` 类删除，替换为模块函数 `SessionLocal()`
- `integration/conftest.py` 补 `_initialized_urls.clear()` 重置

**P0.6 lint / format**：
- ruff 规则集：E/F/W/I/N/UP/B/C4/SIM/RET/RUF
- ruff format 修 43 个文件
- ruff check --fix 修 60 个问题 + 手动 4 个
- `.pre-commit-config.yaml` 用 `language: system` 避免 venv 开销
- Makefile 加 `lint / format / typecheck` target

## 下一步

Phase 0 收尾。下一步按规划进入 **Phase 1 (安全 & 多租户加固)**，起点 P1.1 引入 PyJWT 替换静态 token。预估 5 天。

**待办**（不阻塞开 Phase 1）：
- Docker Desktop 启动后跑一次 `make test-integration`，验证 6 个真 PG/MinIO 集成测试全绿
- 后续 Phase 1 路由迁移时，顺手清理各模块的 mypy strict 违规
