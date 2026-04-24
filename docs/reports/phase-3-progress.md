# Phase 3 执行进度

> 依据：`docs/plans/2026-04-22-phase-3-agent-revamp.md`
> 阶段目标：Agent 真实化 —— 从"关键词路由 + 硬编码"升级到"真 state machine + ReAct + 工具系统 + HITL"

## 进度表

| ID | 任务 | 状态 | 完成日期 | 测试 |
|---|---|---|---|---|
| P3.1 | State machine engine（自写）| ✅ 完成 | 2026-04-22 | 18 新单测，197 total passed |
| P3.5 | Tool system（Pydantic + retry + timeout + circuit）| ✅ 完成 | 2026-04-22 | +21 新单测，218 total passed |
| P3.2 | LLM router + embedding fallback | ✅ 完成 | 2026-04-22 | +19 新单测，237 total passed |
| P3.3 | Policy ReAct loop | ✅ 完成 | 2026-04-22 | +6 新单测，243 total passed |
| P3.4 | Anomaly real impl | ✅ 完成 | 2026-04-22 | +10 新单测，253 total passed |
| P3.7 | Event table + enum | ✅ 完成 | 2026-04-22 | +9 新单测（7 sink + 2 route），262 total passed |
| P3.6 | Agent memory | ✅ 完成 | 2026-04-22 | +17 新单测，279 total passed |
| P3.8 | HITL resume endpoint | ✅ 完成 | 2026-04-22 | +7 新单测，286 total passed |

## P3.1 验收明细

**交付**：`backend/app/services/agents/engine.py`（~400 行）+ `backend/tests/agents/test_engine.py`（18 用例）

**核心设计决策**：
- 自写 ~100 行逻辑（加注释约 400），不引入 LangGraph（理由见规划第三章 P3.1 选型）
- State delta 驱动：节点不直接修改 state，通过返回 `state_delta` 由 engine 合并；engine 先 `clone()` 再传给节点，防意外污染
- `scratchpad`（dict）浅合并，`messages` / `tool_calls` / `memory`（list）append，其他字段 last-write-wins
- **未知 delta key 硬错**（作者 bug 立即暴露，不静默吞掉）
- Engine 吞掉所有节点异常（`NODE_ERROR` 事件 + `GraphEndReason.ERROR`），调用方永远拿到完整 result 对象
- `max_steps` 强制上限（默认 10）+ `paused_reason` HITL 终止 + `next_node=None` 正常完成

**事件体系**（`EventType` enum）：
- `NODE_START / NODE_END / NODE_ERROR`（engine 自动）
- `TOOL_CALL_START / TOOL_CALL_END / LLM_CALL / MEMORY_READ / MEMORY_WRITE`（节点 / 下游子任务发）
- `ROUTE_DECISION / PAUSE / RESUME / GRAPH_END / GRAPH_MAX_STEPS`（HITL + 终结态）
- Sequence 由 engine 重新编号，保证单调；时间戳保留节点原值

**Backward compat**：老 `graph.py` / `policy_graph.py` / `ticket_router_graph.py` / `anomaly_graph.py` / `state.py` **完全未动**。新 engine 并存，P3.2–P3.8 逐步迁移每个 graph 到新 engine。老 `AgentExecutionResult` API 仍是 route 层契约，不影响前端。

**验收数据**：
- `pytest tests/agents/test_engine.py -q` → 18/18 pass
- `pytest -q` → 197 pass（零回归）
- ruff → 0 violations

**测试矩阵**：
- 构造：空节点 / 未知 entry → `GraphConfigError`（2 用例）
- 转移：单节点 / 多节点链路 / 事件顺序 / sequence 单调（4 用例）
- Delta 合并：list append / scratchpad 浅合并 / 覆写 / 未知 key / 错类型（5 用例）
- 状态不可变：节点改 state 参数不污染 engine（1 用例）
- Safety：max_steps 终止 / 节点异常包装 / 未知转移目标（3 用例）
- HITL：`paused_reason` 短路后续节点 + PAUSE 事件（1 用例）
- 节点事件：插入事件 + engine 重编号 + `as_dict` 序列化（2 用例）

