# Phase 9 Mixed-Domain 可视化与评估外显复盘

> 生成时间：2026-04-27
> 状态：已完成
> 对应计划：`docs/plans/2026-04-27-phase-9-mixed-domain-visibility.md`

## 1. 实际交付
### 代码
1. `frontend/src/api/agents.ts`
2. `frontend/src/api/chat.ts`
3. `frontend/src/api/evals.ts`
4. `frontend/src/components/RetrievalTraceDrawer.tsx`
5. `frontend/src/pages/AgentRunsPage.tsx`
6. `frontend/src/pages/EvalPage.tsx`
7. `frontend/src/styles.css`
8. `backend/app/services/eval/dataset_loader.py`
9. `backend/tests/eval/test_eval_runner.py`

### 测试
1. `frontend/tests/agents/AgentRunsPage.test.tsx`
2. `frontend/tests/eval/EvalPage.test.tsx`

### 文档
1. `docs/plans/2026-04-27-phase-9-mixed-domain-visibility.md`
2. `docs/reports/phase-9-mixed-domain-visibility-progress.md`
3. `docs/reports/phase-9-mixed-domain-visibility-review.md`

## 2. 已实现行为
1. Agent 运行页现在能直接展示：
   - `specialist_plan`
   - `profile_reports`
   - `coverage.per_domain`
   - 聚合后的 `missing_dimensions`
2. Trace 抽屉现在能展示：
   - `planned_domains`
   - `specialist_plan`
   - per-domain coverage
3. Eval 页面现在能展示：
   - `retrieval_mrr`
   - `answer_pass_rate`
   - `quality_gate`
   - `quality_gate_reasons`
4. 后端新增了 `zh-policy-mixed-domain` 内置数据集，可用于 mixed-domain 最小回归。

## 3. 验证结果
### 前端定向测试
- `npm test -- --run tests/agents/AgentRunsPage.test.tsx tests/eval/EvalPage.test.tsx`
- 结果：`2 passed`

### 前端全量测试
- `npm test`
- 结果：`11 files passed / 19 tests passed`

### 前端构建
- `npm run build`
- 结果：通过

### 后端 eval 定向测试
- `python -m pytest backend/tests/eval/test_eval_runner.py -k "mixed_domain_dataset_can_be_created or separates_answer_correctness" -q`
- 结果：`2 passed`

### 后端静态检查
- `python -m ruff check backend/app/services/eval/dataset_loader.py backend/tests/eval/test_eval_runner.py`
- 结果：通过

## 4. 收益
1. mixed-domain 能力不再只停留在后端 JSON，工作台已经能直接看“多域拆分 -> 分域 coverage -> 质量门禁”。
2. 回归页面从“只有基础正确率”升级为“能看检索排序质量和质量门禁”的视角，更接近企业级发布闸门。
3. mixed-domain 最小评测集已经落库，后续可以切默认数据集或扩展样本，而不需要再补基础 plumbing。

## 5. 剩余边界
1. Eval 页面还没有提供数据集切换器，目前仍依赖系统默认评测集。
2. `profile_reports` 已可视化，但还没有 drill-down 到单 domain 子问题 / citations 的专门视图。
3. mixed-domain 内置评测集仍是最小样本集，不能替代更完整的酒店 / 机票 / 报销回归集。
4. 本批只覆盖 policy mixed-domain，可视化层还没有扩展到 ticket / anomaly。

## 6. 下一步建议
1. 进入 Phase 10：把 `ticket / anomaly` 逐步迁到统一的 LangGraph 多 agent 编排。
2. 或在进入 Phase 10 前，再补一批“评测工作台增强”：
   - 数据集切换
   - mixed-domain 失败项 drill-down
   - quality gate 趋势对比
