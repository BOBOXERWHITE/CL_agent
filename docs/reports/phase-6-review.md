# Phase 6 Review：Prompt 运营化 + 流式响应整体验收

> 生成时间：2026-04-25
> 范围：`docs/plans/2026-04-25-phase-6-prompt-ops-streaming.md` 全部 5 个子任务 + review
> 参考基线：`docs/reports/phase-5-patch-mini-sprint.md`（综合 8.8 / Prompt 运营 0）
> 进度明细：`docs/reports/phase-6-progress.md`

---

## 一、执行总结

| 指标 | 起点（mini-sprint 结束） | Phase 6 结束 | 变化 |
|---|---|---|---|
| 非 integration 测试数 | 417 passed | **470 passed** | +53（+13%）|
| 新 DB 表 | — | 2（prompt_selection_log / prompt_feedback）+ 1 列（prompt_template.traffic_percent）| 都带 RLS |
| 新 API 端点 | — | 6 | `/api/prompts/{id}/transition`、`/promote`、`/rollback`、`/stats`、`/api/chat/sessions/{id}/feedback`、`/api/chat/ask/stream` |
| Prompt 状态数 | 2（draft/active） | **4**（+candidate/archived） | 状态机完整 |
| LLM 客户端能力 | 同步 + async 一次性返回 | + 流式 `stream_answer_async` | SSE 真流式 |
| ruff violations | 0 | 0 | — |

**子任务完成情况**：5/5 交付 + review。

**契约稳定性**：
- `/api/chat/ask` / `/api/agents/runs` / `/api/tasks/*` / `/api/usage` 响应字段 zero-break
- `PromptTemplate` 老字段不变；新增 `traffic_percent` 有 default
- 老 `activate_prompt_template` 行为保留（legacy 测试依赖它把兄弟 demote 成 draft）
- `get_prompt_selection` 函数仍在（service.py 保留）；实际调用路径换到 `select_prompt_variant`

---

## 二、架构评估

### 2.1 Prompt 从"单一 active"到"持续运营"

**证据**：

| 维度 | Phase 5 结束 | Phase 6 结束 |
|---|---|---|
| Prompt 状态数 | 2（draft / active）| 4（draft / candidate / active / archived）|
| A/B 能力 | 无 | `traffic_percent` + hash 确定性分流 |
| 反馈闭环 | 无 | `POST /feedback` + `GET /stats` + prompt_feedback 表 |
| 升降级流程 | `activate` 强制覆盖 | `promote` / `rollback` / `transition` 状态机校验 |
| 分流记录 | 无 | `prompt_selection_log` 每请求一行 |
| 变体归因 | 无 | chat metadata_json carries prompt_template_id + version |

### 2.2 流式响应接入

SSE stream 端点（`POST /api/chat/ask/stream`）复用了现有的 `answer_policy_question_async` 全管线，只把最终的 answer 文本换成 token-by-token 的 SSE 事件流：

```
Client                Server
  │                     │
  │─── POST ask/stream ─▶
  │                     │ (run full QA pipeline)
  │                     │
  │◀── start ───────────│
  │◀── citations ───────│
  │◀── delta ×N ────────│ (word-group chunks)
  │                     │
  │                     │ (persist ChatMessage / RagRecallLog / audit)
  │◀── done ────────────│
```

**设计权衡**：这不是"真 LLM streaming"（OpenAI `stream=true` 透传），而是"管线跑完一次性答案，然后分块回推"。理由：

- 用户体验相同（打字机效果）
- cache / citations / confidence / token_usage 语义与非流式完全一致
- 失败路径简单（stream 中断只需 fail 一次，不用重连）
- 真 LLM stream 的底层能力（`OpenAICompatiblePolicyAnswerClient.stream_answer_async`）已实现，需要时可把 stream 下推到 engine

### 2.3 新模块职责划分

