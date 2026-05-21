# Phase 8 Review：企业级多 Agent 平台底座 + 酒店专长样板

> 生成时间：2026-04-27
> 状态：通过
> 对应计划：`docs/plans/2026-04-26-phase-8-enterprise-multi-agent-foundation.md`

## 1. 本阶段交付了什么
1. `thread_id` 已成为 chat / agent / checkpoint 的统一线程标识
2. 顶层 policy 路由已从 `travel_policy_agent` 切到 `policy_supervisor_agent`
3. hotel / generic 二级路由已落地，hotel 走 LangGraph 受控 workflow
4. Tool Gateway 已具备高风险工具 interrupt 契约
5. reviewer resume 已扩展为 `approve / edit / reject`
6. review queue 已显式暴露 `agent_run_id / thread_id`
7. 管理后台已能直接承接：
   - chat thread 续问
   - agent trace 查看
   - review edit

## 2. 关键实现
### 2.1 后端契约与模型
- `backend/app/schemas/chat.py`
- `backend/app/schemas/agent.py`
- `backend/app/schemas/rule.py`
- `backend/app/db/models/agent.py`
- `backend/alembic/versions/0013_agent_threads_langgraph.py`

结果：
1. chat / agent / review 三条链路的线程标识统一
2. review queue 可以直接反查 agent run 与 thread
3. thread/checkpoint 已具备 durable state 落点

### 2.2 编排与路由
- `backend/app/services/agents/router.py`
- `backend/app/services/agents/graph.py`
- `backend/app/services/agents/policy_domain.py`
- `backend/app/services/agents/policy_supervisor.py`

结果：
1. 一级路由仍保留 `policy / ticket / anomaly`
2. policy 域内新增 `hotel / generic`
3. hotel specialist 已具备：
   - facts extraction
   - required dimension planning
   - guarded multi-query execution
   - completeness validator
   - pause-to-review

### 2.3 Tool Gateway / Guardrail
- `backend/app/services/agents/tool_registry.py`
- `backend/app/services/agents/tools.py`
- `backend/app/services/agents/tool_gateway.py`

结果：
1. 高风险工具可在执行前中断
2. guardrail 事件可以写回 output / trace
3. reviewer 决策与最终状态闭环打通

### 2.4 管理后台收口
- `frontend/src/pages/ChatPage.tsx`
- `frontend/src/pages/AgentRunsPage.tsx`
- `frontend/src/pages/ReviewQueuePage.tsx`
- `frontend/src/components/RetrievalTraceDrawer.tsx`
- `frontend/src/api/{chat,agents,reviews}.ts`

结果：
1. ChatPage 可以持续复用 `thread_id`
2. AgentRunsPage 不再只展示 queue/result，而是能看到 router、specialist、coverage、interrupt、review 关联
3. ReviewQueuePage 可以直接做 `approve / edit / reject`
4. Trace Drawer 兼容旧 retrieval trace 和新的 orchestration trace

## 3. 验证结果
### 后端
- `python -m pytest tests/api/test_review_queue.py tests/api/test_agent_resume.py -q`
- 结果：`11 passed`

### 前端构建
- `npm run build`
- 结果：通过

### 前端测试
- `npm test`
- 结果：`11 files passed / 19 tests passed`

## 4. 这轮实现解决了什么问题
1. 之前 `thread_id` 只在后端契约里存在，前端并没有真正消费，现在已经闭环
2. review `edit` 虽然后端可用，但前端没有入口，现在 reviewer 可以直接在队列里修订答案
3. agent 运行页之前只能看非常粗的结果，现在能直接看到 specialist / coverage / guardrail / review 上下文
4. review queue 之前缺少显式 `agent_run_id` 暴露，不利于前端动作编排，现在已对齐

## 5. 仍然存在的限制
1. checkpoint 仍是业务表自持久化，不是 LangGraph 官方 saver
2. `flight` / `reimbursement` 仍只有域识别与 generic fallback
3. hotel completeness validator 仍是规则驱动，不是抽象化的 domain profile 引擎
4. review queue 仅对已关联 `agent_run_id` 的案例开放直接 resume 处理
5. ticket / anomaly 仍未迁到 LangGraph

## 6. 对 Phase 9 的建议
1. 把 hotel 的 `required_dimensions`、sub-question 模板、validator 规则抽成 domain profile
2. 落 `flight_policy_agent`
3. 落 `reimbursement_policy_agent`
4. 让 supervisor 能拆 mixed-domain 问题并聚合答案
5. 逐步把 review / checkpoint 从“终态写回”升级为真正的 graph-state continuation
