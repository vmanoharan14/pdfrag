import Link from "next/link";

type Dependency = {
  status: string;
  latency_ms?: number;
};

type HealthPayload = {
  status: string;
  dependencies: Record<string, Dependency>;
};

async function getHealth(): Promise<HealthPayload | null> {
  try {
    const response = await fetch(
      process.env.BACKEND_URL ??
        "http://127.0.0.1:18000/api/health/ready",
      { cache: "no-store" },
    );
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  const health = await getHealth();
  const services = ["postgres", "redis", "qdrant", "minio", "ollama"];

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>System overview</h1>
        </div>
        <span className={`status-pill ${health ? "success" : "warning"}`}>
          {health ? "All systems healthy" : "Backend unavailable"}
        </span>
      </header>

      <div className="page-content">
        <section className="hero-card">
          <div>
            <p className="eyebrow">Inspectable retrieval</p>
            <h2>See how every answer is built.</h2>
            <p>
              PDFRAG records routing, retrieval, fusion, reranking, context,
              generation, and citations as an explicit visual trace.
            </p>
          </div>
          <Link className="primary-button" href="/traces/demo">
            View sample trace
            <span>→</span>
          </Link>
        </section>

        <section>
          <div className="section-heading">
            <div>
              <p className="eyebrow">Runtime</p>
              <h2>Service health</h2>
            </div>
            <small>Live from FastAPI</small>
          </div>

          <div className="service-grid">
            {services.map((service) => {
              const state = health?.dependencies[service];
              return (
                <article className="service-card" key={service}>
                  <div className="service-card-header">
                    <span className={`service-dot ${state ? "online" : ""}`} />
                    <span>{state?.status ?? "unavailable"}</span>
                  </div>
                  <h3>{service}</h3>
                  <p>
                    {state?.latency_ms !== undefined
                      ? `${state.latency_ms.toFixed(1)} ms`
                      : "No response"}
                  </p>
                </article>
              );
            })}
          </div>
        </section>
      </div>
    </>
  );
}
