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
              Check your balance, view your invoices, and confirm payments — sign in with your passkey to get started.
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
            <h2>Confirm Your Payments</h2>
            <p>Once you&apos;ve submitted payment, mark your invoice as paid right from your portal.</p>
          </SurfaceCard>
        </section>

        <SurfaceCard as="section" className="home-trust-card reveal-item" data-delay="2">
          <h2>How do I access my invoices?</h2>
          <p>
            Your agency will send you a passkey — a secure code you use to sign in to your portal.
            Paste it on the sign-in page to view and manage your invoices. Your passkey stays the same
            until your agency revokes it, so keep it somewhere safe.
          </p>
        </SurfaceCard>
      </div>
    </main>
  );
}
