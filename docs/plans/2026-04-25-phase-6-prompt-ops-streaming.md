# Phase 6 规划：Prompt 运营化 + 流式响应

> 生成时间：2026-04-25
> 依据：
> - `docs/architecture-review.md` 第七章 P2："prompt 版本管理 + A/B + 在线评估"
> - `docs/reports/phase-5-patch-mini-sprint.md` 第七章遗留项：SSE streaming / AsyncSession / Prompt A/B
> 范围：`backend/app/services/prompts/` + `backend/app/db/models/prompt_template.py` + 新增 `app/api/routes/streaming.py`
> 工期：8 工作日
> 目标评分跃迁：运营能力 +（规划文档无明确分数；综合 8.8 → 9.0）

---

## 零、为什么 Phase 6 选 Prompt 运营化 + 流式

Phase 5 补丁结束后剩下三块大的：

1. **Prompt 运营化**：当前只支持 `active` / `draft` 两态的单 active 版本；没有 A/B、没有在线信号反馈、没有自动/手动升降级
2. **流式响应**：长答案要等全文生成完才回给前端；UX 落后一个时代
3. **AsyncSession 全量迁移**：`asyncpg` + SQLAlchemy 2.x async；大工程，风险大

前两块贴业务、能立刻看到效果；AsyncSession 是工程债，做完评分不涨、回归风险高 —— 留给未来真性能瓶颈驱动再做。

---

## 一、范围判断：做什么 / 不做什么

### ✅ 做

| 痛点 | 处置 |
|---|---|
| Prompt 单 active → 不能 A/B | 扩展状态机：`draft` / `candidate` / `active` / `archived`；多条 candidate 按 `traffic_percent` 分流 |
| Prompt 选择不被记录 | 新表 `prompt_selection_log`：每次 chat/agent run 记录选到了哪个 version + 用户反馈 |
| 没有在线 reward signal | `POST /api/chat/ask/{session_id}/feedback` + 聚合到 prompt 维度 |
| 没有 promote/demote 流程 | `POST /api/prompt-templates/{id}/promote` + `/rollback` + state-machine guard |
| 长答案体验差 | `GET /api/chat/ask/stream` (SSE) — 拆开 `answer_policy_question_async`，把 generate 的 token stream 逐段往外推 |
| Streaming 下 token usage 统计 | streaming generator 最后 yield 一次 `[DONE]` 并把 `token_usage` 写到对应 event |

### ❌ 不做（记录到"下一步"）

| 项 | 推迟到 |
|---|---|
| AsyncSession + asyncpg 全量迁移 | 业务驱动（出现真性能瓶颈再做）|
| 多目标 bandit 算法自动升级 | 业务驱动，先做手动 promote |
| Prompt template inheritance / partials | Phase 7 |
| Response-side PII 脱敏 / guardrails | Phase 7（运营化）|
| WebSocket 双向（SSE 只是单向 server push）| 业务驱动 |
| Prompt diff 可视化 UI | 前端活，不在本规划 |

---

## 二、子任务拆解（6 个）

| ID | 任务 | 工期 | 核心改动 |
|---|---|---|---|
| P6.1 | Prompt 状态机 + traffic_percent 列 | 1d | `prompt_template` 加 `traffic_percent`；状态枚举扩展；migration |
| P6.2 | A/B 选择器 + `prompt_selection_log` | 1.5d | 新表 + 确定性 hash 路由 + service / query 接入点 |
| P6.3 | 反馈采集 + 指标聚合 | 1.5d | `POST /api/chat/feedback` + `prompt_feedback` 表 + `GET /api/prompt-templates/{id}/stats` |
| P6.4 | Promote / rollback API + state machine | 1d | 新路由 + guard（不允许 archived → active 等）|
| P6.5 | SSE streaming `/api/chat/ask/stream` | 2d | `LlmClient.stream_answer_async`（async generator）+ 路由用 `StreamingResponse`；token usage 统计落 task 侧 |
| P6.6 | Phase 6 review | 0.5d | 报告 + 评分复核 |

