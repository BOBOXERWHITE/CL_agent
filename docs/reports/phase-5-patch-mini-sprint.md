# Phase 5 补丁 Mini-Sprint 报告

> 生成时间：2026-04-24
> 依据：`docs/reports/phase-5-review.md` 第四章遗留事项
> 范围：消化 Phase 5 review 列出的 MEDIUM 技术债
> 工期：实际耗时 1 天

---

## 一、执行总结

| 指标 | Phase 5 结束 | Mini-sprint 结束 | 变化 |
|---|---|---|---|
| 非 integration 测试数 | 403 passed | **417 passed** | +14（+3.5%）|
| ruff violations | 0 | 0 | — |
| Phase 5 MEDIUM 技术债 | 3 条 | **0 条** | 全部收口 |
| 运行时行为变化 | — | trace_span 进入业务 hot path / token_sink 防竞态 / OTEL SDK IT 打通 | 对外接口零破坏 |

**补丁任务**：3 条全部交付 + 1 份报告。

---

## 二、Patch A：`trace_span` 接入业务 hot path

**对应遗留**：Phase 5 review 3.2 —— trace_id 能跨进程但 OTLP 后端看不到业务维度 span。

**交付**：
- `backend/app/services/rag/query_engine.py` — `answer_policy_question_async` 三处打 span：`policy_qa.rewrite`（LLM 改写）/ `policy_qa.retrieve.multi_query`（多通道检索）/ `policy_qa.generate`（答案生成，span 上打 tokens 属性）
- `backend/app/services/agents/event_sink.py` — `persist_agent_events` 包 `agent_event.persist` span，attrs 含 agent_run_id / tenant_id / event_count
- `backend/app/workers/tasks.py` — `ingest_document_task` 内部 `ingestion.run_job` span；worker 入口调 `restore_trace_from_celery_headers(self.request.headers)` 恢复 trace 上下文
- `backend/app/workers/tasks.py::submit_ingestion` — `apply_async(headers=celery_task_headers())` 把 trace_id 放进 Celery headers 给 worker
- `backend/tests/core/test_trace_span_business.py` 6 用例

**核心设计**：
- **no-op 层可断言**：`trace_span_closed` DEBUG log 带 `span_name` + `attrs` 两个字段 —— 测试不需要真 OTEL 就能验证 span 发射
- **早返回兼容**：QA 函数有多个早返回分支（no-evidence / low-confidence / cache-hit），所以没用单个大 span 包函数体；每个 HTTP 调用独立开 span，用 trace_id contextvar 隐式串起来
- **trace 跨进程闭环**：publish 端 `celery_task_headers(current_trace_id())` → Celery headers → worker 端 `restore_trace_from_celery_headers(...)` → 同一条 trace 在后端串成父子 span
- **生成 span 带 token 属性**：`gen_span.set_attr("input_tokens", ...)` —— OTLP 后端能以 token / cost 维度切 span，billing dashboard 友好

**测试覆盖**（6 用例）：
- no-op 层 close log 带 attrs 1
- persist_agent_events 打名称正确的 span 1
- 嵌套 span 顺序正确（inner.a → inner.b → outer）1
- 异常里的 span finally 仍发射 1
- query_engine 源码 grep 保证 `policy_qa.rewrite` / `policy_qa.generate` 名称在 1
- tasks.py 源码 grep 保证 `restore_trace_from_celery_headers` + `ingestion.run_job` + `celery_task_headers` 都还在 1

---

## 三、Patch B：`token_sink` 原子 upsert

**对应遗留**：Phase 5 review 3.3 —— 并发两个 web 请求同一 `(tenant, day, model, agent)` 触发 IntegrityError。

**交付**：
- `backend/app/services/observability/token_sink.py` 重写 `accumulate()`
  - 新 `_accumulate_pg()`：PG 走 `pg_insert().on_conflict_do_update()` + `RETURNING *`，单条 statement
  - 新 `_accumulate_fallback()`：SQLite / 其他方言用 `begin_nested()`（SAVEPOINT）包 INSERT；失败 → UPDATE by unique tuple；单次重试
  - `accumulate()` 按 `session.get_bind().dialect.name` 分派
- `backend/tests/core/test_token_sink.py` 新增 3 用例

**核心设计**：
- **PG 单条语句原子**：`INSERT ... ON CONFLICT DO UPDATE` 配 `TokenUsageDaily.xxx + excluded.xxx` 写法保证 "已有行 + delta" 正确累加；cost_usd_cents 用 `COALESCE` 处理 null-to-value 边界
- **SAVEPOINT 而非全事务 rollback**：原来的代码一 rollback 就把**同 session 里的其他未 commit 写**也抹掉（agents.py 同一 request 里还有 AuditLog、AgentRun 等），所以必须用 SAVEPOINT 只回滚 sink 自己的 INSERT
- **单轮重试足够**：INSERT 失败的唯一原因是同 key 已存在（unique constraint）；UPDATE 直接走 unique tuple，不会再冲突
- **null cost 保留语义**：如果老行 cost=null 且新 delta 也没算出 cost，合并后仍 null（不是 0）

**测试覆盖**（3 新用例）：
- 模拟并发写：预先 INSERT 一行，再调 accumulate → SAVEPOINT 冲突 + UPDATE 兜底 + tokens 正确合并
- 100 次连续 accumulate → 1 行 × 100 requests（没有 SAVEPOINT 错乱导致丢数据）
- null cost + null delta → 合并后仍 null（防止 coalesce 把 null 升成 0）

