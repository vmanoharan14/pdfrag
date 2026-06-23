# Enterprise RAG Plan

## Summary

Build a greenfield **enterprise RAG system** for accurate, low-latency Q&A over PDFs, Office files, spreadsheets, HTML/Markdown/text, images/scans, tables, forms, and table-like content.

Stack:

- **LLM:** Qwen
- **Metadata DB:** PostgreSQL
- **Vector DB:** Qdrant
- **Cache / Queue / Live Events:** Redis
- **Backend:** Python 3.13 + FastAPI
- **Frontend:** React / Next.js
- **Parser:** Docling primary, Apache Tika fallback
- **Observability:** visual RAG trace console + OpenTelemetry

Initial local development is single-user and English-only. Authentication and multi-tenant enforcement are deferred, but request context and storage interfaces must leave a clean path to OIDC and tenant isolation later.

The system must show a clear visual picture of what happens when a user asks a question:

```text
query received
  -> ACL filter
  -> dense retrieval
  -> BM25 retrieval
  -> merge
  -> rerank
  -> context packing
  -> Qwen answer
  -> citations
  -> latency breakdown
```

---

## 1. Retrieval, Embedding, and BM25 Decision

BM25 is **not** an embedding model. BM25 is sparse lexical search. It is excellent for exact terms such as:

- invoice numbers
- policy IDs
- names
- codes
- abbreviations
- dates
- table cell values

Dense embeddings are semantic search. They are better when the user asks with different wording from the document.

Use both.

### Active Implementation Model Stack

Use the following models for the initial implementation:

| Model | Purpose in the app | Status |
|---|---|---|
| `nomic-embed-text` | Dense embeddings for semantic search, retrieval, and embedding cache keys | Active |
| `Qdrant/bm25` | Sparse lexical encoder used in hybrid retrieval alongside dense vectors | Active |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranks retrieved chunks and final evidence candidates | Active |
| `gemma2:2b` | CPU-hosted router for intent classification, retrieval-path selection, and lightweight query rewriting | Active |
| `qwen3.5:9b` | Main generation model for answers and conversation summarization | Active |

This stack fits the current development machine better than running separate multi-billion-parameter embedding and reranking models alongside the generator. The detected GPU is an NVIDIA GeForce RTX 5070 Laptop GPU with 8 GB VRAM, so local services must avoid assuming that all models can remain GPU-resident concurrently.

### Model Responsibilities

- `gemma2:2b` handles bounded, structured routing tasks:
  - intent classification
  - whether query rewriting is needed
  - table/form/comparison detection
  - retrieval strategy hints
- Run `gemma2:2b` for every user query before retrieval so it can select the appropriate retrieval path.
- Run the router on CPU and give `qwen3.5:9b` priority on the GPU.
- Enforce a 1.5-second router timeout and deterministic hybrid-retrieval fallback. Router failure or slowness must not prevent retrieval.
- Limit CPU worker concurrency so routing, MiniLM reranking, parsing, and ingestion do not exhaust memory or contend across all CPU cores.
- `nomic-embed-text` handles dense query and document embeddings.
- Qdrant BM25 handles sparse lexical encoding and scoring.
- `cross-encoder/ms-marco-MiniLM-L-6-v2` reranks the fused candidate set.
- `qwen3.5:9b` generates grounded answers and summarizes conversations.
- Routing must have a deterministic fallback so retrieval still works when `gemma2:2b` is unavailable or returns invalid structured output.
- Query rewriting must preserve identifiers, quoted text, dates, codes, names, and numbers. The original query must always remain available to BM25 retrieval.
- Conversation summaries must not replace source evidence or be treated as authoritative retrieval context.

### Production Upgrade Candidates

The initial models are operational defaults, not permanent production commitments. Evaluate upgrade candidates on domain-specific retrieval and answer-quality datasets:

- **Dense embedding:** `Qwen3-Embedding-0.6B`, `Qwen3-Embedding-4B`, or BGE-M3.
- **Text reranker:** `Qwen3-Reranker-0.6B` or `Qwen3-Reranker-4B`.
- **Answer model:** a Qwen3.5 deployment selected by evaluation, latency, throughput, licensing, and available GPU capacity.
- **Visual retrieval:** `Qwen3-VL-Embedding-2B` and `Qwen3-VL-Reranker-2B` for page images, diagrams, screenshots, and visually structured scans.

