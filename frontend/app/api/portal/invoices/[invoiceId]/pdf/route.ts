import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { fetchCreatorInvoicePdfBySession } from "../../../../../../lib/api";

function safeFilename(invoiceId: string): string {
  const cleaned = invoiceId.replace(/[^a-zA-Z0-9._-]/g, "_");
  return `${cleaned || "invoice"}.pdf`;
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ invoiceId: string }> },
) {
  const { invoiceId } = await params;
  const cookieStore = await cookies();
  const sessionToken = cookieStore.get("eros_session")?.value;

  if (!sessionToken) {
    return NextResponse.json({ error: "session required" }, { status: 401 });
  }

  const backendResponse = await fetchCreatorInvoicePdfBySession(sessionToken, invoiceId);
  if (!backendResponse.ok) {
    let detail = `PDF fetch failed (${backendResponse.status})`;
    try {
      const payload = (await backendResponse.json()) as { detail?: string; error?: string };
      detail = payload.detail || payload.error || detail;
    } catch {
      // keep fallback detail message
    }
    return NextResponse.json({ error: detail }, { status: backendResponse.status });
  }

  const asDownload = request.nextUrl.searchParams.get("download") === "1";
  const content = await backendResponse.arrayBuffer();
  const headers = new Headers();
  headers.set("Content-Type", "application/pdf");
  headers.set(
    "Content-Disposition",
    asDownload
      ? `attachment; filename="${safeFilename(invoiceId)}"`
      : (backendResponse.headers.get("content-disposition") ?? `inline; filename="${safeFilename(invoiceId)}"`),
  );

  return new NextResponse(content, {
    status: 200,
    headers,
  });
}
