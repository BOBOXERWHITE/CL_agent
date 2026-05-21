# Phase 8 执行进度

> 对应计划：`docs/plans/2026-04-26-phase-8-enterprise-multi-agent-foundation.md`

## 进度表
| ID | 任务 | 状态 | 说明 |
|---|---|---|---|
| P8.1 | 文档落盘 | 已完成 | 新建 plan / progress / review 三份文档 |
| P8.2 | `thread_id` 契约升级 | 已完成 | chat / agent API 均支持 `thread_id` |
| P8.3 | thread / checkpoint 模型 | 已完成 | 新增 `agent_thread`、`agent_thread_checkpoint` 与迁移脚本 |
| P8.4 | 顶层 policy route 切到 supervisor | 已完成 | `POLICY_QA -> policy_supervisor_agent` |
| P8.5 | LangGraph policy supervisor | 已完成 | hotel / generic 二级路由与受控 workflow 已落地 |
| P8.6 | Tool Gateway / Guardrail 骨架 | 已完成 | 新增 risk metadata 与 interrupt-before-execution 契约 |
| P8.7 | Resume 扩展到 `edit` | 已完成 | reviewer 可直接人工修订最终答案 |
| P8.8 | review queue 契约显式化 | 已完成 | `agent_run_id / thread_id` 已对外返回 |
| P8.9 | 前端线程 / trace / review 收口 | 已完成 | chat、agent、review 三个页面均已接上新能力 |
| P8.10 | 回归与验证 | 已完成 | 后端 pytest、前端 build、前端 vitest 全部通过 |

## 本轮新增改造
### 后端
- `backend/app/schemas/rule.py`
- `backend/app/api/routes/reviews.py`
- `backend/tests/api/test_review_queue.py`

结果：
1. `ReviewCasePayload` 新增 `agent_run_id`、`thread_id`
2. review queue 序列化优先读显式 FK，兼容 legacy payload 回退
3. review queue 回归测试补齐 thread/run 关联断言

### 前端 API
- `frontend/src/api/chat.ts`
- `frontend/src/api/agents.ts`
- `frontend/src/api/reviews.ts`

结果：
1. `ChatAnswer` / `AgentRun` / `ReviewCase` 契约升级
2. chat 支持显式传入与复用 `thread_id`
3. 新增 `resumeAgentRun()` 前端调用封装
4. retrieval trace 类型兼容 orchestration 字段

### 前端页面与组件
- `frontend/src/pages/ChatPage.tsx`
- `frontend/src/pages/AgentRunsPage.tsx`
- `frontend/src/pages/ReviewQueuePage.tsx`
- `frontend/src/components/RetrievalTraceDrawer.tsx`
- `frontend/src/styles.css`

结果：
1. ChatPage 展示并复用当前 thread
2. AgentRunsPage 展示：
   - thread
   - specialist
   - coverage
   - guardrail / interrupt
   - review 关联
3. ReviewQueuePage 支持：
   - 审核备注
   - 编辑答案
   - approve / edit / reject
4. RetrievalTraceDrawer 兼容旧 retrieval trace 与新 orchestration trace

### 前端测试更新
- `frontend/tests/chat/ChatPage.test.tsx`
- `frontend/tests/agents/AgentRunsPage.test.tsx`
- `frontend/tests/eval/EvalPage.test.tsx`

结果：
1. 测试 fixture 补齐 `thread_id`
2. 断言更新为适配新的页面结构

## 验证结果
### 后端
- `python -m pytest tests/api/test_review_queue.py tests/api/test_agent_resume.py -q`
- 结果：`11 passed`

### 前端构建
- `npm run build`
- 结果：通过

### 前端测试
- `npm test`
- 结果：`11 passed / 19 passed`

## 当前风险
1. checkpoint 仍是业务表自持久化，不是 LangGraph 官方 saver
2. `flight` / `reimbursement` 仍只有域识别和 generic fallback
3. ReviewQueuePage 当前只对已关联 `agent_run_id` 的案例开放直接处理
4. hotel completeness validator 仍是规则驱动，Phase 9 可继续抽象成 domain profile

## 下一步
1. 进入 Phase 9：抽 domain profile
2. 落 `flight_policy_agent`
3. 落 `reimbursement_policy_agent`
4. 让 mixed-domain supervisor 能真正拆分酒店 / 机票 / 报销混合问题
