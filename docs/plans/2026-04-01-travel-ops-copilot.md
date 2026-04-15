# 差旅智能运营 Copilot 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**目标：** 构建一个面向企业差旅场景的全新 AI 智能运营平台，第一阶段先交付带引用的政策问答能力，随后逐步扩展到混合检索、Agent 工作流、规则约束与工程化部署能力。

**架构：** 初期采用模块化单体架构：一个 FastAPI API 服务、一个异步 Worker 进程、一个 React 管理端，并共享 PostgreSQL + Milvus + Redis + MinIO。RAG 主链路由 LlamaIndex 驱动，Agent 工作流由 LangGraph 编排。核心原则是先把文档入库与检索问答做成稳定闭环，再在稳定数据层之上叠加工具调用 Agent 和规则引擎。

**技术栈：** FastAPI、Pydantic、SQLAlchemy、PostgreSQL、Milvus、PyMilvus、LlamaIndex、LangGraph、Redis、Celery、MinIO、LiteLLM 或其他兼容 OpenAI 的模型网关、React + Vite + Ant Design、TanStack Query、Docker Compose、Kubernetes、OpenTelemetry、Prometheus/Grafana

---

## 前提假设

- 这是一个从 0 到 1 的新项目，既要适合面试演示，也要保持真实企业内部平台的组织方式。
- 第一条业务主线聚焦内部运营人员使用的差旅政策问答。
- 订单异常处理、工单分流、审核辅助、邮件场景都放在 RAG 基线稳定之后。
- 第一版目标规模约为 50 到 100 个并发内部用户，而不是公网大流量系统。
- 系统从第一天起就要支持租户和客户隔离，因此所有业务核心表都应保留 `tenant_id` 和 `customer_id`。

## 需求摘要

### 功能需求

- 上传并管理差旅制度、客户合同、FAQ、SOP 和帮助中心等文档。
- 将 DOCX、PDF、XLSX、HTML 和邮件类内容解析为标准化知识记录。
- 按块切分内容，并保留租户、客户、文档类型、生效时间、版本号、访问控制等元数据。
- 必须支持中文文档、中文问题和中英混合问题的检索与问答，不能长期依赖只适配英文 token 的占位实现。
- 生成向量并保存知识分块，支持查看文档处理状态。
- 回答政策问题时必须返回引用、命中文本片段和置信度分数。
- 持久化会话记录、Prompt 模板、检索链路、Agent 运行过程和人工反馈。
- 在 Agent 能力之前先补齐混合检索、Rerank 和离线评测。
- 增加 Query Router、订单异常分析、工单分流和确定性规则校验。
- 对低置信度或高风险结果提供人工审核队列。

### 非功能需求

- 政策问答接口在热启动状态下 p95 延迟小于 8 秒。
- 单次含一个工具调用的 Agent 工作流 p95 延迟小于 15 秒。
- 50 页文档的异步入库处理 SLA 控制在 2 分钟内。
- 内部平台可用性目标为 99.9%。
- 可观测性要求：每次请求都必须记录结构化日志、链路追踪、模型用量和检索证据。
- 评测要求：混合检索与问答评测集必须覆盖中文政策问题、中文文档和中英混合问法，不能只验证英文样例。
- 安全要求：管理端必须鉴权、支持基于角色的权限控制、租户隔离、传输加密、日志脱敏。
- 可靠性要求：低置信度答案不能直接给出最终决策，前端必须能展示兜底或升级处理路径。

## 架构概览

```text
                +------------------------------+
                |  React Admin / Internal UI   |
                +--------------+---------------+
                               |
                               v
                    +----------+-----------+
                    | FastAPI API Gateway  |
                    | auth, routing, logs  |
                    +----+--------+--------+
                         |        |
            +------------+        +----------------------+
            |                                            |
            v                                            v
 +----------+-----------+                    +-----------+------------+
 | RAG Flow (LlamaIndex)|                    | Agent Flow (LangGraph) |
 | upload, retrieve, QA |                    | state, tool, handoff   |
 +----+---------+-------+                    +------+----------+------+
      |         |                                   |          |
      v         v                                   v          v
 +----+--+  +---+-------------+  +----------------+     +----------+--+  +----+----------+
 | MinIO |  | PostgreSQL      |  | Milvus         |     | Rule Engine |  | Tool Adapters  |
 | files |  | metadata/logs   |  | vectors/search |     | policy/SLA  |  | order/ticket   |
 +-------+  +---+-------------+  +----------------+     +-------------+  +---------------+
               |
               v
         +-----+------+
         | Redis      |
         | cache/queue|
         +-----+------+
               |
               v
         +-----+------+
         | Celery     |
         | ingestion  |
         | eval jobs  |
         +------------+
```

## 关键决策与取舍

| 决策 | 原因 | 代价 / 取舍 |
| --- | --- | --- |
| 先做模块化单体 | 最快形成可运行 MVP，调试成本最低，也更适合单人推进 | 横向拆分和独立扩缩容能力不如微服务 |
| 向量库使用 Milvus，PostgreSQL 只保留业务数据与日志 | 更符合企业级 RAG 的角色分层，向量检索可独立扩展，后续更容易演进到大规模检索 | 本地开发和部署链路比 pgvector 更复杂 |
| RAG 主链路使用 LlamaIndex | 更适合文档接入、节点切分、索引构建、Query Engine 和引用式问答 | 需要理解框架抽象，并控制好自定义扩展边界 |
| Agent 编排使用 LangGraph，而不是直接依赖 LangChain 高层 Agent | 更适合有状态、多节点、可回溯、可人工介入的工作流 | 编排代码更显式，初期样板会更多 |
| 使用 Celery 做异步入库与评测 | 文档解析和向量生成不应阻塞 API 请求线程 | 增加 Worker 和队列的运维复杂度 |
| 先做 RAG 再做 Agent | 如果检索基线不稳定，后续所有 Agent 看起来都会不可信 | Agent 相关里程碑会顺延 |
| 规则引擎对阈值和策略边界拥有最终裁决权 | 防止 LLM 在确定性业务规则上产生幻觉 | 需要单独维护规则配置与测试体系 |
| 模型接入层采用 OpenAI 兼容抽象 | 保留模型路由与供应商切换能力，更符合企业网关思路 | 需要额外维护一层适配封装 |

