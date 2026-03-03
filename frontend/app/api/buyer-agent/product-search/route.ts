import { NextResponse } from "next/server";

const backendUrl =
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_BACKEND_URL ??
  "http://127.0.0.1:8000";

export async function POST(request: Request) {
  let body: unknown;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON payload." }, { status: 400 });
  }

  const query =
    typeof body === "object" &&
    body !== null &&
    "prompt" in body &&
    typeof (body as { prompt: unknown }).prompt === "string"
      ? (body as { prompt: string }).prompt.trim()
      : "";

  if (!query) {
    return NextResponse.json({ detail: "Prompt is required." }, { status: 400 });
  }

  try {
    const response = await fetch(`${backendUrl}/buyer-agent/buyer_agent_0221`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
      cache: "no-store",
    });

    const text = await response.text();
    let data: { response?: string; agent?: string; detail?: string } = {};

    if (text) {
      try {
        data = JSON.parse(text) as { response?: string; agent?: string; detail?: string };
      } catch {
        data = { detail: text };
      }
    }

    if (!response.ok) {
      return NextResponse.json(
        { detail: data.detail ?? "Product search request failed." },
        { status: response.status }
      );
    }

    return NextResponse.json({
      response: data.response ?? "",
      agent: data.agent ?? "product_search_agent",
    });
  } catch (error) {
    const reason = error instanceof Error ? error.message : "Unknown network error";
    return NextResponse.json(
      {
        detail: `Backend connection failed (${backendUrl}). Make sure FastAPI server is running. ${reason}`,
      },
      { status: 502 }
    );
  }
}
