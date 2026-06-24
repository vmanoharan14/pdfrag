# PDFRAG Restart Plan

Last updated: 2026-06-25

Use this file to resume work after a break without relying on chat memory.

## Current Working Rule

- Implement one small, testable slice at a time.
- Stop when the user can validate something visible or measurable.
- Commit only after the user confirms the slice looks good.
- Keep questioning weak assumptions instead of blindly implementing requests.
- Keep `PROJECT_DECISIONS.md` updated when we make meaningful design decisions.

## Current Git State

Branch: `main`

Latest commits (pending commit for this session's work):

```text
cb35b50 docs: update NEXT_STEPS and PROJECT_DECISIONS with all session changes
604ec78 fix: exclude feedback-capped chunks from context and invalidate cache on wrong vote
b3f0d7d feat: table-aware chunking with streaming render batching
```

Golden suite: **7/7 passing** on `gemma4:e4b` and all tested models.

## Current Capabilities

### Backend / Retrieval

- `/api/chat/stream` — SSE streaming chat endpoint (`text/event-stream`).
- `/api/retrieval/search` — retrieval workbench and golden scripts.
- `/api/cache` (GET / DELETE) — two-tier response cache management.
- `/api/retrieval/feedback` (POST) — record admin evidence feedback; automatically
  evicts cache entries that cited the chunk when label is "wrong".
- `GET /api/traces` — paginated trace list with `?q=`, `?evidence_status=`, `?cache_event=` filters.
- `GET /api/traces/{trace_id}` — full trace detail with steps, context, timings.
- `GET /api/traces/{trace_id}/eval` — RAGAS evaluation scores for a trace.
- Query analysis expands known topics: enrollment, mental health, emergency care.
- LLM router stage exists but disabled by default locally.
- Hybrid retrieval: dense `nomic-embed-text` + sparse BM25, reciprocal rank fusion.
- Candidate expansion adds neighboring chunks before reranking.
- Reranking: `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU, batch=32, threads=4, ~1,000 ms).
- **Feedback-driven reranking**: admin votes (correct +1.5, incomplete +0.3, wrong −2.0)
  adjust rerank scores at query time via `apply_feedback_adjustments()`, capped at ±4.0.
- **Feedback exclusion**: chunks with `feedback_adjustment <= -4.0` (cap hit) are hard-excluded
  from context packing — ranking penalty alone is not enough when no better results exist.
- **Cache invalidation on wrong vote**: when a chunk receives a "wrong" vote, all cache
  entries that included that chunk are immediately evicted.
- Answer generation: `gemma2:2b` default (~2.1s), `gemma4:e4b` quality option (~7.8s).
- Tokens stream via Ollama streaming API; stages stream in real-time via asyncio.Queue.
- Two-tier response cache: exact hash (PostgreSQL) + semantic similarity (Qdrant 0.93).
- Full RAG trace persisted via `persist_stream_trace` after SSE generation.

### Chunking (table/form-aware)

- `normalize_table_markdown()` — compacts docling's wide pipe tables (hundreds of
  dashes per separator row → `---`), strips cell padding. Cuts chunk size ~50% and
  brings dollar amounts / key values earlier in the token window for the cross-encoder.
- `is_form_block()` — detects blocks where ≥60% of lines are `Key: value` pairs;
  tagged `element_type="form"`.
- `split_large_table()` — splits tables exceeding MAX_CHUNK_CHARS at row boundaries,
  repeating the header on each part.
- Section heading prepended to every table/form chunk so each chunk is self-contained
  for embedding (e.g., `"In-Network Coverage\n\n| Service | Copay |..."`).
- All table/form chunks tagged with `element_type` in `DocumentChunk.metadata_`.
- 12 unit tests covering all new chunking paths.

### Frontend

- Route groups: `(admin)/` (sidebar layout) and `(user)/` (clean layout).
- `/search` — user-facing benefits search portal, no admin chrome, no cache badge,
  suggested questions, SSE streaming answer, source list.
- `/chat` — admin console with full pipeline trace, feedback buttons, score badges
  (`feedback-boost` / `feedback-penalty`), feedback_adjustment shown per chunk.
  Model selector: `gemma2:2b` (default fast) or `gemma4:e4b` (quality).
- `/traces` — admin trace list with search input, evidence status and cache filter chips,
  click-through to trace detail. Replaces old `/traces/demo` sidebar link.
- `/traces/{trace_id}` — full trace detail including RAGAS eval panel (faithfulness,
  answer relevancy, context precision score bars). Shows run command if no scores yet.
- **Streaming render batching**: token updates batched via `requestAnimationFrame`
  in both `/search` and `/chat` — re-renders capped at ~60fps instead of per token.
- Admin feedback buttons only in `/chat`; `/search` has no feedback mechanism.
- Cache badge hidden in `/search` (users don't need to see cache status).
- "Clear cache" button in admin `/chat`.
- Citation click highlights matching evidence blocks.
- Latency summary card below answers.

### Ingestion / Documents

- PDF parsing via Docling (layout + table structure detection).
- Text file parsing fallback.
- Dense + sparse indexing pipeline with re-chunk UI in `/documents`.
- Ingestion quality metrics and warnings in the documents UI.
- Ingestion trace steps stored and displayed per document.
- MinIO for source/artifact storage.

### Evaluation / Golden Checks

Scripts:

```text
scripts/run_golden_queries.py
scripts/run_ragas_eval.py
scripts/compare_generation_models.py
```

Current golden cases (7/7 passing on all tested models):

- `enrollment`
- `mental_health_panic`
- `emergency_panic_attack`
- `specialist_visit_copay`
- `prescription_drugs`
- `preventive_care`
- `no_evidence` — correctly returns "Not enough evidence." after feedback exclusion fix

Run commands:

```bash
# Golden suite
.venv/bin/python scripts/run_golden_queries.py --generation-model gemma4:e4b
.venv/bin/python scripts/run_golden_queries.py --generation-model gemma4:e4b --timeout-seconds 300
.venv/bin/python scripts/run_golden_queries.py --generation-model gemma2:2b

# RAGAS offline evaluation (pull gemma3:4b first if not present)
.venv/bin/python scripts/run_ragas_eval.py                          # last 20 unevaluated traces
.venv/bin/python scripts/run_ragas_eval.py --trace-id <uuid>        # single trace
.venv/bin/python scripts/run_ragas_eval.py --model gemma3:4b --rerun  # re-score all
```

RAGAS findings summary:
- Context precision 0.000 on mental_health and emergency cases = cross-plan bleed from TX-NEXUS chunks
- Specialist copay faithfulness consistently lowest = same cross-plan root cause
- Both fixed by pending slice #1: document routing / plan filtering

## Completed Slices (full history)

1. Dense + sparse hybrid retrieval with RRF fusion.
2. Candidate expansion and MiniLM reranking.
3. Full RAG trace persistence and visual trace page.
4. Deterministic golden evaluation suite (7 cases).
5. Warmup-aware model latency comparison script.
6. `gemma2:2b` as initial default generation model.
7. Ingestion quality observability, document delete, re-chunk UI.
8. SSE streaming endpoint (`/api/chat/stream`) with real-time stages and token streaming.
9. Two-tier response cache: exact hash (PostgreSQL) + semantic (Qdrant 0.93 threshold).
10. Clear cache UI button and `DELETE /api/cache` endpoint.
11. `retrieval_mode` propagated through SSE path and stored in cache.
12. Semantic cache threshold 0.93 (false-positive analysis on insurance domain).
13. Reranker CPU tuning: batch=32, threads=4 → ~1,000 ms (was 1,400–2,200 ms).
14. **User-facing benefits search portal** at `/search` — route groups `(admin)` / `(user)`,
    clean layout, suggested questions, SSE streaming, no cache badge, no feedback buttons.
15. **Feedback-driven reranking** — admin votes adjust rerank scores at query time;
    `apply_feedback_adjustments()` in both SSE and non-SSE pipeline paths.
16. **Feedback exclusion from context** — chunks at the max negative cap (−4.0) are
    hard-excluded from context packing; prevents hallucination when all results are marked wrong.
17. **Cache invalidation on wrong vote** — `record_evidence_feedback` evicts cache entries
    that cited the chunk when label is "wrong".
18. **Table/form-aware chunking** — `normalize_table_markdown`, `is_form_block`,
    `split_large_table`, section context prefix, 12 unit tests.
19. **Streaming render batching** — RAF batching in `/search` and `/chat` token handlers.
20. **Admin trace list page** (`/traces`) — `GET /api/traces` endpoint with search/filter;
    frontend list with evidence status chips, cache chips, click-through to detail.
21. **RAGAS offline evaluation** — `rag_evaluations` table (migration 0009), `run_ragas_eval.py`
    script, `GET /api/traces/{id}/eval` endpoint, RAGAS score panel in trace detail UI.
22. **Multi-model benchmark and model consolidation** — tested 5 models (gemma2:2b,
    gemma3:4b, gemma4:e2b, gemma4:e4b, qwen2.5:1.5b-instruct) against golden suite and RAGAS;
    `gemma2:2b` kept as default (fast, ~2.1s); `gemma4:e4b` as quality option (faithfulness 0.90, context precision 0.90);
    all other models removed from Ollama and codebase.

## Pending Slices (priority order)

### 1. Document routing / plan filtering

**Confirmed root cause by RAGAS**: context precision 0.000 on mental_health and emergency
cases is caused by TX-NEXUS chunks being retrieved for NJ Transit queries. Multiple plan
documents bleed into each other's answers.

Fix: tag documents at upload with a plan/group identifier; query-time Qdrant filter
scopes retrieval to the correct plan.

### 2. Conversation support

Rules:
- Each turn re-retrieves independently — summaries must not replace source evidence.
- Store conversation ID; summaries reference only cited chunks.
- Answer generation still needs retrieved evidence, not only summary.

### 3. Admin trace list enhancements

Current list page is functional. Next:
- Pagination for large trace sets.
- Date range filter.
- Latency histogram / aggregate stats.

### 4. More document formats

After PDF/text path is stable:
- DOCX
- XLSX / CSV
- HTML
- PPTX
- Scanned PDFs with OCR fallback

### 5. FigJam architecture diagram update

Add to the colored diagram:
- User Portal (`/search`) and admin console (`/chat`) as separate entry points.
- Table/form-aware chunking layer in the ingestion path.
- Feedback loop: admin vote → score adjustment → context exclusion → cache eviction.
- RAGAS offline eval layer.

### 6. Authentication and tenant isolation

Defer until local v1 is stable:
- OIDC login
- Tenant memberships, roles, document ACLs
- Enforced Qdrant payload filters per tenant

## Validation Commands

Backend unit tests:

```bash
.runtime/venv/bin/ruff check backend
.runtime/venv/bin/pytest backend/tests/test_chunking.py backend/tests/test_query_analysis.py backend/tests/test_context_packing.py backend/tests/test_ingestion_quality.py backend/tests/test_config.py
```

Frontend:

```bash
cd frontend && npx next build
```

Live golden:

```bash
.runtime/venv/bin/python scripts/run_golden_queries.py --generation-model gemma2:2b
```

## Important Invariants (do not break)

- Cache key must include tenant_id + generation model + pipeline version.
  Do not extend to multi-tenant without expanding the key scope.
- `max_length=512` in MiniLM reranker — 256 broke the no_evidence golden case.
- `gemma4:e4b` LLM router disabled by default locally.
- Feedback exclusion threshold matches `FEEDBACK_ADJUSTMENT_CAP = 4.0`.
- `scripts/run_golden_queries.py` calls `/api/retrieval/search`, not the SSE endpoint.
- `gemma4:e4b` requires `--timeout-seconds 300` on first golden run (model warmup ~115s).
- Only two models are registered: `gemma2:2b` (default fast) and `gemma4:e4b` (quality). Do not add others without benchmarking.
- RAGAS `answer_relevancy` is unreliable with local models — treat as N/A; use `faithfulness` and `context_precision` only.
- Commit only after user confirms the slice looks good.
- No Co-Authored-By lines in git commits.
