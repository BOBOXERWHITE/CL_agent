# Phase 9 规划：Policy Specialist 扩展与 Domain Profile 抽象

> 生成时间：2026-04-27
> 范围：`backend/app/services/agents/{policy_domain,policy_supervisor}*.py`、新增 domain profile 模块、相关测试与文档

## 1. 阶段目标
在 Phase 8 的 policy supervisor 基础上，把 hotel 中写死的多跳逻辑抽成可复用的 domain profile，并落地第二批 specialist：

1. 抽象 `domain profile`：
   - facts extraction
   - required dimensions
   - sub-question planning
   - dimension labels
   - completeness review reason
2. 让 policy supervisor 从“hotel 专用实现”升级成“profile 驱动的 specialist workflow”
3. 新增：
   - `flight_policy_agent`
   - `reimbursement_policy_agent`
4. 保持 generic fallback 仍可用
5. 继续沿用 Phase 8 的：
   - `thread_id`
   - checkpoint
   - guardrail / review interrupt
   - trace 输出

## 2. 本轮只做什么
本轮只做 Phase 9 的第一批核心任务，不做 mixed-domain supervisor 聚合。

交付范围：
1. 新增 policy domain profile 注册表
2. refactor `policy_supervisor.py` 为 profile-driven workflow
3. `choose_policy_specialist()` 真正命中 hotel / flight / reimbursement / generic
4. 为 flight / reimbursement 提供受控多跳 workflow，而不是继续直接 generic fallback
5. 补充 targeted tests

## 3. 验收标准
1. hotel 现有行为不回退
2. flight 问题命中 `flight_policy_agent`
3. reimbursement 问题命中 `reimbursement_policy_agent`
4. profile-driven completeness validator 仍能触发 review interrupt
5. targeted pytest 全部通过

## 4. 本轮不做
1. mixed-domain 聚合
2. flight / reimbursement 的结构化规则引擎
3. ticket / anomaly 迁移到 LangGraph
4. graph-state continuation 的深度重构