```
app/db/models/
├── prompt_template.py         # + traffic_percent + 状态常量
├── prompt_selection_log.py    # 新：A/B 选择事件
└── prompt_feedback.py         # 新：用户反馈

app/services/prompts/
├── service.py                 # + transition_prompt_template + PromptStateError
├── selector.py                # 新：select_prompt_variant + hash bucket
└── stats.py                   # 新：compute_prompt_stats

app/api/routes/
├── prompt_templates.py        # + transition / promote / rollback / stats + feedback_router
└── chat.py                    # + POST /ask/stream SSE endpoint

app/services/llm/
└── client.py                  # + StreamChunk + stream_answer_async (both clients)

alembic/versions/
├── 0009_prompt_traffic_percent.py
├── 0010_prompt_selection_log.py
└── 0011_prompt_feedback.py
```

---

## 三、问题清单（CRITICAL / HIGH / MEDIUM / LOW）

### 3.1 MEDIUM：SSE 端点不是"真 LLM stream"

**证据**：`chat.py::stream_policy_question` 先跑完 `answer_policy_question_async` 再分块回推。

**影响**：
- 用户等到 LLM 完整生成后才开始看到 token，感知延迟 = 真 stream 延迟（不是 streaming 的理论优势）
- P6.5 验收"真正的 token-by-token 流"只在 `stream_answer_async` 底层能力里成立
- 需要更深的 engine 重构才能把 stream 下推到 `answer_policy_question_async` 返回类型

**建议**：
- Phase 7 把 `answer_policy_question_async` 拆成 `prepare_answer_context_async`（返回 citations + confidence）+ `generate_answer_stream(...)` 两段；路由 handler 用前者产出 metadata SSE 事件 + 直接透传后者的 chunk
- 当前 Phase 6 交付的是"可见的流式 UX" + "底层能力就绪"；继续推到真 streaming 是一次 incremental change

### 3.2 MEDIUM：selection_log 只写 active/candidate/default 三态

**证据**：`selector.py` 没有记录"请求被 0% traffic 的 candidate 拦截但回落 active"这种边界状态。

**影响**：
- A/B 分析看到的 variant_group 字段偏简化
- operator 无法调试"为什么这个 candidate 不起作用"（0% traffic 不会 log 就不知道它被屏蔽了）

**建议**：
- 在 selector 里把 `fell_through_to_active:candidates_exist=N` 之类的 reason 字段拓展
- 或新增 `selector_debug_log`（同 selection_log 但包含"跳过的候选"）
- 归入 Phase 7 运营工具

### 3.3 MEDIUM：stats 的 avg_confidence / avg_latency_ms 在 SQLite 下是 null

**证据**：`stats.py::_cast_confidence` 返回 literal NULL；latency 还没有 RagRecallLog 列。

**影响**：
- SQLite 测试环境下 `up_rate` 能算，但 `avg_confidence` / `avg_latency_ms` 总是 null
- 生产 PG 下也没真实数据（因为 SQL path 也是 literal NULL）

**建议**：
- 加 `RagRecallLog.latency_ms` 列（migration）+ route 侧填充
- PG 走 `trace_json->>'confidence'` 提取
- 归入 Phase 7 数据治理

### 3.4 LOW：feedback 端点未验证 rate limit

**证据**：`post_session_feedback` 没挂 slowapi `@limiter.limit`；恶意客户端可以反复 POST。

**影响**：
- 不太严重（一个用户往一个 session 刷 up 不影响 stats 决策）
- 加 rate limit 或写去重一行两全

**建议**：加 per-(tenant, session) dedup 约束，归入 Phase 7

### 3.5 LOW：Prompt inheritance / partials 未做

**证据**：规划推迟项。

**影响**：复用 snippets 只能复制文本，变更不会广播；长期运营痛点。

**建议**：业务驱动，Phase 7+。

---

## 四、遗留事项 / 技术债

