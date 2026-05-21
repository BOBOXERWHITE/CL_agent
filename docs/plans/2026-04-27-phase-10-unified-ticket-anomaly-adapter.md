# Phase 10：ticket / anomaly 统一编排适配层

## 目标
- 不重写 `ticket_router_graph` 和 `anomaly_graph` 的业务判定逻辑。
- 为 `ticket` / `anomaly` 补齐与 `policy_supervisor_agent` 一致的线程持久化外壳：
  - `AgentThreadCheckpoint`
  - `pending_interrupt_json`
  - `latest_checkpoint_id`
  - 统一的 review interrupt 语义
- 保持现有 API 输出、timeline、tool_calls、engine_events 兼容。

## 本批切片
1. 为 `POST /api/agents/runs` 增加统一的 checkpoint 持久化适配层。
2. 让 `ticket_router_agent` 和 `order_anomaly_agent` 都显式产出可持久化的 interrupt / checkpoint 元数据。
3. 让 API 路由在持久化 `AgentRun` 时同步写入 `AgentThreadCheckpoint` 和 `AgentThread.pending_interrupt_json`。
4. 用 API 级测试钉住 ticket/anomaly 的线程状态与 checkpoint 行为。

## 非目标
- 本批不把 ticket / anomaly 的内部 node 迁成 LangGraph。
- 本批不做 graph 级 resume/replay。
- 本批不修改 anomaly 分类规则与 ticket 分流策略。
- 本批不改前端展示。

## 设计
### 统一契约
- 扩展 `AgentExecutionResult`，增加：
  - `interrupt`: 当前 run 的人工审核中断元数据
  - `checkpoint_payload`: 可直接持久化到 `AgentThreadCheckpoint.state_json` 的快照

### interrupt 语义
- ticket:
  - `kind=human_review`
  - `reason=ticket routing requires operator review`
  - `queue_name`
  - `allowed_decisions=["approve", "edit", "reject"]`
- anomaly:
  - `kind=human_review`
  - `reason=anomaly triage requires operator review`
  - `queue_name`
  - `anomaly_code`
  - `allowed_decisions=["approve", "edit", "reject"]`

### checkpoint 持久化
- 新增统一 helper，根据 `AgentExecutionResult` 生成 checkpoint：
  - `checkpoint_type`
    - `langgraph_state`：沿用现有 policy supervisor
    - `engine_adapter_state`：ticket/anomaly 统一适配层
  - `status`
    - 有 interrupt -> `paused`
    - 无 interrupt -> `completed`
- `state_json` 至少包含：
  - `agent_name`
  - `route_name`
  - `timeline`
  - `tool_calls`
  - `output`
  - `confidence`

## 测试
### 先写失败测试
- `ticket` run 会创建 `AgentThreadCheckpoint`
- `anomaly` run 会创建 `AgentThreadCheckpoint`
- `thread.pending_interrupt_json` 会保存 interrupt 信息
- `thread.latest_checkpoint_id` 会指向新 checkpoint
- `agent_run.requires_human_review=true` 时 `thread.status=awaiting_review`

### 回归测试
- 现有 `ticket_router` / `anomaly` timeline、tool_calls、engine_events 测试继续通过
- 现有 `/api/agents/runs`、`/api/agents/runs/{id}/resume` 测试继续通过

## 验证命令
- `python -m pytest backend/tests/api/test_agent_thread_phase10.py -q`
- `python -m pytest backend/tests/agents/test_engine_migration.py backend/tests/agents/test_ticket_router.py backend/tests/agents/test_anomaly_real.py backend/tests/api/test_agents_async.py backend/tests/api/test_agent_resume.py backend/tests/api/test_review_queue.py -q`
- `python -m ruff check backend/app/api/routes/agents.py backend/app/services/agents/graph.py backend/app/services/agents/state.py backend/app/services/agents/ticket_router_graph.py backend/app/services/agents/anomaly_graph.py backend/tests/api/test_agent_thread_phase10.py`
