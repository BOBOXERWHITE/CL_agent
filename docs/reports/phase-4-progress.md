# Phase 4 执行进度

> 依据：`docs/plans/2026-04-23-phase-4-async-workflow.md`
> 阶段目标：异步化 + 任务真异步 + 背压 —— 异步/扩展性维度 3.5 → 7.0

## 进度表

| ID | 任务 | 状态 | 完成日期 | 测试 |
|---|---|---|---|---|
| P4.1 | 异步 HTTP 客户端 | ✅ 完成 | 2026-04-23 | +13 新单测，299 total passed |
| P4.2 | 热路由异步化 | ✅ 完成 | 2026-04-23 | +13 新单测，312 total passed |
| P4.3 | Celery 生产守卫 + retry | ✅ 完成 | 2026-04-23 | +6 新单测，318 total passed |
| P4.4 | Task 状态表 + 幂等键 | ✅ 完成 | 2026-04-23 | +12 新单测，330 total passed |
| P4.5 | Task 状态 API + cancel | ✅ 完成 | 2026-04-23 | +12 新单测，342 total passed |
| P4.6 | Phase 4 review | ✅ 完成 | 2026-04-23 | 见 `phase-4-review.md` |

## P4.1 验收明细

**交付**：
- `backend/app/services/rag/async_http_client.py` — 进程级共享 `AsyncClient` 工厂（double-checked lock 单例 + `aclose()` 由 lifespan shutdown 调用）
- `backend/app/services/rag/embedding_client.py` — 新 `embed_texts_async` / `_embed_batch_async` / `texts_to_embeddings_async` / `text_to_embedding_async`；老 sync API 一字未动
- `backend/app/main.py` — lifespan shutdown 关闭 async client
- `backend/pyproject.toml` — 新增 dev 依赖 `pytest-asyncio>=0.24` + `asyncio_mode = "auto"`
- `backend/tests/rag/test_embedding_client_async.py` 13 用例

**核心设计**：
- **AsyncClient 进程级单例**：避免 per-request 创建（httpx 会报 dangling client 警告 + 无连接池复用）；避免 import time 创建（测试环境 `get_settings` 还没 resolve）。延迟初始化 + lifespan 明确关闭
- **孪生而非替换**：每个 provider 加 `*_async` 方法，老 `embed_texts` / `texts_to_embeddings` 完全保留（Celery worker / eval runner 还在 sync 上下文）
- **重试语义对齐**：async 用 `asyncio.sleep(2**attempt * 0.1)` 指数退避，和 sync 的 busy-loop 在尝试次数 / 重试触发 status 上完全一致，确保两条路径对同一失败给出同一结果
- **注入友好**：`embed_texts_async(texts, dim, async_client=...)` 允许测试直接传 `httpx.AsyncClient(transport=MockTransport(...))`，生产调用省略参数拿共享 client
- **连接池参数**：`max_keepalive_connections=20` + `max_connections=100`，覆盖单 FastAPI worker 的典型并发

**测试覆盖**（13 用例）：
- Deterministic 客户端 async == sync 1
- OpenAI-compat happy path（请求体 / auth header 校验）1
- 大 batch 自动分片（5 items, batch=2 → 3 次请求）1
- 5xx 单次 retry 后成功 1
- 4xx 非重试立即失败 1
- 空输入不发 HTTP 1
- RequestError 重试到上限后 raise 1
- **并发 8 个请求不串行**（asyncio.gather，wall-clock < 3×single）1
- AsyncClient 单例复用 + idempotent close 2
- `texts_to_embeddings_async` 二次调用命中缓存 + 空输入 + single-text 便捷函数 3

**验收数据**：
- `pytest tests/rag/test_embedding_client_async.py -q` → 13/13 pass
- `pytest -q --ignore=tests/integration` → 299 pass（零回归，基线 286）
- ruff → 0 violations

## P4.2 验收明细

