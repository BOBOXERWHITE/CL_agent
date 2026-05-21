import { useEffect, useState } from "react";

import type { EditableSystemSettings } from "../api/settings";
import { getSystemSettings } from "../api/settings";
import AgentRunsPage from "../pages/AgentRunsPage";
import ChatPage from "../pages/ChatPage";
import EvalPage from "../pages/EvalPage";
import KnowledgePage from "../pages/KnowledgePage";
import MonitoringPage from "../pages/MonitoringPage";
import PromptTemplatesPage from "../pages/PromptTemplatesPage";
import ReviewQueuePage from "../pages/ReviewQueuePage";
import RuntimeLogsPage from "../pages/RuntimeLogsPage";
import SystemSettingsPage from "../pages/SystemSettingsPage";

type TabKey =
  | "knowledge"
  | "chat"
  | "prompts"
  | "evals"
  | "agents"
  | "reviews"
  | "monitoring"
  | "logs"
  | "settings";

const DEFAULT_BUSINESS_SETTINGS: EditableSystemSettings = {
  default_tenant_id: "演示租户",
  default_customer_id: "演示客户",
  chat_top_k: 3,
  chat_confidence_threshold: 0.2,
  default_eval_dataset: "zh-policy-smoke",
  agent_router_provider: "keyword",
  chat_history_max_turns: 5,
};

const TAB_CONFIG: {
  key: TabKey;
  label: string;
  description: string;
}[] = [
  { key: "knowledge", label: "知识库管理", description: "文档入库、向量重建与知识资产维护。" },
  { key: "chat", label: "政策问答", description: "基于证据做政策问答、引用展示和置信度判断。" },
  { key: "prompts", label: "Prompt 模板", description: "管理问答和流程使用的 Prompt 模板版本。" },
  { key: "evals", label: "评测运行", description: "执行回归评测，定位答案和引用的质量退化。" },
  { key: "agents", label: "Agent 运行", description: "查看 Agent 任务执行结果、时间线和工具调用。" },
  { key: "reviews", label: "人工复核", description: "处理规则拦截和低置信度结果的审核队列。" },
  { key: "monitoring", label: "监控面板", description: "从业务表聚合得到的运营和运行总览。" },
  { key: "logs", label: "运行日志", description: "按请求维度检索运行日志和错误详情。" },
  { key: "settings", label: "系统设置", description: "维护默认租户、阈值和默认评测集等业务参数。" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("knowledge");
  const [businessSettings, setBusinessSettings] =
    useState<EditableSystemSettings>(DEFAULT_BUSINESS_SETTINGS);

  useEffect(() => {
    let isMounted = true;

    void getSystemSettings()
      .then((response) => {
        if (!isMounted) {
          return;
        }
        setBusinessSettings(response.editable_settings);
      })
      .catch(() => {
        if (!isMounted) {
          return;
        }
        setBusinessSettings(DEFAULT_BUSINESS_SETTINGS);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  function renderActiveTab() {
    switch (activeTab) {
      case "knowledge":
        return (
          <KnowledgePage
            defaultTenantId={businessSettings.default_tenant_id}
            defaultCustomerId={businessSettings.default_customer_id}
          />
        );
      case "chat":
        return (
          <ChatPage
            defaultTenantId={businessSettings.default_tenant_id}
            defaultCustomerId={businessSettings.default_customer_id}
          />
        );
      case "prompts":
        return <PromptTemplatesPage />;
      case "evals":
        return <EvalPage defaultDatasetName={businessSettings.default_eval_dataset} />;
      case "agents":
        return <AgentRunsPage />;
      case "reviews":
        return <ReviewQueuePage />;
      case "monitoring":
        return <MonitoringPage />;
      case "logs":
        return <RuntimeLogsPage />;
      case "settings":
        return <SystemSettingsPage onSaved={setBusinessSettings} />;
      default:
        return null;
    }
  }

  const activeTabMeta = TAB_CONFIG.find((item) => item.key === activeTab) ?? TAB_CONFIG[0];

  return (
    <main className="app-shell">
      <div className="app-shell__backdrop" aria-hidden="true">
        <div className="app-shell__orb app-shell__orb--amber" />
        <div className="app-shell__orb app-shell__orb--teal" />
        <div className="app-shell__grid" />
      </div>

      <section className="hero-panel hero-panel--admin">
        <div className="hero-panel__copy">
          <p className="hero-panel__eyebrow">Travel Ops Copilot</p>
          <h1>差旅智能运营后台</h1>
          <p className="hero-panel__lead">
            把知识库、问答、评测、Agent、人工复核、监控和运行日志收敛到一个后台壳层里。先看证据，再看结论，再看运行状态。
          </p>
        </div>
        <div className="hero-panel__metrics" aria-label="首页概览">
          <article className="metric-card">
            <span className="metric-card__label">当前能力</span>
            <strong>知识入库</strong>
            <p>支持 DOCX / PDF 解析、切块、对象存储与向量写入。</p>
          </article>
          <article className="metric-card">
            <span className="metric-card__label">当前能力</span>
            <strong>中文检索</strong>
            <p>支持中文、中英混合问题的 hybrid retrieval 与轻量 rerank。</p>
          </article>
          <article className="metric-card">
            <span className="metric-card__label">交付原则</span>
            <strong>证据优先</strong>
            <p>问答结果展示引用依据、检索 Trace 和置信度，避免黑盒回答。</p>
          </article>
          <article className="metric-card">
            <span className="metric-card__label">新增能力</span>
            <strong>人工复核</strong>
            <p>规则拦截、低置信度和需要人工接管的 Agent 结果会进入统一审核队列。</p>
          </article>
        </div>
      </section>

      <section className="console-shell">
        <div className="console-shell__header">
          <div>
            <p className="panel__eyebrow">后台导航</p>
            <p className="console-shell__title">{activeTabMeta.label}</p>
            <p className="console-shell__description">{activeTabMeta.description}</p>
          </div>
          <div className="console-shell__meta">
            <span className="panel__tag">
              默认租户：{businessSettings.default_tenant_id} / {businessSettings.default_customer_id}
            </span>
            <span className="panel__tag">默认评测集：{businessSettings.default_eval_dataset}</span>
          </div>
        </div>

        <div className="tab-bar" role="tablist" aria-label="后台模块导航">
          {TAB_CONFIG.map((tab) => (
            <button
              key={tab.key}
              id={`tab-${tab.key}`}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.key}
              aria-controls={`panel-${tab.key}`}
              className={`tab-bar__button ${activeTab === tab.key ? "tab-bar__button--active" : ""}`}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <section
          id={`panel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`tab-${activeTab}`}
          className="workspace-stage"
        >
          {renderActiveTab()}
        </section>
      </section>
    </main>
  );
}