## 建议的仓库结构

```text
backend/
  pyproject.toml
  alembic.ini
  app/
    main.py
    core/
      config.py
      logging.py
      security.py
    api/
      deps.py
      routes/
        health.py
        knowledge.py
        chat.py
        prompt_templates.py
        agents.py
        rules.py
        reviews.py
        evals.py
    db/
      base.py
      session.py
      models/
        knowledge.py
        conversation.py
        prompt_template.py
        agent.py
        rule.py
        eval.py
    schemas/
      knowledge.py
      chat.py
      agent.py
      rule.py
      eval.py
    services/
      llm/
        client.py
      ingestion/
        loader.py
        parser.py
        chunker.py
        pipeline.py
      rag/
        settings.py
        index_builder.py
        vector_store.py
        query_engine.py
        retrievers.py
        rerankers.py
        citation_service.py
      prompts/
        service.py
      agents/
        state.py
        router.py
        graph.py
        nodes.py
        policy_graph.py
        anomaly_graph.py
        ticket_router_graph.py
        tools.py
      rules/
        engine.py
      eval/
        dataset_loader.py
        runner.py
    workers/
      celery_app.py
      tasks.py
  tests/
    api/
    ingestion/
    rag/
    agents/
    rules/
    eval/

frontend/
  package.json
  vite.config.ts
  src/
    main.tsx
    app/
      App.tsx
      router.tsx
      providers.tsx
    api/
      client.ts
      knowledge.ts
      chat.ts
      prompts.ts
      agents.ts
      reviews.ts
      evals.ts
    pages/
      DashboardPage.tsx
      KnowledgePage.tsx
      ChatPage.tsx
      PromptTemplatesPage.tsx
      EvalPage.tsx
      AgentRunsPage.tsx
      ReviewQueuePage.tsx
    components/
      DocumentUploader.tsx
      CitationPanel.tsx
      RetrievalTraceDrawer.tsx
      ConfidenceBadge.tsx
      RuleResultPanel.tsx
      RunTimeline.tsx
    tests/

infra/
  docker/
    backend.Dockerfile
    frontend.Dockerfile
  k8s/
    api-deployment.yaml
    worker-deployment.yaml
    web-deployment.yaml
    postgres-statefulset.yaml
    redis-deployment.yaml
    minio-deployment.yaml
    etcd-deployment.yaml
    milvus-deployment.yaml
    ingress.yaml
  monitoring/
    prometheus.yaml
    grafana-dashboards.json

docs/
  plans/
  adrs/
```

## 数据模型范围

- `knowledge_document`：源文件元数据、版本、租户、客户、ACL、解析状态。
- `knowledge_chunk`：分块文本、向量引用、可检索文本、章节路径、所属文档。
- `chat_session` 和 `chat_message`：会话状态与问答历史。
- `rag_recall_log`：召回候选、打分、Rerank 结果、最终上下文和耗时。
- `prompt_template`：Prompt 模板版本及启用状态。
- `agent_run`：Agent 名称、输入、状态流转、最终输出和置信度。
- `tool_call_log`：工具名、参数、脱敏结果、耗时和状态。
- `policy_rule`：确定性策略阈值与规则表达式。
- `ticket_case` 和 `ticket_route_result`：后续阶段工单分流输入输出。
- `audit_result`：发票或报销审核结果及规则命中情况。
- `feedback_label`：人工纠正与反馈标签，用于后续优化。
- `eval_dataset` 和 `eval_run`：离线评测题集和评测结果指标。

## 里程碑顺序

1. 初始化仓库、搭建本地运行环境、补齐鉴权占位和健康检查。
2. 交付文档上传、解析、切块、向量化和索引入库。
3. 交付带引用和置信度的政策问答及会话日志。
4. 增加 Prompt 管理、检索链路追踪和基础可观测性。
5. 增加混合检索、Rerank 和离线评测。
6. 增加 Query Router 和一到两个工具型 Agent。
7. 增加规则引擎和人工审核队列。
8. 完成容器化、Kubernetes 清单、监控告警和发布控制。
9. 增加真实模型网关接入，并保留 deterministic 本地回退链路。

## 实施任务

### 任务 1：搭建项目脚手架与本地运行环境

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/main.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/app/api/routes/health.py`
- Create: `backend/tests/api/test_health.py`
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/app/App.tsx`
- Create: `frontend/tests/app/App.test.tsx`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `Makefile`

**步骤 1：先写失败的后端与前端冒烟测试**

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_healthcheck_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

```tsx
import { render, screen } from "@testing-library/react";
import App from "../../src/app/App";

test("renders app shell title", () => {
  render(<App />);
  expect(screen.getByText("Travel Ops Copilot")).toBeInTheDocument();
});
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/api/test_health.py -v`
Expected: FAIL because `app.main` and `/health` do not exist.

Run: `cd frontend && pnpm test App.test.tsx`
Expected: FAIL because `App.tsx` does not exist.

**步骤 3：写最小实现**

- 建立带 `/health` 的 FastAPI 应用工厂。
- 增加结构化日志和基于环境变量的配置读取。
- 创建一个只有基础导航占位的 React 壳页面。
- 在 Docker Compose 中加入 PostgreSQL、Redis、MinIO、Etcd 和 Milvus 服务。

**步骤 4：运行验证**

Run: `docker compose up -d postgres redis minio etcd milvus`
Expected: all five dependencies become healthy.

Run: `cd backend && uv run pytest tests/api/test_health.py -v`
Expected: PASS.

Run: `cd frontend && pnpm test App.test.tsx`
Expected: PASS.

**步骤 5：提交**

```bash
git add .env.example Makefile docker-compose.yml backend frontend
git commit -m "chore: scaffold travel ops copilot"
```

### 任务 2：构建知识库入库链路

