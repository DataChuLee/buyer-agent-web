"use client";

import {
  canStartAutomation,
  getRunStatusLabel,
  type CheckoutSession,
  type LocalAutomationRun,
  type PurchaseStatus,
} from "@/lib/purchase-automation";

type PurchaseAutomationCardProps = {
  purchaseStatus?: PurchaseStatus;
  checkoutSession?: CheckoutSession | null;
  run?: LocalAutomationRun | null;
  pending?: boolean;
  errorMessage?: string | null;
  onStart: () => void;
  onOpenApproval: () => void;
  onCancel: () => void;
};

export default function PurchaseAutomationCard({
  purchaseStatus,
  checkoutSession,
  run,
  pending = false,
  errorMessage,
  onStart,
  onOpenApproval,
  onCancel,
}: PurchaseAutomationCardProps) {
  if (!checkoutSession) {
    return null;
  }

  const ready = canStartAutomation(purchaseStatus, checkoutSession);
  const statusText = run ? getRunStatusLabel(run.status) : ready ? "결제 전 자동 주문 준비 가능" : "구매 정보 확인 필요";
  const totalText = run?.detected_total ?? checkoutSession.product.price ?? "확인 중";

  return (
    <section className="rounded-3xl border border-cyan-400/20 bg-cyan-500/[0.06] p-5 text-white shadow-[0_20px_60px_-40px_rgba(34,211,238,0.8)]">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-200/80">
            Purchase Automation
          </p>
          <h3 className="text-lg font-semibold text-white">{checkoutSession.product.name}</h3>
          <p className="text-sm text-slate-300">{statusText}</p>
        </div>
        <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200">
          예상 결제금액 {totalText}
        </div>
      </div>

      <dl className="mt-4 grid gap-3 text-sm text-slate-300 md:grid-cols-2">
        <div className="rounded-2xl border border-white/8 bg-black/15 p-3">
          <dt className="text-xs uppercase tracking-[0.2em] text-slate-500">Option</dt>
          <dd className="mt-2 text-white">
            사이즈 {checkoutSession.product.size ?? "-"} / 수량 {checkoutSession.product.quantity ?? 1}
          </dd>
        </div>
        <div className="rounded-2xl border border-white/8 bg-black/15 p-3">
          <dt className="text-xs uppercase tracking-[0.2em] text-slate-500">Shipping</dt>
          <dd className="mt-2 text-white">{checkoutSession.shipping_info.recipient_name ?? "-"}</dd>
          <dd className="mt-1 text-slate-300">
            {checkoutSession.shipping_info.address ?? ""} {checkoutSession.shipping_info.detail_address ?? ""}
          </dd>
        </div>
      </dl>

      {run?.error_message || errorMessage ? (
        <p className="mt-4 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
          {run?.error_message ?? errorMessage}
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-3">
        {!run && ready ? (
          <button
            type="button"
            onClick={onStart}
            disabled={pending}
            className="rounded-full bg-cyan-300 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-cyan-300/40"
          >
            {pending ? "자동 주문 준비 중..." : "자동 주문 준비 시작"}
          </button>
        ) : null}

        {run?.status === "running" ? (
          <button
            type="button"
            disabled
            className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-300"
          >
            자동 주문 준비 중...
          </button>
        ) : null}

        {run?.status === "awaiting_final_approval" ? (
          <>
            <button
              type="button"
              onClick={onOpenApproval}
              className="rounded-full bg-cyan-300 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-200"
            >
              최종 승인 열기
            </button>
            <button
              type="button"
              onClick={onCancel}
              className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10"
            >
              자동 주문 취소
            </button>
          </>
        ) : null}

        {run && run.status !== "running" && run.status !== "awaiting_final_approval" && ready ? (
          <button
            type="button"
            onClick={onStart}
            disabled={pending}
            className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10 disabled:cursor-not-allowed"
          >
            다시 시도
          </button>
        ) : null}
      </div>
    </section>
  );
}
