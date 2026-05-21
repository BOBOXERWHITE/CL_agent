# Phase 10 复盘：统一 orchestration trace schema

## 结果
- 已完成统一 orchestration trace 的后端输出与前端展示
- ticket / anomaly 不再只能看卡片摘要，也可以走与 policy 相同的 Trace Drawer
- 现有 Trace Drawer 已从“检索 trace”扩展为“检索 + 编排 trace”通用组件

## 本批收益
- 统一了 agent 运行可观测性语义，减少不同 route 各自维护展示逻辑
- 保住了 chat 链路向后兼容，不需要为本批切片改动前端 chat 页面契约
- 为下一步统一 `supervisor / specialist / engine_adapter` trace schema 打好了基础

## 验证
- 后端断言验证了 ticket / anomaly 的 checkpoint、interrupt、queue、anomaly code 都能进入 trace
- 前端断言验证了 AgentRunsPage 可以打开 ticket 的 orchestration trace drawer
- 构建通过，说明类型扩展没有破坏现有页面

## 遇到的问题
- 前端测试最初失败不是实现问题，而是等待条件和断言写得过窄：
  - 页面标题过早可见，不能代表 runs 已加载完成
  - `ticket_router_agent / ticket routing requires operator review / ticket_queue_lookup` 在卡片和 drawer 中可能多次出现
- 解决方式是把测试改为：
  - 等待 run 实际渲染完成
  - 对可重复文本使用 `findAllBy* / getAllBy*`

## 后续建议
1. 继续推进统一 `supervisor / specialist / engine_adapter` trace schema
2. 将 review queue 与 agent event log 进一步纳入同一条 trace 语义
3. 为 eval 工作台补充 trace drill-down，支持按 domain / route / interrupt 类型过滤