**Files:**
- Create: `backend/app/api/routes/knowledge.py`
- Create: `backend/app/db/models/knowledge.py`
- Create: `backend/app/schemas/knowledge.py`
- Create: `backend/app/services/ingestion/loader.py`
- Create: `backend/app/services/ingestion/parser.py`
- Create: `backend/app/services/ingestion/chunker.py`
- Create: `backend/app/services/ingestion/pipeline.py`
- Create: `backend/app/services/rag/settings.py`
- Create: `backend/app/services/rag/index_builder.py`
- Create: `backend/app/services/rag/vector_store.py`
- Create: `backend/app/workers/celery_app.py`
- Create: `backend/app/workers/tasks.py`
- Create: `backend/tests/ingestion/test_pipeline.py`
- Create: `backend/tests/api/test_knowledge_upload.py`
- Create: `frontend/src/api/knowledge.ts`
- Create: `frontend/src/components/DocumentUploader.tsx`
- Create: `frontend/src/pages/KnowledgePage.tsx`

**步骤 1：先写失败测试**

```python
def test_docx_ingestion_persists_document_and_chunks(session, docx_file):
    job_id = start_ingestion(session=session, file=docx_file, tenant_id="t1", customer_id="c1")
    result = wait_for_job(job_id)
    assert result.status == "completed"
    assert result.chunk_count > 0
```

```python
def test_upload_endpoint_returns_job_id(client, docx_file):
    response = client.post("/api/knowledge/upload", files={"file": ("policy.docx", docx_file)})
    assert response.status_code == 202
    assert "job_id" in response.json()
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/ingestion/test_pipeline.py tests/api/test_knowledge_upload.py -v`
Expected: FAIL because ingestion services and API do not exist.

**步骤 3：写最小实现**

- 将原始文件上传到 MinIO，并落一条 `knowledge_document` 记录。
- 第一阶段先支持 DOCX 和 PDF 解析，XLSX 与 HTML 等格式后置。
- 按标题层级切块，保留重叠窗口和元数据透传。
- 通过 Celery 异步生成 embeddings，用 LlamaIndex 组织 node 构建并写入 Milvus。
- 在 PostgreSQL 中保存 chunk、文档元数据与向量主键映射。
- API 返回上传状态和入库任务历史。
- 管理端新增一个基础上传页和任务状态表格。

**步骤 4：运行验证**

Run: `cd backend && uv run pytest tests/ingestion/test_pipeline.py tests/api/test_knowledge_upload.py -v`
Expected: PASS.

Run: `cd backend && uv run pytest -k knowledge -v`
Expected: PASS for all ingestion-related tests.

**步骤 5：提交**

```bash
git add backend/app/api/routes/knowledge.py backend/app/services/ingestion backend/app/services/rag backend/app/workers backend/tests frontend/src/api/knowledge.ts frontend/src/components/DocumentUploader.tsx frontend/src/pages/KnowledgePage.tsx
git commit -m "feat: add knowledge ingestion pipeline"
```
### 任务 3：交付带引用的政策问答与会话日志

**Files:**
- Create: `backend/app/api/routes/chat.py`
- Create: `backend/app/db/models/conversation.py`
- Create: `backend/app/schemas/chat.py`
- Create: `backend/app/services/llm/client.py`
- Create: `backend/app/services/rag/query_engine.py`
- Create: `backend/app/services/rag/citation_service.py`
- Create: `backend/tests/rag/test_policy_qa.py`
- Create: `frontend/src/api/chat.ts`
- Create: `frontend/src/components/CitationPanel.tsx`
- Create: `frontend/src/components/ConfidenceBadge.tsx`
- Create: `frontend/src/pages/ChatPage.tsx`
- Create: `frontend/tests/chat/ChatPage.test.tsx`

**步骤 1：先写失败测试**

```python
def test_policy_answer_includes_citations_and_confidence(client, seeded_policy_chunks):
    response = client.post("/api/chat/ask", json={"question": "Can I book business class?"})
    payload = response.json()
    assert response.status_code == 200
    assert payload["answer"]
    assert payload["citations"]
    assert payload["confidence"] >= 0
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/rag/test_policy_qa.py -v`
Expected: FAIL because LlamaIndex query engine and citation generation are missing.

**步骤 3：写最小实现**

- 通过 LlamaIndex Query Engine + Milvus 实现检索问答。
- 回表 PostgreSQL 获取元数据与引用片段。
- 要求每个答案必须返回 chunk id、document id 和命中文本片段。
- 持久化会话和消息历史。
- 在 React 问答页展示引用依据和置信度。
- 对无命中或低置信度问题提供兜底回复。

**步骤 4：运行验证**

Run: `cd backend && uv run pytest tests/rag/test_policy_qa.py -v`
Expected: PASS.

Run: `cd frontend && pnpm test ChatPage.test.tsx`
Expected: PASS.

**步骤 5：提交**

```bash
git add backend/app/api/routes/chat.py backend/app/db/models/conversation.py backend/app/services/llm/client.py backend/app/services/rag backend/tests/rag frontend/src/api/chat.ts frontend/src/components/CitationPanel.tsx frontend/src/components/ConfidenceBadge.tsx frontend/src/pages/ChatPage.tsx frontend/tests/chat/ChatPage.test.tsx
git commit -m "feat: add policy q-and-a with citations"
```
### 任务 4：增加 Prompt 管理、检索 Trace 与可观测性

**Files:**
- Create: `backend/app/api/routes/prompt_templates.py`
- Create: `backend/app/db/models/prompt_template.py`
- Create: `backend/app/services/prompts/service.py`
- Create: `backend/app/api/deps.py`
- Modify: `backend/app/core/logging.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/api/test_prompt_templates.py`
- Create: `frontend/src/api/prompts.ts`
- Create: `frontend/src/components/RetrievalTraceDrawer.tsx`
- Create: `frontend/src/pages/PromptTemplatesPage.tsx`

**步骤 1：先写失败测试**

