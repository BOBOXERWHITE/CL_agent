# Phase 5 执行进度

> 依据：`docs/plans/2026-04-24-phase-5-observability.md`
> 阶段目标：可观测性 + 遗留技术债收口 —— 可观测性 6.5 → 8.0；Agent 7.5 → 8.0

## 进度表

| ID | 任务 | 状态 | 完成日期 | 测试 |
|---|---|---|---|---|
| P5.1 | Trace 上下文 + OTEL | ✅ 完成 | 2026-04-24 | +20 新单测，362 total passed |
| P5.3 | anomaly/ticket engine 迁移 | ✅ 完成 | 2026-04-24 | +7 新单测 + 2 路由级校正，370 total passed |
| P5.4 | agents.async + ReviewCase FK | ✅ 完成 | 2026-04-24 | +6 新单测，已回归 |
| P5.2 | Token/Cost 聚合表 + API | ✅ 完成 | 2026-04-24 | +19 新单测（10 sink + 9 API），395 total passed |
| P5.5 | task_run cleanup + Celery beat | ✅ 完成 | 2026-04-24 | +8 新单测 |
| P5.6 | Phase 5 review | ✅ 完成 | 2026-04-24 | 见 `phase-5-review.md`，403 total passed |

## P5.1 验收明细

**交付**：
- `backend/app/core/observability/tracing.py` — 自包含 trace context；两层设计：无依赖的内存上下文（总是可用）+ 可选 OTLP 桥（OTEL_EXPORTER_OTLP_ENDPOINT 触发）
- `backend/app/core/config.py` — 新增 `otel_service_name` / `otel_exporter_otlp_endpoint` / `otel_exporter_otlp_headers` 三个设置
- `backend/app/main.py` — lifespan 调 `init_otel_tracer` / shutdown 调 `shutdown_otel_tracer`；中间件从 `traceparent` / `x-trace-id` header 提取 trace_id 并 `set_trace_id()`
- `backend/tests/core/test_tracing.py` 16 用例 + `backend/tests/api/test_trace_propagation.py` 4 用例

**核心设计**：
- **无硬依赖**：代码可导入可运行即使没装 opentelemetry；真实 OTLP 只在设置了 `OTEL_EXPORTER_OTLP_ENDPOINT` + `.[otel]` extras 都满足时才激活
- **两层契约**：`trace_span` / `current_trace_id` / `celery_task_headers` API 永远可用；OTLP 层只是额外附加真 span 给 exporter
- **deterministic trace_id**：从 `traceparent`（W3C 标准）或 `X-Trace-Id`（legacy）header 恢复；都没有就 UUID 新生成
- **Celery header 传播**：`celery_task_headers(trace_id)` / `restore_trace_from_celery_headers(headers)` 跨进程传 trace 上下文
- **Lifespan flush**：shutdown 时 `shutdown_otel_tracer()` 刷新 batch processor 保证 span 不丢

## P5.3 验收明细

**交付**：
- `backend/app/services/agents/anomaly_graph.py` 重写 — `_classify_node` + `_route_node`；`build_anomaly_graph` 工厂；`engine_events = list(run_result.events)` 填充
- `backend/app/services/agents/ticket_router_graph.py` 重写 — 三节点 `queue_lookup → order_lookup → finalize`；保留 `run_ticket_router` legacy 入口
- `backend/tests/agents/test_engine_migration.py` 7 用例
- `backend/tests/api/test_agent_event_persistence.py` 2 用例校正（ticket_router 现在也产事件 + 新增 anomaly 端到端用例）

**核心设计**：
- **老 API 签名不变**：`execute_anomaly_graph` / `execute_ticket_router_graph` 对外契约零改动
- **两个子图 engine 驱动**：每次 run 都经过 NODE_START / NODE_END → `agent_event` 表对三种 agent 覆盖齐全
- **anomaly 分 2 节点**：classify + route —— reviewer 看 timeline 能直接看到"分类完成"和"路由决定"两步
- **ticket_router 分 3 节点**：工单队列查询 / 订单查询 / 汇总 —— 两个 tool call 分别落在 NODE_START，对应的 `tool_calls` 顺序稳定

## P5.4 验收明细

