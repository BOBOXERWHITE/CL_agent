# Phase 9 规划：Mixed-Domain Policy Supervisor

> 生成时间：2026-04-27
> 范围：`backend/app/services/agents/{policy_domain,policy_profiles,policy_supervisor}.py`、`backend/tests/agents/test_policy_supervisor_mixed_domain.py`、对应阶段文档

## 1. 背景
Phase 9 第一批已经完成 `hotel / flight / reimbursement` 三个 specialist，但当前 supervisor 仍是“单题只命中一个 specialist”的模式。对于“酒店 + 机票 + 报销”混合政策问题，系统还不能显式拆分领域、逐域取证并聚合输出。

## 2. 本批目标
1. 支持 policy 域内多 specialist plan 检测，而不是只返回一个命中结果。
2. 让 `policy_supervisor_agent` 能对 mixed-domain 问题按领域顺序执行多个 profile。
3. 输出统一的 mixed-domain 聚合结果，包含：
   - `specialist_plan`
   - `profile_reports`
   - `coverage.per_domain`
   - 聚合后的 `missing_dimensions`
4. 只要任一子域 coverage 不完整，就整体进入 review interrupt，而不是只返回局部结论。

## 3. 设计边界
1. 本批只做同一问题内的多 specialist 顺序执行，不做并行执行。
2. mixed-domain 聚合回答先采用规则化汇总，不引入新的自由式 LLM 聚合器。
3. 只处理 policy 域内的混合问题，不扩展到 ticket / anomaly 跨域 supervisor。

## 4. 实施步骤
1. 扩展 policy routing，新增多 specialist plan 输出能力。
2. 在 `policy_supervisor` 中新增 mixed-domain 执行节点，复用既有 profile 契约逐域运行。
3. 新增 mixed-aware finalizer，汇总多域结论、coverage、guardrail 和 interrupt。
4. 扩展 checkpoint / trace / timeline，使 mixed-domain 运行可恢复、可追踪。
5. 新增 mixed-domain 定向测试，覆盖：
   - 多域识别
   - 聚合成功
   - 任一子域证据不足时整体 review

## 5. 验收标准
1. mixed-domain 问题能识别出多个 specialist。
2. supervisor 能顺序执行多个 profile，并保留 per-domain 结果。
3. 最终输出包含：
   - `specialist_plan`
   - `profile_reports`
   - `coverage.per_domain`
   - `missing_dimensions`
4. 任一子域缺失关键维度时：
   - `requires_human_review=True`
   - `interrupt.kind=completeness_review`
5. 定向 pytest 与相关回归测试通过，`ruff check` 通过。
