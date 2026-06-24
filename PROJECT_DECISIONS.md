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

Response caching is not enabled yet. The pipeline currently computes and traces
a safe cache scope/key preview only.

Current local trace stage:

```text
response cache
cache_enabled: false
cache_event: miss
tenant_id: local-development
principal_id: local-development-principal
acl_context: local-placeholder
query_hash: sha256(normalized query)
pipeline_version: local-text-rag-v1
dense_embedding_model
sparse_encoder_model
reranker_model
generation_model
context budget
cache_key_preview: first 24 chars of scoped key hash
```

Do not enable cache reads/writes until cache keys include every value that can
change the answer, especially tenant/principal/ACL context, document-version
scope, model identifiers, prompt/pipeline versions, and context budget.

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

The plan calls for:

```text
POST /api/chat
```

The project originally implemented:

```text
POST /api/retrieval/search
```

Current decision:

- Keep `/api/retrieval/search` for the retrieval workbench.
- Add `/api/chat` as the plan-aligned API endpoint.
- `/api/chat` should delegate to the same pipeline to avoid duplicate logic.

Implementation status:

- `/api/chat` is implemented.
- The chat UI calls `/api/chat`.
- `/api/retrieval/search` remains available.

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

## Pending Slices in Recommended Order

1. Improve ingestion quality metrics: parser coverage, table/form/OCR
    indicators.
2. Add table/form-aware chunking and retrieval.
3. Add conversation support with provenance-safe summaries.
4. Add SSE streaming for answer text and live trace events.
5. Add DOCX/PPTX/XLSX/CSV/HTML support.
6. Add admin trace list/search page.
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