**净工期 7.5 天 + 0.5 天 buffer = 8 天**。

---

## 三、详细设计

### P6.1 Prompt 状态机扩展

**现状**：`PromptTemplate.status ∈ {draft, active}`，`activate_prompt_template` 把同 task_type 其他全部改 draft，唯一 active 上位。

**改造**：
- 状态枚举：`draft` → `candidate` → `active` ↔ `archived`
  - `draft`：编辑中，不参与分流
  - `candidate`：A/B 试验中，按 `traffic_percent` 分流
  - `active`：主推版本（唯一 per task_type）
  - `archived`：退役（历史记录，不再选中）
- 新字段 `traffic_percent: int` (0-100，只对 candidate 生效)
- Migration：老 `draft` 数据保留；加列 + 索引
- Selection 规则（P6.2 实现）：
  1. 同 task_type 有 candidates → 按 tenant_id hash 分流；剩余流量走 active
  2. 无 candidates → 直接走 active
  3. 无 active → 系统默认（现有 fallback）

**测试**：
- 状态迁移合法性：`draft → candidate` ✓，`active → archived` ✓，`archived → active` ✗
- traffic_percent 超 100 总和 → 拒绝

### P6.2 A/B 选择器 + 选择日志

**新表 `prompt_selection_log`**：
```python
class PromptSelectionLog(Base):
    id: Mapped[int]
    request_id: Mapped[str]            # join RagRecallLog / audit
    tenant_id: Mapped[str]
    task_type: Mapped[str]
    prompt_template_id: Mapped[str]    # which variant got picked
    version: Mapped[int]
    variant_group: Mapped[str]         # "active" / "candidate_v2" / "default"
    selected_reason: Mapped[str]       # "traffic_routed" / "sole_active" / "fallback"
    created_at: Mapped[datetime]
```

**选择器**：`select_prompt_variant(session, task_type, tenant_id, request_id)` —— 决定该次请求用哪个 version，写一条 `prompt_selection_log`。

**hash 分流**：
- `h = sha256(f"{tenant_id}|{task_type}").hexdigest()[:8]` → int mod 100
- 按 candidate 的 `traffic_percent` 累加阈值匹配；剩余流量回落到 active
- **确定性**：同 tenant_id 同 task_type 始终选同一 variant → 用户不会看到 prompt 随机跳动；A/B 更干净

**接入点**：`get_prompt_selection` 被 `chat.ask` + `policy_graph` + `tools` 调用；改造成 `select_prompt_variant` 即可

### P6.3 反馈采集 + 指标聚合

**反馈端点**：`POST /api/chat/sessions/{session_id}/feedback`
- body: `{rating: "up" | "down", comment?: string}`
- 通过 `ChatMessage.metadata_json.prompt_template_id` 反查 + 写 `prompt_feedback` 行

**新表 `prompt_feedback`**：
```python
class PromptFeedback(Base):
    id / session_id / tenant_id / prompt_template_id / rating / comment / created_at
```

**聚合端点**：`GET /api/prompt-templates/{id}/stats`
- 返回：total_requests / up_count / down_count / up_rate / avg_latency_ms / avg_confidence
- Join `prompt_selection_log` + `prompt_feedback` + `rag_recall_log`

### P6.4 Promote / Rollback API

**端点**：
- `POST /api/prompt-templates/{id}/promote` - candidate → active（原 active 降为 archived）
- `POST /api/prompt-templates/{id}/rollback` - active → archived；最新 archived → active（管理员恢复）
- 权限：admin only
- 守卫：draft 不能 promote；archived 不能直接 → active（必须经 candidate）

**审计**：每次转换写 `audit_log` + Celery 任务预热缓存

### P6.5 SSE streaming

