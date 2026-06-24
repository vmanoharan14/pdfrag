# PDFRAG Restart Plan

Last updated: 2026-06-24

Use this file to resume work after a break without relying on chat memory.

## Current Working Rule

- Implement one small, testable slice at a time.
- Stop when the user can validate something visible or measurable.
- Commit only after the user confirms the slice looks good.
- Keep questioning weak assumptions instead of blindly implementing requests.
- Keep `PROJECT_DECISIONS.md` updated when we make meaningful design decisions.

## Current Git State at Time of Writing

Latest committed slice:

```text
Exact response cache (PostgreSQL hash-scoped, alembic migration 0008)
```

Current uncommitted slice:

```text
Semantic cache threshold set to 0.93 (safe for insurance domain) + reranker CPU tuning (batch=32, threads=4)
```

Files that belong to the current uncommitted slice:

```text
NEXT_STEPS.md
PROJECT_DECISIONS.md
plan.md
backend/app/cache.py
backend/app/chat.py
backend/app/main.py
backend/app/reranking.py
frontend/app/chat/page.tsx
```

## Completed Slice: Response Cache Foundation (superseded)

The initial cache-foundation slice added key-scoping and trace visibility only.
That was a stepping stone; the actual cache implementation followed.

## Completed Slice: SSE Streaming + Real-time Stages

Purpose:

- Replace the blocking `/api/chat` request with a streaming SSE endpoint.
- Show each pipeline stage as it completes rather than buffering all stages.

Endpoint: `POST /api/chat/stream` (`text/event-stream`)

SSE event sequence:

```text
stage   — emitted as each pipeline stage finishes (real-time)
context — packed context blocks, before generation starts
token   — one per generated answer token
done    — final answer, citations, trace_id, retrieval_mode, from_cache
```

Real-time stage mechanism:

- `on_stage: Callable[[RetrievalStage], Awaitable[None]]` callback added to
  `run_pipeline_to_context`.
- `asyncio.Queue[RetrievalStage | None]` bridges pipeline and SSE generator.
- `asyncio.create_task` runs the pipeline; sentinel `None` signals completion.
- Stage events appear in the UI as each step completes, not after the full run.

`/api/chat` was removed. The chat UI uses `/api/chat/stream` exclusively.
`/api/retrieval/search` remains for the retrieval workbench and golden scripts.

`persist_stream_trace` added so "Open stored trace" works for SSE queries.

Validation:

```text
golden: 7/7 passed
TypeScript: clean build
```

## Completed Slice: Two-tier Response Cache

Purpose:

- Avoid redundant full-pipeline runs for repeated or semantically equivalent
  questions.

Tier 1 — Exact cache (PostgreSQL `response_cache` table, alembic migration 0008):

- Cache key: SHA-256(normalized query + tenant + generation model + pipeline version).
- Instant lookup with no embedding cost on hit.

Tier 2 — Semantic cache (Qdrant `pdfrag_response_cache_v1`):

- On exact miss, embed the query with `nomic-embed-text` (768-dim, Cosine).
- Qdrant similarity search at threshold **0.93**.
- Returns PostgreSQL `cache_key` from Qdrant payload → fetch full answer from PG.
- Query embedding is reused when writing the new Qdrant point (no double-embed).

Collection created at startup via `ensure_semantic_cache_collection` in lifespan.

Cache management endpoints (`/api/cache`):

```text
GET  /api/cache  → {entries, total_hits, semantic_entries}
DELETE /api/cache → {deleted, semantic_deleted}
```

Chat UI shows amber "Cached" badge + "Served from cache" heading on hits.
"Clear cache" button in the form row calls `DELETE /api/cache`.

Validation:

```text
golden: 7/7 passed
TypeScript: clean build
```

## Completed Slice: Reranker CPU Tuning

Root causes of reranking being the bottleneck (1,400–2,200 ms per query):

1. `RERANK_BATCH_SIZE = 8` forced 2–3 forward passes for 14–18 candidates.
2. `torch.set_num_threads` defaulted to 24 (all CPU cores) — scheduling overhead
   for a small model (MiniLM-L6) is worse than using 4 threads.

Fix applied in `backend/app/reranking.py`:

```python
RERANK_BATCH_SIZE = 32   # all candidates in one pass
RERANK_NUM_THREADS = 4   # set via torch.set_num_threads() in score_pairs_sync
max_length = 512          # kept at 512 — 256 broke no_evidence golden case
```

`max_length=256` was tested and reverted. Insurance chunks average 387 tokens;
at 256 tokens the reranker can't see enough of irrelevant chunks to score them
sufficiently negative, causing the LLM to hallucinate answers for no-evidence queries.

Result: reranking **1,400–2,200 ms → ~1,000 ms**. Golden suite 7/7.

## Completed Slice: Semantic Cache Threshold Calibration

Threshold tested at 0.75 — caused false positives in the insurance domain:
- "chest pain" vs "head pain" → 0.84 (wrong cached answer served)
- "specialist copay" vs "emergency copay" → 0.86 (different benefit, wrong answer)
- "outpatient surgery" vs "inpatient surgery" → 0.93 (completely different benefits)

`nomic-embed-text` treats structurally similar insurance queries as very similar
regardless of the key distinguishing word. There is no threshold between 0.75–0.92
that catches genuine paraphrases without false positives in this domain.

Final threshold: **0.93** in `backend/app/cache.py`.

At 0.93, only near-identical rephrasing hits (e.g., same question with minor
wording change). Broader paraphrases run the full pipeline — which is correct
and safe for insurance benefit questions.

## Current Capabilities Already Built

### Backend / Retrieval

- `/api/chat/stream` is the primary chat endpoint (SSE, `text/event-stream`).
- `/api/chat` has been removed.
- `/api/retrieval/search` remains for the retrieval workbench and golden scripts.
- `/api/cache` (GET / DELETE) manages the two-tier response cache.
- Query analysis expands known topics:
  - enrollment
  - mental health
  - emergency care
- LLM router stage exists but is disabled by default locally.
- Hybrid retrieval:
  - dense embeddings with `nomic-embed-text`
  - sparse/BM25 retrieval
  - reciprocal rank fusion
- Candidate expansion adds neighboring chunks before reranking.
- Reranking uses `cross-encoder/ms-marco-MiniLM-L-6-v2` (CPU, batch=32, threads=4, ~1,000 ms for 14–18 candidates).
- Answer generation can use per-query model selection:
  - default `gemma2:2b` for local responsiveness
  - optional `qwen3.5:9b` for quality checks
- Tokens stream via Ollama streaming API; stages stream in real-time via asyncio.Queue.
- Two-tier response cache: exact hash (PostgreSQL) + semantic similarity (Qdrant 0.93).
- `retrieval_mode` from router decision is propagated through SSE path and stored in cache.
- Full RAG trace is persisted via `persist_stream_trace` after SSE generation completes.
- `GET /api/traces/{trace_id}` returns stored trace JSON.

### Frontend

- `/chat` calls `/api/chat/stream` (SSE endpoint).
- Stages appear in real-time as each pipeline step completes.
- Answer tokens stream character-by-character with a blinking cursor.
- Chat has answer model selector:
  - Gemma default fast local mode
  - Qwen quality-check mode
- "Clear cache" button in the form row calls `DELETE /api/cache`.
- Cache hit UI: amber "Cached" badge, "Served from cache" heading, trace link hidden.
- Chat shows pipeline trace stages (live during streaming, final on completion).
- Chat links to stored trace (for non-cached answers).
- Citations are clickable.
- Citation click highlights matching evidence blocks.
- `/traces/{trace_id}` renders persisted traces.

### Ingestion / Documents

- Existing ingestion UI and ingestion trace are present.
- PDF parsing/chunking/indexing path exists.
- Dense/sparse indexing exists.
- MinIO is used locally for source/artifacts.

### Evaluation / Golden Checks

Scripts:

```text
scripts/run_golden_queries.py
scripts/compare_generation_models.py
```

Examples:

```bash
.runtime/venv/bin/python scripts/run_golden_queries.py --generation-model gemma2:2b
.runtime/venv/bin/python scripts/run_golden_queries.py --generation-model qwen3.5:9b --case enrollment
.runtime/venv/bin/python scripts/run_golden_queries.py \
  --generation-model gemma2:2b \
  --json-output .runtime/evals/golden-gemma.json
.runtime/venv/bin/python scripts/compare_generation_models.py \
  --models qwen3.5:9b,gemma2:2b \
  --json-output .runtime/evals/model-comparison.json
```

