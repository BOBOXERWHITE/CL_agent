# Phase 5 规划：可观测性 + 遗留技术债收口

> 生成时间：2026-04-24
> 依据：
> - `docs/architecture-review.md` 第七章：OTEL / tracing / token cost / SLO 告警
> - `docs/reports/phase-3-review.md` 第四章遗留事项 3.1（anomaly/ticket_router 迁移到 engine）+ 3.6（ReviewCase agent_run_id FK）
> - `docs/reports/phase-4-review.md` 第四章遗留事项 3.1（`/api/agents/runs` async）+ 3.2（Celery 真 broker IT）+ 3.4（task_run cleanup）
> 范围：`backend/app/core/observability/` + `backend/app/api/routes/agents.py` + `backend/app/services/agents/anomaly_graph.py` + `backend/app/services/agents/ticket_router_graph.py` + cron job 基建
> 工期：8 工作日
> 目标评分跃迁：可观测性 6.5 → 8.0；Agent 7.5 → 8.0（捎带提升）；综合 8.3 → 8.6

---

## 零、为什么 Phase 5 选可观测性

Phase 4 结束后各维度：

| 维度 | 当前 | 备注 |
|---|---|---|
| 数据库 | 8.0 | |
| API/鉴权 | 8.0 | |
| RAG | 7.5 | |
| 后端工程 | 8.0 | |
| 安全 | 8.5 | |
| Agent | 7.5 | anomaly/ticket_router 未迁移到 engine |
| **可观测性** | **6.5** | **单数维度最低** |
| 异步/扩展性 | 7.0 | |

可观测性是**生产运营的最后一块短板**：
1. 332 个结构化 `agent_event` 事件产出但**没有聚合查询 / dashboard / 告警**
2. 没有 trace_id 把 `POST /api/chat/ask → answer_policy_question_async → Milvus → LLM gateway` 串起来
3. Token / cost 统计只有 Prometheus counter，没有按 tenant / model / route 的明细
4. Celery worker 的 task 进度有 DB 行但 web 没地方看"哪条 pipeline 正在第几步"
5. Phase 3 遗留：anomaly / ticket_router 走的是老 timeline，`agent_event` 表在这两条 agent 上是空的（operator 没法对比）
6. Phase 4 遗留：`/api/agents/runs` 是 `def`，并发不解放 event loop

这些问题一起放 Phase 5 做，原因是**它们共享同一套基础设施**：trace_id 传递、结构化事件表、OTEL 导出器、cost 聚合——改完一处受益十处。

---

## 一、范围判断：做什么 / 不做什么

### ✅ 做

| 痛点 | 处置 |
|---|---|
| 无 trace_id 跨进程打通 | 统一 trace_id（request_id → agent run → celery task → audit / event 所有下游）|
| 没有 OTEL / span | 引入 `opentelemetry-sdk` + OTLP exporter；FastAPI / Celery / httpx auto-instrument；业务关键节点手打 span |
| Token / cost 没有 per-tenant 明细 | 新 `token_usage` 聚合表（tenant / model / route / agent / date 维度）|
| task_run 没清理 | Celery beat 定时任务：删 90 天前的 succeeded/canceled |
| anomaly / ticket_router 不走 engine | 迁移到 P3.1 engine；`agent_event` 表覆盖全部 agent run |
| `/api/agents/runs` 同步 | 改 `async def`（复用 P4.1/P4.2 的基建）|
| ReviewCase ↔ AgentRun 靠 payload_json JSON path | 加 `ReviewCase.agent_run_id` 显式 FK + alembic 迁移 |
| Celery 真 broker 无 IT | `tests/integration/test_celery_broker.py` 起 Redis testcontainer |

### ❌ 不做（记录到"下一步"）

| 项 | 推迟到 |
|---|---|
| Prometheus → Grafana dashboard 可视化 | 运营侧工作，不在工程规划；留 `/metrics` 端点即可 |
| Alertmanager 告警规则 | SRE-side，Phase 6 或之后 |
| SLO 定义（latency / error budget）| 业务 / 运营侧 |
| LangSmith / Phoenix 集成 | OTLP 后做 |
| Prompt 版本 A/B | Phase 6 Prompt 运营 |
| PII 脱敏 / guardrails | 业务驱动 |
| SSE streaming 答案 | Phase 6 |

---

## 二、子任务拆解（6 个）

| ID | 任务 | 工期 | 核心改动 |
|---|---|---|---|
| P5.1 | Trace 上下文 + OTEL 接入 | 2d | 新 `app/core/observability/tracing.py` + auto-instrument + 手动 span |
| P5.2 | Token/Cost 聚合表 + `/api/usage` | 1.5d | 新 `token_usage_daily` 表 + sink + 查询端点 |
| P5.3 | anomaly/ticket_router 迁移 engine | 1.5d | 重写两个 graph 到 P3.1 engine，产出 `engine_events` |
| P5.4 | `/api/agents/runs` 异步化 + `agent_run_id` FK | 1d | route → async；ReviewCase 加 FK 列 + 迁移 |
| P5.5 | task_run cleanup cron + Celery beat | 1d | beat 调度 + cleanup task + retention config |
| P5.6 | Phase 5 review | 0.5d | 总报告 + 评分复核 |

