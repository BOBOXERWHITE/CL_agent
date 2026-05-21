# Phase 9 Mixed-Domain 执行进度

> 对应计划：`docs/plans/2026-04-27-phase-9-mixed-domain-supervisor.md`

## 进度表
| ID | 任务 | 状态 | 说明 |
|---|---|---|---|
| P9M.1 | mixed-domain 规划落盘 | 已完成 | 新增计划、进度、复盘文档 |
| P9M.2 | 多 specialist plan 检测 | 已完成 | `choose_policy_specialist_plan` 支持输出多域命中结果 |
| P9M.3 | mixed-domain supervisor 聚合 | 已完成 | `policy_supervisor` 新增 mixed 执行与 finalizer |
| P9M.4 | checkpoint / trace 扩展 | 已完成 | 持久化 `specialist_plan`、`profile_reports`，timeline 展示 mixed 计划 |
| P9M.5 | 定向测试与回归验证 | 已完成 | mixed-domain 新增 3 个测试，相关回归共 42 个测试通过 |

## 本批实际修改
1. `backend/app/services/agents/policy_profiles.py`
   - 新增 `match_policy_profiles(question)`，支持多 profile 命中。
2. `backend/app/services/agents/policy_domain.py`
   - 新增 `choose_policy_specialist_plan(question)`。
   - 保留单 specialist 路由接口，兼容旧调用方。
3. `backend/app/services/agents/policy_supervisor.py`
   - route 阶段支持 mixed-domain 识别。
   - 新增 `_mixed_execute_node`，逐域执行 profile。
   - 新增 mixed-aware finalizer，输出聚合答案和 per-domain coverage。
   - 持久化 checkpoint 时记录 `specialist_plan`、`profile_reports`。
4. `backend/tests/agents/test_policy_supervisor_mixed_domain.py`
   - 新增多域计划、聚合成功、整体 review 三个定向测试。

## 验证记录
### 定向 mixed-domain 测试
```bash
python -m pytest backend/tests/agents/test_policy_supervisor_mixed_domain.py -q
```

结果：
- `3 passed`

### Phase 8 / Phase 9 相关回归
```bash
python -m pytest \
  backend/tests/agents/test_policy_supervisor_phase8.py \
  backend/tests/agents/test_policy_specialists_phase9.py \
  backend/tests/agents/test_policy_supervisor_mixed_domain.py \
  backend/tests/agents/test_router.py \
  backend/tests/agents/test_router_strategies.py \
  backend/tests/api/test_agent_resume.py \
  backend/tests/api/test_review_queue.py -q
```

结果：
- `42 passed`

### 静态检查
```bash
python -m ruff check \
  backend/app/services/agents/policy_domain.py \
  backend/app/services/agents/policy_profiles.py \
  backend/app/services/agents/policy_supervisor.py \
  backend/tests/agents/test_policy_supervisor_mixed_domain.py
```

结果：
- `All checks passed!`

## 当前结论
本批 mixed-domain 能力已经可用：policy supervisor 可以对酒店 / 机票 / 报销混合问题做显式拆分、逐域执行、聚合输出，并在任一子域 coverage 不完整时统一进入 review。
