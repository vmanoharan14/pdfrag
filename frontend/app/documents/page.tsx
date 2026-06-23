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
};

const backendUrl =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:18000";

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
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
    fetch(`${backendUrl}/api/documents`, { cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error("Could not load documents.");
        return response.json();
      })
      .then((payload: DocumentItem[]) => {
        if (active) {
          setDocuments(payload);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : "Request failed.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
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

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Library</p>
          <h1>Documents</h1>
        </div>
        <span className="status-pill neutral">Upload persistence only</span>
      </header>

      <div className="page-content documents-page">
        <section className="upload-card">
          <div>
            <p className="eyebrow">Add source</p>
            <h2>Upload a document</h2>
            <p>
              This slice stores the original in MinIO and creates document,
              version, and ingestion-job records. Parsing starts in the next
              slice.
            </p>
          </div>

          <form onSubmit={upload}>
            <label className="file-picker" htmlFor="document-file">
              <span>{selected ? selected.name : "Choose PDF, Markdown, or text"}</span>
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
              documents.map((item) => (
                <article className="document-row" key={item.version_id}>
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
                  <span className="queue-state">
                    <i />
                    {item.current_stage.replaceAll("_", " ")}
                  </span>
                  <code>{item.job_id.slice(0, 8)}</code>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
    </>
  );
}