**新 `POST /api/chat/ask/stream`**（返回 `text/event-stream`）：
- body 同 `/ask`
- 响应：每 token 一个 `data: {"delta": "..."}\n\n`；结束 `data: {"event": "done", "citations": [...], "token_usage": {...}}\n\n`
- token usage 累加到 `token_usage_daily` 同 `/ask`

**底层**：
- 在 `LlmClient` 加 `async def stream_answer_async(...) -> AsyncIterator[StreamToken]`
- OpenAI-compatible `/chat/completions` with `stream=true` → SSE 解析 → yield
- Deterministic client 也提供 async generator（一次性 yield 整段）以便测试

**测试**：
- 使用 `httpx.AsyncClient` + `ASGITransport` 消费 SSE stream，断言事件序列
- stream 中途断开：底层 LLM 的连接释放 / token usage 丢弃（不写库）
- 确定性模式：mock stream yields 3 chunks，断言客户端收到 3 + [DONE]

### P6.6 Phase 6 review

同 Phase 1-5 format：子任务验收清单 / 问题清单 / 遗留 / 评分复核 / 下一步

---

## 四、依赖关系图

```
P6.1 状态机 + traffic_percent (基础)
  ↓
P6.2 A/B 选择器 + selection_log ←── 读 traffic_percent
  ↓
P6.3 反馈采集 + stats 聚合 ←── join selection_log
  ↓
P6.4 promote / rollback (独立)
  ↓
P6.5 SSE streaming (独立)
  ↓
P6.6 review
```

**建议执行顺序**：P6.1 → P6.2 → P6.3 → P6.4 → P6.5 → P6.6

---

## 五、契约稳定性承诺

| 类别 | 稳定性 |
|---|---|
| `/api/chat/ask` / `/api/agents/runs` / `/api/tasks/*` / `/api/usage` 响应字段 | 不变 |
| `get_prompt_selection` 函数签名 | 不变（向后兼容：调用侧仍能拿 `PromptSelection` dataclass）|
| `PromptTemplate.status` 字段 | 加字符串扩展，不新增非空列 |
| `prompt_selection_log` / `prompt_feedback` | 新表，不影响老数据 |
| `AgentExecutionResult` / `PolicyAnswerResult` | 不变 |
| `/api/chat/ask/stream` | 新增端点（老 `/ask` 继续可用）|

---

## 六、不做但要记录

| 项 | 推迟到 |
|---|---|
| AsyncSession + asyncpg 全量迁移 | 业务驱动 |
| 多目标 bandit 算法 auto-promote | 手动 promote 后再看需求 |
| Prompt template inheritance / partials | Phase 7 |
| Response-side PII 脱敏 | Phase 7 运营化 |
| WebSocket 双向通信 | 业务驱动 |
| Frontend prompt diff 可视化 | 前端团队 |

---

## 七、总验收

完成 Phase 6 后应该能：

1. **创建一个 candidate prompt 版本**，设 traffic_percent=20，20% 请求命中它（按 tenant hash 确定性）
2. **查询 `GET /api/prompt-templates/{id}/stats`** 返回 up/down 评分、平均置信度、平均延迟
3. **反馈 → promote**：candidate 胜出后 admin 点 promote，该 candidate 升为 active，原 active 降 archived
4. **`curl POST /api/chat/ask/stream`** 看到真正的 token-by-token 流
5. **rollback** 把最近 archived 的版本推回 active

**评分预期**：综合项目 8.8 → 9.0

---

## 八、下一步

等用户：
- **「OK，按此顺序执行」** → 开 P6.1（状态机 + traffic_percent）
- **「先做 P6.5 看看 SSE」** → 改执行顺序
- **「AsyncSession 必须做」** → 加 P6.7 AsyncSession 迁移（工期 +4 天）

流程同 Phase 1-5：每个子任务完成就回归 + 更新 `docs/reports/phase-6-progress.md`。
