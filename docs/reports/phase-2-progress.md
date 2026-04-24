# Phase 2 执行进度

> 依据：`docs/plans/2026-04-07-enterprise-migration-phase-0-2.md`
> 阶段目标：RAG 真实化 —— 从"看起来像 RAG"升级到"能量化的真 RAG"

## 进度表（全部完成）

| ID | 任务 | 状态 | 完成日期 | 回归 |
|---|---|---|---|---|
| P2.1 | 默认 embedding 改真模型 + fail-fast | ✅ | 2026-04-21 | +7 unit |
| P2.2 | Deterministic 降级消失（并入 P2.1） | ✅ | 2026-04-21 | 同上 |
| P2.3 | 混检融合改 RRF | ✅ | 2026-04-21 | +4 unit |
| P2.4 | 接真 reranker（OpenAI 兼容 /rerank） | ✅ | 2026-04-21 | +5 unit |
| P2.5 | Retrieval 评测（recall@k / nDCG / MRR） | ✅ | 2026-04-21 | +19 unit |
| P2.6 | Query 改写升级（LLM paraphrase + HyDE） | ✅ | 2026-04-21 | +20 unit |
| P2.7 | Redis 缓存（三层 key + noop/memory/redis backend） | ✅ | 2026-04-21 | +10 unit |
| P2.8 | Milvus lifespan preload + HNSW 索引 | ✅ | 2026-04-21 | +7 unit |

**回归**：**175 unit + 11 integration + ruff 0 violations = 186 passed**（Phase 2 新增 72 unit test）

---

## 核心交付总览（按模块分类）

### 新增模块（5 个）

| 文件 | 作用 |
|---|---|
| `app/services/llm/rewrite_client.py` | LLM rewrite adapter（paraphrase + HyDE） |
| `app/services/eval/retrieval_metrics.py` | recall@k / precision@k / MRR / nDCG@k 纯函数 |
| `app/services/eval/retrieval_runner.py` | benchmark 驱动 + 汇总指标 |
| `app/core/cache.py` | Cache Protocol + Noop/InMemory/Redis backend |

### 重写模块（4 个）

| 文件 | 关键变化 |
|---|---|
| `app/services/rag/embedding_client.py` | silent fallback → `EmbeddingConfigError` fail-fast |
| `app/services/rag/rerankers.py` | 新 `OpenAICompatibleRerankerClient` + heuristic fallback |
| `app/services/rag/query_rewriter.py` | 新 `MultiQueryRewriteResult` + LLM paraphrase + HyDE |
| `app/services/rag/vector_store.py` | `preload()` + HNSW 索引 + `_loaded` 缓存 |

### 配置字段新增（17 个）

`backend/app/core/config.py`：
- **Reranker**: `reranker_provider` / `reranker_model_name` / `reranker_api_base_url` / `reranker_api_key` / `reranker_top_n` / `reranker_timeout_seconds`
- **Query rewrite**: `query_rewrite_llm_enabled` / `query_rewrite_llm_variants` / `hyde_enabled`
- **Cache**: `cache_enabled` / `cache_redis_url` / `cache_embedding_ttl_seconds` / `cache_retrieval_ttl_seconds` / `cache_answer_ttl_seconds`
- 加 `redis>=5.0,<7.0` 到 `pyproject.toml`

### Lifespan 增强

`app/main.py` 启动时：
1. schema bootstrap + seed rules（继承 Phase 0）
2. 打印 `embedding_provider / model / dimension`（P2.1）
3. deterministic 模式 WARNING（P2.1）
4. **Milvus `preload()` 一次性 load 集合**（P2.8）
5. 9 项生产 secret 校验（继承 Phase 1）

---

## 每任务验收亮点

### P2.1/P2.2 — 生产链路三层防护

| 层 | 动作 |
|---|---|
| 启动时 | `_validate_production_security` 强制 openai-compatible 配 key |
| 运行时 | `get_embedding_client()` 抛 `EmbeddingConfigError` 列出所有缺失 var |
| 日志层 | deterministic 模式 startup WARNING |

### P2.3 — RRF 融合已是事实（加 lock-in test）

`fuse_ranked_hits` 用 `1/(k+rank)` 公式；4 个测试锁定公式 / 融合顺序 / 文档去重 / 空通道处理。

### P2.4 — Reranker 双路径 + 失败降级

| Provider | 来源 | 失败处理 |
|---|---|---|
| `heuristic`（默认） | phrase+lexical bonus | 永远成功 |
| `openai-compatible` | `/rerank` API（Cohere/Jina/智谱 schema） | HTTP 错/解析错 → 自动 heuristic |

