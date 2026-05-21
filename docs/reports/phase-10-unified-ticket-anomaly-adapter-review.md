# Phase 10 复盘：ticket / anomaly 统一编排适配层

## 结果
- 已完成 Phase 10 第一批切片：ticket / anomaly 统一编排适配层。
- 本批没有改 ticket/anomaly 的业务判定逻辑，只补了统一线程持久化外壳。
- ticket/anomaly 运行后现在都会：
  - 创建 `AgentThreadCheckpoint`
  - 写入 `thread.pending_interrupt_json`
  - 更新 `thread.latest_checkpoint_id`
  - 保持既有 timeline / tool_calls / engine_events 契约不变

## 验证
- `python -m pytest tests/api/test_agent_thread_phase10.py -q`
- `python -m pytest tests/agents/test_engine_migration.py tests/agents/test_ticket_router.py tests/agents/test_anomaly_real.py -q`
- `python -m pytest tests/api/test_agents_async.py tests/api/test_agent_resume.py tests/api/test_review_queue.py -q`
- `python -m ruff check app/api/routes/agents.py app/services/agents/state.py app/services/agents/thread_runtime.py app/services/agents/ticket_router_graph.py app/services/agents/anomaly_graph.py app/services/agents/policy_supervisor.py tests/api/test_agent_thread_phase10.py`

## 后续
- 下一步可以把这层 engine adapter 继续往前推两种方向：
  1. 为 ticket/anomaly 增加统一的前端 trace / checkpoint 可视化
  2. 进一步把 ticket/anomaly 的内部执行图迁到 LangGraph，同时保留当前 checkpoint 契约
- 如果继续推进 Phase 10，更合理的下一批是：
  - 抽统一 `supervisor / specialist / engine_adapter` trace schema
  - 让 review queue 能直接看到 checkpoint 中的 interrupt 详情
