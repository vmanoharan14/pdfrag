"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useState } from "react";

type DocumentItem = {
  document_id: string;
  version_id: string;
  job_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  status: string;
  current_stage: string;
  parser_used: string | null;
  page_count: number | null;
  chunk_count: number;
  indexed_chunk_count: number;
  vector_collection: string | null;
  steps: TraceStep[];
};

type TraceStep = {
  sequence: number;
  stage: string;
  status: string;
  message: string | null;
  details: Record<string, unknown> | null;
  duration_ms: number | null;
};

type DocumentChunk = {
  id: string;
  chunk_index: number;
  content: string;
  token_estimate: number;
  section_title: string | null;
  element_type: string;
  page_number: number | null;
  metadata: Record<string, unknown> | null;
  index_status: string;
  vector_collection: string | null;
  embedding_model: string | null;
  embedding_dimension: number | null;
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:18000";

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function collapseTraceSteps(steps: TraceStep[]): TraceStep[] {
  const grouped = new Map<string, TraceStep>();
  const latestRunStart = steps.findLastIndex((step) => step.stage === "worker_started");
  const currentRunSteps = latestRunStart >= 0 ? steps.slice(latestRunStart) : steps;

  for (const step of currentRunSteps) {
    const existing = grouped.get(step.stage);
    if (!existing) {
      grouped.set(step.stage, step);
      continue;
    }

    grouped.set(step.stage, {
      ...existing,
      ...step,
      sequence: existing.sequence,
      message: step.message ?? existing.message,
      details: step.details ?? existing.details,
      duration_ms: step.duration_ms ?? existing.duration_ms,
    });
  }

  return Array.from(grouped.values());
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [chunksByVersion, setChunksByVersion] = useState<
    Record<string, DocumentChunk[]>
  >({});
  const [expandedVersionId, setExpandedVersionId] = useState<string | null>(null);
  const [selected, setSelected] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const response = await fetch(`${backendUrl}/api/documents`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Could not load documents.");
      setDocuments(await response.json());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const response = await fetch(`${backendUrl}/api/documents`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Could not load documents.");
        const payload: DocumentItem[] = await response.json();
        if (active) {
          setDocuments(payload);
          setError(null);
          setLoading(false);
        }
      } catch (caught) {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Request failed.");
          setLoading(false);
        }
      }
    }

    void refresh();
    const interval = window.setInterval(() => void refresh(), 2000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    setSelected(event.target.files?.[0] ?? null);
    setError(null);
    setMessage(null);
  }

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;

    setUploading(true);
    setError(null);
    setMessage(null);
    const body = new FormData();
    body.append("file", selected);

    try {
      const response = await fetch(`${backendUrl}/api/documents`, {
        method: "POST",
        body,
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail ?? "Upload failed.");
      }
      setMessage(`Queued ${payload.filename} as job ${payload.job_id}.`);
      setSelected(null);
      const input = document.getElementById("document-file") as HTMLInputElement;
      input.value = "";
      await loadDocuments();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function retryJob(jobId: string) {
    setError(null);
    setMessage(null);
    try {
      const response = await fetch(
        `${backendUrl}/api/ingestion-jobs/${jobId}/retry`,
        { method: "POST" },
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail ?? "Could not queue ingestion.");
      }
      setMessage(`Queued ingestion job ${jobId}.`);
      await loadDocuments();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed.");
    }
  }

  async function toggleChunks(versionId: string) {
    if (expandedVersionId === versionId) {
      setExpandedVersionId(null);
      return;
    }

    setExpandedVersionId(versionId);
    if (chunksByVersion[versionId]) return;

    setError(null);
    try {
      const response = await fetch(
        `${backendUrl}/api/document-versions/${versionId}/chunks?limit=25`,
        { cache: "no-store" },
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail ?? "Could not load chunks.");
      }
      setChunksByVersion((current) => ({ ...current, [versionId]: payload }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed.");
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Library</p>
          <h1>Documents</h1>
        </div>
        <span className="status-pill success">Async parsing enabled</span>
      </header>

      <div className="page-content documents-page">
        <section className="upload-card">
          <div>
            <p className="eyebrow">Add source</p>
            <h2>Upload a document</h2>
            <p>
              The original is stored in MinIO, then a single CPU worker parses
              it asynchronously and records every ingestion stage below.
            </p>
          </div>

          <form onSubmit={upload}>
            <label className="file-picker" htmlFor="document-file">
              <span>
                {selected
                  ? selected.name
                  : "Choose digital PDF, Markdown, or text"}
              </span>
              <small>{selected ? formatBytes(selected.size) : "Maximum 50 MB"}</small>
              <input
                accept=".pdf,.md,.markdown,.txt,application/pdf,text/plain,text/markdown"
                id="document-file"
                onChange={chooseFile}
                type="file"
              />
            </label>
            <button className="upload-button" disabled={!selected || uploading}>
              {uploading ? "Uploading…" : "Upload and queue"}
            </button>
          </form>

          {message ? <p className="form-message success-message">{message}</p> : null}
          {error ? <p className="form-message error-message">{error}</p> : null}
        </section>

        <section className="document-list-section">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Stored originals</p>
              <h2>Ingestion queue</h2>
            </div>
            <small>{documents.length} document version(s)</small>
          </div>

          <div className="document-table">
            <div className="document-row document-header">
              <span>Document</span>
              <span>Size</span>
              <span>Stage</span>
              <span>Job</span>
            </div>
            {loading ? (
              <p className="document-empty">Loading documents…</p>
            ) : documents.length === 0 ? (
              <p className="document-empty">
                No documents yet. Upload a small file to test this slice.
              </p>
            ) : (
              documents.map((item) => {
                const stageSteps = collapseTraceSteps(item.steps);

                return (
                  <article className="document-entry" key={item.version_id}>
                    <div className="document-row">
                      <div className="document-name">
                        <span className="file-icon">
                          {item.media_type === "application/pdf" ? "PDF" : "TXT"}
                        </span>
                        <div>
                          <strong>{item.filename}</strong>
                          <small>sha256 {item.sha256.slice(0, 12)}…</small>
                        </div>
                      </div>
                      <span>{formatBytes(item.size_bytes)}</span>
                      <span className={`queue-state ${item.status}`}>
                        <i />
                        {item.current_stage.replaceAll("_", " ")}
                      </span>
                      <code>{item.job_id.slice(0, 8)}</code>
                    </div>
                    {stageSteps.length > 0 ? (
                      <div className="ingestion-trace">
                        <div className="ingestion-trace-summary">
                        <span>
                          {item.parser_used ?? "Parser pending"}
                          {item.page_count ? ` · ${item.page_count} page(s)` : ""}
                          {` · ${item.chunk_count} chunk(s)`}
                          {item.indexed_chunk_count > 0
                            ? ` · ${item.indexed_chunk_count} indexed`
                            : ""}
                        </span>
                        <div>
                          <strong>{item.status}</strong>
                          {item.chunk_count > 0 ? (
                            <button
                              className="retry-button"
                              onClick={() => void toggleChunks(item.version_id)}
                              type="button"
                            >
                              {expandedVersionId === item.version_id ? "Hide chunks" : "View chunks"}
                            </button>
                          ) : null}
                          {item.status === "queued" ||
                          item.status === "failed" ||
                          (item.status === "completed" &&
                            item.indexed_chunk_count < item.chunk_count) ||
                          (item.status === "completed" && item.chunk_count === 0) ? (
                            <button
                              className="retry-button"
                              onClick={() => void retryJob(item.job_id)}
                              type="button"
                            >
                              {item.status !== "completed"
                                ? "Process"
                                : item.chunk_count > 0
                                  ? "Build index"
                                  : "Build chunks"}
                            </button>
                          ) : null}
                        </div>
                        </div>
                        <ol>
                          {stageSteps.map((step, index) => (
                            <li
                              className={`ingestion-step ${step.status}`}
                              key={step.stage}
                            >
                              <span className="trace-sequence">
                                {String(index + 1).padStart(2, "0")}
                              </span>
                              <div>
                                <strong>{step.stage.replaceAll("_", " ")}</strong>
                                <small>{step.message}</small>
                              </div>
                              <time>
                                {step.duration_ms === null
                                  ? step.status
                                  : `${step.duration_ms} ms`}
                              </time>
                            </li>
                          ))}
                        </ol>
                        {expandedVersionId === item.version_id ? (
                          <div className="chunk-preview">
                            {(chunksByVersion[item.version_id] ?? []).map((chunk) => (
                              <article className="chunk-card" key={chunk.id}>
                                <div className="chunk-meta">
                                  <strong>#{chunk.chunk_index + 1}</strong>
                                  <span>{chunk.element_type}</span>
                                  <span>{chunk.token_estimate} tokens est.</span>
                                  <span>{chunk.index_status}</span>
                                  {chunk.section_title ? (
                                    <span>{chunk.section_title}</span>
                                  ) : null}
                                  {chunk.embedding_model ? (
                                    <span>
                                      {chunk.embedding_model}
                                      {chunk.embedding_dimension
                                        ? `/${chunk.embedding_dimension}`
                                        : ""}
                                    </span>
                                  ) : null}
                                </div>
                                <p>{chunk.content}</p>
                              </article>
                            ))}
                            {!chunksByVersion[item.version_id] ? (
                              <p className="chunk-loading">Loading chunks…</p>
                            ) : null}
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div className="ingestion-trace empty-trace">
                        <span>No worker events recorded yet.</span>
                        <button
                          className="retry-button"
                          onClick={() => void retryJob(item.job_id)}
                          type="button"
                        >
                          Process
                        </button>
                      </div>
                    )}
                  </article>
                );
              })
            )}
          </div>
        </section>
      </div>
    </>
  );
}
