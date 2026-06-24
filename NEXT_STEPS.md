# PDFRAG Restart Plan

Last updated: 2026-06-23

Use this file to resume work after a break without relying on chat memory.

## Current Working Rule

- Implement one small, testable slice at a time.
- Stop when the user can validate something visible or measurable.
- Commit only after the user confirms the slice looks good.
- Keep questioning weak assumptions instead of blindly implementing requests.
- Keep `PROJECT_DECISIONS.md` updated when we make meaningful design decisions.

## Current Git State at Time of Writing

Latest completed slice to commit now:

```text
Response-cache foundation trace stage
```

Current uncommitted slice:

```text
None after committing the response-cache foundation trace stage.
```

Files that belong to the response-cache foundation commit:

```text
NEXT_STEPS.md
PROJECT_DECISIONS.md
backend/app/retrieval.py
backend/tests/test_retrieval.py
scripts/run_golden_queries.py
```

After this commit, start with the warmup-aware model latency comparison slice.

## Completed Slice: Response Cache Foundation

Purpose:

- Add cache visibility without serving cached answers yet.
- Validate safe cache scoping before enabling cache reads/writes.

Behavior added:

```text
03 response cache
status: skipped
cache_enabled: false
cache_event: miss
reason: cache read/write disabled during local validation
cache_key_preview: short scoped hash
```

The cache scope includes:

- tenant id
- principal id
- ACL context
- query hash
- pipeline version
- dense embedding model
- sparse encoder model
- reranker model
- generation model
- context budget

Important decision:

- Cache read/write is intentionally disabled.
- This is only a trace/key-safety foundation.
- Do not enable response caching until document-version scope and prompt/pipeline
  versioning are fully included.

Validation already run:

```bash
.runtime/venv/bin/ruff check backend scripts/run_golden_queries.py
.runtime/venv/bin/pytest
npm run build
```

Observed:

```text
pytest: 38 passed
response cache stage appears as sequence 03
golden enrollment smoke passed
```

User validation completed:

- `/chat` trace stage `03 response cache` was checked and approved.

Expected trace order remains:

```text
how to enroll
```

```text
01 query analysis
02 security context
03 response cache
04 intent routing
05 dense retrieval
06 sparse retrieval
07 rank fusion
08 candidate expansion
09 rerank
10 context packing
11 answer generation
12 evidence preview
```

Expected `response cache` details:

```text
status: skipped
cache_event: miss
cache_enabled: false
cache_key_preview: present
```

Commit command used for this slice:

```bash
git add NEXT_STEPS.md PROJECT_DECISIONS.md backend/app/retrieval.py backend/tests/test_retrieval.py scripts/run_golden_queries.py
git commit -m "feat: trace response cache scope"
```

## Current Capabilities Already Built

### Backend / Retrieval

- `/api/chat` endpoint exists and delegates to the RAG pipeline.
- `/api/retrieval/search` still exists for the retrieval workbench.
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
- Reranking uses `cross-encoder/ms-marco-MiniLM-L-6-v2`.
- Answer generation can use per-query model selection:
  - default `qwen3.5:9b`
  - optional `gemma2:2b`
- Full RAG trace is persisted.
- `GET /api/traces/{trace_id}` returns stored trace JSON.

### Frontend

- `/chat` calls `/api/chat`.
- Chat has answer model selector:
  - Qwen default quality mode
  - Gemma fast local test mode
- Chat shows pipeline trace.
- Chat links to stored trace.
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
- `qwen3.5:9b` remains default generation model for quality.
- `gemma2:2b` is available as fast local A/B test model.
- RAGAS is optional offline evaluation only, not request-time.
- Cache must be scoped safely before being enabled.
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

### 1. Decide whether to optimize generation

Possible options:

- lower `generation_num_predict`
- reduce `context_max_chunks` for simple questions
- add model-specific defaults:
  - Qwen quality mode
  - Gemma fast mode
- add streaming before further model tuning

Do not blindly switch default to Gemma until golden results compare quality.

### 2. Add optional offline RAGAS adapter

Only after deterministic golden checks are useful.

Rules:

- Not request-time.
- Store evaluator model, prompt, metric version, raw rationale.
- Treat LLM-evaluated scores as directional, not ground truth.

### 3. Add SSE streaming for answer and live trace

Reason:

- Even if full answer takes 6–12 sec, streaming improves perceived latency.

Expected behavior:

- User sees answer tokens as they arrive.
- Trace stages update live.

This is bigger than prior slices; split carefully:

1. Backend streaming endpoint.
2. Frontend streaming render.
3. Live trace event render.

### 4. Conversation support with provenance-safe summaries

Rules:

- Conversation summary must not replace source evidence.
- Summary can help with user context, but answer still needs retrieved evidence.
- Store conversation id and summary provenance.

### 5. Ingestion quality metrics

Add parser/chunking quality signals:

- parser used
- page count
- chunk count
- empty page count
- table detected count
- OCR needed/used later
- warnings

Show these in document/ingestion UI.

### 6. Table/form-aware retrieval

Later after text RAG stabilizes:

- table headers
- row groups
- form key-value pairs
- table summaries
- row-level expansion

### 7. More document formats

After PDF/text/Markdown path is stable:

- DOCX
- XLSX
- CSV
- HTML
- PPTX
- scanned PDFs/OCR

### 8. Admin trace list/search page

Add:

- recent traces
- filter by model
- filter by status
- filter by latency
- filter by question text
- open trace detail

### 9. Authentication and tenant isolation

Defer until local v1 is stable.

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
- Keep response cache disabled until cache safety is fully scoped.
- Keep `gemma2:2b` routing disabled by default locally.
- Do not add RAGAS into request-time path.
