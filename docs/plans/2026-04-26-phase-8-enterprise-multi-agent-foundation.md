# Phase 8 规划：企业级多 Agent 平台底座 + 酒店专长样板

> 生成时间：2026-04-26
> 更新时间：2026-04-27
> 范围：`backend/app/services/agents/*`、`backend/app/api/routes/{agents,chat,reviews}.py`、`backend/app/db/models/*`、`backend/alembic/versions/*`、`frontend/src/{api,pages,components}/*`

## 1. 阶段目标
本阶段只落地企业级多 Agent 平台的第一块可运行切片，不直接实现 Phase 9 / Phase 10 的全部能力。

核心目标：
1. 在不推翻现有 `ticket/anomaly` 旧链路的前提下，引入 LangGraph 作为新的 policy 编排底座。
2. 将 `thread_id` 提升为 chat / agent / checkpoint 的统一线程标识，`session_id` 仅保留兼容语义。
3. 把原有 `POLICY_QA -> travel_policy_agent` 单跳链路升级成：
   - 一级：业务路由 `policy / ticket / anomaly`
   - 二级：policy 域内路由 `hotel / generic`
4. 实现 `hotel_policy_agent` 的受控多跳 workflow：
   - 题干事实抽取
   - 必答维度规划
   - 定向检索
   - completeness validator
   - 缺维度时转人工复核
5. 建立 Tool Gateway 与高风险 interrupt 契约。
6. 补齐管理后台最小可用闭环：
   - chat 页可持续复用 `thread_id`
   - agent 运行页可展示 router / specialist / coverage / guardrail / review 结果
   - review 队列可直接 `approve / edit / reject`

## 2. 设计取舍
### 2.1 为什么采用 LangGraph + 双栈迁移
1. 当前 `ticket` / `anomaly` / 旧 policy 路径仍在工作，不能一次性整体替换。
2. Phase 8 先只把 policy 主链路切到 LangGraph，降低迁移风险。
3. 旧 `travel_policy_agent` 保留为 fallback，确保回滚面清晰。

### 2.2 为什么先做 hotel / generic
1. 当前最明显的质量问题集中在酒店政策多跳问答。
2. hotel 适合作为第一套 domain profile，验证 facts extraction、coverage 校验和人工复核中断。
3. `flight` / `reimbursement` 先只做识别和 generic fallback，把 specialist 落到 Phase 9。

### 2.3 为什么 checkpoint 先用业务表自持久化
1. 项目已经稳定使用 Postgres / SQLAlchemy。
2. 先把 thread / checkpoint 做成业务可见对象，后续切 LangGraph 官方 saver 也不会改业务契约。
3. Phase 8 目标是“可恢复、可追踪”，不是“一步到位接入最重的工作流底座”。

## 3. 交付范围
### 3.1 后端契约与模型
1. `POST /api/chat/ask` 支持 `thread_id`，并继续兼容 `session_id`
2. `POST /api/agents/runs` 支持 `thread_id`
3. `POST /api/agents/runs/{id}/resume` 支持 `approve / edit / reject`
4. `GET /api/reviews/queue` 明确返回 `agent_run_id / thread_id`
5. 新增：
   - `agent_thread`
   - `agent_thread_checkpoint`
   - `agent_run.thread_id`

### 3.2 编排与路由
1. 顶层 router 把 `POLICY_QA` 交给 `policy_supervisor_agent`
2. `policy_supervisor_agent` 内部做 hotel / generic 二级路由
3. `hotel_policy_agent` 采用 LangGraph 受控 workflow
4. `generic_policy_agent` 继续复用现有 policy search

### 3.3 Tool Gateway 与 Guardrail
1. 工具元数据支持：
   - `risk_level`
   - `requires_approval`
   - `idempotency_scope`
2. 高风险工具执行前可被 interrupt
3. 复核动作统一进入 `resume` 契约

### 3.4 Trace / Eval / 审计
1. trace 至少覆盖：
   - router decision
   - specialist decision
   - tool call
   - guardrail decision
   - interrupt / resume
   - final response
2. 保留 OTel 主链路
3. 为 Phase 8 增加 router / supervisor / resume / review queue 相关测试

### 3.5 管理后台收口
1. ChatPage 复用 `thread_id`
2. AgentRunsPage 展示：
   - `thread_id`
   - specialist / fallback reason
   - coverage / missing dimensions
   - interrupt / guardrail events
   - review resolution
3. ReviewQueuePage 支持：
   - 审核备注
   - 人工编辑答案
   - 直接调用 resume API 完成 `approve / edit / reject`
4. Trace Drawer 兼容旧 retrieval trace 和新 orchestration trace

## 4. 验收标准
### 4.1 功能
1. hotel 问题能够进入 `hotel_policy_agent`
2. generic policy 问题仍可正常回退
3. `thread_id` 能贯穿 chat / agent run / review case / checkpoint
4. completeness validator 能把不完整 hotel 结果送入 review
5. reviewer 可以在前端直接完成 `approve / edit / reject`

### 4.2 可观测性
1. 运行结果中能看到 router / specialist / coverage / interrupt 信息
2. review case 能直接关联到 `agent_run_id / thread_id`
3. 管理后台可以从结果页进入 trace 级别的排查

### 4.3 回归
1. `ticket` / `anomaly` 旧路径不被破坏
2. 不传 `thread_id` 的旧客户端仍可工作
3. 前端 build 和 vitest 必须通过
4. 后端 targeted pytest 必须通过

## 5. 执行顺序
1. 文档落盘：plan / progress / review
2. schema / model / migration
3. 顶层 router 切到 `policy_supervisor_agent`
4. LangGraph hotel/generic policy supervisor
5. Tool Gateway / review interrupt
6. 前端收口：thread / review edit / trace 展示
7. targeted verification

## 6. 本阶段不做
1. `flight_policy_agent`
2. `reimbursement_policy_agent`
3. `ticket` / `anomaly` 全量迁到 LangGraph
4. GraphRAG / Knowledge Graph
5. 外部 SaaS tracing 作为强依赖
6. 独立 ADR 体系
