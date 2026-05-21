# Phase 10：统一 orchestration trace schema

## 目标
- 让 `policy / ticket / anomaly` 三类 agent run 都输出统一的 `orchestration_trace`
- 复用现有 Trace Drawer，不再为 ticket / anomaly 单独做一套展示组件
- 保持 `retrieval_trace` 向后兼容，不改 chat 链路接口

## 本批切片
1. 在 `POST /api/agents/runs` 中统一写入 `output.orchestration_trace`
2. policy run 在已有 `retrieval_trace` 的基础上补齐 orchestration 字段
3. ticket / anomaly run 直接从 route、timeline、tool_calls、checkpoint、interrupt 组装 trace
4. AgentRunsPage 优先读取 `orchestration_trace`，缺失时回退 `retrieval_trace`
5. RetrievalTraceDrawer 扩展为同时展示 retrieval 信息和 orchestration 信息

## 统一 trace 最小字段
- `agent_name`
- `route_name`
- `thread_id`
- `thread_status`
- `router`
- `queue_name`
- `pending_interrupt`
- `latest_checkpoint`
- `timeline_nodes`
- `tool_calls`

## 设计约束
- 不新增单独的 trace API
- 不修改 chat API 的 `retrieval_trace` 语义
- 不改 ticket / anomaly 内部既有 graph，只在 route 层做适配
- `resume` 后 thread 顶层状态可能变化，前端展示时优先使用响应顶层字段覆盖 trace 内旧值

## 后端设计
- 在 `thread_runtime` 中新增统一的 trace 组装 helper
- route 层持久化 checkpoint 后，再将 checkpoint / interrupt / timeline / tool_calls 汇总到 `output.orchestration_trace`
- policy run：
  - 先继承已有 `retrieval_trace`
  - 再补 thread、checkpoint、interrupt、timeline、tool_calls 摘要
- ticket / anomaly run：
  - 直接构造 orchestration-only trace

## 前端设计
- `AgentRunOutput` 增加 `orchestration_trace`
- `RetrievalTrace` 类型扩展到同时承载 retrieval 信息和 orchestration 信息
- Trace Drawer 增加以下展示区块：
  - execution summary
  - pending interrupt
  - latest checkpoint
  - timeline nodes
  - tool calls

## 测试
- 后端：
  - ticket run 的 `output.orchestration_trace` 包含 queue、checkpoint、interrupt
  - anomaly run 的 `output.orchestration_trace` 包含 `anomaly_code`
- 前端：
  - AgentRunsPage 能打开 ticket run 的 orchestration trace drawer
  - drawer 内能看到 `route_name / checkpoint_type / queue_name / interrupt / tool_calls`

## 验证命令
- `python -m pytest tests/api/test_agent_thread_phase10.py -q`
- `python -m ruff check app/api/routes/agents.py app/services/agents/thread_runtime.py`
- `npm test -- --run tests/agents/AgentRunsPage.test.tsx`
- `npm run build`
