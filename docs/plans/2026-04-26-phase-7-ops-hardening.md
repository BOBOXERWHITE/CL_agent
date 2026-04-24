# Phase 7 规划：运营化闭环 + 真流式下推

> 生成时间：2026-04-26
> 依据：`docs/reports/phase-6-review.md` 第四章遗留事项
> 范围：SSE engine 重构 + PII 脱敏 + stats 数据治理 + SLO 观测端点 + selection_log 边界日志
> 工期：7 工作日
> 目标评分跃迁：综合 9.0 → 9.2（边际；Phase 7 是质量沉淀而非评分突破）

---

## 零、为什么 Phase 7

Phase 6 结束后已经具备：
- 完整的 Agent / Prompt / Token 运营面
- OTEL 可观测基础设施
- A/B + 反馈闭环
- SSE streaming 基础

但剩下 5 个 MEDIUM / LOW 项卡在"最后一公里"：
1. **SSE 端点不是真 LLM stream**（Phase 6 review 3.1）：用户等到 LLM 生成完整才开始分块
2. **没有输入 / 输出 PII 脱敏**：生产安全红线
3. **stats 的 avg_confidence / latency 是 null**（Phase 6 review 3.3）：A/B 决策只能看 up_rate
4. **没有 SLO 观测面**：运维无法判断"当前健康度"
5. **selection_log 边界状态**（Phase 6 review 3.2）：A/B 分析盲点

这些单独看都不大；一起做能形成"可上线可运营"的闭环。

---

## 一、范围判断：做什么 / 不做什么

### ✅ 做

| 痛点 | 处置 |
|---|---|
| SSE 端点先跑完再分块 | `answer_policy_question_async` 拆 `prepare_answer_context_async` + `generate_answer_stream_async`；路由按需组合 |
| 无 PII 脱敏 | 新 `app/core/guardrails/redaction.py`：手机号 / 邮箱 / 身份证 / 银行卡 / 护照 pattern；入参脱敏（log）+ 出参可选过滤（flag 开关）|
| stats 拿不到真数据 | `RagRecallLog.latency_ms` 列；路由填充；`stats.py` 用 `latency_ms` 平均；PG 下从 `trace_json->>'confidence'` 提取 |
| 无 SLO 观测端点 | 新 `/api/health/slo`：返回 p50/p95 latency、error rate、active trace count、cache hit rate |
| selection_log 漏边界状态 | 加记 `skipped:<reason>` 行（0-traffic candidate / 未配置）|

### ❌ 不做（记录到"下一步"）

| 项 | 推迟到 |
|---|---|
| Grafana dashboard 配置 / Alertmanager 规则 | SRE 侧工作，不在工程 |
| WebSocket 双向 | 业务驱动 |
| 多目标 bandit auto-promote | 手动够用 |
| AsyncSession 全量迁移 | 业务驱动 |
| PII 脱敏的 LLM 辅助检测（regex-only 即可）| Phase 8+ |

---

## 二、子任务拆解（5 个 + review）

| ID | 任务 | 工期 | 核心改动 |
|---|---|---|---|
| P7.1 | 真流式下推（engine 拆分）| 2d | `prepare_answer_context_async` + `generate_answer_stream_async`；chat route 直接消费 |
| P7.2 | PII 脱敏 guardrails | 1.5d | `redaction.py` + log 中间件 + response flag |
| P7.3 | RagRecallLog.latency_ms + stats 数据治理 | 1d | alembic 0012 + 路由填充 + stats 查询更新 |
| P7.4 | `/api/health/slo` 观测端点 | 1d | Prometheus + RuntimeLog + cache metrics 聚合 |
| P7.5 | selection_log 边界状态 | 0.5d | selector 新增 skip reason 写入 |
| P7.6 | Phase 7 review | 0.5d | 报告 + 评分复核 + 下一步 |

**净工期 6.5 天 + 0.5 天 buffer = 7 天**。

---

## 三、详细设计

### P7.1 真流式下推

**现状**：`chat.py::stream_policy_question` 先 `await answer_policy_question_async(...)` 拿到完整 `PolicyAnswerResult`，再按空格切块回推。用户感知延迟 = 完整生成延迟，streaming 的理论优势未兑现。

**改造**：
- 拆 `answer_policy_question_async` 为两段：
  - `prepare_answer_context_async(question, tenant, customer)` → `AnswerContext(citations, prompt_selection, evidence_snippets, cached_answer, top_score, ...)`；无 LLM 生成
  - `generate_answer_stream_async(context)` → `AsyncIterator[StreamChunk]`；调用 `answer_client.stream_answer_async`
- 路由 handler：先 await `prepare_answer_context_async` 拿 citations + 早返回分支（no-evidence / low-confidence / cache-hit）；然后 yield start + citations；最后 async-for `generate_answer_stream_async` yield delta
- 老 `answer_policy_question_async` 保留：内部 call `prepare` + `generate_answer_stream_async` 并消费到终态（sync-facing callers 不感知）

**测试**：
- `test_stream_real_generates_token_by_token`：mock OpenAI streaming handler 分 5 chunks；断言路由 yield 的 delta 数 ≥ 5
- 语义 parity 不变：`test_stream_and_ask_return_same_answer` 用确定性客户端对比

