import AgentRunsPage from "../pages/AgentRunsPage";
import ChatPage from "../pages/ChatPage";
import EvalPage from "../pages/EvalPage";
import KnowledgePage from "../pages/KnowledgePage";
import PromptTemplatesPage from "../pages/PromptTemplatesPage";
import ReviewQueuePage from "../pages/ReviewQueuePage";

export default function App() {
  return (
    <main className="app-shell">
      <div className="app-shell__backdrop" aria-hidden="true">
        <div className="app-shell__orb app-shell__orb--amber" />
        <div className="app-shell__orb app-shell__orb--teal" />
        <div className="app-shell__grid" />
      </div>

      <section className="hero-panel">
        <div className="hero-panel__copy">
          <p className="hero-panel__eyebrow">Travel Ops Copilot</p>
          <h1>差旅智能运营台</h1>
          <p className="hero-panel__lead">
            面向政策检索、知识入库、中文问答、评测回归和人工复核的统一工作台。先看证据，再看结论，再决定是否继续放量。
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

      <section className="workspace-grid">
        <KnowledgePage />
        <ChatPage />
      </section>
      <section className="workspace-stack workspace-stack--double">
        <PromptTemplatesPage />
        <EvalPage />
      </section>
      <section className="workspace-stack workspace-stack--double">
        <AgentRunsPage />
        <ReviewQueuePage />
      </section>
    </main>
  );
}
