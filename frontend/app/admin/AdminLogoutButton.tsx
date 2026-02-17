"use client";

import { useRouter } from "next/navigation";

export function AdminLogoutButton() {
  const router = useRouter();

  async function handleLogout() {
    await fetch("/api/admin/logout", { method: "POST" });
    router.push("/admin/gate");
  }

  return (
    <button className="button-link button-link--secondary" onClick={handleLogout} style={{ padding: "6px 16px", fontSize: "0.84rem" }}>
      Sign Out
    </button>
  );
}
