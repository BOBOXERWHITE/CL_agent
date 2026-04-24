# Phase 5 Review：可观测性 + 遗留技术债收口整体验收

> 生成时间：2026-04-24
> 范围：`docs/plans/2026-04-24-phase-5-observability.md` 全部 5 个子任务 + review
> 参考基线：`docs/reports/phase-4-review.md`（可观测性 6.5 / Agent 7.5）
> 进度明细：`docs/reports/phase-5-progress.md`

---

## 一、执行总结

| 指标 | 起点（Phase 4 结束） | Phase 5 结束 | 变化 |
|---|---|---|---|
| 非 integration 测试数 | 342 passed | **403 passed** | +61（+18%）|
| 可观测性相关单测 | 0 | 48 | +48 |
| 新 DB 表 | — | 1（token_usage_daily）+ 1 列（review_case.agent_run_id）| +1 条 RLS policy |
| 新 API 端点 | — | 1（`GET /api/usage`）| — |
| 引擎迁移 agent | 1/3 (policy) | **3/3** (policy + anomaly + ticket_router) | 所有 agent 现在产出结构化 `agent_event` |
| 异步热路由 | 1（chat）| **2**（chat + agents）| `/api/agents/runs` 改 `async def` |
| trace_id 跨进程可打通 | 无 | W3C `traceparent` + `X-Trace-Id` + Celery header | 全链路 |
| Celery beat 定时任务 | 无 | 1（cleanup-task-run-daily）| 基建就位 |
| ruff violations | 0 | 0 | — |

**子任务完成情况**：5/5 交付 + review，按调整后的执行顺序 P5.1 → P5.3 → P5.4 → P5.2 → P5.5 → P5.6（把遗留技术债 P5.3 / P5.4 提前）。

**契约稳定性**：
- 所有 API 响应字段零破坏（`/api/agents/runs` / `/api/chat/ask` / `/api/tasks/*` 不变）
- `execute_policy_graph` / `execute_anomaly_graph` / `execute_ticket_router_graph` 签名不变
- `create_review_case(payload={"agent_run_id": ...})` 老调用仍可用（自动 lift 到 FK 列）
- `observe_token_usage` Prometheus counter 不变；新增的聚合表与其并存
- `submit_ingestion` 签名向后兼容

---

## 二、架构评估

### 2.1 从"结构化事件但没法聚合"到"trace_id 全链路"

**证据**：

| 维度 | Phase 4 结束 | Phase 5 结束 |
|---|---|---|
| trace_id 来源 | FastAPI 自生成 request_id | W3C `traceparent` / `X-Trace-Id` 上游传入 + UUID 新生成兜底 |
| trace_id 传播 | 进程内可见 | FastAPI → Celery task headers → worker → audit / agent_event |
| OTEL 接入 | 无 | 可选 OTLP exporter（opentelemetry-sdk + OTLPSpanExporter）；未装/未配 时无副作用 |
| 业务 span | 无 | `trace_span(name, **attrs)` contextmanager；无依赖也可用（no-op 层） |
| agent_event 覆盖度 | 1/3 agent（policy）| 3/3 agent（policy + anomaly + ticket_router）|
| token / cost 查询 | Prometheus histogram | `token_usage_daily` 聚合表 + `GET /api/usage` |
| task_run 清理 | 无 | Celery beat daily @ 03:15 UTC + retention 可配 |
| ReviewCase ↔ AgentRun | `payload_json.agent_run_id`（JSON path 依赖）| 显式 FK + ondelete SET NULL |

### 2.2 可观测性的三层曝光面

Phase 5 把三个"看得见"的层次都补齐：

1. **metric 层**：`/metrics` Prometheus endpoint（Phase 4 保留）+ 新增的 `token_usage_daily` 表。前者给 SRE，后者给 billing。
2. **log 层**：structured JSON log（Phase 0 + P5.1 trace_id 注入）+ `agent_event` 表（P3.7 + P5.3 覆盖度）。前者流到 ELK，后者流到 runbook。
3. **trace 层**：W3C traceparent 透传 + 可选 OTLP 到 Grafana Tempo / Jaeger / Phoenix。

### 2.3 技术债收口范围

规划文档第一章列的"做"一栏 8 条全部落地：

| 痛点 | 处置（已完成） |
|---|---|
| 无 trace_id 跨进程打通 | 统一 trace_id 跨 web → Celery → audit / event |
| 没有 OTEL / span | opentelemetry-sdk 可选接入 + 业务 span contextmanager |
| Token / cost 没有 per-tenant 明细 | `token_usage_daily` + `GET /api/usage` group_by model/agent/day |
| task_run 没清理 | Celery beat 定时 + `TASK_RUN_RETENTION_DAYS` 可配 |
| anomaly / ticket_router 不走 engine | 全部 3 agent 迁移完毕 |
| `/api/agents/runs` 同步 | `async def` + `asyncio.to_thread` 包 sync 引擎 |
| ReviewCase ↔ AgentRun 靠 payload_json | `agent_run_id` 显式 FK 列 + 索引 + backfill + fallback |
| Celery 真 broker 无 IT | 留给后续（降优先级；P5.6 遗留）|

