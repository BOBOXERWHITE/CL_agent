# Phase 9 Mixed-Domain Review

> 生成时间：2026-04-27
> 状态：已完成
> 对应计划：`docs/plans/2026-04-27-phase-9-mixed-domain-supervisor.md`

## 1. 实际交付
### 代码
1. `backend/app/services/agents/policy_profiles.py`
2. `backend/app/services/agents/policy_domain.py`
3. `backend/app/services/agents/policy_supervisor.py`
4. `backend/tests/agents/test_policy_supervisor_mixed_domain.py`

### 文档
1. `docs/plans/2026-04-27-phase-9-mixed-domain-supervisor.md`
2. `docs/reports/phase-9-mixed-domain-progress.md`
3. `docs/reports/phase-9-mixed-domain-review.md`

## 2. 已实现行为
1. `choose_policy_specialist_plan` 可以返回多个 specialist 命中结果。
2. `policy_supervisor_agent` 对 mixed-domain policy 问题会：
   - 标记 `policy_domain=mixed`
   - 生成 `specialist_plan`
   - 逐域执行 hotel / flight / reimbursement profile
   - 汇总 `profile_reports`
   - 输出 `coverage.per_domain`
   - 聚合 `missing_dimensions`
3. 任一子域 coverage 不完整时，整体结果进入 `completeness_review` interrupt。
4. thread checkpoint 会保留 mixed-domain 关键信息，便于 trace 与 resume。

## 3. 验证结果
### mixed-domain 定向测试
- `python -m pytest backend/tests/agents/test_policy_supervisor_mixed_domain.py -q`
- 结果：`3 passed`

### 相关回归
- `python -m pytest backend/tests/agents/test_policy_supervisor_phase8.py backend/tests/agents/test_policy_specialists_phase9.py backend/tests/agents/test_policy_supervisor_mixed_domain.py backend/tests/agents/test_router.py backend/tests/agents/test_router_strategies.py backend/tests/api/test_agent_resume.py backend/tests/api/test_review_queue.py -q`
- 结果：`42 passed`

### 静态检查
- `python -m ruff check backend/app/services/agents/policy_domain.py backend/app/services/agents/policy_profiles.py backend/app/services/agents/policy_supervisor.py backend/tests/agents/test_policy_supervisor_mixed_domain.py`
- 结果：通过

## 4. 收益
1. Phase 9 从“单 specialist policy supervisor”升级为“可拆 mixed-domain 的 policy supervisor”。
2. 多领域问题不再只命中一个最显眼的 specialist，而是能保留 per-domain 证据与 coverage。
3. review interrupt 从单域 completeness 扩展为 mixed-domain completeness，护栏边界更清晰。

## 5. 剩余边界
1. mixed-domain 仍为顺序执行，尚未并行化。
2. mixed-domain 聚合回答仍是规则式汇总，不是基于独立 aggregation LLM 的总结器。
3. 当前 mixed-domain 只覆盖 policy 域内的 hotel / flight / reimbursement，不支持跨 `policy / ticket / anomaly` 的多域 supervisor。
4. `profile_reports` 已进入 checkpoint，但还没有单独的前端可视化页面消费它。

## 6. 下一步建议
1. 进入 Phase 9 下一批：mixed-domain supervisor 的前端可视化与 eval 指标外显。
2. 或直接推进 Phase 10：把 ticket / anomaly 逐步迁到统一的 LangGraph 多 agent 编排模型。
