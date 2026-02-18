import Image from "next/image";

interface BrandWordmarkProps {
  className?: string;
  size?: "sm" | "md" | "lg";
}

export function BrandWordmark({ className, size = "md" }: BrandWordmarkProps) {
  const sizeClass = size === "sm" ? "brand-wordmark--sm" : size === "lg" ? "brand-wordmark--lg" : "";
  // Logo aspect ratio is ~4.17:1 (743x178 source with smoothed alpha edges)
  const dimensions =
    size === "sm" ? { width: 150, height: 36 } : size === "lg" ? { width: 280, height: 67 } : { width: 200, height: 48 };

  return (
    <span className={["brand-wordmark", sizeClass, className].filter(Boolean).join(" ")}>
      <Image
        className="brand-wordmark__logo"
        src="/brand/eros-logo-hero-transparent-hq.png"
        alt="EROS"
        width={dimensions.width}
        height={dimensions.height}
        priority={size === "lg"}
        unoptimized
      />
    </span>
  );
}
