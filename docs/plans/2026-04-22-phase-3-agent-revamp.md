# Phase 3 规划：Agent 真实化

> 生成时间：2026-04-22
> 依据：`docs/plans/2026-04-07-enterprise-migration-phase-0-2.md` 第 7 章"不做但要记录"项 1 明确推迟到 Phase 3；`docs/architecture-review.md` 中 Agent 评分 3.5/10 是全项目最低
> 范围：`backend/app/services/agents/` 全面升级
> 工期：10 工作日
> 目标评分跃迁：Agent 层 3.5 → 7.5

---

## 零、为什么 Phase 3 选 Agent

Phase 0-2 完成后各维度评分：

| 维度 | 当前 | 全项目最低？ |
|---|---|---|
| 数据库 | 8.0 | |
| API/鉴权 | 8.0 | |
| RAG | 7.5 | |
| 后端工程 | 7.5 | |
| 安全 | 8.5 | |
| **Agent** | **3.5** | **✅** |
| 可观测性 | 4.0 | |
| 异步/扩展性 | 3.5 | |

Agent 和 async 同分垫底。差别：
- **Agent 是业务功能本身**（用户体验直接挂钩）
- **Async 是基建**（性能瓶颈未到前不见效）

所以 Phase 3 做 Agent、Phase 4 做 Async。

---

## 一、当前 Agent 层的真实问题（证据）

从 `docs/architecture-review.md` 第 5 章抽出，再对照当前代码：

| 问题 | 证据 | 影响 |
|---|---|---|
| `anomaly_graph.py` 完全不读入参，返回常量 | 38 行的文件，`confidence=0.74` 写死 | 这个 agent 不工作 |
| `ticket_router` 硬编码 confidence=0.86 | `ticket_router_graph.py` | 置信度不能区分好/坏 |
| `router.py` 关键词匹配选 agent | 85 行硬编码关键词列表 | 加 agent 必须改代码 |
| 所有 graph 都是"一次调用即返回" | `graph.py` 42 行 | 没有 ReAct / 多步推理 |
| `tools.py` mock 实现 | 34 行，`lookup_order_details` 返回硬编码 | 工具系统不存在 |
| Timeline 用字符串 free-form | `state.py` 中 `TimelineStep.status: str` | 做不了聚合分析 |
| 没有 agent memory | — | 对话无上下文 |
| 没有 HITL 中断/恢复 | — | 长流程没法暂停等人 |

**一句话**：现在不是 agent，是"关键词路由 + 硬编码结果生成器"。

---

## 二、子任务拆解（8 个）

| ID | 任务 | 工期 | 核心改动 |
|---|---|---|---|
| P3.1 | 引入 state machine 框架（LangGraph 或自写） | 1.5d | 新 `app/services/agents/engine.py` |
| P3.2 | Router 改 LLM 意图分类 + embedding fallback | 1.5d | 重写 `router.py` |
| P3.3 | `policy_graph` 真 ReAct loop（多轮工具调用） | 2d | 重写 `policy_graph.py` |
| P3.4 | `anomaly_graph` 真实实现（规则 + LLM） | 1d | 重写 `anomaly_graph.py` |
| P3.5 | Tool 系统（JSON Schema + retry + timeout + circuit） | 1.5d | 重写 `tools.py` + 新 `tool_registry.py` |
| P3.6 | Agent memory（短期 conversation + 长期 vector） | 1d | 新 `app/services/agents/memory.py` |
| P3.7 | Timeline 事件 enum + 独立表 | 0.5d | 新 `app/db/models/agent_event.py` + migration |
| P3.8 | HITL 中断 / 恢复 | 1d | 新 `app/api/routes/agent_tasks.py` |

**净工期 10 天**，留 1-2 天 buffer 做 integration test 和 review。

---

## 三、详细设计

### P3.1 State Machine 框架

**选型**：**自写最小 state machine**，不引入 LangGraph。

**理由**：
- LangGraph 适合复杂多 agent 协作，我们只有 3 个 agent
- 增加一个大依赖（含 pydantic / langchain-core），提升学习成本
- 自写核心 ~100 行，可控度更高，和现有 audit / cache 体系容易对齐

**接口设计**：

