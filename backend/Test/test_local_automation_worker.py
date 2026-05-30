import os
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from AutomationWorker.models import CheckoutSessionPayload
from AutomationWorker.service import (
    AutomationCommandRunner,
    CheckoutAutomationDriver,
    FinalizationResult,
    LocalAutomationService,
    PreparationResult,
)


def _sample_checkout_session() -> CheckoutSessionPayload:
    return CheckoutSessionPayload.model_validate(
        {
            "id": "checkout-1",
            "type": "checkout_session",
            "seller": "크레이지11",
            "seller_code": "crazy11",
            "automation_mode": "local_agent_browser",
            "approval_boundary": "before_payment_submit",
            "supported": True,
            "status": "ready_for_checkout",
            "session_id": "session-1",
            "user_id": "user-1",
            "created_at": "2026-04-25T00:00:00Z",
            "stop_before_payment": True,
            "flow": [
                "open_product_detail",
                "verify_product",
                "select_size_option",
                "confirm_quantity",
                "move_to_cart_or_order",
                "fill_shipping_info",
                "stop_before_payment",
            ],
            "product": {
                "product_key": "product-1",
                "name": "머큐리얼 베이퍼 16",
                "product_url": "https://www.crazy11.co.kr/shop/shopdetail.html?branduid=123",
                "price": "109,000원",
                "size": "270",
                "available_size": ["260", "265", "270"],
                "quantity": 1,
                "image": "https://www.crazy11.co.kr/image.png",
            },
            "shipping_info": {
                "recipient_name": "홍길동",
                "phone": "010-1234-5678",
                "address": "서울시 강남구 테헤란로 1",
                "detail_address": "101동 202호",
            },
        }
    )


class MissingRunner(AutomationCommandRunner):
    def is_available(self) -> bool:
        return False


class AvailableRunner(AutomationCommandRunner):
    def is_available(self) -> bool:
        return True


class FakeDriver(CheckoutAutomationDriver):
    async def prepare_until_approval(self, checkout_session, run_id):
        return PreparationResult(
            summary={
                "product_name": checkout_session.product.name,
                "size": checkout_session.product.size,
                "price": checkout_session.product.price,
                "recipient_name": checkout_session.shipping_info.recipient_name,
            },
            screenshot_path=Path(tempfile.gettempdir()) / f"{run_id}.png",
            detected_total="109,000원",
        )

    async def finalize_purchase(self, checkout_session, run_id):
        return FinalizationResult(
            confirmation_message=f"{checkout_session.product.name} 주문 제출 완료",
        )


class LocalAutomationServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_session_fails_when_agent_browser_is_missing(self):
        service = LocalAutomationService(
            runner=MissingRunner(),
            driver_registry={},
            artifacts_dir=Path(tempfile.mkdtemp()),
        )

        run = await service.start_session(_sample_checkout_session())

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "agent_browser_not_installed")
        self.assertIn("agent-browser", run.error_message)

    async def test_session_moves_to_approval_and_submitted_states(self):
        service = LocalAutomationService(
            runner=AvailableRunner(),
            driver_registry={"crazy11": FakeDriver()},
            artifacts_dir=Path(tempfile.mkdtemp()),
        )

        run = await service.start_session(_sample_checkout_session())

        self.assertEqual(run.status, "awaiting_final_approval")
        self.assertEqual(run.summary["product_name"], "머큐리얼 베이퍼 16")
        self.assertTrue(run.screenshot_url.endswith(".png"))

        approved = await service.approve_run(run.id)

        self.assertEqual(approved.status, "submitted")
        self.assertIn("주문 제출 완료", approved.confirmation_message)

    async def test_cancel_marks_run_cancelled(self):
        service = LocalAutomationService(
            runner=AvailableRunner(),
            driver_registry={"crazy11": FakeDriver()},
            artifacts_dir=Path(tempfile.mkdtemp()),
        )

        run = await service.start_session(_sample_checkout_session())
        cancelled = await service.cancel_run(run.id)

        self.assertEqual(cancelled.status, "cancelled")


if __name__ == "__main__":
    unittest.main()
