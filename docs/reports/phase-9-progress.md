# Phase 9 执行进度

> 对应计划：`docs/plans/2026-04-27-phase-9-policy-specialists.md`

## 进度表
| ID | 任务 | 状态 | 说明 |
|---|---|---|---|
| P9.1 | 文档落盘 | 已完成 | 新建 phase 9 plan / progress / review |
| P9.2 | 抽象 domain profile | 已完成 | hotel 的 facts / dimensions / planner 已从 supervisor 中拆出 |
| P9.3 | 落地 flight specialist | 已完成 | `flight_policy_agent` 已进入 profile-driven workflow |
| P9.4 | 落地 reimbursement specialist | 已完成 | `reimbursement_policy_agent` 已进入 profile-driven workflow |
| P9.5 | targeted tests 与验证 | 已完成 | router / profile / supervisor 相关回归已通过 |

## 本轮实际改造
### 新增模块
- `backend/app/services/agents/policy_profiles.py`

结果：
1. 建立了 `PolicyDomainProfile` 抽象
2. 新增 hotel / flight / reimbursement 三套 profile
3. 每个 profile 都包含：
   - keyword matching
   - facts extraction
   - required dimensions
   - sub-question planning
   - dimension labels
   - completeness interrupt reason

### 路由与 supervisor 重构
- `backend/app/services/agents/policy_domain.py`
- `backend/app/services/agents/policy_supervisor.py`

结果：
1. `choose_policy_specialist()` 现在可直接返回：
   - `hotel_policy_agent`
   - `flight_policy_agent`
   - `reimbursement_policy_agent`
   - `generic_policy_agent`
2. `policy_supervisor` 从 hotel 专用实现升级为 profile-driven workflow
3. 保留了 Phase 8 已有能力：
   - `thread_id`
   - checkpoint
   - guardrail events
   - completeness review interrupt
   - generic fallback

### 新增测试
- `backend/tests/agents/test_policy_specialists_phase9.py`

覆盖：
1. flight specialist 命中
2. reimbursement specialist 命中
3. hotel 与 reimbursement 关键词重叠时 hotel 优先
4. flight / reimbursement 的必答维度规划

## 验证结果
### 后端 pytest
- `python -m pytest tests/agents/test_policy_supervisor_phase8.py tests/agents/test_policy_specialists_phase9.py tests/agents/test_router.py tests/agents/test_router_strategies.py tests/api/test_agent_resume.py tests/api/test_review_queue.py -q`
- 结果：`39 passed`

### ruff
- `python -m ruff check app/services/agents/policy_domain.py app/services/agents/policy_profiles.py app/services/agents/policy_supervisor.py tests/agents/test_policy_specialists_phase9.py`
- 结果：通过

## 当前风险
1. 现在是“单 specialist 命中”，还没有 mixed-domain 聚合
2. `flight` / `reimbursement` 已有专长 workflow，但仍基于通用 `policy_search`，不是结构化规则引擎
3. completeness validator 仍以规则驱动为主，不是可配置策略图

## 下一步
1. 做 mixed-domain supervisor 拆分与聚合
2. 把 profile 继续下沉成更显式的 domain registry / config 结构
3. 视效果决定是否给 flight / reimbursement 增加更强的结构化规则层
