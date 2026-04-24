# Phase 4 规划：异步化 + 任务真异步 + 背压

> 生成时间：2026-04-23
> 依据：
> - `docs/architecture-review.md` 第七章 P1 "决定能不能扩展" 栏目：async / await 改造、Celery 不要 eager
> - `docs/reports/phase-3-review.md` 第六章：异步/扩展性维度 **3.5**（与 Phase 2 结束持平，Phase 3 未动）
> - `docs/plans/2026-04-07-enterprise-migration-phase-0-2.md` 第 7 章"不做但要记录"项 2：async 改造推迟到 Phase 4
> 范围：`backend/app` 核心 IO 路径 + `backend/app/workers` + 新增 task 观测表
> 工期：8 工作日
> 目标评分跃迁：异步/扩展性 3.5 → 7.0（非 8.0：AsyncSession 全量迁移留给 Phase 6）

---

## 零、为什么 Phase 4 选 Async / Tasks

Phase 3 结束后各维度：

| 维度 | 当前 | 全项目最低？ |
|---|---|---|
| 数据库 | 8.0 | |
| API/鉴权 | 8.0 | |
| RAG | 7.5 | |
| 后端工程 | 7.5 | |
| 安全 | 8.5 | |
| Agent | 7.5 | |
| 可观测性 | 5.5 | |
| **异步/扩展性** | **3.5** | **✅** |

扩展性是唯一没动过的垫底维度。具体痛点：
1. FastAPI 所有路由都是 `def`（同步），RAG / LLM / Milvus / MinIO 调用全部阻塞事件循环 → **单 worker 吞吐等于串行**
2. Celery 默认 `task_always_eager=true`，生产配置漏掉就回退到同步，**没有硬拦截**
3. Celery task 没有 retry / backoff，失败就是终态，**ingestion / eval 一旦挂就要人工重跑**
4. 没有"这批任务跑到哪了"的观测面 —— 前端 upload 后只能轮询 `GET /api/knowledge/documents` 猜状态
5. Ingestion / eval 没有幂等键，重复提交（用户刷新 / 网络重试）会跑两份

---

## 一、范围判断：做什么 / 不做什么

### ✅ 做

| 痛点 | 处置 |
|---|---|
| 路由阻塞事件循环 | **关键热路径**（chat / agents / query）异步化 —— 不做全量迁移 |
| LLM / embedding / rerank 客户端同步 httpx | 增 `AsyncClient` 孪生接口；老 sync 接口保留（Celery worker 还要用）|
| Celery eager 默认 | 生产硬拦截：`_validate_production_security` 里加 eager=true 禁用项 |
| Task 无 retry | `@celery_app.task(bind=True, autoretry_for=..., retry_backoff=True)` |
| Task 无幂等键 | 增 `task_run` 表 + `idempotency_key` 唯一索引 |
| Task 无观测面 | `GET /api/tasks/{id}` + `GET /api/tasks?status=...` + 整合到 `task_run` |
| 长任务无法取消 | 最小可用 `cancel` 接口：`revoke()` + 状态置为 `canceled` |

### ❌ 不做（记录到"下一步"）

| 项 | 推迟到 |
|---|---|
| AsyncSession 全量迁移（SQLAlchemy async）| Phase 6 —— 当前每个路由的 DB 调用都很短，不是瓶颈 |
| 真正的 backpressure（rate limit on Celery queues）| Phase 5 可观测 + 限流后再做 |
| 流式响应（SSE / websocket for long agent runs）| Phase 5 + Phase 3 遗留 HITL-continue 一起 |
| 多 broker / Kafka replace Redis | 业务规模驱动 |
| Task priority queue 分层 | 看到真实瓶颈再分 |

---

## 二、子任务拆解（6 个）

| ID | 任务 | 工期 | 核心改动 |
|---|---|---|---|
| P4.1 | 异步 HTTP 客户端（LLM / embedding / rerank）| 2d | `async_http_client.py` + `AsyncOpenAICompatible*` 孪生类 |
| P4.2 | 热路由异步化（chat / agents / query）| 1.5d | `async def` 路由 + 内部 IO 全部 `await`|
| P4.3 | Celery 生产守卫 + retry / backoff | 0.5d | `_validate_production_security` + `autoretry_for` |
| P4.4 | Task 状态表 + 幂等键 | 1.5d | 新 `task_run` model + migration + sink |
| P4.5 | Task 状态 API（查询 + 取消）| 1d | 新 `/api/tasks` 路由 + Celery revoke |
| P4.6 | Phase 4 review | 0.5d | 报告 + 评分复核 |

**净工期 7 天 + 1 天 buffer = 8 天**，结构和 Phase 3 一致。