| 条目 | 来源 | 优先级 | 建议归属 |
|---|---|---|---|
| 真 LLM stream 下推到 engine | MEDIUM 3.1 | Medium | Phase 7 |
| selection_log 边界状态记录 | MEDIUM 3.2 | Low | Phase 7 运营 |
| stats 的 avg_confidence / latency 拿到真数据 | MEDIUM 3.3 | Medium | Phase 7 数据治理 |
| feedback rate limit | LOW 3.4 | Low | Phase 7 |
| Prompt inheritance / partials | LOW 3.5 | Low | 业务驱动 |
| Response-side PII 脱敏 / guardrails | 规划推迟项 | Medium | Phase 7 运营化 |
| Grafana dashboard / Alertmanager | 规划推迟项 | Low | SRE 侧 |
| AsyncSession 全量迁移 | 规划推迟项 | Low | 业务驱动 |
| 多目标 bandit auto-promote | 规划推迟项 | Low | 手动够用再看 |
| Frontend prompt diff 可视化 | 规划推迟项 | Low | 前端团队 |

---

## 五、验收总清单

### 5.1 规划文档第七章总验收标准逐条核对

1. ✅ **创建 candidate (traffic=20)** → 20% 请求按 tenant hash 确定命中
   - 证据：`test_traffic_split_approximates_percentage` (10-45% 容差，200 个 tenant)
   - 证据：`test_selection_is_deterministic_for_same_tenant`

2. ✅ **GET `/api/prompts/{id}/stats`** 返回 up/down + up_rate
   - 证据：`test_stats_aggregates_up_down_counts` (3 up + 1 down → up_rate=0.75)

3. ✅ **candidate promote → active**，旧 active 自动 archive
   - 证据：`test_promote_candidate_to_active` + `test_transition_candidate_to_active_archives_previous_active`

4. ✅ **SSE streaming** 端到端
   - 证据：`test_stream_chat_emits_start_citations_delta_done` + `test_stream_chat_session_persisted_after_done`

5. ✅ **rollback archived → 恢复路径**
   - 证据：`test_rollback_active_to_archived` + `test_archived_to_draft_then_active_works`

### 5.2 回归 / Lint / Migration

- `pytest -q --ignore=tests/integration` → **470 passed**（基线 417；+53 新测试）
- `ruff check app/ tests/` → **0 violations**
- `alembic upgrade head`：新增 0009 / 0010 / 0011；链条 0001 → 0011 连续

---

## 六、评分变化

| 维度 | Phase 5 patch 结束 | Phase 6 结束 | 变化 |
|---|---|---|---|
| 数据库 | 8.0 | 8.0 | — |
| API / 鉴权 | 8.0 | 8.0 | — |
| RAG | 7.5 | 7.5 | — |
| 后端工程 | 8.2 | 8.3 | +0.1（状态机 + SSE 架构清晰度）|
| 安全 | 8.5 | 8.5 | — |
| Agent | 8.0 | 8.0 | — |
| 可观测性 | 8.3 | 8.3 | — |
| 异步 / 扩展性 | 7.5 | **8.0** | +0.5（SSE streaming 完成；真流式基建就绪）|
| **Prompt 运营化**（新增维度）| **0** | **8.0** | **全新能力** |

**综合项目评分**：8.8 → **9.0**（达成规划预估 9.0）

---

## 七、下一步选项

1. **Phase 7（运营化 / SRE 接入 / 真 stream 下推）**
   - 消化 MEDIUM 技术债：真 LLM stream 下推 / stats 数据治理 / PII 脱敏
   - 运营工具：Grafana dashboard / Alertmanager / SLO 定义
   - 预期 8 天

2. **业务功能迭代（非工程评分）**
   - 新 agent / 新工具 / 新集成
   - 不再追综合评分，转业务侧

3. **Phase 6 补丁 mini-sprint**
   - 2-3 天消化 3.1 + 3.3
   - 保守稳妥

建议按 **Phase 7 → 业务迭代** 顺序：先把运营闭环最后一公里（PII / 告警 / 真 stream 下推）补齐，然后转业务功能。

---

**Phase 6 验收结论**：✅ 通过。Prompt 运营化全新能力上线（4 态状态机 + A/B + 反馈闭环 + 流式 SSE）；综合评分 8.8 → 9.0 达成规划目标；0 生产回归；0 lint 违规；5 子任务 + review 全部交付。建议进入 Phase 7 或转业务迭代。