Visual retrieval is an optional second-stage path. Text extraction and text retrieval remain the default because they are cheaper, easier to inspect, and easier to cite.

All model capabilities must be implemented behind provider interfaces so models can be changed without modifying ingestion or query orchestration:

- embedding provider
- sparse encoder provider
- reranker provider
- router provider
- generation provider

Store provider name, model identifier, model revision, vector dimension, normalization strategy, instruction template version, and pipeline version with generated artifacts. Changing embedding dimensions or embedding models requires a new named vector or collection migration; existing vectors must never be silently overwritten with incompatible vectors.

---

## 2. Latency Requirements

Latency is a first-class requirement, not an afterthought.

### Production Query Latency Targets

| Stage | p95 Target |
|---|---:|
| Deterministic query normalization | <= 100 ms |
| Router/rewrite model | <= 1.5 seconds timeout locally; optimize toward 500 ms p95 |
| ACL filter lookup | <= 100 ms |
| Dense + BM25 retrieval + fusion | <= 500 ms |
| Candidate expansion | <= 150 ms |
| Reranking | <= 700 ms |
| Context packing | <= 150 ms |
| First token latency | <= 3 seconds |
| Full answer latency for normal questions | <= 8 seconds |
| Cached safe response | <= 1 second |
| Trace write overhead | <= 100 ms |

### Latency Design Rules

- Run dense and BM25 retrieval in parallel.
- Invoke `gemma2:2b` for every query, but apply a 1.5-second timeout and fall back to standard dense + BM25 hybrid retrieval.
- Use Qdrant named dense and sparse vectors with server-side IDF-enabled BM25 scoring.
- Fuse dense and BM25 results using Reciprocal Rank Fusion by default. Keep DBSF as an evaluated alternative.
- Use Redis cache for repeated queries, document metadata, ACL filters, session state, and safe model responses.
- Scope every cache key by tenant, effective ACL/security context, document-version set, model identifiers, prompt version, and pipeline version.
- Use Qdrant metadata filters before vector scoring to reduce search space.
- Keep top-k controlled:
  - dense top-k: 40-80
  - sparse/BM25 top-k: 40-80
  - merged candidates before rerank: 50-100
  - final chunks to LLM: usually 6-15
- Use reranker batching.
- Stream responses so the user sees the first token quickly.
- Ingestion must be async; upload should not block until indexing is complete.
- Store trace events asynchronously where possible, but never lose the final trace summary.
- Precompute:
  - chunk metadata
  - document outlines
  - table summaries
  - page summaries
  - extracted form fields
- For large tables, retrieve table summaries first, then expand into row-level evidence only when needed.
- Cache ACL decisions and document metadata with short TTLs.
- Avoid sending unnecessary chunks to Qwen; keep context tight and high-confidence.
- Establish latency targets against named hardware profiles, corpus sizes, concurrency, and document-filter cardinality. Targets without those conditions are directional, not acceptance criteria.

---

## 3. Architecture

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React / Next.js | Chat UI and visual trace/admin console |
| Backend | Python 3.12 + FastAPI | APIs and explicit RAG pipeline |
| Metadata DB | PostgreSQL | Tenants, users, documents, chunks, ACLs, jobs, traces |
| Vector DB | Qdrant | Dense + sparse hybrid retrieval |
| Cache / Live Events | Redis | Cache, live trace events, sessions, and rate limits |
| Durable Job Queue | Dramatiq with Redis | Async ingestion with acknowledgements, retries, and dead-letter handling |
| Object Storage | MinIO locally; S3-compatible storage in production | Originals, parsed JSON, page images, OCR artifacts |
| Model Serving | Host-native Ollama plus dedicated host-native embedding/reranking runtimes in development; benchmark-selected serving in production | CPU routing, GPU-prioritized generation, embedding, and reranking |
| Observability | OpenTelemetry + optional Langfuse | Service traces, LLM traces, evaluations |

Avoid a black-box chain. The RAG pipeline must be explicit and inspectable.

Use Docker Compose locally for PostgreSQL, Qdrant, Redis, and MinIO only. Run Ollama, embedding/reranking processes, FastAPI, Dramatiq workers, and the Next.js application directly on the host. Use npm for frontend package management.

