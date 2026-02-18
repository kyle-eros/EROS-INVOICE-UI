"use client";

import { useEffect, useState } from "react";

interface FlashResponse {
  creator_name: string | null;
  passkey: string | null;
}

export function AdminPasskeyFlash() {
  const [payload, setPayload] = useState<FlashResponse | null>(null);

  useEffect(() => {
    let active = true;
    async function loadFlash() {
      try {
        const response = await fetch("/api/admin/passkey-flash", {
          method: "GET",
          cache: "no-store",
        });
        if (!response.ok || !active) {
          return;
        }
        const parsed = (await response.json()) as FlashResponse;
        if (parsed.passkey && parsed.creator_name) {
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

  if (!payload?.passkey || !payload.creator_name) {
    return null;
  }

  return (
    <div>
      <p className="muted-small">
        Passkey generated for <strong>{payload.creator_name}</strong>:
      </p>
      <div className="passkey-display">{payload.passkey}</div>
      <p className="passkey-warning">This passkey is shown only once. Copy it now and send it securely.</p>
    </div>
  );
}
