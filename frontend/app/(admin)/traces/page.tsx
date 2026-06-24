"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type TraceSummary = {
  trace_id: string;
  original_question: string;
  mode: string;
  evidence_status: string;
  cache_event: string;
  generation_model: string | null;
  total_latency_ms: number;
  created_at: string;
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:18000";

function evidencePillClass(status: string) {
  if (status === "answered") return "success";
  if (status === "no_evidence" || status === "insufficient_evidence") return "warning";
  return "neutral";
}

function cacheLabel(event: string) {
  if (event === "hit_exact") return "exact hit";
  if (event === "hit_semantic") return "semantic hit";
  return event;
}

function formatMs(ms: number) {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  return `${ms} ms`;
}

function formatDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
    " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

const EVIDENCE_FILTERS = ["all", "answered", "no_evidence", "insufficient_evidence"];
const CACHE_FILTERS = ["all", "miss", "hit_exact", "hit_semantic"];

export default function TracesPage() {
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [evidenceFilter, setEvidenceFilter] = useState("all");
  const [cacheFilter, setCacheFilter] = useState("all");

  useEffect(() => {
    setLoading(true);
    fetch(`${backendUrl}/api/traces?limit=100`, { cache: "no-store" })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => { setTraces(data); setLoading(false); })
      .catch((e) => { setError(e.message); setLoading(false); });
  }, []);

  const visible = traces.filter((t) => {
    if (search && !t.original_question.toLowerCase().includes(search.toLowerCase())) return false;
    if (evidenceFilter !== "all" && t.evidence_status !== evidenceFilter) return false;
    if (cacheFilter !== "all" && t.cache_event !== cacheFilter) return false;
    return true;
  });

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Admin</p>
          <h1>Query traces</h1>
        </div>
        <span className="status-pill neutral">{traces.length} stored</span>
      </header>

      <div className="page-content">
        <div className="trace-list-controls">
          <input
            className="trace-search-input"
            placeholder="Search questions…"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="trace-filter-group">
            <span className="filter-label">Evidence</span>
            {EVIDENCE_FILTERS.map((f) => (
              <button
                key={f}
                className={`filter-chip ${evidenceFilter === f ? "active" : ""}`}
                onClick={() => setEvidenceFilter(f)}
              >
                {f === "all" ? "All" : f.replace("_", " ")}
              </button>
            ))}
          </div>
          <div className="trace-filter-group">
            <span className="filter-label">Cache</span>
            {CACHE_FILTERS.map((f) => (
              <button
                key={f}
                className={`filter-chip ${cacheFilter === f ? "active" : ""}`}
                onClick={() => setCacheFilter(f)}
              >
                {f === "all" ? "All" : cacheLabel(f)}
              </button>
            ))}
          </div>
        </div>

        {loading && <p className="document-empty">Loading traces…</p>}
        {error && <p className="document-empty">Error: {error}</p>}

        {!loading && !error && (
          <div className="document-table">
            <div className="document-header document-row trace-list-row">
              <span>Question</span>
              <span>Evidence</span>
              <span>Cache</span>
              <span>Model</span>
              <span>Latency</span>
              <span>Time</span>
            </div>

            {visible.length === 0 && (
              <p className="document-empty">No traces match the current filters.</p>
            )}

            {visible.map((t) => (
              <Link
                key={t.trace_id}
                href={`/traces/${t.trace_id}`}
                className="document-entry trace-list-link"
              >
                <div className="document-row trace-list-row">
                  <div className="trace-question-cell">
                    <strong>{t.original_question}</strong>
                    <small>{t.trace_id.slice(0, 8)}</small>
                  </div>
                  <span>
                    <span className={`status-pill ${evidencePillClass(t.evidence_status)}`}>
                      {t.evidence_status.replace("_", " ")}
                    </span>
                  </span>
                  <span>
                    <span className={`status-pill ${t.cache_event.startsWith("hit") ? "success" : "neutral"}`}>
                      {cacheLabel(t.cache_event)}
                    </span>
                  </span>
                  <span className="trace-model-cell">{t.generation_model ?? "—"}</span>
                  <span>{formatMs(t.total_latency_ms)}</span>
                  <span className="trace-date-cell">{formatDate(t.created_at)}</span>
                </div>
              </Link>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