---

## 四、Patch C：OTEL 端到端 mock IT

**对应遗留**：Phase 5 review 3.1 —— OTEL SDK 升级 / API 变化没有回归。

**交付**：
- `backend/pyproject.toml` — 新增可选 extras `otel = ["opentelemetry-sdk>=1.29,<2.0", "opentelemetry-exporter-otlp-proto-http>=1.29,<2.0"]`
- `backend/app/core/observability/tracing.py::init_otel_tracer` — 新增 `exporter` / `force` kwargs 让测试注入 `InMemorySpanExporter`；跳过 env check；把 `SimpleSpanProcessor` 用于 test exporter（同步刷新）
- `backend/tests/core/test_otel_export.py` 5 用例，用 `importorskip("opentelemetry.sdk.trace")` 保证没装 OTEL 时整个文件 skip 不阻塞 CI

**核心设计**：
- **不用 Docker / 真 collector**：`InMemorySpanExporter` 是 OTEL SDK 官方的测试 exporter，全路径（TracerProvider → SimpleSpanProcessor → exporter.export）都是真 SDK 代码
- **module-scope setup**：OTEL 的 `set_tracer_provider` 是一次性（第二次 call 被 log warning + 保留老 provider）→ 用 `scope="module"` 的 autouse fixture 初始化一次，每个 test 通过 `exporter.clear()` 清空 buffer
- **`importorskip`**：没装 `opentelemetry-sdk` 时整个 test module skip，和 `otel` extras 的可选性一致
- **force=True**：production lifespan 永远不传；只有测试会用

**测试覆盖**（5 用例）：
- 基础 `trace_span` → exporter 收到 name + attrs 正确 1
- 嵌套 span parent-child 关系：inner.parent.span_id == outer.context.span_id + 同 trace_id 1
- 异常 span StatusCode.ERROR 正确打标 1
- `init_otel_tracer` 无 force 幂等（第二次调用不替换 exporter）1
- 业务 hot path (`persist_agent_events`) 真的把 span 导到 exporter 1

---

## 五、验收数据

- `pytest tests/core/test_trace_span_business.py tests/core/test_token_sink.py tests/core/test_otel_export.py -q` → 24/24 pass
- `pytest -q --ignore=tests/integration` → **417 passed**（基线 403，+14 新测试）
- `ruff check` on all mini-sprint new/modified files → **0 violations**
- 对外 API 契约零破坏

---

## 六、消化的遗留事项

| 条目 | 来源 | 状态 |
|---|---|---|
| OTEL 真 OTLP export IT | Phase 5 review 3.1 | ✅ 以 InMemorySpanExporter 等价覆盖 |
| trace_span 接入业务 hot path | Phase 5 review 3.2 | ✅ policy_qa / agent_event / ingestion 三条 |
| token_sink 真 atomic upsert | Phase 5 review 3.3 | ✅ PG ON CONFLICT + SQLite SAVEPOINT |

## 七、仍未消化的遗留（保持原判）

| 条目 | 来源 | 优先级 | 建议归属 |
|---|---|---|---|
| cost_usd_cents 精度升级 | Phase 5 review 3.4 | Low | billing 上线前 |
| Celery beat 部署指南 | Phase 5 review 3.5 | Low | 运维文档 |
| Celery real broker IT | Phase 5 review 3.6 | Low | 业务驱动 |
| AsyncSession 全量迁移 | Phase 4 遗留 | Low | Phase 6 |
| SSE / WebSocket streaming | 规划推迟项 | Medium | Phase 6 |
| Prompt 版本 A/B + 在线评估 | 规划推迟项 | Medium | Phase 6 |
| LangSmith / Phoenix 直接集成 | 规划推迟项 | Low | OTLP 后做 |
| PII 脱敏 / guardrails | 规划推迟项 | — | 业务驱动 |

---

## 八、评分变化

| 维度 | Phase 5 结束 | Mini-sprint 结束 | 变化 |
|---|---|---|---|
| 可观测性 | 8.0 | **8.3** | +0.3（业务 span 落到 OTLP + IT 回归防护）|
| 后端工程 | 8.0 | **8.2** | +0.2（`accumulate` 并发安全）|
| 其他维度 | — | — | 无变化 |

**综合项目评分**：8.7 → **8.8**

---

## 九、下一步

Phase 5 + mini-sprint 完结后的自然去向：

1. **Phase 6（Prompt 运营 + AsyncSession + streaming）**
   - 规划里推迟到 Phase 6 的项目（Prompt A/B、SSE 流式响应、AsyncSession 全量迁移）
   - 预期 10 天

2. **Phase 7（运营化 / SRE 接入）**
   - Grafana dashboard / Alertmanager 规则
   - PII 脱敏 / guardrails
   - SLO / error budget 定义
   - 主要是 SRE + 业务侧工作

3. **业务功能迭代**
   - 不再追评分；转到真实业务需求（新 agent / 新工具 / 新集成）

建议按 **Phase 6 → Phase 7** 顺序进入下一阶段；或者如果业务时间表紧迫，可以把 Phase 6 的 Prompt 运营部分拆出单独做（SSE / AsyncSession 留到更晚）。

---

**Mini-sprint 验收结论**：✅ 通过。Phase 5 的 3 条 MEDIUM 技术债全部收口；+14 新测试；0 回归；0 lint 违规；对外 API 向后兼容。建议进入 Phase 6。