**交付**：
- `backend/app/services/llm/rewrite_client.py` — `DeterministicRewriteClient` + `OpenAICompatibleRewriteClient` 新增 `_chat_async` / `paraphrase_async` / `generate_hyde_document_async`；老 sync API 不变
- `backend/app/services/llm/client.py` — `DeterministicPolicyAnswerClient` + `OpenAICompatiblePolicyAnswerClient` 新增 `generate_answer_async`；老 sync API 不变
- `backend/app/services/rag/query_rewriter.py` — 新 `rewrite_query_multi_async`（`getattr` 探测客户端是否支持 `*_async` 方法，legacy sync-only 客户端走 `asyncio.to_thread` 降级，保持兼容）
- `backend/app/services/rag/query_engine.py` — 新 `answer_policy_question_async`：两条 LLM 热路径 (rewrite + generate) 用 `await`；Milvus / SQL 检索走 `asyncio.to_thread` 不阻塞事件循环；cache / citation 构造保持 sync
- `backend/app/api/routes/chat.py` — `POST /api/chat/ask` 改 `async def`，内部 `await answer_policy_question_async`；签名对外不变
- `backend/tests/rag/test_query_engine_async.py` 5 用例（parity + 并发 + 空证据 + 空 query）
- `backend/tests/rag/test_rewrite_client_async.py` 6 用例（rewrite / HyDE / 答案生成 async）
- `backend/tests/api/test_chat_ask_async.py` 2 路由级用例（`httpx.AsyncClient` + `ASGITransport`）

**核心设计**：
- **事件循环真正解放**：`answer_policy_question_async` 里两个 HTTP 调用（rewrite 和 generate）通过 `await` + 共享 `AsyncClient`（P4.1）真正并发；sync 检索包在 `asyncio.to_thread` 里由线程池并行处理
- **Parity 是硬契约**：`test_async_matches_sync_for_same_inputs` 钉死"同样的输入，sync 和 async 必须返回相同 `PolicyAnswerResult`"，防止两条路径悄悄漂移
- **Legacy sync-only 客户端不 break**：`rewrite_query_multi_async` 用 `getattr(client, "paraphrase_async", None)` 探测，拿不到就 `asyncio.to_thread` 降级，任何第三方实现的 RewriteClient Protocol 都能接
- **DB 会话保持 sync**：短查询跨 FastAPI async 路由的 sync `Session` 是官方推荐模式；AsyncSession 全量迁移留给 Phase 6
- **TestClient 对 async 路由透明**：所有老测试无改动直接通过

**测试覆盖**（13 用例）：
- rewrite client async 6：deterministic parity / 正常解析 JSON array / 500 降级返回空 / HyDE 成功 / HyDE 500 降级 / answer client 正常解析+usage
- query_engine async 5：sync=async parity / 并发 5 请求 wall-clock < 3× single / 无证据路径 parity / 空 query 错误对齐 / rewrite parity
- 路由端到端 2：`ASGITransport` 打通 `/api/chat/ask` / 4 并发请求不串行（wall-clock < 2.5× single）

**验收数据**：
- `pytest tests/rag/test_query_engine_async.py tests/rag/test_rewrite_client_async.py tests/api/test_chat_ask_async.py -q` → 13/13 pass
- `pytest -q --ignore=tests/integration` → 312 pass（零回归，基线 299）
- ruff → 0 violations

## P4.3 验收明细

**交付**：
- `backend/app/main.py` — `_validate_production_security` 新增第 5 组检查：`CELERY_TASK_ALWAYS_EAGER=true` 在 `APP_ENV=production` 下直接 `RuntimeError`
- `backend/app/workers/tasks.py` — `ingest_document_task` 加 `bind=True` + `autoretry_for=(ConnectionError, TimeoutError, OSError, RuntimeError)` + `retry_backoff=2, retry_backoff_max=60, retry_jitter=True, max_retries=3`；按 retry 次数打 info 日志
- `backend/tests/api/test_production_secrets.py` — `_prod_env` baseline 显式设 `CELERY_TASK_ALWAYS_EAGER=false`；新增 `test_production_rejects_celery_eager_mode`
- `backend/tests/workers/test_celery_retry.py` 5 用例

