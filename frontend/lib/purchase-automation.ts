export type PurchaseStatus =
  | "awaiting_product_selection"
  | "awaiting_purchase_info"
  | "ready_for_checkout"
  | "unsupported_seller"
  | "missing_product_url"
  | string
  | null
  | undefined;

export type AutomationRunStatus =
  | "running"
  | "awaiting_final_approval"
  | "submitted"
  | "cancelled"
  | "failed"
  | "needs_manual_intervention";

export type CheckoutSession = {
  id: string;
  seller_code: string;
  automation_mode: string;
  approval_boundary: string;
  product: {
    name: string;
    size?: string | null;
    price?: string | null;
    quantity?: number | null;
  };
  shipping_info: {
    recipient_name?: string | null;
    phone?: string | null;
    address?: string | null;
    detail_address?: string | null;
  };
};

export type LocalAutomationRun = {
  id: string;
  status: AutomationRunStatus;
  summary?: Record<string, unknown> | null;
  detected_total?: string | null;
  screenshot_url?: string | null;
  confirmation_message?: string | null;
  error_code?: string | null;
  error_message?: string | null;
};

export function canStartAutomation(
  purchaseStatus: PurchaseStatus,
  checkoutSession: CheckoutSession | null | undefined,
): checkoutSession is CheckoutSession {
  return Boolean(
    purchaseStatus === "ready_for_checkout" &&
      checkoutSession &&
      checkoutSession.automation_mode === "local_agent_browser" &&
      checkoutSession.approval_boundary === "before_payment_submit",
  );
}

export function isAwaitingFinalApproval(run: LocalAutomationRun | null | undefined): boolean {
  return run?.status === "awaiting_final_approval";
}

export function getRunStatusLabel(status: AutomationRunStatus): string {
  switch (status) {
    case "running":
      return "자동 주문 준비 중";
    case "awaiting_final_approval":
      return "최종 승인 대기";
    case "submitted":
      return "주문 제출 완료";
    case "cancelled":
      return "자동 주문 취소됨";
    case "needs_manual_intervention":
      return "수동 확인 필요";
    case "failed":
    default:
      return "자동 주문 실패";
  }
}

export function getLocalAutomationBaseUrl(): string {
  return (
    process.env.NEXT_PUBLIC_LOCAL_AUTOMATION_URL ??
    "http://127.0.0.1:8123"
  ).replace(/\/+$/, "");
}

async function parseRunResponse(response: Response): Promise<LocalAutomationRun> {
  if (!response.ok) {
    let detail = "로컬 자동화 워커에 연결하지 못했습니다.";
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail ?? detail;
    } catch {
      // Ignore non-JSON responses.
    }
    throw new Error(detail);
  }

  return (await response.json()) as LocalAutomationRun;
}

export async function startLocalAutomation(checkoutSession: CheckoutSession): Promise<LocalAutomationRun> {
  const response = await fetch(`${getLocalAutomationBaseUrl()}/sessions/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(checkoutSession),
  });
  return parseRunResponse(response);
}

export async function getLocalAutomationRun(runId: string): Promise<LocalAutomationRun> {
  const response = await fetch(`${getLocalAutomationBaseUrl()}/sessions/${runId}`, {
    cache: "no-store",
  });
  return parseRunResponse(response);
}

export async function approveLocalAutomation(runId: string): Promise<LocalAutomationRun> {
  const response = await fetch(`${getLocalAutomationBaseUrl()}/sessions/${runId}/approve`, {
    method: "POST",
  });
  return parseRunResponse(response);
}

export async function cancelLocalAutomation(runId: string): Promise<LocalAutomationRun> {
  const response = await fetch(`${getLocalAutomationBaseUrl()}/sessions/${runId}/cancel`, {
    method: "POST",
  });
  return parseRunResponse(response);
}