---

## 三、详细设计

### P4.1 异步 HTTP 客户端

**现状**：
- `embedding_client.OpenAICompatibleEmbeddingClient` 内部 `httpx.Client`
- `rewrite_client.OpenAICompatibleRewriteClient` 同构
- `rerankers.OpenAICompatibleReranker` 同构
- 每次 RAG 查询依次 sync POST → embeddings / rewrite / rerank，FastAPI worker 线程完全阻塞

**设计**：
- 新 `app/services/rag/async_http_client.py` 提供 `AsyncHttpClient` 封装（连接池 / timeout / retry policy 复用 sync 的配置）
- 每个 provider 类加 `async def embed_texts_async / rewrite_async / rerank_async`（**不重写 sync 方法**，并存）
- 改写重试循环，用 `asyncio.sleep` 指数退避替代 sync 的 busy loop
- 老 sync API 保留（worker 进程里用）

**测试**：
- `pytest-asyncio` 打开
- 每个 async 方法：happy + 4xx retry + 5xx retry + timeout 降级
- 每个 provider 加 deterministic mode 不动 HTTP（现在 sync 已经是这样）

**风险**：
- httpx AsyncClient 的 lifecycle 要挂到 FastAPI lifespan 而不是 per-request（pool 复用）
- 需要在 `app/main.py:lifespan` 创建全局 AsyncClient，shutdown 里 `await aclose()`

### P4.2 热路由异步化

**现状**：`POST /api/chat/ask`、`POST /api/agents/runs`、`POST /api/query` 全是 `def`。

**设计**：
- 只改 3 条热路径，其它 60+ 路由保持同步（改全量一日之功，收益不成比例）
- `chat.py:ask` / `agents.py:create_agent_run` / `query` 改 `async def`
- `query_engine.answer_policy_question` 也拆 `async def answer_policy_question_async`（老 sync 版保留给 Celery / eval runner）
- DB 调用保留 sync `Session`（非瓶颈，Phase 6 再统一）
- 新的内部 IO 调用走 P4.1 的 async 客户端

**测试**：
- 现有 `test_chat_ask.py` / `test_review_queue.py` / `test_knowledge_upload.py` 用 `TestClient`（底层已是 asgi adapter），零改动应该 pass
- 新增并发测试：10 个 concurrent `POST /api/chat/ask`，验证 p95 延迟从 "10 × single" 降到 "≈ single + overhead"

**风险**：
- FastAPI 同步 DB session 在 async 路由里 OK（都是短查询），但不能跨 await 持有
- 测试 fixture 里的 `SessionLocal` 用法需要审视一遍

### P4.3 Celery 生产守卫 + retry

**现状**：
```python
# config.py
celery_task_always_eager: bool = False  # 默认，但 .env 可以设 true
```

生产 .env 漏配 `CELERY_TASK_ALWAYS_EAGER=false` 就走 eager，**没有任何 loud failure**。

**设计**：
- `app/core/config.py:_validate_production_security` 加检查：
  ```python
  if settings.env == "production" and settings.celery_task_always_eager:
      raise ConfigurationError("CELERY_TASK_ALWAYS_EAGER must be false in production")
  ```
- `app/workers/tasks.py`：每个 task 加 `bind=True, autoretry_for=(RuntimeError, ConnectionError), retry_backoff=2, retry_backoff_max=60, max_retries=3`
- 测试：`test_celery_retry.py`，用 `eager + retries` 模式（eager 支持 retries）验证失败 → 重试到上限 → 终态

### P4.4 Task 状态表 + 幂等键

**现状**：Celery 的 `result_backend` 只有成功/失败/结果，没有业务字段（tenant_id, source, idempotency_key）。

**设计**：
- 新 `app/db/models/task_run.py`：
  ```python
  class TaskRun(Base):
      __tablename__ = "task_run"
      id: Mapped[str]                  # celery task id
      tenant_id: Mapped[str]           # RLS
      task_name: Mapped[str]
      status: Mapped[str]              # pending|running|succeeded|failed|canceled
      idempotency_key: Mapped[str]     # unique per (tenant, task_name, key)
      input_json / result_json / error_json / trace_id
      created_at / updated_at / finished_at
  ```
- Alembic 0006 migration + RLS policy + unique constraint `(tenant_id, task_name, idempotency_key)`
- 新 `app/services/tasks/sink.py`：`register_task(...)` / `mark_running` / `mark_succeeded` / `mark_failed` —— 每个 Celery task 调用
- Task 入口默认检查：如果 `(tenant, name, key)` 已有 succeeded 记录 → 直接返回老结果，不重跑
- `submit_ingestion` / `submit_eval` 接入

