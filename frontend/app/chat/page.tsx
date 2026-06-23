"use client";

import { FormEvent, useState } from "react";

type RetrievalStage = {
  sequence: number;
  stage: string;
  status: string;
  message: string;
  duration_ms: number;
  details: Record<string, unknown>;
};

type RetrievalResult = {
  chunk_id: string;
  document_id: string | null;
  document_version_id: string | null;
  source_filename: string | null;
  chunk_index: number | null;
  section_title: string | null;
  element_type: string | null;
  page_number: number | null;
  text: string;
  fused_score: number;
  dense_score: number | null;
  sparse_score: number | null;
  dense_rank: number | null;
  sparse_rank: number | null;
};

type RetrievalResponse = {
  query: string;
  mode: string;
  stages: RetrievalStage[];
  results: RetrievalResult[];
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:18000";

function formatScore(value: number | null) {
  if (value === null) return "—";
  return value.toFixed(value >= 1 ? 2 : 4);
}

function shortText(value: string) {
  if (value.length <= 900) return value;
  return `${value.slice(0, 900).trim()}…`;
}

function detailValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(4);
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  return JSON.stringify(value);
}

export default function ChatPage() {
  const [query, setQuery] = useState("What does the plan say about infrastructure?");
  const [response, setResponse] = useState<RetrievalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runRetrieval(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);

    try {
      const apiResponse = await fetch(`${backendUrl}/api/retrieval/search`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: trimmed }),
      });
      const payload = await apiResponse.json();
      if (!apiResponse.ok) {
        throw new Error(payload.detail ?? "Retrieval failed.");
      }
      setResponse(payload);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Retrieval failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Ask</p>
          <h1>Document chat</h1>
        </div>
        <span className="status-pill neutral">Retrieval only</span>
      </header>

      <div className="page-content chat-workbench">
        <section className="retrieval-panel">
          <div>
            <p className="eyebrow">Hybrid search</p>
            <h2>Ask from indexed chunks</h2>
            <p>
              This step stops before reranking and answer generation. It shows
              which dense and sparse retrieval stages ran and what evidence was
              returned.
            </p>
          </div>

          <form className="question-box active" onSubmit={runRetrieval}>
            <textarea
              aria-label="Question"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Ask a question about your documents…"
              rows={2}
            />
            <button disabled={loading || !query.trim()} aria-label="Run retrieval">
              {loading ? "…" : "↑"}
            </button>
          </form>

          {error ? <p className="form-error">{error}</p> : null}
        </section>

        <section className="trace-results-grid">
          <div className="retrieval-trace-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Trace</p>
                <h2>Pipeline stages</h2>
              </div>
              {response ? <small>{response.mode.replace("_", " ")}</small> : null}
            </div>

            {response ? (
              <div className="retrieval-stage-list">
                {response.stages.map((stage) => (
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
                          <dd>{stage.duration_ms} ms</dd>
                        </div>
                        {Object.entries(stage.details).map(([key, value]) => (
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
            ) : (
              <p className="document-empty">
                Run a query to see dense retrieval, sparse retrieval, rank fusion,
                and evidence preview stages.
              </p>
            )}
          </div>

          <div className="retrieval-results-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Evidence</p>
                <h2>Top chunks</h2>
              </div>
              {response ? <small>{response.results.length} result(s)</small> : null}
            </div>

            {response?.results.length ? (
              <div className="retrieval-results">
                {response.results.map((result, index) => (
                  <article className="retrieval-result" key={result.chunk_id}>
                    <div className="result-head">
                      <span>#{index + 1}</span>
                      <div>
                        <h3>{result.source_filename ?? "Unknown source"}</h3>
                        <p>
                          Chunk {result.chunk_index ?? "—"}
                          {result.section_title ? ` · ${result.section_title}` : ""}
                          {result.page_number ? ` · page ${result.page_number}` : ""}
                        </p>
                      </div>
                    </div>

                    <div className="score-row">
                      <span>fused {formatScore(result.fused_score)}</span>
                      <span>
                        dense rank {result.dense_rank ?? "—"} / score{" "}
                        {formatScore(result.dense_score)}
                      </span>
                      <span>
                        sparse rank {result.sparse_rank ?? "—"} / score{" "}
                        {formatScore(result.sparse_score)}
                      </span>
                    </div>

                    <p className="result-text">{shortText(result.text)}</p>
                  </article>
                ))}
              </div>
            ) : response ? (
              <p className="document-empty">
                No chunks were returned. Confirm at least one document is indexed.
              </p>
            ) : (
              <p className="document-empty">
                Evidence chunks will appear here after a query.
              </p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
