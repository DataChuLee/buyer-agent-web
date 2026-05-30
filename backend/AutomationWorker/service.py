from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from AutomationWorker.models import AutomationRun, CheckoutSessionPayload


class AutomationServiceError(Exception):
    error_code = "automation_service_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ManualInterventionRequired(AutomationServiceError):
    error_code = "manual_intervention_required"


class InvalidAutomationRequest(AutomationServiceError):
    error_code = "invalid_automation_request"


@dataclass(frozen=True)
class PreparationResult:
    summary: dict[str, Any]
    screenshot_path: Path | None = None
    detected_total: str | None = None


@dataclass(frozen=True)
class FinalizationResult:
    confirmation_message: str


class AutomationCommandRunner(ABC):
    def __init__(self, *, profile_name: str | None = None):
        self.profile_name = profile_name or os.getenv("LOCAL_AUTOMATION_BROWSER_PROFILE", "Default")

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    def close(self, session_id: str) -> None:
        return None


class AgentBrowserCommandRunner(AutomationCommandRunner):
    def __init__(
        self,
        *,
        executable: str = "agent-browser",
        profile_name: str | None = None,
        timeout_seconds: int = 30,
    ):
        super().__init__(profile_name=profile_name)
        self.executable = executable
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None

    def run(
        self,
        session_id: str,
        args: list[str],
        *,
        expect_json: bool = False,
        timeout_seconds: int | None = None,
    ) -> Any:
        command = [self.executable, "--session", session_id]
        if self.profile_name:
            command.extend(["--profile", self.profile_name])
        command.extend(args)
        if expect_json:
            command.append("--json")

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds or self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "agent-browser command failed"
            raise AutomationServiceError(message)
        if expect_json:
            return json.loads(completed.stdout or "{}")
        return completed.stdout

    def close(self, session_id: str) -> None:
        if not self.is_available():
            return
        subprocess.run(
            [self.executable, "--session", session_id, "close"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )


class CheckoutAutomationDriver(ABC):
    @abstractmethod
    async def prepare_until_approval(
        self,
        checkout_session: CheckoutSessionPayload,
        run_id: str,
    ) -> PreparationResult:
        raise NotImplementedError

    @abstractmethod
    async def finalize_purchase(
        self,
        checkout_session: CheckoutSessionPayload,
        run_id: str,
    ) -> FinalizationResult:
        raise NotImplementedError


class Crazy11AgentBrowserDriver(CheckoutAutomationDriver):
    LOGIN_KEYWORDS = ("로그인", "아이디", "비밀번호", "login", "password")
    FINAL_APPROVAL_BUTTONS = ("결제하기", "주문하기", "최종 결제", "구매하기")
    MOVE_TO_ORDER_BUTTONS = ("바로구매", "주문하기", "구매하기", "장바구니")
    RECIPIENT_LABELS = ("받는 분", "받는분", "수령인", "이름")
    PHONE_LABELS = ("휴대폰", "연락처", "전화번호", "핸드폰")
    ADDRESS_LABELS = ("주소", "배송지 주소")
    DETAIL_ADDRESS_LABELS = ("상세주소", "나머지 주소", "상세 주소")

    def __init__(self, runner: AgentBrowserCommandRunner, artifacts_dir: Path):
        self.runner = runner
        self.artifacts_dir = artifacts_dir

    async def prepare_until_approval(
        self,
        checkout_session: CheckoutSessionPayload,
        run_id: str,
    ) -> PreparationResult:
        self.runner.run(run_id, ["open", checkout_session.product.product_url])
        self.runner.run(run_id, ["wait", "--load", "networkidle"])

        snapshot = self._snapshot_text(run_id)
        if self._requires_login(snapshot):
            raise ManualInterventionRequired("로그인이 필요합니다. 로그인 완료 후 다시 시도하세요.")

        self._select_size(run_id, checkout_session.product.size)
        self._confirm_quantity(run_id, checkout_session.product.quantity)
        self._move_to_order_page(run_id)

        post_navigation_snapshot = self._snapshot_text(run_id)
        if self._requires_login(post_navigation_snapshot):
            raise ManualInterventionRequired("주문 단계에서 로그인이 필요합니다.")

        self._fill_shipping(run_id, checkout_session)

        run_artifact_dir = self.artifacts_dir / run_id
        run_artifact_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = run_artifact_dir / "approval-review.png"
        self.runner.run(run_id, ["screenshot", str(screenshot_path)])

        detected_total = self._extract_total(post_navigation_snapshot) or checkout_session.product.price
        summary = {
            "product_name": checkout_session.product.name,
            "size": checkout_session.product.size,
            "price": checkout_session.product.price,
            "quantity": checkout_session.product.quantity,
            "recipient_name": checkout_session.shipping_info.recipient_name,
            "phone": checkout_session.shipping_info.phone,
            "address": checkout_session.shipping_info.address,
            "detail_address": checkout_session.shipping_info.detail_address,
            "detected_total": detected_total,
        }
        return PreparationResult(
            summary=summary,
            screenshot_path=screenshot_path,
            detected_total=detected_total,
        )

    async def finalize_purchase(
        self,
        checkout_session: CheckoutSessionPayload,
        run_id: str,
    ) -> FinalizationResult:
        self._click_by_text(run_id, self.FINAL_APPROVAL_BUTTONS)
        self.runner.run(run_id, ["wait", "1500"])
        return FinalizationResult(
            confirmation_message=f"{checkout_session.product.name} 주문 제출을 시도했습니다.",
        )

    def _snapshot_text(self, run_id: str) -> str:
        response = self.runner.run(run_id, ["snapshot", "-i"], expect_json=True)
        snapshot = response.get("data", {}).get("snapshot")
        if not snapshot:
            raise AutomationServiceError("페이지 스냅샷을 가져오지 못했습니다.")
        return str(snapshot)

    def _requires_login(self, snapshot: str) -> bool:
        normalized = snapshot.lower()
        return any(keyword.lower() in normalized for keyword in self.LOGIN_KEYWORDS)

    def _select_size(self, run_id: str, size: str | None) -> None:
        if not size:
            return
        attempts = [
            ["find", "text", size, "click"],
            ["select", "select[name*='option']", size],
            ["select", "select[id*='option']", size],
            ["click", f"text={size}"],
        ]
        self._run_first_successful(run_id, attempts, f"사이즈 {size} 선택에 실패했습니다.")

    def _confirm_quantity(self, run_id: str, quantity: int) -> None:
        if quantity <= 1:
            return
        value = str(quantity)
        attempts = [
            ["fill", "input[name*='qty']", value],
            ["fill", "input[id*='qty']", value],
            ["fill", "input[name*='quantity']", value],
        ]
        self._run_first_successful(run_id, attempts, "수량 입력에 실패했습니다.")

    def _move_to_order_page(self, run_id: str) -> None:
        self._click_by_text(run_id, self.MOVE_TO_ORDER_BUTTONS)
        self.runner.run(run_id, ["wait", "--load", "networkidle"])

    def _fill_shipping(self, run_id: str, checkout_session: CheckoutSessionPayload) -> None:
        self._fill_by_labels(run_id, self.RECIPIENT_LABELS, checkout_session.shipping_info.recipient_name)
        self._fill_by_labels(run_id, self.PHONE_LABELS, checkout_session.shipping_info.phone)
        self._fill_by_labels(run_id, self.ADDRESS_LABELS, checkout_session.shipping_info.address)
        self._fill_by_labels(
            run_id,
            self.DETAIL_ADDRESS_LABELS,
            checkout_session.shipping_info.detail_address,
        )

    def _fill_by_labels(self, run_id: str, labels: tuple[str, ...], value: str) -> None:
        attempts = [["find", "label", label, "fill", value] for label in labels]
        self._run_first_successful(run_id, attempts, f"{labels[0]} 입력에 실패했습니다.")

    def _click_by_text(self, run_id: str, names: tuple[str, ...]) -> None:
        attempts = []
        for name in names:
            attempts.append(["find", "role", "button", "click", "--name", name])
            attempts.append(["find", "text", name, "click"])
        self._run_first_successful(run_id, attempts, f"{names[0]} 동작에 실패했습니다.")

    def _run_first_successful(
        self,
        run_id: str,
        attempts: list[list[str]],
        error_message: str,
    ) -> None:
        last_error: Exception | None = None
        for command in attempts:
            try:
                self.runner.run(run_id, command)
                return
            except Exception as exc:  # pragma: no cover - command-specific fallback
                last_error = exc
        if last_error:
            raise ManualInterventionRequired(f"{error_message} {last_error}")
        raise ManualInterventionRequired(error_message)

    def _extract_total(self, snapshot: str) -> str | None:
        matches = re.findall(r"([0-9][0-9,]{2,}\s*원)", snapshot)
        return matches[-1] if matches else None


class LocalAutomationService:
    def __init__(
        self,
        *,
        runner: AutomationCommandRunner | None = None,
        driver_registry: dict[str, CheckoutAutomationDriver] | None = None,
        artifacts_dir: Path | None = None,
        public_base_url: str | None = None,
    ):
        self.artifacts_dir = artifacts_dir or (Path(tempfile.gettempdir()) / "buyer-agent-automation")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.public_base_url = (
            public_base_url
            or os.getenv("LOCAL_AUTOMATION_PUBLIC_BASE_URL")
            or "http://127.0.0.1:8123"
        ).rstrip("/")
        self.runner = runner or AgentBrowserCommandRunner()
        self.driver_registry = driver_registry or self._build_default_registry(self.runner)
        self.runs: dict[str, AutomationRun] = {}
        self.checkout_sessions: dict[str, CheckoutSessionPayload] = {}

    def _build_default_registry(
        self,
        runner: AutomationCommandRunner,
    ) -> dict[str, CheckoutAutomationDriver]:
        if isinstance(runner, AgentBrowserCommandRunner):
            return {
                "crazy11": Crazy11AgentBrowserDriver(runner, self.artifacts_dir),
            }
        return {}

    def get_run(self, run_id: str) -> AutomationRun:
        run = self.runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    async def start_session(self, checkout_session: CheckoutSessionPayload) -> AutomationRun:
        run = AutomationRun(
            id=str(uuid4()),
            checkout_session_id=checkout_session.id,
            seller_code=checkout_session.seller_code,
            approval_boundary=checkout_session.approval_boundary,
            status="running",
            created_at=self._now(),
            updated_at=self._now(),
        )
        self.runs[run.id] = run
        self.checkout_sessions[run.id] = checkout_session

        if checkout_session.automation_mode != "local_agent_browser":
            return self._fail_run(run.id, "unsupported_automation_mode", "지원하지 않는 자동화 방식입니다.")
        if checkout_session.approval_boundary != "before_payment_submit":
            return self._fail_run(run.id, "unsupported_approval_boundary", "지원하지 않는 승인 경계입니다.")
        if not self.runner.is_available():
            return self._fail_run(
                run.id,
                "agent_browser_not_installed",
                "agent-browser CLI가 설치되어 있지 않습니다. `npm install -g agent-browser && agent-browser install` 후 다시 시도하세요.",
            )

        driver = self.driver_registry.get(checkout_session.seller_code)
        if driver is None:
            return self._fail_run(run.id, "unsupported_seller", f"{checkout_session.seller_code} 판매처는 아직 지원하지 않습니다.")

        try:
            prepared = await driver.prepare_until_approval(checkout_session, run.id)
        except ManualInterventionRequired as exc:
            return self._set_run(
                run.id,
                status="needs_manual_intervention",
                error_code=exc.error_code,
                error_message=exc.message,
            )
        except AutomationServiceError as exc:
            return self._fail_run(run.id, exc.error_code, exc.message)
        except Exception as exc:  # pragma: no cover - defensive guard
            return self._fail_run(run.id, "unexpected_error", str(exc))

        screenshot_url = None
        if prepared.screenshot_path:
            screenshot_url = f"{self.public_base_url}/sessions/{run.id}/artifacts/{prepared.screenshot_path.name}"

        return self._set_run(
            run.id,
            status="awaiting_final_approval",
            summary=prepared.summary,
            detected_total=prepared.detected_total,
            screenshot_url=screenshot_url,
            artifact_path=prepared.screenshot_path,
            error_code=None,
            error_message=None,
        )

    async def approve_run(self, run_id: str) -> AutomationRun:
        run = self.get_run(run_id)
        if run.status != "awaiting_final_approval":
            raise InvalidAutomationRequest("최종 승인 대기 상태에서만 승인할 수 있습니다.")

        checkout_session = self.checkout_sessions[run_id]
        driver = self.driver_registry.get(run.seller_code)
        if driver is None:
            return self._fail_run(run.id, "unsupported_seller", f"{run.seller_code} 판매처는 아직 지원하지 않습니다.")

        try:
            finalized = await driver.finalize_purchase(checkout_session, run.id)
        except ManualInterventionRequired as exc:
            return self._set_run(
                run.id,
                status="needs_manual_intervention",
                error_code=exc.error_code,
                error_message=exc.message,
            )
        except AutomationServiceError as exc:
            return self._fail_run(run.id, exc.error_code, exc.message)
        finally:
            self.runner.close(run.id)

        return self._set_run(
            run.id,
            status="submitted",
            confirmation_message=finalized.confirmation_message,
        )

    async def cancel_run(self, run_id: str) -> AutomationRun:
        run = self.get_run(run_id)
        if run.status in {"submitted", "cancelled", "failed"}:
            return run
        self.runner.close(run.id)
        return self._set_run(run.id, status="cancelled")

    def _fail_run(self, run_id: str, error_code: str, error_message: str) -> AutomationRun:
        return self._set_run(
            run_id,
            status="failed",
            error_code=error_code,
            error_message=error_message,
        )

    def _set_run(self, run_id: str, **updates: Any) -> AutomationRun:
        current = self.get_run(run_id)
        next_run = current.model_copy(
            update={
                **updates,
                "updated_at": self._now(),
            }
        )
        self.runs[run_id] = next_run
        return next_run

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

