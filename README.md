# CL_agent

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

## 当前可验证能力

### Task 2：知识入库

- 上传接口会写入 `PostgreSQL` 文档记录
- 原始文件会写入 `MinIO`
- 切块向量会写入 `Milvus`

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

## 建议验证顺序

1. 上传一份 `DOCX / PDF`
2. 在前端确认任务状态变成 `已完成`
3. 到 PostgreSQL 查看 `knowledge_document` 和 `knowledge_chunk`
4. 提一个中文问题，例如 `北京酒店报销上限是多少？`
5. 确认返回答案、引用依据、置信度和 `检索 Trace`
6. 点击 `运行评测`，确认页面出现最新评测记录
7. 在 `Agent 运行记录` 面板执行一条示例工单，确认页面出现队列、时间线、规则判定和工具调用记录
8. 在 `人工复核队列` 面板确认刚才的工单已经进入队列，并能看到规则命中详情与建议动作
9. 将 `.env` 里的 `AUTH_ENABLED=true`，并给 `frontend/.env` 配置 `VITE_API_TOKEN`，确认：
   - `admin` Token 可以创建 Prompt
   - `operator` Token 创建 Prompt 返回 `403`
   - `reviewer` Token 可以查看 `人工复核队列`
10. 打开 `http://localhost:8000/metrics`，确认 Prometheus 文本指标可访问

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
```

然后重新启动后端，再做两件事：

1. 上传一份新文档，让知识块按真实 embedding 重建
2. 重新提问并查看 `retrieval_trace.model_name` 是否已经变成真实模型名

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
