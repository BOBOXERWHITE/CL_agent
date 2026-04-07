import { useState } from "react";

import { RetrievalTrace } from "../api/chat";


interface RetrievalTraceDrawerProps {
  trace: RetrievalTrace;
}

export default function RetrievalTraceDrawer({ trace }: RetrievalTraceDrawerProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <section className="trace-card">
      <button
        type="button"
        className="trace-card__toggle"
        onClick={() => setIsOpen((current) => !current)}
      >
        {isOpen ? "收起检索 Trace" : "查看检索 Trace"}
      </button>
      {isOpen ? (
        <div className="trace-card__body">
          <div className="trace-card__summary">
            <div>
              <span>检索模式</span>
              <strong>{trace.mode}</strong>
            </div>
            <div>
              <span>Prompt</span>
              <strong>
                {trace.prompt_name} v{trace.prompt_version}
              </strong>
            </div>
            <div>
              <span>模型</span>
              <strong>{trace.model_name}</strong>
            </div>
            <div>
              <span>Tokens</span>
              <strong>
                输入 {trace.token_usage.input_tokens} / 输出 {trace.token_usage.output_tokens}
              </strong>
            </div>
          </div>
          <div className="trace-card__list">
            <h4>已选 chunks</h4>
            <ul>
              {trace.selected_chunks.map((chunk) => (
                <li key={chunk.chunk_id}>
                  <strong>{chunk.document_title}</strong>
                  <span>{chunk.chunk_id}</span>
                  <em>命中分数 {Math.round(chunk.score * 100)}%</em>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </section>
  );
}