**交付**：
- `backend/app/db/models/rule.py` — `ReviewCase.agent_run_id` 显式 FK 列（nullable + ondelete=SET NULL）
- `backend/alembic/versions/0007_review_case_agent_run_fk.py` — 加列 + 索引 + PG backfill from `payload_json`
- `backend/app/services/rules/engine.py` — `create_review_case(..., agent_run_id=...)` 参数；老 payload 路径自动 lift
- `backend/app/api/routes/agents.py` — `create_agent_run` 改 `async def`，内部 `await asyncio.to_thread(run_agent_workflow, ...)`；resume 端点先走 FK 查询，fallback 到 payload_json
- `backend/tests/api/test_agents_async.py` 2 用例（并发契约 + round-trip）
- `backend/tests/api/test_review_case_fk.py` 4 用例（FK 填充 + resume via FK + legacy fallback + lift-from-payload）

**核心设计**：
- **async but sync inside**：route `async def` + `asyncio.to_thread` 包裹 sync `run_agent_workflow`；事件循环不阻塞，sync 引擎不变
- **FK + payload_json 双写**：过渡期内两份数据共存，未来彻底迁移后移除 payload_json 字段
- **FK 优先查询**：resume 端点先 `WHERE agent_run_id = ...`，命中则 O(1)；不命中才扫 payload_json 兼容老数据

## P5.2 验收明细

**交付**：
- `backend/app/db/models/token_usage.py` — `TokenUsageDaily` 聚合表，唯一约束 `(tenant, day, model, agent)`
- `backend/alembic/versions/0008_token_usage_daily.py` — CREATE TABLE + RLS policy + GRANT
- `backend/app/services/observability/token_sink.py` — `accumulate(...)` upsert 语义（SELECT + INSERT/UPDATE 分支，PG/SQLite 都支持）；cost 从 `COST_RATE_{MODEL}_{INPUT|OUTPUT}_PER_1K_CENTS` 环境变量读
- `backend/app/schemas/token_usage.py` — `TokenUsageBucket` / `TokenUsageSummary` / `TokenUsageResponse`
- `backend/app/api/routes/usage.py` — `GET /api/usage` 端点，`group_by ∈ {model, agent, day, none}`，`from` / `to` 时间范围
- `backend/app/main.py` — 响应中间件 `_accumulate_token_usage_safe(request)` 自动聚合（失败不 escalate）
- `backend/app/api/routes/chat.py` + `agents.py` — 在路由里设置 `request.state.agent_name`
- `backend/tests/core/test_token_sink.py` 10 用例 + `backend/tests/api/test_usage_api.py` 9 用例

**核心设计**：
- **upsert by tuple**：`(tenant_id, day, model_name, agent_name)` 唯一约束；重复聚合向同一行累加
- **null cost ≠ 0 cost**：没配 `COST_RATE_*` 时 cost=null，summary 全 null 时 total=null（UI 能区分"未配置 cost"和"真 $0"）
- **middleware 兜底**：路由不用手动 call sink；request.state.token_usage 有内容中间件就累加，失败只 log
- **dashboard 友好**：`group_by=day` 直接给时间序列；`summary` 块给 UI 左上角大数字
- **role 分级**：admin / operator 能看；reviewer 403（spend profile 敏感）

## P5.5 验收明细

**交付**：
- `backend/app/core/config.py` — 新增 `task_run_retention_days: int`（默认 90，0 禁用）
- `backend/app/workers/maintenance.py` — `cleanup_old_task_runs(retention_days, statuses, now)` + `cleanup_old_task_runs_task` Celery 入口 + `submit_task_run_cleanup`
- `backend/app/workers/celery_app.py` — `beat_schedule={"cleanup-task-run-daily": {"schedule": crontab(hour=3, minute=15)}}` + `imports` 确保 maintenance 模块加载
- `backend/tests/workers/test_cleanup_task.py` 8 用例

**核心设计**：
- **仅 prune 终态**：succeeded / failed / canceled 走清理；running / pending 永不删（运营要看"卡住"的任务）
- **retention_days=0 no-op**：dev / 测试环境不会意外删数据
- **cron 独立于 celery worker**：`celery beat` 只下发 schedule；normal worker 执行任务
- **可注入 `now`**：测试传 fake `datetime.now(UTC)` 不用 time travel
- **bypass_rls_session**：worker 没有 per-request tenant context，跨 tenant 执行合法
- **dry-run 支持**：传 `retention_days` 参数可以做 what-if；传 `statuses` 参数可以过滤维度

**测试覆盖**（8 用例）：
- 老 succeeded 被删 1
- running / pending 永不删（即使 120 天）1
- failed / canceled 也被删 1
- retention 阈值正确生效 1
- retention=0 no-op 1
- Celery task 正确返回 count 1
- beat_schedule 注册正确 1
- 自定义 status filter 1

## 下一步

P5.6 Phase 5 review 报告：整体验收 + 评分复核 + 遗留事项 + 下一步建议（Phase 6 Prompt 运营 / AsyncSession）。
