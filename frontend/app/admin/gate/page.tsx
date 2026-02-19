"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { BrandWordmark } from "../../components/BrandWordmark";
import { SurfaceCard } from "../../components/SurfaceCard";
import { AuthClientError, isAbortError, postAuthJson } from "../../../lib/auth-client";

interface AdminLoginResponse {
  authenticated: boolean;
}

export default function AdminGatePage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestVersionRef = useRef(0);
  const inFlightControllerRef = useRef<AbortController | null>(null);
  const passwordInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const syncFromInput = () => {
      const currentValue = passwordInputRef.current?.value ?? "";
      setPassword((previous) => (previous === currentValue ? previous : currentValue));
    };

    syncFromInput();
    const intervalId = window.setInterval(syncFromInput, 250);
    const timeoutId = window.setTimeout(() => {
      window.clearInterval(intervalId);
    }, 2000);

    return () => {
      window.clearTimeout(timeoutId);
      window.clearInterval(intervalId);
      inFlightControllerRef.current?.abort();
      inFlightControllerRef.current = null;
    };
  }, []);

  function beginRequest(): { requestVersion: number; signal: AbortSignal } {
    requestVersionRef.current += 1;
    inFlightControllerRef.current?.abort();
    const controller = new AbortController();
    inFlightControllerRef.current = controller;
    return { requestVersion: requestVersionRef.current, signal: controller.signal };
  }

  function isCurrentRequest(requestVersion: number): boolean {
    return requestVersionRef.current === requestVersion;
  }

  async function handleLoginSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) {
      return;
    }

    const formData = new FormData(event.currentTarget);
    const rawPassword = String(formData.get("password") ?? "");
    const normalizedPassword = rawPassword.trim();
    setPassword(rawPassword);

    if (!normalizedPassword) {
      setError("Admin password is required.");
      return;
    }

    const { requestVersion, signal } = beginRequest();
    setError(null);
    setLoading(true);

    try {
      await postAuthJson<AdminLoginResponse>(
        "/api/admin/login",
        { password: normalizedPassword },
        { signal, fallbackMessage: "Unable to complete admin sign-in right now. Please try again." },
      );
      if (!isCurrentRequest(requestVersion)) {
        return;
      }

      router.push("/admin");
    } catch (err) {
      if (isAbortError(err) || !isCurrentRequest(requestVersion)) {
        return;
      }

      if (err instanceof AuthClientError) {
        setError(err.message);
      } else {
        setError("Unable to complete admin sign-in right now. Please try again.");
      }
    } finally {
      if (isCurrentRequest(requestVersion)) {
        inFlightControllerRef.current = null;
        setLoading(false);
      }
    }
  }

  function handlePasswordInput(value: string): void {
    setPassword(value);
    if (error) {
      setError(null);
    }
  }

  return (
    <main id="main-content" className="auth-scene auth-scene--gate">
      <div className="auth-layout auth-layout--gate">
        <header className="auth-hero auth-hero--compact reveal-item">
          <span className="eyebrow">Internal Access</span>
          <BrandWordmark size="sm" />
          <h1 className="auth-hero__title">Admin Operations</h1>
          <p className="auth-hero__copy">
            Restricted entry for authorized finance, operations, and compliance staff.
          </p>
          <ul className="auth-hero__list" aria-label="Admin security highlights">
            <li>Session-protected dashboard with strict cookie scope</li>
            <li>Credential validation with rate-limit enforcement</li>
            <li>Audit-safe access path for finance and operations workflows</li>
          </ul>
        </header>

        <SurfaceCard className="auth-panel auth-panel--gate reveal-item" data-delay="1">
          <form className="auth-form" onSubmit={handleLoginSubmit} noValidate aria-busy={loading}>
            <div className="auth-panel__head">
              <h2 className="auth-panel__title">Admin Sign In</h2>
              <p className="auth-panel__subtitle">Use your admin credential to access invoicing operations.</p>
            </div>
            <div className="auth-field">
              <label htmlFor="admin-password">Admin password</label>
              <div className="auth-password-row">
                <input
                  ref={passwordInputRef}
                  className="auth-input"
                  id="admin-password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Enter admin password"
                  value={password}
                  onChange={(event) => handlePasswordInput(event.target.value)}
                  onInput={(event) => handlePasswordInput(event.currentTarget.value)}
                  autoComplete="current-password"
                  autoFocus
                />
                <button
                  type="button"
                  className="button-link button-link--secondary auth-password-toggle"
                  onClick={() => setShowPassword((current) => !current)}
                  aria-label={showPassword ? "Hide password text" : "Show password text"}
                  aria-pressed={showPassword}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </div>
            {error ? (
              <p className="auth-feedback auth-feedback--error" role="alert" aria-live="polite">
                {error}
              </p>
            ) : null}
            <button
              className="button-link auth-submit"
              type="submit"
              disabled={loading}
            >
              {loading ? "Verifying..." : "Enter Dashboard"}
            </button>
          </form>

          <div className="auth-trust">
            <Image
              className="auth-trust__icon"
              src="/brand/eros-symbol.svg"
              alt=""
              aria-hidden="true"
              width={14}
              height={14}
            />
            <span>Admin security zone</span>
          </div>
        </SurfaceCard>
      </div>
    </main>
  );
}
