from __future__ import annotations

from typing import Any


def lookup_order_details(ticket_id: str) -> dict[str, Any]:
    return {
        "ticket_id": ticket_id,
        "order_status": "pending_review",
        "source": "sandbox-order-service",
    }


def lookup_ticket_queue(ticket: dict[str, Any]) -> dict[str, Any]:
    expense_type = str(ticket.get("expense_type", "")).lower()
    city = str(ticket.get("city", ""))
    amount = float(ticket.get("amount", 0))

    if expense_type == "hotel" and amount > 1000:
        return {
            "queue_name": "finance-review",
            "reason": f"{city}酒店费用超出酒店标准，需财务复核。",
        }

    if amount > 5000:
        return {
            "queue_name": "senior-approval",
            "reason": "金额超过高额审批阈值，需高级审批。",
        }

    return {
        "queue_name": "ops-review",
        "reason": "命中常规人工复核队列。",
    }