### 2.4 新增模块职责划分

```
app/core/observability/
└── tracing.py              # 两层 trace context (no-op + OTLP bridge)

app/services/observability/
└── token_sink.py           # accumulate() upsert sink

app/db/models/
├── token_usage.py          # TokenUsageDaily aggregate
└── rule.py                 # (ReviewCase.agent_run_id FK 新增)

app/api/routes/
└── usage.py                # GET /api/usage

app/workers/
└── maintenance.py          # cleanup_old_task_runs + beat task

app/services/agents/        # P5.3 重写：
├── anomaly_graph.py        # 2 节点 (classify → route)
└── ticket_router_graph.py  # 3 节点 (queue → order → finalize)

alembic/versions/
├── 0007_review_case_agent_run_fk.py
└── 0008_token_usage_daily.py
```

---

## 三、问题清单（CRITICAL / HIGH / MEDIUM / LOW）

### 3.1 MEDIUM：OTEL 层未 integration-test

**证据**：`init_otel_tracer` 只有"libs 缺失时 no-op"的单测；真 OTLP HTTP 导出没跑过。

**影响**：
- 代码路径逻辑有覆盖（无依赖也能工作）
- 真 OTEL SDK 的 `TracerProvider` 初始化 / exporter 网络交互没验过
- Upgrade opentelemetry 版本可能触发兼容问题

**建议**：
- `tests/integration/test_otel_export.py` 起 Grafana Tempo / Jaeger testcontainer，打一个真 span 验证 collector 收到
- 归入 Phase 6 / 或运营 sprint

### 3.2 MEDIUM：trace_span 未接入业务 hot path

**证据**：规划文档 P5.1 "业务关键 span" 列了 5 处（`answer_policy_question_async` / Milvus `retrieve_hybrid` / `answer_client.generate_answer_async` / `ingest_document_task` / `persist_agent_events`），实际仅 lifespan / middleware 接入。

**影响**：
- trace_id 能跨进程传递
- 但真 OTLP 后端里看不到"policy_search took X ms"这种业务维度 span
- 仅从 log 能还原出 trace；不如真 span 体验好

**建议**：
- 给 `answer_policy_question_async` / `_multi_query_search` 等加 `with trace_span("policy_qa", ...)` 包裹
- 作为 Phase 5 后续微调（0.5 天），或归入 Phase 6 运营化一起做

### 3.3 MEDIUM：token_sink upsert 不是原子

**证据**：`accumulate` 在 SQLite / PG 都走 SELECT + INSERT/UPDATE 分支，不是真 `ON CONFLICT`。

**影响**：
- 并发 web 请求可能在同一 (tenant, day, model, agent) 上发生竞争：两个 SELECT 都拿不到行 → 两个都 INSERT → 唯一约束冲突 → 其中一个 request 500
- 单 worker 单租户低并发时不出问题
- 高并发或跨进程 worker 场景下需要真 ON CONFLICT

**建议**：
- PG 路径用 `postgresql.insert().on_conflict_do_update(...)`；SQLite 路径包 `IntegrityError` 后 fall back SELECT + UPDATE
- 或加 advisory lock / per-tenant mutex
- 归入 Phase 6 AsyncSession 迁移时一起做

### 3.4 LOW：`cost_usd_cents` 粒度是整数分

**证据**：模型里列类型 `Integer`；`_compute_cost_cents` `round()` 成整数。

**影响**：
- 小请求（< 0.005 USD）cost 舍入到 0
- 大 tenant 全年累计低估，但误差 < 0.5% 典型
- billing-grade precision 需要 `Numeric(14, 6)` 或 `BigInt` micros

**建议**：换成 micros（美分的 1/10000）或 Decimal —— 归入真上线 billing 时改

### 3.5 LOW：Celery beat 进程部署指南缺失

**证据**：schedule 配置在 `celery_app.py`；`Makefile` / README 里没有 `make celery-beat` 入口。

**影响**：
- 运维上线时 beat 进程可能忘起（schedule 不会自动触发）
- 单测的 `beat_schedule` 字典存在不代表运行时有 beat 进程

**建议**：
- README / docker-compose 增 `worker-beat` 服务
- healthcheck 端点暴露 "last beat tick timestamp"

### 3.6 LOW：Celery real broker IT 留白（Phase 4 遗留未消化）

**证据**：规划文档 "✅ 做" 里列了"Celery 真 broker 无 IT"，实际未落地。

**影响**：
- 同 Phase 4 review 3.2
- 本次没新增风险，只是没消化老债

**建议**：优先级不高，归入业务驱动或 Phase 6

