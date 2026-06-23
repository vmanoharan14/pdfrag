# PDFRAG

Enterprise document RAG implemented in small, testable slices.

## Local infrastructure

Models and application processes run directly on the host. Docker Compose runs
only PostgreSQL, Qdrant, Redis, and MinIO.

Start the services:

```bash
./scripts/start_infra.sh
```

Check service health:

```bash
./scripts/infra_status.sh
```

Stop the services:

```bash
./scripts/stop_infra.sh
```

Local endpoints:

- PostgreSQL: `127.0.0.1:15432`
- Redis: `127.0.0.1:16379`
- Qdrant HTTP: `http://127.0.0.1:16333`
- Qdrant gRPC: `127.0.0.1:16334`
- MinIO API: `http://127.0.0.1:9000`
- MinIO console: `http://127.0.0.1:9001`

The checked-in `.env.example` contains placeholders. The local `.env` file is
ignored by Git and must never contain production credentials.

## Backend health API

Create an isolated environment using the existing Python 3.13 interpreter:

```bash
./scripts/setup_backend.sh
```

Start the API:

```bash
./scripts/start_backend.sh
```

Health endpoints:

- Liveness: `http://127.0.0.1:18000/api/health/live`
- Dependency readiness: `http://127.0.0.1:18000/api/health/ready`
- OpenAPI: `http://127.0.0.1:18000/docs`

## Frontend

Install frontend dependencies:

```bash
./scripts/setup_frontend.sh
```

Start the Next.js development server:

```bash
./scripts/start_frontend.sh
```

Open:

- Overview: `http://127.0.0.1:13000`
- Chat preview: `http://127.0.0.1:13000/chat`
- Trace preview: `http://127.0.0.1:13000/traces/demo`
- Documents: `http://127.0.0.1:13000/documents`

## Database migrations

Apply backend schema migrations after infrastructure and backend setup:

```bash
./scripts/migrate_database.sh
```

Start the ingestion worker in a separate terminal:

```bash
./scripts/start_worker.sh
```

The local worker intentionally uses one process and one thread to bound CPU and
memory use while Docling parses documents. A successful ingestion now parses the
source, writes canonical Markdown to MinIO, creates local Markdown-layout chunks
in PostgreSQL, indexes dense vectors in Qdrant with `nomic-embed-text`, writes
BM25-compatible sparse lexical vectors to Qdrant, and marks the document version
active.
