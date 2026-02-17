import { NextRequest, NextResponse } from "next/server";
import { backendLookupPasskey } from "../../../../lib/api";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const passkey = body.passkey;
    if (!passkey || typeof passkey !== "string") {
      return NextResponse.json({ error: "passkey required" }, { status: 400 });
    }
    const result = await backendLookupPasskey(passkey);
    return NextResponse.json(result);
  } catch (error) {
    const message = error instanceof Error ? error.message : "lookup failed";
    const status = message.includes("401") ? 401 : message.includes("429") ? 429 : 500;
    return NextResponse.json({ error: message }, { status });
  }
}