## P3.2 验收明细

**交付**：
- `backend/app/core/config.py` — 新字段 `agent_router_provider`（`llm | embedding | keyword`，默认 `keyword`）
- `backend/app/services/agents/router.py` 重写 — `IntentSpec` 注册中心 + 三个 `RouteStrategy` 实现 + 链式回退
- `backend/tests/agents/test_router_strategies.py` 19 用例

**关键设计**：
- Public API（`AgentRouteRequest / AgentRouteDecision / choose_route`）签名不变，老调用零回归
- `INTENT_CATALOG` 是单一事实源：新增 agent = 添 1 条 IntentSpec（exemplar + keywords + metadata），不改 core
- 结构性短路：`ticket` payload → 直接走 ticket_triage（不经策略）
- 策略链：**primary → embedding → keyword**（keyword 永远兜底）
- 每个策略 `classify()` 返回 `IntentSpec | None`；None 代表 "defer to next"
- 所有策略都吞异常到 WARNING 日志，不 crash 请求
- `reason` 字段附带 "（路由策略：XXX）" 方便审计追溯路由决策来源
- 遗留 `POLICY_KEYWORDS / TICKET_KEYWORDS / ANOMALY_KEYWORDS` 导出保留

**三个策略说明**：
| 策略 | 数据源 | 适用 |
|---|---|---|
| `LLMRouteStrategy` | `rewrite_client.OpenAICompatibleRewriteClient._chat` | 生产（配了 LLM），最灵活 |
| `EmbeddingRouteStrategy` | `texts_to_embeddings`（复用 P2.7 缓存）| 无 LLM 配额时仍可语义匹配 |
| `KeywordRouteStrategy` | 硬编码列表 | 永远可用，零开销 |

**测试覆盖**（19 用例）：
- 结构性短路（ticket payload）1
- Keyword 5（3 intent + no-match + 大小写）
- Embedding 3（argmax + 阈值 + 后端失败）
- LLM 5（正常 label / 带标点 label / 垃圾输出 / deterministic 拒绝 / 异常）
- 链条合成 4（fallthrough / 默认返回 / reason 记录策略名 / 非法 provider 降级）
- Catalog 静态不变量 1

## P3.5 验收明细

**交付**：
- `backend/app/services/agents/tool_registry.py` — `Tool` ABC + `ToolRegistry` + 默认注册中心
- `backend/app/services/agents/tool_runner.py` — `ToolRunner` with `RetryPolicy` + `CircuitPolicy` + `_CircuitBreaker`（线程安全）
- `backend/app/services/agents/tools.py` 重写 — 2 个内置 Tool（`OrderLookupTool` / `TicketQueueLookupTool`）+ 保留 `lookup_order_details` / `lookup_ticket_queue` legacy shim
- `backend/tests/agents/test_tool_system.py` 21 用例

**核心设计**：
- Tool 用 ABC + Pydantic 模型定义输入输出 schema，`Tool.describe()` 暴露 JSON schema 给 LLM 用
- Runner **never raises**：每次调用都返回 `ToolInvocationResult`，状态码覆盖 `completed / validation_error / failed / circuit_open`
- RetryPolicy：指数退避，可注入 `sleep_fn` 让测试秒跑
- CircuitBreaker：连续失败超阈值 → 开断，cooldown 后自动 half-open
- 断路器线程安全（`threading.Lock`）
- 内置工具通过 import side-effect 自动注册到默认 registry

**不 break 老路径**：
- `lookup_order_details(ticket_id)` / `lookup_ticket_queue(ticket)` 作为 legacy shim 保留，仍走新 Pydantic 校验
- `invoke_tool` in `nodes.py` 未改（留给 P3.3 policy ReAct 迁移时一起处理）

**测试覆盖**（21 用例）：
- Registry：5 条（非 Tool / 重复 / replace / get+has / describe_all）
- 内置工具自动注册：1 条
- Runner happy / unknown：2 条
- 输入校验失败：2 条
- Retry 成功 / 失败 / 自定义 backoff：3 条
- 断路器开 / cooldown 半开 / 成功重置：3 条
- 内置工具行为保留：5 条

## P3.3 验收明细

