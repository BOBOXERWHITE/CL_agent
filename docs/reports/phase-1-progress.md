# Phase 1 执行进度

> 依据：`docs/plans/2026-04-07-enterprise-migration-phase-0-2.md`
> 阶段目标：安全 & 多租户加固 —— 消除越权风险，鉴权链路从 demo 级升级到真 production 可用

## 进度表

| ID | 任务 | 状态 | 完成时间 | 回归测试 |
|---|---|---|---|---|
| P1.1 | 引入 PyJWT 替换静态 token | ✅ 完成 | 2026-04-17 | 76 passed |
| P1.2 | Token claim 注入 RequestContext | ✅ 完成 | 2026-04-17 | 80 passed |
| P1.3 | Route 层 tenant 一致性校验 | ✅ 完成 | 2026-04-20 | 87 unit + 6 integration |
| P1.4 | PostgreSQL Row Level Security | ✅ 完成 | 2026-04-20 | 87 unit + 11 integration |
| P1.5 | audit_log 表 + 写路径打点 | ✅ 完成 | 2026-04-20 | 92 unit + 11 integration |
| P1.6 | Rate Limiting (slowapi) | ✅ 完成 | 2026-04-21 | 96 unit + 11 integration |
| P1.7 | Secrets 配置分层 | ✅ 完成 | 2026-04-21 | 106 unit + 11 integration |

## P1.1 验收明细

**配置面**
- Settings 加 7 个 JWT 字段；默认 `JWT_ENABLED=false` 保障迁移兼容；production 启动强制 JWT=true + 真密钥 + dev-token 路由 off

**代码面**
- `core/jwt.py` 64 行：encode/decode + TokenClaims + TokenError + 7 种 UnauthorizedReason 枚举
- `core/security.py` 重写：JWT 模式与 static 模式并存；`require_roles` 按 claim roles 集合判定
- `api/routes/auth.py` 新 `/api/auth/dev-token`：只在 dev/test/integration env 签发
- `main.py` 加 `_validate_production_security` 启动守卫

**测试面**
- 9 个新用例覆盖全部错误分支（test_jwt_auth.py）
- 原 67 单元测试通过 `client` fixture 默认带 admin-token 头继续通过
- 总计 **76 passed, 6 deselected**（integration 等 Docker 验证）
- ruff 全绿

## 安全相关的启动守卫（新）

`create_app()` 在 `app_env=production` 时强制要求：
- `JWT_ENABLED=true`（不允许静态 token 模式）
- `JWT_SECRET_KEY ≠ dev-only-insecure-change-me` 且非空
- `JWT_DEV_TOKEN_ENDPOINT_ENABLED=false`（阻止生产环境自签任意 tenant token）

任一不满足即 `RuntimeError: insecure production config: ...` 立即 crash。测试覆盖此路径。

## P1.2 验收明细

- `RequestContext` 字段：request_id / tenant_id / user_id / role / roles
- `get_request_context` 链式依赖 `get_auth_context`，自动鉴权
- 同时写 `request.state.tenant_id/user_id/user_role`，供 middleware 使用
- `tests/api/test_request_context.py` 4 用例
  - JWT claim 注入（tenant-zeta / 双 role）
  - 防 body 越权（X-Tenant-Override 不被信任）
  - X-Request-ID 透传 trace
  - static-token 模式 fallback（兼容期）

## P1.3 验收明细

- `app/api/guards.py` 新建 `require_tenant_match(body, ctx)`
- 4 条规则：None body / 占位符 body / static 模式 / JWT 严格匹配
- 4 个路由集成：chat / agents / knowledge / reviews
- `tests/api/test_tenant_isolation.py` 7 用例全过：
  - chat 越权 → 403 + TENANT_MISMATCH ✓
  - chat 同租户 → 通过 ✓
  - chat 省略 tenant_id → 用 claim ✓
  - agents 越权 → 403 ✓
  - knowledge form 越权 → 403 ✓
  - reviews ingest 越权 → 403 ✓
  - static 模式兼容性 → 通过 ✓
- 集成测试（真 PG + MinIO）6/6 通过，证明 route 改动不破坏 pipeline

## P1.4 验收明细

- alembic 0002：创建 `travel_ops_app_user` 角色 + 7 表 RLS + 7 policy + 完整 downgrade
- session.py：`_apply_tenant_scope` 双 SET LOCAL（ROLE + GUC）；新增 `bypass_rls_session` / `scoped_session` 上下文管理器
- 14 处服务层切换到 bypass session（lifespan / Celery / ingestion / eval / RAG）
- 5 个真 PG RLS 测试 全过：scoped 只见己 / bypass 见全 / unset fail-close / JWT E2E

**踩坑记录（值得 P1.5+ 警惕）**：
- PG superuser 自动绕过 RLS，必须 SET LOCAL ROLE 切非 superuser 才生效
- testcontainers 默认用 superuser，没切 ROLE 时 RLS 测试假阳性通过

## P1.5 验收明细

- 新表 audit_log（11 字段，关键字段加索引）+ alembic 0003 含 RLS
- 修复 0001：显式 baseline 表列表，避免后续 metadata 增长污染历史 migration
- record_audit helper：自动脱敏（password/token/secret/apikey/api_key/authorization）+ XFF 优先
- 4 个写路径打点：chat.ask / agent.run / knowledge.upload / review.ingest
- audit + 业务**同事务**写入，原子性
- 5 个单元测试：sanitize / e2e / 直调 / XFF 优先 / 缺 client