Current golden cases:

- `enrollment`
- `mental_health_panic`
- `emergency_panic_attack`
- `specialist_visit_copay`
- `prescription_drugs`
- `preventive_care`
- `no_evidence`

## Important Decisions So Far

See `PROJECT_DECISIONS.md` for full detail. Key points:

- Intent routing is not mandatory for RAG.
- `gemma2:2b` router is disabled by default locally because it added latency
  without changing the path.
- Deterministic hybrid retrieval is the default.
- `gemma2:2b` is the local default generation model after measured comparison.
- `qwen3.5:9b` remains available as a quality-check A/B model.
- RAGAS is optional offline evaluation only, not request-time.
- Two-tier response cache is active: exact hash (PostgreSQL) + semantic (Qdrant 0.93).
- SSE streaming replaces the blocking `/api/chat` endpoint.
- Reranker tuned: batch=32, threads=4 → ~1,000 ms (was 1,400–2,200 ms). max_length stays at 512.
- Local v1 uses fixed server-side principal, not client-supplied auth.

## Recommended Next Slices

### Recently completed: Answer latency summary in Chat UI

Purpose:

- Make latency visible without opening every trace stage.
- Show whether answer generation, reranking, or retrieval is the bottleneck.

Expected UI after asking a question:

```text
Latency
Total
Retrieval
Rerank
Context
Generation
Model
Bottleneck
```

Validation:

1. Open `/chat`.
2. Ask `how to enroll`.
3. Expected: a latency summary card appears below the answer.
4. Expected: generation is usually the bottleneck.
5. Expected: selected answer model is visible in the latency card.

Committed as:

```text
feat: show chat latency summary
```

### Recently completed: Expanded deterministic golden questions

Current golden cases:

- `enrollment`
- `mental_health_panic`
- `emergency_panic_attack`
- `specialist_visit_copay`
- `prescription_drugs`
- `preventive_care`
- `no_evidence`

Why these were added:

- They cover enrollment, mental health, emergency care, specialist copay,
  prescription drugs, preventive care, and no-evidence behavior.
- They are deterministic string/evidence checks, not LLM-judge checks.
- Broad “doctor visit cost” was intentionally not added yet because the current
  indexed evidence returned `Not enough evidence`; this needs either better
  query expansion or a more specific golden case.

### Recently completed: Warmup-aware model latency comparison

Reason:

- Ollama model switching can make first-run timing misleading.
- Need separate warm and cold measurements.

Script:

```text
scripts/compare_generation_models.py
```

What it does:

- Runs warmup pass(es) separately from measured pass(es).
- Reuses the deterministic golden cases.
- Reports measured pass count, average elapsed latency, p95 elapsed latency,
  average answer-generation latency, and p95 answer-generation latency.
- Can write a structured JSON report.

Models:

```text
qwen3.5:9b
gemma2:2b
```

Optional command to inspect loaded Ollama models:

```bash
curl -sS http://127.0.0.1:11434/api/ps
```

Small validation run:

```bash
.runtime/venv/bin/python scripts/compare_generation_models.py \
  --models gemma2:2b \
  --case specialist_visit_copay \
  --warmup-runs 1 \
  --measured-runs 1
```

Observed result:

```text
warmup elapsed: 9612 ms
measured elapsed: 2458 ms
measured answer generation: 374 ms
```

This confirms that first-run latency can be misleading and should not be used
alone when comparing generation models.

### Recently completed: Generation default optimization decision

Decision:

- Use `gemma2:2b` as the local default answer model.
- Keep `qwen3.5:9b` selectable as quality-check mode.
- Do not reduce `generation_num_predict` or `context_max_chunks` yet; changing
  the default model gives a large latency win without weakening retrieval input.

Measured result from `scripts/compare_generation_models.py`:

```text
qwen3.5:9b | 7/7 | avg elapsed 8110 ms | avg generation 6565 ms
gemma2:2b  | 7/7 | avg elapsed 2102 ms | avg generation 1117 ms
```