```python
# app/services/agents/engine.py
@dataclass(frozen=True)
class NodeResult:
    next_node: str | None          # None 表示终止
    state_delta: dict[str, Any]    # 合并到 GraphState
    events: list[TimelineEvent]    # 结构化事件 list

class Graph:
    def __init__(self, nodes: dict[str, NodeFn], entry: str): ...
    def run(self, initial_state: GraphState, *, max_steps: int = 10) -> GraphRunResult: ...
```

**GraphState**：
- `messages: list[Message]`
- `tool_calls: list[ToolCallRecord]`
- `scratchpad: dict[str, Any]`（工具输出 / 中间结论 / ReAct observation）
- `memory: list[MemoryEntry]`（P3.6 注入）
- `tenant_id`, `user_id`, `request_id`（来自 RequestContext）

**保护**：
- `max_steps` 防死循环
- 每个节点开始前打 `TimelineEvent.node_start`，结束打 `node_end`
- 工具调用前后打事件（由 P3.5 tool runner 负责）

### P3.2 LLM Router

**现状**：`router.py` 用 `POLICY_KEYWORDS / TICKET_KEYWORDS / ANOMALY_KEYWORDS` 做 substring match。

**改造**：
1. 主路径：调 LLM 做意图分类（1 个 token 返回），3 个意图枚举
2. 回退 1：embedding 相似度（query vs 3 个 intent 描述的 embedding），argmax
3. 回退 2：保留原关键词匹配

**Prompt**：

```
系统提示：你是意图分类器。用户的问题属于以下三类之一，只返回枚举值，不要解释。
  POLICY_QA      — 差旅政策咨询
  TICKET_TRIAGE  — 工单路由 / 异常排查
  ORDER_ANOMALY  — 订单异常 / 退款争议
```

**Config**：`AGENT_ROUTER_PROVIDER=llm | embedding | keyword`，默认 `llm`，缺配置自动降级。

**测试**：3 个意图 × 2 (LLM 命中 / LLM 挂了走 embedding)，共 6 个用例。

### P3.3 Policy ReAct Loop

**现状**：`policy_graph.py` 调一次 RAG 即返回。

**改造**：ReAct loop 的节点图

```
    entry
      ↓
    [plan] — 决定调哪个工具 / 是否直接回答
      ↓
    [tool_exec] — 调 RAG / 外部 API 等
      ↓
    [observe] — 把工具结果写进 scratchpad
      ↓
    [reflect] — 决定"够了→finalize" 或 "还不够→plan"
      ↓ (loop)
    [finalize] — 基于完整 scratchpad 生成最终答案
```

**收敛**：`max_steps=5`。每一轮 plan 都带上历史 scratchpad；finalize 用 LLM 基于 evidence 生成答案（和当前 `answer_policy_question` 一样，但输入是多轮累积的 evidence）。

**Backward compat**：若 LLM 不可用（deterministic provider），退化为 1 轮 plan → 1 工具调用 → finalize，等价于现在的行为。

### P3.4 Anomaly Graph 真实实现

**现状**：完全不看输入，返回常量。

**改造**：
- 节点：`load_order` → `rule_check` → `llm_diagnose` → `route_decision`
- `load_order`：调 `order_lookup` 工具（P3.5 改造后）
- `rule_check`：调现有 `rules.engine.evaluate_rules`（复用！）
- `llm_diagnose`：LLM 根据 order 详情 + rule 结果给诊断结论
- `route_decision`：根据规则决定去 ops-review / customer-service / auto-approve

**confidence**：基于 LLM 返回 + rule_result 综合算，不再写死。

### P3.5 Tool 系统重构

**当前 `tools.py`**：34 行，`lookup_ticket_queue` / `lookup_order_details` 硬编码字典。

**改造**：
1. `Tool` Protocol：`name`, `description`, `input_schema` (Pydantic), `output_schema`, `invoke(input) -> output`
2. `ToolRegistry`：注册中心，支持按名查找
3. `ToolRunner`：调用时的 wrapper
   - JSON schema 输入校验（Pydantic）
   - Timeout（`asyncio.wait_for` / httpx timeout）
   - Retry（指数退避，默认 2 次）
   - Circuit breaker（失败率超阈值自动熔断 30s）
   - 全链路日志 + `ToolCallLog` 持久化
4. 保留现有 `lookup_ticket_queue` / `lookup_order_details` 作为 mock 实现，但改用新 interface
5. 新增一个 `policy_search` 工具，实际调 `rag.query_engine.answer_policy_question`

**testable**：`ToolRegistry` 可注入 fake tools，不依赖外部 HTTP。