---

## 4. Ingestion Pipeline

1. Store the original file in object storage.
2. Create `document`, `document_version`, and `ingestion_job` records in PostgreSQL.
   - Make upload and ingestion idempotent using tenant, source hash, requested operation, and document version.
   - Record an immutable source checksum before processing.
3. Detect file type.
4. Parse using:
   - **Docling** as the primary parser.
   - LibreOffice conversion for older Office formats if needed.
   - Apache Tika as fallback for obscure or legacy formats.
5. Extract canonical structure:
   - pages
   - headings
   - paragraphs
   - lists
   - tables
   - forms/key-value fields
   - captions
   - footnotes
   - OCR text
   - page numbers
   - bounding boxes where available
6. Run quality checks:
   - empty page detection
   - OCR confidence
   - table extraction confidence
   - form extraction confidence
   - duplicate detection
   - extraction coverage score
7. Chunk layout-aware:
   - small tables stay as one chunk
   - large tables split by row groups while preserving headers
   - form key/value pairs stay together
   - prose chunks by heading/section with overlap
   - table-like text is detected and normalized as table chunks where possible
8. Store metadata on every chunk:
   - tenant id
   - ACL ids
   - document id
   - version id
   - page number
   - section title
   - element type
   - parser used
   - table headers
   - bounding box
   - source file hash
9. Generate:
   - dense embedding
   - sparse/BM25 representation
   - reranker-ready text
10. Store chunk metadata in PostgreSQL.
11. Store dense and sparse vectors in Qdrant.
12. Emit ingestion trace events to Redis/PostgreSQL.
13. Mark the document version active only after metadata and vector writes complete successfully.
14. Retry transient failures with bounded exponential backoff.
15. Send permanently failed jobs to a dead-letter queue with the failed stage, retry count, and operator action.
16. Make reprocessing safe: repeated execution must not create duplicate chunks or expose a partially indexed document version.

---

## 5. Query Pipeline

When a user asks a question:

1. `POST /api/chat` receives a question, optional conversation id, and optional filters.
   - Local v1 uses a fixed development principal and tenant context supplied by trusted server configuration.
   - Do not expose client-controlled tenant or ACL identifiers.
   - Add verified OIDC claims and full tenant isolation in a later security milestone.
2. Create `trace_id`.
3. Build ACL/RBAC filter before retrieval.
4. Normalize query:
   - clean text
   - detect language
   - classify intent:
     - factual lookup
     - table lookup
     - form lookup
     - comparison
     - summary
     - multi-document question
   - Run `gemma2:2b` on CPU for every query to select the retrieval path.
   - Use standard dense + BM25 hybrid retrieval when the router exceeds 1.5 seconds, is unavailable, or returns invalid output.
   - Preserve the original query and exact identifiers through rewriting.
5. Run dense retrieval in Qdrant with the effective ACL filter.
6. Run BM25/sparse retrieval in Qdrant with the same effective ACL filter.
7. Fuse dense and sparse candidates with RRF by default.
8. Expand candidates with:
   - neighboring chunks
   - same section
   - table headers
   - footnotes
   - form labels
9. Rerank candidates.
10. Pack final context:
    - deduplicate overlapping chunks
    - preserve citation metadata
    - enforce token budget
11. Generate answer with Qwen:
    - answer only from evidence
    - cite document/page/table/section
    - return "not enough evidence" if evidence is weak
12. Save final trace:
    - timings
    - scores
    - selected chunks
    - prompt size
    - model latency
    - answer
    - citations
    - cache status
    - authenticated security context identifier
    - model and pipeline versions

When authentication and multi-tenant access are enabled, the ACL filter must be applied inside every retrieval request. Post-filtering unauthorized candidates is not an acceptable security boundary.

---

## 6. Visual Trace Console

Build a trace dashboard for both chat and ingestion.

### Per-Question Trace

Show:

- original question
- normalized query
- user, tenant, ACL filter
- dense retrieval results
- BM25 retrieval results
- merged candidates
- reranker scores
- final selected chunks
- source document preview
- page/table/form preview
- final context sent to Qwen
- generated answer
- citations
- latency per stage
- cache hit/miss
- token usage
- failure stage and reason

