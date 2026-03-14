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

  const b = body as { prompt?: unknown; user_id?: unknown; session_id?: unknown };

  const message =
    typeof b.prompt === "string" ? b.prompt.trim() : "";
  const userId =
    typeof b.user_id === "string" && b.user_id.trim() ? b.user_id.trim() : "anonymous";
  const sessionId =
    typeof b.session_id === "string" && b.session_id.trim() ? b.session_id.trim() : "default";

  if (!message) {
    return NextResponse.json({ detail: "Prompt is required." }, { status: 400 });
  }

  try {
    const response = await fetch(`${backendUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, session_id: sessionId, message }),
      cache: "no-store",
    });

    const text = await response.text();
    let data: { response?: string; detail?: string } = {};

    if (text) {
      try {
        data = JSON.parse(text) as { response?: string; detail?: string };
      } catch {
        data = { detail: text };
      }
    }

    if (!response.ok) {
      return NextResponse.json(
        { detail: data.detail ?? "Agent request failed." },
        { status: response.status }
      );
    }

    return NextResponse.json({ response: data.response ?? "" });
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
