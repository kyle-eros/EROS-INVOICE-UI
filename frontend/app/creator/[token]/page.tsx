import Link from "next/link";
import { redirect } from "next/navigation";
import { BrandWordmark } from "../../components/BrandWordmark";
import { SurfaceCard } from "../../components/SurfaceCard";

export default async function DeprecatedCreatorPage() {
  return (
    <main id="main-content" className="page-wrap">
      <div className="section-stack">
        <header className="creator-header reveal-item" style={{ textAlign: "center" }}>
          <BrandWordmark size="sm" />
        </header>

        <SurfaceCard as="section" className="login-card reveal-item" data-delay="1">
          <h2>This link is no longer active</h2>
          <p className="kicker">
            We&apos;ve upgraded to a new login system. Please use the passkey your agency sent you to sign in.
          </p>
          <Link className="button-link" href="/login">
            Go to Sign In
          </Link>
        </SurfaceCard>
      </div>
    </main>
  );
}