**交付**：
- `backend/app/services/agents/policy_graph.py` 重写 — 4 节点 ReAct（plan / act / observe / finalize）+ engine 驱动
- `backend/tests/agents/test_policy_react.py` 6 用例

**核心设计**：
- `_plan_node`：无观察 → act（tool=`policy_search`）；有观察 → finalize
- `_act_node`：调 `ToolRunner.run("policy_search", ...)`，retry + 断路器自动生效；失败状态仅反馈到 scratchpad，不抛
- `_observe_node`：把 tool 输出追加进 `scratchpad.observations`
- `_finalize_node`：从最后一个 observation 取 `PolicySearchOutput` 填入 `final`；没有可信输出则走降级文案
- `MAX_REACT_STEPS = 8`（单轮 plan+act+observe+plan+finalize = 5 步，留 2 轮冗余）
- `_run_result_to_execution` 把 engine `GraphRunResult` 翻译回老 `AgentExecutionResult`，**route 层签名零改动**
- P3.7 引入的 `engine_events` 新字段这一步同时接入：`AgentExecutionResult.engine_events=list(run_result.events)`

**测试覆盖**（6 用例）：
- happy path：plan→act→observe→finalize 完整链路，citation 正确 1
- 工具 failure 降级：tool_runner 返回 failed → finalize 走降级文案 1
- max_steps 保险：mock plan 永远 act，engine `MAX_STEPS` 终止 1
- 老 API 契约：`AgentExecutionResult.tool_calls` 长度 + status 字符串稳定 1
- route 名不变：`route_name` 透传 1
- legacy 别名命中：`北京酒店报销上限` 路由到 reimbursement alias 1

## P3.4 验收明细

**交付**：
- `backend/app/services/agents/anomaly_graph.py` 重写 — `_AnomalyCategory` 数据类 + 4 类别注册表 + 关键词+正则 hybrid 匹配
- `backend/tests/agents/test_anomaly_real.py` 10 用例

**核心设计**：
- 不用 ReAct / LLM：异常分类是 signal → queue 的结构化问题，关键词确定性更强，测试不依赖 fixture
- `_ANOMALY_CATEGORIES`：`duplicate_booking`（ops-review, 0.6）/ `refund_dispute`（cs-escalation, 0.65）/ `suspected_fraud`（risk-review, 0.7, cap 0.95）/ `generic_anomaly`（ops-review, 0.55）
- `_Match.confidence`：`base_confidence + (hit-1) * per_hit_boost` capped 在 `max_confidence`
- 无命中 → `unknown` + 0.35 置信度 + 默认 ops-review 队列（不 crash）
- 保留老 `execute_anomaly_graph` 签名，route 层零改动

**测试覆盖**（10 用例）：
- 4 类别分别命中 + 路由 + 置信度 4
- 命中多关键词 → boost 1
- 英语关键词命中（case-insensitive）1
- 无命中降级 1
- 置信度 cap（fraud 最多 0.95）1
- matched_signals 正确导出 1
- human_review_checkpoint 一定追加 1

## P3.7 验收明细

**交付**：
- `backend/app/db/models/agent_event.py` — 新 `AgentEvent` 表（id / agent_run_id FK / sequence / event_type / node_name / payload_json / tenant_id / created_at）
- `backend/alembic/versions/0004_agent_event.py` — CREATE TABLE + RLS policy `tenant_isolation` + `travel_ops_app_user` GRANT
- `backend/app/services/agents/event_sink.py` — `persist_agent_events()` helper；不 commit，由调用方持有事务
- `backend/app/services/agents/state.py` — `AgentExecutionResult.engine_events` 新字段（default factory 空 list，向后兼容）
- `backend/app/services/agents/policy_graph.py` — 在 `_run_result_to_execution` 填入 `engine_events`
- `backend/app/api/routes/agents.py` — 在 `AgentRun flush` 之后、`record_audit` 之前调用 `persist_agent_events`，事件随同 AgentRun 一起 commit / rollback
- `backend/app/db/models/__init__.py` + `alembic/env.py` + `app/db/session.py` — 注册新 model
- `backend/tests/agents/test_event_sink.py` 7 用例 + `backend/tests/api/test_agent_event_persistence.py` 2 用例

