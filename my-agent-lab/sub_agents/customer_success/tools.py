"""Customer Success tools — read customers and tickets from the Quill backend."""
from __future__ import annotations

from typing import Any

from google.adk.tools import FunctionTool

from tools.quill_api import as_items, quill_get


def list_customers() -> list[dict[str, Any]]:
    """List all customers with health score and headline account fields.

    Returns a list of customer objects. Use the customer ``id`` (or account_id)
    for ticket lookups. Flag any customer with health < 60 as at-risk. On error,
    returns a single-element list containing an ``error`` key.
    """
    payload = quill_get("/v1/customers")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def get_customer_tickets(account_id: str) -> list[dict[str, Any]]:
    """Get support tickets for one customer.

    Args:
        account_id: The customer / account ``id`` from ``list_customers``.

    Returns a list of ticket objects (priority like P1/P2/P3, status, subject).
    Surface any OPEN P1 or P2 tickets.
    """
    payload = quill_get(f"/v1/customers/{account_id}/tickets")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


def get_customer_notes(account_id: str) -> list[dict[str, Any]]:
    """Get account notes for one customer.

    Args:
        account_id: The customer / account ``id`` from ``list_customers``.
    """
    payload = quill_get(f"/v1/customers/{account_id}/notes")
    if isinstance(payload, dict) and payload.get("error"):
        return [payload]
    return as_items(payload)


list_customers_tool = FunctionTool(func=list_customers)
get_customer_tickets_tool = FunctionTool(func=get_customer_tickets)
get_customer_notes_tool = FunctionTool(func=get_customer_notes)

CUSTOMER_SUCCESS_TOOLS = [
    list_customers_tool,
    get_customer_tickets_tool,
    get_customer_notes_tool,
]
