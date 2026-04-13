# Travel Ops Copilot 架构与流程评审

> 生成时间：2026-04-07
> 范围：backend / database / RAG / agents 四大板块
> 目的：工程评审 + 架构可视化，作为迭代路线图的基线文档

---

## 一、总体评分

**综合：5.0 / 10**（原型 → 早期 MVP 之间）

| 维度 | 分数 | 备注 |
|---|---|---|
| 架构分层 | 7 | routes → schemas → services → db 划分清晰 |
| 数据库设计 | 6 | ORM 规范，但缺迁移、缺约束、JSON 列滥用 |
| RAG 实现 | 5.5 | 混检 + rerank 思路对，但 embedding 是哈希假实现 |
| Agent 框架 | 3.5 | 关键词路由 + 大量硬编码，几乎没有真正的 agent loop |
| API / 安全 | 4 | Bearer Token 静态映射，租户隔离仅在应用层 |
| 可观测性 | 4 | JSON log + Prometheus 起步，无 tracing / 无审计 |
| 测试 | 4 | SQLite + noop vector store，没真集成测试 |
| 异步 / 扩展性 | 3 | 全同步、无缓存、`init_db` + `seed_default_rules` 每次请求都跑 |

**一句话总结**：思路是企业级的，实现是 demo 级的。把 embedding、agent loop、鉴权、迁移、async、tracing 这六块补齐后，再谈 production。当前状态适合作为内部 PoC 演示，不适合接真实业务流量。

---

## 二、后端核心问题

### 1. `app/db/session.py` 的 Session 工厂代理

```python
class _SessionLocalProxy:
    def __call__(self) -> Session:
        if engine != _session_factory.kw["bind"]:
            raise RuntimeError("session factory bind drift detected")
```

- 代理 + 断言的写法是为了对付测试 monkeypatch，**生产里完全没必要**
- 启动时 `Base.metadata.create_all()` 建表，**没有 Alembic 迁移** —— 企业级红线问题之一

### 2. `agents.py` 路由里每次请求都跑

```python
init_db()
seed_default_rules(session)
```

这两行该在 app startup 一次性执行，现在每个 `POST /api/agents/runs` 都重复，**纯属性能浪费 + 写库竞争**。

### 3. 没有 async / await

FastAPI 的 IO 优势完全没用上，RAG / LLM / Milvus / MinIO 全部 sync 调用，**单 worker 吞吐很差**。

### 4. 安全 / 多租户

- `core/security.py` 是 token → 角色 的内存字典，**没有过期、签名、撤销、审计**
- `tenant_id` / `customer_id` 完全由前端传入，**后端不校验请求 token 是否有权访问该租户** —— 这是企业项目最常见也最危险的越权漏洞
- `auth_enabled=false` 时直接给 admin 权限，dev 默认值 `admin-token` 一旦配置疏漏就是后门

### 5. 错误处理几乎为 0

- 没有自定义异常体系，没有 4xx / 5xx 区分
- LLM 客户端 `response.raise_for_status()` 后没有重试、降级、熔断
- ingestion pipeline 一个大 try / except 包住整流程，**根因被吞掉**

---

## 三、数据库层不合理点

1. **没有 Alembic**，schema 改动只能靠 drop & recreate
2. **JSON 列滥用**：`metadata_json / input_json / output_json / timeline_json / payload_json / samples_json / metrics_json` 一堆，能结构化的都塞 JSON，将来没法索引、没法做分析、没法 evolve schema
3. **缺 FK 约束**：`EvalRun.dataset_id` / `ReviewCase` 关联字段都没真正的外键，仅靠应用层约束
4. **没有软删除、没有版本字段、没有 audit 表**，企业级合规审计无从谈起
5. **多租户隔离仅在应用层**，没有 PostgreSQL RLS 或 schema 级隔离，违反 defense in depth
6. SQLAlchemy 用 sync session，对应 FastAPI 应该用 `AsyncSession`

---

## 四、RAG 部分的硬伤

