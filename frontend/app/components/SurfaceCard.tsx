import type { HTMLAttributes, ReactNode } from "react";

interface SurfaceCardProps extends HTMLAttributes<HTMLElement> {
  as?: "section" | "article" | "div";
  children: ReactNode;
}

export function SurfaceCard({ as = "section", className, children, ...rest }: SurfaceCardProps) {
  const TagName = as;

  return (
    <TagName className={["surface-card", className].filter(Boolean).join(" ")} {...rest}>
      {children}
    </TagName>
  );
}
