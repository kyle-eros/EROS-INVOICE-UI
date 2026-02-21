"use client";

import { useEffect, useRef, useState } from "react";

interface FlashResponse {
  creator_id: string | null;
  creator_name: string | null;
  passkey: string | null;
}

type CopyArtifact = "passkey" | "creator_id" | "portal_link";

function fallbackCopyText(value: string): boolean {
  if (typeof document === "undefined") {
    return false;
  }

  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-9999px";
  textarea.style.left = "-9999px";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);

  let copied = false;
  try {
    if (typeof document.execCommand === "function") {
      copied = document.execCommand("copy");
    }
  } catch {
    copied = false;
  } finally {
    textarea.remove();
  }
  return copied;
}

async function copyText(value: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    // Fall through to document.execCommand fallback.
  }

  return fallbackCopyText(value);
}

export function AdminPasskeyFlash() {
  const [payload, setPayload] = useState<FlashResponse | null>(null);
  const [copyStatus, setCopyStatus] = useState<string>("");
  const copyStatusTimerRef = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    async function loadFlash() {
      try {
        const response = await fetch("/admin/passkey-flash", {
          method: "GET",
          cache: "no-store",
        });
        if (!response.ok || !active) {
          return;
        }
        const parsed = (await response.json()) as FlashResponse;
        if (parsed.passkey && parsed.creator_name && parsed.creator_id) {
          setPayload(parsed);
        }
      } catch {
        // Silent fail: flash display should never block admin workflow.
      }
    }
    void loadFlash();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (copyStatusTimerRef.current !== null) {
        window.clearTimeout(copyStatusTimerRef.current);
      }
    };
  }, []);

  function setTransientStatus(message: string): void {
    setCopyStatus(message);
    if (copyStatusTimerRef.current !== null) {
      window.clearTimeout(copyStatusTimerRef.current);
    }
    copyStatusTimerRef.current = window.setTimeout(() => {
      setCopyStatus("");
      copyStatusTimerRef.current = null;
    }, 2600);
  }

  async function handleCopy(artifact: CopyArtifact): Promise<void> {
    if (!payload?.passkey || !payload.creator_id) {
      return;
    }

    const value =
      artifact === "passkey"
        ? payload.passkey
        : artifact === "creator_id"
          ? payload.creator_id
          : `${window.location.origin}/login`;
    const copied = await copyText(value);
    if (!copied) {
      setTransientStatus("Copy failed. Select and copy manually.");
      return;
    }

    if (artifact === "passkey") {
      setTransientStatus("Passkey copied.");
      return;
    }
    if (artifact === "creator_id") {
      setTransientStatus("Creator ID copied.");
      return;
    }
    setTransientStatus("Portal link copied.");
  }

  if (!payload?.passkey || !payload.creator_name || !payload.creator_id) {
    return null;
  }

  return (
    <div className="passkey-flash">
      <p className="muted-small">
        Passkey generated for <strong>{payload.creator_name}</strong>:
      </p>
      <div className="passkey-display">{payload.passkey}</div>
      <p className="muted-small">
        Creator ID: <span className="task-id">{payload.creator_id}</span>
      </p>
      <div className="passkey-copy-actions" role="group" aria-label="Copy creator login artifacts">
        <button
          type="button"
          className="button-link button-link--secondary passkey-copy-action"
          onClick={() => void handleCopy("passkey")}
        >
          Copy passkey
        </button>
        <button
          type="button"
          className="button-link button-link--secondary passkey-copy-action"
          onClick={() => void handleCopy("creator_id")}
        >
          Copy creator ID
        </button>
        <button
          type="button"
          className="button-link button-link--secondary passkey-copy-action"
          onClick={() => void handleCopy("portal_link")}
        >
          Copy portal link
        </button>
      </div>
      {copyStatus ? (
        <p className="muted-small passkey-copy-status" role="status" aria-live="polite">
          {copyStatus}
        </p>
      ) : null}
      <p className="passkey-warning">This passkey is shown only once. Copy it now and send it securely.</p>
      <p className="muted-small">If clipboard access is blocked, highlight the values above and copy manually.</p>
    </div>
  );
}
