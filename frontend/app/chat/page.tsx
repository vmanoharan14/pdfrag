export default function ChatPage() {
  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Ask</p>
          <h1>Document chat</h1>
        </div>
        <span className="status-pill neutral">Interface preview</span>
      </header>

      <div className="page-content chat-preview">
        <section className="empty-chat">
          <span className="empty-icon">⌁</span>
          <h2>Ask from your evidence</h2>
          <p>
            Document ingestion and retrieval are not connected yet. This page
            confirms the intended chat layout before we build the pipeline.
          </p>
          <div className="question-box">
            <span>Ask a question about your documents…</span>
            <button disabled aria-label="Send question">
              ↑
            </button>
          </div>
        </section>
      </div>
    </>
  );
}
