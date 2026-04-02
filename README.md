# CL_agent

基于差旅场景的企业级 `RAG + Agent` 项目，当前技术路线为 `FastAPI + React + PostgreSQL + Redis + MinIO + Milvus + LlamaIndex + LangGraph`。

## 文档

- 实施计划：`docs/plans/2026-04-01-travel-ops-copilot.md`
- 开发规则：`docs/development-rules.md`

## 本地开发前提

- Docker Desktop 已安装并可执行 `docker compose`
- Python `3.13+`
- Node.js 与 `npm`

## 配置文件

- 仓库根目录使用 `.env.example` 作为后端配置模板
- 前端开发环境使用 `frontend/.env.example` 作为 Vite 配置模板
- 前端依赖安装使用 `frontend/.npmrc` 中的镜像源配置，避免默认私有源超时

首次启动前可复制环境变量文件：

```powershell
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env
```

## 基础依赖启动

启动 PostgreSQL、Redis、MinIO、etcd、Milvus：

```powershell
docker compose up -d postgres redis minio etcd milvus
```

查看容器状态：

```powershell
docker compose ps
```

查看 Milvus 启动日志：

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
| PostgreSQL | `5432` | 数据库 |
| Redis | `6379` | 缓存与队列 |
| MinIO API | `9000` | 对象存储 API |
| MinIO Console | `9001` | 管理控制台 |
| etcd | `2379` | Milvus 元数据依赖 |
| Milvus gRPC | `19530` | 向量检索接入 |
| Milvus HTTP | `9091` | 健康检查与管理接口 |

默认账号信息来自 `.env.example`：

- PostgreSQL: `travel_ops / travel_ops / travel_ops`
- MinIO: `minioadmin / minioadmin123`
- MinIO Bucket: `knowledge`
- Milvus Collection: `knowledge_chunks`

## 关键环境变量

- `DATABASE_URL`: 后端结构化数据存储，默认指向本机 Docker PostgreSQL
- `OBJECT_STORAGE_PROVIDER`: 默认 `minio`
- `VECTOR_STORE_PROVIDER`: 默认 `milvus`
- `CELERY_TASK_ALWAYS_EAGER`: 默认 `true`，开发阶段上传任务在 API 进程内立即执行，无需单独启动 worker
- `CHAT_TOP_K`: 问答阶段默认取前 `3` 条候选证据
- `CHAT_CONFIDENCE_THRESHOLD`: 默认 `0.2`，低于阈值时返回低置信度兜底答复
- `VITE_API_BASE_URL`: 前端请求后端 API 的地址，开发模式下默认写成 `http://localhost:8000`

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

当前 Task 2 的文档入库链路已经接通：

- 上传接口会写入 PostgreSQL 文档记录
- 原始文件会写入 MinIO
- 切块向量会写入 Milvus
- 开发环境下使用确定性本地 embedding，便于无模型密钥先完成链路联调
- Celery 目前默认 eager 模式，因此不需要先起独立 worker

当前 Task 3 的政策问答链路也已经接通：

- `POST /api/chat/ask` 返回 `answer`、`confidence`、`citations` 和 `session_id`
- 后端会持久化 `chat_session` 与 `chat_message`
- 前端主页已包含 `Policy Q&A` 区块，可直接查看答案、引用和置信度
- 当前答案生成仍是本地可解释实现，目的是先把“检索证据 -> 答案 -> 会话日志”闭环跑通

## 测试命令

```powershell
make test-backend
make test-frontend
make test
```

## 文档同步约定

所有影响本地开发、部署或依赖接入的配置变更，都必须在同一次改动中同步更新 `README.md`。详细规则见 `docs/development-rules.md`。
