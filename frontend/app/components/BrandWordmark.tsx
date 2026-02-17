interface BrandWordmarkProps {
  className?: string;
  size?: "sm" | "md" | "lg";
}

export function BrandWordmark({ className, size = "md" }: BrandWordmarkProps) {
  const sizeClass = size === "sm" ? "brand-wordmark--sm" : size === "lg" ? "brand-wordmark--lg" : "";

  return (
    <span className={["brand-wordmark", sizeClass, className].filter(Boolean).join(" ")}>
      <span>EROS</span>
      <span className="brand-wordmark-accent">Invoicing</span>
    </span>
  );
}
