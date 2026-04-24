# Phase 6 执行进度

> 依据：`docs/plans/2026-04-25-phase-6-prompt-ops-streaming.md`
> 阶段目标：Prompt 运营化（A/B + 反馈 + 升降级）+ SSE 流式响应

## 进度表

| ID | 任务 | 状态 | 完成日期 | 测试 |
|---|---|---|---|---|
| P6.1 | Prompt 状态机 + traffic_percent | ✅ 完成 | 2026-04-25 | +14 新单测，431 total passed |
| P6.2 | A/B 选择器 + selection_log | ✅ 完成 | 2026-04-25 | +11 新单测，442 total passed |
| P6.3 | 反馈采集 + stats 聚合 | ✅ 完成 | 2026-04-25 | +8 新单测 |
| P6.4 | Promote / rollback API | ✅ 完成 | 2026-04-25 | +5 新单测 |
| P6.5 | SSE streaming | ✅ 完成 | 2026-04-25 | +10 新单测 |
| P6.6 | Phase 6 review | ✅ 完成 | 2026-04-25 | 见 `phase-6-review.md`，470 total passed |

## P6.1 验收明细

**交付**：
- `backend/app/db/models/prompt_template.py` — 状态枚举常量（`STATUS_DRAFT/CANDIDATE/ACTIVE/ARCHIVED`）+ `traffic_percent` 列
- `backend/alembic/versions/0009_prompt_traffic_percent.py` — `ADD COLUMN traffic_percent INT DEFAULT 0`
- `backend/app/services/prompts/service.py` — `transition_prompt_template()` 带合法转换 map
- `backend/app/schemas/prompt_template.py` — `PromptTemplateTransitionRequest` + payload 增 traffic_percent
- `backend/tests/core/test_prompt_state_machine.py` 14 用例

**核心设计**：四态状态机 `draft ↔ candidate → active → archived → draft`；`active → active` 幂等 + `candidate → candidate` 可改 traffic；legacy `activate_prompt_template` 行为保留；非 candidate 状态 traffic_percent > 0 直接 raise。

## P6.2 验收明细

**交付**：
- `backend/app/db/models/prompt_selection_log.py` — 新表
- `backend/alembic/versions/0010_prompt_selection_log.py` — CREATE TABLE + RLS
- `backend/app/services/prompts/selector.py` — `select_prompt_variant()` hash-bucket A/B + log sink
- `backend/app/services/rag/query_engine.py` — 两条 QA 路径接入 selector
- `backend/tests/core/test_prompt_selector.py` 11 用例

**核心设计**：`sha256(tenant|task)[:8] % 100` 确定性哈希；累加阈值分流；`variant_group` + `selected_reason` 双字段便于 A/B 溯源；log failure 不拦截请求。

## P6.3 验收明细

**交付**：
- `backend/app/db/models/prompt_feedback.py` — 新表 + rating 常量
- `backend/alembic/versions/0011_prompt_feedback.py` — CREATE TABLE + RLS
- `backend/app/services/prompts/stats.py` — `compute_prompt_stats()` join
- 新路由：`GET /api/prompts/{id}/stats`、`POST /api/chat/sessions/{id}/feedback`

**核心设计**：反馈自动归因到最新 assistant 消息的 prompt；`up_rate` null vs 0 语义清晰；reviewer 角色不能看 stats；session 跨租户防护。

## P6.4 验收明细

**交付**：
- `POST /api/prompts/{id}/promote` + `/rollback` 语法糖端点
- `POST /api/prompts/{id}/transition` 底层暴露
- Tests: promote + rollback + idempotency + role guard (5 new)

**核心设计**：URL 动词让 audit 搜索直观；拒绝 `archived → active` 直接跳转；admin-only。

## P6.5 验收明细

**交付**：
- `backend/app/services/llm/client.py` — `StreamChunk` + `stream_answer_async` on both clients（deterministic + OpenAI SSE）
- `backend/app/api/routes/chat.py` — `POST /api/chat/ask/stream` with `StreamingResponse` + SSE frames
- `backend/tests/rag/test_llm_client_stream.py` 5 用例（OpenAI SSE + deterministic 对齐）
- `backend/tests/api/test_chat_stream.py` 5 用例（端到端 event sequence + 侧效应）

**核心设计**：4 种事件（`start` / `citations` / `delta` / `done` / `error`）；词组分块保护 CJK；持久化在流结束后；OpenAI 真 `stream=true` SSE 解析容忍 malformed JSON。

## 下一步

P6.6 Phase 6 review：综合报告 + 评分复核 + 下一步建议（Phase 7 运营化 / SRE 接入）。
