import Link from "next/link";
import { BrandWordmark } from "./components/BrandWordmark";
import { SurfaceCard } from "./components/SurfaceCard";

export default function HomePage() {
  return (
    <main id="main-content" className="page-wrap">
      <div className="section-stack">
        <header className="home-hero surface-card reveal-item">
          <div className="home-hero__copy">
            <span className="eyebrow">Eros Revenue Operations</span>
            <BrandWordmark size="lg" />
            <h1 className="home-hero__title">Precision invoicing orchestration for high-trust agency finance.</h1>
            <p className="kicker">
              Operate preview, confirmation, and run workflows from a single premium control surface built for
              executive clarity and operational confidence.
            </p>
          </div>
          <div className="home-hero__actions">
            <Link className="button-link" href="/invoicing">
              Open Invoicing Dashboard
            </Link>
            <p className="home-hero__meta">Lifecycle support: preview, confirm, run-once, task and artifact visibility.</p>
          </div>
        </header>

        <section className="home-trust-grid reveal-item" data-delay="1" aria-label="System highlights">
          <SurfaceCard className="home-trust-card">
            <h2>Operational Readability</h2>
            <p>Tabular task visibility with high-legibility hierarchy for rapid decision cycles.</p>
          </SurfaceCard>
          <SurfaceCard className="home-trust-card">
            <h2>Workflow Integrity</h2>
            <p>Deterministic invoicing lifecycle with preview-to-run controls and traceable status signals.</p>
          </SurfaceCard>
          <SurfaceCard className="home-trust-card">
            <h2>Execution Confidence</h2>
            <p>Production-safe Next.js delivery designed for stable releases and audit-friendly operations.</p>
          </SurfaceCard>
        </section>
      </div>
    </main>
  );
}
