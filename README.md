# CL_agent — Travel Ops Copilot

> **Production-grade RAG + Agent reference for corporate travel ops.**
> Chinese-first hybrid retrieval, multi-agent workflows, real-gateway / local-fallback model layer,
> and a 9-tab operations console — not just another chat-with-PDF demo.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/)
[![Node 20+](https://img.shields.io/badge/node-20+-green.svg)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![Milvus](https://img.shields.io/badge/Milvus-00A1EA?logo=milvus&logoColor=white)](https://milvus.io/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

---

## ✨ Why this project

Most open-source RAG samples stop at *"upload a PDF, ask a question, get an answer."*
**CL_agent goes the rest of the way to a system you could actually put in front of an ops team.**

| 🎯 Capability | What's actually inside |
| --- | --- |
| **🇨🇳 Chinese-first hybrid retrieval** | BM25 + dense vectors + lightweight reranker, with query rewrite, alias expansion and mixed-language handling — tuned on real Chinese policy text, not translated English. |
| **🤖 Real multi-agent workflows** | LangGraph-style stateful graphs for `travel_policy_agent`, `ticket_router_agent` and anomaly handling — every step persisted to `agent_run` + `tool_call_log` for full replay. |
| **🔌 Gateway-or-local model layer** | OpenAI-compatible gateway in production (DashScope / Volces ARK / OpenAI / your own), deterministic local fallback for dev — **the same code path, no `if MOCK:` branches**. |
| **📊 Built-in offline evaluation** | Ship a dataset, get answer correctness, citation hit rate and low-confidence ratio per question. Compare runs, drill into failures, export CSV — all in the UI. |
| **👮 Rule engine + human review queue** | Configurable rules auto-route low-confidence or policy-violating answers to a manual review panel. No more "the LLM said something weird" black holes. |
| **🛠️ Real ops console (9 tabs)** | Knowledge / Q&A / Prompts / Eval / Agents / Review / Monitoring / Runtime logs / Settings. Tenant + customer scoping, RBAC (`admin` / `operator` / `reviewer`), live config override without restart. |
| **📈 Production observability** | Prometheus `/metrics`, request-ID tracing across every layer, `runtime_log` table for queryable history, `rag_recall_log` for retrieval forensics. |
| **🚢 Container + K8s ready** | Dockerfiles, `docker-compose` for the full local stack (Postgres + Redis + MinIO + Milvus + etcd + Attu), Kubernetes manifests under `infra/k8s`. |

## 🏗️ Architecture at a glance

```
┌────────────────────────────────────────────────────────────────────────┐
│                React + Vite Operations Console (9 tabs, RBAC)          │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │  REST + SSE (X-Request-ID end-to-end)
┌──────────────────────────────────┴─────────────────────────────────────┐
│                          FastAPI Application                            │
│  ┌──────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │ Routes   │→ │ Agent Graphs │→ │ RAG Core │→ │ Model Gateway Layer │  │
│  │ + RBAC   │  │ (LangGraph)  │  │ Hybrid + │  │ openai-compatible / │  │
│  │          │  │ + Tool Calls │  │ Rerank   │  │ deterministic local │  │
│  └──────────┘  └──────────────┘  └──────────┘  └────────────────────┘  │
│        │              │                │                  │             │
│        ▼              ▼                ▼                  ▼             │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ PostgreSQL │ Redis │ MinIO (objects) │ Milvus (vectors) │ etcd  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│        │                                                                │
│        └──→ Prometheus /metrics  +  runtime_log  +  rag_recall_log     │
└────────────────────────────────────────────────────────────────────────┘
```

## 🎬 30-second demo flow

1. Drop a Chinese travel-policy DOCX into **Knowledge** → ingestion job runs end-to-end (parse → chunk → embed → index).
2. Ask `"北京酒店报销上限是多少？"` in **Q&A** → get an answer with **citations + confidence + retrieval trace**.
3. Open **Eval**, run `zh-policy-smoke` → see correctness / citation-hit / low-confidence broken down per question.
4. Trigger a sample ticket in **Agents** → watch the LangGraph timeline, rule hits and tool calls get persisted.
5. Edit the confidence threshold in **Settings** → next answer reflects the new threshold without a restart.

> 中文用户请直接阅读下方的中文章节，下面只是一段英文快速上手指引。

## English Quickstart

### Prerequisites
- Docker Desktop (with `docker compose`)
- Python `3.13+`
- Node.js `20+` and `npm`

### 1. Clone & configure
```bash
git clone https://github.com/BOBOXERWHITE/CL_agent.git
cd CL_agent
cp .env.example .env
cp frontend/.env.example frontend/.env
```

### 2. Start infrastructure (PostgreSQL, Redis, MinIO, etcd, Milvus, Attu)
```bash
docker compose up -d postgres redis minio etcd milvus attu
```

### 3. Run backend
```bash
make backend-install
cd backend && uvicorn app.main:app --reload
```
Backend listens on `http://localhost:8000`. Prometheus metrics at `/metrics`.

### 4. Run frontend
```bash
make frontend-install
cd frontend && npm run dev
```
Console listens on `http://localhost:5173`.

### 5. Try it
1. Open the **知识库管理** (Knowledge) tab and upload a DOCX or PDF.
2. Wait for the ingestion job to flip to `已完成` (done).
3. Switch to **政策问答** (Q&A) and ask a question — answers come back with citations,
   confidence scores and a retrieval trace.
4. Switch to **评测运行** (Eval) and run the bundled `zh-policy-smoke` dataset.
5. Plug in a real `OpenAI-compatible` gateway via `LLM_*` / `EMBEDDING_*` env vars to replace
   the deterministic local fallback. The system always falls back to local providers when
   gateway credentials are missing — local development never breaks.

### Tests
```bash
make test           # backend + frontend
make test-backend   # pytest only
make test-frontend  # vitest only
```

### Project layout
```
backend/    FastAPI app (routes, services, agents, RAG, eval, db models)
frontend/   React + Vite operations console
infra/      Dockerfiles, docker-compose, Kubernetes manifests
docs/       Architecture review, plans, reports, knowledge base samples
```

See [`docs/architecture-review.md`](docs/architecture-review.md) for the full architectural deep dive
and [`docs/plans/`](docs/plans) for iteration history.

Contributions are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a PR.

---

## 项目简介（中文）

基于差旅场景的企业级 `RAG + Agent` 项目。当前主线已经完成 `Task 1` 到 `Task 8` 的最小可落地版本，并继续进入下一轮质量升级：把 demo 级模型链路改造成“真实模型网关 + 本地回退”的结构。

## 文档

- 实施计划：`docs/plans/2026-04-01-travel-ops-copilot.md`
- 开发规则：`docs/development-rules.md`

## 本地开发前提

- 已安装 Docker Desktop，并且可以执行 `docker compose`
- Python `3.13+`
- Node.js 与 `npm`

## 配置文件

- 仓库根目录使用 `.env.example` 作为后端配置模板
- 前端使用 `frontend/.env.example` 作为 Vite 配置模板
- 前端依赖安装使用 `frontend/.npmrc` 中的镜像源配置

首次启动前可以复制环境变量文件：

```powershell
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env
```

## 基础依赖启动

启动 PostgreSQL、Redis、MinIO、etcd、Milvus、Attu：

```powershell
docker compose up -d postgres redis minio etcd milvus attu
```

查看容器状态：

```powershell
docker compose ps
```

查看 Milvus 日志：

```powershell
docker compose logs --tail 80 milvus
```

停止基础依赖：

```powershell
docker compose down
```

## 默认端口与凭据

| 服务 | 端口 | 说明 |
| --- | --- | --- |
| PostgreSQL | `5432` | 结构化业务数据 |
| Redis | `6379` | 缓存与队列 |
| MinIO API | `9000` | 对象存储 API |
| MinIO Console | `9001` | 管理界面 |
| etcd | `2379` | Milvus 元数据依赖 |
| Milvus gRPC | `19530` | 向量检索接口 |
| Milvus HTTP | `9091` | 管理接口 |
| Attu | `18000` | Milvus 图形界面 |
| API Metrics | `8000/metrics` | Prometheus 抓取入口 |

默认凭据来自 `.env.example`：

- PostgreSQL：`travel_ops / travel_ops / travel_ops`
- MinIO：`minioadmin / minioadmin123`
- MinIO Bucket：`knowledge`
- Milvus Collection：`knowledge_chunks`
- Attu：浏览器访问 `http://localhost:18000`

## 关键环境变量

### 后端

- `DATABASE_URL`：后端结构化数据存储
- `OBJECT_STORAGE_PROVIDER`：默认 `minio`
- `VECTOR_STORE_PROVIDER`：默认 `milvus`
- `CELERY_TASK_ALWAYS_EAGER`：默认 `true`，开发阶段任务在 API 进程内同步执行
- `CHAT_TOP_K`：问答阶段默认取前 `3` 条候选证据
- `CHAT_CONFIDENCE_THRESHOLD`：默认 `0.2`
- `CORS_ALLOW_ORIGINS`：允许的前端来源
- `AUTH_ENABLED`：是否启用 Bearer Token 鉴权
- `AUTH_ADMIN_TOKENS`：管理员 Token 列表，逗号分隔
- `AUTH_OPERATOR_TOKENS`：运营角色 Token 列表，逗号分隔
- `AUTH_REVIEWER_TOKENS`：审核角色 Token 列表，逗号分隔

### 模型网关

- `LLM_PROVIDER`：`deterministic` 或 `openai-compatible`
- `LLM_MODEL_NAME`：聊天模型名
- `LLM_API_BASE_URL`：OpenAI 兼容网关地址，例如 `https://your-gateway/v1`
- `LLM_API_KEY`：聊天模型网关密钥
- `EMBEDDING_PROVIDER`：`deterministic` 或 `openai-compatible`
- `EMBEDDING_MODEL_NAME`：embedding 模型名
- `EMBEDDING_API_BASE_URL`：embedding 网关地址；留空时会回退到 `LLM_API_BASE_URL`
- `EMBEDDING_API_KEY`：embedding 网关密钥；留空时会回退到 `LLM_API_KEY`
- `EMBEDDING_DIMENSION`：向量维度，使用真实 embedding 时必须与模型输出维度一致
- `EMBEDDING_BATCH_SIZE`：OpenAI-compatible embedding 单次批量大小，默认 `16`
- `EMBEDDING_MAX_RETRIES`：OpenAI-compatible embedding 在 `429 / 5xx / 网络异常` 下的最大重试次数，默认 `2`

### 前端

- `VITE_API_BASE_URL`：前端请求后端 API 的地址，默认 `http://localhost:8000`
- `VITE_API_TOKEN`：可选的 Bearer Token。开启后端鉴权时，前端会自动附带它

如果浏览器提示跨域，先确认两件事：

- 后端已经从最新 `.env` 读到 `CORS_ALLOW_ORIGINS`
- 前端实际访问地址在允许列表内，例如 `http://127.0.0.1:5173`

## Attu 使用

当前 `docker compose` 已集成 `Attu`，访问地址：

- `http://localhost:18000`

如果页面要求填写 Milvus 连接信息，直接输入：

- Address：`milvus:19530`

## 应用启动

安装后端依赖：

```powershell
make backend-install
```

启动后端开发服务：

```powershell
cd backend
uvicorn app.main:app --reload
```

安装前端依赖：

```powershell
make frontend-install
```

启动前端开发服务：

```powershell
cd frontend
npm run dev
```

## 后台控制台与运维面板

前端现在已经重构为顶部标签式后台控制台，默认包含 9 个入口：

- `知识库管理`
- `政策问答`
- `Prompt 模板`
- `评测运行`
- `Agent 运行`
- `人工复核`
- `监控面板`
- `运行日志`
- `系统设置`

其中新增的 3 个运维面板职责如下：

- `监控面板`：聚合知识库、问答、评测、Agent、人工复核和近 1 小时请求指标，不直接解析 `/metrics`
- `运行日志`：按请求路径、状态码、请求 ID、租户、会话和时间范围查询 `runtime_log`
- `系统设置`：维护业务默认值，并把数据库配置即时覆盖到问答与前端默认参数

### 权限说明

- `系统设置`：仅 `admin` 可读写
- `监控面板`：`admin`、`operator` 可读
- `运行日志`：`admin`、`operator` 可读

### 相关接口

- `GET /api/settings/system`
- `PUT /api/settings/system`
- `GET /api/monitoring/overview`
- `GET /api/logs/runtime`
- `GET /api/logs/runtime/{id}`

### 配置生效规则

- 系统设置面板当前可编辑的业务项只有：
  - `default_tenant_id`
  - `default_customer_id`
  - `chat_top_k`
  - `chat_confidence_threshold`
  - `default_eval_dataset`
- 这些值优先级高于 `.env` 中的默认值，保存后无需重启即可影响：
  - 问答页默认租户 / 客户
  - 知识入库页默认租户 / 客户
  - 问答链路的 `top_k`
  - 问答低置信度阈值
  - 评测页默认评测集
- 基础设施配置仍然只从 `.env` 读取，不会出现在页面中：
  - `LLM_*`
  - `EMBEDDING_*`
  - `MILVUS_*`
  - `MINIO_*`
  - `AUTH_*`

## 当前可验证能力

### Task 2：知识入库

- 上传接口会写入 `PostgreSQL` 文档记录
- 原始文件会写入 `MinIO`
- 切块向量会写入 `Milvus`
- 新增知识库向量重建能力：
  - `POST /api/knowledge/reindex`
  - 可在切换真实 embedding 后，对现有知识库执行全量向量重建而不必重新上传文档
- `GET /api/knowledge/jobs` 现在会返回：
  - 文档已写入的向量配置
  - 当前运行中的向量配置
  - `requires_reindex` 标记，帮助识别切模型后需要重建的文档
- 新增 `GET /api/knowledge/embedding-readiness`，用于检查当前 embedding 网关配置与连通性
- 新增 `POST /api/knowledge/embedding-smoke-test`，用于执行一次真实 embedding 请求并返回向量维度与耗时
- 新增 `DELETE /api/knowledge/documents/{document_id}`，用于同步删除 PostgreSQL、对象存储和向量库中的单份文档数据
- 前端知识入库面板支持单文档 `重建此文档`
- 前端知识入库面板支持：
  - `检查模型网关`
  - `执行真实向量测试`
  - `重建待重建文档`
  - `重建此文档`
  - `删除此文档`

### Task 3：政策问答

- `POST /api/chat/ask` 返回 `answer`、`confidence`、`citations`、`session_id`
- 问答过程会持久化 `chat_session` 与 `chat_message`
- 前端可以直接查看答案、引用依据和置信度

### Task 4：Prompt 管理与检索 Trace

- `GET /api/prompts`
- `POST /api/prompts`
- `POST /api/prompts/{id}/activate`
- `POST /api/chat/ask` 额外返回 `retrieval_trace`
- 后端会持久化 `rag_recall_log`
- 所有 API 响应都会带 `X-Request-ID`

### Task 5：中文检索升级与离线评测

- 检索链路升级为中文友好的 `hybrid retrieval`
- 支持中文问题、中英混合问题和中文别名扩展
- 增加轻量 `rerank`
- 离线评测指标拆分为 `答案正确率 / 引用命中率 / 低置信度占比`
- 新增离线评测接口：
  - `GET /api/evals/runs`
  - `POST /api/evals/runs`
- 前端新增 `评测运行` 面板，可直接执行 `zh-policy-smoke`
- 评测卡片支持展开单题明细，查看问题、系统答案、期望引用、实际引用和低置信度标记
- 评测明细支持本地筛选失败项、筛选低置信度项，并导出当前筛选结果为 CSV
- 评测明细新增失败原因汇总，按整次评测统计失败题数、答案未命中、引用未命中、低置信度和无引用返回

### Task 6：Query Router 与 Agent 工作流

- 新增 Agent 运行接口：
  - `GET /api/agents/runs`
  - `POST /api/agents/runs`
- 新增两类最小 Agent：
  - `travel_policy_agent`
  - `ticket_router_agent`
- 每次运行都会持久化：
  - `agent_run`
  - `tool_call_log`

### Task 7：规则引擎与人工复核队列

- 新增规则接口：
  - `GET /api/rules`
  - `POST /api/rules/evaluate`
- 新增审核队列接口：
  - `GET /api/reviews/queue`
  - `POST /api/reviews/ingest`
- Agent 运行在命中规则或低置信度时会自动写入 `review_case`
- 前端新增 `人工复核队列` 面板

### Task 8：容器化、安全基线与部署准备

- 新增 RBAC 基线：
  - `admin`
  - `operator`
  - `reviewer`
- 新增 `/metrics` Prometheus 指标端点
- 新增 Dockerfile、Kubernetes 清单和监控配置

### Task 9：模型网关与本地回退结构

- 聊天回答链路现在支持：
  - `deterministic` 本地回退
  - `openai-compatible` 模型网关
- embedding 链路现在支持：
  - `deterministic` 本地回退
  - `openai-compatible` embedding 网关
- 即使未配置真实网关，也不会破坏当前本地开发和测试链路

### 后续迭代：后台控制台与运维面板重构

- 前端已从纵向堆叠工作台重构为顶部标签式后台壳层
- 系统设置已落库到 `system_setting`，并通过“环境变量默认值 + PostgreSQL 覆盖值”形成 effective settings
- 请求级运行日志已落库到 `runtime_log`，stdout JSON 日志继续保留
- 监控概览通过业务表聚合输出，不直接把 Prometheus 原始文本暴露给页面
- 新增页面：
  - `监控面板`
  - `运行日志`
  - `系统设置`

## 建议验证顺序

1. 上传一份 `DOCX / PDF`
2. 在前端确认任务状态变成 `已完成`
3. 如已切换新的 embedding 配置，先点击 `检查模型网关`
4. 再点击 `执行真实向量测试`，确认能看到真实请求返回的向量维度和耗时
5. 确认任务看板里需要重建的文档显示 `待重建`
6. 点击 `重建此文档`、`重建待重建文档` 或 `重建向量索引`
7. 到 PostgreSQL 查看 `knowledge_document` 和 `knowledge_chunk`
8. 点击 `删除此文档`，确认页面提示删除成功，且列表、数据库和对象存储中的该文档记录被清理
9. 提一个中文问题，例如 `北京酒店报销上限是多少？`
10. 确认返回答案、引用依据、置信度和 `检索 Trace`
11. 点击 `运行评测`，确认页面出现最新评测记录
12. 在 `Agent 运行记录` 面板执行一条示例工单，确认页面出现队列、时间线、规则判定和工具调用记录
13. 在 `人工复核队列` 面板确认刚才的工单已经进入队列，并能看到规则命中详情与建议动作
14. 进入 `系统设置` 面板，用 `admin` Token 修改默认租户、默认客户和问答阈值，刷新后确认知识库页、问答页和评测页默认值已经同步变化
15. 进入 `运行日志` 面板，确认刚才的上传、问答、评测和 Agent 请求都能按路径、请求 ID 和时间范围筛出来
16. 进入 `监控面板`，确认知识库、问答、评测、Agent 和失败请求的聚合数字发生对应变化
17. 将 `.env` 里的 `AUTH_ENABLED=true`，并给 `frontend/.env` 配置 `VITE_API_TOKEN`，确认：
   - `admin` Token 可以创建 Prompt
   - `operator` Token 创建 Prompt 返回 `403`
   - `reviewer` Token 可以查看 `人工复核队列`
18. 打开 `http://localhost:8000/metrics`，确认 Prometheus 文本指标可访问

## 真实模型网关验证

如果你已经有 OpenAI 兼容网关，可以在 `.env` 中配置：

```dotenv
LLM_PROVIDER=openai-compatible
LLM_MODEL_NAME=gpt-4o-mini
LLM_API_BASE_URL=https://your-gateway.example.com/v1
LLM_API_KEY=your-key

EMBEDDING_PROVIDER=openai-compatible
EMBEDDING_MODEL_NAME=text-embedding-3-small
EMBEDDING_API_BASE_URL=https://your-gateway.example.com/v1
EMBEDDING_API_KEY=your-key
EMBEDDING_DIMENSION=1536
EMBEDDING_BATCH_SIZE=16
EMBEDDING_MAX_RETRIES=2
```

然后重新启动后端，再做两件事：

1. 在知识入库面板先点击 `检查模型网关`
2. 再点击 `执行真实向量测试`，确认返回的 `向量维度` 与 `EMBEDDING_DIMENSION` 一致
3. 上传一份新文档，或对显示 `待重建` 的文档点击 `重建此文档` / `重建待重建文档`
4. 重新提问并查看 `retrieval_trace.model_name` 是否已经变成真实模型名
5. 如果 embedding 网关容易限流，先保持默认 `EMBEDDING_BATCH_SIZE=16` 和 `EMBEDDING_MAX_RETRIES=2`，再根据网关限制调整批量大小和重试次数

## 部署验证

后端镜像：

```powershell
docker build -f infra/docker/backend.Dockerfile -t travel-ops-api:local .
```

前端镜像：

```powershell
docker build -f infra/docker/frontend.Dockerfile -t travel-ops-web:local .
```

Kubernetes 清单校验：

```powershell
kubectl apply --dry-run=client -f infra/k8s
```

如果本机没有可用的 Docker Hub 网络或 Kubernetes 集群上下文，这两步需要换到具备相应网络与集群条件的环境执行。

## 测试命令

```powershell
make test-backend
make test-frontend
make test
```

当前已验证通过：

```powershell
pytest -q backend/tests
cd frontend && npm test
cd frontend && npm run build
```

## 文档同步约定

所有影响本地开发、部署、依赖接入、环境变量、端口或第三方服务连接方式的变更，都必须在同一次改动里同步更新 `README.md`。详细规则见 `docs/development-rules.md`。

## 问答检索隔离说明

- 政策问答页面现在支持填写 `租户 ID` 和 `客户 ID`
- 这两个值必须与知识入库时使用的值保持一致，否则检索会因为隔离条件不匹配而返回空证据
- 如果页面提示“当前没有检索到足够的政策证据”，先核对问答页和入库页的 `租户 ID / 客户 ID` 是否一致

## 2026-04-13 Iteration Addendum

This round added two concrete capabilities on top of the existing Task 9 baseline:

- real `LLM / Embedding` gateway readiness checks and smoke tests
- retrieval-chain hardening for production-like usage

### New APIs

- `GET /api/chat/llm-readiness`
- `POST /api/chat/llm-smoke-test`
- `GET /api/knowledge/embedding-readiness`
- `POST /api/knowledge/embedding-smoke-test`

### New UI entry points

- `系统设置 -> LLM 网关联调`
- `系统设置 -> Embedding 网关联调`
- `评测运行 -> 本次评测配置`

### Recommended validation flow

1. Configure real `LLM_*` and `EMBEDDING_*` values in `.env`.
2. Restart the backend service.
3. Use `系统设置` to run `检查 LLM 网关` and `检查 Embedding 网关`.
4. Run `执行 LLM 烟雾测试` and `执行 Embedding 烟雾测试`.
5. Rebuild stale knowledge documents from `知识库管理`.
6. Rerun `评测运行` and confirm `本次评测配置` has switched to the real models.

### Retrieval-chain hardening in this round

- Query rewrite now happens once at the RAG entry point instead of being repeated inside every retriever.
- Dense retrieval now loads only the matched `chunk_id` rows from PostgreSQL instead of scanning all chunks in the tenant scope.
- Lexical retrieval now narrows candidates in the database first, then scores them in Python.
- `eval_run.metrics` now stores a `provider_snapshot` so every evaluation run can be traced back to the actual LLM, embedding model, and vector store configuration.

### Remaining boundary

- This round implements the gateway integration hooks and verification workflow.
- If real gateway credentials are missing, the system still falls back to local `deterministic` providers by design.
- Whether retrieval quality is good enough for enterprise rollout still depends on rerunning evaluation against your real knowledge base and real model gateway.

### Provider notes

- DashScope / 百炼 `text-embedding-v4` currently enforces a maximum embedding batch size of `10`.
- When you use `https://dashscope.aliyuncs.com/compatible-mode/v1`, set `EMBEDDING_BATCH_SIZE=10` or lower in `.env`.
- The backend now also caps DashScope embedding batches to `10` automatically, so knowledge reindexing does not fail with a raw upstream batch-size error.