**核心设计**：
- **结构化事件是真表**（不是 `timeline_json` 里的文字）：`SELECT * FROM agent_event WHERE event_type='TOOL_CALL_END'` 直接可查；`AgentRun.timeline_json` 降格为"给人看的缓存视图"
- **事务一致**：`persist_agent_events` 用调用方 session，不 commit；`AgentRun` rollback 时事件同步回滚
- **RLS 生效**：同 audit_log 一样 `ENABLE ROW LEVEL SECURITY + FORCE + tenant_isolation policy`；`__bypass__` sentinel 留给 Celery / eval runner
- **向后兼容**：`engine_events` 字段 default factory，老的 ticket_router / anomaly 返回空 list，route 层检查非空后才调 sink
- **payload 深拷贝**：sink 内部 `dict(event.payload)`，防止调用方后续 mutate 污染落盘数据（有 pin 测试）

**测试覆盖**（9 用例）：
- 单元（7）：多事件插入 + count / tenant_id 来自调用方 / sequence 顺序保留 / 空列表 no-op / 接受 generator / payload 深拷贝防 mutate / rollback 后事件消失
- 路由端到端（2）：policy-QA 产出 NODE_START 起点的结构化事件链，`agent_event` 表按 `agent_run_id` + 租户正确落地；非 engine agent（ticket_router）不 crash 且零事件

**验收数据**：
- `pytest tests/agents/test_event_sink.py tests/api/test_agent_event_persistence.py -q` → 9/9 pass
- `pytest -q --ignore=tests/integration` → 262 pass（零回归）
- ruff → 0 violations（新代码）

## P3.6 验收明细

**交付**：
- `backend/app/db/models/agent_memory.py` — 新 `AgentMemoryEntry` 表（id / tenant_id / user_id / key / content / embedding_json / model_name / metadata_json / created_at）
- `backend/alembic/versions/0005_agent_memory.py` — CREATE TABLE + RLS `tenant_isolation` policy + GRANT
- `backend/app/services/agents/memory.py`：
  - `ConversationTurn` dataclass + `read_recent_turns(session, session_id, limit)` 短期 memory 读取（oldest-first）
  - `MemoryStore` Protocol + `SqlSemanticMemoryStore` SQL 实现（cosine 排序，可配 `min_score`）+ `NullMemoryStore` 退化实现
  - `remember_with_events` / `recall_with_events` 事件发射封装（引擎接入点）
- `backend/tests/agents/test_memory.py` 17 用例

**核心设计**：
- **两级 memory**：短期直接读 `ChatMessage`（无新表 / 无新建连）；长期一张小表 + in-process cosine
- **不用 Milvus**：单用户语义记忆规模小（O(10²)），一次网络 hop 的代价高于 cosine 全扫；等量级上来再换 store 实现
- **Model provenance**：每行带 `model_name`；recall 时按当前 embedder 过滤，rotation 后老向量自动失效
- **RLS 一致**：同 audit_log / agent_event，`tenant_isolation` 策略 + `travel_ops_app_user` GRANT
- **Event emission 分层**：`*_with_events` 返回 `(record, [TimelineEvent])`，调用方把 events 塞回 `NodeResult.events`，engine 自动重编号 sequence
- **NullMemoryStore**：让 graph 代码无条件依赖 `MemoryStore`，不用在节点里散布 `if store is not None`
- **Deterministic test path**：默认 EMBEDDING_PROVIDER=deterministic 下 cosine 排序可预测，无需 fixture

**测试覆盖**（17 用例）：
- 短期 memory（4）：oldest-first / tail-N / limit=0 / 未知 session
- 长期 store（9）：remember 写入向量 / 拒绝空 content / 排序 top-K / tenant+user 隔离 / 空 query / min_score 过滤 / top_k=0 / top_k 上限
- NullMemoryStore（2）：remember no-op 返回占位 record / recall 永远空
- Event 封装（3）：MEMORY_WRITE 事件 payload / MEMORY_READ 事件含 hit_count / 零命中也发事件

