# Phase 10：checkpoint / interrupt 前端外显

## 目标
- 将 ticket / anomaly / policy 的线程状态统一外显到现有前端工作台。
- 不新增独立查询接口，优先复用：
  - `GET /api/agents/runs`
  - `GET /api/reviews/queue`
- 让 Agent 运行页和 Review Queue 都能直接看到：
  - `thread_status`
  - `pending_interrupt`
  - `latest_checkpoint`

## 本批切片
1. 扩展 `AgentRunPayload`
   - `thread_status`
   - `pending_interrupt`
   - `latest_checkpoint`
2. 扩展 `ReviewCasePayload`
   - `pending_interrupt`
   - `latest_checkpoint`
3. 更新 AgentRunsPage
   - 展示 checkpoint 类型 / 状态 / 时间
   - 展示 interrupt 的 reason / queue / anomaly_code / allowed_decisions
4. 更新 ReviewQueuePage
   - 展示 interrupt 摘要
   - 展示 checkpoint 摘要

## 非目标
- 本批不新增 replay/resume from checkpoint
- 本批不改 ticket/anomaly 内部 graph
- 本批不引入新的 trace 协议

## 设计
### AgentRunPayload
- 由 `AgentRun.thread` 推导：
  - `thread_status = thread.status`
  - `pending_interrupt = thread.pending_interrupt_json`
  - `latest_checkpoint = { id, checkpoint_type, status, created_at }`

### ReviewCasePayload
- 优先从关联 thread 查询：
  - `thread_id -> AgentThread`
  - `thread.latest_checkpoint_id -> AgentThreadCheckpoint`
- 若无显式 thread，则回退 payload 中已有字段

## 测试
- 后端：
  - `ticket/anomaly` 的 `/api/agents/runs` 响应包含 checkpoint/interrupt 摘要
  - `/api/reviews/queue` 响应包含 checkpoint/interrupt 摘要
- 前端：
  - AgentRunsPage 渲染 checkpoint/interrupt
  - ReviewQueuePage 渲染 checkpoint/interrupt

## 验证命令
- `python -m pytest tests/api/test_agent_thread_phase10.py tests/api/test_review_queue.py -q`
- `npm test -- --run tests/agents/AgentRunsPage.test.tsx tests/reviews/ReviewQueuePage.test.tsx`
- `npm run build`
- `python -m ruff check app/schemas/agent.py app/schemas/rule.py app/api/routes/agents.py app/api/routes/reviews.py`
