# Phase 9 Review：Policy Specialist 扩展与 Domain Profile 抽象

> 生成时间：2026-04-27
> 状态：通过
> 对应计划：`docs/plans/2026-04-27-phase-9-policy-specialists.md`

## 1. 本轮交付了什么
1. 把 hotel 中写死的 facts / dimensions / sub-question 逻辑抽成了可复用的 `PolicyDomainProfile`
2. policy supervisor 从“hotel 专用工作流”升级成“profile 驱动工作流”
3. `flight_policy_agent` 和 `reimbursement_policy_agent` 已进入 supervisor 正常路由
4. generic fallback 仍保留

## 2. 关键实现
### 2.1 Domain Profile 层
- `backend/app/services/agents/policy_profiles.py`

结果：
1. profile 现在是新增 specialist 的标准扩展点
2. hotel / flight / reimbursement 共用同一套 supervisor 执行框架
3. 新增 specialist 不再需要复制一份 supervisor 逻辑

### 2.2 Router
- `backend/app/services/agents/policy_domain.py`

结果：
1. domain 识别不再依赖散落在 router 里的关键词常量
2. specialist 选择直接由 profile 注册表驱动

### 2.3 Supervisor
- `backend/app/services/agents/policy_supervisor.py`

结果：
1. facts extraction、planner、execute、validate 现在都走 active profile
2. hotel / flight / reimbursement 共用：
   - guarded tool execution
   - coverage calculation
   - completeness review interrupt
   - checkpoint persistence
   - trace 输出

## 3. 验证结果
### pytest
- `python -m pytest tests/agents/test_policy_supervisor_phase8.py tests/agents/test_policy_specialists_phase9.py tests/agents/test_router.py tests/agents/test_router_strategies.py tests/api/test_agent_resume.py tests/api/test_review_queue.py -q`
- 结果：`39 passed`

### ruff
- `python -m ruff check app/services/agents/policy_domain.py app/services/agents/policy_profiles.py app/services/agents/policy_supervisor.py tests/agents/test_policy_specialists_phase9.py`
- 结果：通过

## 4. 这轮解决了什么问题
1. 之前 flight / reimbursement 只会识别后 fallback generic，现在已经有自己的 specialist 路径
2. 之前 hotel 逻辑写死在 supervisor 内，扩域要复制代码；现在已经抽成 profile 扩展点
3. 以后继续加 specialist 时，主要新增的是 profile 和测试，而不是再造一套 supervisor

## 5. 仍然存在的限制
1. supervisor 目前一次只选一个 specialist，不会把 hotel / flight / reimbursement 混合问题拆开聚合
2. flight / reimbursement 仍建立在通用 `policy_search` 上，没有专门的结构化规则判定
3. profile 目前仍以 Python 代码注册，不是外置配置

## 6. 对下一步的建议
1. Phase 9 下一批直接做 mixed-domain supervisor
2. 把 “问题拆分 -> specialist 调度 -> 聚合回答” 做成显式 supervisor 子流程
3. 如果 mixed-domain 效果稳定，再决定是否把 profile 进一步外置成配置文件或 registry