### P3.6 Agent Memory

**两级 memory**：

1. **短期（conversation memory）**：`ChatSession` 的最近 N 条 `ChatMessage` 直接读，不需要新表。Plan 节点的 prompt 里注入。
2. **长期（semantic memory）**：新 `app/services/agents/memory.py`，提供：
   - `remember(tenant, user, key, content)` → 写进 Milvus（新 collection `agent_memory`）
   - `recall(tenant, user, query, top_k)` → embedding 检索 + 过 RLS
   - 关键节点（`finalize` / 工具成功）自动 remember

**复用 Phase 2 基建**：embedding / vector store / cache 都直接用。

### P3.7 Timeline 事件结构化

**现状**：`AgentRun.timeline_json` 是 JSON 列，字符串 status + free-form detail。

**改造**：
- 新表 `agent_event`：id / agent_run_id(FK) / sequence / event_type(ENUM) / node_name / payload_json / created_at
- `event_type` enum：`NODE_START / NODE_END / TOOL_CALL_START / TOOL_CALL_END / LLM_CALL / MEMORY_WRITE / MEMORY_READ / ROUTE_DECISION`
- 保留 `AgentRun.timeline_json` 做视图缓存（前端显示用），`agent_event` 做真源头
- Alembic migration 0004 建表 + RLS

### P3.8 HITL（Human In The Loop）

**场景**：`rule_check` 说 "blocked" → agent run 暂停，等 reviewer 决策。

**改造**：
- `GraphState` 新字段 `paused_reason: str | None`
- 新节点输出 `next_node=None` + `state_delta={"paused_reason": "需要审核批准报销超标"}`
- 现有 `ReviewCase` 已有 HITL 基座（P1.5 做过）；这里要打通：
  - Engine detect `paused_reason` → mark `AgentRun.status="awaiting_review"` + 创建 `ReviewCase`
  - 新 API `POST /api/agents/runs/{id}/resume`：reviewer 批准后恢复 run，把 decision 写进 state，从断点继续
- Timeline 事件新增 `PAUSE` / `RESUME`

---

## 四、依赖关系图

```
P3.1 engine (基础)
  ↓
P3.5 tool system ←─┐
  ↓                │
P3.2 router       P3.3 policy ReAct ←── P3.6 memory
  ↓                ↓
  └─── P3.4 anomaly
                   ↓
           P3.7 timeline events
                   ↓
           P3.8 HITL resume
```

**建议执行顺序**：P3.1 → P3.5 → P3.2 → P3.3 → P3.4 → P3.7 → P3.6 → P3.8

---

## 五、不做但要记录

| 项 | 推迟到 |
|---|---|
| 多 agent 协作（agent-to-agent 通信） | Phase 5 或之后，本 phase 只做单 agent ReAct |
| Agent trace export 到 OTEL / LangSmith / Phoenix | Phase 5 可观测性 |
| Cost / token 统计聚合到 metrics | Phase 5 |
| ReAct prompt 版本管理 + A/B | Phase 6 Prompt 运营化 |
| Real tool integrations（ERP / 支付网关 / CRM） | 业务驱动，不在工程规划 |

---

## 六、总验收

完成 Phase 3 后应该能：

1. **新开一种 agent** 只需要：写 graph nodes + 注册到 router intent 表，**不改 core 代码**
2. **工具错了**能重试、能熔断、能 fallback，不会把整条 chain 弄挂
3. **anomaly_graph 真读取输入**，输出的 decision 能覆盖测试场景
4. **整条 agent run** 的每一步都有结构化 event，可以在 DB 查到"第 3 步用了 X 工具返回 Y，第 4 步 LLM 决定 Z"
5. **reviewer 决策完** 能一键恢复 agent run 继续走
6. **memory** 能把前 3 次同用户的关键结论带到本次 prompt

**评分预期**：
- Agent 3.5 → 7.5
- 综合项目评分 7.0 → 7.8

---

## 七、下一步

等你：
- **「OK，按此顺序执行」** → 我开 P3.1（engine 框架）
- **「改一下：XXX」** → 告诉我哪些子任务合并 / 砍掉 / 重排
- **「先做 P3.X 看看效果」** → 改执行顺序，先跑那个子任务

无论哪条，都同 Phase 1 / 2 的模式：每个子任务完成就回归 + 更新 `docs/reports/phase-3-progress.md`。