**净工期 7.5 天 + 0.5 天 buffer = 8 天**。

---

## 三、详细设计

### P5.1 Trace 上下文 + OTEL

**现状**：
- `RequestContext.request_id` 是 FastAPI 这一进程内的 id，Celery worker 看不到
- `TaskRun.trace_id` 是 P4.4 加的，但没有系统化传播路径
- 没 OTEL span，只有 structured logging

**改造**：
- 新 `app/core/observability/tracing.py`：
  - `init_tracer()` —— lifespan 初始化全局 TracerProvider；默认 no-op exporter，配了 `OTEL_EXPORTER_OTLP_ENDPOINT` 走 OTLP
  - `trace_context()` —— contextmanager 封装 `tracer.start_as_current_span(name)` + 自动挂 trace_id / tenant_id attrs
  - `current_trace_id()` —— 返回当前 span 的 trace_id（16 hex chars），写入 `TaskRun.trace_id` / audit_log / agent_event 时用这个而不是 request_id
- FastAPI 中间件：从 incoming header `traceparent` / `x-trace-id` 恢复 trace；发 response 时回写
- Celery 任务：`before_task_publish` / `task_prerun` signal 把 trace_id 放进 task headers，worker 取出来恢复 span
- 业务关键 span：
  - `answer_policy_question_async`
  - Milvus `retrieve_hybrid`
  - `answer_client.generate_answer_async`
  - `ingest_document_task`
  - `persist_agent_events`
- httpx instrument（`httpx.AsyncClient`）自动发 `traceparent` 到 LLM gateway（方便查第三方 latency）

**测试**：
- `test_tracing.py`：
  - 未配 OTLP 时无 crash（no-op exporter）
  - Trace id 从 FastAPI header 透传到业务 span
  - `TaskRun.trace_id` = HTTP request 的 trace id
  - Celery task 内 span 继承 publish 时的 trace_id

**依赖**：
- `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx`, `opentelemetry-instrumentation-celery`, `opentelemetry-exporter-otlp-proto-http`

### P5.2 Token / Cost 聚合表

**现状**：
- `observe_token_usage` 是 Prometheus histogram；只能看全局；没有 per-tenant
- 每次 `/api/chat/ask` 的 token usage 只落在 `RagRecallLog.token_usage_json`，查询时要 scan

**改造**：
- 新表 `token_usage_daily(tenant_id, day, model_name, agent_name, input_tokens, output_tokens, requests, cost_usd_cents)`
- 唯一约束 `(tenant_id, day, model_name, agent_name)`
- 新 `app/services/observability/token_sink.py`：`accumulate_tokens(tenant, model, agent, usage, cost_cents)` —— upsert 语义（PG ON CONFLICT DO UPDATE；SQLite SELECT-then-INSERT-or-UPDATE）
- 改 `chat.ask` / `agents.create_agent_run` / `policy_graph.finalize` 在 commit 时调 `accumulate_tokens`
- `cost_usd_cents` 按 settings 里的 `COST_RATE_*` 配置计算；缺配置 → 记 tokens 不记 cost（不阻塞写入）
- 新 `GET /api/usage?from=...&to=...&group_by=model|agent|day`：admin-only，聚合查询
- 老 Prometheus counter 保留，不破坏现有 `/metrics`

**测试**：
- `test_token_sink.py`：upsert / 累加 / tenant 隔离 / 缺 cost config 时 cost=None
- `test_usage_api.py`：group_by 聚合 / 时间范围 / role=admin 才行

### P5.3 Anomaly + Ticket Router 迁移 engine

**现状**：
- `anomaly_graph.py`：关键词 hybrid matcher，单个 function 直接返回 `AgentExecutionResult`，`engine_events=[]`
- `ticket_router_graph.py`：同样是单 function
- `POST /api/agents/runs` 对这两条 agent 路径 `agent_event` 表完全是空的

**改造**：
- `anomaly_graph.py`：
  - 拆 3 节点：`_load_node`（收集输入/scratchpad）→ `_classify_node`（关键词 matcher，结果写入 scratchpad）→ `_route_node`（写 queue_name + human_review_checkpoint）
  - `build_anomaly_graph()` 工厂 + `execute_anomaly_graph` 走 engine
  - 旧 API 签名不变
- `ticket_router_graph.py`：同模式
- 关键效果：两种 agent run 也产出 `agent_event` 行，`GET /api/tasks` 风格的"按 event_type 聚合"查询对所有 agent 生效

**测试**：
- 两个 graph 的 node-level 单测（同 policy_graph）
- `/api/agents/runs` 端到端：三种 agent 都有非空 `agent_event`

### P5.4 `/api/agents/runs` async + ReviewCase FK

