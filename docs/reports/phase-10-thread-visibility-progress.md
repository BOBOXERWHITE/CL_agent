# Phase 10 进度：checkpoint / interrupt 前端外显

## 状态
- `2026-04-27`：已完成切片设计，开始测试先行实现。
- `2026-04-27`：已补后端红测，确认 `/api/agents/runs` 与 `/api/reviews/queue` 还未外显 checkpoint/interrupt 摘要。
- `2026-04-27`：已补前端红测，确认 AgentRunsPage / ReviewQueuePage 尚未展示 checkpoint/interrupt。
- `2026-04-27`：已完成 API 契约扩展与前端展示改造。
- `2026-04-27`：已完成定向验证与前端 build。

## 本批任务
1. 新增计划文档
2. 先补后端与前端失败测试
3. 扩展 Agent / Review 响应契约
4. 更新 AgentRunsPage / ReviewQueuePage
5. 跑验证并回填复盘

## 风险
- `ReviewCase` 不是所有来源都绑定 `thread_id`，需要保留 payload fallback。
- `AgentRun` 列表页不能因为 checkpoint 展示引入明显的 N+1 查询退化。

## 已完成改造
- `AgentRunPayload` 新增：
  - `thread_status`
  - `pending_interrupt`
  - `latest_checkpoint`
- `ReviewCasePayload` 新增：
  - `pending_interrupt`
  - `latest_checkpoint`
- `/api/agents/runs`
  - 预加载 `thread -> checkpoints`
  - 序列化 thread 与 checkpoint 摘要
- `/api/reviews/queue`
  - 批量加载 `AgentThread`
  - 批量加载 `AgentThreadCheckpoint`
  - 统一外显 interrupt 与 checkpoint
- `AgentRunsPage`
  - 增加 checkpoint 卡片
  - 增加 interrupt 摘要显示
- `ReviewQueuePage`
  - 增加 pending interrupt 卡片
  - 增加 checkpoint 卡片

## 验证结果
- `python -m pytest tests/api/test_agent_thread_phase10.py tests/api/test_review_queue.py -q`
  - `4 passed`
- `python -m ruff check app/schemas/agent.py app/schemas/rule.py app/api/routes/agents.py app/api/routes/reviews.py`
  - passed
- `npm test -- --run tests/agents/AgentRunsPage.test.tsx tests/reviews/ReviewQueuePage.test.tsx`
  - `2 passed`
- `npm run build`
  - passed
