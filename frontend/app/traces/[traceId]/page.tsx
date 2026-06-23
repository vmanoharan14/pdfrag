import { notFound } from "next/navigation";

type TraceStep = {
  sequence: number;
  stage: string;
  status: string;
  message: string;
  duration_ms: number;
  details: Record<string, unknown> | null;
};

type SelectedChunk = {
  chunk_id?: string;
  source_filename?: string | null;
  chunk_index?: number | null;
  section_title?: string | null;
  page_number?: number | null;
  final_rank?: number;
  rerank_score?: number | null;
  text?: string;
};

type PackedContextBlock = {
  citation_id: string;
  chunk_id: string;
  source_filename: string | null;
  chunk_index: number | null;
  section_title: string | null;
  page_number: number | null;
  text: string;
};

type TraceResponse = {
  trace_id: string;
  tenant_id: string;
  user_id: string;
  original_question: string;
  normalized_query: string;
  mode: string;
  evidence_status: string;
  answer: string;
  citations: string[];
  selected_chunks: SelectedChunk[];
  packed_context: {
    blocks?: PackedContextBlock[];
    prompt_context?: string;
    token_estimate?: number;
    char_count?: number;
    max_chars?: number;
    truncated?: boolean;
  };
  timings_ms: Record<string, number>;
  cache_event: string;
  model_details: Record<string, unknown>;
  created_at: string;
  steps: TraceStep[];
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:18000";

function formatMs(value: number) {
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  return `${value} ms`;
}

function detailValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(4);
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  return JSON.stringify(value);
}

function shortText(value: string | undefined) {
  if (!value) return "";
  if (value.length <= 520) return value;
  return `${value.slice(0, 520).trim()}…`;
}

function toneForStage(stage: string) {
  if (stage.includes("query")) return "blue";
  if (stage.includes("dense")) return "cyan";
  if (stage.includes("sparse")) return "amber";
  if (stage.includes("fusion") || stage.includes("expansion")) return "orange";
  if (stage.includes("rerank")) return "pink";
  if (stage.includes("context")) return "indigo";
  if (stage.includes("answer")) return "green";
  return "slate";
}

async function getTrace(traceId: string): Promise<TraceResponse> {
  const response = await fetch(`${backendUrl}/api/traces/${traceId}`, {
    cache: "no-store",
  });
  if (response.status === 404) notFound();
  if (!response.ok) {
    throw new Error(`Could not load trace ${traceId}`);
  }
  return response.json();
}

export default async function TracePage({
  params,
}: {
  params: Promise<{ traceId: string }>;
}) {
  const { traceId } = await params;
  const trace = await getTrace(traceId);
  const totalLatency = Object.values(trace.timings_ms).reduce(
    (total, value) => total + value,
    0,
  );
  const packedBlocks = trace.packed_context.blocks ?? [];

  return (
    <>
      <header className="topbar trace-topbar">
        <div>
          <p className="eyebrow">Trace / {trace.trace_id.slice(0, 8)}</p>
          <h1>Question trace</h1>
        </div>
        <div className="trace-actions">
          <span className="status-pill neutral">{trace.mode.replaceAll("_", " ")}</span>
          <span className="status-pill success">{trace.evidence_status}</span>
        </div>
      </header>

      <div className="page-content trace-page">
        <section className="trace-summary">
          <div className="summary-main">
            <p className="eyebrow">Original question</p>
            <h2>{trace.original_question}</h2>
            <div className="answer-preview">
              <span>Answer</span>
              <p>{trace.answer}</p>
              <small>
                citations{" "}
                {trace.citations.length
                  ? trace.citations.map((id) => `[${id}]`).join(", ")
                  : "—"}
              </small>
            </div>
          </div>
          <dl className="trace-metrics">
            <div>
              <dt>Total latency</dt>
              <dd>{formatMs(totalLatency)}</dd>
            </div>
            <div>
              <dt>Evidence status</dt>
              <dd className="green-text">{trace.evidence_status}</dd>
            </div>
            <div>
              <dt>Cache</dt>
              <dd>{trace.cache_event}</dd>
            </div>
            <div>
              <dt>Final chunks</dt>
              <dd>{packedBlocks.length}</dd>
            </div>
          </dl>
        </section>

        <section className="pipeline-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Execution</p>
              <h2>Pipeline stages</h2>
            </div>
            <small>{new Date(trace.created_at).toLocaleString()}</small>
          </div>

          <div className="pipeline">
            {trace.steps.map((stage, index) => (
              <article className="stage-row" key={`${stage.sequence}-${stage.stage}`}>
                <div className="stage-line">
                  <span className={`stage-node ${toneForStage(stage.stage)}`}>
                    {String(stage.sequence).padStart(2, "0")}
                  </span>
                  {index < trace.steps.length - 1 ? <span /> : null}
                </div>
                <div className="stage-card">
                  <div>
                    <h3>{stage.stage}</h3>
                    <p>{stage.message}</p>
                  </div>
                  <div className="stage-meta">
                    <span
                      className={
                        stage.status === "completed" ? "complete-mark" : "warning-mark"
                      }
                    >
                      {stage.status === "completed" ? "✓" : "!"}
                    </span>
                    <time>{formatMs(stage.duration_ms)}</time>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="trace-results-grid trace-detail-grid">
          <div className="retrieval-trace-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Stage details</p>
                <h2>Inputs and outputs</h2>
              </div>
              <small>{trace.steps.length} step(s)</small>
            </div>

            <div className="retrieval-stage-list">
              {trace.steps.map((stage) => (
                <article className="retrieval-stage" key={stage.sequence}>
                  <span>{String(stage.sequence).padStart(2, "0")}</span>
                  <div>
                    <h3>{stage.stage}</h3>
                    <p>{stage.message}</p>
                    <dl>
                      <div>
                        <dt>Status</dt>
                        <dd>{stage.status}</dd>
                      </div>
                      <div>
                        <dt>Time</dt>
                        <dd>{formatMs(stage.duration_ms)}</dd>
                      </div>
                      {Object.entries(stage.details ?? {}).map(([key, value]) => (
                        <div key={key}>
                          <dt>{key.replaceAll("_", " ")}</dt>
                          <dd>{detailValue(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                </article>
              ))}
            </div>
          </div>

          <div className="retrieval-results-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Evidence</p>
                <h2>Selected prompt chunks</h2>
              </div>
              <small>
                {trace.packed_context.token_estimate ?? 0} est. tokens ·{" "}
                {trace.packed_context.char_count ?? 0}/
                {trace.packed_context.max_chars ?? 0} chars
              </small>
            </div>

            {packedBlocks.length ? (
              <div className="retrieval-results">
                {packedBlocks.map((block) => (
                  <article className="retrieval-result" key={block.citation_id}>
                    <div className="result-head">
                      <span>{block.citation_id}</span>
                      <div>
                        <h3>{block.source_filename ?? "Unknown source"}</h3>
                        <p>
                          Chunk {block.chunk_index ?? "—"}
                          {block.section_title ? ` · ${block.section_title}` : ""}
                          {block.page_number ? ` · page ${block.page_number}` : ""}
                        </p>
                      </div>
                    </div>
                    <p className="result-text">{shortText(block.text)}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="document-empty">No prompt evidence was stored for this trace.</p>
            )}

            <details className="prompt-preview">
              <summary>Show packed prompt context</summary>
              <pre>{trace.packed_context.prompt_context ?? ""}</pre>
            </details>
          </div>
        </section>
      </div>
    </>
  );
}