**改造**：
- `create_agent_run` 改 `async def`；内部 `await run_agent_workflow_async(...)`（后者只包 policy_graph 走 async，anomaly/ticket_router 走 `asyncio.to_thread`）
- `ReviewCase` 新增 `agent_run_id: str | None` 列 + FK（ondelete SET NULL）
- `create_review_case` 接 agent_run_id 参数；老 payload_json 路径保留（向后兼容）
- HITL resume 的 `ReviewCase` 查找改成走新 FK 而不是 Python 过滤 payload_json

**测试**：
- 并发 `/api/agents/runs` 3 请求 wall-clock < 3×single
- ReviewCase.agent_run_id FK ondelete 正确
- 老 payload_json 路径仍能挂载（过渡期）

### P5.5 task_run cleanup + Celery beat

**改造**：
- `app/workers/celery_app.py`：`conf.beat_schedule = {"cleanup-task-run-daily": ...}`
- 新 `app/workers/maintenance.py`：
  - `cleanup_old_task_runs_task` —— `DELETE FROM task_run WHERE created_at < now() - interval + status IN ('succeeded','canceled')`
  - Retention `TASK_RUN_RETENTION_DAYS` 环境变量（默认 90）
- `pyproject.toml` 增 `celery[redis]` extras（如已有就保留）
- 生产守卫加 `CELERY_BEAT_ENABLED` 警示（不强制，避免 dev 被卡）

**测试**：
- `test_cleanup_task.py`：
  - seed 一批 100 天前 succeeded + 30 天前 succeeded + 100 天前 running
  - run cleanup → 仅老的 succeeded 被删；30 天前 succeeded 留；100 天前 running 留（running 不删）

**IT**：
- `tests/integration/test_celery_broker.py`：起 Redis testcontainer + 真 worker；submit 一个 ingest task 看 task_run 状态流转真 broker 下正确

### P5.6 Phase 5 review

同 Phase 1-4 review 格式：
- 子任务逐条验收
- 问题清单（CRITICAL / HIGH / MEDIUM / LOW）
- 遗留事项
- 评分复核
- 下一步（Phase 6 选项）

---

## 四、依赖关系图

```
P5.1 tracing (基础)
  ↓
P5.2 token sink ←── 用 P5.1 trace_id 做 query join key
  ↓
P5.3 anomaly/ticket engine (独立)
  ↓
P5.4 agents.async + ReviewCase FK (独立)
  ↓
P5.5 cleanup cron (独立)
  ↓
P5.6 review
```

**建议执行顺序**：P5.1 → P5.3 → P5.4 → P5.2 → P5.5 → P5.6
（P5.3/P5.4 放前面因为最消化 Phase 3/4 遗留；P5.2 需要 P5.1 的 trace_id；P5.5 可以最后）

---

## 五、契约稳定性承诺

| 类别 | 稳定性 |
|---|---|
| `/api/chat/ask` / `/api/agents/runs` / `/api/tasks/*` 响应 schema | 不变 |
| `AgentExecutionResult` / `execute_policy_graph` / `choose_route` 签名 | 不变 |
| `observe_token_usage` / `observe_agent_run` 现有 Prometheus counters | 保留 |
| `/metrics` 端点 | 不变 |
| `AgentEvent` / `TaskRun` / `AgentMemoryEntry` 表结构 | 不变（ReviewCase 加列，additive）|
| `ReviewCase.payload_json` 老 agent_run_id 字段 | 保留过渡期读 |

---

## 六、不做但要记录

| 项 | 推迟到 |
|---|---|
| 全链路 SSE / WebSocket streaming | Phase 6 |
| AsyncSession 全量迁移 | Phase 6 |
| Prompt 版本 A/B + 在线评估 | Phase 6 运营化 |
| PII 脱敏 / prompt injection 检测 | 业务驱动 |
| Grafana dashboard / Alertmanager 规则 | 运营侧 |
| 真 LangSmith / Phoenix 集成 | OTLP 后做 |
| per-model cost 自动更新（pricing API）| 业务驱动 |

---

## 七、总验收

完成 Phase 5 后应该能：

1. **一条 `/api/chat/ask` 的 trace_id 贯通** web → Milvus → LLM gateway → agent_event → audit_log
2. **`GET /api/usage?group_by=model` 看到** 当前 tenant 每 model 的 tokens + cost 聚合
3. **anomaly / ticket_router 的 run 在 `agent_event` 表可查** 全部结构化事件
4. **`POST /api/agents/runs` 3 并发** wall-clock 明显低于 3×single
5. **90 天前的 succeeded task 自动清理**（cron 可触发 / 可跳过）
6. **`ReviewCase.agent_run_id` 是真 FK**，HITL resume 查找走 SQL JOIN 不是 Python 过滤

**评分预期**：
- 可观测性 6.5 → 8.0
- Agent 7.5 → 8.0
- 综合项目 8.3 → 8.6

---

## 八、下一步

等用户：
- **「OK，按此顺序执行」** → 开 P5.1 trace 上下文
- **「改一下：XXX」** → 告诉我哪些子任务合并 / 砍掉 / 重排
- **「先做 P5.X 看看效果」** → 改执行顺序

流程同 Phase 1-4：每个子任务完成就回归 + 更新 `docs/reports/phase-5-progress.md`。