### 1. `embedding_client.py` 的"确定性 embedding"是哈希分桶

```python
digest = hashlib.sha256(token.encode("utf-8")).digest()
bucket = int.from_bytes(digest[:4], "big") % dimension
vector[bucket] += 1.0
```

这**根本不是 embedding**，等价于一个稀疏 BoW + L2 normalize，**没有任何语义相似度能力**。但它是 default 行为，意味着没配 OpenAI 时整个 dense retrieval 是假的。测试套件依赖这个，导致 RAG 测试通过 ≠ RAG 真的好。

### 2. `vector_store.py` 的 Milvus 集成

- `collection.load()` 每次 search 都调一遍，Milvus 大忌，应该启动时 load 一次
- filter 表达式拼字符串，即使有 escape，**Milvus 表达式注入**风险仍在
- 索引硬编码 `AUTOINDEX`，没暴露 IVF / HNSW 参数
- `NoopVectorStore` 静默返回空，**生产配置错了不会报错**，只是检索不到东西

### 3. `query_rewriter.py` 是手写同义词表

```python
ALIAS_RULES = (
    ("住宿别名", ("住宿","住宿标准","hotel"), ("酒店","报销上限","住宿标准")),
    ...
)
```

三条规则，**完全不可扩展**。没有 LLM 改写、没有 HyDE、没有 multi-query。

### 4. `retrievers.py` 的混合检索

- 权重 `0.65 dense / 0.35 lexical` 硬编码
- 没有 RRF (Reciprocal Rank Fusion) 这种工业界标准融合方案
- lexical 走 SQL 全表加载到 Python 里算分，**不能 scale**

### 5. `query_engine.py` 的回退链

hybrid → vector → lexical，回退是静默的，**用户和日志都不知道用了哪条**，离线分析和 debug 极困难。confidence 阈值在代码里写死。

### 6. 缺失项

- 没有真正的 reranker（Cohere / bge-reranker）
- 没有 chunk overlap 策略可调、没有 semantic chunking
- 没有 retrieval evaluation（recall@k / nDCG），只有最末端的 substring 匹配
- 没有 query / answer 缓存

---

## 五、Agent 部分（最弱）

### 1. 这不是 Agent，是 if-else 路由 + 写死结果

```python
# anomaly_graph.py
return AgentExecutionResult(
    agent_name="order_anomaly_agent",
    confidence=0.74,                 # 写死
    output={"queue_name":"ops-review","reason":"异常订单类问题..."},
)
```

异常分析 agent **完全没看输入**，直接返回常量。`ticket_router` 的 confidence=0.86 也是常量。

### 2. `router.py` 用关键词匹配选 agent

- 没有 LLM 路由、没有 embedding 路由、没有 fallback
- 改 agent 必须改代码，**没有注册中心**

### 3. 没有真正的 agent loop

所有 graph 都是"调一次工具 → 返回"，**不存在 ReAct / Plan-and-Execute / 多步推理**。`graph.py` 起的名字让人误以为是 state machine，实际是顺序调用。

### 4. 工具系统是 mock

`tools.py` 里 `lookup_order_details()` 直接返回硬编码 sandbox 数据，**没有外部 API 调用**，没有 schema 校验、没有重试、没有超时。

### 5. 缺失项

- 无 agent memory（短期 / 长期）
- 无 human-in-the-loop 中断 / 恢复
- 无 token / cost 统计
- 无 trace export（OTEL / LangSmith / Phoenix）
- 无 guardrails（输入 / 输出过滤、PII 脱敏、prompt injection 检测）

---

## 六、最该优先修的"明显不合理"实现

