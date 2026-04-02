import { Citation } from "../api/chat";


interface CitationPanelProps {
  citations: Citation[];
}

export default function CitationPanel({ citations }: CitationPanelProps) {
  if (citations.length === 0) {
    return <p className="citation-panel__empty">当前没有可展示的引用依据。</p>;
  }

  return (
    <section className="citation-panel">
      <h3>引用依据</h3>
      <ul className="citation-panel__list">
        {citations.map((citation, index) => (
          <li key={citation.chunk_id} className="citation-panel__item">
            <div className="citation-panel__item-header">
              <span className="citation-panel__index">{String(index + 1).padStart(2, "0")}</span>
              <strong>{citation.document_title}</strong>
              <span className="citation-panel__score">命中分数 {Math.round(citation.score * 100)}%</span>
            </div>
            <p>{citation.snippet}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