In local v1, full traces, retrieved chunks, and final prompts are visible to all users of the local application. Still redact secrets, bearer tokens, credentials, and environment values. Add tenant- and role-based trace authorization when authentication is introduced.

### Per-Ingestion Trace

Show:

- file uploaded
- parser selected
- OCR status
- table extraction status
- form extraction status
- pages processed
- chunks created
- embeddings generated
- Qdrant upsert status
- warnings/errors

---

## 7. Public APIs

### `POST /api/documents`

Upload/import document.

Returns:

- `document_id`
- `version_id`
- `job_id`

### `GET /api/ingestion-jobs/{job_id}`

Returns:

- ingestion status
- parser used
- page count
- chunk count
- warnings
- errors

### `POST /api/chat`

Input:

- question
- optional conversation id
- optional filters

Output:

- answer
- citations
- trace id
- evidence status

Authentication middleware supplies the effective user, tenant, roles, and permissions. These values are not accepted as authoritative request fields.

For local v1, the server substitutes a fixed development principal. The API contract must not require clients to submit authoritative identity or tenant fields.

### `GET /api/traces/{trace_id}`

Returns full visual trace.

### `GET /api/documents/{document_id}`

Returns document metadata, versions, and processing status.

### `GET /api/document-versions/{version_id}/source`

Streams original file or extracted artifact if authorized.

---

## 8. Core Database Entities

- tenant
- user
- role
- permission
- document
- document_version
- document_acl
- chunk
- ingestion_job
- rag_trace
- rag_trace_step
- feedback
- eval_case
- eval_run

---

## 9. Test Plan

### Ingestion Tests

- Digital PDF with headings, paragraphs, tables, and footnotes.
- Scanned PDF requiring OCR.
- PDF form with key-value fields.
- DOCX with tables and images.
- PPTX with slide titles, notes, and tables.
- XLSX with multiple sheets, merged cells, and formulas.
- CSV with headers and numeric columns.
- HTML, Markdown, and plain text.
- Table-like content in plain text.
- Corrupted file returns clear failure.
- Unsupported file returns clear failure.
- Re-upload creates a new document version without corrupting old data.

### Retrieval Tests

- Exact lookup: policy number, invoice number, employee id, clause number.
- Semantic lookup where user wording differs from document wording.
- Table lookup from row/column relationship.
- Form lookup from key-value field.
- Multi-page answer using neighboring chunks.
- Multi-document comparison.
- No-evidence question returns "not enough evidence."
- Citation maps to document, page, and chunk.
- ACL test confirms unauthorized chunks are never retrieved.
- Router failure falls back to deterministic retrieval.
- Query rewriting preserves identifiers, dates, codes, quoted text, and numbers.
- Dense and BM25 retrieval use identical ACL filters.
- Cache keys do not collide across tenants, ACL contexts, document versions, or model/pipeline versions.
- Reindexing with a new embedding model does not corrupt or mix vector dimensions.

### Latency Tests

- Query normalization p95 <= 100 ms.
- CPU router/rewrite model must time out at 1.5 seconds; optimize toward p95 <= 500 ms and measure it separately.
- ACL lookup p95 <= 100 ms.
- Retrieval + fusion p95 <= 500 ms.
- Candidate expansion p95 <= 150 ms.
- Reranking p95 <= 700 ms.
- Context packing p95 <= 150 ms.
- First token p95 <= 3 seconds.
- Full answer p95 <= 8 seconds for normal questions.
- Cached response p95 <= 1 second.
- Trace overhead <= 100 ms.

### Observability Tests

- Every chat response has `trace_id`.
- Every ingestion job has step-level trace.
- Trace shows dense, sparse, merged, reranked, and selected evidence.
- Trace records cache hit/miss.
- Trace records per-stage latency.
- Failed jobs identify exact failed stage.
- Admin UI filters by user, document, latency, status, and error type.
- Local v1 exposes traces to all local application users; later authenticated deployments require tenant and role authorization.
- Sensitive authentication data and secrets never appear in traces.

### Evaluation Gates

Maintain versioned evaluation datasets for:

- exact lexical lookup
- semantic paraphrase retrieval
- table and form lookup
- multi-document comparison
- scanned and OCR-heavy documents
- citation correctness
- no-evidence refusal
- ACL isolation