```python
def test_prompt_template_can_be_created_and_activated(client):
    response = client.post("/api/prompts", json={"name": "default-policy", "template": "..."})
    assert response.status_code == 201
    assert response.json()["status"] == "draft"
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/api/test_prompt_templates.py -v`
Expected: FAIL because prompt template APIs are missing.

**步骤 3：写最小实现**

- 增加 Prompt 模板 CRUD，并保证同一任务类型只有一个激活版本。
- 将 LlamaIndex 检索过程、召回候选和最终上下文写入 `rag_recall_log`。
- 结构化日志中补充 request id、tenant id、耗时、token 用量和模型名。
- 用 OpenTelemetry 对 API 与 Worker 进行埋点。
- 管理端增加 Prompt 配置页与检索链路查看面板。

**步骤 4：运行验证**

Run: `cd backend && uv run pytest tests/api/test_prompt_templates.py -v`
Expected: PASS.

Run: `cd backend && uv run pytest -k "prompt or recall_log" -v`
Expected: PASS.

**步骤 5：提交**

```bash
git add backend/app/api/routes/prompt_templates.py backend/app/db/models/prompt_template.py backend/app/services/prompts/service.py backend/app/core/logging.py backend/app/main.py backend/tests/api/test_prompt_templates.py frontend/src/api/prompts.ts frontend/src/components/RetrievalTraceDrawer.tsx frontend/src/pages/PromptTemplatesPage.tsx
git commit -m "feat: add prompt management and observability"
```

### 任务 5：升级为混合检索与离线评测

**Files:**
- Create: `backend/app/services/rag/query_rewriter.py`
- Modify: `backend/app/services/rag/query_engine.py`
- Modify: `backend/app/services/rag/retrievers.py`
- Create: `backend/app/services/rag/rerankers.py`
- Create: `backend/app/db/models/eval.py`
- Create: `backend/app/services/eval/dataset_loader.py`
- Create: `backend/app/services/eval/runner.py`
- Create: `backend/app/api/routes/evals.py`
- Create: `backend/tests/rag/test_hybrid_retrieval.py`
- Create: `backend/tests/eval/test_eval_runner.py`
- Create: `frontend/src/api/evals.ts`
- Create: `frontend/src/pages/EvalPage.tsx`

**步骤 1：先写失败测试**

```python
def test_hybrid_retrieval_prefers_exact_policy_keyword_matches(seed_data):
    result = retrieve("hotel limit for beijing", tenant_id="t1")
    assert result.top_hits[0].document_title == "Beijing Travel Policy"
```

```python
def test_eval_runner_persists_metrics(eval_dataset):
    run = run_eval(eval_dataset_id="dataset-1")
    assert run.metrics["answer_recall"] >= 0
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/rag/test_hybrid_retrieval.py tests/eval/test_eval_runner.py -v`
Expected: FAIL because hybrid retriever assembly and eval modules are missing.

**步骤 3：写最小实现**

- 在 LlamaIndex 中装配 Milvus dense / sparse 检索与结构化过滤。
- 替换当前只适合英文 token 的占位式 embedding / lexical 检索逻辑，升级为可支持中文文本、中文问题和中英混合问法的实现。
- 增加可选的 Query 改写，用于支持运营缩写和政策别名。
- 在生成答案前增加 Rerank。
- 建立带标准答案和标准引用的评测集，至少覆盖中文政策问答、城市名/费用类型等中文实体，以及中英混合表达。
- 跟踪检索命中率、引用准确率、答案完整度和人工通过率。
- 管理端增加评测运行触发和结果查看页面。

**中文检索升级子任务**

#### 子任务 5.1：建立中文检索基线样本

- 从现有差旅制度、酒店限额、机票舱位、报销规则文档中抽取一组中文问题样本。
- 样本必须同时覆盖三类输入：纯中文问题、中英混合问题、英文问题。
- 每条样本至少标注：问题、期望命中文档、期望 chunk 关键词、标准答案、标准引用。
- 至少覆盖以下实体类型：城市名、费用类型、舱位类型、金额上限、审批条件。
- 将这批样本沉淀为评测集，而不是只做手工测试。

#### 子任务 5.2：替换当前占位式中文不友好的检索实现

- 移除当前只依赖 `[a-zA-Z0-9]+` token 的简化 embedding / lexical 检索逻辑作为主方案。
- 引入支持中文语义的 embedding 方案，用于替换当前本地 hash bucket 向量实现。
- 引入支持中文的 lexical 检索策略，至少满足以下之一：
  - 中文分词检索
  - 字符 n-gram 检索
  - 中文 sparse 检索
- 要求 dense 检索和 lexical 检索都能处理中文文本，而不是只在英文问题下有效。
- 保留租户、客户、文档状态过滤，不得因为升级中文检索而破坏数据隔离。

#### 子任务 5.3：组装中文可用的混合检索链路

- 将中文 embedding 检索、中文 lexical 检索、结构化过滤统一组装成 hybrid retrieval。
- 增加 Query 改写层，用于处理差旅缩写、城市别名、费用别名、中英混合表达。
- 在 hybrid retrieval 之后增加 Rerank，确保最终进入上下文的 chunks 更稳定。
- retrieval trace 中必须记录 dense 命中、lexical 命中、Rerank 后结果和最终 selected chunks。
- 对中文问题要能解释“为什么命中这些 chunk”，不能只返回最终答案。

#### 子任务 5.4：建立中文专项评测与回归门槛

- 新增中文专项评测指标：
  - 答案正确率
  - 中文引用准确率
  - 中英混合问题命中率
  - 低置信度占比
- 为城市限额、舱位规则、报销口径准备最少一组回归问题集。
- 验收门槛不能只看“能返回答案”，必须同时看引用是否正确、`0%` 置信度是否显著下降。
- 如果中文问题仍大量命中失败，即使英文评测通过，也不能视为 Task 5 完成。

#### 子任务 5.5：中文检索升级的交付标准

