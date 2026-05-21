# Phase 10 进度：统一 trace_events 事件流

## 状态
- `2026-04-27`：已完成计划落盘，开始测试先行实现
- `2026-04-27`：后端 `trace_events` 组装、AgentRun / ReviewQueue 接线、前端事件流展示均已完成
- `2026-04-27`：目标验证已跑通，准备进入下一切片

## 本批任务
1. 新增计划、进度、复盘文档
2. 补后端失败测试：agent run / resume / review queue 的 `trace_events`
3. 补前端失败测试：AgentRunsPage / ReviewQueuePage 的事件流展示
4. 实现后端统一 `trace_events` 组装
5. 实现前端展示
6. 跑验证并回填复盘

## 已完成实现
- `thread_runtime` 新增统一 `trace_events` 归一化与合成逻辑，统一输出 `router / tool / interrupt / review / checkpoint` 事件
- `GET /api/agents/runs` 现在会基于当前 thread、checkpoint、interrupt 和 `agent_event` 重新生成 `output.orchestration_trace.trace_events`
- `GET /api/reviews/queue` 现在会把 review case 对应的运行事件、checkpoint 和 interrupt 拼成同一套 `trace_events`
- `RetrievalTraceDrawer` 新增 `Trace Events` 区块
- `ReviewQueuePage` 新增最近 trace 事件展示

## 验证结果
- `python -m pytest tests/api/test_agent_thread_phase10.py tests/api/test_agent_resume.py tests/api/test_review_queue.py -q`
  - `13 passed`
- `npm test -- --run tests/agents/AgentRunsPage.test.tsx tests/reviews/ReviewQueuePage.test.tsx`
  - `2 files passed / 3 tests passed`
- `python -m ruff check app/api/routes/agents.py app/api/routes/reviews.py app/services/agents/thread_runtime.py app/schemas/rule.py tests/api/test_agent_thread_phase10.py tests/api/test_agent_resume.py tests/api/test_review_queue.py`
  - `All checks passed`
- `npm run build`
  - 通过

## 风险
- `agent_event` 目前只对部分 graph 有完整事件，ticket/anomaly 仍需要合成事件兜底
- `resume` 的当前响应依赖重新序列化输出，不能只读旧 `output_json`
