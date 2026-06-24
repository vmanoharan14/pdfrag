# PDFRAG Project Decisions and Findings

Last updated: 2026-06-24

This file records decisions, findings, and pending implementation slices so the
project can be resumed without relying on chat memory.

## Working Process

- Build one small, testable slice at a time.
- Stop when the user can test a visible behavior.
- Commit only after the user confirms the slice looks good.
- Do not implement broad changes in one pass.
- Challenge inconsistencies and ask questions when the requested direction
  conflicts with observed behavior or the architecture.
- Keep the RAG pipeline explicit and visually inspectable.

## Local Development Constraints

- Local development uses host-native Python and npm.
- Docker Compose is used only for infrastructure services:
  PostgreSQL, Qdrant, Redis, and MinIO.
- Ollama and app processes run on the host, not inside Docker.
- Local v1 is English-only.
- Local v1 uses a fixed development principal; real authentication and tenant
  isolation are deferred.
- Local traces are visible to local users for debugging.
- Accuracy is preferred over forced answers.

## Active Model Stack

| Model | Purpose | Current Decision |
|---|---|---|
| `nomic-embed-text` | Dense embeddings | Active |
| `Qdrant/bm25` / local BM25 sparse encoder | Sparse lexical retrieval | Active |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranking | Active, batch=32, threads=4, max_length=512 |
| `gemma2:2b` | Default local answer generation | Active default — fastest response, 7/7 golden |
| `gemma4:e4b` | Quality answer generation | Active — selectable when faithfulness matters more than speed |

## Generation Model Decision

Default local answer generation is `gemma2:2b` (fast, 7/7 golden). `gemma4:e4b` is available as the quality option.

### Model Evaluation — Full Benchmark (7-case golden suite + RAGAS)

Five models were evaluated. RAGAS scores use `gemma3:4b` as the evaluator judge.
Timings are post-warmup averages over 5 answered cases.

| Model | Golden | Avg gen | Avg total | Faithfulness | Context Precision | Decision |
|---|---|---:|---:|---:|---:|---|
| `gemma2:2b` | 7/7 | 1,117 ms | 2,100 ms | 0.67 | — | **Active default** — fastest response |
| `qwen2.5:1.5b-instruct` | 7/7 | 1,265 ms | 2,475 ms | 0.80 | 0.63 | Removed — weaker faithfulness |
| `gemma3:4b` | 7/7 | 3,280 ms | 4,500 ms | 0.93 | 0.65 | Removed — superseded by gemma4 |
| `gemma4:e2b` | 7/7 | 3,256 ms | ~10,000 ms* | **0.93** | 0.74 | Removed — unpredictable total latency |
| `gemma4:e4b` | 7/7 | 5,577 ms | 7,800 ms | 0.90 | **0.90** | Active quality option |

*gemma4:e2b total time was inflated by model-swap overhead; generation time itself was comparable to gemma3:4b.

### Why gemma4:e4b