1. `agents.py` 路由里调用 `init_db()` + `seed_default_rules()` → 移到 lifespan startup
2. `_SessionLocalProxy` 的 drift 断言 → 删掉
3. `DeterministicPolicyAnswerClient` 默认开启 → 改成只在测试 fixture 启用，生产缺失应**直接报错**
4. `seed_default_rules` 在请求路径上 → 改 startup 或 migration data seed
5. JSON 列里的 `timeline_json / tool_calls` → 抽出独立表
6. Milvus `collection.load()` per query → 启动时 load
7. 关键词路由 + 关键词同义词 → 至少接一个轻量 LLM 做意图分类 + query rewrite
8. `auth_enabled=false → admin` → 改成"未鉴权时拒绝所有写操作"
9. `tenant_id` 由 body 传入未校验 → 改成从 token claim 推断
10. 评估指标 substring 匹配 → 加 LLM-as-judge 或 embedding similarity

---

## 七、距离真正企业级的差距清单（按重要性）

**P0（不补就上不了生产）**
- Alembic 迁移
- 真 embedding 模型
- 真鉴权（JWT + RBAC + tenant claim）
- 全链路 tracing
- 错误体系与重试熔断
- 真集成测试（Testcontainers 起 PG + Milvus + MinIO）

**P1（决定能不能扩展）**
- async / await 改造
- Redis 缓存（embedding、检索、答案）
- 任务真异步（Celery 不要 eager）
- Milvus 索引参数与 partition
- 多租户 DB 级隔离

**P2（决定能不能运营）**
- prompt 版本管理 + A/B + 在线评估
- retrieval recall@k 离线评测
- agent trace export
- cost & token 统计
- 审计日志 + 数据脱敏

**P3（决定团队能不能维护）**
- OpenAPI 客户端生成
- 类型化的 timeline 事件
- Pre-commit + ruff / mypy strict
- Dockerfile + Helm
- SLO 与告警

---

## 八、整体架构图

```mermaid
flowchart TB
    subgraph Client["前端 React + Vite"]
        UI_Chat[ChatPage]
        UI_Know[KnowledgePage]
        UI_Agent[AgentRunsPage]
        UI_Review[ReviewQueuePage]
        UI_Prompt[PromptTemplatesPage]
        UI_Eval[EvalPage]
    end

    subgraph API["FastAPI 后端"]
        direction TB
        MW[CORS / Auth / Metrics 中间件]
        subgraph Routes["api/routes"]
            R_Chat[chat.py]
            R_Know[knowledge.py]
            R_Agent[agents.py]
            R_Rule[rules.py]
            R_Prompt[prompt_templates.py]
            R_Review[reviews.py]
            R_Eval[evals.py]
        end
        Deps[deps.py RequestContext]
        Sec[core/security.py Bearer Token to Role]
    end

    subgraph Services["services 业务层"]
        direction TB
        subgraph RAG["rag/"]
            QE[query_engine]
            QR[query_rewriter]
            RET[retrievers hybrid/dense/lexical]
            RER[rerankers]
            EMB[embedding_client]
            VS[vector_store]
            CIT[citation_service]
        end
        subgraph Agents["agents/"]
            ROUTER[router 关键词匹配]
            GRAPH[graph 调度]
            PG[policy_graph]
            TG[ticket_router_graph]
            AG[anomaly_graph]
            TOOLS[tools mock]
        end
        subgraph Other["其它服务"]
            ING[ingestion pipeline]
            LLM[llm/client Deterministic or OpenAI]
            RULE[rules/engine]
            PROMPT[prompts/service]
            EVAL[eval/runner]
        end
    end

    subgraph Infra["基础设施"]
        PG_DB[(PostgreSQL SQLAlchemy)]
        MILVUS[(Milvus 向量库)]
        MINIO[(MinIO 对象存储)]
        CELERY[Celery Worker]
        METRICS[Prometheus /metrics]
        LLMAPI[外部 LLM API 可选]
    end

    Client -->|HTTPS JSON| MW
    MW --> Sec --> Deps --> Routes

    R_Chat --> QE
    R_Know --> ING
    R_Agent --> GRAPH
    R_Rule --> RULE
    R_Prompt --> PROMPT
    R_Review --> PG_DB
    R_Eval --> EVAL

    GRAPH --> ROUTER
    ROUTER --> PG
    ROUTER --> TG
    ROUTER --> AG
    PG --> QE
    TG --> TOOLS
    AG --> TOOLS

    QE --> QR --> RET
    RET --> VS
    RET --> PG_DB
    RET --> RER --> CIT
    QE --> PROMPT
    QE --> LLM
    VS --> EMB
    EMB --> LLMAPI
    LLM --> LLMAPI

    ING --> MINIO
    ING --> PG_DB
    ING --> VS
    ING --> CELERY

    EVAL --> QE
    EVAL --> PG_DB
    RULE --> PG_DB
    PROMPT --> PG_DB

    Routes --> METRICS
```