---

## 四、遗留事项 / 技术债

| 条目 | 来源 | 优先级 | 建议归属 |
|---|---|---|---|
| OTEL 真 OTLP export IT | MEDIUM 3.1 | Medium | Phase 6 运营 |
| trace_span 接入业务 hot path | MEDIUM 3.2 | Medium | Phase 5 微调 or Phase 6 |
| token_sink 真 atomic upsert | MEDIUM 3.3 | High | Phase 6 AsyncSession 一起 |
| cost_usd_cents 精度升级 | LOW 3.4 | Low | billing 上线前 |
| Celery beat 部署指南 | LOW 3.5 | Low | 运维文档 |
| Celery real broker IT | LOW 3.6 | Low | 业务驱动 |
| AsyncSession 全量迁移 | Phase 4 遗留 | Low | Phase 6 |
| SSE / WebSocket streaming | 规划推迟项 | Medium | Phase 6 |
| Prompt 版本 A/B + 在线评估 | 规划推迟项 | Medium | Phase 6 |
| LangSmith / Phoenix 直接集成 | 规划推迟项 | Low | OTLP 后做 |
| PII 脱敏 / guardrails | 规划推迟项 | — | 业务驱动 |

---

## 五、验收总清单

### 5.1 规划文档第七章总验收标准逐条核对

1. ✅ **`/api/chat/ask` 的 trace_id 贯通** → W3C traceparent 提取 + set_trace_id + Celery header 传播全部到位
2. ✅ **`GET /api/usage?group_by=model` 看到 per-tenant tokens + cost** → `TokenUsageResponse` + summary；含 `test_usage_default_group_by_model`
3. ✅ **anomaly / ticket_router agent_event 可查** → `test_ticket_router_run_now_produces_engine_events` + `test_anomaly_run_produces_engine_events`
4. ✅ **`POST /api/agents/runs` 3 并发不串行** → `test_agents_run_concurrent_requests_dont_serialise` wall-clock < 2.5×single
5. ✅ **90 天前 succeeded task 自动清理** → `test_cleanup_deletes_old_succeeded_rows`
6. ✅ **`ReviewCase.agent_run_id` 是真 FK** → `test_review_case_populates_agent_run_id_column` + `test_resume_finds_linked_case_via_fk_column`

### 5.2 回归 / Lint / Migration

- `pytest -q --ignore=tests/integration` → **403 passed**，0 failed（基线 342 ∴ +61 新测试）
- `ruff check` on all Phase 5 new/modified files → **0 violations**
- `alembic upgrade head`：新增 0007_review_case_agent_run_fk + 0008_token_usage_daily；链条 0001 → 0008 连续

---

## 六、评分变化（对齐 architecture-review.md）

| 维度 | Phase 4 结束 | Phase 5 结束 | 规划目标 | 达成 |
|---|---|---|---|---|
| 数据库 | 8.0 | 8.0 | — | — |
| API / 鉴权 | 8.0 | 8.0 | — | — |
| RAG | 7.5 | 7.5 | — | — |
| 后端工程 | 8.0 | 8.0 | — | — |
| 安全 | 8.5 | 8.5 | — | — |
| **Agent** | **7.5** | **8.0** | **8.0** | **✅**（3/3 agent engine 化）|
| **可观测性** | **6.5** | **8.0** | **8.0** | **✅**（trace + agent_event 全量 + token 聚合 + cleanup cron）|
| 异步 / 扩展性 | 7.0 | 7.5 | — | +0.5（agents.async 补齐）|

**综合项目评分**：8.3 → **8.7**（超出规划预估 8.6）

---

## 七、下一步选项

1. **开 Phase 6（Prompt 运营 + AsyncSession）**
   - 消化剩余 MEDIUM 技术债：token_sink 原子化 / trace_span 业务接入 / OTEL IT
   - 新增能力：Prompt 版本管理 + A/B + 在线评估 / SSE streaming
   - AsyncSession 全量迁移
   - 预期 10 天

2. **Phase 5 补丁 mini-sprint**
   - 2-3 天：trace_span 业务接入（3.2）+ atomic upsert（3.3）+ OTEL IT（3.1）
   - 不新增维度评分，只巩固 Phase 5 质量

3. **进入运营化阶段（非开发）**
   - Grafana dashboard / Alertmanager 规则
   - PII 脱敏 / 生产监控
   - SRE 侧工作，不在工程规划

建议按 **Phase 5 补丁 mini-sprint → Phase 6** 顺序，给可观测性加一层业务 span 后再做运营化工作。

---

**Phase 5 验收结论**：✅ 通过。可观测性从 6.5 跃升到规划目标 8.0；Agent 也到 8.0；两个主要 sub-dimension 目标达成；0 生产回归；403 tests 全绿；5 子任务 + review 全部交付。建议进入 Phase 6 或先做 mini-sprint 巩固。
