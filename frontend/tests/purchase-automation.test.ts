import assert from "node:assert/strict";

import {
  canStartAutomation,
  getRunStatusLabel,
  isAwaitingFinalApproval,
  type CheckoutSession,
  type LocalAutomationRun,
} from "../lib/purchase-automation.ts";

const checkoutSession: CheckoutSession = {
  id: "checkout-1",
  seller_code: "crazy11",
  automation_mode: "local_agent_browser",
  approval_boundary: "before_payment_submit",
  product: {
    name: "머큐리얼 베이퍼 16",
    size: "270",
    price: "109,000원",
    quantity: 1,
  },
  shipping_info: {
    recipient_name: "홍길동",
    phone: "010-1234-5678",
    address: "서울시 강남구 테헤란로 1",
    detail_address: "101동 202호",
  },
};

function run() {
  assert.equal(canStartAutomation("ready_for_checkout", checkoutSession), true);
  assert.equal(canStartAutomation("awaiting_purchase_info", checkoutSession), false);
  assert.equal(
    canStartAutomation("ready_for_checkout", {
      ...checkoutSession,
      automation_mode: "manual",
    }),
    false,
  );

  const runState: LocalAutomationRun = {
    id: "run-1",
    status: "awaiting_final_approval",
  };
  assert.equal(isAwaitingFinalApproval(runState), true);
  assert.equal(isAwaitingFinalApproval({ ...runState, status: "submitted" }), false);

  assert.equal(getRunStatusLabel("running"), "자동 주문 준비 중");
  assert.equal(getRunStatusLabel("awaiting_final_approval"), "최종 승인 대기");
  assert.equal(getRunStatusLabel("needs_manual_intervention"), "수동 확인 필요");
}

run();