- 对同一批样本，中文问题与中英混合问题不应再大面积出现“无引用 + 0% 置信度”。
- 数据库中的 `rag_recall_log` 应能清晰展示中文问题的检索链路和最终命中 chunks。
- 前端 `retrieval_trace` 面板应能用于人工核查中文问题是否命中了正确证据。
- 如果当前模型或向量策略仍不足以支撑中文效果，必须在任务收尾时明确记录遗留问题，而不是模糊带过。

**步骤 4：运行验证**

Run: `cd backend && uv run pytest tests/rag/test_hybrid_retrieval.py tests/eval/test_eval_runner.py -v`
Expected: PASS.

Run: `cd backend && uv run pytest -k "hybrid or eval" -v`
Expected: PASS.

Run: 使用中文问题、中英混合问题和英文问题各准备一组样本进行手工回归验证
Expected: 中文与中英混合问题能够命中正确 chunks，并返回可解释引用，而不是大面积出现 `0%` 置信度。

**步骤 5：提交**

```bash
git add backend/app/services/rag/query_rewriter.py backend/app/services/rag/query_engine.py backend/app/services/rag/retrievers.py backend/app/services/rag/rerankers.py backend/app/db/models/eval.py backend/app/services/eval backend/app/api/routes/evals.py backend/tests/rag/test_hybrid_retrieval.py backend/tests/eval/test_eval_runner.py frontend/src/api/evals.ts frontend/src/pages/EvalPage.tsx
git commit -m "feat: add hybrid retrieval and offline evaluation"
```
### 任务 6：增加 Query Router 与首批 Agent 工作流

**Files:**
- Create: `backend/app/api/routes/agents.py`
- Create: `backend/app/db/models/agent.py`
- Create: `backend/app/schemas/agent.py`
- Create: `backend/app/services/agents/state.py`
- Create: `backend/app/services/agents/router.py`
- Create: `backend/app/services/agents/graph.py`
- Create: `backend/app/services/agents/nodes.py`
- Create: `backend/app/services/agents/policy_graph.py`
- Create: `backend/app/services/agents/anomaly_graph.py`
- Create: `backend/app/services/agents/ticket_router_graph.py`
- Create: `backend/app/services/agents/tools.py`
- Create: `backend/tests/agents/test_router.py`
- Create: `backend/tests/agents/test_ticket_router.py`
- Create: `frontend/src/api/agents.ts`
- Create: `frontend/src/components/RunTimeline.tsx`
- Create: `frontend/src/pages/AgentRunsPage.tsx`

**步骤 1：先写失败测试**

```python
def test_router_sends_policy_question_to_rag_agent():
    route = choose_route("What is the hotel cap in Shanghai?")
    assert route.agent_name == "travel_policy_agent"
```

```python
def test_ticket_router_agent_returns_queue_and_reason(seed_ticket):
    result = run_ticket_router(seed_ticket)
    assert result.queue_name
    assert result.reason
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/agents/test_router.py tests/agents/test_ticket_router.py -v`
Expected: FAIL because LangGraph router and workflow graphs do not exist.

**步骤 3：写最小实现**

- 基于意图和置信度阈值实现一个轻量级 Router。
- 用 LangGraph 显式定义 state、nodes、edges 和人工审核检查点。
- 至少实现两个工具：订单查询和工单队列查询。
- 将每次状态流转、模型调用和工具调用都写入 `agent_run` 与 `tool_call_log`。
- 管理端增加运行时间线和失败记录查看页。

**步骤 4：运行验证**

Run: `cd backend && uv run pytest tests/agents/test_router.py tests/agents/test_ticket_router.py -v`
Expected: PASS.

Run: `cd backend && uv run pytest -k agents -v`
Expected: PASS.

**步骤 5：提交**

```bash
git add backend/app/api/routes/agents.py backend/app/db/models/agent.py backend/app/schemas/agent.py backend/app/services/agents backend/tests/agents frontend/src/api/agents.ts frontend/src/components/RunTimeline.tsx frontend/src/pages/AgentRunsPage.tsx
git commit -m "feat: add langgraph agent workflows"
```
### 任务 7：增加规则引擎与人工审核队列

**Files:**
- Create: `backend/app/api/routes/rules.py`
- Create: `backend/app/api/routes/reviews.py`
- Create: `backend/app/db/models/rule.py`
- Create: `backend/app/services/rules/engine.py`
- Create: `backend/tests/rules/test_rule_engine.py`
- Create: `backend/tests/api/test_review_queue.py`
- Create: `frontend/src/api/reviews.ts`
- Create: `frontend/src/components/RuleResultPanel.tsx`
- Create: `frontend/src/pages/ReviewQueuePage.tsx`

**步骤 1：先写失败测试**

```python
def test_rule_engine_blocks_out_of_policy_amount():
    result = evaluate_rules({"amount": 2500, "city_tier": "tier-2", "expense_type": "hotel"})
    assert result.decision == "blocked"
```

```python
def test_low_confidence_agent_result_creates_review_case(client):
    response = client.post("/api/reviews/ingest", json={"source": "agent", "confidence": 0.32})
    assert response.status_code == 201
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/rules/test_rule_engine.py tests/api/test_review_queue.py -v`
Expected: FAIL because rules and review APIs are missing.

**步骤 3：写最小实现**

- 将政策规则存成结构化条件，而不是只保存自然语言。
- 在检索或 Agent 输出之后、最终结果返回之前执行规则校验。
- 将低置信度、规则冲突或缺乏证据的结果送入审核队列。
- 前端展示规则命中、拦截原因和建议处理动作。
- 持久化人工覆盖原因，满足审计要求。

**步骤 4：运行验证**

Run: `cd backend && uv run pytest tests/rules/test_rule_engine.py tests/api/test_review_queue.py -v`
Expected: PASS.

Run: `cd backend && uv run pytest -k "rules or review" -v`
Expected: PASS.

**步骤 5：提交**

```bash
git add backend/app/api/routes/rules.py backend/app/api/routes/reviews.py backend/app/db/models/rule.py backend/app/services/rules/engine.py backend/tests/rules/test_rule_engine.py backend/tests/api/test_review_queue.py frontend/src/api/reviews.ts frontend/src/components/RuleResultPanel.tsx frontend/src/pages/ReviewQueuePage.tsx
git commit -m "feat: add rule engine and review workflow"
```