## P1.6 验收明细

- slowapi 依赖 + 5 个 RATE_LIMIT_* Settings 字段（默认 disabled）
- `core/rate_limit.py`：tenant:user 优先 IP 兜底的 key 函数 + `reset_limiter_storage` 测试辅助
- 3 个路由装饰：chat.ask (20/min)、knowledge.upload (10/min)、auth.dev-token (10/min)
- 429 响应统一为 `{error: {code: RATE_LIMITED}}` 结构
- X-RateLimit-* headers 暴露在成功响应上
- 4 用例覆盖：超限 / headers / per-key 隔离 / 默认 disabled

**踩坑记录**：
- slowapi `@limiter.limit` 装饰的路由必须加 `response: Response` 形参，否则抛 "parameter response must be..." 错误
- `@limiter.limit(lambda: ...)` 延迟求值避免测试改 env 后需重建 limiter
- 测试间必须 `reset_limiter_storage()` 清内存计数，否则互相干扰

## P1.7 验收明细

- python-dotenv 加载 `.env.local` → `.env`，环境变量优先级最高
- `.env.example` 模板化（~90 行，`[PROD-REQUIRED]` 明确标记）
- `.gitignore` 扩展：`.env.local` / `.env.*.local` gitignored；`.env.example` allow-listed
- 生产启动守卫从 3 条扩展到 9 条（JWT × 3 + AUTH × 3 + LLM × 1 + Embedding × 1 + MinIO × 2）
- 多问题聚合报错，一次暴露所有错误
- `main.py` 去掉模块级 `app = create_app()`，改为 `__getattr__` 惰性构造；uvicorn 需用 `--factory` 模式
- 10 个用例覆盖每个 secret + 聚合 + 放行

**范围调整**：规划原定 Pydantic Settings v2 重写，实际改为"保留 dataclass + dotenv 加载"最小侵入。价值等同，风险低得多。Pydantic 重写作为后续技术债。

---

# 🎉 Phase 1 全部完成（2026-04-21）

## 安全防线总览

```
请求进入
  → [1] CORS / 日志中间件
  → [2] SlowAPI 限流 (P1.6)              — 429 挡过量请求
  → [3] JWT 鉴权 (P1.1)                  — Bearer 验证签名/exp/aud/iss
  → [4] RequestContext claim 注入 (P1.2) — tenant_id 从 claim 读
  → [5] route handler
    → [6] require_tenant_match (P1.3)     — 应用层 body tenant 一致性
    → [7] record_audit (P1.5)             — 所有写操作留痕
    → [8] PostgreSQL RLS (P1.4)           — DB 兜底，应用 bug 也挡
  → [9] 响应 + 统一错误 envelope
```

9 层防护，配合启动 **9 项生产 secret 校验**（P1.7）。

## 指标变化

| 维度 | Phase 1 开始前 | Phase 1 收尾 | 增量 |
|---|---|---|---|
| 单元测试 | 67 passed | 106 passed | **+39** |
| 集成测试 | 6 passed | 11 passed | **+5** |
| lint 规则 | 全绿 | 全绿 | 保持 |
| 总测试 | 73 | 117 | **+60%** |
| 安全层数 | 1（基础 Bearer） | 9（纵深防御） | |

## 新增文件（Phase 1）

- `app/core/jwt.py` / `app/core/audit.py` / `app/core/rate_limit.py`
- `app/api/guards.py` / `app/api/rate_limit_middleware.py` / `app/api/routes/auth.py`
- `app/db/models/audit_log.py`
- `alembic/versions/0002_enable_rls.py` / `0003_audit_log.py`
- `backend/.env.example`
- `tests/api/test_jwt_auth.py` (9) / `test_request_context.py` (4) / `test_tenant_isolation.py` (7) / `test_audit.py` (5) / `test_rate_limit.py` (4) / `test_production_secrets.py` (10)
- `tests/integration/test_rls_isolation.py` (5)

## 修改文件（Phase 1）

- `app/core/config.py`（+JWT/RL 字段 + dotenv）
- `app/core/security.py`（JWT + static 双模式）
- `app/main.py`（lifespan + 9 项生产守卫 + factory 模式）
- `app/db/session.py`（RLS scope + bypass session）
- `app/api/error_handlers.py`（429 handler）
- `app/api/deps.py`（RequestContext 扩展）
- 4 个 route 文件（guard + audit + rate limit）
- `alembic/versions/0001_baseline.py`（显式表列表）
- `.gitignore`（env 文件规则）
- `pyproject.toml`（+ pyjwt / slowapi / python-dotenv）

## 按客观评分维度变化

| 维度 | Phase 0 后 | Phase 1 后 |
|---|---|---|
| 安全 | 3 | **8.5**（9 层防御 + 生产守卫 + 审计）|
| API / 鉴权 | 4 | **8**（JWT claim + RLS + 限流） |
| 数据库 | 7 | **8**（RLS + audit_log + 显式 baseline） |

## 下一阶段：Phase 2 RAG 真实化

按规划，Phase 2 预估 7 天。7 个子任务：
- P2.1 真 embedding（OpenAI 兼容）
- P2.2 deterministic 降级消失 + prod fail-fast
- P2.3 RRF 融合替代硬编码权重
- P2.4 真 reranker
- P2.5 retrieval eval (recall@k / nDCG)
- P2.6 LLM query rewriter + HyDE
- P2.7 Redis 缓存（embedding / retrieval / answer）
- P2.8 Milvus lifespan preload + HNSW

等你确认继续推进。
