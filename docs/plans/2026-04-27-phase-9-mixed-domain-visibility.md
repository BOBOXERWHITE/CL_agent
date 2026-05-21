# Phase 9 规划：Mixed-Domain 可视化与评估外显

> 生成时间：2026-04-27
> 范围：`frontend/src/{api,pages,components}`, `frontend/tests/*`, `backend/app/services/eval/dataset_loader.py` 及对应阶段文档

## 1. 背景
Phase 9 已经完成 mixed-domain policy supervisor 的后端能力，但当前后台工作台还停留在单 specialist 视角：
1. Agent 运行页只能看到单个 specialist、总 coverage 和 guardrail 概览。
2. Trace 抽屉没有展示 `specialist_plan`、`planned_domains`、`coverage.per_domain`。
3. Eval 页面只展示基础指标，没有把 `retrieval_mrr`、`answer_pass_rate`、`quality_gate` 这类回归门禁指标显式展示出来。
4. 内置评测集仍以 smoke 数据为主，缺少最小 mixed-domain 回归样本。

## 2. 本批目标
1. 在 Agent 运行页展示 mixed-domain 关键信息：
   - `specialist_plan`
   - `profile_reports`
   - `coverage.per_domain`
   - 聚合后的 `missing_dimensions`
2. 在 Trace 抽屉展示 mixed-domain router 与 per-domain coverage 细节。
3. 在 Eval 页面外显：
   - `retrieval_mrr`
   - `answer_pass_rate`
   - `quality_gate`
   - `quality_gate_reasons`
4. 补充一个最小 mixed-domain 内置评测集，便于后续切换默认回归集或手动触发对比。

## 3. 设计边界
1. 本批不改动 Agent 后端执行逻辑，只消费和外显既有 mixed-domain 结果。
2. Eval 页面先做指标外显，不新增完整的多数据集管理台。
3. mixed-domain 内置评测集只做最小样本集，不在本批引入新的离线评分器。

## 4. 实施步骤
1. 扩展前端类型定义，接住 mixed-domain 输出与新增 eval metrics。
2. 先补前端定向测试：
   - AgentRunsPage mixed-domain 展示
   - EvalPage 新指标展示
3. 实现 Agent 运行页与 Trace 抽屉的 mixed-domain 可视化。
4. 实现 Eval 页面新增指标与质量门禁展示。
5. 在后端补最小 mixed-domain 内置评测集。
6. 运行前端与相关后端验证，并回填文档。

## 5. 验收标准
1. Agent 运行页能明确显示 mixed-domain 的 specialist plan、per-domain coverage 和 profile 摘要。
2. Trace 抽屉能显示 planned domains、specialist plan 和 per-domain coverage。
3. Eval 页面能展示 `retrieval_mrr`、`answer_pass_rate`、`quality_gate` 与失败原因。
4. mixed-domain 内置评测集可被创建和运行。
5. 定向前端测试、相关回归测试与静态检查通过。