**测试**：
- 重复 submit 同 idempotency_key → 只跑一次
- 失败 task 记 error_json 含 exception 名
- RLS：tenant A 看不到 tenant B 的 task

### P4.5 Task 状态 API + 取消

**新增**：
- `GET /api/tasks` —— 当前 tenant 的 task 列表（按 created_at desc，带 status/pagination）
- `GET /api/tasks/{id}` —— 单个 task 详情
- `POST /api/tasks/{id}/cancel` —— 发 `celery_app.control.revoke(task_id, terminate=True)` 并置 DB 状态 `canceled`（幂等）

**schema**：`TaskRunPayload` / `TaskRunListResponse` / `TaskCancelResponse`

**授权**：`admin / operator` 可查所有；`reviewer` 只能查自己发起的（或禁止？—— 先统一 admin/operator）

**测试**：
- 查询 / 分页 / 租户隔离 / 404 / 409（cancel 已终态）

### P4.6 Phase 4 review

同 Phase 1 / 2 / 3 review：
- 子任务逐条核对验收标准
- 问题清单（CRITICAL / HIGH / MEDIUM / LOW）
- 遗留事项（AsyncSession、SSE、priority queue 等归档到"下一步"）
- 评分复核
- 下一步建议（Phase 5 可观测 / Phase 6 Prompt 运营）

---

## 四、依赖关系图

```
P4.1 async HTTP (基础)
  ↓
P4.2 异步路由 ←── 依赖 P4.1
  ↓
P4.3 Celery 守卫 + retry (独立)
  ↓
P4.4 task_run 表 + 幂等键 ←── 依赖 P4.3
  ↓
P4.5 task API + cancel ←── 依赖 P4.4
  ↓
P4.6 review
```

**建议执行顺序**：P4.1 → P4.2 → P4.3 → P4.4 → P4.5 → P4.6

---

## 五、与 Phase 0-3 的契约稳定性承诺

| 类别 | 稳定性 |
|---|---|
| `/api/chat/ask` / `/api/agents/runs` / `/api/knowledge/*` 响应 schema | 不变 |
| `Session` 同步用法（route / service / worker 内部）| 不变 |
| `run_agent_workflow` / `execute_policy_graph` 签名 | 不变 |
| `OpenAICompatibleEmbeddingClient.embed_texts(sync)` | 保留，并存 async 版 |
| `submit_ingestion(document_id)` 入口 | 保留；返回值从 dict 变 TaskRun payload（扩展兼容）|
| `celery_task_always_eager=true` 在测试/开发 | 保留 |
| `AgentEvent / AgentMemoryEntry / ReviewCase` 表结构 | 不变 |

---

## 六、不做但要记录（延迟到后续 phase）

| 项 | 推迟到 |
|---|---|
| AsyncSession + asyncpg 全量迁移 | Phase 6 |
| SSE / WebSocket streaming 长回复 | Phase 5 + HITL-continue 一起 |
| Celery task priority queue 分层 | 出现真实拥塞后 |
| Celery beat 定时任务（cleanup / recurring eval）| Phase 5 运营工具链 |
| 取消后的资源清理（partial upload rollback）| 业务驱动 |
| 全链路 trace_id 打通 FastAPI → Celery | Phase 5 可观测（OTEL）|

---

## 七、总验收

完成 Phase 4 后应该能：

1. **10 并发 chat/ask** p95 延迟显著低于 "10 × single"（说明不再是串行阻塞）
2. **生产 .env 配错 `CELERY_TASK_ALWAYS_EAGER=true`** 启动直接失败（_validate_production_security）
3. **上传同一文档两次（同 idempotency_key）** 只跑一次 ingestion；第二次直接返回老 task_run
4. **ingestion 中途挂** 自动重试 3 次，每次 backoff 翻倍，最终 error 记录到 task_run.error_json
5. **前端能查** "当前 tenant 近 50 个 task 的状态 / 失败原因"
6. **可以取消跑飞的 task** —— revoke + DB 状态一致

**评分预期**：
- 异步/扩展性 3.5 → 7.0
- 综合项目评分 7.8 → 8.2

---

## 八、下一步

等用户：
- **「OK，按此顺序执行」** → 开 P4.1（异步 HTTP 客户端）
- **「改一下：XXX」** → 告诉我哪些子任务合并 / 砍掉 / 重排
- **「先做 P4.X 看看效果」** → 改执行顺序，先跑那个子任务
- **「Phase 3 遗留事项 mini-sprint」** → 先补 anomaly/ticket_router 迁移、ReviewCase FK 等

流程同 Phase 1 / 2 / 3：每个子任务完成就回归 + 更新 `docs/reports/phase-4-progress.md`。
