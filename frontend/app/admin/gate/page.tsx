"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { BrandWordmark } from "../../components/BrandWordmark";
import { SurfaceCard } from "../../components/SurfaceCard";

export default function AdminGatePage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleLogin() {
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Invalid password");
      }
      router.push("/admin");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main-content" className="page-wrap">
      <div className="section-stack" style={{ paddingTop: "20vh" }}>
        <SurfaceCard className="gate-card reveal-item">
          <BrandWordmark size="sm" />
          <h1>Admin Access</h1>
          <input
            className="login-input"
            type="password"
            placeholder="Enter admin password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && password) handleLogin();
            }}
            autoFocus
          />
          {error && <p className="login-error">{error}</p>}
          <button
            className="button-link"
            onClick={handleLogin}
            disabled={loading || !password}
          >
            {loading ? "Verifying..." : "Enter"}
          </button>
        </SurfaceCard>
      </div>
    </main>
  );
}
