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
