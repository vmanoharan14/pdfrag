"use client";

import { FormEvent, useRef, useState } from "react";
import Link from "next/link";

type RetrievalStage = {
  sequence: number;
  stage: string;
  status: string;
  message: string;
  duration_ms: number;
  details: Record<string, unknown>;
};

type ContextBlock = {
  citation_id: string;
  chunk_id: string;
  source_filename: string | null;
  chunk_index: number | null;
  section_title: string | null;
  page_number: number | null;
  text: string;
};

type StreamedContext = {
  blocks: ContextBlock[];
};

type StreamResult = {
  source_filename: string | null;
  section_title: string | null;
  page_number: number | null;
  chunk_id: string;
};

type StreamDone = {
  trace_id: string | null;
  answer: string;
  citation_ids: string[];
  generation_model: string;
  retrieval_mode: string;
  from_cache: boolean;
  cached_at: string | null;
  results: StreamResult[];
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:18000";

const STAGE_LABELS: Record<string, string> = {
  "query analysis": "Analyzing your question...",
  "security context": "Checking access...",
  "response cache": "Looking for a quick answer...",
  "dense retrieval": "Searching your benefits documents...",
  "sparse retrieval": "Searching your benefits documents...",
  "rank fusion": "Ranking results...",
  "candidate expansion": "Expanding search...",
  rerank: "Finding the most relevant information...",
  "context packing": "Preparing your answer...",
  "answer generation": "Writing your answer...",
};

const SUGGESTED = [
  "How do I enroll in the plan?",
  "What is my copay for a specialist visit?",
  "Does the plan cover mental health treatment?",
  "What prescriptions are covered?",
  "What happens in an emergency?",
];

function friendlyLabel(stage: string) {
  return STAGE_LABELS[stage] ?? "Processing...";
}

function cleanSourceName(filename: string | null): string {
  if (!filename) return "Benefits document";
  const base = filename.split("/").pop() ?? filename;
  return base.replace(/\.[^.]+$/, "").replace(/[_-]/g, " ");
}

type Source = { name: string; section: string | null; page: number | null; key: string };

function buildSources(done: StreamDone | null, ctx: StreamedContext | null): Source[] {
  const raw = done?.results?.length ? done.results : ctx?.blocks ?? [];
  const seen = new Set<string>();
  const out: Source[] = [];
  for (const r of raw) {
    const k = `${r.source_filename ?? ""}::${r.section_title ?? ""}`;
    if (!seen.has(k)) {
      seen.add(k);
      out.push({ name: cleanSourceName(r.source_filename), section: r.section_title, page: r.page_number, key: k });
    }
  }
  return out;
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [liveStages, setLiveStages] = useState<RetrievalStage[]>([]);
  const [liveContext, setLiveContext] = useState<StreamedContext | null>(null);
  const [streamText, setStreamText] = useState("");
  const [streamDone, setStreamDone] = useState<StreamDone | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  const lastStage = liveStages[liveStages.length - 1];
  const statusLabel =
    loading && !streamDone && lastStage ? friendlyLabel(lastStage.stage) : null;

  const answerText = streamDone?.answer ?? streamText;
  const hasAnswer = answerText.length > 0;
  const sources = buildSources(streamDone, liveContext);

  async function runSearch(queryText: string) {
    const trimmed = queryText.trim();
    if (!trimmed) return;

    setSubmitted(true);
    setLoading(true);
    setError(null);
    setLiveStages([]);
    setLiveContext(null);
    setStreamText("");
    setStreamDone(null);

    try {
      const res = await fetch(`${backendUrl}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmed, generation_model: "gemma2:2b" }),
      });
      if (!res.ok || !res.body) {
        const payload = (await res.json()) as { detail?: string };
        throw new Error(payload.detail ?? "Search failed.");
      }

      const reader = res.body.getReader();
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
          const eventType =
            lines.find((l) => l.startsWith("event: "))?.slice(7) ?? "";
          const dataStr =
            lines.find((l) => l.startsWith("data: "))?.slice(5) ?? "";
          if (!eventType || !dataStr) continue;

          const data = JSON.parse(dataStr) as Record<string, unknown>;
          if (eventType === "stage")
            setLiveStages((p) => [...p, data as unknown as RetrievalStage]);
          else if (eventType === "context")
            setLiveContext(data as unknown as StreamedContext);
          else if (eventType === "token")
            setStreamText((p) => p + String(data.text ?? ""));
          else if (eventType === "done")
            setStreamDone(data as unknown as StreamDone);
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runSearch(query);
  }

  function handleSuggestion(text: string) {
    setQuery(text);
    void runSearch(text);
  }

  function handleNewSearch() {
    setSubmitted(false);
    setStreamDone(null);
    setStreamText("");
    setLiveStages([]);
    setLiveContext(null);
    setError(null);
    setQuery("");
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  return (
    <div className={`search-portal${submitted ? " search-portal--active" : ""}`}>
      <header className="search-header">
        <div className="search-brand">
          <span className="search-brand-mark">B</span>
          <strong>Benefits Search</strong>
        </div>
        <Link className="search-admin-link" href="/chat">
          Admin console
        </Link>
      </header>

      <div className="search-hero">
        {!submitted && (
          <div className="search-hero-text">
            <div className="search-icon">?</div>
            <h1>How can we help you today?</h1>
            <p>Ask any question about your benefits coverage.</p>
          </div>
        )}

        <form className="search-form" onSubmit={handleSubmit}>
          <div className="search-box">
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search your benefits..."
              aria-label="Search your benefits"
              autoComplete="off"
              autoFocus
            />
            <button
              type="submit"
              disabled={loading || !query.trim()}
              aria-label="Search"
            >
              {loading ? "…" : "→"}
            </button>
          </div>
        </form>

        {!submitted && (
          <div className="search-suggestions">
            <span>Try asking:</span>
            {SUGGESTED.map((s) => (
              <button
                key={s}
                type="button"
                className="suggestion-chip"
                onClick={() => handleSuggestion(s)}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>

      {submitted && (
        <div className="search-results">
          {error && <p className="search-error">{error}</p>}

          {loading && !hasAnswer && statusLabel && (
            <div className="search-status">
              <span className="search-spinner" />
              <span>{statusLabel}</span>
            </div>
          )}

          {hasAnswer && (
            <div className="search-answer">
              <div className="search-answer-header">
                <span className="search-answer-label">Answer</span>
                {streamDone?.from_cache && (
                  <span className="search-cached-badge">from cache</span>
                )}
              </div>

              <p className="search-answer-text">
                {answerText}
                {loading && !streamDone ? <span className="stream-cursor" /> : null}
              </p>

              {sources.length > 0 && !loading && (
                <div className="search-sources">
                  <span className="search-sources-label">Sources</span>
                  <div className="search-source-list">
                    {sources.map((s) => (
                      <div key={s.key} className="search-source">
                        <span className="search-source-icon">📄</span>
                        <div>
                          <strong>{s.name}</strong>
                          {s.section && (
                            <small>
                              {s.section}
                              {s.page ? ` · page ${s.page}` : ""}
                            </small>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {streamDone && (
            <button
              type="button"
              className="search-new-button"
              onClick={handleNewSearch}
            >
              Ask another question
            </button>
          )}
        </div>
      )}
    </div>
  );
}
