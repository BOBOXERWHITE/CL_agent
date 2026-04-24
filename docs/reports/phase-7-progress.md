# Phase 7 执行进度

> 依据：`docs/plans/2026-04-26-phase-7-ops-hardening.md`
> 阶段目标：运营化闭环 + 真流式下推；消化 Phase 6 review 遗留 MEDIUM/LOW

## 进度表

| ID | 任务 | 状态 | 完成日期 | 测试 |
|---|---|---|---|---|
| P7.3 | RagRecallLog.latency_ms + stats 数据治理 | ✅ 完成 | 2026-04-26 | +2 新单测 |
| P7.4 | `/api/health/slo` 观测端点 | ✅ 完成 | 2026-04-26 | +7 新单测 |
| P7.1 | 真流式下推（engine 拆分）| ✅ 完成 | 2026-04-26 | +2 新单测 |
| P7.2 | PII 脱敏 guardrails | ✅ 完成 | 2026-04-26 | +16 新单测 |
| P7.5 | selection_log 边界日志 | ✅ 完成 | 2026-04-26 | +2 新单测 |
| P7.6 | Phase 7 review | ✅ 完成 | 2026-04-26 | 见 `phase-7-review.md`，499 total passed |

## P7.3 验收明细

**交付**：
- `backend/app/db/models/rag_recall_log.py` — 新 `latency_ms` / `confidence` 列
- `backend/alembic/versions/0012_rag_recall_log_latency.py` — ADD COLUMN × 2
- `backend/app/api/routes/chat.py` — `/ask` + `/ask/stream` 路由填充这两列
- `backend/app/services/prompts/stats.py` — `compute_prompt_stats` 走真 SQL AVG(latency_ms) + AVG(confidence)
- `backend/tests/api/test_prompt_feedback.py` +2 测试

**核心设计**：
- 把 latency / confidence 提升为一等列，取消 P6.3 的 JSON path 占位符
- null 语义保留（区分"无数据"和"零延迟"）

## P7.4 验收明细

**交付**：
- `backend/app/api/routes/slo.py` — 新 `GET /api/health/slo` 端点
- `backend/app/main.py` — 挂载 `slo_router`
- `backend/tests/api/test_slo_endpoint.py` 7 用例

**核心设计**：
- 5 分钟默认窗口（1-60 分钟可配）聚合 `runtime_log`
- Python 端线性插值计算 p50 / p95（SQLite 无 `percentile_cont`）
- error_rate = (status_code ≥ 500) / total
- active_chat_sessions = distinct session_id（非空）
- cache_hit_rate 从 Prometheus counter 反查，缺失返回 null
- 租户隔离 + admin/operator only

## P7.1 验收明细

**交付**：
- `backend/app/services/rag/query_engine.py`：
  - 新 `StreamReadyContext` dataclass
  - `prepare_answer_context_async` 返回 `PolicyAnswerResult | StreamReadyContext`
  - `stream_answer_from_context` 异步 generator
  - `build_policy_answer_from_stream`（事后重建 canonical + write cache）
- `backend/app/api/routes/chat.py` — `/ask/stream` 重写成真 pushdown
- `backend/app/api/routes/chat.py::_persist_chat` — 抽出的共享持久化 helper
- `backend/tests/api/test_chat_stream.py` +2 用例

**核心设计**：
- **早返回 vs 流式两路**：`prepare_answer_context_async` 返回 early `PolicyAnswerResult` 或 `StreamReadyContext`；早返回不开 LLM stream
- **真 pushdown**：streaming 路径 `async for` 取 LLM token（不是"跑完一次性答案再分块"）
- **非流式路径 byte-for-byte 不变**：`answer_policy_question_async` 原封保留
- **cache write-back 对齐**：`build_policy_answer_from_stream` 用同一 cache_key，和非流式一致
- **持久化抽公共 helper**：避免早返回 vs 流式两份 copy

## P7.2 验收明细

**交付**：
- `backend/app/core/guardrails/redaction.py` — 新 module + 6 类 PII regex + 3 个公共函数
- `backend/app/core/audit.py::_sanitize` — 扩展 string value regex redaction
- `backend/app/services/runtime_logs.py::create_runtime_log` — `error_message` 写库前 redact
- `backend/tests/core/test_pii_redaction.py` 16 用例

**核心设计**：
- regex-only，不接 LLM（目标"拦下明显 PII"，非合规级）
- `GUARDRAILS_PII_ENABLED` 全局 flag + `force` 参数单点覆盖
- 长/具体模式优先（email → CN ID → passport → bank card → phones）
- 非字符串值原样保留；不递归嵌套结构
- 记录侧脱敏（audit / runtime_log），用户响应 answer 不改

## P7.5 验收明细

**交付**：
- `backend/app/services/prompts/selector.py` — 对 0-traffic candidate 也拉出；主选择后为每条写 `variant_group="skipped"` log
- `backend/tests/core/test_prompt_selector.py` +2 用例

**核心设计**：
- 调试可读性：operator 查 `WHERE variant_group='skipped'` 能看到被屏蔽的 candidate
- 批量写后 commit；失败仅 log warning 不挂请求
- 原 traffic 分流语义不变

## 下一步

P7.6 Phase 7 review：综合报告 + 评分复核 + 下一步建议。
