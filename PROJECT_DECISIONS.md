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
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranking | Active |
| `gemma2:2b` | Default local answer generation | Active default for local v1 |
| `qwen3.5:9b` | Quality-check answer generation | Installed/available; selectable for answer A/B tests |

## Generation Model Decision

Default local answer generation is `gemma2:2b`.

Reason:

- Warmup-aware measured comparison showed both `gemma2:2b` and `qwen3.5:9b`
  passing the current 7 deterministic golden cases.
- `gemma2:2b` was materially faster on measured runs.
- Local v1 needs responsive iteration while keeping `qwen3.5:9b` available for
  quality checks.

Expected tradeoff:

- `gemma2:2b`: faster default, acceptable on current deterministic goldens.
- `qwen3.5:9b`: slower, often returns more complete citation coverage.

Do not treat this as a final production decision. Re-evaluate after more golden
questions, conversation support, and table/form-aware retrieval are added.

Observed first local A/B check for `how to enroll`:

| Model | Answer generation latency | Citation behavior | Initial finding |
|---|---:|---|---|
| `gemma2:2b` | about 7.5 seconds | returned `E1`, `E3`, `E4` | faster, but skipped one useful eligibility citation |
| `qwen3.5:9b` | about 33.1 seconds in this run | returned `E1`, `E2`, `E3`, `E4` | slower, more complete evidence coverage |

This first check was not enough for a permanent model decision because model
swapping and Ollama load state can distort latency. It led to the
warmup-aware comparison script below.

Warmup-aware measured comparison on the 7-case golden set:

| Model | Pass rate | Avg elapsed | P95 elapsed | Avg answer generation | P95 answer generation | Decision |
|---|---:|---:|---:|---:|---:|---|
| `gemma2:2b` | 7/7 | 2102 ms | 2767 ms | 1117 ms | 1766 ms | Local default |
| `qwen3.5:9b` | 7/7 | 8110 ms | 14912 ms | 6565 ms | 11470 ms | Quality-check option |

Quality caveat from the same measured report:

- Qwen returned more citations for some cases, for example enrollment and
  emergency panic attack.
- Gemma still passed the current deterministic evidence/answer checks.
- Decision: use Gemma as default for local responsiveness, keep Qwen selectable
  and continue comparing as the golden set grows.

## Router Decision

Initial plan considered running `gemma2:2b` on every query as an intent router.
Live testing showed this added about 1.5 seconds when the router timed out:

```text
intent routing: fallback, about 1528 ms
```

That is not a good local tradeoff because current retrieval still uses the same
hybrid path after routing.

Current decision:

- LLM-based routing is not mandatory for RAG.
- Default local retrieval path is deterministic hybrid retrieval.
- Keep an `intent routing` trace stage for visibility and future expansion.
- Disable the LLM router by default:

```text
router_enabled=false
```

Expected local trace:

```text
intent routing: skipped
duration_ms: 0
source: deterministic
selected_retrieval_path: hybrid
reason: router disabled for local latency
```

Future use of `gemma2:2b` should be gated by evidence that it materially changes
the retrieval path or improves quality without unacceptable latency.

## Retrieval Pipeline Decision

Current request-time pipeline:

```text
query analysis
security context, fixed local principal in local v1
response cache, scoped but disabled until safety validation
intent routing, skipped locally by default
dense retrieval
sparse/BM25 retrieval
rank fusion
candidate expansion
rerank
context packing
answer generation
evidence preview
trace persistence
```

Dense retrieval handles semantic matches. Sparse/BM25 retrieval handles exact
terms, IDs, dates, codes, and table-like values. Both are needed.

## Security Context Decision

Local v1 uses a fixed server-side principal. Clients do not submit authoritative
tenant, user, role, or ACL identifiers.

Current local trace stage:

```text
security context
tenant_id: local-development
user_id: local-user
principal_id: local-development-principal
acl_mode: local_placeholder
acl_filter_applied: false
auth_source: server_fixed_local_v1
```