**核心设计**：
- **生产硬拦截**：eager 模式"看起来能跑"是生产最危险的失误 —— 任务内联到 web 进程，所有 ingestion / eval 吞吐瞬间归零；`_validate_production_security` 直接 raise，重启就是配置错误，不会静默生效
- **可重试 vs 程序错误分离**：`autoretry_for=(ConnectionError, TimeoutError, OSError, RuntimeError)` 专攻 infra flakiness；`ValueError` / `TypeError` / `KeyError` 保留给程序 bug，**不自动重试**（重试也不会成功，只烧配额）
- **Backoff 2/4/8s + jitter**：指数退避但 cap 在 60s；jitter 防雷鸣群 reconnect
- **bind=True + 日志**：`self.request.retries` 带出当前尝试次数，运营看日志知道"第 2 次重试"
- **eager 模式仍支持 retry**：Celery 设计允许 eager 里跑 autoretry_for 循环，单测就靠这个验证重试 ladder 不需要真 broker
- **submit_ingestion 返回值契约不变**：eager 分支继续返回 dict，API 调用者 zero break

**测试覆盖**（6 新用例）：
- `test_production_rejects_celery_eager_mode` — 生产 env + eager=true → RuntimeError
- `test_retryable_exception_is_retried_up_to_max_retries` — ConnectionError 4 次（1+3 retries）
- `test_non_retryable_exception_fails_fast` — ValueError 只 1 次
- `test_transient_failure_then_success_retries_until_ok` — 第 2 次成功，共 2 次调用
- `test_task_is_registered_with_retry_config` — retry 配置在 task 对象上正确（防止 decorator 意外丢失）
- `test_submit_ingestion_still_returns_dict_in_eager_mode` — 向后兼容

**验收数据**：
- `pytest tests/workers/test_celery_retry.py tests/api/test_production_secrets.py -q` → 16/16 pass
- `pytest -q --ignore=tests/integration` → 318 pass（零回归，基线 312）
- ruff → 0 violations

## P4.4 验收明细

**交付**：
- `backend/app/db/models/task_run.py` — 新 `TaskRun` 表（id / tenant_id / user_id / task_name / status / idempotency_key(nullable) / input_json / result_json / error_json / retries / trace_id / summary / created_at / updated_at / finished_at）+ 唯一约束 `(tenant_id, task_name, idempotency_key)`
- `backend/alembic/versions/0006_task_run.py` — CREATE TABLE + RLS `tenant_isolation` policy + GRANT
- `backend/app/services/tasks/sink.py` — 纯 SQL helper：`register_task` / `mark_running` / `mark_succeeded` / `mark_failed` / `mark_canceled` / `find_existing`；5 种 status 常量 + `TERMINAL_STATUSES`
- `backend/app/workers/tasks.py` 重写：`submit_ingestion(document_id, *, tenant_id, user_id, trace_id)` + `_ingestion_idempotency_key`；Celery task 内用 `bypass_rls_session` 跑 mark_running / mark_succeeded / mark_failed
- `backend/app/api/routes/knowledge.py` — `submit_ingestion` 调用加上 `tenant_id / user_id / trace_id` 参数
- `backend/app/db/models/__init__.py` + alembic env + session — 注册新 model
- `backend/tests/workers/test_task_sink.py` 10 用例（sink 全接口）
- `backend/tests/workers/test_celery_retry.py` 新增 3 用例（submit_ingestion 向后兼容 + 同 tenant 同 doc 去重 + 跨 tenant 不去重）+ 既有 4 retry 用例全部更新参数
- `backend/tests/workers/conftest.py` — autouse `init_db` 修 worker 单测路径依赖 schema

