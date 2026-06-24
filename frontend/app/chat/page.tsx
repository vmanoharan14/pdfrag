"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";

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
  rerank_score: number | null;
  final_rank: number;
};

type RetrievalResponse = {
  trace_id: string;
  query: string;
  mode: string;
  query_analysis: QueryAnalysis;
  stages: RetrievalStage[];
  results: RetrievalResult[];
  packed_context: PackedContext;
  answer: Answer;
};

type FeedbackLabel = "correct" | "incomplete" | "wrong";
type GenerationModel = "qwen3.5:9b" | "gemma2:2b";

type QueryAnalysis = {
  original_query: string;
  retrieval_query: string;
  intent: string;
  topics: string[];
  expansions: string[];
};

type Answer = {
  text: string;
  model: string;
  citation_ids: string[];
  prompt_chars: number;
  prompt_token_estimate: number;
};

type ContextBlock = {
  citation_id: string;
  chunk_id: string;
  source_filename: string | null;
  chunk_index: number | null;
  section_title: string | null;
  page_number: number | null;
  text: string;
  char_count: number;
  token_estimate: number;
};

type PackedContext = {
  blocks: ContextBlock[];
  prompt_context: string;
  char_count: number;
  token_estimate: number;
  max_chars: number;
  truncated: boolean;
};

type StreamedContext = {
  blocks: Omit<ContextBlock, "char_count" | "token_estimate">[];
  token_estimate: number;
  char_count: number;
  max_chars: number;
  truncated: boolean;
};

