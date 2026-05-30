"use client";

import {
  type CheckoutSession,
  type LocalAutomationRun,
} from "@/lib/purchase-automation";

type PurchaseApprovalModalProps = {
  open: boolean;
  checkoutSession: CheckoutSession | null;
  run: LocalAutomationRun | null;
  approvalPending?: boolean;
  onApprove: () => void;
  onCancel: () => void;
  onClose: () => void;
};

function SummaryRow({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-white/8 py-3 text-sm last:border-b-0">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-right text-white">{value ?? "-"}</dd>
    </div>
  );
}

export default function PurchaseApprovalModal({
  open,
  checkoutSession,
  run,
  approvalPending = false,
  onApprove,
  onCancel,
  onClose,
}: PurchaseApprovalModalProps) {
  if (!open || !checkoutSession || !run) {
    return null;
  }

  const summary = run.summary ?? {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#020617]/80 px-4 py-8 backdrop-blur-sm">
      <div className="w-full max-w-4xl overflow-hidden rounded-[32px] border border-white/10 bg-[#0b1220] shadow-[0_40px_120px_-50px_rgba(0,0,0,0.95)]">
        <div className="flex items-start justify-between gap-4 border-b border-white/8 px-6 py-5">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-200/80">
              Final Approval
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-white">최종 결제 직전 승인</h2>
            <p className="mt-2 text-sm text-slate-400">
              아래 정보와 스크린샷을 확인한 뒤 승인하면 마지막 결제 제출 동작을 실행합니다.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-white/10 px-3 py-1.5 text-sm text-slate-300 transition hover:bg-white/5"
          >
            닫기
          </button>
        </div>

        <div className="grid gap-0 lg:grid-cols-[1.05fr_0.95fr]">
          <div className="border-b border-white/8 p-6 lg:border-b-0 lg:border-r">
            <h3 className="text-sm font-medium uppercase tracking-[0.22em] text-slate-500">Summary</h3>
            <dl className="mt-4">
              <SummaryRow label="상품" value={String(summary.product_name ?? checkoutSession.product.name)} />
              <SummaryRow label="사이즈" value={String(summary.size ?? checkoutSession.product.size ?? "-")} />
              <SummaryRow label="수량" value={String(summary.quantity ?? checkoutSession.product.quantity ?? 1)} />
              <SummaryRow label="결제금액" value={String(run.detected_total ?? checkoutSession.product.price ?? "-")} />
              <SummaryRow label="수령인" value={String(summary.recipient_name ?? checkoutSession.shipping_info.recipient_name ?? "-")} />
              <SummaryRow label="전화번호" value={String(summary.phone ?? checkoutSession.shipping_info.phone ?? "-")} />
              <SummaryRow
                label="배송지"
                value={`${String(summary.address ?? checkoutSession.shipping_info.address ?? "")} ${String(summary.detail_address ?? checkoutSession.shipping_info.detail_address ?? "")}`.trim()}
              />
            </dl>
          </div>

          <div className="p-6">
            <h3 className="text-sm font-medium uppercase tracking-[0.22em] text-slate-500">Review Capture</h3>
            {run.screenshot_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={run.screenshot_url}
                alt="Automation review screenshot"
                className="mt-4 h-[320px] w-full rounded-3xl border border-white/8 object-cover"
              />
            ) : (
              <div className="mt-4 flex h-[320px] items-center justify-center rounded-3xl border border-dashed border-white/10 bg-white/[0.03] px-6 text-center text-sm text-slate-500">
                스크린샷을 불러오지 못했습니다. 요약 정보를 확인한 뒤 승인할 수 있습니다.
              </div>
            )}

            <div className="mt-6 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={onApprove}
                disabled={approvalPending}
                className="rounded-full bg-cyan-300 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-cyan-300/40"
              >
                {approvalPending ? "최종 승인 처리 중..." : "최종 결제 승인"}
              </button>
              <button
                type="button"
                onClick={onCancel}
                disabled={approvalPending}
                className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/10 disabled:cursor-not-allowed disabled:text-slate-500"
              >
                자동 주문 취소
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
