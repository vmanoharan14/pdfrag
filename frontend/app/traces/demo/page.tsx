const stages = [
  {
    number: "01",
    name: "Query received",
    detail: "What is the specialist visit copayment?",
    latency: "0.3 ms",
    tone: "blue",
  },
  {
    number: "02",
    name: "Intent routing",
    detail: "factual_lookup · no rewrite needed",
    latency: "184 ms",
    tone: "violet",
  },
  {
    number: "03",
    name: "Security context",
    detail: "local-development-principal",
    latency: "0.8 ms",
    tone: "slate",
  },
  {
    number: "04",
    name: "Dense retrieval",
    detail: "40 candidates · best score 0.88",
    latency: "92 ms",
    tone: "cyan",
  },
  {
    number: "05",
    name: "BM25 retrieval",
    detail: "40 candidates · exact term match",
    latency: "71 ms",
    tone: "amber",
  },
  {
    number: "06",
    name: "RRF fusion",
    detail: "62 unique candidates",
    latency: "2.7 ms",
    tone: "orange",
  },
  {
    number: "07",
    name: "Reranking",
    detail: "MiniLM · 12 evidence candidates",
    latency: "138 ms",
    tone: "pink",
  },
  {
    number: "08",
    name: "Context packing",
    detail: "8 chunks · 3,240 tokens",
    latency: "4.2 ms",
    tone: "indigo",
  },
  {
    number: "09",
    name: "Answer generation",
    detail: "gemma2:2b · grounded response",
    latency: "2.4 s",
    tone: "green",
  },
];

export default function DemoTracePage() {
  return (
    <>
      <header className="topbar trace-topbar">
        <div>
          <p className="eyebrow">Trace / demo-01</p>
          <h1>Question trace</h1>
        </div>
        <div className="trace-actions">
          <span className="status-pill neutral">Mock data</span>
          <span className="status-pill success">Completed</span>
        </div>
      </header>

      <div className="page-content trace-page">
        <section className="trace-summary">
          <div className="summary-main">
            <p className="eyebrow">Original question</p>
            <h2>What is the specialist visit copayment?</h2>
            <div className="answer-preview">
              <span>Answer</span>
              <p>
                The specialist visit copayment is <strong>$40</strong> after
                the deductible does not apply.
              </p>
              <small>Benefits Guide · page 14 · Medical benefits table</small>
            </div>
          </div>
          <dl className="trace-metrics">
            <div>
              <dt>Total latency</dt>
              <dd>2.89 s</dd>
            </div>
            <div>
              <dt>Evidence status</dt>
              <dd className="green-text">Supported</dd>
            </div>
            <div>
              <dt>Cache</dt>
              <dd>Miss</dd>
            </div>
            <div>
              <dt>Final chunks</dt>
              <dd>8</dd>
            </div>
          </dl>
        </section>

        <section className="pipeline-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Execution</p>
              <h2>Pipeline stages</h2>
            </div>
            <small>Every step will expand into real inputs and outputs</small>
          </div>

          <div className="pipeline">
            {stages.map((stage, index) => (
              <article className="stage-row" key={stage.number}>
                <div className="stage-line">
                  <span className={`stage-node ${stage.tone}`}>
                    {stage.number}
                  </span>
                  {index < stages.length - 1 ? <span /> : null}
                </div>
                <div className="stage-card">
                  <div>
                    <h3>{stage.name}</h3>
                    <p>{stage.detail}</p>
                  </div>
                  <div className="stage-meta">
                    <span className="complete-mark">✓</span>
                    <time>{stage.latency}</time>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

        <p className="mock-note">
          This trace is intentionally mock data. It validates the visual model;
          later slices will replace each stage with persisted backend events.
        </p>
      </div>
    </>
  );
}
