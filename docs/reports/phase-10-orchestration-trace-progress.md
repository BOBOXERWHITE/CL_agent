# Phase 10 进度：统一 orchestration trace schema

## 状态
- `2026-04-27`：本批切片已完成开发、验证和文档回填

## 已完成任务
1. 新增本批计划、进度、复盘文档
2. 后端补齐统一 orchestration trace 组装逻辑
3. `POST /api/agents/runs` 输出 `output.orchestration_trace`
4. 前端 AgentRunsPage 统一读取 orchestration trace / retrieval trace
5. RetrievalTraceDrawer 扩展到支持 execution-oriented trace
6. 补齐 ticket / anomaly 后端断言与 AgentRunsPage 前端用例

## 关键变更
- 后端：
  - `backend/app/services/agents/thread_runtime.py`
  - `backend/app/api/routes/agents.py`
  - `backend/tests/api/test_agent_thread_phase10.py`
- 前端：
  - `frontend/src/api/chat.ts`
  - `frontend/src/api/agents.ts`
  - `frontend/src/components/RetrievalTraceDrawer.tsx`
  - `frontend/src/pages/AgentRunsPage.tsx`
  - `frontend/tests/agents/AgentRunsPage.test.tsx`

## 验证结果
- `python -m pytest tests/api/test_agent_thread_phase10.py -q` -> `2 passed`
- `python -m ruff check app/api/routes/agents.py app/services/agents/thread_runtime.py` -> 通过
- `npm test -- --run tests/agents/AgentRunsPage.test.tsx` -> `2 passed`
- `npm run build` -> 通过

## 说明
- 当前统一 trace 已覆盖 `policy / ticket / anomaly`
- `resume` 后顶层 `thread_status / pending_interrupt / latest_checkpoint` 会覆盖 trace 内旧值，避免前端显示过期状态
