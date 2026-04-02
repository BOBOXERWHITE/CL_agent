import ChatPage from "../pages/ChatPage";
import KnowledgePage from "../pages/KnowledgePage";


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
            面向政策检索、知识入库与运营问答的统一控制界面。
            先把证据链看清，再决定下一步动作。
          </p>
        </div>
        <div className="hero-panel__metrics" aria-label="首页概览">
          <article className="metric-card">
            <span className="metric-card__label">当前能力</span>
            <strong>知识入库</strong>
            <p>支持 DOCX / PDF 的解析、切块与向量写入。</p>
          </article>
          <article className="metric-card">
            <span className="metric-card__label">答复方式</span>
            <strong>证据优先</strong>
            <p>每次问答都展示引用依据和置信度，不直接黑盒输出。</p>
          </article>
          <article className="metric-card">
            <span className="metric-card__label">当前节奏</span>
            <strong>初步验证</strong>
            <p>适合一边联调接口，一边观察页面和数据链路。</p>
          </article>
        </div>
      </section>

      <section className="workspace-grid">
        <KnowledgePage />
        <ChatPage />
      </section>
    </main>
  );
}
