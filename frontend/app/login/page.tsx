"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { BrandWordmark } from "../components/BrandWordmark";
import { SurfaceCard } from "../components/SurfaceCard";

type Step = "paste" | "confirm" | "redirecting";

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("paste");
  const [passkey, setPasskey] = useState("");
  const [creatorName, setCreatorName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLookup() {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/lookup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passkey: passkey.trim() }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Invalid passkey");
      }
      const data = await res.json();
      setCreatorName(data.creator_name);
      setStep("confirm");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/auth/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ passkey: passkey.trim() }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Login failed");
      }
      setStep("redirecting");
      router.push("/portal");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setStep("paste");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main-content" className="page-wrap">
      <div className="section-stack">
        <header className="creator-header reveal-item" style={{ textAlign: "center" }}>
          <BrandWordmark size="sm" />
        </header>

        <SurfaceCard className="login-card reveal-item" data-delay="1">
          {step === "paste" && (
            <>
              <h1>Sign In to Your Portal</h1>
              <p className="kicker">Paste the passkey you received from your agency.</p>
              <input
                className="login-input"
                type="text"
                placeholder="Paste your passkey here"
                value={passkey}
                onChange={(e) => setPasskey(e.target.value)}
                autoFocus
              />
              {error && <p className="login-error">{error}</p>}
              <button
                className="button-link"
                onClick={handleLookup}
                disabled={loading || !passkey.trim()}
              >
                {loading ? "Looking up..." : "Look Up"}
              </button>
            </>
          )}

          {step === "confirm" && (
            <>
              <h1>Is this you?</h1>
              <p className="login-confirm-name">{creatorName}</p>
              {error && <p className="login-error">{error}</p>}
              <div className="login-actions">
                <button
                  className="button-link"
                  onClick={handleConfirm}
                  disabled={loading}
                >
                  {loading ? "Signing in..." : "Yes, that\u2019s me"}
                </button>
                <button
                  className="button-link button-link--secondary"
                  onClick={() => {
                    setStep("paste");
                    setPasskey("");
                    setCreatorName("");
                    setError(null);
                  }}
                >
                  That&apos;s not me
                </button>
              </div>
            </>
          )}

          {step === "redirecting" && (
            <>
              <h1>Welcome, {creatorName}</h1>
              <p className="kicker">Redirecting to your portal...</p>
            </>
          )}
        </SurfaceCard>
      </div>
    </main>
  );
}