### P2.5 — Retrieval 评测可量化

4 个 IR 指标纯函数 + `RetrievalSample`/`RetrievalEvalReport`/`PerSampleResult` 结构化数据 + 运行 benchmark 的 runner。配套 13 个 metrics 单测（边界全覆盖）+ 3 个 runner E2E 测试。

### P2.6 — 三级查询改写

```
原 query
  → 1. alias expansion（always, offline）
  → 2. LLM paraphrase（QUERY_REWRITE_LLM_ENABLED）
  → 3. HyDE（HYDE_ENABLED）
  → all_queries() deduplicated，调用方 RRF 融合
```

- Rewrite client 单独分离（`app/services/llm/rewrite_client.py`），不影响 answer generation 路径
- 失败路径全部 try/except + WARNING，alias 兜底

### P2.7 — 三层 Cache 抽象

| Backend | 用途 |
|---|---|
| `NoopCache` | `CACHE_ENABLED=false`（默认） |
| `InMemoryCache` | 测试 / 单进程 dev |
| `RedisCache` | 生产 |

- 三类 key 命名：`emb:` / `retr:` / `ans:` + 独立 TTL
- JSON 编码值；非 JSON 值 `set` 时立即抛错
- `scan_iter` 实现 `clear_prefix`，不阻塞 Redis
- 单测 10 个（Noop/InMemory/key helper/factory fallback）

### P2.8 — Milvus 启动时 load 一次

| 问题 | 原状态 | P2.8 |
|---|---|---|
| `collection.load()` 调用频率 | 每次 search 都 load | 启动 load 一次 + `_loaded` 缓存 |
| 索引类型 | `AUTOINDEX`（不可调） | `HNSW` M=16 efConstruction=200 + query ef=64 |
| 无 preload 场景兜底 | — | search 检测 `_loaded=False` 自动补 load |
| 启动失败兜底 | — | preload 内 try/except，不 crash |

---

## 功能矩阵（三模块都新支持 OpenAI 兼容协议）

| 能力 | 协议 | 失败降级 | 超时 |
|---|---|---|---|
| Embedding | `/v1/embeddings` | fail-fast（production） | 30s |
| Reranker | `/v1/rerank` | heuristic | 5s |
| Query rewrite | `/v1/chat/completions` | alias-only | 10s |

换 provider（OpenAI / DeepSeek / 智谱 / Kimi / Jina ...）只改 3 个 env var：`*_API_BASE_URL` / `*_API_KEY` / `*_MODEL_NAME`。

---

## 新增测试文件（7 个）

| 文件 | 用例数 |
|---|---|
| `tests/rag/test_embedding_fail_fast.py` | 7 |
| `tests/rag/test_rrf_fusion.py` | 4 |
| `tests/rag/test_rerankers.py` | 5 |
| `tests/rag/test_query_rewriter_multi.py` | 8 |
| `tests/rag/test_rewrite_client.py` | 10 |
| `tests/rag/test_vector_store_preload.py` | 7 |
| `tests/eval/test_retrieval_metrics.py` | 13 |
| `tests/eval/test_retrieval_runner.py` | 2 |
| `tests/core/test_cache.py` | 10 |

**总计 72 新增单测，零 integration regression。**

---

## 不在 Phase 2 范围（明确记录）

| 项 | 推迟到 |
|---|---|
| `llm/client.py` (answer generation) fail-fast | Phase 3 或 Phase 4 |
| Query engine 接入 multi-query fusion（LLM variants + HyDE 真接到 retrieval） | 下一个 sprint |
| 缓存真接入 embedding/retrieval/answer 三个路径 | 下一个 sprint（接入动作是零风险增强，可随时做） |
| 实际 benchmark 标注数据集（50-100 条真标注） | 下一个 sprint |
| Milvus Lite 集成测试（替代 noop vector store） | 下一个 sprint |

**"接入"类工作**（P2.5 runner 接 /api/evals/retrieval-runs / P2.7 cache 装饰 embedding/answer / P2.6 query_engine 用 multi-query）**组件都已就位**，只差"在 service 层插入调用"—— 这是低风险连接工作，可以按需滚动完成，不阻塞 Phase 3 启动。

---

## 下一步建议

1. **先 review Phase 2**（推荐）—— 同 Phase 1 review 节奏，确认 72 新测试 + 9 改造点符合预期
2. **或**跳 Phase 3（Async 化 / 可观测性 / K8s 部署 —— 见规划文档）
3. **或**做"接入冲刺"：把 P2.5/P2.6/P2.7 的组件真插到 `query_engine.py` / `embedding_client.py` / `/api/evals/retrieval-runs` 里