This is not production authorization. It is a visible placeholder so the query
pipeline has the correct stage shape before real OIDC, tenant memberships,
roles, and ACL filters are added.

## Response Cache Decision

A two-tier response cache is active.

**Tier 1 — Exact hash cache (PostgreSQL `response_cache`)**

Cache key: SHA-256(normalized query + tenant_id + generation model + pipeline version).

- No embedding needed on a hit.
- `created_at` and `hit_count` tracked per entry.
- Context snapshot stored alongside answer and citation_ids.

Alembic migration: `0008_response_cache.py`.

**Tier 2 — Semantic cache (Qdrant `pdfrag_response_cache_v1`)**

On exact miss, embed the query with `nomic-embed-text` (768-dim) and search
Qdrant with cosine similarity threshold **0.93**.

Threshold history and rationale:
- Started at 0.93 — too strict, genuine paraphrases never reached it.
- Lowered to 0.75 — caused false positives: "chest pain" vs "head pain" scored
  0.84, "specialist copay" vs "emergency copay" scored 0.86, "outpatient surgery"
  vs "inpatient surgery" scored 0.93. All different questions with different answers.
- Raised back to 0.93 — only near-identical rephrasing hits. Insurance domain
  queries share sentence structure, making the gap between paraphrase and
  different-question scores too small for a lower threshold to be safe.

- Qdrant point IDs are deterministic UUIDs: `uuid.uuid5(NAMESPACE_DNS, cache_key)`.
- Payload stores `cache_key`, `tenant_id`, and original `query`.
- On a semantic hit, the full answer is fetched from PostgreSQL using the returned key.
- The query embedding is reused when writing the new cache entry to avoid
  a second embed call.

Cache management:

```text
GET  /api/cache  → {entries, total_hits, semantic_entries}
DELETE /api/cache → {deleted, semantic_deleted}
```

CORS must include DELETE for the browser clear-cache button to work.

On cache hit, the SSE endpoint emits three stage events (query analysis, security
context, response cache) and then a `done` event with `from_cache: true`. No
pipeline trace is saved on a cache hit.

Do not serve cached answers across different tenants or pipeline versions.
Extend cache key scope before enabling multi-tenant use.

## Query Expansion Decision

Deterministic query analysis is currently the main routing/query expansion
mechanism. It handles known topic expansion such as:

- enrollment
- mental health
- emergency care

The topic expansion array can grow over time, but it should not become an
uncontrolled synonym dump. Add terms only when they are:

- observed in user questions,
- observed in source documents,
- useful for recall,
- and validated by examples or evaluation cases.

## Anxiety / Panic Attack Finding

Question tested:

```text
I feel anxious and feel like having panic attacks, what kind of coverage do I have?
```

Finding:

- The query should expand toward mental health and behavioral health.
- It may also include emergency care terms because "panic attack" can imply an
  urgent/emergency concern.
- The answer should be conservative when documents mention mental health
  coverage generally but do not explicitly say anxiety/panic attacks are covered.

Expected behavior:

- Retrieve mental health / behavioral health evidence.
- Cite only actual evidence.
- Say "not enough evidence" when exact coverage cannot be proven.

## Candidate Expansion Decision

After rank fusion, the pipeline expands around top candidates with neighboring
chunks before reranking.

Reason:

- Sometimes the top retrieved chunk is not the full answer.
- Neighboring chunks often contain section continuation, eligibility context,
  table headers, or related enrollment details.

Observed example:

- Query: `how to enroll`
- Candidate expansion added 11 neighboring chunks.
- Reranker then selected richer enrollment evidence.

Current expansion:

- window: 1 neighboring chunk before/after
- seed candidates: first 6 fused candidates

Future expansion candidates:

- same section expansion
- table header expansion
- footnotes
- form labels

## Human-in-the-Loop Decision

Human feedback is required because reranker score alone may not match human
judgment. Example discussed:

- Top result may have the highest score.
- Second result may actually be the better answer.

Current feedback labels:

- correct evidence
- relevant but incomplete
- wrong / not useful

Feedback is stored for later evaluation and tuning. It is not yet used
automatically to retrain or alter ranking.

## Trace Decision

Trace visibility is a core requirement, not an optional debugging feature.

Current trace support:

- every retrieval response includes `trace_id`
- full trace is persisted in PostgreSQL
- `GET /api/traces/{trace_id}` returns stored trace JSON
- `/traces/{trace_id}` renders a visual trace page

The trace page shows:

- original question
- generated answer
- evidence status
- latency summary
- cache event
- pipeline stages
- stage details
- selected prompt chunks
- packed prompt context

## API Decision

The plan originally called for `POST /api/chat`. The project first implemented
`POST /api/retrieval/search`.

Current decision:

- `/api/chat` has been removed. It was a blocking JSON endpoint.
- `/api/chat/stream` is the primary chat endpoint — SSE `text/event-stream`.
- `/api/retrieval/search` remains for the retrieval workbench and golden scripts.
- `/api/cache` (GET / DELETE) manages the two-tier response cache.

SSE event types:

```text
stage   — one per pipeline stage as it completes (real-time)
context — packed context blocks before generation
token   — one per generated answer token
done    — final: answer, citation_ids, trace_id, retrieval_mode, from_cache, cached_at
```

Implementation notes:

- Real-time stages use `asyncio.Queue` + `asyncio.create_task`; pipeline runs in
  background and puts stages on the queue as they complete.
- `on_stage: Callable[[RetrievalStage], Awaitable[None]]` is the callback contract.
- `scripts/run_golden_queries.py` calls `/api/retrieval/search` (synchronous,
  not SSE) — do not change this.
- `retrieval_mode` from the router decision propagates through the SSE path and
  is stored in the cache entry.

## SSE Streaming Decision

The blocking `POST /api/chat` endpoint was replaced with a streaming SSE endpoint
`POST /api/chat/stream` (`text/event-stream`).

Reason:

- Even at 2–8 seconds total, streaming makes the response feel instant because
  the user sees stages and tokens as they arrive.
- Blocking JSON response required waiting for full pipeline completion before
  anything was rendered.

Real-time stage implementation:

- `on_stage` callback added to `run_pipeline_to_context` with signature
  `Callable[[RetrievalStage], Awaitable[None]] | None`.
- `asyncio.Queue[RetrievalStage | None]` bridges the pipeline coroutine and the
  SSE generator.
- `asyncio.create_task` runs the pipeline concurrently; the SSE generator drains
  the queue until the `None` sentinel arrives.
- This avoids buffering: stages appear in the UI the moment each step finishes.

Known constraint:

- `asyncio.Queue` requires the SSE generator and pipeline to run on the same
  event loop. This works with FastAPI's default single-process dev server and
  Uvicorn's default asyncio loop. Review if switching to a multi-process worker.

## Ingestion Quality Metrics Decision

Ingestion quality metrics are observability only. They may be displayed in the
document UI and stored in ingestion trace details, but they must not change
request-time answer quality paths by themselves.

Safe scope:

- parser used
- page count
- character count and characters per page
- empty page count when available
- chunk count and chunk-size summary
- table-like content count
- OCR used/needed indicators
- human-readable warnings

Do not make this slice alter parsing, chunking, indexing, retrieval, reranking,
context packing, prompts, or generation defaults. Table/form-aware retrieval is
a separate later quality-improvement slice.

## RAGAS Decision

RAGAS is not required in the request-time flow.

Current decision:

- Use deterministic evaluation metrics first.
- Add RAGAS only as an optional offline evaluation adapter near the end.
- Store evaluator model, prompt, metric version, raw rationale, and scores.
- Treat LLM-judged scores as directional, not ground truth.

## Current Validation Commands

Backend:

```bash
.runtime/venv/bin/ruff check backend
.runtime/venv/bin/pytest
```

Frontend:

```bash
npm run lint
npm run build
```

Live golden checks:

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