Measure at minimum:

- Recall@k for dense, sparse, and fused retrieval
- MRR or nDCG for ranked candidates
- reranker lift over fused retrieval
- citation precision and citation coverage
- grounded answer correctness
- no-evidence precision and recall
- p50/p95 latency and throughput

No model or prompt upgrade is promoted solely from public benchmark results. It must improve the project evaluation set without violating the relevant latency and infrastructure budget.

Use deterministic and directly measurable metrics as the primary evaluation
gates. Add RAGAS as an optional offline evaluation adapter for:

- faithfulness
- response relevance
- context precision
- context recall

RAGAS must not be part of the request-time query pipeline. Run it against
versioned evaluation datasets and store the evaluator model, prompt, metric
version, and raw rationale with each result. Treat LLM-judged scores as
directional evidence rather than ground truth, and do not use the answer model
as the only evaluator of its own responses.

---

## 10. Delivery Milestones

Build the system as vertical, testable increments.

### Milestone 0: Repository and Engineering Baseline

- Initialize Git and commit the reviewed plan.
- Add backend and frontend project structure.
- Add formatting, linting, type checking, tests, environment validation, and local service orchestration.
- Document supported hardware profiles and model configuration.
- Use the existing host Python 3.13 interpreter with an isolated project virtual environment.
- Add Docker Compose for PostgreSQL, Qdrant, Redis, and MinIO only.
- Run models and application processes directly on the host.
- Use npm for the frontend.

### Milestone 1: Local Text RAG

- Fixed server-side development principal with authentication deferred.
- PDF/text/Markdown ingestion.
- PostgreSQL metadata, object storage, Qdrant dense + BM25 vectors.
- `nomic-embed-text`, Qdrant BM25, MiniLM reranking, `gemma2:2b` routing, and `qwen3.5:9b`.
- SSE streaming for answers and live trace events.
- Answer citations and a minimal per-question trace.
- Core ACL, retrieval, grounding, and latency tests.

### Milestone 2: Durable Ingestion and Enterprise Formats

- Durable queue, retries, dead-letter handling, and idempotent reprocessing.
- DOCX, PPTX, XLSX, CSV, HTML, OCR, tables, and forms.
- Parser quality metrics and ingestion trace UI.

### Milestone 3: Conversation and Routing Hardening

- Expand and evaluate `gemma2:2b` intent routing and bounded query rewriting beyond the initial routing cases.
- Conversation summarization with provenance-safe context handling.
- Cache isolation and invalidation.

### Milestone 4: Admin Trace Console and Evaluations

- Full visual trace console.
- Feedback and evaluation entities.
- Automated retrieval, grounding, security, and latency evaluation gates.
- Optional offline RAGAS adapter for faithfulness, response relevance, context
  precision, and context recall.

### Milestone 4A: Authentication and Tenant Isolation

- Integrate an OIDC provider selected for the deployment environment.
- Replace the fixed development principal with verified claims.
- Add tenant memberships, role assignments, group membership, role permissions, and group/document ACL mappings.
- Enforce tenant and role authorization for documents, traces, feedback, and administration.

### Milestone 5: Production Model and Scale Validation

- Benchmark Qwen embedding, reranking, generation, and optional visual retrieval candidates.
- Load, concurrency, failover, backup, migration, and disaster-recovery validation.
- Promote models and latency SLOs only after measurements on named production hardware.

---

## 11. Assumptions

- This is a greenfield implementation.
- Old/reference implementation is ignored.
- Production is optimized for GPU server infrastructure.
- Local Ollama models are used only for development and testing.
- Local v1 is English-only.
- Local v1 uses no external authentication and is not suitable for exposure to untrusted networks.
- The local latency targets are optimization goals on the current host, not production SLO guarantees.
- Delivery is incremental; secure text RAG is completed before adding the full enterprise format and visual feature set.
- Audio/video transcription is deferred.
- Accuracy is preferred over forced answers.
- Embedding model is pluggable.
- BM25 is mandatory as part of hybrid retrieval.
- Low latency is mandatory and measured at every stage.
- Model selection is evaluation-driven and recorded with explicit revisions and pipeline versions.
