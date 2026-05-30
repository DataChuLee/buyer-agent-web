from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RunStatus = Literal[
    "running",
    "awaiting_final_approval",
    "submitted",
    "cancelled",
    "failed",
    "needs_manual_intervention",
]


class CheckoutProduct(BaseModel):
    product_key: str | None = None
    name: str
    product_url: str
    price: str | None = None
    size: str | None = None
    available_size: list[str] | None = None
    quantity: int = 1
    image: str | None = None


class ShippingInfo(BaseModel):
    recipient_name: str
    phone: str
    address: str
    detail_address: str


class CheckoutSessionPayload(BaseModel):
    id: str
    type: str
    seller: str
    seller_code: str
    automation_mode: str
    approval_boundary: str
    supported: bool
    status: str
    session_id: str
    user_id: str
    created_at: str
    stop_before_payment: bool = True
    flow: list[str] = Field(default_factory=list)
    product: CheckoutProduct
    shipping_info: ShippingInfo


class AutomationRun(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    checkout_session_id: str
    seller_code: str
    approval_boundary: str
    status: RunStatus
    created_at: str
    updated_at: str
    summary: dict | None = None
    detected_total: str | None = None
    screenshot_url: str | None = None
    confirmation_message: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    artifact_path: Path | None = Field(default=None, exclude=True)

