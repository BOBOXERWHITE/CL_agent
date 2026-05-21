# Phase 10 复盘：checkpoint / interrupt 前端外显

## 结果
- 已完成 Phase 10 第二批：checkpoint / interrupt 前端外显。
- 现有工作台现在可以直接看到：
  - 线程状态
  - 中断原因
  - 队列名 / anomaly code
  - 最新 checkpoint 类型 / 状态 / 时间
- 本批没有新增独立查询接口，复用了现有 `agents/runs` 与 `reviews/queue`。

## 验证
- `python -m pytest tests/api/test_agent_thread_phase10.py tests/api/test_review_queue.py -q`
- `python -m ruff check app/schemas/agent.py app/schemas/rule.py app/api/routes/agents.py app/api/routes/reviews.py`
- `npm test -- --run tests/agents/AgentRunsPage.test.tsx tests/reviews/ReviewQueuePage.test.tsx`
- `npm run build`

## 后续
- 下一批更合理的是继续做 Phase 10 的 trace 统一：
  1. 抽 `orchestration trace` 统一 schema，让 policy / ticket / anomaly 都能进同一套 trace drawer
  2. 在 review queue 中补 agent run 直链和 checkpoint drill-down
  3. 再往后才是 ticket/anomaly 内部 graph 迁到 LangGraph