---

## 九、RAG 问答流程（POST /api/chat/ask）

```mermaid
sequenceDiagram
    autonumber
    actor U as 用户
    participant FE as ChatPage
    participant API as chat.py
    participant QE as query_engine
    participant QR as query_rewriter
    participant RET as retrievers
    participant VS as Milvus
    participant DB as PostgreSQL
    participant RER as reranker
    participant PS as prompt service
    participant LLM as llm client

    U->>FE: 输入问题
    FE->>API: POST /api/chat/ask
    API->>API: Bearer Token 鉴权
    API->>QE: answer_policy_question()

    QE->>QR: rewrite_query(question)
    QR-->>QE: 扩展后的 query 同义词表

    QE->>RET: hybrid_search()
    RET->>VS: dense 向量检索
    VS-->>RET: top-k chunk_id
    RET->>DB: lexical SQL 检索
    DB-->>RET: 候选 chunks
    RET->>RET: 融合打分 0.65/0.35
    alt 命中不足
        RET->>VS: 仅 dense 回退
    end
    alt 仍无结果
        RET->>DB: 仅 lexical 回退
    end
    RET-->>QE: 候选列表

    QE->>RER: rerank()
    RER-->>QE: 重排 + citations

    alt confidence 低于阈值
        QE-->>API: 置信度过低 需人工复核
    else
        QE->>PS: 取 active prompt
        PS-->>QE: prompt 模板
        QE->>LLM: generate_answer evidence
        LLM-->>QE: AnswerDraft
    end

    QE-->>API: 答案 + citations + confidence
    API->>DB: 写 ChatSession / ChatMessage / RagRecallLog
    API-->>FE: 200 JSON
    FE-->>U: 渲染答案与引用
```

---

## 十、Agent 执行流程（POST /api/agents/runs）

```mermaid
flowchart TB
    Start([POST /api/agents/runs]) --> Auth[鉴权 admin/operator]
    Auth --> InitBad[init_db + seed_default_rules 每次请求都跑]
    InitBad --> Route[router.choose_route 关键词匹配]

    Route -->|含 ticket 或 工单关键词| TRoute[ticket_router_agent]
    Route -->|含 异常/退款关键词| ARoute[order_anomaly_agent]
    Route -->|默认| PRoute[travel_policy_agent]

    subgraph Policy["policy_graph"]
        PRoute --> P1[调用 RAG query_engine]
        P1 --> P2{confidence 大于等于阈值?}
        P2 -->|是| PDone[status=completed]
        P2 -->|否| PReview[status=needs_review]
    end

    subgraph Ticket["ticket_router_graph"]
        TRoute --> T1[invoke_tool ticket_queue_lookup]
        T1 --> T2[invoke_tool order_lookup mock]
        T2 --> T3[硬编码 confidence=0.86]
    end

    subgraph Anomaly["anomaly_graph"]
        ARoute --> A1[完全不看输入]
        A1 --> A2[硬编码 confidence=0.74]
    end

    PDone --> Rule
    PReview --> Rule
    T3 --> Rule
    A2 --> Rule

    Rule{payload 含 ticket?}
    Rule -->|是| RE[rules/engine evaluate_rules]
    RE --> ReviewChk
    Rule -->|否| ReviewChk

    ReviewChk{需要人工复核?}
    ReviewChk -->|是| CR[create_review_case]
    ReviewChk -->|否| Save
    CR --> Save

    Save[写 AgentRun + ToolCallLog]
    Save --> Resp([201 AgentRunPayload])
```

