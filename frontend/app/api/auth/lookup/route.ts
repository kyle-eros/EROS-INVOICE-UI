import { NextRequest, NextResponse } from "next/server";
import { backendLookupPasskey } from "../../../../lib/api";
import { mapAuthRouteError } from "../../../../lib/auth-errors";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const passkey = body.passkey;
    if (!passkey || typeof passkey !== "string") {
      return NextResponse.json({ error: "Passkey is required.", code: "BAD_REQUEST" }, { status: 400 });
    }
    const result = await backendLookupPasskey(passkey);
    return NextResponse.json(result);
  } catch (error) {
    const mapped = mapAuthRouteError(error, "creator_lookup");
    return NextResponse.json(mapped.payload, { status: mapped.status });
  }
}