- **Highest context precision (0.90)** — generates answers that align tightly with retrieved evidence, leaving irrelevant chunks unused
- **Strong faithfulness (0.90)** — consistently grounded; 4 of 6 golden cases scored 1.000
- **128K context window** — ready for plan-filtered multi-document retrieval (pending slice #2)
- **Multimodal architecture** — future-proofed for image/table extraction improvements
- Trade-off accepted: ~7.8s avg total vs ~2.1s for gemma2:2b; cache hits drop to ~300ms regardless

### Remaining Models

Only two models are registered in the system:

| Model | Role | Avg total latency |
|---|---|---|
| `gemma2:2b` | Default — fast | ~2.1s (fresh), ~300ms (cache) |
| `gemma4:e4b` | Quality option | ~7.8s (fresh), ~300ms (cache) |

All other models (gemma3:4b, gemma4:e2b, qwen2.5:1.5b-instruct, qwen3.5:9b) have been removed from Ollama and the codebase.

## Router Decision

LLM-based routing adds ~1.5 s latency locally without changing the retrieval path.
Disabled by default. Deterministic hybrid retrieval is the default.

```text
router_enabled=false
```

## Retrieval Pipeline Decision

Current request-time pipeline:

```text
query analysis          → topic expansion, term expansion
security context        → fixed local principal (local v1)
response cache          → exact hash hit (no pipeline) or semantic hit (no pipeline)
intent routing          → skipped locally by default
dense retrieval         → nomic-embed-text, Qdrant
sparse retrieval        → BM25, Qdrant
rank fusion             → reciprocal rank fusion
candidate expansion     → ±1 neighboring chunks around top 6 fused candidates
rerank                  → MiniLM cross-encoder, batch=32, threads=4
feedback adjustment     → apply_feedback_adjustments() adjusts rerank scores
feedback exclusion      → candidates at cap (−4.0) removed before context packing
context packing         → top admissible chunks packed into prompt
answer generation       → Ollama streaming
trace persistence       → persist_stream_trace after generation
```

## Feedback-Driven Reranking Decision

Admin votes adjust rerank scores at query time via `apply_feedback_adjustments()`.

Score deltas:

| Label | Delta |
|---|---|
| correct | +1.5 |
| incomplete | +0.3 |
| wrong | −2.0 |

Cap: ±4.0 (chunks never boosted or penalised beyond this).

**Feedback exclusion rule**: if `feedback_adjustment <= -FEEDBACK_ADJUSTMENT_CAP`,
the chunk is hard-excluded from context packing entirely. Rationale: when ALL
retrieved results have been marked wrong (and hit the cap), ranking penalty alone
is not enough — they would still win by default with no better alternatives.
Exclusion forces the generator to see an empty context and say "not enough evidence."

**Cache invalidation on wrong vote**: when a chunk receives a "wrong" label in
`POST /api/retrieval/feedback`, any `response_cache` entries whose `context_snapshot`
includes that `chunk_id` are deleted immediately. This prevents stale answers
from being served from cache after feedback is given.

Both adjustments apply in the SSE path (`/api/chat/stream`) and the non-SSE
retrieval path (`/api/retrieval/search`).

Feedback is admin-only. The user portal (`/search`) has no feedback buttons.

## User Portal Decision

A separate user-facing search portal exists at `/search`.

Implementation:
- Next.js route groups `(admin)/` and `(user)/` scope layouts without URL changes.
- Admin pages (`/`, `/chat`, `/documents`, `/traces`) get the sidebar layout.
- User portal (`/search`) gets a clean, minimal layout with no sidebar.

User portal design choices:
- No "from cache" badge — users do not need to know about internal caching.
- No feedback buttons — only admins can vote on evidence quality.
- Suggested questions as chips for first-time users.
- SSE streaming answer with live status labels (friendly, not technical stage names).
- Source list deduped by filename + section.

## Table/Form-Aware Chunking Decision

Docling exports tables as pipe-formatted markdown with cell widths padded to match
content. For a 2-column benefits table (description | amount), the separator row
contains hundreds of dashes. This has two problems:

1. The cross-encoder's token budget is consumed by separator noise before reaching
   dollar amounts deep in the chunk.
2. Large tables (51 detected in the TX-NEXUS 210-page PDF) were emitted as one
   oversized chunk, bypassing `MAX_CHUNK_CHARS`.

Fixes applied in `backend/app/chunking.py`:

- `normalize_table_markdown()` — collapses `|---N---| → | --- |` and strips cell
  padding. Cuts chunk size ~50%, brings amounts to the top of the token window.
- `split_large_table()` — splits tables at row boundaries, repeating the header
  on each part so every chunk is independently parseable.
- `is_form_block()` — detects key-value sections (≥60% lines match `Key: value`)
  and tags them `element_type="form"`.
- Section heading prepended to every table/form chunk as context prefix so
  embedding is self-contained (e.g., `"In-Network Coverage\n\n| Service | Copay |..."`).

Validation: 12 unit tests in `backend/tests/test_chunking.py`. After re-indexing
the TX-NEXUS document, deductible and out-of-pocket queries correctly return
specific dollar amounts.

Known limitation: `normalize_table_markdown` works on markdown pipe tables only.
Docling exports tables in this format; other parsers may differ.

## Streaming Render Batching Decision

Problem: SSE token events arrive at 20–40 tokens/second. Each token called
`setStreamText((p) => p + token)`, causing a React re-render on every token.
For a 200-token response this is 200 full component re-renders.

Fix: buffer tokens in a `useRef`, schedule one `requestAnimationFrame` per render
cycle (at most ~60fps), and call `setStreamText` with the fully accumulated buffer.
Applied in both `/search` and admin `/chat` pages.

## Security Context Decision

Local v1 uses a fixed server-side principal. Clients do not submit authoritative
tenant, user, role, or ACL identifiers. This is a visible placeholder so the
pipeline has the correct stage shape before real OIDC is added.

## Response Cache Decision

Two-tier response cache is active.

**Tier 1 — Exact hash cache (PostgreSQL `response_cache`)**

Cache key: SHA-256(normalized query + tenant_id + generation model + pipeline version).

**Tier 2 — Semantic cache (Qdrant `pdfrag_response_cache_v1`)**

Threshold: **0.93** (raised from 0.75 after false positives in insurance domain:
"chest pain" vs "head pain" scored 0.84, "specialist copay" vs "emergency copay"
scored 0.86 — different questions with different answers).

**Cache invalidation**: when a chunk receives a "wrong" feedback vote, cache entries
that cited that chunk are immediately evicted. This ensures stale wrong answers
are not served after an admin marks them.

Cache management:

```text
GET  /api/cache  → {entries, total_hits, semantic_entries}
DELETE /api/cache → {deleted, semantic_deleted}
```

## Reranker Performance Decision

| Parameter | Before | After | Reason |
|---|---|---|---|
| `RERANK_BATCH_SIZE` | 8 | 32 | All 14–18 candidates in one forward pass |
| `torch.set_num_threads` | 24 (default) | 4 | Scheduling contention for small model — biggest win |
| `max_length` | 512 | **kept at 512** | 256 broke `no_evidence` (reranker needs full context to score irrelevant chunks sufficiently negative) |

Result: reranking **1,400–2,200 ms → ~1,000 ms**. Golden suite 7/7.

## Candidate Expansion Decision

After rank fusion, expand ±1 neighboring chunk around each of the top 6 fused
candidates before reranking. Reason: top retrieved chunk may not be the full
answer; neighbors contain section continuation, table headers, or eligibility context.

## API Decision

- `/api/chat` has been removed (blocking JSON endpoint).
- `/api/chat/stream` is the primary chat endpoint — SSE `text/event-stream`.
- `/api/retrieval/search` remains for the retrieval workbench and golden scripts.
- `/api/cache` (GET / DELETE) manages the two-tier response cache.
- `/api/retrieval/feedback` (POST) records admin votes and evicts stale cache.

SSE event types:

```text
stage   — one per pipeline stage as it completes (real-time)
context — packed context blocks before generation
token   — one per generated answer token
done    — final: answer, citation_ids, trace_id, retrieval_mode, from_cache, cached_at
```

`scripts/run_golden_queries.py` calls `/api/retrieval/search` — do not change this.

## Query Expansion Decision

Deterministic query analysis handles known topic expansion:
- enrollment
- mental health
- emergency care

Add terms only when observed in user questions AND source documents AND validated
by a golden case. Do not make this an uncontrolled synonym dump.

## Ingestion Quality Metrics Decision

Observability only. Stored in ingestion trace details and displayed in `/documents`.
Must not alter parsing, chunking, indexing, retrieval, or generation paths.

Metrics surfaced:
- parser used, page count, character count, chars/page
- empty page count, table/form detected counts
- chunk count, average/max chunk chars
- OCR used/needed indicators, human-readable warnings

## RAGAS Decision

Not required in request-time flow. Add only as optional offline evaluation adapter.
Store evaluator model, prompt, metric version, raw rationale. Treat LLM-judged
scores as directional, not ground truth.

## RAGAS Offline Evaluation Decision

RAGAS is integrated as an offline evaluation tool — not part of the request-time pipeline.

**Metrics stored per trace** (in `rag_evaluations` table):

| Metric | What it measures | Requires ground truth? |
|---|---|---|
| `faithfulness` | Are all answer claims supported by retrieved context? | No |
| `answer_relevancy` | Does the answer address the question? | No |
| `context_precision` | Are retrieved chunks relevant to the query? | No |

`answer_relevancy` consistently fails with small local models (gemma2:2b, gemma4:e4b) because they cannot reliably follow RAGAS's structured JSON output format for that metric. Faithfulness and context precision are reliable.

**Evaluator model**: `gemma3:4b` (not in Ollama by default — pull when running evals).

**RAGAS findings** from benchmark run:

- Context precision 0.000 on mental_health and emergency cases across all models = cross-plan bleed (TX-NEXUS chunks retrieved for NJ Transit questions). Not a model problem — pending slice #2 (plan filtering) fixes this.
- Specialist copay faithfulness is consistently the lowest case (0.500–0.833) — same root cause: irrelevant context chunks from a second plan document contaminating the answer.

Run command:
```bash
.venv/bin/python scripts/run_ragas_eval.py                         # last 20 unevaluated
.venv/bin/python scripts/run_ragas_eval.py --trace-id <uuid>       # single trace
.venv/bin/python scripts/run_ragas_eval.py --model gemma3:4b --rerun  # re-score all
```

## Admin Trace List Decision

`GET /api/traces` list endpoint added to `backend/app/traces.py`.

Supports query params: `?q=` (text search), `?evidence_status=`, `?cache_event=`, `?limit=`, `?offset=`.

Frontend `/traces` page replaces the old `/traces/demo` link in the sidebar. Shows question, evidence status, cache event, model, latency, and timestamp per trace. Client-side search and filter chips.

Trace detail page (`/traces/{id}`) now includes a RAGAS eval panel showing faithfulness, answer relevancy, and context precision score bars. Shows the run command if no scores exist yet.

## Completed Slices (summary)

1. Dense + sparse hybrid retrieval with RRF fusion.
2. Candidate expansion and MiniLM reranking.
3. Full RAG trace persistence and visual trace page.
4. Deterministic golden evaluation suite (7 cases, 7/7 passing).
5. Warmup-aware model latency comparison script.
6. `gemma2:2b` as initial default generation model.
7. Ingestion quality observability, document delete, re-chunk UI.
8. SSE streaming endpoint with real-time stages and token streaming.
9. Two-tier response cache: exact hash (PostgreSQL) + semantic (Qdrant 0.93).
10. Clear cache UI and `DELETE /api/cache`.
11. `retrieval_mode` propagated through SSE and stored in cache.
12. Semantic cache threshold calibrated to 0.93.
13. Reranker CPU tuning: batch=32, threads=4.
14. User-facing benefits search portal at `/search` with route groups.
15. Feedback-driven reranking with `apply_feedback_adjustments()`.
16. Admin-only feedback buttons; user portal has no feedback mechanism.
17. Feedback exclusion: chunks at −4.0 cap hard-excluded from context packing.
18. Cache invalidation when chunk receives "wrong" feedback vote.
19. Table/form-aware chunking: normalize, split, form detection, context prefix, 12 tests.
20. Streaming render batching via `requestAnimationFrame` in both portal pages.
21. Admin trace list page (`/traces`) with search, filters, and click-through to detail.
22. RAGAS offline evaluation: `rag_evaluations` table, `run_ragas_eval.py` script, eval panel in trace detail.
23. Multi-model benchmark (5 models, golden + RAGAS); `gemma2:2b` kept as default (fast), `gemma4:e4b` added as quality option; all other models removed.

## Pending Slices (priority order)

1. **Document routing / plan filtering** — prevent answer bleed between multiple plan docs (confirmed root cause of low context precision by RAGAS).
2. **Conversation support** — multi-turn with provenance-safe summaries.
3. **Admin trace list enhancements** — pagination, date range filter, latency histogram.
4. **More document formats** — DOCX, XLSX, CSV, HTML, PPTX, OCR fallback.
5. **FigJam architecture diagram update** — user portal, feedback loop, table chunking, RAGAS eval layer.
6. **Authentication and tenant isolation** — OIDC, roles, ACLs, Qdrant filters.

## Open Questions

- What threshold should trigger the optional LLM router in future?
- Should human feedback affect reranking through evaluation reports first, or
  automatically through ranking rules? (Currently: automatically at query time.)
- Which remaining golden questions should be added as the golden set grows?
- Which document formats should be prioritized after PDF: DOCX, XLSX, HTML, or scanned PDFs?
- Should the user portal support conversation history, or stay stateless?
