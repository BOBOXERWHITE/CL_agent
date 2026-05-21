# Phase 10：统一 trace_events 事件流

## 目标
- 在现有 `orchestration_trace` 之上增加统一的 `trace_events` 事件流
- 让 `policy / ticket / anomaly / review` 都能用同一套事件格式表达执行轨迹
- 让 AgentRunsPage 与 ReviewQueuePage 直接消费同一份事件语义，而不是继续堆散字段

## 本批切片
1. 为 `orchestration_trace` 增加 `trace_events`
2. 事件来源统一收敛为：
   - `agent_event` 持久化事件
   - `pending_interrupt`
   - `latest_checkpoint`
   - review case 当前状态
   - run 的 `resolution`
3. `GET /api/agents/runs` 返回的 `output.orchestration_trace` 要带 `trace_events`
4. `GET /api/reviews/queue` 返回的 review item 要带 `trace_events`
5. Trace Drawer 增加事件流展示
6. ReviewQueuePage 增加最近 trace 事件展示

## 统一事件格式
- `category`: `router | specialist | tool | memory | interrupt | review | checkpoint | engine`
- `name`: 稳定的事件名，如 `route_decision`、`human_review`、`resume`、`checkpoint_state`
- `status`: 如 `completed / paused / open / resolved / rejected / info`
- `detail`: 人类可读摘要
- `timestamp`: ISO 时间
- `metadata`: 事件补充信息，保持为对象

## 设计约束
- 本批不改 chat API 的 `retrieval_trace` 契约
- 本批不把 review queue 直接做成 trace drawer 页面，只做最小事件流外显
- 本批不重写 `ticket / anomaly` 内部 graph
- 本批允许 `trace_events` 由“持久化事件 + 合成事件”混合组成

## 后端设计
- `thread_runtime` 提供统一的 `trace_events` 组装 helper
- `AgentRun` 序列化时，用当前 thread / checkpoint / interrupt / resolution 和 `agent_event` 重新生成 `trace_events`
- `ReviewCase` 序列化时，从关联 run / thread / checkpoint 组装同样格式的 `trace_events`
- 对没有 engine event 的 ticket/anomaly，至少补齐：
  - route / interrupt / checkpoint / review

## 前端设计
- `RetrievalTrace` 增加 `trace_events`
- `ReviewCase` 增加 `trace_events`
- RetrievalTraceDrawer 增加 `Trace Events` 区块
- ReviewQueuePage 增加最近 trace 事件列表，便于复核员快速判断是 route、checkpoint 还是 review 卡住

## 测试
- 后端：
  - agent run 响应包含 `trace_events`
  - resume 后响应里的 `trace_events` 包含 `resume`
  - review queue 响应包含 `trace_events`
- 前端：
  - AgentRunsPage trace drawer 展示 `Trace Events`
  - ReviewQueuePage 展示最近 trace 事件

## 验证命令
- `python -m pytest tests/api/test_agent_thread_phase10.py tests/api/test_agent_resume.py tests/api/test_review_queue.py -q`
- `python -m ruff check app/api/routes/agents.py app/api/routes/reviews.py app/services/agents/thread_runtime.py app/db/models/agent.py`
- `npm test -- --run tests/agents/AgentRunsPage.test.tsx tests/reviews/ReviewQueuePage.test.tsx`
- `npm run build`