Quality caveat:

- Qwen returned more citations in some measured cases.
- Gemma still passed all current deterministic golden checks.
- Revisit this after the golden set expands and table/form-aware retrieval is
  added.

### Current slice: Semantic response cache (uncommitted, pending user test)

Purpose:

- Serve semantically equivalent queries from cache without a full pipeline run.
- Use `nomic-embed-text` embeddings and Qdrant cosine similarity at 0.93.

Test it by:

1. Ask any question. Wait for the full pipeline answer.
2. Ask a rephrased version of the same question (different wording, same intent).
3. Expected: second query shows amber "Cached" badge and "Served from cache".
4. Expected: `DELETE /api/cache` button clears both PostgreSQL and Qdrant entries.

### 1. Add table/form-aware retrieval

This is the next quality-critical slice after the cache is committed.

- table headers
- row groups
- form key-value pairs
- table summaries
- row-level expansion

### 2. Add ingestion quality metrics (observability only)

Purpose:

- Surface document-level parsing warnings before trusting retrieval.
- Do not change parsing, chunking, indexing, retrieval, or generation paths.

Behavior to validate in `/documents`:

```text
Quality: chars, chars/page, avg chunk, max chunk, tables, empty pages
OCR may be needed (when detected)
Warnings (when detected)
```

### 3. Add conversation support with provenance-safe summaries

Rules:

- Conversation summary must not replace source evidence.
- Summary can help with user context, but answer still needs retrieved evidence.
- Store conversation id and summary provenance.

### 4. More document formats

After PDF/text/Markdown path is stable:

- DOCX
- XLSX
- CSV
- HTML
- PPTX
- scanned PDFs/OCR

### 5. Admin trace list/search page

Add:

- recent traces
- filter by model
- filter by status
- filter by latency
- filter by question text
- open trace detail

### 6. Authentication and tenant isolation

Defer until local v1 is stable.

### 7. Optional offline RAGAS adapter

Good to have near the end, not required for the product path.

Rules:

- Not request-time.
- Store evaluator model, prompt, metric version, raw rationale.
- Treat LLM-evaluated scores as directional, not ground truth.

Future work:

- OIDC
- tenant memberships
- role assignments
- document ACLs
- trace authorization
- enforced Qdrant filters

## Validation Commands to Reuse

Backend:

```bash
.runtime/venv/bin/ruff check backend scripts/run_golden_queries.py
.runtime/venv/bin/pytest
```

Frontend:

```bash
npm run lint
npm run build
```

Live golden:

```bash
.runtime/venv/bin/python scripts/run_golden_queries.py --generation-model gemma2:2b
```

Single case:

```bash
.runtime/venv/bin/python scripts/run_golden_queries.py \
  --generation-model gemma2:2b \
  --case enrollment
```

Report:

```bash
.runtime/venv/bin/python scripts/run_golden_queries.py \
  --generation-model gemma2:2b \
  --json-output .runtime/evals/golden-gemma.json
```

Inspect report:

```bash
.runtime/venv/bin/python -m json.tool .runtime/evals/golden-gemma.json
```

Ollama loaded models:

```bash
curl -sS http://127.0.0.1:11434/api/ps
```

## Known Latency Finding

Current local query latency can be 6–12 seconds, sometimes more.

Main contributor:

- answer generation

Observed examples:

- `gemma2:2b` can be faster, but may miss useful citations.
- `qwen3.5:9b` can be slower, but usually gives better evidence coverage.
- First query after switching models may include Ollama model load/warmup time.

Do not judge model speed from a single switched-model run.

## Do Not Forget

- If the user says a slice looks good, commit before starting the next slice.
- If a slice affects the plan, update `PROJECT_DECISIONS.md` or this file.
- Response cache IS active. Do not extend to multi-tenant without expanding the cache key scope.
- Keep `gemma2:2b` routing disabled by default locally.
- Do not add RAGAS into request-time path.
- Cache hit answers do not produce a trace; hide the trace link on cache hits.
- `scripts/run_golden_queries.py` targets `/api/retrieval/search`, not the SSE endpoint. Keep it that way.
