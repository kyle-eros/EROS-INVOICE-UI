import Link from "next/link";
import { BrandWordmark } from "./components/BrandWordmark";
import { SurfaceCard } from "./components/SurfaceCard";

export default function HomePage() {
  return (
    <main id="main-content" className="page-wrap">
      <div className="section-stack">
        <header className="home-hero surface-card reveal-item">
          <div className="home-hero__copy">
            <span className="eyebrow">EROS Creator Portal</span>
            <BrandWordmark size="lg" />
            <h1 className="home-hero__title">Your invoices, all in one place.</h1>
            <p className="kicker">
              Check your balance, review invoice details, and download official PDFs with your secure passkey.
            </p>
            <div className="home-hero__actions">
              <Link className="button-link" href="/login">
                Sign In to Your Portal
              </Link>
            </div>
          </div>
        </header>

        <section className="home-trust-grid reveal-item" data-delay="1" aria-label="Key features">
          <SurfaceCard className="home-trust-card">
            <h2>See What You Owe</h2>
            <p>View all your outstanding invoices, amounts due, and payment due dates in one place.</p>
          </SurfaceCard>
          <SurfaceCard className="home-trust-card">
            <h2>Track Payment Progress</h2>
            <p>See invoice status updates in one place, including open, overdue, partial, and paid states.</p>
          </SurfaceCard>
        </section>

        <SurfaceCard as="section" className="home-trust-card reveal-item" data-delay="2">
          <h2>How do I access my invoices?</h2>
          <p>
            We&apos;ll send your passkey directly to you. This secure code is what you use to sign in to your portal.
            Paste it on the sign-in page to view your invoices and download PDFs. You&apos;ll use this same passkey
            each time you sign in. If you lose it or need a new one at any time, message us and we&apos;ll send a
            replacement right away.
          </p>
        </SurfaceCard>
      </div>
    </main>
  );
}