### P7.2 PII 脱敏 guardrails

**新模块** `app/core/guardrails/redaction.py`：
- `redact_text(text: str) -> str`：regex 替换 / 邮箱 / 手机（中美）/ 身份证 / 银行卡（Luhn 宽松）/ 护照
- `has_pii(text: str) -> bool`：仅检测
- 规则集 可配：`PII_REDACTION_ENABLED = true`（生产默认 true）；单元测试可关
- 返回形式：邮箱 → `[EMAIL]`、手机 → `[PHONE]`、身份证 → `[ID]`

**接入点**：
1. **日志脱敏**：`app.main.request_logger` 对 `question_chars` 等字段不变，但 runtime_log 写入前对 `question` 字段过一次 redact（防止 operator 查询日志时暴露用户 PII）
2. **audit_log**：`record_audit` payload 里如果有"user-supplied"字段，也过 redact
3. **response 可选过滤**：`POST /api/chat/ask` 带 `redact_response=true` query param 时对 `answer` 过一次 redact（B2B 场景合规需求）

**测试**：
- regex 覆盖 5 类 PII
- 日志中间件真实 redact（capture log record，assert `[EMAIL]` in message）
- response flag 开关行为
- 无害文本不被误伤

### P7.3 RagRecallLog.latency_ms + stats 真数据

**现状**：`RagRecallLog` 没有 latency 列；`prompt_template_stats.avg_latency_ms` 始终 null。

**改造**：
- alembic 0012：`ALTER TABLE rag_recall_log ADD COLUMN latency_ms INT`
- `chat.py` + streaming route 填充：记录 `perf_counter()` 起止
- `stats.py::compute_prompt_stats`：新增 avg_latency 子查询；PG 下 `AVG(cast(trace_json->>'confidence' AS real))` 提取 confidence
- 测试：SQLite 下 `latency_ms` 已有 → stats 返回非 null

### P7.4 `/api/health/slo`

**新端点**：`GET /api/health/slo` 返回：
```json
{
  "window_minutes": 5,
  "request_count": 123,
  "p50_latency_ms": 420,
  "p95_latency_ms": 1850,
  "error_rate": 0.012,
  "cache_hit_rate": 0.68,
  "active_chat_sessions": 14,
  "updated_at": "..."
}
```

**实现**：
- 聚合查询 `runtime_log` 最近 5 min（窗口可配）
- cache hit rate 从 Prometheus counter 读（不准确则 fallback null）
- 权限：admin / operator
- 测试：seed 不同 runtime_log 状态码 → 验证 error_rate / latency 聚合

### P7.5 selection_log 边界日志

**改造**：
- `selector.py::select_prompt_variant` 内部：
  - 如果发现 0-traffic candidate → 写 `selection_log(variant_group="skipped", reason="candidate_zero_traffic:{id}")`
  - 如果发现配置错（traffic 累计 > 100）→ 写 warning log + 强制回落
- 保证 A/B 分析能看到"candidate 有，但 traffic=0 所以没流量"
- 测试：seed 0-traffic candidate → 断言 skipped log 行存在

### P7.6 Phase 7 review

同前格式。

---

## 四、依赖关系图

```
P7.1 engine 拆分 (独立)
P7.2 PII 脱敏 (独立)
P7.3 latency + confidence (独立)
  ↓
P7.4 SLO 端点 ←── 读 RagRecallLog.latency_ms
P7.5 selection_log 边界 (独立)
  ↓
P7.6 review
```

建议顺序：P7.3 → P7.4 → P7.1 → P7.2 → P7.5 → P7.6（先拿数据，后搭观测面，然后真 stream，最后 PII 和 selector）

---

## 五、契约稳定性承诺

| 类别 | 稳定性 |
|---|---|
| `/api/chat/ask` 非流式响应字段 | 不变 |
| `/api/chat/ask/stream` 事件序列 | 不变（P7.1 只改"何时 yield delta"）|
| `PolicyAnswerResult` 字段 | 不变（拆分后内部用 `AnswerContext`）|
| `RagRecallLog` 老字段 | 不变（additive 加 latency_ms）|
| 日志字段名 | 不变（PII 只是替换值）|

---

## 六、总验收

1. **`/api/chat/ask/stream`** 在真 OpenAI 上的 TTFB < 完整响应时间的 1/3
2. **日志里看到** `"[EMAIL]"` / `"[PHONE]"` 替换而非明文
3. **`GET /api/prompts/{id}/stats`** 返回非 null 的 `avg_latency_ms`
4. **`GET /api/health/slo`** 返回 5 min 窗口的 p50/p95/error rate
5. **`SELECT * FROM prompt_selection_log WHERE variant_group='skipped'`** 能看到 0-traffic candidate 记录

---

## 七、下一步

等用户：
- **「OK，按此顺序执行」** → 开 P7.3（latency 列 + stats 数据治理）
- **「先做 PII」** → 改序 P7.2 优先
- **「只做必要的」** → 只做 P7.1 + P7.2（真 stream + 安全红线），其余推迟