---

## 十一、知识库 ingestion 流程（POST /api/knowledge/upload）

```mermaid
sequenceDiagram
    autonumber
    actor U as 用户
    participant FE as KnowledgePage
    participant API as knowledge.py
    participant OS as MinIO
    participant DB as PostgreSQL
    participant CEL as Celery Task
    participant PRS as parser
    participant CHK as chunker
    participant EMB as embedding_client
    participant VS as Milvus

    U->>FE: 上传 PDF / DOCX / MD
    FE->>API: POST /api/knowledge/upload multipart
    API->>OS: put_object file
    OS-->>API: storage_key
    API->>DB: INSERT KnowledgeDocument status=pending
    API->>CEL: enqueue run_ingestion_job doc_id
    API-->>FE: 202 job_id

    Note over CEL: CELERY_TASK_ALWAYS_EAGER=true 实际同步执行
    CEL->>DB: status=processing
    CEL->>OS: read storage_key
    OS-->>CEL: file bytes
    CEL->>PRS: parse_document
    PRS-->>CEL: ParsedDocument
    CEL->>CHK: chunk_document
    CHK-->>CEL: chunks

    loop 每个 chunk
        CEL->>EMB: embed text
        EMB-->>CEL: vector
    end

    CEL->>DB: INSERT KnowledgeChunk
    CEL->>VS: upsert vectors
    VS-->>CEL: vector_ids
    CEL->>DB: UPDATE chunk.vector_id
    CEL->>DB: status=completed

    alt 任意步骤异常
        CEL->>DB: status=failed + error_message
    end

    FE->>API: GET /api/knowledge/jobs 轮询
    API->>DB: 查状态
    API-->>FE: completed / failed
```

---

## 十二、规则引擎 + 人工复核流程

```mermaid
flowchart LR
    subgraph Input["输入"]
        TK[Ticket payload 金额 城市 类型]
    end

    TK --> INF[city_tier 推断 硬编码 map]
    INF --> LOAD[加载 DEFAULT_RULES 硬编码 3 条]

    LOAD --> MATCH{逐条匹配 expense_type city_tier amount}
    MATCH -->|无命中| APV[decision=approved]
    MATCH -->|命中 threshold| BLK[decision=blocked + RuleHit 列表]

    APV --> OUT[RuleEvaluationResult]
    BLK --> OUT

    OUT --> DEC{agent confidence 低或 rule=blocked?}
    DEC -->|是| RC[create_review_case 写 ReviewCase 表]
    DEC -->|否| END1([直接返回])

    RC --> Q[review queue]
    Q --> Human[reviewer 角色 GET /api/reviews/queue]
    Human --> Decide[人工决策]
    Decide --> END2([更新 case 状态])
```

---

## 十三、评估流程（POST /api/evals/runs）

```mermaid
sequenceDiagram
    autonumber
    participant API as evals.py
    participant Runner as eval/runner
    participant DB as PostgreSQL
    participant QE as query_engine

    API->>Runner: run_eval dataset_id
    Runner->>DB: SELECT EvalDataset
    DB-->>Runner: samples_json

    loop 同步遍历 每个 sample
        Runner->>QE: answer_policy_question q tenant customer
        QE-->>Runner: answer + citations + confidence
        Runner->>Runner: citation substring 匹配 answer 关键词匹配
        Runner->>Runner: 累加命中计数
    end

    Runner->>Runner: 计算 answer_correctness citation_hit_rate low_confidence_rate
    Runner->>DB: INSERT EvalRun metrics_json
    Runner-->>API: EvalRun
    API-->>Client: 200
```

---

## 十四、数据库 ER 简图

