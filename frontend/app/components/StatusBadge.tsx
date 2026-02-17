import type { ReactNode } from "react";

export type StatusTone = "success" | "warning" | "brand" | "danger" | "muted";

interface StatusBadgeProps {
  tone: StatusTone;
  children: ReactNode;
  className?: string;
}

export function StatusBadge({ tone, children, className }: StatusBadgeProps) {
  return (
    <span className={["status-badge", `status-badge--${tone}`, className].filter(Boolean).join(" ")}>
      {children}
    </span>
  );
}
