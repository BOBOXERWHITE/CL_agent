# Phase 2 接入 Sprint（2026-04-22）

> 上游：`docs/reports/phase-2-progress.md` 明确记录了四项"推迟到下一 sprint"的接入工作。
> 本 sprint 把 Phase 2 新建的组件**真正接到主路径**。
> 结果：**179 unit + ruff 全绿（+4 新测试）**。

## 目标 & 范围

Phase 2 收尾时，组件都建好了但没串起来：

- ✅ `rewrite_query_multi` 存在 → 但 `query_engine` 仍调老的 `rewrite_query`
- ✅ `Cache` / `InMemoryCache` / `RedisCache` 存在 → 但 `answer_policy_question` 不读写
- ✅ `texts_to_embeddings` 存在 → 但没过缓存层
- ✅ `run_retrieval_eval` 存在 → 但没暴露 HTTP 接口

本次 sprint 全部接通。

---

## 交付清单

### S1：多查询检索接入（`query_engine.py`）

**改动**：
- `answer_policy_question` 从 `rewrite_query(question)` 切到 `rewrite_query_multi(question)`
- 新增 `_multi_query_search` 函数：对 `all_queries() + hyde_document` 的每个通道单独跑 `retrieve_hybrid`，然后 `fuse_ranked_hits` RRF 融合，最后一次 `rerank_hits` 收尾
- 单通道（alias-only，flags 关闭时的默认）走 fast-path，零开销
- 多通道时 `retrieval_trace.mode` 标为 `multi_hybrid`，便于离线分析

**Fallback 链保持不变**：`multi_hybrid` → `vector` → `lexical` 三级兜底都还在。

**测试**：
- `test_answer_policy_question_uses_multi_query_rewriter`：强制注入双通道 rewrite，确认 `multi_hybrid` 路径被走到
- 两处老 `test_policy_qa.py` 测试 patch 目标更新：`rewrite_query` → `rewrite_query_multi`，`_vector_search` 额外 patch `_multi_query_search`

### S2：答案缓存接入（`answer_policy_question`）

**改动**：
- LLM 调用前读取 `answer_cache_key(tenant_id, question|prompt_version, top_chunks_sig)`
- **命中**：短路 LLM，`retrieval_trace.rewrite_rules` 追加 `answer_cache_hit`，mode 后缀 `cache_hit`
- **未命中**：跑 LLM → 仅当 `answer_draft.confidence >= confidence_threshold` 时 write-through（避免缓存住"证据不足"的消极答复）
- 缓存 key 含 `prompt_version`，prompt 灰度发布自动失效
- 序列化失败用 `try/except` 吞掉，chat 主路径永不因缓存挂掉

**TTL**：`settings.cache_answer_ttl_seconds`（默认 600s / 10 min）。

**测试**：`test_answer_cache_hit_short_circuits_llm` 验证同一 query 二次调用走 cache 路径。

### S3：Embedding 缓存接入（`texts_to_embeddings`）

**改动**：
- 输入 texts 列表 → 逐个查 cache → 只把 miss 的 texts 送给 provider → 回写 cache
- Cache key = `emb:{model}:{sha256(text)[:32]}`，**model 在 key 里**，换 model 自动失效
- 两道防御：cache 读失败 / 写失败 / 反序列化失败都静默降级为"provider 直接算"
- TTL：`settings.cache_embedding_ttl_seconds`（默认 30 天）
- dimension 不匹配的 cache 值视为 miss（多一道保险）

**测试**：`test_embedding_cache_hit_on_repeat_call` 注入 counting provider，连续两次相同 text 只触发 1 次 provider 调用。

### S4：`/api/evals/retrieval-runs` 路由

**改动**：
- `backend/app/api/routes/evals.py` 新增 `POST /api/evals/retrieval-runs`
- 新 Pydantic schema：`RetrievalSamplePayload` / `RetrievalEvalRequest` / `PerSamplePayload` / `RetrievalEvalResponse`
- 每个 sample 都过 P1.3 的 `require_tenant_match`，拒绝跨租户评测
- 需要 `admin` 或 `operator` 角色（与 `/api/evals/runs` 一致）
- 返回 `sample_count + metrics + per_sample`，字段与 `run_retrieval_eval` 的 `RetrievalEvalReport` 对齐

**测试**：`test_retrieval_runs_endpoint_rejects_cross_tenant` 跑一次真 pipeline，验证响应结构 + metrics 键集合。

---

## 回归

| 指标 | 值 |
|---|---|
| 单元测试 | **179 passed**（+4）|
| ruff | 0 violations |
| integration | skip（Docker Desktop 未启动；Phase 2 原 11 集成测试在上次执行过）|

---

## 文件变更总览

### 新增（1 文件）
- `backend/tests/rag/test_query_engine_integrations.py`（4 用例）

### 修改（4 文件）
- `backend/app/services/rag/query_engine.py`：+multi-query path + answer cache
- `backend/app/services/rag/embedding_client.py`：+cache wrapper in `texts_to_embeddings`
- `backend/app/api/routes/evals.py`：+retrieval-runs route
- `backend/tests/rag/test_policy_qa.py`：更新 monkeypatch 目标为 `rewrite_query_multi` / `_multi_query_search`

---

## 端到端流程（/api/chat/ask 主路径）

```
    HTTP Request (JWT + body)
      ↓
    auth → guard (tenant_match) → audit
      ↓
    rewrite_query_multi(question)        # alias + LLM paraphrase + HyDE
      ↓
    _multi_query_search(rewrite)          # per-channel hybrid + RRF fuse
      ↓
    rerank_hits(...)                      # heuristic or openai-compatible
      ↓
    build_citations → confidence gate
      ↓
    [answer_cache HIT?] → YES: return cached
      ↓ NO
    LLM generate_answer(...)
      ↓
    write-through cache (if high-confidence)
      ↓
    persist ChatMessage + RagRecallLog + AuditLog (in one txn)
      ↓
    Response
```

**每个组件都有降级**：LLM 挂 → alias only；reranker 挂 → heuristic；cache 挂 → 直查；embedding provider 挂 → 主路径报 502，不伪造结果。

---

## 后续可选工作（不在本 sprint）

| 项 | 建议时机 |
|---|---|
| 录入 50-100 条真 benchmark 标注 | 和产品 / 领域专家一起，离线做 |
| `cache_enabled=true` 在测试里默认开，验证 write-through 路径 | 下一次"质量冲刺" |
| `/api/chat/ask` 也走 SlowAPI 限流配 answer cache 做压测 | Phase 3 async 化之后 |
| Milvus 真集成测试（替代 noop）| P2.8 规划说归下个 sprint，仍未做 |

---

## 小结

Phase 2 的 8 个子任务 + 本 sprint 的 4 项接入，让 RAG 链路从"组件齐全但孤立"变成"组件串起来且每一环都上了 caller 侧的主路径"。`/api/chat/ask` 现在真正利用了：

- 三级 query rewrite（alias + paraphrase + HyDE）
- 多通道 RRF 融合
- 两级 cache（embedding + answer）
- 可切换 reranker provider
- 全链路 audit trail

**下一步建议**：Phase 3（async / 可观测性 / K8s），或"质量冲刺"（benchmark 数据 + prompt A/B）。