```mermaid
erDiagram
    ChatSession ||--o{ ChatMessage : has
    KnowledgeDocument ||--o{ KnowledgeChunk : has
    AgentRun ||--o{ ToolCallLog : logs
    EvalDataset ||--o{ EvalRun : produces
    PromptTemplate ||--o{ AgentRun : uses
    PolicyRule }o--o{ ReviewCase : triggers

    ChatSession {
        uuid id PK
        string tenant_id
        string customer_id
        datetime created_at
    }
    ChatMessage {
        uuid id PK
        uuid session_id FK
        string role
        text content
        json metadata_json
    }
    KnowledgeDocument {
        uuid id PK
        string filename
        string status
        int chunk_count
        string parser_name
    }
    KnowledgeChunk {
        uuid id PK
        uuid document_id FK
        int chunk_index
        string title
        text content
        string vector_id
    }
    AgentRun {
        uuid id PK
        string agent_name
        string route_name
        string status
        float confidence
        json timeline_json
    }
    ToolCallLog {
        uuid id PK
        uuid agent_run_id FK
        string tool_name
        string status
        int latency_ms
        json input_json
        json output_json
    }
    PromptTemplate {
        uuid id PK
        string name
        string task_type
        int version
        string status
        text template
    }
    PolicyRule {
        uuid id PK
        string rule_code
        string expense_type
        string city_tier
        float threshold_amount
        string decision_on_exceed
    }
    ReviewCase {
        uuid id PK
        string source
        string tenant_id
        json payload_json
        json rule_result_json
        string status
    }
    EvalDataset {
        uuid id PK
        string name
        json samples_json
    }
    EvalRun {
        uuid id PK
        uuid dataset_id
        json metrics_json
        json details
    }
    RagRecallLog {
        uuid id PK
        string question
        json retrievals_json
        float top_score
    }
```

---

## 十五、请求总生命周期（跨层视角）

```mermaid
flowchart LR
    A[HTTP Request] --> B[CORS]
    B --> C[Metrics 计数 + 计时]
    C --> D[get_auth_context Bearer to Role]
    D --> E[get_request_context tenant/customer/request_id]
    E --> F[get_session SQLAlchemy Session]
    F --> G[Route Handler]
    G --> H[Pydantic 校验]
    H --> I[调用 Service 层]
    I --> J[DB / Milvus / MinIO / LLM]
    J --> K[ORM commit]
    K --> L[Pydantic 响应序列化]
    L --> M[JSON Log 输出]
    M --> N[HTTP Response]
```

> 红色风险点：`D`（静态 token 映射）是目前最弱的一环
> 绿色亮点：`I`（Service 层）是架构上最成熟的一环

---

## 十六、值得肯定的地方

- **分层与文件命名是工业级风格**，不是教程式的一坨 `main.py`
- 想到了 RAG 的 query rewrite / hybrid / rerank / citation / confidence / human review 这条完整链路（思路对，落地差）
- 想到了 prompt 模板表、规则引擎表、eval 数据集表、review 队列表，**领域建模有 sense**
- Pydantic + 类型注解 + frozen dataclass 用得还行

---

## 十七、后续迭代建议（下一个 Sprint 可交付）

最小闭环改造，一周内可落地：

1. **Embedding 真实化**：接入 `text-embedding-3-small` 或本地 `bge-m3`，保留 deterministic 作为 test fixture
2. **Lifespan 修复**：`init_db` + `seed_default_rules` 移入 FastAPI lifespan
3. **租户校验**：`get_request_context` 里强制 `tenant_id` 来自 token claim，body 里的仅作一致性校验
4. **Alembic 接入**：生成首次 baseline migration，禁用 `create_all`
5. **Async 改造起步**：`chat.py` + `query_engine.py` 先异步化，其它保持同步
6. **Agent 真 loop**：引入 `langgraph` 或自写最小 ReAct，把 `anomaly_graph` 从硬编码改成真推理

完成这 6 项后，评分应该能从 5.0 提到 6.5 左右。

---

*文档由 Claude 基于 `backend/` 源码全量静态分析生成，供团队工程评审与迭代规划使用。*
