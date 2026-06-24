import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const FASTAPI = process.env.FASTAPI_URL || "http://127.0.0.1:8000";

type RouteContext = {
  params: Promise<{ dealId: string }>;
};

export async function POST(request: Request, { params }: RouteContext) {
  const { dealId } = await params;

  if (!/^\d+$/.test(dealId)) {
    return NextResponse.json({ detail: "Invalid deal id." }, { status: 400 });
  }

  const contentType = request.headers.get("content-type");
  if (!contentType?.toLowerCase().includes("multipart/form-data")) {
    return NextResponse.json(
      { detail: "Upload request must be multipart form data." },
      { status: 415 },
    );
  }

  if (!request.body) {
    return NextResponse.json(
      { detail: "Upload request did not include a file body." },
      { status: 400 },
    );
  }

  try {
    const upstream = await fetch(`${FASTAPI}/api/deals/${dealId}/documents/upload`, {
      method: "POST",
      headers: forwardedRequestHeaders(request),
      body: request.body,
      cache: "no-store",
      // Required by Node's fetch implementation when forwarding a streamed request body.
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: forwardedResponseHeaders(upstream),
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Unknown upload proxy failure.";
    return NextResponse.json(
      { detail: `Upload proxy could not reach the document API: ${detail}` },
      { status: 502 },
    );
  }
}

function forwardedRequestHeaders(request: Request): Headers {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const cookie = request.headers.get("cookie");
  const accept = request.headers.get("accept");

  if (contentType) headers.set("content-type", contentType);
  if (cookie) headers.set("cookie", cookie);
  if (accept) headers.set("accept", accept);

  return headers;
}

function forwardedResponseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  const contentType = upstream.headers.get("content-type");
  const retryAfter = upstream.headers.get("retry-after");
  const rateLimitBucket = upstream.headers.get("x-ratelimit-bucket");
  const rateLimitLimit = upstream.headers.get("x-ratelimit-limit");

  if (contentType) headers.set("content-type", contentType);
  if (retryAfter) headers.set("retry-after", retryAfter);
  if (rateLimitBucket) headers.set("x-ratelimit-bucket", rateLimitBucket);
  if (rateLimitLimit) headers.set("x-ratelimit-limit", rateLimitLimit);

  headers.set("cache-control", "no-store");
  return headers;
}
