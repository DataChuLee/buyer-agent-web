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
    const response = await fetch(`${backendUrl}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, session_id: sessionId, message }),
      cache: "no-store",
    });

    if (!response.ok) {
      const text = await response.text();
      let detail = "Agent request failed.";
      try {
        detail = (JSON.parse(text) as { detail?: string }).detail ?? detail;
      } catch { /* ignore */ }
      return NextResponse.json({ detail }, { status: response.status });
    }

    if (!response.body) {
      return NextResponse.json({ detail: "No response body from backend." }, { status: 502 });
    }

    return new Response(response.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
      },
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
