# Phase 9 Mixed-Domain 可视化与评估外显进度

> 对应计划：`docs/plans/2026-04-27-phase-9-mixed-domain-visibility.md`

## 进度表
| ID | 任务 | 状态 | 说明 |
|---|---|---|---|
| P9V.1 | 计划与阶段文档落盘 | 已完成 | 新增 plan / progress / review 文档 |
| P9V.2 | mixed-domain 前端类型与展示 | 已完成 | Agent 页面、Trace 抽屉已展示 specialist plan / profile reports / per-domain coverage |
| P9V.3 | eval 指标外显 | 已完成 | Eval 页面已外显 Retrieval MRR、Answer Pass Rate、Quality Gate |
| P9V.4 | mixed-domain 内置评测集 | 已完成 | 后端新增 `zh-policy-mixed-domain` 数据集 |
| P9V.5 | 测试与验证 | 已完成 | 前端 19 个测试通过，新增 backend eval 用例通过，构建通过 |

## 本批实际修改
### 前端
1. `frontend/src/api/agents.ts`
   - 扩展 `specialist_plan`、`profile_reports`、`coverage.per_domain` 类型。
2. `frontend/src/api/chat.ts`
   - 扩展 `router.planned_domains`、`coverage.per_domain`、`specialist_plan` 类型。
3. `frontend/src/api/evals.ts`
   - 扩展 `retrieval_mrr`、`answer_pass_rate`、`quality_gate`、`quality_gate_reasons`。
4. `frontend/src/components/RetrievalTraceDrawer.tsx`
   - 增加 planned domains、specialist plan、per-domain coverage 展示。
5. `frontend/src/pages/AgentRunsPage.tsx`
   - 增加 mixed-domain specialist plan、per-domain coverage、domain reports 主视图。
6. `frontend/src/pages/EvalPage.tsx`
   - 增加 Retrieval MRR、Answer Pass Rate、Quality Gate 卡片与原因展示。
7. `frontend/src/styles.css`
   - 增加 mixed-domain 相关展示样式。

### 测试
1. `frontend/tests/agents/AgentRunsPage.test.tsx`
   - 升级为 mixed-domain specialist plan 与 domain reports 用例。
2. `frontend/tests/eval/EvalPage.test.tsx`
   - 升级为 mixed-domain quality gate 指标展示用例。

### 后端
1. `backend/app/services/eval/dataset_loader.py`
   - 新增 `zh-policy-mixed-domain` 内置数据集。
2. `backend/tests/eval/test_eval_runner.py`
   - 新增 mixed-domain 内置数据集创建测试。

## 验证记录
### 前端定向测试
```bash
npm test -- --run tests/agents/AgentRunsPage.test.tsx tests/eval/EvalPage.test.tsx
```

结果：
- `2 passed`

### 前端全量测试
```bash
npm test
```

结果：
- `11 files passed / 19 tests passed`

### 前端构建
```bash
npm run build
```

结果：
- 通过

### 后端 eval 定向测试
```bash
python -m pytest backend/tests/eval/test_eval_runner.py -k "mixed_domain_dataset_can_be_created or separates_answer_correctness" -q
```

结果：
- `2 passed`

### 后端静态检查
```bash
python -m ruff check backend/app/services/eval/dataset_loader.py backend/tests/eval/test_eval_runner.py
```

结果：
- `All checks passed!`

## 当前结论
本批已经把 mixed-domain 能力从“后端有结构化结果”推进到“工作台可直接观察、回归页可直接看门禁指标”的状态。Agent 页面和 Trace 抽屉能看多域拆分结果，Eval 页面能看质量门禁，后端也有了最小 mixed-domain 内置样本集。