The golden and model-comparison scripts require the local backend, indexed
documents, Qdrant, Ollama, and supporting services to be running.

Current golden cases:

- `enrollment`
- `mental_health_panic`
- `emergency_panic_attack`
- `specialist_visit_copay`
- `prescription_drugs`
- `preventive_care`
- `no_evidence`

Observed first run:

- `gemma2:2b`: 7/7 golden checks passed.
- `qwen3.5:9b`: 7/7 golden checks passed.

Warmup-aware model comparison:

- Implemented in `scripts/compare_generation_models.py`.
- Warmup pass(es) are tracked separately from measured pass(es).
- Small validation with `gemma2:2b` on `specialist_visit_copay` showed:
  - warmup elapsed: 9612 ms
  - measured elapsed: 2458 ms
  - measured answer generation: 374 ms
- Decision: do not compare generation models using first-run latency alone.

## Reranker Performance Decision

MiniLM-L6 cross-encoder runs on CPU. Default PyTorch settings caused it to be
the pipeline bottleneck at 1,400–2,200 ms per query.

Root causes found and fixed:

| Parameter | Before | After | Reason |
|---|---|---|---|
| `RERANK_BATCH_SIZE` | 8 | 32 | Eliminates 2–3 forward passes; all 14–18 candidates in one pass |
| `torch.set_num_threads` | 24 (default) | 4 | 24 threads caused scheduling contention for this small model — biggest win |
| `max_length` | 512 | **kept at 512** | Tested 256 — broke `no_evidence` golden case (reranker needs full context to correctly score irrelevant chunks as very negative) |

Result: reranking **1,400–2,200 ms → ~1,000 ms**. Golden suite 7/7 passes.

`max_length=256` finding: all chunks average 387 tokens (1,549 chars). Some chunks
are massive (48K chars, ~12K tokens — pipe-formatted tables / TOC). Truncation at
256 caused the "lunar habitat repairs" no-evidence query to rank a "reimbursement"
chunk too high, leading the LLM to hallucinate a tangential answer. 512 keeps the
negative rerank scores deep enough that the LLM correctly refuses.

## Completed Slices (summary)

1. Dense + sparse hybrid retrieval with RRF fusion.
2. Candidate expansion and MiniLM reranking.
3. Full RAG trace persistence and visual trace page.
4. Deterministic golden evaluation suite (7 cases).
5. Warmup-aware model latency comparison script.
6. `gemma2:2b` as default generation model.
7. Ingestion quality metrics UI (observability only).
8. SSE streaming endpoint (`/api/chat/stream`) with real-time stages and token streaming.
9. Two-tier response cache: exact hash (PostgreSQL) + semantic (Qdrant 0.93 threshold).
10. Clear cache UI button and `DELETE /api/cache` endpoint.
11. `retrieval_mode` propagated through SSE path and stored in cache.
12. Semantic cache threshold set to 0.93 after false positive analysis (chest pain vs head pain, specialist vs emergency copay).
13. Reranker CPU tuning: batch=32, threads=4 → rerank 1,400–2,200 ms → ~1,000 ms.

## Pending Slices in Recommended Order

1. Add table/form-aware chunking and retrieval.
2. Add conversation support with provenance-safe summaries.
3. Add DOCX/PPTX/XLSX/CSV/HTML support.
4. Add admin trace list/search page.
5. Feedback-driven reranking (votes stored but not yet used).
6. Document routing / filtering (UHC vs NJ Transit plan bleed).
7. Add authentication and tenant isolation after local v1 is stable.
8. Add optional offline RAGAS adapter.

## Open Questions

- What threshold should decide whether a query is ambiguous enough to use the
  optional LLM router in the future?
- Should human feedback affect reranking manually through evaluation reports
  first, or automatically through ranking rules?
- Which remaining golden questions should be added after retrieval/generation
  stabilizes?
- Which document types should be prioritized after PDF/text/Markdown:
  DOCX, XLSX, CSV, HTML, or scanned PDFs?