### 任务 8：容器化、安全基线与部署准备

**Files:**
- Create: `infra/docker/backend.Dockerfile`
- Create: `infra/docker/frontend.Dockerfile`
- Create: `infra/k8s/api-deployment.yaml`
- Create: `infra/k8s/worker-deployment.yaml`
- Create: `infra/k8s/web-deployment.yaml`
- Create: `infra/k8s/ingress.yaml`
- Create: `infra/monitoring/prometheus.yaml`
- Create: `infra/monitoring/grafana-dashboards.json`
- Modify: `backend/app/core/security.py`
- Modify: `.env.example`
- Create: `backend/tests/api/test_authz.py`

**步骤 1：先写失败测试**

```python
def test_operator_without_admin_role_cannot_edit_prompt_template(client, operator_token):
    response = client.post("/api/prompts", headers={"Authorization": f"Bearer {operator_token}"}, json={})
    assert response.status_code == 403
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/api/test_authz.py -v`
Expected: FAIL because authorization policy is incomplete.

**步骤 3：写最小实现**

- 增加 admin、operator、reviewer 三类角色的权限控制。
- 构建 API、Worker 和 Web 的生产镜像。
- 增加 Kubernetes 清单，包括健康检查、资源限制、Secrets 和 ConfigMap。
- 暴露请求延迟、任务吞吐、评测运行、Agent 失败率和 Token 用量等指标。
- 制定发布路径：本地 compose、测试环境 Kubernetes、API 先灰度。

**步骤 4：运行验证**

Run: `cd backend && uv run pytest tests/api/test_authz.py -v`
Expected: PASS.

Run: `docker build -f infra/docker/backend.Dockerfile .`
Expected: PASS.

Run: `kubectl apply --dry-run=client -f infra/k8s`
Expected: PASS.

**步骤 5：提交**

```bash
git add infra backend/app/core/security.py backend/tests/api/test_authz.py .env.example
git commit -m "chore: add deployment and security baseline"
```

### 任务 9：真实模型网关接入与本地回退

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/llm/client.py`
- Create: `backend/app/services/rag/embedding_client.py`
- Modify: `backend/app/services/rag/index_builder.py`
- Modify: `backend/app/services/rag/query_engine.py`
- Modify: `backend/pyproject.toml`
- Modify: `.env.example`
- Modify: `README.md`
- Create: `backend/tests/llm/test_client.py`
- Create: `backend/tests/rag/test_embedding_client.py`

**步骤 1：先写失败测试**

```python
def test_openai_compatible_policy_client_parses_gateway_response():
    client = OpenAICompatiblePolicyAnswerClient(...)
    draft = client.generate_answer(question="北京酒店报销上限是多少", citations=[])
    assert draft.model_name == "gpt-4o-mini"
```

```python
def test_openai_compatible_embedding_client_parses_gateway_response():
    client = OpenAICompatibleEmbeddingClient(...)
    vectors = client.embed_texts(["北京酒店报销上限"], dimension=4)
    assert vectors[0] == [0.1, 0.2, 0.3, 0.4]