type StreamDone = {
  trace_id: string;
  answer: string;
  citation_ids: string[];
  generation_model: string;
  retrieval_mode: string;
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

function formatDuration(ms: number) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function stageDuration(stages: RetrievalStage[], stageName: string) {
  return stages.find((stage) => stage.stage === stageName)?.duration_ms ?? 0;
}

function latencySummary(stages: RetrievalStage[]) {
  const dense = stageDuration(stages, "dense retrieval");
  const sparse = stageDuration(stages, "sparse retrieval");
  const fusion = stageDuration(stages, "rank fusion");
  const expansion = stageDuration(stages, "candidate expansion");
  const rerank = stageDuration(stages, "rerank");
  const context = stageDuration(stages, "context packing");
  const generation = stageDuration(stages, "answer generation");
  const total = stages.reduce((sum, stage) => sum + stage.duration_ms, 0);
  const retrieval = dense + sparse + fusion + expansion;
  const bottleneck =
    generation >= rerank && generation >= retrieval
      ? "answer generation"
      : rerank >= retrieval
        ? "rerank"
        : "retrieval";

  return { total, retrieval, rerank, context, generation, bottleneck };
}

function LatencySummaryCard({ stages, model }: { stages: RetrievalStage[]; model: string }) {
  const summary = latencySummary(stages);

  return (
    <section className="latency-card">
      <div className="section-heading compact">
        <div>
          <p className="eyebrow">Latency</p>
          <h2>Stage timing summary</h2>
        </div>
        <small>bottleneck: {summary.bottleneck}</small>
      </div>
      <div className="latency-grid">
        <div><span>Total</span><strong>{formatDuration(summary.total)}</strong></div>
        <div><span>Retrieval</span><strong>{formatDuration(summary.retrieval)}</strong></div>
        <div><span>Rerank</span><strong>{formatDuration(summary.rerank)}</strong></div>
        <div><span>Context</span><strong>{formatDuration(summary.context)}</strong></div>
        <div><span>Generation</span><strong>{formatDuration(summary.generation)}</strong></div>
        <div><span>Model</span><strong>{model}</strong></div>
      </div>
    </section>
  );
}

export default function ChatPage() {
  const [query, setQuery] = useState("What does the plan say about infrastructure?");
  const [response, setResponse] = useState<RetrievalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [generationModel, setGenerationModel] = useState<GenerationModel>("gemma2:2b");
  const [feedbackByChunk, setFeedbackByChunk] = useState<Record<string, FeedbackLabel>>({});
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [activeCitation, setActiveCitation] = useState<string | null>(null);

  // Streaming state
  const [streamText, setStreamText] = useState("");
  const [liveStages, setLiveStages] = useState<RetrievalStage[]>([]);
  const [liveContext, setLiveContext] = useState<StreamedContext | null>(null);
  const [streamDone, setStreamDone] = useState<StreamDone | null>(null);

  async function runRetrieval(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;

    setLoading(true);
    setError(null);
    setResponse(null);
    setStreamText("");
    setLiveStages([]);
    setLiveContext(null);
    setStreamDone(null);
    setFeedbackByChunk({});
    setFeedbackError(null);
    setActiveCitation(null);

    try {
      const apiResponse = await fetch(`${backendUrl}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmed, generation_model: generationModel }),
      });
      if (!apiResponse.ok || !apiResponse.body) {
        const payload = await apiResponse.json() as { detail?: string };
        throw new Error(payload.detail ?? "Retrieval failed.");
      }

      const reader = apiResponse.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";

        for (const part of parts) {
          const lines = part.trim().split("\n");
          const eventType = lines.find((l) => l.startsWith("event: "))?.slice(7) ?? "";
          const dataStr = lines.find((l) => l.startsWith("data: "))?.slice(5) ?? "";
          if (!eventType || !dataStr) continue;

          const data = JSON.parse(dataStr) as Record<string, unknown>;
          if (eventType === "stage") {
            setLiveStages((prev) => [...prev, data as unknown as RetrievalStage]);
          } else if (eventType === "context") {
            setLiveContext(data as unknown as StreamedContext);
          } else if (eventType === "token") {
            setStreamText((prev) => prev + String(data.text ?? ""));
          } else if (eventType === "done") {
            setStreamDone(data as unknown as StreamDone);
          }
        }
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Retrieval failed.");
    } finally {
      setLoading(false);
    }
  }

  function selectCitation(citationId: string) {
    setActiveCitation(citationId);
    window.requestAnimationFrame(() => {
      document
        .getElementById(`chat-evidence-${citationId}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  async function submitFeedback(result: RetrievalResult, label: FeedbackLabel) {
    if (!result.document_id || !result.document_version_id) return;
    if (!response && !streamDone) return;

    setFeedbackError(null);

    const feedbackQuery = response?.query ?? query;
    const feedbackMode = response?.mode ?? streamDone?.retrieval_mode ?? "hybrid";
    const feedbackStages = response?.stages ?? liveStages;

    try {
      const apiResponse = await fetch(`${backendUrl}/api/retrieval/feedback`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          query: feedbackQuery,
          mode: feedbackMode,
          chunk_id: result.chunk_id,
          document_id: result.document_id,
          document_version_id: result.document_version_id,
          label,
          final_rank: result.final_rank,
          dense_rank: result.dense_rank,
          sparse_rank: result.sparse_rank,
          fused_score: result.fused_score,
          dense_score: result.dense_score,
          sparse_score: result.sparse_score,
          rerank_score: result.rerank_score,
          trace: {
            stages: feedbackStages.map((stage) => ({
              sequence: stage.sequence,
              stage: stage.stage,
              status: stage.status,
              duration_ms: stage.duration_ms,
              details: stage.details,
            })),
          },
        }),
      });
      const payload = await apiResponse.json();
      if (!apiResponse.ok) {
        throw new Error(payload.detail ?? "Could not save feedback.");
      }
      setFeedbackByChunk((current) => ({ ...current, [result.chunk_id]: label }));
    } catch (caught) {
      setFeedbackError(
        caught instanceof Error ? caught.message : "Could not save feedback.",
      );
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Ask</p>
          <h1>Document chat</h1>
        </div>
        <span className="status-pill neutral">Retrieval + rerank</span>
      </header>

      <div className="page-content chat-workbench">
        <section className="retrieval-panel">
          <div>
            <p className="eyebrow">Hybrid search</p>
            <h2>Ask from indexed chunks</h2>
            <p>
              This step generates a grounded answer from the packed context. The
              trace keeps retrieval, reranking, context packing, generation, and
              evidence visible for inspection.
            </p>
          </div>

          <form className="question-form" onSubmit={runRetrieval}>
            <div className="question-box active">
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
            </div>
            <label className="model-selector">
              <span>Answer model</span>
              <select
                value={generationModel}
                onChange={(event) =>
                  setGenerationModel(event.target.value as GenerationModel)
                }
              >
                <option value="gemma2:2b">gemma2:2b · default fast local</option>
                <option value="qwen3.5:9b">qwen3.5:9b · quality check</option>
              </select>
            </label>
          </form>

          {error ? <p className="form-error">{error}</p> : null}
        </section>

        {(streamText || streamDone || response) ? (
          <>
            <section className="answer-card">
              <div className="section-heading">
                <div>
                  <p className="eyebrow">Answer</p>
                  <h2>Generated from packed evidence</h2>
                </div>
                <small>{streamDone?.generation_model ?? response?.answer.model ?? generationModel}</small>
              </div>
              <p>
                {streamDone?.answer ?? streamText ?? response?.answer.text ?? ""}
                {loading && !streamDone ? <span className="stream-cursor" /> : null}
              </p>
              <div className="score-row">
                {streamDone ? (
                  <Link href={`/traces/${streamDone.trace_id}`}>open stored trace</Link>
                ) : response ? (
                  <Link href={`/traces/${response.trace_id}`}>open stored trace</Link>
                ) : null}
                {(streamDone?.citation_ids ?? response?.answer.citation_ids ?? []).length ? (
                  <div className="citation-chips" aria-label="Answer citations">
                    <span>citations</span>
                    {(streamDone?.citation_ids ?? response?.answer.citation_ids ?? []).map((id) => (
                      <button
                        className={activeCitation === id ? "citation-chip active" : "citation-chip"}
                        key={id}
                        type="button"
                        onClick={() => selectCitation(id)}
                      >
                        [{id}]
                      </button>
                    ))}
                  </div>
                ) : (
                  <span>citations —</span>
                )}
                {response ? (
                  <>
                    <span>{response.answer.prompt_token_estimate} prompt tokens est.</span>
                    <span>{response.answer.prompt_chars} prompt chars</span>
                  </>
                ) : null}
              </div>
              {response ? (
                <div className="query-analysis-summary">
                  <span>intent: {response.query_analysis.intent.replaceAll("_", " ")}</span>
                  <span>
                    topics:{" "}
                    {response.query_analysis.topics.length
                      ? response.query_analysis.topics.map((t) => t.replaceAll("_", " ")).join(", ")
                      : "none"}
                  </span>
                  {response.query_analysis.expansions.length ? (
                    <details>
                      <summary>Expanded retrieval terms</summary>
                      <p>{response.query_analysis.expansions.join(", ")}</p>
                    </details>
                  ) : null}
                </div>
              ) : null}
            </section>

            {(streamDone || (!loading && liveStages.length > 0) || response) ? (
              <LatencySummaryCard
                stages={liveStages.length > 0 ? liveStages : (response?.stages ?? [])}
                model={streamDone?.generation_model ?? response?.answer.model ?? generationModel}
              />
            ) : null}
          </>
        ) : null}

        <section className="trace-results-grid">
          <div className="retrieval-trace-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Trace</p>
                <h2>Pipeline stages</h2>
              </div>
              {response ? <small>{response.mode.replaceAll("_", " ")}</small> : null}
            </div>

            {(liveStages.length > 0 || response) ? (
              <div className="retrieval-stage-list">
                {(liveStages.length > 0 ? liveStages : (response?.stages ?? [])).map((stage) => (
                  <article className="retrieval-stage" key={stage.sequence}>
                    <span>{String(stage.sequence).padStart(2, "0")}</span>
                    <div>
                      <h3>{stage.stage}</h3>
                      <p>{stage.message}</p>
                      <dl>
                        <div><dt>Status</dt><dd>{stage.status}</dd></div>
                        <div><dt>Time</dt><dd>{stage.duration_ms} ms</dd></div>
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
                {loading && !streamDone ? (
                  <article className="retrieval-stage streaming-stage">
                    <span className="stream-cursor" />
                    <div><h3>generating…</h3></div>
                  </article>
                ) : null}
              </div>
            ) : (
              <p className="document-empty">
                Run a query to see dense retrieval, sparse retrieval, rank fusion,
                reranking, context packing, answer generation, and evidence preview
                stages.
              </p>
            )}
          </div>

          <div className="retrieval-results-card">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Evidence</p>
                <h2>Top chunks</h2>
              </div>
              {(streamDone?.results ?? response?.results) ? (
                <small>{(streamDone?.results ?? response?.results)!.length} result(s)</small>
              ) : null}
            </div>
            {feedbackError ? <p className="form-error">{feedbackError}</p> : null}

            {(streamDone?.results ?? response?.results ?? []).length ? (
              <div className="retrieval-results">
                {(streamDone?.results ?? response?.results ?? []).map((result, index) => (
                  <article className="retrieval-result" key={result.chunk_id}>
                    <div className="result-head">
                      <span>#{result.final_rank || index + 1}</span>
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
                      <span>rerank {formatScore(result.rerank_score)}</span>
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

                    <div className="feedback-panel">
                      <span>
                        {feedbackByChunk[result.chunk_id]
                          ? `Saved: ${feedbackByChunk[result.chunk_id].replace("incomplete", "relevant but incomplete")}`
                          : "Human review"}
                      </span>
                      <div>
                        <button
                          className={
                            feedbackByChunk[result.chunk_id] === "correct" ? "selected" : ""
                          }
                          type="button"
                          onClick={() => void submitFeedback(result, "correct")}
                        >
                          Correct evidence
                        </button>
                        <button
                          className={
                            feedbackByChunk[result.chunk_id] === "incomplete"
                              ? "selected"
                              : ""
                          }
                          type="button"
                          onClick={() => void submitFeedback(result, "incomplete")}
                        >
                          Relevant but incomplete
                        </button>
                        <button
                          className={
                            feedbackByChunk[result.chunk_id] === "wrong" ? "selected" : ""
                          }
                          type="button"
                          onClick={() => void submitFeedback(result, "wrong")}
                        >
                          Wrong / not useful
                        </button>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            ) : (streamDone || response) ? (
              <p className="document-empty">
                No chunks were returned. Confirm at least one document is indexed.
              </p>
            ) : (
              <p className="document-empty">
                Evidence chunks will appear here after a query.
              </p>
            )}

            {(liveContext ?? response?.packed_context) ? (() => {
              const ctx = liveContext ?? response?.packed_context;
              if (!ctx) return null;
              return (
                <div className="packed-context-card">
                  <div className="section-heading compact">
                    <div>
                      <p className="eyebrow">Context</p>
                      <h2>Prompt evidence pack</h2>
                    </div>
                    <small>
                      {ctx.token_estimate} est. tokens ·{" "}
                      {ctx.char_count}/{ctx.max_chars} chars
                    </small>
                  </div>
                  <div className="context-blocks">
                    {ctx.blocks.map((block) => (
                      <article
                        className={activeCitation === block.citation_id ? "context-block active" : "context-block"}
                        id={`chat-evidence-${block.citation_id}`}
                        key={block.citation_id}
                      >
                        <h3>[{block.citation_id}] {block.source_filename ?? "Unknown source"}</h3>
                        <p>
                          Chunk {block.chunk_index ?? "—"}
                          {block.section_title ? ` · ${block.section_title}` : ""}
                          {block.page_number ? ` · page ${block.page_number}` : ""}
                        </p>
                      </article>
                    ))}
                  </div>
                  {(() => {
                    const pc = "prompt_context" in ctx ? (ctx as { prompt_context?: string }).prompt_context : undefined;
                    return pc ? (
                      <details className="prompt-preview">
                        <summary>Show packed prompt context</summary>
                        <pre>{pc}</pre>
                      </details>
                    ) : null;
                  })()}
                </div>
              );
            })() : null}
          </div>
        </section>
      </div>
    </>
  );
}
