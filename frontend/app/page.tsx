import Link from "next/link";

export default function HomePage() {
  return (
    <main style={{ margin: "3rem auto", maxWidth: 760, fontFamily: "sans-serif" }}>
      <h1>EROS Invoicing Web</h1>
      <p>Standalone Next.js skeleton for invoicing operations.</p>
      <Link href="/invoicing">Open invoicing dashboard</Link>
    </main>
  );
}