```

**步骤 2：运行测试，确认先失败**

Run: `cd backend && uv run pytest tests/llm/test_client.py tests/rag/test_embedding_client.py -v`
Expected: FAIL because OpenAI-compatible gateway clients do not exist.

**步骤 3：写最小实现**

- 在 LLM 链路增加 provider 抽象，支持 `deterministic` 与 `openai-compatible`。
- 在 embedding 链路增加独立 provider 抽象，支持真实 embedding 网关与本地 deterministic 回退。
- `query_engine` 内部统一通过 provider 工厂获取回答客户端，避免把 deterministic 逻辑写死在主链路里。
- `index_builder` 改为批量调用 embedding client，便于后续切换真实模型而不改上层入库流程。
- 当网关未配置或密钥缺失时，系统必须自动回退，不允许因为外部模型缺失而破坏本地开发和测试。
- `.env.example` 与 `README.md` 必须同步补充模型网关配置说明和验证步骤。

**步骤 4：运行验证**

Run: `cd backend && uv run pytest tests/llm/test_client.py tests/rag/test_embedding_client.py -v`
Expected: PASS.

Run: `pytest -q backend/tests`
Expected: PASS.

Run: `cd frontend && npm test && npm run build`
Expected: PASS because前端接口契约未被破坏。

**步骤 5：提交**

```bash
git add backend/app/core/config.py backend/app/services/llm/client.py backend/app/services/rag/embedding_client.py backend/app/services/rag/index_builder.py backend/app/services/rag/query_engine.py backend/pyproject.toml backend/tests/llm/test_client.py backend/tests/rag/test_embedding_client.py .env.example README.md
git commit -m "feat: add model gateway with deterministic fallback"
```

### 后续迭代任务：后台控制台与运维面板重构

**范围：**

- 顶部标签壳层
- 知识库管理重组
- 监控面板
- 运行日志
- 系统设置

**明确不做：**

- `.env` 与密钥在线编辑
- Prometheus 原始文本解析式前端
- Alembic 迁移框架引入
- 多页面路由化重构

**后端改造要点：**

- 新增 `system_setting` 表，使用 `key + value_json` 持久化业务默认值。
- 新增 settings service，形成“环境变量默认值 + PostgreSQL 覆盖值”的 effective settings。
- 新增接口：
  - `GET /api/settings/system`
  - `PUT /api/settings/system`
- 可编辑字段固定为：
  - `default_tenant_id`
  - `default_customer_id`
  - `chat_top_k`
  - `chat_confidence_threshold`
  - `default_eval_dataset`
- 只读运行配置固定展示：
  - `llm_provider`
  - `llm_model_name`
  - `embedding_provider`
  - `embedding_model_name`
  - `embedding_dimension`
  - `vector_store_provider`
  - `auth_enabled`
- 新增 `runtime_log` 表，持久化请求级运行日志。
- 在请求中间件中把成功请求与异常请求都写入 `runtime_log`，并保留 stdout JSON 日志。
- 新增接口：
  - `GET /api/logs/runtime`
  - `GET /api/logs/runtime/{id}`
- 日志筛选参数固定支持：
  - `path`
  - `status_code`
  - `request_id`
  - `tenant_id`
  - `session_id`
  - `date_from`
  - `date_to`
  - `limit`
- 新增 `GET /api/monitoring/overview`，聚合输出：
  - `knowledge_summary`
  - `chat_summary`
  - `review_summary`
  - `agent_summary`
  - `eval_summary`
  - `request_summary`
  - `recent_activity`
- 把问答链路中的 `chat_top_k` 和 `chat_confidence_threshold` 改为优先读取 effective settings。

**前端改造要点：**

- 将 `App.tsx` 重构为顶部标签式后台壳层，不引入 `react-router`。
- 标签顺序固定为：
  - `知识库管理`
  - `政策问答`
  - `Prompt 模板`
  - `评测运行`
  - `Agent 运行`
  - `人工复核`
  - `监控面板`
  - `运行日志`
  - `系统设置`
- 新增 API 封装：
  - `monitoring.ts`
  - `logs.ts`
  - `settings.ts`
- 新增页面：
  - `MonitoringPage`
  - `RuntimeLogsPage`
  - `SystemSettingsPage`
- 知识库页增加顶部摘要卡，展示文档总数、待重建文档和当前向量状态。
- 前端默认租户、客户和默认评测集改为通过系统设置接口加载。

**权限规则：**

- `系统设置`：仅 `admin` 可读写
- `监控面板`：`admin`、`operator` 可读
- `运行日志`：`admin`、`operator` 可读

**验收标准：**

- 顶部标签切换正常，默认进入 `知识库管理`
- 管理员修改默认租户、客户和检索阈值后，知识库、问答和评测页默认值即时更新
- 上传文档、发起问答、执行评测、运行 Agent 后，监控面板与运行日志能看到对应变化
- `operator` 能看监控与日志，但不能修改系统设置
- 原有知识库、问答、Prompt、评测、Agent、人工复核能力不回退
- 前端构建与后端测试全通过

## 明确延后处理的事项

- 初期不要上微服务。
- 不要让 LlamaIndex 和 LangChain 高层 Agent 同时接管同一条主业务链路。
- 在单 Agent 链路还不透明之前，不要做多 Agent 编排。
- 在政策问答评测指标稳定前，不要增加发票 OCR 或邮件自动回复。
- 初期不要训练自定义模型，优先优化 Prompt、检索、Rerank 和规则。
- 在 Milvus 内建混合检索与 Rerank 能力证明确实不够之前，不要单独引入 OpenSearch 集群。

## 交付风险与缓解措施

| 风险 | 为什么重要 | 缓解方案 |
| --- | --- | --- |
| 不同文档格式的解析质量差异大 | 坏切块会直接破坏检索质量 | 第一阶段只支持 DOCX 和 PDF，增加格式专项测试，并记录解析失败原因 |
| 元数据质量不稳定 | 错误的租户或版本会造成不安全回答 | 上传流程强制要求租户和文档版本字段 |
| 混合检索在线效果不如离线效果 | 离线评测提升不一定转化为业务价值 | 建立人工反馈闭环，并衡量引用是否真的有用 |
| 中文语料检索效果不达标 | 当前差旅政策与运营提问天然以中文为主，如果中文召回差，系统即使架构完整也不可用 | 在任务 5 中明确替换占位检索实现，并用中文样本做专项评测与手工回归 |
| Agent 路由过程不透明 | 面试演示和排障时都难以建立信任 | 持久化每次路由、工具调用和置信度 |
| 规则覆盖不足 | LLM 可能答得像对，但仍然违反业务规则 | 所有最终动作前都加确定性后置校验 |
| 基础设施过早复杂化 | 项目可能还没出业务价值就先被运维拖慢 | 前两个阶段只保留一个应用和一个 Worker |

## 近期首个 Sprint 建议

1. 完整完成任务 1。
2. 完成任务 2，但只支持 DOCX 和 PDF。
3. 完成任务 3，只打通“政策问答 + 引用展示”这一条业务闭环。
4. 用 3 份文档、10 个精选问题和可视化检索证据做一次演示。

计划文件已保存到 `docs/plans/2026-04-01-travel-ops-copilot.md`。后续有两种执行方式：

**1. 当前会话继续推进**：按任务逐步实现，并在每个阶段做校验。

**2. 单独开实现会话**：在新会话中按这份计划分阶段执行，并在关键节点做 review。

## 任务 10：真实模型联调收口与检索链生产化升级

### 本轮目标

- 把 `LLM / Embedding` 从“支持 OpenAI-compatible provider”推进到“支持页面内可验证的真实网关联调”。
- 把检索链从原型级实现推进到更接近生产可用的结构，优先解决重复改写、无效全量扫描和评测可追溯性不足的问题。

### 本轮已实现

#### 10.1 真实 LLM 网关联调能力

- 新增 `GET /api/chat/llm-readiness`，用于检查模型网关是否可达、配置是否齐全、目标模型是否出现在 `/models` 列表中。
- 新增 `POST /api/chat/llm-smoke-test`，直接执行一次真实聊天生成请求，返回：
  - `answer_preview`
  - `latency_ms`
  - `token_usage`
  - `endpoint`
- 前端 `系统设置` 页面新增：
  - `检查 LLM 网关`
  - `执行 LLM 烟雾测试`
- 当 `LLM_PROVIDER=openai-compatible` 但缺少地址或密钥时，仍然保持 deterministic 回退，不破坏本地开发链路。

#### 10.2 Embedding 网关联调闭环

- 保留并复用：
  - `GET /api/knowledge/embedding-readiness`
  - `POST /api/knowledge/embedding-smoke-test`
- 前端 `系统设置` 页面同步集成：
  - `检查 Embedding 网关`
  - `执行 Embedding 烟雾测试`
- 这样真实模型联调不再分散在多个页面，管理员可以在一个入口完成模型连通性检查。

#### 10.3 检索链生产化升级

- `query_engine` 入口只做一次 Query Rewrite，避免每个 retriever 内重复扩词。
- `dense retrieval` 改为按 Milvus 返回的 `chunk_id` 定向回表，只加载命中的 PostgreSQL rows。
- `lexical retrieval` 改为先做数据库候选筛选，再在 Python 层计算更细打分，降低租户内全量扫描成本。
- 保留现有 `hybrid retrieval -> rerank -> citation` 主链，不破坏原有 API 契约。

#### 10.4 质量验证链路升级

- `eval_run.metrics` 新增 `provider_snapshot`，记录：
  - `llm_provider`
  - `llm_model_name`
  - `embedding_provider`
  - `embedding_model_name`
  - `vector_store_provider`
- 前端 `评测运行` 页面新增 `本次评测配置` 面板，后续做真实模型回归时可以直接看到这次评测到底跑在什么配置上。

### 本轮验证结果

- `pytest -q backend/tests`：通过
- `cd frontend && npm test`：通过
- `cd frontend && npm run build`：通过

### 当前边界

- 本轮完成的是“真实网关接入能力、页面联调入口和评测追踪能力”，不是“真实模型效果达标”本身。
- 如果没有填写真实 `LLM_* / EMBEDDING_*`，系统仍会回退到本地 deterministic provider。
- 是否达到企业级检索质量，仍需在真实知识库和真实网关上重新跑中文评测与人工验收。

### 下一步建议

1. 在 `.env` 中配置真实 `LLM_*` 与 `EMBEDDING_*`。
2. 通过 `系统设置` 页面完成四项联调动作：
   - `检查 LLM 网关`
   - `执行 LLM 烟雾测试`
   - `检查 Embedding 网关`
   - `执行 Embedding 烟雾测试`
3. 回到 `知识库管理` 页面，重建 `待重建` 文档。
4. 在 `评测运行` 页面重新跑中文评测，并根据 `本次评测配置` 与失败明细判断是否进入下一轮检索质量优化。

## 任务 11：企业化检索、召回与评测强化（第一轮）

### 本轮目标

- 把当前检索主链路从“可运行”推进到“更接近企业生产”的可调优结构，优先解决融合策略粗糙、重复文档挤占上下文和召回排序不可评估的问题。
- 把真实网关联调从“依赖 `/models` 成功”推进到“基于真实请求探活”的方式，兼容方舟、百炼这类 OpenAI-compatible 但能力面不完全一致的网关。
- 把评测从“只看是否命中”推进到“看召回排序、看是否达标、看是否放行”的企业评估口径。

### 本轮改造范围

#### 11.1 架构层

- 保持模块化单体不变，不新增微服务拆分。
- 新增一份“企业检索链 ADR”，明确：
  - 为什么保留 `PostgreSQL + Milvus`
  - 为什么在当前阶段采用 `RRF + rerank + 文档多样性约束`
  - 为什么质量门槛以离线评测和人工验收共同裁决

#### 11.2 检索策略

- 将 `hybrid retrieval` 的融合方式从“按 chunk 取更高分数”升级为 `RRF`。
- 在融合后增加文档多样性约束，避免同一文档的多个 chunk 挤占全部证据窗口。
- 保留 `dense + lexical + rerank` 三段式结构，但让排序更稳定、可解释。
- 为检索链引入显式可配置参数：
  - `RAG_RRF_K`
  - `RAG_MAX_CHUNKS_PER_DOCUMENT`
  - `RAG_DENSE_CANDIDATE_MULTIPLIER`
  - `RAG_LEXICAL_CANDIDATE_MULTIPLIER`

#### 11.3 召回策略

- `dense retrieval` 继续按 `chunk_id` 定向回表，但扩大候选数后再融合。
- `lexical retrieval` 保留数据库候选筛选，再在 Python 层精算分数。
- `query rewrite` 继续只在入口执行一次，不在 retriever 内重复扩写。
- 在 `retrieval_trace` 中补充更多可诊断信息：
  - 原始问题
  - 扩写后问题
  - 命中的 rewrite 规则
  - 候选数量与最终入选数量

#### 11.4 模型网关联调

- `LLM readiness` 不再只依赖 `/models`，当模型列表接口不兼容时，允许回退到一次最小真实推理探活。
- `Embedding readiness` 不再只依赖 `/models`，改为优先验证 `/embeddings` 真正可用。
- `Embedding` 请求补充可配置参数，支持：
  - `dimensions`
  - `encoding_format`
- 这样可以兼容百炼 `text-embedding-v4` 这类需要指定维度的模型。
- 对供应商约束做显式兼容处理，例如 DashScope / 百炼 `text-embedding-v4` 的 embedding 单次批量上限为 `10`，避免知识库重建因默认批量过大直接失败。

#### 11.5 评估标准

- 在现有指标基础上新增：
  - `retrieval_mrr`
  - `retrieval_hit_rate`
  - `answer_pass_rate`
  - `quality_gate`
  - `quality_gate_reasons`
- `quality_gate` 至少区分：
  - `pass`
  - `warn`
  - `fail`
- 评估时不只看“答没答出来”，还要看：
  - 证据排序是否足够靠前
  - 低置信度占比是否过高
  - 在当前模型/向量配置下是否满足放行门槛

### 本轮明确不做

- 不引入 Elasticsearch / OpenSearch 作为第二检索引擎。
- 不引入复杂 Query Planner、多跳检索或完整 Graph RAG。
- 不在这一轮内完成所有企业生产要求，只完成“企业化第一轮收口”。

### 本轮验收标准

- 真实 LLM readiness 在 `/models` 不可用时仍可完成探活。
- 真实 embedding readiness 能验证向量接口可用性，并支持显式维度参数。
- `hybrid retrieval` 使用 RRF 融合并通过回归测试。
- 评测结果能够返回 `quality_gate` 与排序类指标。
- 迭代文档、README 和实现保持一致。