**核心设计**：
- **NULL idempotency_key = 不去重**：标准 SQL 语义，多个 NULL 行永不冲突；空字符串自动 normalize 成 NULL 防 "每个 opt-out 都撞同一行"
- **dedupe 在 sink 层，不在 Celery**：`register_task` 在 handoff 前就查，重复提交直接返回老 row id，不用让 Celery 跑一遍才发现
- **已成功的 task 立即返回缓存**：`submit_ingestion` 发现 `STATUS_SUCCEEDED` 行直接 `return cached_result`，连 Celery 都不拍了
- **Worker 状态机可观测**：task 从 pending → running → (succeeded|failed|canceled)；retry 次数走 `mark_running(retries=...)` 单调递增
- **RLS 一致**：同 audit_log / agent_event / agent_memory 统一策略，worker 用 `bypass_rls_session`（跨 tenant 合法）
- **task_id = Celery task id**：`apply_async(task_id=pre_allocated)` 让 DB 行和 Celery result backend 共享同一 id，方便 join
- **eager 模式也走 sink**：保持观测口径一致（dev / prod 看到同样形状的 task_run）
- **向后兼容**：`submit_ingestion` 返回 dict 在 eager 成功路径不变；签名新增 kwargs 可选

**测试覆盖**（12 新用例）：
- sink 10：register pending / 同 key dedupe / 空 key 不 dedupe（NULL 语义）/ mark_running 更新 retries / mark_running 在 terminal 后 no-op / mark_succeeded 写 result+finished_at / mark_failed 写 error+retries+finished_at / mark_canceled idempotent / missing row 返回 None / find_existing 按 tenant 隔离
- submit_ingestion 2：同 tenant 同 doc 第二次直接命中缓存（pipeline 只跑 1 次）/ 跨 tenant 同 doc 两次都跑（pipeline 跑 2 次）

**验收数据**：
- `pytest tests/workers -q` → 17/17 pass
- `pytest -q --ignore=tests/integration` → 330 pass（零回归，基线 318）
- ruff → 0 violations

## P4.5 验收明细

**交付**：
- `backend/app/schemas/task_run.py` — 新 `TaskRunPayload` / `TaskRunListResponse` / `TaskCancelRequest` / `TaskCancelResponse`
- `backend/app/api/routes/tasks.py` — 新 `GET /api/tasks` / `GET /api/tasks/{id}` / `POST /api/tasks/{id}/cancel` 三个端点
- `backend/app/main.py` — 挂载 `tasks_router`
- `backend/tests/api/test_tasks_api.py` 12 用例

**核心设计**：
- **list 端点查询支持 status + task_name 过滤 + limit/offset 分页**：dashboard 拉 pending 队列 / 失败列表都走这一接口
- **newest-first 排序**：`ORDER BY created_at DESC` + `total` 字段（前端做"剩余页"展示）
- **tenant 隔离**：list 用 `WHERE tenant_id = context.tenant_id`；detail 额外走 `require_tenant_match` 防 id 猜测
- **cancel 是终态转换不是终态创建**：succeeded / failed 不能取消（409）；已 canceled 幂等返回 `transitioned=false`；其他状态 → revoke + mark_canceled + audit
- **Celery revoke 失败不阻塞 DB 更新**：broker down / eager 模式下 revoke 没意义，只记 warning，DB 照常转 canceled（UI 状态才能前进）
- **角色权限分级**：
  - list / get → `admin / operator / reviewer`（所有人都能看）
  - cancel → `admin / operator`（reviewer 不能取消，因为 ingestion mid-way 取消会留 object storage 垃圾）
- **审计**：`task.cancel` 带 note + 原 status + 新 status

**测试覆盖**（12 用例）：
- list 按 tenant 隔离 / status 过滤 / newest-first + limit 分页 3
- get 单行详情 / 404 unknown 2
- cancel running → canceled + `transitioned=true` 1
- cancel 已 canceled → 幂等 `transitioned=false` + 第一次的 note 保留 1
- cancel succeeded → 409 / cancel failed → 409 / cancel unknown → 404 3
- role guard：reviewer cancel → 403 / reviewer list → 200 2

**验收数据**：
- `pytest tests/api/test_tasks_api.py -q` → 12/12 pass
- `pytest -q --ignore=tests/integration` → 342 pass（零回归，基线 330）
- ruff → 0 violations

## 下一步

P4.6 Phase 4 review：整体验收报告（参照 phase-1 / phase-2 / phase-3 review 的格式），含问题清单 / 遗留事项 / 评分复核。
