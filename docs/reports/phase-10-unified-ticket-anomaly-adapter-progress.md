# Phase 10 进度：ticket / anomaly 统一编排适配层

## 状态
- `2026-04-27`：已完成方案确认，进入测试先行实现。
- `2026-04-27`：已补 API 级红测，确认 ticket/anomaly 缺少 checkpoint 与 interrupt 持久化。
- `2026-04-27`：已完成统一适配层实现，ticket/anomaly 现在会把 checkpoint 与 review interrupt 一并落库。
- `2026-04-27`：已补 checkpoint output 同步修正，route 层追加的 `rule_result` 也会进入 checkpoint 快照。
- `2026-04-27`：已完成定向验证与回归验证。

## 本批任务
1. 新增计划文档
2. 先补 API 级失败测试
3. 实现统一 checkpoint / interrupt 持久化适配层
4. 跑定向验证
5. 回填复盘

## 风险
- `policy_supervisor_agent` 已经自行写 checkpoint，ticket/anomaly 不能重复写入冲突状态。
- 现有 `resume` 语义是 route-level finalization，本批只能保证 review interrupt 状态统一，不能冒进到 graph continuation。

## 已完成改造
- 扩展 `AgentExecutionResult`，统一承载 `interrupt`、`checkpoint_payload`、`checkpoint_type`
- 新增 `app/services/agents/thread_runtime.py`
  - 统一构建 checkpoint state
  - 统一持久化 `AgentThreadCheckpoint`
- `ticket_router_graph` 输出 review interrupt 与 engine adapter checkpoint 快照
- `anomaly_graph` 输出 review interrupt 与 engine adapter checkpoint 快照
- `policy_supervisor` 也显式回传 `interrupt`，保证 route 层 thread 状态更新语义一致
- `/api/agents/runs` 在写入 `AgentRun` 后统一补：
  - `thread.pending_interrupt_json`
  - `thread.memory_summary_json`
  - `AgentThreadCheckpoint`
  - `thread.latest_checkpoint_id`

## 验证结果
- `python -m pytest tests/api/test_agent_thread_phase10.py -q`
  - `2 passed`
- `python -m pytest tests/agents/test_engine_migration.py tests/agents/test_ticket_router.py tests/agents/test_anomaly_real.py -q`
  - `19 passed`
- `python -m pytest tests/api/test_agents_async.py tests/api/test_agent_resume.py tests/api/test_review_queue.py -q`
  - `13 passed`
- `python -m ruff check app/api/routes/agents.py app/services/agents/state.py app/services/agents/thread_runtime.py app/services/agents/ticket_router_graph.py app/services/agents/anomaly_graph.py app/services/agents/policy_supervisor.py tests/api/test_agent_thread_phase10.py`
  - passed
