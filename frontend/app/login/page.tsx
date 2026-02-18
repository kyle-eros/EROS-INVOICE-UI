"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { BrandWordmark } from "../components/BrandWordmark";
import { SurfaceCard } from "../components/SurfaceCard";
import { AuthClientError, isAbortError, postAuthJson } from "../../lib/auth-client";

type Step = "paste" | "confirm" | "redirecting";

interface LookupResponse {
  creator_id: string;
  creator_name: string;
}

interface ConfirmResponse {
  creator_id: string;
  creator_name: string;
}

export default function LoginPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("paste");
  const [passkey, setPasskey] = useState("");
  const [creatorName, setCreatorName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const requestVersionRef = useRef(0);
  const inFlightControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
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

  function resetToPaste(): void {
    requestVersionRef.current += 1;
    inFlightControllerRef.current?.abort();
    inFlightControllerRef.current = null;
    setStep("paste");
    setPasskey("");
    setCreatorName("");
    setError(null);
    setLoading(false);
  }

  async function handleLookupSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedPasskey = passkey.trim();
    if (!normalizedPasskey || loading) {
      return;
    }

    const { requestVersion, signal } = beginRequest();
    setError(null);
    setLoading(true);

    try {
      const data = await postAuthJson<LookupResponse>(
        "/api/auth/lookup",
        { passkey: normalizedPasskey },
        { signal, fallbackMessage: "Unable to verify your passkey right now. Please try again." },
      );
      if (!isCurrentRequest(requestVersion)) {
        return;
      }

      setCreatorName(data.creator_name);
      setStep("confirm");
    } catch (err) {
      if (isAbortError(err) || !isCurrentRequest(requestVersion)) {
        return;
      }

      if (err instanceof AuthClientError) {
        setError(err.message);
      } else {
        setError("Unable to verify your passkey right now. Please try again.");
      }
    } finally {
      if (isCurrentRequest(requestVersion)) {
        inFlightControllerRef.current = null;
        setLoading(false);
      }
    }
  }

  async function handleConfirmSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedPasskey = passkey.trim();
    if (!normalizedPasskey || loading) {
      return;
    }

    const { requestVersion, signal } = beginRequest();
    setError(null);
    setLoading(true);

    try {
      const data = await postAuthJson<ConfirmResponse>(
        "/api/auth/confirm",
        { passkey: normalizedPasskey },
        { signal, fallbackMessage: "Unable to complete sign-in right now. Please try again." },
      );
      if (!isCurrentRequest(requestVersion)) {
        return;
      }

      setCreatorName(data.creator_name);
      setStep("redirecting");
      router.push("/portal");
    } catch (err) {
      if (isAbortError(err) || !isCurrentRequest(requestVersion)) {
        return;
      }

      if (err instanceof AuthClientError) {
        setError(err.message);
        if (err.code === "INVALID_CREDENTIALS") {
          setStep("paste");
          setCreatorName("");
        }
      } else {
        setError("Unable to complete sign-in right now. Please try again.");
      }
    } finally {
      if (isCurrentRequest(requestVersion)) {
        inFlightControllerRef.current = null;
        setLoading(false);
      }
    }
  }

  const hasPasskey = passkey.trim().length > 0;

  return (
    <main id="main-content" className="auth-scene">
      <div className="auth-layout">
        <header className="auth-hero reveal-item">
          <span className="eyebrow">Creator Portal</span>
          <BrandWordmark size="lg" />
          <h1 className="auth-hero__title">Secure access to your creator finance portal.</h1>
          <p className="auth-hero__copy">
            Use the passkey we sent you to enter a secure workspace for invoices, balances, and due-date tracking.
          </p>
          <ul className="auth-hero__list" aria-label="Security highlights">
            <li>Signed session token with strict cookie controls</li>
            <li>Automated login throttling to block brute-force attempts</li>
            <li>Immediate passkey revocation support from us</li>
          </ul>
        </header>

        <SurfaceCard className="auth-panel reveal-item" data-delay="1">
          {step === "paste" && (
            <form className="auth-form" onSubmit={handleLookupSubmit} noValidate aria-busy={loading}>
              <div className="auth-panel__head">
                <h2 className="auth-panel__title">Sign In</h2>
                <p className="auth-panel__subtitle">Paste the passkey we sent you.</p>
              </div>
              <div className="auth-field">
                <label htmlFor="creator-passkey">Your passkey</label>
                <input
                  className="auth-input"
                  id="creator-passkey"
                  type="text"
                  placeholder="Paste your passkey here"
                  value={passkey}
                  onChange={(event) => setPasskey(event.target.value)}
                  autoComplete="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  autoFocus
                />
              </div>
              {error ? (
                <p className="auth-feedback auth-feedback--error" role="alert" aria-live="polite">
                  {error}
                </p>
              ) : null}
              <button
                className="button-link auth-submit"
                type="submit"
                disabled={loading || !hasPasskey}
              >
                {loading ? "Checking passkey..." : "Continue"}
              </button>
            </form>
          )}

          {step === "confirm" && (
            <form className="auth-form" onSubmit={handleConfirmSubmit} noValidate aria-busy={loading}>
              <div className="auth-panel__head">
                <h2 className="auth-panel__title">Confirm Identity</h2>
                <p className="auth-panel__subtitle">You are signing in as:</p>
              </div>
              <p className="auth-identity">{creatorName}</p>
              {error ? (
                <p className="auth-feedback auth-feedback--error" role="alert" aria-live="polite">
                  {error}
                </p>
              ) : null}
              <div className="auth-actions">
                <button
                  className="button-link auth-submit"
                  type="submit"
                  disabled={loading}
                >
                  {loading ? "Signing in..." : "Yes, that\u2019s me"}
                </button>
                <button
                  className="button-link button-link--secondary"
                  type="button"
                  onClick={resetToPaste}
                >
                  This isn&apos;t me
                </button>
              </div>
            </form>
          )}

          {step === "redirecting" && (
            <section className="auth-form" aria-live="polite">
              <div className="auth-panel__head">
                <h2 className="auth-panel__title">Welcome, {creatorName}</h2>
                <p className="auth-panel__subtitle">Redirecting to your portal...</p>
              </div>
              <p className="auth-feedback auth-feedback--info">Your secure session is active.</p>
            </section>
          )}

          <div className="auth-trust">
            <Image
              className="auth-trust__icon"
              src="/brand/eros-symbol.svg"
              alt=""
              aria-hidden="true"
              width={14}
              height={14}
            />
            <span>Secured by EROS</span>
          </div>
        </SurfaceCard>
      </div>

      <footer className="auth-footer">
        <span>Need help with access? Message us and we&apos;ll get you a new passkey.</span>
      </footer>
    </main>
  );
}