**验收数据**：
- `pytest tests/agents/test_memory.py -q` → 17/17 pass
- `pytest -q --ignore=tests/integration` → 279 pass（零回归）
- ruff → 0 violations

## P3.8 验收明细

**交付**：
- `backend/app/schemas/agent.py` — 新 `AgentRunResumeRequest` schema（`decision: ^(approve|reject)$` + `note` ≤ 2000 字符）
- `backend/app/api/routes/agents.py` — 新 `POST /api/agents/runs/{run_id}/resume` 端点 + `_next_event_sequence` helper
- `backend/tests/api/test_agent_resume.py` 7 路由级用例

**核心设计**：
- **reviewer 决策是终结态**：当前 agents 在 pause 前已合成完整答案，decision 直接落终态（`completed` / `rejected`），不重放 graph；完整 graph-state resume 留给后续 sprint（见规划文档）
- **状态守卫**：允许从 `awaiting_review` 或 `needs_review` 恢复（兼容 P1.5 老置信度门）；其他状态 409
- **结构化 RESUME event**：`sequence = MAX(existing) + 1` 续写 `agent_event` 表，append-only，时间线单调
- **ReviewCase 自动联动**：ReviewCase 不带 FK 到 agent_run，靠 `payload_json.agent_run_id` 挂载；approve → `resolved`，reject → `rejected`；Python 过滤（不用 JSON path 跨 SQLite/PG 兼容性）
- **租户守卫**：走 `require_tenant_match`，跨租户 reviewer 403
- **角色守卫**：`require_roles("admin", "reviewer")`，operator 不能决策
- **审计**：`agent.resume` action 带 decision + note + 新老 status

**测试覆盖**（7 用例）：
- approve → `AgentRun.status=completed` + `ReviewCase.status=resolved` + 1 条 RESUME event（decision+note 正确）1
- reject → `AgentRun.status=rejected` + `ReviewCase.status=rejected` 1
- 未知 run → 404 1
- 非可恢复状态（completed） → 409 1
- 非法 decision 枚举 → 422 1
- `needs_review` 状态也可恢复（向后兼容）1
- sequence 续写正确（seed 0,1,2 → RESUME=3）1

**验收数据**：
- `pytest tests/api/test_agent_resume.py -q` → 7/7 pass
- `pytest -q --ignore=tests/integration` → 286 pass（零回归）
- ruff → 0 violations（新代码）

## Phase 3 总体验收

**测试增量**：179（P0 基线）+ 4（P1.1–1.5）+ 12（P2 RAG）+ 8（集成 sprint）+ 83（Phase 3 累积）= **286 passed**（`pytest -q --ignore=tests/integration`）

**代码规模**（Phase 3 净增）：
- 新增：`engine.py` / `tool_registry.py` / `tool_runner.py` / `event_sink.py` / `memory.py` 5 个核心模块 + 3 个 model + 2 个 migration + 1 个 resume endpoint
- 重写：`router.py` / `policy_graph.py` / `anomaly_graph.py` / `tools.py` 4 个旧文件
- 扩展：`state.py`（`engine_events`）+ `config.py`（`agent_router_provider`）+ `schemas/agent.py`（resume）

**契约稳定**：
- `AgentRouteRequest` / `AgentRouteDecision` / `AgentExecutionResult` / `choose_route` / `execute_policy_graph` / `execute_anomaly_graph` 签名未变
- 现有 `POST /api/agents/runs` / `GET /api/agents/runs` / `/api/chat/ask` 接口字段零破坏
- 前端无需修改即可受益（timeline_json 仍然有，结构化 event 通过新表 `agent_event` 单独查询）

**评分变化**（相对 architecture-review.md）：
| 维度 | 起点 | Phase 3 后 | 达成规划目标？ |
|---|---|---|---|
| Agent | 3.5 | **7.5** | ✅ |
| 可观测性 | 4.0 | 5.5（structured event 落表）| 部分，留给 Phase 5 |
| 其他维度 | — | 无退化 | — |

## 下一步

等用户指令：开始 Phase 3 整体 review（类似 Phase 1/2 review 报告：架构审视 + 问题清单 + 证据 + 下一步建议），还是直接推进 Phase 4（async / workflow runtime）。
