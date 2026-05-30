from __future__ import annotations

from dataclasses import dataclass

from Tools.seller_normalization import normalize_seller_crawler, normalize_seller_display


@dataclass(frozen=True)
class CheckoutFlowDefinition:
    seller: str
    seller_code: str
    supported: bool
    flow: list[str]
    stop_before_payment: bool = True


class CheckoutAdapter:
    flow_definition: CheckoutFlowDefinition

    def build_checkout_session(
        self,
        *,
        selected_product: dict,
        shipping_info: dict,
        session_id: str,
        user_id: str,
        session_token: str,
        created_at: str,
    ) -> dict:
        return {
            "id": session_token,
            "type": "checkout_session",
            "seller": self.flow_definition.seller,
            "seller_code": self.flow_definition.seller_code,
            "automation_mode": "local_agent_browser",
            "approval_boundary": "before_payment_submit",
            "supported": self.flow_definition.supported,
            "status": "ready_for_checkout",
            "session_id": session_id,
            "user_id": user_id,
            "created_at": created_at,
            "stop_before_payment": self.flow_definition.stop_before_payment,
            "flow": self.flow_definition.flow,
            "product": {
                "product_key": selected_product.get("product_key"),
                "name": selected_product.get("name"),
                "product_url": selected_product.get("product_url"),
                "price": selected_product.get("price"),
                "size": selected_product.get("selected_size"),
                "available_size": selected_product.get("available_size"),
                "quantity": selected_product.get("quantity", 1),
                "image": selected_product.get("image"),
            },
            "shipping_info": {
                "recipient_name": shipping_info.get("recipient_name"),
                "phone": shipping_info.get("phone"),
                "address": shipping_info.get("address"),
                "detail_address": shipping_info.get("detail_address"),
            },
        }


class Crazy11CheckoutAdapter(CheckoutAdapter):
    flow_definition = CheckoutFlowDefinition(
        seller="크레이지11",
        seller_code="crazy11",
        supported=True,
        flow=[
            "open_product_detail",
            "verify_product",
            "select_size_option",
            "confirm_quantity",
            "move_to_cart_or_order",
            "fill_shipping_info",
            "stop_before_payment",
        ],
    )


SUPPORTED_CHECKOUT_SELLERS = {"크레이지11"}


def get_checkout_adapter(seller: str) -> CheckoutAdapter:
    display = normalize_seller_display(seller)
    seller_code = normalize_seller_crawler(display)
    if seller_code == "crazy11":
        return Crazy11CheckoutAdapter()
    raise ValueError(f"Unsupported checkout seller: {seller}")


def build_checkout_session_payload(
    *,
    adapter: CheckoutAdapter,
    selected_product: dict,
    shipping_info: dict,
    session_id: str,
    user_id: str,
    session_token: str,
    created_at: str,
) -> dict:
    return adapter.build_checkout_session(
        selected_product=selected_product,
        shipping_info=shipping_info,
        session_id=session_id,
        user_id=user_id,
        session_token=session_token,
        created_at=created_at,
    )
